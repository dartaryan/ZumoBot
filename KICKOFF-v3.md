# Kickoff prompt — Zumo v3 implementation

> Paste the contents below this line into a fresh Claude Code session opened in `c:/Users/darta/Desktop/projects/zumo`. Make sure `prompts/zumo-merge-agent.md` exists first (the system prompt your agent builder produced from `MERGE-AGENT-BRIEF.md`).

---

You are picking up a planned, multi-stream change to the Zumo bot. Read these files in order before you do anything else:

1. [PLAN-v3.md](PLAN-v3.md) — full plan, work streams A–E, execution order, pause points, and acceptance criteria.
2. [MERGE-AGENT-BRIEF.md](MERGE-AGENT-BRIEF.md) — context for the new merge agent (you don't need to act on this directly; the user has already produced the system prompt).
3. [prompts/zumo-merge-agent.md](prompts/zumo-merge-agent.md) — the system prompt for the merge agent. This file MUST exist before you start work stream A. If it's missing, stop and ask the user to provide it.
4. [LOGS/logs.1777298121146.log](LOGS/logs.1777298121146.log) — the production log that motivated this work (Gemini hung at 12:58:40, never returned).
5. [src/gemini_transcriber.py](src/gemini_transcriber.py), [src/processor.py](src/processor.py), [bot.py](bot.py) — the three files you'll touch the most.

## Order of work

Use TodoWrite to track these. Pause for user input where the plan says to.

### Step 1 — Stream C (JobQueue) — fastest win
- Update `requirements.txt` so `python-telegram-bot` includes the `[job-queue]` extra (match the currently pinned version).
- If a Dockerfile builds wheels separately, ensure the extra is picked up.
- Confirm to the user, then move on.

### Step 2 — Stream B (Gemini stabilization)
- Run a WebSearch for: "best Gemini model for audio transcription with speaker diarization Hebrew" (and similar). Filter to the Gemini family available right now (mid-2026). Compare: latency on long audio, Hebrew accuracy, diarization quality, Files API ACTIVE-state behavior, preview vs GA.
- Post a 5-10 line summary to the user with a recommendation. **Wait for one-line approval** before changing `GEMINI_MODEL` in `src/gemini_transcriber.py`.
- Once approved:
  - Set `GEMINI_MODEL` to the chosen ID.
  - Add a `speakers: str` parameter to `transcribe_with_diarization` and splice it into the prompt:
    > The conversation includes these speakers: <names>. Identify which speaker is talking by voice characteristics and label each line with their actual name. If you detect more speakers than listed, use Speaker D, E, etc. for the extras.
  - Add `http_options=types.HttpOptions(timeout=600_000)` (10 min cap) on the `genai.Client(...)` constructor or on `generate_content`, whichever the SDK version supports — verify by reading the installed `google-genai` source.
  - After upload, poll `client.files.get(name=uploaded_file.name)` until `state == "ACTIVE"` (max 90 s, 2 s sleep between polls). If timeout, raise.
  - In `bot.py:_do_preprocess`, change `fh.result()` and `fg.result()` to `fh.result(timeout=...)` / `fg.result(timeout=...)` (e.g. 600 s) and let the existing `except Exception` branches catch `TimeoutError`. Keep the existing fall-back behavior: Gemini-only or Hebrew-only when one side fails.
  - Add a 60 s `requests` timeout in `src/transcriber.py` (Hebrew AI side) so it can't hang either.

### Step 3 — Stream A (Merge Agent) — depends on `prompts/zumo-merge-agent.md`
- Verify `prompts/zumo-merge-agent.md` exists and is non-empty. If not, stop and ask the user.
- Create `src/merge_agent.py`:
  - Function: `merge_transcripts(hebrew_ai_text: str, gemini_text: str, speakers: str, session_type: str, language: str, api_key: str) -> str`.
  - Loads the system prompt from `prompts/zumo-merge-agent.md`.
  - Uses `Anthropic` client with the latest Opus model (match how `processor.py` does it — same client style, but Opus instead of `SONNET_MODEL`).
  - User message follows the exact input format documented in `MERGE-AGENT-BRIEF.md` ("Inputs" section).
  - Returns the merged transcript string, raises on error.
- In `bot.py:_process_and_reply`, after dual transcription succeeds with at least Hebrew AI OR Gemini, call `merge_transcripts(...)` to produce a `merged_text`.
  - Use `merged_text` as the value of `primary_text` for the analysis call.
  - Use `merged_text` as the input to `format_transcript_md`.
  - On merge agent failure: log the error, fall back to the previous behavior (Hebrew AI text as primary, raw Gemini as side input to analysis).
- In `src/processor.py:analyze_transcript`, simplify: remove the dual-source prompt branch (`if gemini_text:`), since the merged transcript already encodes both. Keep the function signature backwards-compatible; just stop using `gemini_text` if `transcript_text` is the merged form. (Actually: keep `gemini_text` parameter as a fallback path used only when merge_agent failed. Document this in a comment-free way by branching on a `merged: bool` flag passed from bot.py.)
- Verify that the dashboard transcript on a real run shows real names with timestamps.

### Step 4 — Stream D (Personalized session-type menu)
- Clone https://github.com/dartaryan/zumo-data into `c:/tmp/zumo-data` (read-only side directory). Use `git clone --depth 1`.
- Walk the directory; identify the convention (folders contain analysis.md / metadata / session-type prefix in folder name). Spend up to 10 minutes reading.
- Cluster session types: count occurrences, group near-duplicates, list dominant categories.
- Propose to the user a personalized menu of 6-10 items, each with:
  - Display label (Hebrew)
  - One-line subtitle describing when to pick it
  - Internal `session_type` string (used by the analysis agent — keep existing string when possible)
- **Wait for user approval / edits.**
- Once approved, find the keyboard in `bot.py` that asks "what kind of session is this?" and replace its options. Add an "אחר / Other" escape that opens a free-text reply step.

### Step 5 — Stream E (Output-format clarity)
- Grep for the buttons that offer the structured-analysis vs knowledge-document choice. Read the current labels and the handler.
- Propose to the user:
  - New labels (clearer, with subtitles).
  - A default per session type (so the choice can be skipped automatically when obvious).
- **Wait for user approval.**
- Implement the chosen approach.

## Conventions

- TypeScript-style strictness applied to Python: explicit types, narrow returns, fail closed.
- Don't add features outside the plan. If you discover something else broken, log it in a comment to the user — don't fix it silently.
- Don't commit. The user reviews the diff at the end and asks for the commit themselves.
- Never run `git push` or anything destructive without explicit approval.
- Use the existing project style: `loop.run_in_executor` for blocking calls, `concurrent.futures` patterns already in `_do_preprocess`, `httpx`/`google-genai` already imported.

## When you're done

Print a single end-of-turn summary:
- What changed in each stream (one bullet per stream).
- Any pause point still open.
- Suggested next user action (test on a real recording / approve a pending choice / commit).

## Addendum — gotchas and clarifications

These were caught in a post-audit and matter:

1. **Model constants in `src/config.py` are misnamed.** `SONNET_MODEL = "claude-opus-4-6"` — the variable says Sonnet but the value is already Opus 4.6. Don't change `SONNET_MODEL` (the analysis agent depends on it). For the merge agent, add a new constant: `OPUS_MODEL = "claude-opus-4-7"` (current latest per the project's CLAUDE.md). Import it in `src/merge_agent.py`.

