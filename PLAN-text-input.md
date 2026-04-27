# Zumo — Text Transcript Input Path

> Author: prep session, 2026-04-27.
> Standalone follow-on to [PLAN-v3.md](PLAN-v3.md). Independent of v3 streams A-E.

## Why this exists

Today the bot only ingests audio. There's no path for an existing transcript that came from elsewhere (a Zoom export, a YouTube auto-transcript, a manual notes session, an AI-generated transcript from another tool). The user wants to be able to send a `.md` or `.txt` file and have the bot run the rest of the pipeline (session-type questions, analysis, dashboard publish) without doing any transcription.

## What this changes

Add a new entry path to the bot:

- **File types:** `.md`, `.txt`.
- **Behavior:** skip transcription (Hebrew AI + Gemini both not called), skip the merge agent (no two sources to reconcile). Use the file's contents as the canonical transcript that goes into both the dashboard and the analysis prompt.
- **Conversation flow:** identical to the audio path — session type, speakers, output-format are all asked the same way. The user confirmed all four UX decisions: keep all questions on, treat the text as if it had come out of the merge agent already.

## Architecture

```
Audio path (post-v3):
  audio → [Hebrew AI || Gemini] → merge agent → primary_text → analysis → dashboard

Text path (NEW):
  .md / .txt → primary_text (verbatim, lightly normalized) → analysis → dashboard
```

The text path enters the existing pipeline at the same point where the merge agent's output lands. From analysis onward, behavior is identical.

## Files affected

- `bot.py`:
  - New `MessageHandler` filtering `Document.FileExtension("md") | Document.FileExtension("txt")`. Same `ConversationHandler` so the existing session-type / speakers / output-format states fire afterward.
  - New handler function `text_input_handler` that reads + normalizes + stores file content in `context.user_data['text_input']`, sends the user-facing notice, and transitions into the existing first question.
  - `_process_and_reply` accepts a new parameter `text_input: str = ""`. When set: skip `_do_preprocess`, skip the merge agent, use `text_input` directly as `primary_text` for both the dashboard and the analysis call.
- No changes to `src/processor.py` — `analyze_transcript` already handles a single source via `transcript_text`.
- No changes to `src/formatter.py` — `format_transcript_md` already accepts arbitrary text.
- `src/merge_agent.py` (introduced in v3) is not touched.
- No changes to `pipeline.py` (out of scope for this stream — bot-only).

## Light normalization (applied before storing)

- Strip UTF-8 BOM (`﻿`).
- Normalize line endings: `\r\n` → `\n`, lone `\r` → `\n`.
- Trim trailing whitespace from each line.
- Collapse runs of 3+ blank lines down to 2.
- **No content changes.** This only cleans encoding/whitespace artifacts.

## Edge cases

| Case | Behavior |
|---|---|
| Empty file (post-strip) | Reject with a clear Hebrew message. |
| Non-UTF-8 decode | Try `utf-8`, fall back to `utf-8-sig`, then `errors='replace'`. If that still fails, reject. |
| Oversized (>500 KB or >200k characters) | Reject — analysis caps at 100k anyway, surprise truncation is bad UX. |
| `.txt` with binary content | Decode failure → reject. |
| `.md` with embedded YAML frontmatter / images | Pass through verbatim. The dashboard renders MD natively. |
| File too large for vanilla Telegram (>20 MB) | Won't happen for plain text in practice; let the existing Pyrogram large-file path handle it if it does. |
| `original_duration` missing | Set to `0`. Verify dashboard renderer hides the duration field gracefully when 0. |

## Coordination with v3

- v3 is **in flight**. The merge-agent integration in `_process_and_reply` may or may not be merged when fresh-session Claude starts on this stream.
- Fresh-session Claude **must read `_process_and_reply` first** to see its current shape. The new `text_input` branch goes at the **very top** of the function body — it short-circuits the audio path entirely.
- The `text_input` branch works the same whether or not v3's merge agent is in place: it never invokes the merge agent, regardless. So this stream is safe to ship before, alongside, or after v3.

## Pause points

**One pause** — before patching `bot.py`, fresh-session Claude drafts all the Hebrew user-facing strings and presents them for approval:

- File received notice (e.g. "got the file, will skip transcription").
- Continuation message (introducing the upcoming session-type question).
- Empty-file rejection.
- Non-text-decode rejection.
- Oversized-file rejection.

Wait for user approval or edits before writing any code.

## Acceptance criteria

- [ ] Upload `.md` → bot accepts, runs the full conversation, publishes verbatim text (post-normalization) to the dashboard, runs analysis.
- [ ] Upload `.txt` → same as above.
- [ ] Upload empty `.txt` → bot rejects with the approved Hebrew message; conversation does not advance.
- [ ] Upload binary file with `.txt` extension → bot rejects.
- [ ] Upload audio file (existing behavior) → unchanged, no regression.
- [ ] Production log for a text-input session shows zero calls to Hebrew AI / Gemini / merge agent.
- [ ] Dashboard for a text-input session shows the file's text exactly (modulo normalization), with metadata header populated correctly even though `original_duration` is `0`.

## What the user provides

Just the approval on the Hebrew strings during the single pause point. No external artifacts (system prompts, model IDs, repo data) needed for this stream.
