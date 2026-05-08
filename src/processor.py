"""Claude API for transcript analysis."""

import logging
from pathlib import Path

from anthropic import Anthropic

from .anthropic_stream import StreamResult, stream_with_continuation
from .config import ANALYZE_MODEL, HAIKU_MODEL

logger = logging.getLogger(__name__)

# Load the Zumo Bot agent prompt once at import time
_AGENT_PROMPT_PATH = Path(__file__).parent.parent / "zumo-bot-agent.md"
_AGENT_PROMPT = _AGENT_PROMPT_PATH.read_text(encoding="utf-8")


def generate_summary(
    transcript_text: str,
    api_key: str,
    model: str = HAIKU_MODEL,
) -> str:
    """Generate a one-line Hebrew summary using Claude Haiku. For the index."""
    if not api_key:
        return "—"

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": (
                "סכם את התמלול הבא במשפט אחד קצר בעברית (עד 15 מילים). "
                "רק הסיכום, בלי שום דבר אחר:\n\n"
                f"{transcript_text[:4000]}"
            ),
        }],
    )
    return response.content[0].text.strip()


def analyze_transcript(
    transcript_text: str,
    api_key: str,
    session_type: str,
    speakers: str,
    language: str = "he",
    model: str = ANALYZE_MODEL,
    user_requests: str = "full analysis",
    gemini_text: str = "",
    merged: bool = False,
) -> StreamResult:
    """Full structured analysis using the Zumo Bot agent prompt.

    Three modes, in order of preference:
      - merged=True → `transcript_text` is the merged speaker-labeled transcript;
        send it as the single source. `gemini_text` is ignored.
      - merged=False with `gemini_text` → legacy dual-source fallback used when
        the merge agent failed; sends Hebrew AI + Gemini side-by-side.
      - merged=False with no `gemini_text` → single-source fallback.

    Returns a StreamResult. Empty StreamResult (text="", iterations=0) if no
    api_key — callers detect this via `result.text` falsiness.

    max_tokens=32000 matches the Opus 4.6 ceiling. The wrapper auto-continues
    via assistant-prefill when the model still hits max_tokens, and exposes
    `truncated=True` when even continuation can't finish — callers must surface
    that to the user instead of silently shipping a partial analysis.
    """
    if not api_key:
        return StreamResult(
            text="", stop_reason="", iterations=0, truncated=False,
            total_input_tokens=0, total_output_tokens=0,
        )

    if merged or not gemini_text:
        user_message = (
            f"Session Type: {session_type}\n"
            f"Speakers: {speakers or 'Not specified'}\n"
            f"Language: {language}\n"
            f"User Requests: {user_requests}\n"
            f"\n"
            f"--- TRANSCRIPT ---\n"
            f"{transcript_text[:100000]}"
        )
    else:
        user_message = (
            f"Session Type: {session_type}\n"
            f"Speakers: {speakers or 'Not specified'}\n"
            f"Language: {language}\n"
            f"User Requests: {user_requests}\n"
            f"\n"
            f"--- HEBREW AI TRANSCRIPT (accurate text, no speaker labels) ---\n"
            f"{transcript_text[:100000]}\n"
            f"\n"
            f"--- GEMINI TRANSCRIPT (speaker labels, may contain errors) ---\n"
            f"{gemini_text[:100000]}"
        )

    client = Anthropic(api_key=api_key)
    return stream_with_continuation(
        client=client,
        model=model,
        max_tokens=32000,
        system=_AGENT_PROMPT,
        user_message=user_message,
    )
