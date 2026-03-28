"""Claude API for transcript analysis."""

from anthropic import Anthropic

from .config import HAIKU_MODEL, SONNET_MODEL, SESSION_TYPES


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
) -> str:
    """Full structured analysis using Claude Sonnet.

    Phase 1: Basic system prompt. Phase 2 will use zumo-bot-agent.md from Seeker.
    Returns empty string if no api_key.
    """
    if not api_key:
        return ""

    type_info = SESSION_TYPES.get(session_type, SESSION_TYPES["other"])
    type_label = type_info["he"] if language == "he" else type_info["en"]
    lang_instruction = "כתוב את כל הפלט בעברית." if language == "he" else "Write all output in English."

    system_prompt = f"""You are Zumo, a transcript analysis agent. You receive a transcript and produce a structured markdown document.

Session type: {type_label}
Speakers: {speakers or "Not specified"}

{lang_instruction}

Output the following sections in markdown:
1. **Title** — A short descriptive title for this session
2. **Participants** — List of speakers and their roles (if identifiable)
3. **Summary** — 3-5 sentence summary of the session
4. **Key Topics** — Numbered list of main topics discussed
5. **Action Items** — Table with columns: Task | Owner | Deadline (use "—" if unknown)
6. **Key Quotes** — Important quotes with speaker attribution (use blockquotes)
7. **Open Questions** — Any unresolved questions or items needing follow-up

Quality rules:
- Every claim must come from the transcript. Never fabricate.
- If something is unclear, mark it: "[unclear]" or "[לא ברור]"
- Quotes must be exact, not paraphrased.
- Action items without clear owners get "[not specified]" / "[לא צוין]"."""

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"Analyze this transcript:\n\n{transcript_text[:100000]}",
        }],
    )
    return response.content[0].text
