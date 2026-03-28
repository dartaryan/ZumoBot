# Zumo -- Handoff for Next Agent

> Written: 2026-03-28
> Author: Claude Opus (session with Ben Akiva)
> Project: `c:\Users\darta\Desktop\פרויקטים\zumo`

---

## What Changed This Session

### Telegram Bot -- DONE (Priority 4)

Built `bot.py` using `python-telegram-bot`, following the same pattern as `tiktok-pipeline/bot.py`.

#### What Was Added

| File | Change |
|------|--------|
| `bot.py` | New -- Telegram bot, 3 handlers (start, file, zoom URL) |
| `src/users.py` | Added `find_user_by_telegram_id()` -- scans all user JSONs |
| `requirements.txt` | Added `python-telegram-bot>=21.0` |
| `.env.example` | Added `TELEGRAM_BOT_TOKEN` |

#### How It Works

1. User sends audio/video file (or voice/video note) to the bot via Telegram
2. Bot looks up `telegram_user_id` across all `users/*.json` files to authenticate
3. Bot downloads the file to a temp directory
4. Bot calls `process_file()` from `pipeline.py` in a thread executor (non-blocking)
5. Pipeline runs the full 8 steps (extract, silence removal, diarize, transcribe, analyze, save)
6. Bot replies with duration, transcript length, and dashboard URL
7. Temp files cleaned up

#### Auth Model

No env-var allowlist. Auth is purely by `telegram_user_id` field in `users/*.json`. If a user's Telegram ID isn't in any user config, they get "Access denied" with their ID shown (so you can add them).

`find_user_by_telegram_id(telegram_id)` returns `(username, UserConfig)` or `None`.

#### Caption Metadata

Users can set session metadata in the file's caption:

```
type:training speakers:Ben,Omri lang:he
```

All optional. Defaults: `type:other`, no speakers, language from user config.

#### Zoom URL Support

Text messages containing Zoom recording links (`zoom.us/rec/share/...` or `zoom.us/rec/play/...`) are detected and processed. Passcode extracted from `?pwd=` query param if present. Default session type: `team-meeting`.

#### Handlers

| Handler | Trigger | Purpose |
|---------|---------|---------|
| `/start` | Command | Shows help text with session types |
| File handler | Audio, video, voice, video note, document | Downloads + runs pipeline |
| Text handler | Non-command text | Checks for Zoom URLs |

#### Status Messages

No emojis (Ben's rules). Uses bracket markers:
- `[>]` -- in progress
- `[=]` -- done
- `[x]` -- error

#### Not Tested End-to-End

Syntax verified. The bot requires `TELEGRAM_BOT_TOKEN` in `.env` and valid GitHub credentials. To test:

```bash
# Add bot token to .env
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env

# Run the bot
python bot.py
```

Then send an audio file to the bot on Telegram.

#### Known Limitations

- Telegram file size limit is 20MB for downloads via Bot API. For larger files, users need to use the CLI pipeline or send a Zoom link.
- `process_file()` prints progress to stdout (server console), not to the Telegram chat. The user sees download -> processing -> done. No step-by-step progress.
- `Document.ALL` filter catches all documents; non-media extensions are rejected inside the handler.

---

### Previous: Agent Prompt Integration -- DONE (Priority 2)

See git history. Replaced hardcoded analysis prompt with `zumo-bot-agent.md`.

### Previous: Speaker Diarization -- DONE (Priority 1)

See git history (commit `eefdf03`).

### Previous: Dashboard HTML Generator -- DONE (Priority 3)

See git history (commit `13e139b`).

---

## What's NOT Done Yet

### Priority 5: Deployment

Deploy the bot and dashboard to production.

#### Bot Deployment (Railway)

1. Create a Railway project with the zumo repo
2. Set environment variables in Railway dashboard:
   - `TELEGRAM_BOT_TOKEN` -- from @BotFather on Telegram
   - `GITHUB_TOKEN` -- PAT with repo + contents write access
   - `GITHUB_REPO` -- `owner/zumo-data` format
   - `GITHUB_BRANCH` -- `main`
   - `HUGGINGFACE_TOKEN` -- for speaker diarization (optional, heavy)
3. Start command: `python bot.py`
4. No port needed -- bot uses polling, not webhook
5. Railway plan: Starter ($5/mo) should be enough for 5 users

#### Diarization on Railway

pyannote.audio pulls in torch (~2GB). Railway's free tier has 512MB RAM. Options:
- **Option A**: Skip diarization on Railway (bot runs with `skip_diarization=True`). Simplest.
- **Option B**: Use a larger Railway plan with 2GB+ RAM. Install torch CPU-only to save space.
- **Option C**: Run diarization as a separate service (overkill for 5 users).

Recommendation: Option A for now. Diarization is nice-to-have, not critical.

#### Dashboard Deployment (Netlify)

1. The pipeline saves sessions to a GitHub repo (`GITHUB_REPO`)
2. `src/dashboard.py` generates a self-contained `index.html` per user
3. Two approaches:
   - **Static**: Run `python pipeline.py --user X --dashboard` to regenerate HTML, commit to a `gh-pages` branch or separate repo, deploy via Netlify
   - **GitHub Pages**: Enable GitHub Pages on the data repo directly (simpler)
4. Set `DASHBOARD_BASE_URL` in `.env` to the deployed URL (e.g., `https://zumo.netlify.app`)
5. The bot will then return clickable dashboard links with session anchors

#### Netlify Config (if using Netlify)

```toml
# netlify.toml
[build]
  publish = "output/"
  command = "echo 'static site'"
```

Or use `_redirects` for pretty URLs.

#### Domain

No custom domain yet. Use `zumo-XXXX.netlify.app` or `owner.github.io/zumo-data` for now.

### Priority 6: Onboarding Guide

Markdown doc for new users. Should cover:
- How to get a Telegram bot token from @BotFather
- How to create a `users/username.json` with their API keys
- How to find their Telegram user ID (forward a message to @userinfobot)
- How to use the bot (send files, captions, Zoom links)
- How to use the CLI pipeline for large files

---

## Key Files to Read First

1. `bot.py` -- Telegram bot (Priority 4, just built)
2. `pipeline.py` -- Full 8-step pipeline flow, `process_file()` function
3. `src/users.py` -- User loading + `find_user_by_telegram_id()`
4. `src/config.py` -- Env vars, session types, model config
5. `zumo-bot-agent.md` -- System prompt for analysis step
6. `src/dashboard.py` -- HTML dashboard generation

---

## Ben's Preferences (Unchanged)

- No emojis in UI or outputs. Geometric shapes OK.
- Hebrew for content, English for code/technical.
- Don't over-engineer. 5 users max. Keep it simple.
- Dark mode only. Rubik font. Very rounded. Thick strokes.
- He builds cathedrals when houses would do -- nudge him to ship.
