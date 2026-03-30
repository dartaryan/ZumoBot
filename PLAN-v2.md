# Zumo v2 — Implementation Plan

## Vision

Redesign the Zumo pipeline to produce transcripts with accurate speaker attribution and flexible, conversational output control. The current pipeline produces flat text with no speaker labels (pyannote is not installed on Railway). The new pipeline uses Gemini Flash for speaker diarization, Hebrew AI for accurate Hebrew text, and Claude for intelligent synthesis — plus a conversational Telegram flow that lets the user refine what output they want.

---

## Architecture Overview

```
User sends file to Telegram
        │
        ▼
┌─────────────────────┐
│  Step 1: Compress    │  Convert to lean MP3 (ffmpeg)
│  (server-side)       │  Solves: >20MB files, speed
└─────────┬───────────┘
          │
          ▼
┌─────────────────────────────────────────┐
│  Step 2: Dual Transcription (parallel)  │
│                                          │
│  ┌──────────────┐  ┌──────────────────┐ │
│  │  Hebrew AI   │  │  Gemini Flash    │ │
│  │  (accurate   │  │  (speaker        │ │
│  │   Hebrew     │  │   diarization +  │ │
│  │   text)      │  │   rough text)    │ │
│  └──────┬───────┘  └────────┬─────────┘ │
└─────────┼───────────────────┼───────────┘
          │                   │
          ▼                   ▼
┌─────────────────────────────────────────┐
│  Step 3: Interactive Conversation       │
│                                          │
│  Bot already has both results.           │
│  Proposes speakers, type, purpose        │
│  based on Gemini's analysis.             │
│                                          │
│  User confirms/corrects via buttons      │
│  OR free-text conversation.              │
│                                          │
│  Ends with: confirmed speakers, type,    │
│  purpose, output format.                 │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  Step 4: Claude Synthesis               │
│                                          │
│  Receives:                               │
│  1. Hebrew AI transcript (accurate text) │
│  2. Gemini diarization (speaker labels)  │
│  3. User conversation context            │
│                                          │
│  Knows: Gemini labels may be wrong.      │
│  Cross-references content, gender,       │
│  context to produce correct attribution. │
│                                          │
│  Outputs: Deep knowledge document        │
│  (not summary, not quotes — full KB)     │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│  Step 5: Save + Notify                  │
│  Push to GitHub → Dashboard             │
│  Send link to Telegram                  │
│  Progress ticker throughout             │
└─────────────────────────────────────────┘
```

---

## Task Breakdown

### Task 1: Add Gemini transcription module
**File:** `src/gemini_transcriber.py` (NEW)
**What:**
- New module that sends audio to Gemini 2.5 Flash API for transcription with speaker diarization
- Uses `google-genai` Python SDK
- Upload audio via Gemini Files API (for files >20MB support)
- Prompt instructs Gemini to: transcribe with speaker labels (Speaker A, Speaker B, etc.), include timestamps, identify speaker changes
- Returns structured text with speaker labels
- Handles the `GEMINI_API_KEY` env var

**Prompt for Gemini (draft):**
```
Transcribe this audio file. Identify different speakers and label them as Speaker A, Speaker B, etc.
For each speaker change, start a new line with the speaker label.
Format: "Speaker A: [text]"
Include timestamps at natural breaks in [MM:SS] format.
Focus on accurately identifying WHEN speakers change, even if the text isn't perfect.
```

**Dependency:** `pip install google-genai` → add to requirements.txt

### Task 2: Add audio compression step
**File:** `src/audio.py` (EDIT — add function)
**What:**
- New function `compress_for_upload(input_path, output_path, target_mb=20)`
- Converts any audio/video to MP3, targeting a specific file size
- Uses ffmpeg with variable bitrate to hit the target
- Called early in the pipeline, before both transcription services
- This replaces the current compress_audio() which only fires at >25MB

**Also edit:** `pipeline.py` — move compression to happen BEFORE transcription step, not after diarization

