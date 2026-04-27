# Zumo v3 — Stabilization + Merge Agent + Personalization

> Author: prep session, 2026-04-27.
> Execution: a new Claude Code session uses `KICKOFF-v3.md` to run all of this.

## Why this plan exists

After the v2 launch (Gemini diarization + dual transcription + smart conversation flow) we hit two classes of problems:

1. **Reliability** — the bot can silently hang on Gemini, with no timeout, no JobQueue rescue, and no error path. See [LOGS/logs.1777298121146.log](LOGS/logs.1777298121146.log): bot processed an m4a fine, called `client.models.generate_content` on `gemini-3-flash-preview` at 12:58:40, and then never returned. PTB polling kept running so the bot *looked* alive.
2. **Quality** — the cross-reference between Hebrew AI and Gemini happens implicitly inside the Claude analysis prompt. The dashboard transcript is Hebrew-AI-only with no speaker labels. The user has no clean, verified, speaker-labeled transcript to read.
3. **UX** — generic session-type menu, ambiguous "structured analysis vs knowledge document" choice, generic "Speaker A/B" labels even when the user already typed real names.

## Goals

- Bot never hangs silently. Every external call has a timeout. Every stuck conversation auto-recovers.
- Dashboard transcript = a single merged, speaker-labeled, verified document.
- Session-type menu reflects the user's actual conversation history.
- Output-format choice is self-explanatory.
- Gemini model is the current best for Hebrew/English audio diarization, and gets the user's speaker names directly in its prompt.

## Work streams

### A. Merge Agent (NEW)

**What it does.** A new Claude Opus call that runs *between* the dual transcription and the existing analysis agent. Inputs:
- `hebrew_ai_text` — accurate Hebrew/English words, no speaker labels
- `gemini_text` — speaker-labeled (Speaker A/B/...) with `[MM:SS]` timestamps, may have word-level errors
- `speakers` — the comma-separated names the user typed in the bot at session start
- `session_type`, `language`

Output: one merged transcript:
```
[MM:SS] שם הדובר: …
[MM:SS] שם דובר אחר: …
```
Words come from Hebrew AI (more accurate). Speaker turns + timestamps come from Gemini. Real names replace `Speaker A/B`. Falls back to "דובר 1 / דובר 2" if user didn't supply names.

**Files affected:**
- `src/merge_agent.py` (NEW) — `merge_transcripts(hebrew_ai_text, gemini_text, speakers, session_type, language, api_key) -> str`
- `prompts/zumo-merge-agent.md` (NEW, supplied by user from agent builder)
- `bot.py` `_process_and_reply` — call merge agent before analysis, use its output as `primary_text` and as the saved transcript
- `src/processor.py` `analyze_transcript` — receive the merged transcript instead of raw Hebrew AI; drop the dual-source prompt branch (no longer needed)
- `src/formatter.py` `format_transcript_md` — no shape change, just gets fed the merged text now

