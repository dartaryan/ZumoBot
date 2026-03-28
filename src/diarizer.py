"""Speaker diarization via pyannote-audio and transcript alignment."""

import os
import re
import subprocess
from pathlib import Path
from typing import Callable


HUGGINGFACE_TOKEN_VAR = "HUGGINGFACE_TOKEN"


def is_available() -> bool:
    """Check if pyannote.audio is installed."""
    try:
        import pyannote.audio  # noqa: F401
        return True
    except ImportError:
        return False


def _convert_to_wav(audio_path: Path, output_path: Path) -> Path:
    """Convert audio to 16kHz mono WAV for reliable pyannote processing."""
    subprocess.run(
        ["ffmpeg", "-i", str(audio_path), "-ar", "16000", "-ac", "1",
         str(output_path), "-y"],
        check=True, capture_output=True, text=True,
    )
    return output_path


def diarize(
    audio_path: str | Path,
    num_speakers: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Run speaker diarization on audio file.

    Returns list of segments: [{"start": float, "end": float, "speaker": str}, ...]
    Requires pyannote.audio and HUGGINGFACE_TOKEN env var.
    """
    import torch

    # PyTorch 2.6+ defaults weights_only=True, but pyannote 3.x models
    # use unpickling. Patch torch.load BEFORE importing pyannote so all
    # internal references use the patched version.
    _original_torch_load = torch.load
    torch.load = lambda *a, **kw: _original_torch_load(*a, **{**kw, "weights_only": False})

    from pyannote.audio import Pipeline

    token = os.getenv(HUGGINGFACE_TOKEN_VAR, "")
    if not token:
        torch.load = _original_torch_load
        raise RuntimeError(
            f"Missing {HUGGINGFACE_TOKEN_VAR} environment variable.\n"
            "Get a token at https://huggingface.co/settings/tokens\n"
            "and accept pyannote model terms at "
            "https://huggingface.co/pyannote/speaker-diarization-3.1"
        )

    # Set HF_TOKEN so huggingface_hub auto-detects it (avoids deprecated use_auth_token)
    os.environ["HF_TOKEN"] = token

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    audio_path = Path(audio_path)

    # Convert to WAV for maximum compatibility
    wav_path = audio_path.parent / "diarize_input.wav"
    _progress("Converting to WAV for diarization...")
    _convert_to_wav(audio_path, wav_path)

    _progress("Loading pyannote pipeline...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pipeline.to(device)

    _progress(f"Running diarization on {device}...")

    kwargs = {}
    if num_speakers and num_speakers > 1:
        kwargs["num_speakers"] = num_speakers

    diarization = pipeline(str(wav_path), **kwargs)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker,
        })

    # Clean up temp WAV
    wav_path.unlink(missing_ok=True)

    unique = set(s["speaker"] for s in segments)
    _progress(f"Found {len(unique)} speaker(s) in {len(segments)} segment(s).")
    return segments


def merge_segments(
    segments: list[dict], gap_threshold: float = 1.5,
) -> list[dict]:
    """Merge consecutive segments from the same speaker if gap < threshold."""
    if not segments:
        return []

    merged = [segments[0].copy()]
    for seg in segments[1:]:
        prev = merged[-1]
        if (seg["speaker"] == prev["speaker"]
                and (seg["start"] - prev["end"]) < gap_threshold):
            prev["end"] = seg["end"]
        else:
            merged.append(seg.copy())

    return merged


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for alignment.
    Keeps punctuation with the sentence. Handles Hebrew and English.
    """
    parts = re.split(r'(?<=[.?!\u3002\n])\s*', text)
    return [p for p in parts if p.strip()]


def _majority_speaker(
    start_time: float,
    end_time: float,
    segments: list[dict],
) -> str:
    """Find which speaker has the most overlap with a time window."""
    durations: dict[str, float] = {}
    for seg in segments:
        overlap_start = max(start_time, seg["start"])
        overlap_end = min(end_time, seg["end"])
        if overlap_start < overlap_end:
            d = overlap_end - overlap_start
            durations[seg["speaker"]] = durations.get(seg["speaker"], 0) + d

    if not durations:
        return segments[0]["speaker"] if segments else "UNKNOWN"

    return max(durations, key=durations.get)


def _build_speaker_map(
    segments: list[dict],
    speaker_names: list[str] | None = None,
) -> dict[str, str]:
    """Map pyannote speaker IDs to display names.

    Uses speaker_names in order of first appearance if provided,
    otherwise falls back to 'דובר 1', 'דובר 2', etc.
    """
    # Collect unique speakers in order of first appearance
    unique = []
    seen = set()
    for seg in segments:
        if seg["speaker"] not in seen:
            unique.append(seg["speaker"])
            seen.add(seg["speaker"])

    mapping = {}
    for i, speaker_id in enumerate(unique):
        if speaker_names and i < len(speaker_names):
            mapping[speaker_id] = speaker_names[i].strip()
        else:
            mapping[speaker_id] = f"דובר {i + 1}"

    return mapping


def align_transcript(
    transcript: str,
    segments: list[dict],
    audio_duration: float,
    speaker_names: list[str] | None = None,
) -> str:
    """Align plain transcript with speaker diarization segments.

    Strategy:
    1. Split transcript into sentences
    2. Map each sentence to a proportional time window (chars -> seconds)
    3. Assign speaker by majority overlap with diarization segments
    4. Group consecutive sentences from the same speaker into paragraphs

    This is an approximation — accurate to ~sentence level, not word level.
    """
    if not segments or not transcript.strip():
        return transcript

    merged = merge_segments(segments)
    speaker_map = _build_speaker_map(merged, speaker_names)

    sentences = _split_sentences(transcript)
    if not sentences:
        return transcript

    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0 or audio_duration <= 0:
        return transcript

    # Assign a speaker to each sentence based on proportional time mapping
    chars_done = 0
    labeled: list[tuple[str, str]] = []  # (display_name, sentence_text)

    for sentence in sentences:
        start_frac = chars_done / total_chars
        end_frac = (chars_done + len(sentence)) / total_chars
        start_t = start_frac * audio_duration
        end_t = end_frac * audio_duration

        speaker_id = _majority_speaker(start_t, end_t, merged)
        display = speaker_map.get(speaker_id, speaker_id)
        labeled.append((display, sentence))
        chars_done += len(sentence)

    # Group consecutive sentences from the same speaker
    parts: list[str] = []
    current_speaker = None
    current_text: list[str] = []

    for speaker, text in labeled:
        if speaker != current_speaker:
            if current_text:
                joined = " ".join(current_text).strip()
                parts.append(f"**{current_speaker}:** {joined}")
            current_speaker = speaker
            current_text = [text]
        else:
            current_text.append(text)

    if current_text:
        joined = " ".join(current_text).strip()
        parts.append(f"**{current_speaker}:** {joined}")

    return "\n\n".join(parts)