### Task 3: Restructure pipeline for parallel dual transcription
**File:** `pipeline.py` (EDIT)
**What:**
- After audio extraction + silence removal + compression:
  - Run Hebrew AI transcription and Gemini transcription **in parallel** (using threads, since both are I/O-bound API calls)
  - Hebrew AI returns: accurate Hebrew text (flat, no speakers)
  - Gemini returns: rough text with speaker labels
- Remove the pyannote diarization step (Step 3) entirely — replaced by Gemini
- Remove the diarizer alignment step (Step 5) — replaced by Claude synthesis
- Keep Zoom VTT alignment as a fallback option
- Store both transcription results for passing to Claude

**New pipeline steps:**
1. Audio extraction (unchanged)
2. Silence removal (unchanged)
3. Compress for upload (moved earlier)
4. **Dual transcription** — Hebrew AI + Gemini in parallel
5. Interactive conversation (delegated to bot.py)
6. **Claude synthesis** — merge both transcriptions with user context
7. Summary generation (unchanged)
8. Format & Save (unchanged)

### Task 4: Smart interactive conversation in Telegram
**File:** `bot.py` (EDIT — major changes to conversation flow)
**What:**
The current flow: rigid buttons only (type → speakers → purpose → format).
The new flow: smart suggestions from Gemini analysis + free-text conversation.

**New conversation states:**
```
WAITING_TYPE           # Button selection (keep existing)
WAITING_SPEAKERS       # Bot SUGGESTS speakers from Gemini, user confirms/corrects
WAITING_PURPOSE        # Bot SUGGESTS purpose from content, user confirms/corrects
WAITING_CONVERSATION   # NEW: free-text back-and-forth with Claude
WAITING_CONFIRM        # NEW: bot proposes final structure, user approves
```

**How WAITING_SPEAKERS changes:**
- After Gemini transcription completes, bot analyzes the speaker labels
- Bot sends: "זיהיתי 2 דוברים בשיחה. לפי התוכן, נראה ש-Speaker A מסביר על X ו-Speaker B שואל שאלות. מי הם?"
- User can type names ("בן ושלהבת") or press skip

**How WAITING_CONVERSATION works (NEW):**
- After basic metadata is set, bot asks: "יש משהו נוסף שחשוב לי לדעת על השיחה הזאת? או שנמשיך?"
- User can type free-text context (like with Mike)
- Bot acknowledges and asks if there's more
- User sends "זהו" / "המשך" / presses a "Continue" button to proceed
- All free-text context gets collected and passed to Claude as part of user_requests

**How WAITING_CONFIRM works (NEW):**
- Bot proposes the output structure: "אני הולך להכין מסמך ידע עם הפרקים הבאים: [list]. מאשר?"
- User approves or corrects
- Then processing begins

**Progress ticker:** Already implemented (from earlier fix) — updates every 30 seconds.

### Task 5: Update Claude synthesis (processor.py + agent prompt)
**File:** `src/processor.py` (EDIT), `zumo-bot-agent.md` (EDIT)
**What:**

**processor.py changes:**
- `analyze_transcript()` now receives TWO transcriptions + conversation context:
  - `hebrew_ai_text` — accurate Hebrew text
  - `gemini_text` — rough text with speaker labels
  - `user_requests` — includes all conversation context from the interactive flow
- Builds a new prompt format that gives Claude both sources

**New input format for Claude:**
```
Session Type: {type}
Speakers: {confirmed speaker names}
Language: {language}
User Requests: {all accumulated context from conversation}

--- HEBREW AI TRANSCRIPT (accurate text, no speaker labels) ---
{hebrew_ai_text}

--- GEMINI TRANSCRIPT (speaker labels, may contain errors) ---
{gemini_text}
```

