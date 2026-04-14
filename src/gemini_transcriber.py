"""Gemini Flash transcription with speaker diarization."""

import asyncio
import tempfile
from pathlib import Path

from google import genai
from google.genai import types

from .config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-3-flash-preview"

DIARIZATION_PROMPT = (
    "Transcribe this audio file. Identify different speakers and label them as Speaker A, Speaker B, etc.\n"
    "For each speaker change, start a new line with the speaker label.\n"
    "Format: \"Speaker A: [text]\"\n"
    "Include timestamps at natural breaks in [MM:SS] format.\n"
    "Focus on accurately identifying WHEN speakers change, even if the text isn't perfect.\n"
    "If the audio is in Hebrew, transcribe in Hebrew.\n"
    "Do NOT summarize or omit any parts — transcribe everything."
)


def _get_client(api_key: str | None = None) -> genai.Client:
    """Create a Gemini client."""
    key = api_key or GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=key)


def transcribe_with_diarization(
    audio_path: str | Path,
    api_key: str | None = None,
    on_progress=None,
) -> str:
    """Send audio to Gemini Flash for transcription with speaker diarization.

    Uses the Gemini Files API for upload, then generates transcription.
    Returns text with speaker labels (Speaker A, Speaker B, etc.).
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    def _progress(msg: str):
        if on_progress:
            on_progress(msg)

    client = _get_client(api_key)

    _progress("Uploading audio to Gemini...")
    uploaded_file = client.files.upload(file=audio_path)
    _progress(f"Upload complete. Processing with {GEMINI_MODEL}...")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type=uploaded_file.mime_type,
                    ),
                    types.Part.from_text(text=DIARIZATION_PROMPT),
                ]
            )
        ],
    )

    text = response.text or ""
    _progress(f"Gemini transcription complete ({len(text)} characters).")
    return text
