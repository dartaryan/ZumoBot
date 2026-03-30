"""Claude API for transcript analysis."""

from pathlib import Path

from anthropic import Anthropic

from .config import HAIKU_MODEL, SONNET_MODEL

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
    model: str = SONNET_MODEL,
    user_requests: str = "full analysis",
    gemini_text: str = "",
) -> str:
    """Full structured analysis using the Zumo Bot agent prompt.

    Uses zumo-bot-agent.md as the system prompt. Supports dual-source mode
    when gemini_text is provided (Hebrew AI for accurate text, Gemini for
    speaker diarization). Returns empty string if no api_key.
    """
    if not api_key:
        return ""

    if gemini_text:
        # Dual-source mode: Hebrew AI + Gemini
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
    else:
        # Single-source mode (fallback)
        user_message = (
            f"Session Type: {session_type}\n"
            f"Speakers: {speakers or 'Not specified'}\n"
            f"Language: {language}\n"
            f"User Requests: {user_requests}\n"
            f"\n"
            f"--- TRANSCRIPT ---\n"
            f"{transcript_text[:100000]}"
        )

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=16384,
        system=_AGENT_PROMPT,
        messages=[{
            "role": "user",
            "content": user_message,
        }],
    )
    return response.content[0].text
