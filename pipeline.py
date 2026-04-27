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

from concurrent.futures import ThreadPoolExecutor

from src.config import (
    OUTPUT_DIR,
    SESSION_TYPES,
    SILENCE_THRESHOLD_DB,
    validate_config,
)
from src.users import load_user
from src.audio import (
    compress_for_upload,
    extract_audio,
    format_duration,
    get_duration,
    is_audio_file,
    detect_silence,
    remove_silence,
)
from src.transcriber import transcribe
from src.gemini_transcriber import transcribe_with_diarization
from src.processor import analyze_transcript, generate_summary
from src.merge_agent import merge_transcripts
from src.formatter import (
    format_analysis_md,
    format_transcript_md,
    generate_folder_name,
)
from src.downloader import download_zoom_recording, is_zoom_url
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
    zoom_vtt_path: Path | None = None,
    user_requests: str = "full analysis",
    gemini_api_key: str | None = None,
) -> dict:
    """Main pipeline: audio -> compress -> dual transcribe -> analyze -> save."""

    result = {"status": "error", "error": None}
    timestamp = datetime.now()

    print(f"\n{'=' * 60}")
    print(f"Zumo Pipeline v2")
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

            # --- Step 3: Compress for upload ---
            print("\n[3/8] Compressing audio for upload...")
            upload_path = tmp / "compressed.mp3"
            compress_for_upload(trimmed_path, upload_path)
            compressed_size_mb = upload_path.stat().st_size / 1024 / 1024
            print(f"  Compressed to {compressed_size_mb:.1f}MB")

            # --- Step 4: Dual transcription (parallel) ---
            _gemini_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")

            if not user.hebrew_ai_api_key and not _gemini_key:
                raise ValueError(
                    "No transcriber configured. Set ZUMO_USER_HEBREW_AI_KEY or GEMINI_API_KEY."
                )

            print(f"\n[4/8] Dual transcription (Hebrew AI + Gemini Flash)...")

            hebrew_ai_text = ""
            gemini_text = ""
            hebrew_ai_error: str | None = None
            gemini_error: str | None = None

            def _run_hebrew_ai():
                t, _ = transcribe(
                    upload_path,
                    user.hebrew_ai_api_key,
                    language,
                    on_progress=lambda msg: print(f"  [Hebrew AI] {msg}"),
                )
                return t

            def _run_gemini():
                if not _gemini_key:
                    print("  [Gemini] Skipping — GEMINI_API_KEY not set.")
                    return ""
                return transcribe_with_diarization(
                    upload_path,
                    api_key=_gemini_key,
                    on_progress=lambda msg: print(f"  [Gemini] {msg}"),
                    speakers=speakers,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                future_hebrew = pool.submit(_run_hebrew_ai) if user.hebrew_ai_api_key else None
                future_gemini = pool.submit(_run_gemini)

                if future_hebrew is not None:
                    try:
                        hebrew_ai_text = future_hebrew.result()
                        print(f"  [Hebrew AI] Complete ({len(hebrew_ai_text)} chars)")
                    except Exception as e:
                        hebrew_ai_error = str(e)
                        print(f"  [Hebrew AI] Failed: {e}")
                else:
                    hebrew_ai_error = "hebrew_ai_api_key not configured"

                try:
                    gemini_text = future_gemini.result()
                    print(f"  [Gemini] Complete ({len(gemini_text)} chars)")
                except Exception as e:
                    gemini_error = f"{type(e).__name__}: {e}"
                    print(f"  [Gemini] Failed: {gemini_error}")
                    gemini_text = ""

            if not _gemini_key:
                gemini_error = "GEMINI_API_KEY not set"

            # Pick primary transcript — Hebrew AI first, Gemini as fallback
            if hebrew_ai_text:
                primary_text = hebrew_ai_text
                side_gemini_text = gemini_text
                transcriber_used = "both" if gemini_text else "hebrew-ai"
            elif gemini_text:
                primary_text = gemini_text
                side_gemini_text = ""  # avoid passing Gemini twice to Claude
                transcriber_used = "gemini-only"
                print(f"  [!] Hebrew AI unavailable — proceeding with Gemini only.")
            else:
                raise RuntimeError(
                    f"Both transcribers failed.\n"
                    f"  Hebrew AI: {hebrew_ai_error or 'n/a'}\n"
                    f"  Gemini: {gemini_error or 'n/a'}"
                )

            result["transcriber_used"] = transcriber_used
            if transcriber_used == "gemini-only":
                result["fallback_reason"] = hebrew_ai_error or "Hebrew AI unavailable"

            # --- Step 5: Zoom VTT fallback / Merge agent ---
            vtt_applied = False
            if zoom_vtt_path and zoom_vtt_path.exists() and not side_gemini_text and transcriber_used != "gemini-only":
                print(f"\n[5/8] Aligning speakers from Zoom VTT: {zoom_vtt_path.name}")
                try:
                    from src.vtt_align import align_with_zoom_vtt
                    primary_text = align_with_zoom_vtt(primary_text, zoom_vtt_path)
                    vtt_applied = True
                    print(f"  Speaker-aligned transcript: {len(primary_text)} characters.")
                except Exception as e:
                    print(f"  VTT alignment failed, using raw transcript: {e}")

            # Merge agent: produce a unified, speaker-labeled transcript from
            # Hebrew AI words + Gemini turns. Skip when VTT already labeled the
            # transcript or when the Anthropic key isn't available.
            use_merged = False
            if not vtt_applied and user.anthropic_api_key and not skip_analysis:
                print("\n[5b/8] Running merge agent (speaker reconciliation)...")
                try:
                    merged_text = merge_transcripts(
                        hebrew_ai_text=hebrew_ai_text,
                        gemini_text=gemini_text,
                        speakers=speakers,
                        session_type=session_type,
                        language=language,
                        api_key=user.anthropic_api_key,
                    )
                    if merged_text.strip():
                        primary_text = merged_text
                        side_gemini_text = ""
                        use_merged = True
                        print(f"  Merge complete ({len(merged_text)} characters).")
                except Exception as e:
                    print(f"  Merge agent failed, falling back to dual-source analysis: {e}")
            elif vtt_applied:
                print("\n[5b/8] Merge agent skipped (VTT alignment in use).")
            else:
                print("\n[5b/8] Merge agent skipped (no Anthropic key or skip_analysis).")

            # --- Step 6: Summary ---
            print("\n[6/8] Generating summary...")
            summary = generate_summary(primary_text, user.anthropic_api_key)
            print(f"  Summary: {summary}")

            # --- Step 7: Analysis (Claude synthesis) ---
            if skip_analysis or not user.anthropic_api_key:
                print("\n[7/8] Skipping analysis.")
                analysis = None
            else:
                print("\n[7/8] Claude analysis...")
                analysis = analyze_transcript(
                    primary_text,
                    user.anthropic_api_key,
                    session_type,
                    speakers,
                    language,
                    user_requests=user_requests,
                    gemini_text=side_gemini_text,
                    merged=use_merged,
                )
                print(f"  Analysis complete ({len(analysis)} characters).")

            # --- Step 8: Format & Save ---
            print("\n[8/8] Saving...")
            folder_name = generate_folder_name(
                session_type, speakers or file_path.stem, timestamp,
            )

            transcript_md = format_transcript_md(
                primary_text, file_path.stem, session_type, speakers, language,
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
            result["transcript_length"] = len(primary_text)
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
