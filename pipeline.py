"""Zumo — CLI entry point for the transcription pipeline."""

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile

# Fix Windows console encoding for Hebrew + emoji output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from datetime import datetime
from pathlib import Path

from src.config import (
    OUTPUT_DIR,
    SESSION_TYPES,
    SILENCE_THRESHOLD_DB,
    validate_config,
)
from src.users import load_user
from src.audio import (
    compress_audio,
    extract_audio,
    format_duration,
    get_duration,
    is_audio_file,
    detect_silence,
    remove_silence,
)
from src.transcriber import transcribe
from src.processor import analyze_transcript, generate_summary
from src.formatter import (
    format_analysis_md,
    format_transcript_md,
    generate_folder_name,
)
from src.downloader import download_zoom_recording, is_zoom_url
from src.diarizer import is_available as diarizer_available, diarize, align_transcript
from src.storage import (
    ensure_repo_structure,
    save_session,
    save_session_local,
)
from src.dashboard import save_dashboard


def process_file(
    file_path: Path,
    user,
    session_type: str,
    speakers: str,
    language: str,
    local_mode: bool,
    skip_analysis: bool,
    skip_diarization: bool = False,
) -> dict:
    """Main pipeline: audio -> transcribe -> analyze -> save."""

    result = {"status": "error", "error": None}
    timestamp = datetime.now()

    print(f"\n{'=' * 60}")
    print(f"Zumo Pipeline")
    print(f"  User:    {user.name}")
    print(f"  File:    {file_path.name}")
    print(f"  Type:    {session_type}")
    print(f"  Lang:    {language}")
    print(f"{'=' * 60}\n")

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            # --- Step 1: Audio extraction ---
            print("[1/8] Extracting audio...")
            if is_audio_file(file_path):
                audio_path = tmp / "original.mp3"
                shutil.copy2(str(file_path), str(audio_path))
                print("  Audio file detected, skipping extraction.")
            else:
                audio_path = tmp / "extracted.mp3"
                extract_audio(file_path, audio_path)
                print("  Audio extracted from video.")

            original_duration = get_duration(audio_path)
            print(f"  Original duration: {format_duration(original_duration)}")

            # --- Step 2: Silence removal ---
            print(f"\n[2/8] Detecting silence (>{user.silence_threshold_seconds}s)...")
            silences = detect_silence(
                audio_path, SILENCE_THRESHOLD_DB, user.silence_threshold_seconds,
            )
            print(f"  Found {len(silences)} silent segment(s).")

            trimmed_path = tmp / "trimmed.mp3"
            _, silence_removed = remove_silence(audio_path, silences, trimmed_path)
            trimmed_duration = get_duration(trimmed_path)
            print(f"  Removed {format_duration(silence_removed)} of silence.")
            print(f"  Trimmed duration: {format_duration(trimmed_duration)}")

            # --- Step 3: Speaker Diarization ---
            diarization_segments = None
            speaker_names = [s.strip() for s in speakers.split(",") if s.strip()] if speakers else []

            if skip_diarization:
                print("\n[3/8] Skipping speaker diarization (--skip-diarization).")
            elif not diarizer_available():
                print("\n[3/8] Skipping diarization (pyannote.audio not installed).")
                print("  Install: pip install pyannote.audio")
            else:
                try:
                    print("\n[3/8] Running speaker diarization...")
                    num_speakers = len(speaker_names) if speaker_names else None
                    diarization_segments = diarize(
                        trimmed_path,
                        num_speakers=num_speakers,
                        on_progress=lambda msg: print(f"  {msg}"),
                    )
                except Exception as e:
                    print(f"  Diarization failed, continuing without: {e}")
                    diarization_segments = None

            # --- Step 3.5: Compress if too large ---
            trimmed_size_mb = trimmed_path.stat().st_size / 1024 / 1024
            if trimmed_size_mb > 25:
                print(f"\n[3.5/8] Compressing audio ({trimmed_size_mb:.0f}MB > 25MB limit)...")
                upload_path = tmp / "compressed.mp3"
                compress_audio(trimmed_path, upload_path)
                compressed_size_mb = upload_path.stat().st_size / 1024 / 1024
                print(f"  Compressed: {trimmed_size_mb:.0f}MB -> {compressed_size_mb:.1f}MB")
            else:
                upload_path = trimmed_path

            # --- Step 4: Transcription ---
            if not user.hebrew_ai_api_key:
                raise ValueError("hebrew_ai_api_key is not configured. Check ZUMO_USER_HEBREW_AI_KEY env var.")
            print(f"\n[4/8] Transcribing via Hebrew AI ({language})...")
            text, api_duration = transcribe(
                upload_path,
                user.hebrew_ai_api_key,
                language,
                on_progress=lambda msg: print(f"  {msg}"),
            )
            print(f"  Transcription complete ({len(text)} characters).")

            # --- Step 5: Align speakers with transcript ---
            if diarization_segments:
                print("\n[5/8] Aligning speakers with transcript...")
                text = align_transcript(
                    text,
                    diarization_segments,
                    trimmed_duration,
                    speaker_names=speaker_names or None,
                )
                print(f"  Diarized transcript: {len(text)} characters.")
            else:
                print("\n[5/8] No diarization data, using raw transcript.")

            # --- Step 6: Summary ---
            print("\n[6/8] Generating summary...")
            summary = generate_summary(text, user.anthropic_api_key)
            print(f"  Summary: {summary}")

            # --- Step 7: Analysis ---
            if skip_analysis or not user.anthropic_api_key:
                print("\n[7/8] Skipping analysis.")
                analysis = None
            else:
                print("\n[7/8] Analyzing transcript via Claude...")
                analysis = analyze_transcript(
                    text, user.anthropic_api_key, session_type, speakers, language,
                )
                print(f"  Analysis complete ({len(analysis)} characters).")

            # --- Step 8: Format & Save ---
            print("\n[8/8] Saving...")
            folder_name = generate_folder_name(
                session_type, speakers or file_path.stem, timestamp,
            )

            transcript_md = format_transcript_md(
                text, file_path.stem, session_type, speakers, language,
                original_duration, trimmed_duration, silence_removed, timestamp,
            )

            analysis_md = None
            if analysis:
                analysis_md = format_analysis_md(
                    analysis, summary, session_type, speakers, timestamp,
                )

            if local_mode:
                local_path = save_session_local(
                    OUTPUT_DIR, user.dashboard_slug, folder_name,
                    transcript_md, analysis_md,
                )
                print(f"  Saved locally: {local_path}")
                result["local_path"] = str(local_path)

                # Regenerate dashboard HTML
                dash_path = save_dashboard(
                    user.dashboard_slug, user.name, user.web_password_hash,
                )
                print(f"  Dashboard: {dash_path}")
            else:
                ensure_repo_structure(user.dashboard_slug)
                dashboard_url = save_session(
                    user.dashboard_slug, folder_name,
                    transcript_md, analysis_md, summary,
                    user_name=user.name,
                    pw_hash=user.web_password_hash,
                )
                print(f"  Dashboard: {dashboard_url}")
                result["dashboard_url"] = dashboard_url

            result["status"] = "success"
            result["folder_name"] = folder_name
            result["transcript_length"] = len(text)
            result["original_duration"] = original_duration
            result["trimmed_duration"] = trimmed_duration

    except subprocess.CalledProcessError as e:
        result["error"] = f"ffmpeg error: {e.stderr[:500] if e.stderr else str(e)}"
        print(f"\nError: {result['error']}")
    except RuntimeError as e:
        result["error"] = str(e)
        print(f"\nError: {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        print(f"\nError: {result['error']}")

    print(f"\n{'=' * 60}")
    print(f"Status: {result['status']}")
    print(f"{'=' * 60}\n")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Zumo — Zoom/Audio Transcription Pipeline",
    )
    parser.add_argument("file", nargs="?", help="Path to audio/video file")
    parser.add_argument("--user", required=True, help="Username (matches users/{name}.json)")
    parser.add_argument(
        "--session-type",
        choices=list(SESSION_TYPES.keys()),
        default="other",
        help="Type of session (default: other)",
    )
    parser.add_argument("--speakers", default="", help="Comma-separated speaker names")
    parser.add_argument(
        "--language", choices=["he", "en"], default=None,
        help="Override user's default language",
    )
    parser.add_argument("--url", help="Zoom recording share link (alternative to file)")
    parser.add_argument("--passcode", default="", help="Zoom recording passcode")
    parser.add_argument("--local", action="store_true", help="Save locally instead of GitHub")
    parser.add_argument("--skip-analysis", action="store_true", help="Transcript only, no Claude analysis")
    parser.add_argument("--skip-diarization", action="store_true", help="Skip speaker diarization")
    parser.add_argument("--init", action="store_true", help="Initialize GitHub repo structure for user")
    parser.add_argument("--dashboard", action="store_true", help="Regenerate dashboard HTML only")

    args = parser.parse_args()

    # Load user
    try:
        user = load_user(args.user)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    language = args.language or user.default_language

    # Dashboard-only mode
    if args.dashboard:
        dash_path = save_dashboard(
            user.dashboard_slug, user.name, user.web_password_hash,
        )
        print(f"Dashboard generated: {dash_path}")
        sys.exit(0)

    # Init mode
    if args.init:
        validate_config(local_mode=False)
        ensure_repo_structure(user.dashboard_slug)
        print(f"Repo structure initialized for {user.name} ({user.dashboard_slug}/)")
        sys.exit(0)

    # Normal mode — need a file or URL
    if not args.file and not args.url:
        parser.error("file or --url is required (unless using --init)")

    # Validate config
    try:
        validate_config(local_mode=args.local)
    except EnvironmentError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # If URL provided, download first
    if args.url:
        if not is_zoom_url(args.url):
            print(f"Error: URL doesn't look like a Zoom recording: {args.url}")
            sys.exit(1)

        print(f"Downloading Zoom recording...")
        try:
            download_dir = Path(tempfile.mkdtemp(prefix="zumo-dl-"))
            file_path = download_zoom_recording(args.url, download_dir, args.passcode or None)
            print(f"  Downloaded: {file_path.name}")
        except RuntimeError as e:
            print(f"Error downloading: {e}")
            sys.exit(1)
    else:
        file_path = Path(args.file)
        download_dir = None
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            sys.exit(1)

    # Run pipeline
    try:
        result = process_file(
            file_path=file_path,
            user=user,
            session_type=args.session_type,
            speakers=args.speakers,
            language=language,
            local_mode=args.local,
            skip_analysis=args.skip_analysis,
            skip_diarization=args.skip_diarization,
        )
    finally:
        # Clean up download dir if we created one
        if download_dir and download_dir.exists():
            shutil.rmtree(download_dir, ignore_errors=True)

    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
