"""Align Hebrew AI transcript with Zoom VTT speaker labels."""

import re
from pathlib import Path


def parse_vtt(vtt_path: Path) -> list[dict]:
    """Parse a Zoom VTT file into segments with speaker labels.

    Handles both formats:
    - "Speaker Name: text" (colon-delimited)
    - "<v Speaker Name>text</v>" (WebVTT voice tag)
    """
    text = vtt_path.read_text(encoding="utf-8")
    segments = []

    # Split into cue blocks (separated by blank lines)
    blocks = re.split(r"\n\s*\n", text)

    for block in blocks:
        lines = block.strip().split("\n")

        # Find the timestamp line
        ts_line = None
        text_lines = []
        for line in lines:
            if "-->" in line:
                ts_line = line
            elif ts_line is not None and line.strip():
                text_lines.append(line.strip())

        if not ts_line or not text_lines:
            continue

        # Parse timestamps
        ts_match = re.match(
            r"(\d+:\d+:\d+[.,]\d+)\s*-->\s*(\d+:\d+:\d+[.,]\d+)", ts_line
        )
        if not ts_match:
            continue

        start = _ts_to_seconds(ts_match.group(1))
        end = _ts_to_seconds(ts_match.group(2))
        content = " ".join(text_lines)

        # Extract speaker
        speaker = None

        # Format 1: <v Speaker Name>text</v>
        v_match = re.match(r"<v\s+([^>]+)>(.+?)(?:</v>)?$", content, re.DOTALL)
        if v_match:
            speaker = v_match.group(1).strip()
            content = v_match.group(2).strip()
        else:
            # Format 2: Speaker Name: text
            colon_match = re.match(r"^(.+?):\s+(.+)$", content, re.DOTALL)
            if colon_match:
                potential_speaker = colon_match.group(1).strip()
                # Avoid matching timestamps or URLs as speakers
                if len(potential_speaker) < 60 and "://" not in potential_speaker:
                    speaker = potential_speaker
                    content = colon_match.group(2).strip()

        segments.append({
            "start": start,
            "end": end,
            "speaker": speaker,
            "text": content,
        })

    return segments


def _ts_to_seconds(ts: str) -> float:
    """Convert "HH:MM:SS.mmm" or "HH:MM:SS,mmm" to seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def align_with_zoom_vtt(
    ai_transcript: str,
    vtt_path: Path,
) -> str:
    """Merge Zoom VTT speaker labels into the AI transcript.

    Strategy: Use the VTT to build a timeline of who spoke when,
    then insert speaker headers into the AI transcript based on
    paragraph timing estimation.

    Since Hebrew AI doesn't provide timestamps, we use a simpler approach:
    build a speaker-labeled version directly from the VTT structure,
    replacing VTT text with AI text proportionally.
    """
    vtt_segments = parse_vtt(vtt_path)
    if not vtt_segments:
        return ai_transcript

    # Build speaker timeline: consecutive segments by same speaker → one block
    speaker_blocks = []
    current_speaker = None
    current_text = []
    current_start = 0

    for seg in vtt_segments:
        speaker = seg["speaker"] or "Unknown"
        if speaker != current_speaker:
            if current_speaker and current_text:
                speaker_blocks.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_text),
                    "start": current_start,
                    "end": seg["start"],
                })
            current_speaker = speaker
            current_text = [seg["text"]]
            current_start = seg["start"]
        else:
            current_text.append(seg["text"])

    if current_speaker and current_text:
        speaker_blocks.append({
            "speaker": current_speaker,
            "text": " ".join(current_text),
            "start": current_start,
            "end": vtt_segments[-1]["end"],
        })

    if not speaker_blocks:
        return ai_transcript

    # Calculate proportion of each speaker block (by VTT text length)
    total_vtt_chars = sum(len(b["text"]) for b in speaker_blocks)
    if total_vtt_chars == 0:
        return ai_transcript

    # Split AI transcript proportionally and assign speakers
    ai_text = ai_transcript.strip()
    total_ai_chars = len(ai_text)
    result_parts = []
    ai_pos = 0
    prev_speaker = None

    for block in speaker_blocks:
        proportion = len(block["text"]) / total_vtt_chars
        chunk_size = int(proportion * total_ai_chars)

        # Find a natural break point (sentence end) near the target position
        target_pos = ai_pos + chunk_size
        if target_pos >= total_ai_chars:
            chunk = ai_text[ai_pos:]
        else:
            # Look for sentence boundary within ~100 chars of target
            best_break = target_pos
            for delim in [".\n", ".\r", ". ", "?\n", "? ", "!\n", "! "]:
                idx = ai_text.rfind(delim, max(ai_pos, target_pos - 100), min(total_ai_chars, target_pos + 100))
                if idx > ai_pos:
                    best_break = idx + len(delim)
                    break
            chunk = ai_text[ai_pos:best_break]

        chunk = chunk.strip()
        if chunk:
            if block["speaker"] != prev_speaker:
                result_parts.append(f"\n**{block['speaker']}:**\n{chunk}")
                prev_speaker = block["speaker"]
            else:
                result_parts.append(chunk)

        ai_pos = ai_pos + len(chunk) + (len(ai_text[ai_pos:]) - len(ai_text[ai_pos:].lstrip()) if chunk else 0)
        ai_pos = min(ai_pos + chunk_size - len(chunk), total_ai_chars) if chunk else ai_pos

    # Append any remaining text
    remaining = ai_text[ai_pos:].strip() if ai_pos < total_ai_chars else ""
    if remaining:
        result_parts.append(remaining)

    return "\n".join(result_parts).strip()