2. **Stale handoff docs at the repo root.** `HANDOFF.md`, `HANDOFF-NEXT.md`, `PLAN.md`, `PLAN-v2.md`, `AGENT-EXECUTE-PLAN.md`, `RAILWAY-DEBUG-PROMPT.md` are from previous sessions and may contradict v3. **Treat `PLAN-v3.md` and this kickoff as the only authoritative plan.** Don't modify or delete the old docs — they're history.

3. **Hebrew AI already has a `requests` timeout** of 60 s in `src/transcriber.py:38`. The Step 2 instruction to "add a 60 s `requests` timeout in `src/transcriber.py`" is obsolete — skip it.

4. **`pipeline.py` also calls `transcribe_with_diarization`** (line ~146 — the CLI / local fallback path used by `_process_and_reply` when there's no preprocessed text). Integrate the merge agent there too, so behavior is consistent between the bot and the CLI. Same fall-back rules: if merge fails, use Hebrew AI text + raw Gemini text into analysis as before.

5. **Deployment context.** The bot runs in a container (`Dockerfile` at repo root, deployed to Railway/Fly.io judging by `RAILWAY-DEBUG-PROMPT.md` and the production log). You can't smoke-test by running `python bot.py` locally without Telegram credentials. Verify via:
   - Code review of the diff against the plan.
   - Optionally: run `python pipeline.py <sample.m4a>` against a small local file to exercise the new merge path end-to-end. Don't rely on this for the bot-flow changes.

6. **Pause-point output language.** When you pause for user approval on the personalized session-type menu (Stream D) and the new output-format labels (Stream E), present the *proposed user-facing text in Hebrew* — that's what will appear on the bot. Surrounding analysis/explanation can stay in English.

7. **`google-genai` SDK, not `google-generativeai`.** Confirm the timeout API by reading the installed source (`pip show google-genai` → site-packages path, then look at `genai.Client` or `types.HttpOptions`). The exact field name (`timeout` vs `timeout_ms`) varies by SDK version.

8. **Merge-agent prompt loading.** Read `prompts/zumo-merge-agent.md` once at module import (not per call). Cache it at module level in `src/merge_agent.py`.

9. **`max_tokens` for the merge agent.** Long sessions can produce >16k tokens of output. Set `max_tokens=32000` for the merge agent's `client.messages.create(...)` call — Opus 4.7 supports it. (Analysis at 16384 stays unchanged.)

10. **Don't break Pyrogram large-file download.** The bot uses Pyrogram for Telegram files >20 MB. Anything under `src/telegram_downloader.py` should stay untouched.

11. **The `_progress_ticker` should keep running through the merge step.** Adding the merge agent inserts another ~30-60 s of API time. The ticker that updates the status message must stay alive across the merge call so the user sees progress.

12. **Stream E hint.** Search `bot.py` for the conversation step that follows session-type selection — that's where the "structured analysis vs knowledge document" buttons live. Look for `InlineKeyboardButton` callback data names that hint at "analysis" / "knowledge" / "doc".
