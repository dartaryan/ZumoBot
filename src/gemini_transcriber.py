"""Gemini Flash transcription with speaker diarization."""

import time
from pathlib import Path

from google import genai
from google.genai import types

from .config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-2.5-pro"

# 10 min hard cap on the underlying HTTP call. Field is milliseconds.
_HTTP_TIMEOUT_MS = 600_000

# How long to wait for an uploaded file to reach ACTIVE before generating.
_FILE_ACTIVE_BUDGET_S = 90
_FILE_ACTIVE_POLL_INTERVAL_S = 2

DIARIZATION_PROMPT = (
    "Transcribe this audio file. Identify different speakers and label them as Speaker A, Speaker B, etc.\n"
    "For each speaker change, start a new line with the speaker label.\n"
    "Format: \"Speaker A: [text]\"\n"
    "Include timestamps at natural breaks in [MM:SS] format.\n"
    "Focus on accurately identifying WHEN speakers change, even if the text isn't perfect.\n"
    "If the audio is in Hebrew, transcribe in Hebrew.\n"
    "Do NOT summarize or omit any parts — transcribe everything."
)


def _build_prompt(speakers: str) -> str:
    """Splice user-supplied speaker names into the diarization prompt."""
    cleaned = (speakers or "").strip()
    if not cleaned:
        return DIARIZATION_PROMPT
    speaker_hint = (
        f"The conversation includes these speakers: {cleaned}.\n"
        "Identify which speaker is talking by voice characteristics and label "
        "each line with their actual name. If you detect more speakers than "
        "listed, use Speaker D, E, etc. for the extras.\n\n"
    )
    return speaker_hint + DIARIZATION_PROMPT


def _state_name(state) -> str:
    """Normalize the SDK's File.state (enum or str) to a plain name."""
    if state is None:
        return ""
    return getattr(state, "name", None) or str(state).split(".")[-1]


def _get_client(api_key: str | None = None) -> genai.Client:
    """Create a Gemini client with a 10-minute HTTP timeout."""
    key = api_key or GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=_HTTP_TIMEOUT_MS),
    )


def _wait_for_active(client: genai.Client, uploaded_file, on_progress) -> object:
    """Poll the Files API until the upload is ACTIVE or fail within the budget."""
    deadline = time.monotonic() + _FILE_ACTIVE_BUDGET_S
    state = _state_name(uploaded_file.state)
    while True:
        if state == "ACTIVE":
            return uploaded_file
        if state == "FAILED":
            raise RuntimeError(f"Gemini Files upload reported state=FAILED for {uploaded_file.name}")
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Gemini Files upload did not reach ACTIVE within "
                f"{_FILE_ACTIVE_BUDGET_S}s (last state: {state or 'unknown'})"
            )
        time.sleep(_FILE_ACTIVE_POLL_INTERVAL_S)
        on_progress(f"Waiting for upload to be ACTIVE (current: {state or 'unknown'})...")
        uploaded_file = client.files.get(name=uploaded_file.name)
        state = _state_name(uploaded_file.state)


def transcribe_with_diarization(
    audio_path: str | Path,
    api_key: str | None = None,
    on_progress=None,
    speakers: str = "",
) -> str:
    """Send audio to Gemini for transcription with speaker diarization.

    Uploads via the Files API, waits for ACTIVE, then runs generate_content.
    Returns text with speaker labels (Speaker A, Speaker B, etc.). When
    `speakers` is provided, real names are spliced into the prompt so Gemini
    attempts to label by voice with the actual names.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    client = _get_client(api_key)

    _progress("Uploading audio to Gemini...")
    uploaded_file = client.files.upload(file=audio_path)

    _progress("Upload posted, waiting for Files API to mark ACTIVE...")
    uploaded_file = _wait_for_active(client, uploaded_file, _progress)

    _progress(f"Upload ACTIVE. Generating with {GEMINI_MODEL}...")
    prompt = _build_prompt(speakers)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type=uploaded_file.mime_type,
                    ),
                    types.Part.from_text(text=prompt),
                ]
            )
        ],
    )

    text = response.text or ""
    _progress(f"Gemini transcription complete ({len(text)} characters).")
    return text
