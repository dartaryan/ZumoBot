# Zumo — Implementation Plan

> Written: 2026-03-30
> Project: `c:\Users\darta\Desktop\פרויקטים\zumo`

---

## Task Queue

Execute tasks in order. Pick the first task with status `PENDING`, execute it, then change its status to `DONE`.

| # | Task | Status | Files Touched |
|---|------|--------|---------------|
| 1 | Agent 4: API Cleanup + Setup Docs | DONE | requirements.txt, bot.py, .env.example, SETUP.md |
| 2 | Agent 1: Large File Handling | DONE | requirements.txt, src/telegram_downloader.py, bot.py, .env.example |
| 3 | Agent 2: Interactive Questions + KB Mode | DONE | bot.py, zumo-bot-agent.md, pipeline.py, src/processor.py |
| 4 | Agent 3: Dashboard Download/Copy/Export | DONE | src/dashboard.py |

---

## Task 1: API Cleanup + Setup Documentation

### Problem
The project has accumulated debug logging, unclear documentation, and no setup guide. Needs cleanup for maintainability and new user onboarding.

### Instructions

Read each file before modifying it.

#### 1. Clean up `requirements.txt`
Reorganize into clearly labeled sections:

```
# === Core (required) ===
anthropic>=0.49.0
requests>=2.31
PyGithub>=2.5.0
python-dotenv>=1.0.0
python-slugify>=8.0.0
python-telegram-bot>=21.0

# === Large file support (recommended — enables downloading files > 20MB) ===
pyrogram>=2.0.0

# === Zoom recording download (optional) ===
yt-dlp>=2024.0.0
webvtt-py>=0.5.0

# === Speaker diarization (optional — heavy, pulls in torch ~2GB) ===
# Not included by default — the pipeline skips diarization when not installed.
# To install locally:
#   pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
#   pip install "pyannote.audio>=3.1,<4.0" "huggingface_hub<0.24"
```

#### 2. Remove debug boot logging from `bot.py`
Remove the boot debug block near the bottom of `main()` — the lines that print `[BOOT]` messages with env vars and user configs. These were added for Railway debugging.