**Model:** Claude Opus (latest Opus 4.x — match the project's existing constants).

**Dependency:** user-supplied system prompt from agent builder, saved at `prompts/zumo-merge-agent.md`. Brief for the builder is in [`MERGE-AGENT-BRIEF.md`](MERGE-AGENT-BRIEF.md).

**Acceptance:** open the dashboard for a session with two named speakers — every transcript line begins with `[MM:SS] {real name}:`.

---

### B. Gemini stabilization

**Three sub-tasks:**

1. **Pick the right model.** Current `gemini-3-flash-preview` is preview-tier and has hung in production. New-session Claude runs a WebSearch covering: best Gemini audio model as of late April 2026, Hebrew transcription quality, diarization quality, latency on long audio, Files API ACTIVE-state behavior. Posts a summary, asks user to pick one. Model goes in `src/gemini_transcriber.py:GEMINI_MODEL`.

2. **Pass real speaker names into the Gemini prompt.** Today `DIARIZATION_PROMPT` is generic. Change `transcribe_with_diarization` to accept a `speakers: str` argument (the user-typed comma-separated names), splice them into the prompt:
   ```
   The conversation includes these speakers: <names>.
   Identify which speaker is talking by voice and label lines with their actual names.
   If you detect more speakers than listed, use Speaker D, E, ... for the extras.
   ```
   Wire it through `bot.py:_do_preprocess` → pass `speakers` down.

3. **Stop the hang.** Add:
   - `client.models.generate_content(..., http_options=types.HttpOptions(timeout=600_000))` — 10 min hard cap.
   - After upload, poll `client.files.get(name=uploaded_file.name)` until `state == ACTIVE` (with a 90 s budget) before calling `generate_content`.
   - In `bot.py:_do_preprocess`, change `fh.result()` / `fg.result()` to `result(timeout=...)` and treat timeouts as the existing exception path (already covered by commits `a66b30d` "fall back to Gemini-only" and `2da21c7` "surface failure reason").

**Files affected:** `src/gemini_transcriber.py`, `bot.py`, `src/transcriber.py` (Hebrew AI side: add a `requests` timeout too).

**Acceptance:** simulate a hung Gemini call (e.g. wrong model name) → bot reports a clean error within timeout, falls back to Hebrew-AI-only path, conversation closes properly.

---

### C. JobQueue install

PTBUserWarning in the log says `Ignoring conversation_timeout because the Application has no JobQueue`. The configured timeout is silently disabled. Fix:

- Update `requirements.txt`: `python-telegram-bot[job-queue]==<current pinned version>`.
- Verify the warning disappears on next boot.

**Files affected:** `requirements.txt`, possibly `Dockerfile` if it builds wheels separately.

**Acceptance:** boot log no longer contains `Ignoring conversation_timeout`. A stuck conversation auto-times out per the configured `silence_threshold_seconds`-related setting.

---

### D. Personalized session-type menu

Repo: https://github.com/dartaryan/zumo-data

**Steps in new session:**
1. `git clone` to `c:/tmp/zumo-data` (read-only side directory).
2. Walk the directory tree; identify what each session looked like — folder names contain session type prefixes; analysis files contain rich session-type metadata.
3. Cluster: count occurrences of session types, find recurring patterns, group near-duplicates.
4. Propose a personalized menu (probably 6-10 items, with a "Other" escape hatch). Each item gets:
   - Display label (Hebrew)
   - One-line description (so user knows when to pick it)
   - Mapping to the existing internal `session_type` string the analysis agent expects, OR a new internal value if it's a new category.
5. **Pause for user approval** before patching `bot.py`.
6. After approval, replace the hardcoded keyboard in the session-type step.

**Files affected:** `bot.py` (the conversation flow that asks "what kind of session is this?").

**Acceptance:** menu shows the user's top conversation types from history, with descriptions; "Other" handles edge cases; analysis still works because internal session_type values are mapped correctly.

---

### E. Output-format choice clarity

Today the bot offers two outputs but the labels don't tell the user what each *produces*. Fix in two passes:

1. **Read** the current button labels and surrounding code (grep `analyze_transcript`, button keyboards).
2. **Propose** to user: clearer labels (e.g. "📊 ניתוח עם תובנות" + subtitle, "📚 מסמך ידע ארוך-טווח" + subtitle), and a default per session type so the choice is opt-in rather than required.
3. **Pause for user approval**, then patch.

**Files affected:** `bot.py` (button keyboard + handler).

**Acceptance:** every option button reads as a single self-explanatory sentence; default selection happens automatically based on session type.

---

## Execution order

1. **C (JobQueue)** — trivial, do first so subsequent stuck conversations auto-recover during testing.
2. **B (Gemini stabilization)** — research → pause for model approval → implement timeouts + speaker injection.
3. **A (Merge agent)** — requires user-provided system prompt. Implement once prompt is in place at `prompts/zumo-merge-agent.md`.
4. **D (Personalized menu)** — research → pause for menu approval → patch.
5. **E (Output-format clarity)** — research → pause for label approval → patch.

A and B are independent and could run in parallel; C is trivial; D and E require user pauses.

## Pause points (where new-session Claude must wait)

- After WebSearch on Gemini models → user picks the model.
- Before A is implementable → user pastes system prompt at `prompts/zumo-merge-agent.md`.
- After zumo-data clustering → user approves the proposed menu.
- After E proposal → user approves the new labels.

## What the user provides

| When | Artifact | Path |
|---|---|---|
| Before kickoff | System prompt for merge agent | `prompts/zumo-merge-agent.md` |
| During kickoff | One-line approval on Gemini model | chat |
| During kickoff | Approval on personalized menu | chat |
| During kickoff | Approval on output-format labels | chat |

## Acceptance criteria for the whole release

- [ ] Bot processes a long m4a end-to-end without hanging; on Gemini failure it falls back gracefully.
- [ ] Dashboard transcript shows real speaker names with timestamps.
- [ ] No `JobQueue` warning on boot.
- [ ] Session-type menu is the personalized list approved by the user.
- [ ] Output-format buttons are self-explanatory or auto-defaulted.
- [ ] No Hebrew AI / Gemini call lacks a timeout.
