"""
Zoom Transcription Pipeline
============================
Local tool for transcribing Zoom recordings via Hebrew AI.

Flow: Upload video/audio → Extract audio → Remove silence (>30s) → 
      Transcribe via Hebrew AI → Summarize via Claude → Save .md → Cleanup
"""

import gradio as gr
import subprocess
import requests
import os
import sys
import time
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from anthropic import Anthropic

# ─── Config ───────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path.home() / "zoom-transcriptions"
INDEX_FILE = OUTPUT_DIR / "index.md"

SILENCE_THRESHOLD_DB = -30
SILENCE_MIN_DURATION = 30  # seconds

POLL_INTERVAL = 5  # seconds between status checks
POLL_TIMEOUT = 1800  # 30 minutes max wait


# ─── Audio Processing ─────────────────────────────────────────────────────────

def get_duration(file_path: str) -> float:
    """Get audio/video duration in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", file_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio track from video as MP3."""
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vn", "-acodec", "libmp3lame",
         "-q:a", "2", output_path, "-y"],
        check=True, capture_output=True, text=True
    )
    return output_path


def is_audio_file(file_path: str) -> bool:
    """Check if the file is already an audio file."""
    audio_extensions = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}
    return Path(file_path).suffix.lower() in audio_extensions


def detect_silence(audio_path: str, threshold_db: float, min_duration: float) -> list:
    """Detect silent segments longer than min_duration using ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-i", audio_path,
         "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
         "-f", "null", "-"],
        capture_output=True, text=True
    )

    silences = []
    current_start = None

    for line in result.stderr.split("\n"):
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[1].strip().split()[0])
            except (IndexError, ValueError):
                current_start = None
        elif "silence_end:" in line and current_start is not None:
            try:
                end = float(line.split("silence_end:")[1].strip().split()[0])
                silences.append((current_start, end))
            except (IndexError, ValueError):
                pass
            current_start = None

    return silences


def remove_silence(audio_path: str, silences: list, output_path: str) -> tuple:
    """Remove silent segments and concatenate non-silent parts. Returns (output_path, removed_seconds)."""
    if not silences:
        shutil.copy2(audio_path, output_path)
        return output_path, 0.0

    total_duration = get_duration(audio_path)

    # Calculate non-silent segments
    segments = []
    prev_end = 0.0
    for start, end in sorted(silences):
        if start > prev_end + 0.1:  # keep segments > 100ms
            segments.append((prev_end, start))
        prev_end = end
    if prev_end < total_duration - 0.1:
        segments.append((prev_end, total_duration))

    if not segments:
        shutil.copy2(audio_path, output_path)
        return output_path, 0.0

    # Build ffmpeg filter_complex
    filter_parts = []
    for i, (start, end) in enumerate(segments):
        filter_parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )

    concat_inputs = "".join(f"[a{i}]" for i in range(len(segments)))
    filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=0:a=1[out]")
    filter_complex = ";".join(filter_parts)

    subprocess.run(
        ["ffmpeg", "-i", audio_path,
         "-filter_complex", filter_complex,
         "-map", "[out]",
         output_path, "-y"],
        check=True, capture_output=True, text=True
    )

    removed = sum(end - start for start, end in silences)
    return output_path, removed


# ─── Hebrew AI Integration ────────────────────────────────────────────────────

def transcribe(audio_path: str, api_key: str, language: str = "he") -> tuple:
    """Send audio to Hebrew AI, poll for result. Returns (text, duration)."""
    headers = {"Authorization": f"Bearer {api_key}"}

    # Submit
    with open(audio_path, "rb") as f:
        resp = requests.post(
            "https://hebrew-ai.com/api/transcribe",
            headers=headers,
            files={"file": ("audio.mp3", f, "audio/mpeg")},
            data={"language": language}
        )

    data = resp.json()
    if not data.get("success"):
        raise Exception(f"Hebrew AI error: {data.get('error', 'Unknown error')}")

    transcription_id = data["transcription_id"]

    # Poll
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        resp = requests.get(
            f"https://hebrew-ai.com/api/transcribe?id={transcription_id}",
            headers=headers
        )
        result = resp.json()
        status = result.get("status")

        if status == "COMPLETED":
            return result.get("text", ""), result.get("duration", 0)
        elif status == "FAILED":
            raise Exception("Hebrew AI transcription failed")

    raise Exception(f"Transcription timed out after {POLL_TIMEOUT}s")


# ─── Claude Summary ───────────────────────────────────────────────────────────

def generate_summary(text: str, api_key: str) -> str:
    """Generate a one-line Hebrew summary using Claude Haiku."""
    if not api_key:
        return "—"

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": (
                "סכם את התמלול הבא במשפט אחד קצר בעברית (עד 15 מילים). "
                "רק הסיכום, בלי שום דבר אחר:\n\n"
                f"{text[:4000]}"
            )
        }]
    )
    return response.content[0].text.strip()


# ─── Output ───────────────────────────────────────────────────────────────────

def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    seconds = int(seconds)
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def save_transcription(
    text: str,
    original_name: str,
    original_duration: float,
    trimmed_duration: float,
    silence_removed: float,
    timestamp: str,
) -> Path:
    """Save transcription as .md file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in original_name)
    filename = f"{timestamp}_{safe_name}.md"
    filepath = OUTPUT_DIR / filename

    content = f"""# {original_name}

| Field | Value |
|-------|-------|
| **Date** | {timestamp.replace('_', ' ').replace('-', '/', 2)} |
| **Original Duration** | {format_duration(original_duration)} |
| **Trimmed Duration** | {format_duration(trimmed_duration)} |
| **Silence Removed** | {format_duration(silence_removed)} |

---

{text}
"""

    filepath.write_text(content, encoding="utf-8")
    return filepath


