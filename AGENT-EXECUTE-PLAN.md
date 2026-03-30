# Agent Prompt: Execute Zumo v2 Implementation Plan

You are implementing a major upgrade to the Zumo Telegram bot. Read and execute the plan in `PLAN-v2.md` in this repository.

## Context

Zumo is a Telegram bot that transcribes audio/video recordings into structured markdown documents. It runs on Railway (Python 3.11, Docker) with a Telegram bot interface.

**The problem:** The current pipeline produces flat transcripts with NO speaker labels. The pyannote diarization library is not installed on Railway (too heavy — requires PyTorch ~2GB).

**The solution:** Use Gemini 2.5 Flash for speaker diarization (who said what) alongside Hebrew AI for accurate Hebrew text. Claude merges both into a final document with correct speaker attribution. The Telegram bot gets a smarter conversational flow.

## Your Instructions

1. **Read `PLAN-v2.md` first** — it contains the complete task breakdown, execution order, file change summary, and architecture diagram.

2. **Execute tasks in the order specified** in the plan (Task 6 → 1 → 2 → 3 → 5 → 4 → 7). Tasks 1 and 2 can be done in parallel.

3. **Before editing any file, read it first.** Understand the existing code before modifying it.

4. **Key files to read before starting:**
   - `pipeline.py` — the main 8-step pipeline (will be restructured)
   - `bot.py` — Telegram bot with interactive conversation flow (will be expanded)
   - `src/processor.py` — Claude API integration (will receive dual transcriptions)
   - `zumo-bot-agent.md` — Claude's system prompt (will get dual-source protocol)
   - `src/transcriber.py` — Hebrew AI integration (reference for how transcription modules work)
   - `src/audio.py` — audio processing functions (will get new compression function)
   - `src/config.py` — env var configuration (will add GEMINI_API_KEY)
   - `src/dashboard.py` — HTML dashboard generator (will get reading experience redesign)
   - `requirements.txt` — dependencies (will add google-genai)
   - `.env.example` — env var template (will update)

5. **Important constraints:**
   - Python 3.11 on Railway (Docker)
   - Use `google-genai` SDK (NOT `google-generativeai` — use the newer SDK)
   - Gemini model: `gemini-2.5-flash` for transcription
   - Claude model: `claude-sonnet-4-6` for analysis (already configured)
   - The bot uses `python-telegram-bot` async library
   - `run_in_executor` for blocking calls (Hebrew AI uses `requests`, which is synchronous)
   - Gemini's `google-genai` SDK is async-native — can be awaited directly or run in executor
   - Keep the caption fast-path working (users can still send `type:training speakers:Ben,Omri` to skip interactive flow)
   - Keep Zoom link processing working (separate handler in bot.py)
   - For Task 8 (dashboard redesign): only change the content reading area CSS, NOT the session list/cards, dark theme colors, action bar, or password gate. Take inspiration from https://github.com/dartaryan/hebrew-markdown-export (the preview-content CSS rules for typography, spacing, headings, tables, blockquotes, lists). The repo is public — read the CSS from the source.

6. **Testing approach:**
   - After each task, verify the code is syntactically correct (no import errors, no missing references)
   - The full integration test happens on Railway after deployment
   - Focus on clean, working code — not perfection

7. **Commit after each task** with a clear commit message describing what changed.

## What Success Looks Like

After all tasks are complete:
- User sends an audio file to the Telegram bot
- Bot compresses it to MP3
- Bot runs Hebrew AI + Gemini Flash in parallel
- Bot presents smart suggestions (speakers detected, purpose guessed) and allows free-text conversation
- User confirms/corrects and approves
- Claude receives both transcriptions + user context, produces a deep knowledge document with correct speaker attribution
- Document appears on the dashboard
- Progress ticker shows throughout

## Env Vars Available on Railway

```
TELEGRAM_BOT_TOKEN=***
GEMINI_API_KEY=***
ZUMO_USER_SLUG=ben-akiva
ZUMO_USER_NAME=Ben Akiva
ZUMO_USER_TELEGRAM_ID=***
ZUMO_USER_ANTHROPIC_KEY=***
ZUMO_USER_HEBREW_AI_KEY=***
ZUMO_USER_LANGUAGE=he
GITHUB_TOKEN=***
GITHUB_REPO=***
GITHUB_BRANCH=main
DASHBOARD_BASE_URL=***
TELEGRAM_API_ID=***
TELEGRAM_API_HASH=***
ZOOM_ACCOUNT_ID=***
ZOOM_CLIENT_ID=***
ZOOM_CLIENT_SECRET=***
```