**zumo-bot-agent.md changes:**
- Add new section: "Dual-Source Processing Protocol"
- Instructions:
  - Hebrew AI text is the SOURCE OF TRUTH for what was said
  - Gemini text is a GUIDE for who said it (speaker labels)
  - Gemini's speaker attribution may be wrong — cross-reference with:
    - Content analysis (who explains vs. who asks)
    - Hebrew gendered verb forms (תיכנסי vs. תיכנס)
    - How speakers address each other
    - Expertise signals
  - When Gemini and content analysis disagree, trust content analysis
  - Map Gemini's "Speaker A/B" to confirmed speaker names from metadata

### Task 6: Environment + Dependencies
**Files:** `requirements.txt`, `src/config.py`, `.env.example`
**What:**
- Add `google-genai` to requirements.txt
- Add `GEMINI_API_KEY` to config.py
- Remove `HUGGINGFACE_TOKEN` from config.py (dead code)
- Update `.env.example`
- Remove pyannote diarization imports from pipeline.py (no longer needed on Railway)

### Task 7: Clean up dead code
**Files:** `src/diarizer.py`, `pipeline.py`
**What:**
- Keep `src/diarizer.py` for local development (optional pyannote usage) but remove it from the main pipeline flow
- Remove diarizer imports and steps from pipeline.py
- The diarizer module stays in the repo but is no longer called by the production pipeline

### Task 8: Redesign dashboard reading experience
**File:** `src/dashboard.py` (EDIT — the HTML/CSS inside the `generate_dashboard` function)
**What:**
Take design inspiration from the Hebrew Markdown Export project: https://github.com/dartaryan/hebrew-markdown-export (live: https://dartaryan.github.io/hebrew-markdown-export/)

The current dashboard content area is cramped and hard to read. The hebrew-markdown-export has a spacious, beautiful reading experience that we want to replicate for the transcript/analysis view.

