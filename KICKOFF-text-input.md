# Kickoff prompt — Text Transcript Input Path

> Paste the contents below this line into a fresh Claude Code session opened in `c:/Users/darta/Desktop/projects/zumo`. This stream is independent of v3 and can run before, after, or alongside it.

---

You are picking up a small standalone change to the Zumo bot: adding an entry path that accepts `.md` / `.txt` files as ready-made transcripts, skipping all transcription and the merge agent.

Read these in order before starting:

1. [PLAN-text-input.md](PLAN-text-input.md) — the full plan for this stream. Authoritative.
2. [PLAN-v3.md](PLAN-v3.md) — what's running in parallel; you need to coordinate, not duplicate. Skim the merge-agent stream (A) so you know what `_process_and_reply` may look like post-v3.
3. [bot.py](bot.py) — current `ConversationHandler` structure, the audio entry handlers, and `_process_and_reply` signature.
4. [src/processor.py](src/processor.py) — how `analyze_transcript` consumes a single transcript source today.
5. [src/formatter.py](src/formatter.py) — how `format_transcript_md` shapes the dashboard text.

## Order of work

Use TodoWrite to track these.

### Step 1 — Audit current state
- Open `bot.py:_process_and_reply` and confirm its current shape. Note whether v3's merge agent has been integrated yet (look for imports from `src.merge_agent`).
- Map the `ConversationHandler`: identify entry points, conversation states, and how the audio path stores its file in `context.user_data`.
- Don't change anything yet.

### Step 2 — Draft Hebrew user-facing strings, pause for approval
Draft the following Hebrew messages and present them in a single chat message:

1. **File received notice** — confirms file was accepted and explains the bot will skip audio transcription.
2. **Continuation message** — introduces the upcoming session-type question (so the transition feels natural).
3. **Empty-file rejection** — file decoded fine but is empty.
4. **Decode-failure rejection** — file is not readable text (binary / unsupported encoding).
5. **Oversized-file rejection** — file is >500 KB or >200k characters.

Match the tone of the bot's existing Hebrew strings (search for `await update.message.reply_text` calls in `bot.py` for examples). Then **stop and wait for user approval or edits before patching any code.**

### Step 3 — Implement file handler
Once strings are approved:

- Add a `MessageHandler` to the `ConversationHandler` `entry_points` list:
  ```python
  MessageHandler(
      filters.Document.FileExtension("md") | filters.Document.FileExtension("txt"),
      text_input_handler,
  )
  ```
- Implement `text_input_handler(update, context)`:
  - `await update.message.document.get_file()` → download to a temp path. Files are small; no Pyrogram MTProto branch needed.
  - Read bytes, decode: try `utf-8`, fall back to `utf-8-sig`. If both fail, send the decode-failure rejection and return `ConversationHandler.END`.
  - Apply normalization: strip BOM, normalize line endings (`\r\n` and lone `\r` → `\n`), trim trailing whitespace per line, collapse 3+ blank lines to 2.
  - Validate: empty after strip → empty-file rejection + END. Length checks (>500 KB raw bytes OR >200k chars after normalization) → oversized rejection + END.
  - Store in `context.user_data['text_input'] = normalized_text`.
  - Also store the file name (without extension) in `context.user_data` so the dashboard folder name uses it (mirror the audio path).
  - Send the file-received notice.
  - Transition into the first existing conversation state (the session-type question) — return that state's constant.

### Step 4 — Wire `_process_and_reply` to consume `text_input`
- Add parameter: `text_input: str = ""`.
- At the top of the function, **before** any audio preprocessing or merge logic:
  ```python
  if text_input:
      primary_text = text_input
      original_duration = 0
      # Skip _do_preprocess. Skip merge agent. Run the existing publish + analyze branch.
  ```
- Make the existing publish/analyze branch handle `original_duration = 0` cleanly. Verify `format_transcript_md` and the dashboard renderer hide or sensibly display "0" duration.
- Update the call site that finishes the conversation flow (the handler that runs after the last question is answered) to pass `text_input=context.user_data.get('text_input', '')`.

### Step 5 — Verify
- Re-read the diff against PLAN-text-input.md acceptance criteria.
- Check that the audio path is byte-identical to before (no regression in the existing flow).
- Confirm: when `text_input` is set, no Hebrew AI / Gemini / merge agent code path can run.

## Conventions

- Don't commit. The user reviews the diff and asks for the commit themselves.
- No git push, no destructive operations.
- Match existing Python style: type hints, narrow returns, fail closed on rejection paths.
- Hebrew user-facing text only — no emojis unless they match existing bot UX.
- Don't touch v3-owned files (`src/merge_agent.py`, `prompts/zumo-merge-agent.md`, the merge-agent integration in `_process_and_reply`). If v3 has already added the merge agent, the new `text_input` branch sits *above* it and never reaches it.

## When you're done

Print a single end-of-turn summary:
- Files changed (one bullet each).
- Pause points still open (none expected after Step 2 is approved).
- Suggested next user action (smoke test by uploading a `.md` to the bot / commit / etc.).
