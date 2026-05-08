"""Zumo Merge Agent — reconciles Hebrew AI + Gemini transcripts into a single,
speaker-labeled transcript using Claude Opus."""

from pathlib import Path

from anthropic import Anthropic

from .anthropic_stream import StreamResult, stream_with_continuation
from .config import OPUS_MODEL

# Load the merge agent system prompt once at module import.
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "zumo-merge-agent.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Long sessions can produce >16k tokens of merged transcript; Opus 4.7 supports 32k out.
_MAX_TOKENS = 32000

# Cap each input side. Hebrew AI + Gemini get the full payload Claude analysis
# already accepts (~100k chars per side).
_MAX_CHARS_PER_SIDE = 100_000


def merge_transcripts(
    hebrew_ai_text: str,
    gemini_text: str,
    speakers: str,
    session_type: str,
    language: str,
    api_key: str,
) -> StreamResult:
    """Run the merge agent. Returns a StreamResult.

    Raises RuntimeError on missing api key or empty result. Caller is
    responsible for falling back to the previous behavior on failure, and for
    surfacing `result.truncated` to the user when it's True (means the merged
    transcript itself is incomplete — analysis downstream operates on partial
    source).
    """
    if not api_key:
        raise RuntimeError("Anthropic API key is required for the merge agent.")

    user_message = (
        f"Session Type: {session_type}\n"
        f"Speakers: {speakers}\n"
        f"Language: {language}\n"
        f"\n"
        f"--- HEBREW AI TRANSCRIPT (accurate text, no speaker labels) ---\n"
        f"{(hebrew_ai_text or '')[:_MAX_CHARS_PER_SIDE]}\n"
        f"\n"
        f"--- GEMINI TRANSCRIPT (speaker labels and timestamps, may have word errors) ---\n"
        f"{(gemini_text or '')[:_MAX_CHARS_PER_SIDE]}"
    )

    client = Anthropic(api_key=api_key)
    result = stream_with_continuation(
        client=client,
        model=OPUS_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        user_message=user_message,
    )

    if not result.text.strip():
        raise RuntimeError("Merge agent returned empty text.")
    return result