**Key design changes (content reading area only — don't change the session list/cards):**

1. **Wider content area:** Change `max-width` from 768px to 1000px for the content reading view
2. **Typography upgrade:**
   - Font: Keep Rubik but increase body font to 16px with line-height 1.8
   - H1: 2rem, bold, with a colored bottom border (3px solid, using Zumo's orange accent)
   - H2: 1.5rem, with a lighter bottom border (2px solid)
   - H3: 1.25rem, colored (text-secondary)
   - Paragraphs: line-height 1.8, good spacing between paragraphs
3. **RTL-aware blockquotes:** border-right (not border-left) for RTL, with subtle background, rounded corners
4. **Table styling:** Header row with accent color background, alternating row colors, proper padding
5. **Code blocks:** Dark background (#0d1117), light text, rounded corners (16px)
6. **Lists:** Proper RTL padding (padding-right, not padding-left), generous spacing between items
7. **Bold text:** Should pop — use primary text color for strong elements
8. **Spacing:** More generous margins between sections, headings breathe
9. **Scrollbar:** Styled thin scrollbar matching the theme
10. **Print-friendly:** Clean print stylesheet

**What NOT to change:**
- The session cards/list layout — only the content reading area (transcript + analysis tabs)
- The dark theme color scheme (keep Zumo's existing dark palette)
- The action bar (PDF/Copy/Download)
- Password gate styling

**Also update the PDF export CSS** (line ~701 in dashboard.py) to match:
- Same wider layout (max-width: 700px → 900px for print)
- Same heading styles with colored borders
- Same generous line-height and spacing

**Reference CSS to adapt (from hebrew-markdown-export):**
```css
/* Key rules to adapt for Zumo's reading view */
.preview-content h1 { font-size: 2rem; border-bottom: 3px solid var(--accent); padding-bottom: 0.5rem; }
.preview-content h2 { font-size: 1.5rem; border-bottom: 2px solid var(--accent-secondary); padding-bottom: 0.3rem; }
.preview-content h3 { font-size: 1.25rem; color: var(--text-secondary); }
.preview-content p { margin-bottom: 1em; line-height: 1.8; }
.preview-content blockquote { padding: 1em 1.25em; border-right: 4px solid var(--accent); background: var(--surface); border-radius: 0 12px 12px 0; }
.preview-content table th { background: var(--accent); color: white; }
.preview-content tr:nth-child(even) { background: var(--surface); }
.preview-content pre { background: #0d1117; border-radius: 16px; padding: 1.25em; }
.preview-content ul, .preview-content ol { padding-right: 1.5em; }
.preview-content li { margin-bottom: 0.5em; line-height: 1.7; }
.preview-content strong { font-weight: 700; color: var(--text-primary); }
```

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `src/gemini_transcriber.py` | **NEW** | Gemini Flash transcription with speaker diarization |
| `src/audio.py` | EDIT | Add `compress_for_upload()` function |
| `pipeline.py` | EDIT | Restructure: parallel dual transcription, remove pyannote step |
| `bot.py` | EDIT | Smart suggestions, free-text conversation, confirmation step |
| `src/processor.py` | EDIT | Accept dual transcriptions, build new prompt format |
| `zumo-bot-agent.md` | EDIT | Add dual-source processing protocol |
| `requirements.txt` | EDIT | Add `google-genai` |
| `src/config.py` | EDIT | Add `GEMINI_API_KEY`, remove `HUGGINGFACE_TOKEN` |
| `.env.example` | EDIT | Add `GEMINI_API_KEY`, remove `HUGGINGFACE_TOKEN` |
| `src/dashboard.py` | EDIT | Redesign content reading area (typography, spacing, RTL) |

---

## Execution Order

Tasks should be executed in this order (dependencies matter):

1. **Task 6** — Environment + dependencies (needed by everything else)
2. **Task 1** — Gemini module (no dependencies on other tasks)
3. **Task 2** — Audio compression (no dependencies on other tasks)
4. **Task 3** — Pipeline restructure (depends on Tasks 1, 2)
5. **Task 5** — Claude synthesis update (depends on Task 3 for new data flow)
6. **Task 4** — Telegram conversation redesign (depends on Tasks 3, 5)
7. **Task 7** — Dead code cleanup (last, after everything works)
8. **Task 8** — Dashboard reading experience redesign (independent — can run in parallel with Tasks 1-3)

Tasks 1, 2, and 8 can be done in parallel.
Tasks 6 should be first as it sets up the foundation.

---

## Key Design Decisions

1. **Gemini Flash, not Pro** — Flash is cheaper, faster, and good enough for diarization. We don't need Gemini's text accuracy — Hebrew AI handles that.

2. **Parallel transcription** — Both APIs are I/O-bound. Running them in parallel roughly halves the total wait time.

3. **Claude as synthesizer, not transcriber** — Claude never hears the audio. It receives two text sources and produces the best merge. This is cost-effective and plays to Claude's strength (reasoning, not speech recognition).

4. **Conversational flow is optional** — Users can still use the caption fast-path (`type:training speakers:Ben,Omri`) to skip all questions. The conversation is for when they want to refine the output.

5. **Gemini labels are untrusted** — The prompt and agent instructions explicitly tell Claude that Gemini's speaker attribution is a starting point, not ground truth. Content analysis is the tiebreaker.

6. **Keep pyannote as optional local tool** — Don't delete diarizer.py. It's useful for local development with GPU. Just remove it from the Railway pipeline.

---

## Environment Variables (final state)

### Required:
- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY` ← NEW
- `ZUMO_USER_SLUG`
- `ZUMO_USER_NAME`
- `ZUMO_USER_TELEGRAM_ID`
- `ZUMO_USER_ANTHROPIC_KEY`
- `ZUMO_USER_HEBREW_AI_KEY`
- `ZUMO_USER_LANGUAGE`
- `GITHUB_TOKEN`
- `GITHUB_REPO`
- `GITHUB_BRANCH`
- `DASHBOARD_BASE_URL`

### Optional:
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` (large file MTProto)
- `ZOOM_ACCOUNT_ID` / `ZOOM_CLIENT_ID` / `ZOOM_CLIENT_SECRET` (Zoom downloads)

### Removed:
- `HUGGINGFACE_TOKEN` (was unused — pyannote not installed on Railway)