def update_index(
    original_name: str,
    original_duration: float,
    trimmed_duration: float,
    summary: str,
    transcript_filename: str,
    timestamp: str,
):
    """Append entry to index.md."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Create index with header if it doesn't exist
    if not INDEX_FILE.exists():
        header = """# Transcription Index

| Date | File | Original | Trimmed | Summary | Link |
|------|------|----------|---------|---------|------|
"""
        INDEX_FILE.write_text(header, encoding="utf-8")

    date_str = timestamp.split("_")[0]
    row = (
        f"| {date_str} "
        f"| {original_name} "
        f"| {format_duration(original_duration)} "
        f"| {format_duration(trimmed_duration)} "
        f"| {summary} "
        f"| [{transcript_filename}](./{transcript_filename}) |\n"
    )

    with open(INDEX_FILE, "a", encoding="utf-8") as f:
        f.write(row)


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def process(
    file_obj,
    language: str,
    hebrew_ai_key: str,
    anthropic_key: str,
    silence_threshold: int,
    delete_source: bool,
    progress=gr.Progress(track_tqdm=False),
):
    """Main processing pipeline."""
    if file_obj is None:
        return "❌ No file uploaded."

    file_path = file_obj if isinstance(file_obj, str) else file_obj.name
    original_name = Path(file_path).stem
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if not hebrew_ai_key:
        return "❌ Hebrew AI API key is required."

    log = []

    def status(msg):
        log.append(msg)
        return "\n".join(log)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            # Step 1: Extract audio
            progress(0.1, desc="Extracting audio...")
            status("🎬 Extracting audio...")

            if is_audio_file(file_path):
                audio_path = str(tmp / "original.mp3")
                shutil.copy2(file_path, audio_path)
                status("📁 Audio file detected, skipping extraction.")
            else:
                audio_path = str(tmp / "extracted.mp3")
                extract_audio(file_path, audio_path)
                status("✅ Audio extracted.")

            original_duration = get_duration(audio_path)
            status(f"⏱️ Original duration: {format_duration(original_duration)}")

            # Step 2: Silence removal
            progress(0.25, desc="Detecting silence...")
            status(f"🔇 Detecting silence (>{silence_threshold}s threshold)...")

            silences = detect_silence(audio_path, SILENCE_THRESHOLD_DB, silence_threshold)
            status(f"   Found {len(silences)} silent segment(s).")

            trimmed_path = str(tmp / "trimmed.mp3")
            _, silence_removed = remove_silence(audio_path, silences, trimmed_path)
            trimmed_duration = get_duration(trimmed_path)

            status(f"✂️ Removed {format_duration(silence_removed)} of silence.")
            status(f"⏱️ Trimmed duration: {format_duration(trimmed_duration)}")

            # Step 3: Transcribe
            progress(0.4, desc="Transcribing via Hebrew AI...")
            lang_code = "he" if language == "עברית" else "en"
            status(f"📝 Sending to Hebrew AI ({language})...")

            text, api_duration = transcribe(trimmed_path, hebrew_ai_key, lang_code)
            status(f"✅ Transcription complete ({len(text)} characters).")

            # Step 4: Summary
            progress(0.8, desc="Generating summary...")
            if anthropic_key:
                status("🤖 Generating summary via Claude...")
                summary = generate_summary(text, anthropic_key)
                status(f"📋 Summary: {summary}")
            else:
                summary = "—"
                status("⚠️ No Anthropic key — skipping summary.")

            # Step 5: Save output
            progress(0.9, desc="Saving...")
            md_path = save_transcription(
                text, original_name, original_duration,
                trimmed_duration, silence_removed, timestamp
            )
            status(f"💾 Saved: {md_path.name}")

            update_index(
                original_name, original_duration, trimmed_duration,
                summary, md_path.name, timestamp
            )
            status(f"📇 Index updated.")

        # Step 6: Cleanup (outside temp dir context — temp files auto-deleted)
        if delete_source and os.path.exists(file_path):
            os.remove(file_path)
            status(f"🗑️ Deleted source file: {Path(file_path).name}")

        progress(1.0, desc="Done!")
        status("")
        status(f"✅ Done! Output: {OUTPUT_DIR}")
        return "\n".join(log)

    except subprocess.CalledProcessError as e:
        return "\n".join(log) + f"\n\n❌ ffmpeg error: {e.stderr}"
    except Exception as e:
        return "\n".join(log) + f"\n\n❌ Error: {str(e)}"


# ─── Gradio UI ────────────────────────────────────────────────────────────────

def build_ui():
    with gr.Blocks(
        title="Zoom Transcriber",
        theme=gr.themes.Soft(),
    ) as app:
        gr.Markdown("# 🎙️ Zoom Transcriber\nUpload → Trim silence → Transcribe → Done.")

        with gr.Row():
            with gr.Column(scale=1):
                file_input = gr.File(
                    label="Upload Video / Audio",
                    file_types=[".mp4", ".mkv", ".avi", ".mov", ".webm",
                                ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"],
                )
                language = gr.Radio(
                    choices=["עברית", "English"],
                    value="עברית",
                    label="Language",
                )
                silence_threshold = gr.Slider(
                    minimum=5, maximum=120, value=30, step=5,
                    label="Silence threshold (seconds)",
                    info="Remove silent segments longer than this",
                )
                delete_source = gr.Checkbox(
                    value=True,
                    label="🗑️ Delete source file after transcription",
                )

                with gr.Accordion("API Keys", open=True):
                    hebrew_ai_key = gr.Textbox(
                        label="Hebrew AI API Key",
                        type="password",
                        placeholder="Bearer key from hebrew-ai.com/en/profile/apikeys",
                    )
                    anthropic_key = gr.Textbox(
                        label="Anthropic API Key (optional — for summary)",
                        type="password",
                        placeholder="sk-ant-...",
                    )

                btn = gr.Button("🚀 Transcribe", variant="primary", size="lg")

            with gr.Column(scale=1):
                output = gr.Textbox(
                    label="Status",
                    lines=22,
                    interactive=False,
                    show_copy_button=True,
                )

        btn.click(
            fn=process,
            inputs=[file_input, language, hebrew_ai_key, anthropic_key,
                    silence_threshold, delete_source],
            outputs=output,
        )

        gr.Markdown(
            f"**Output folder:** `{OUTPUT_DIR}`  \n"
            f"**Index file:** `{INDEX_FILE}`"
        )

    return app


if __name__ == "__main__":
    app = build_ui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
