"""Hebrew AI transcription API integration."""

import time
from pathlib import Path
from typing import Callable

import requests

HEBREW_AI_BASE_URL = "https://hebrew-ai.com/api/transcribe"
POLL_INTERVAL = 5
POLL_TIMEOUT = 1800


def transcribe(
    audio_path: str | Path,
    api_key: str,
    language: str = "he",
    on_progress: Callable[[str], None] | None = None,
) -> tuple[str, float]:
    """Send audio to Hebrew AI, poll for result.

    Returns (transcript_text, duration_seconds).
    """
    headers = {"Authorization": f"Bearer {api_key}"}

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # Submit
    _progress("Submitting to Hebrew AI...")
    with open(str(audio_path), "rb") as f:
        resp = requests.post(
            HEBREW_AI_BASE_URL,
            headers=headers,
            files={"file": ("audio.mp3", f, "audio/mpeg")},
            data={"language": language},
            timeout=60,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Hebrew AI HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
    except requests.exceptions.JSONDecodeError:
        raise RuntimeError(f"Hebrew AI returned non-JSON response ({resp.status_code}): {resp.text[:300]}")

    if not data.get("success"):
        raise RuntimeError(f"Hebrew AI submit error: {data.get('error', 'Unknown error')}")

    transcription_id = data.get("transcriptionId") or data.get("transcription_id")
    if not transcription_id:
        raise RuntimeError(f"Hebrew AI response missing transcription ID: {data}")
    _progress(f"Transcription submitted (ID: {transcription_id}), polling...")

    # Poll
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        resp = requests.get(
            f"{HEBREW_AI_BASE_URL}?id={transcription_id}",
            headers=headers,
            timeout=30,
        )
        result = resp.json()
        status = result.get("status")

        _progress(f"Status: {status} (elapsed: {elapsed}s)")

        if status == "COMPLETED":
            return result.get("text", ""), result.get("duration", 0)
        elif status == "FAILED":
            raise RuntimeError("Hebrew AI transcription failed")

    raise RuntimeError(f"Transcription timed out after {POLL_TIMEOUT}s")