Keep: `logger.info("Zumo bot is running...")`
Remove: All `print(f"[BOOT]...")` lines and their surrounding loop.
Clean up: Any imports that become unused after removal (like `sys`, `list_users`, `load_user` — but verify they're not used elsewhere in the file first).

#### 3. Rewrite `.env.example`
Read the current one first. Rewrite it with clear sections and concise comments:

```
# ============================================================
# Zumo Bot — Environment Variables
# ============================================================
# Copy this file to .env and fill in your values.

# --- Required ---
TELEGRAM_BOT_TOKEN=         # From @BotFather on Telegram
GITHUB_TOKEN=               # GitHub PAT with repo contents write permission
GITHUB_REPO=owner/repo      # GitHub data repo (e.g., dartaryan/zumo-data)

# --- User Config (single user via env vars) ---
# For multiple users, create JSON files in users/ directory instead.
ZUMO_USER_SLUG=             # URL-safe identifier (e.g., ben-akiva)
ZUMO_USER_NAME=             # Display name
ZUMO_USER_TELEGRAM_ID=      # Telegram user ID (send /start to @userinfobot)
ZUMO_USER_HEBREW_AI_KEY=    # API key from hebrew-ai.com
ZUMO_USER_ANTHROPIC_KEY=    # Anthropic API key (sk-ant-...)
ZUMO_USER_LANGUAGE=he       # Default: he (Hebrew) or en (English)
ZUMO_USER_PASSWORD_HASH=    # SHA-256 hash of web dashboard password (optional)

# --- Optional ---
GITHUB_BRANCH=main
DASHBOARD_BASE_URL=                     # e.g., https://zumobot.netlify.app
ZUMO_USER_SILENCE_THRESHOLD=30          # Min silence duration in seconds

# --- Large File Support (recommended) ---
# Required for downloading Telegram files > 20MB.
# Get from https://my.telegram.org → API development tools
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# --- Zoom API (optional) ---
ZOOM_ACCOUNT_ID=
ZOOM_CLIENT_ID=
ZOOM_CLIENT_SECRET=

# --- Speaker Diarization (optional) ---
HUGGINGFACE_TOKEN=
```

#### 4. Create `SETUP.md`
Create a concise, practical setup guide. No marketing language. Structure:

**What You Need** — table of credentials with Required/Recommended/Optional labels and where to get each one.

**Quick Start** — numbered steps: clone, install, configure .env, init GitHub repo, run.

**Adding a User** — create `users/slug.json` with example JSON, explain each field briefly. Include how to get Telegram ID and generate password hash.

**Deploy to Railway** — brief: push to GitHub, create Railway project, set env vars, auto-builds from Dockerfile.

**Netlify Dashboard** — brief: create site connected to data repo, set DASHBOARD_BASE_URL.

### Constraints
- Do NOT modify pipeline.py, dashboard.py, processor.py, or the agent prompt
- Do NOT remove any functional code — only debug logging
- Do NOT delete or modify user JSON files
- Do NOT change .gitignore
- SETUP.md should be under 150 lines — concise and practical

---

## Task 2: Large File Handling

### Problem
When users send audio files > 20MB via Telegram (e.g., 29.9MB m4a from iPhone), the bot fails with "File is too big". The Telegram Bot API HTTP interface has a hard 20MB download limit on `bot.get_file()`.

### Instructions

#### 1. Add pyrogram dependency
In `requirements.txt`, add `pyrogram>=2.0.0` in the "Large file support" section (should already exist from Task 1).

#### 2. Create `src/telegram_downloader.py`
A helper module that downloads Telegram files via MTProto for large files:

- Read env vars: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_BOT_TOKEN`
- Define `MAX_BOT_API_SIZE = 20 * 1024 * 1024`
- Function `download_large_file(file_id, chat_id, message_id, dest_path)`:
  - Uses `pyrogram.Client` with `in_memory=True` (no session files)
  - Authenticates as bot (`api_id` + `api_hash` + `bot_token`)
  - Downloads the message's file to `dest_path`
  - Returns the Path

#### 3. Modify `bot.py` handle_file function
At the download section (around line 140), replace the simple download with size-aware logic:

- Get `file_size` from `file_obj.file_size`
- If `file_size > 20MB`:
  - Edit status message: `"[>] Large file (X MB) — downloading via MTProto..."`
  - Call `download_large_file()` with `file_obj.file_id`, `msg.chat_id`, `msg.message_id`, `file_path`
  - If it fails (missing env vars or other error): show helpful error message explaining what env vars are needed
- If `file_size <= 20MB` (or unknown):
  - Download normally via `get_file()` + `download_to_drive()` (current behavior)

#### 4. Update `.env.example`
Add the new env vars (if not already present from Task 1):
```
# Large file support (optional — needed for files > 20MB)
# Get from https://my.telegram.org → API development tools
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
```

### Constraints
- Do NOT change pipeline.py, dashboard.py, or any other files besides the ones listed
- Do NOT modify any other functionality
- Keep the existing normal download path for files <= 20MB
- The pyrogram client must use `in_memory=True` (no session files on disk)
- Handle the case where pyrogram is not installed: catch `ImportError` gracefully and show a helpful message

---

## Task 3: Interactive Questions + Knowledge Base Mode

### Problem
Currently, when a user sends an audio file, the bot processes it immediately with default settings. Two changes needed:
1. Bot should ask questions before processing
2. Output should support a "Knowledge Base" mode (professional reference document, no speaker quotes)

### Instructions

#### Part 1: Interactive Flow in `bot.py`

Replace the current direct-processing approach with a `ConversationHandler`.

**States:**
- `WAITING_TYPE` — Bot received file, asking for session type
- `WAITING_SPEAKERS` — Got type, asking for speakers
- `WAITING_PURPOSE` — Got speakers, asking for purpose/goal
- `WAITING_FORMAT` — Got purpose, asking for output format

**Flow:**
1. User sends audio/video file
2. Bot saves file to temp dir, stores path + file_name in `context.user_data`
3. Bot replies with inline keyboard asking session type:
   - ישיבת צוות (Team Meeting)
   - הדרכה (Training)
   - שיחת לקוח (Client Call)
   - שיחת טלפון (Phone Call)
   - אימון (Coaching)
   - אחר (Other)
   - דלג (Skip) → defaults to "other"
4. User taps type → bot stores it, asks: "מי הדוברים? (שמות מופרדים בפסיק, או לחץ דלג)"
   - Inline keyboard with just "דלג (Skip)" button
   - Or user types names as text
5. User provides speakers or skips → bot asks: "מה המטרה או הפוקוס המיוחד? (או לחץ דלג לניתוח מלא)"
   - Inline keyboard with "דלג (Skip)" button
   - Or user types their goal
6. User provides goal or skips → bot asks output format with inline keyboard:
   - "מסמך מקור ידע (Knowledge Base)" → sets format to "knowledge-base"
   - "ניתוח מובנה (Structured Analysis)" → sets format to "standard"
7. Bot starts processing with all collected metadata

**Implementation details:**
- Use `ConversationHandler` from `telegram.ext` with `CallbackQueryHandler` for inline buttons and `MessageHandler` for text input
- Store in `context.user_data`: `tmp_dir`, `file_path`, `file_name`, `session_type`, `speakers`, `purpose`, `output_format`
- The purpose text goes into the `User Requests` field when calling `process_file` → `analyze_transcript`
- The format choice (`"knowledge-base"` or `"standard"`) is prepended to User Requests: e.g., `"knowledge-base: focus on methodology"` or `"standard: full analysis"`
- Update the `process_file` call to pass `user_requests` through to `analyze_transcript`
- In `processor.py`, modify `analyze_transcript` to accept and pass `user_requests` to the Claude prompt
- Add `/cancel` command handler inside the `ConversationHandler` to abort and clean up
- Add `ConversationHandler.TIMEOUT` with `timeout=600` (10 minutes) and a timeout handler that cleans up
- Keep caption-based metadata as a fast-path: if caption contains `type:` OR `speakers:`, skip the interactive flow and process directly

The `ConversationHandler` should be registered INSTEAD of the current `MessageHandler` for files. The `handle_zoom_link` handler stays separate (Zoom links don't use the interactive flow).

**Passing user_requests through the pipeline:**
- `process_file()` in `pipeline.py` needs a new parameter: `user_requests` (default: `"full analysis"`)
- This gets passed to `analyze_transcript()` in `processor.py`
- `analyze_transcript()` already builds a prompt with `"User Requests: {value}"` — just needs to receive it as a parameter instead of hardcoding `"full analysis"`
- Read the current `analyze_transcript` function in `src/processor.py` to understand the current prompt structure

#### Part 2: Knowledge Base Mode in `zumo-bot-agent.md`

Add a new section BEFORE "Session Type Extraction Strategies" (before line 93). Title: `## Output Modes`

**Content of the new section:**

**Standard Mode (default):** The current behavior. Structured analysis with speaker attribution, quotes, and comprehensive extraction.

**Knowledge Base Mode:** Activated when User Requests contains `"knowledge-base"` or `"מסמך מקור ידע"`.

Rules for KB mode:
1. No speaker quotes — never use blockquotes with speaker attribution
2. No conversational attribution — don't write "Ben said" or "the trainer explained"
3. Professional, academic tone — reads like a textbook, methodology guide, or official curriculum
4. Preserve ALL information — KB mode changes the form, not the depth
5. Structure by topic/subject, not by conversation flow

Type-specific KB adaptations:
- Training → Curriculum document (modules, methodology, exercises as instructions, examples as case studies)
- Team Meeting → Decisions & plans document (policy statements, project plan, no "who said what")
- Client Call → Requirements specification (priorities, timeline, risk register)
- Phone Call → Information sheet (data by category, checklists, reference tables)
- Coaching → Development guide (principles, tools with instructions, development plan)
- Other → Reference document (topic chapters)

Also update Step 5 (User Request Overlay) to mention: if User Requests contains "knowledge-base", apply KB mode rules on top of the type-specific extraction.

### Constraints
- Modify ONLY: `bot.py`, `zumo-bot-agent.md`, `pipeline.py` (add `user_requests` param), `src/processor.py` (accept `user_requests` param)
- Do NOT touch `dashboard.py`, `storage.py`, or other files
- Do NOT remove existing functionality
- Caption-based metadata fast-path must still work
- Zoom link handler stays unchanged (no interactive flow)
- All inline keyboard button labels in Hebrew with English in parentheses

---

## Task 4: Dashboard Download/Copy/Export

### Problem
The dashboard only displays content. Users need: (1) Download as .md, (2) Copy .md to clipboard, (3) Export to PDF with white background and dark orange styling.

### Instructions

Read `src/dashboard.py` first to understand the `_TEMPLATE` string structure.

#### 1. Action bar HTML
Inside each card body (in the JavaScript that builds `card.innerHTML`), add an action bar div BETWEEN the tabs div and the content-area div:

```html
<div class="action-bar">
    <button class="action-btn" onclick="event.stopPropagation();downloadMd(INDEX)">
        <!-- download SVG icon -->
        <span>Download</span>
    </button>
    <button class="action-btn" onclick="event.stopPropagation();copyMd(INDEX)">
        <!-- copy SVG icon -->
        <span>Copy</span>
    </button>
    <button class="action-btn" onclick="event.stopPropagation();exportPdf(INDEX)">
        <!-- print/PDF SVG icon -->
        <span>PDF</span>
    </button>
</div>
```

Replace `INDEX` with the actual loop variable (`i`).

#### 2. CSS (add to the `<style>` section)

```css
.action-bar{display:flex;gap:8px;padding:8px 22px;border-top:1px solid var(--border)}
.action-btn{display:flex;align-items:center;gap:6px;padding:8px 16px;border:1px solid var(--border);border-radius:12px;background:var(--bg-elevated);color:var(--text-secondary);font-size:12px;font-weight:500;font-family:inherit;cursor:pointer;transition:all 200ms}
.action-btn:hover{background:var(--bg-hover);color:var(--text-primary);border-color:var(--border-strong)}
.action-btn svg{width:14px;height:14px}
.action-btn.copied{color:var(--success);border-color:var(--success)}
```

Mobile responsive (add inside the existing `@media max-width 640px` block):
```css
.action-bar{padding:6px 16px;gap:6px}
.action-btn{padding:6px 12px;font-size:11px}
```

#### 3. SVG Icons (inline, stroke-based, matching existing icon style)

Download:
```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
```

Copy:
```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect width="13" height="13" x="9" y="9" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
```

PDF/Print:
```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect width="12" height="8" x="6" y="14"/></svg>
```

#### 4. JavaScript functions (add to the `<script>` section)

**`getActiveContent(i)`** — Returns `{text, label}` — the raw markdown of whichever tab is active. Check if the analysis tab exists and is active; if so return `{text: s.analysis, label: 'analysis'}`, otherwise return `{text: s.transcript, label: 'transcript'}`.

**`downloadMd(i)`** — Get active content via `getActiveContent(i)`. Create Blob with type `'text/markdown;charset=utf-8'`. Create temporary `<a>` element with download attribute = `session_id + '-' + label + '.md'`. Click it, then clean up.

**`copyMd(i)`** — Get active content. Use `navigator.clipboard.writeText()`. On success: add `'copied'` class to the Copy button, change span text to "Copied", revert after 2 seconds.

**`exportPdf(i)`** — Get active content and session data. Render markdown to HTML using `renderMd(data.text)` in the parent window BEFORE opening the new window. Open new window with `window.open('', '_blank')`. Write self-contained HTML with Google Fonts (Rubik) link, print-optimized CSS, session metadata line at top, the pre-rendered HTML, and auto-trigger `window.print()` on load.

#### PDF Color Scheme (CRITICAL — must be accessible):
```css
body { background: #fff; color: #1C1917; }
h1 { color: #C2410C; }
h2 { color: #C2410C; border-bottom: 2px solid #FDBA74; padding-bottom: 6px; }
h3 { color: #9A3412; }
blockquote { border-right: 3px solid #F97316; color: #44403C; }
th { color: #9A3412; background: #FFF7ED; border-bottom: 2px solid #FDBA74; }
td { border-bottom: 1px solid #FED7AA; }
tr:nth-child(even) td { background: #FFFBEB; }
code { background: #FFF7ED; color: #9A3412; }
a { color: #EA580C; }
hr { background: #FDBA74; }
```

Font: Rubik. Max-width: 700px. Line-height: 1.8. Padding: 40px 32px. `@media print`: body padding 0, `@page` margin 2cm.

### Constraints
- ONLY modify `src/dashboard.py` (the `_TEMPLATE` string)
- Do NOT add external libraries or CDNs (except Google Fonts which is already there)
- Reuse existing functions: `renderMd()`, `inl()`, `esc()`
- The action bar is INSIDE `card-body` — only visible when expanded
- The dark theme stays for the dashboard — white/orange is ONLY for PDF export
- All colors must pass WCAG AA accessibility on their respective backgrounds
- Hebrew RTL direction in the PDF (`dir="rtl"` on html element)
