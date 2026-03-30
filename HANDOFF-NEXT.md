# Zumo -- Handoff for Next Agent

> Written: 2026-03-28
> Author: Claude Opus (session with Ben Akiva)
> Project: `c:\Users\darta\Desktop\פרויקטים\zumo`
> Repo: https://github.com/dartaryan/ZumoBot

---

## Current Status: BLOCKED on Railway env var issue

The deployment infrastructure is built but the bot can't start because one env var (`ZUMO_USER_HEBREW_AI_KEY`) returns empty despite being set in Railway's UI. Other env vars in the same pattern (ZUMO_USER_ANTHROPIC_KEY, ZUMO_USER_SLUG, etc.) work fine.

---

## What Was Done This Session

### Deployment Infrastructure (Priority 5) -- PARTIALLY DONE

#### Files Created
| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.11-slim + ffmpeg, no torch/pyannote |
| `.dockerignore` | Excludes output/, .env, .git, design-system/ |
| `railway.toml` | Dockerfile builder, restart on failure |

#### Files Modified
| File | Change |
|------|---------|
| `requirements.txt` | Commented out pyannote/huggingface (optional, skipped gracefully) |
| `src/users.py` | Added `_ensure_users_from_env()` -- creates user JSON from individual `ZUMO_USER_*` env vars or `USERS_CONFIG` JSON. Includes extensive boot logging to stderr. |
| `src/dashboard.py` | Added `_load_sessions_from_github()`, `generate_dashboard_from_github()` -- reads sessions from GitHub API to generate dashboard HTML |
| `src/storage.py` | Added `save_dashboard_to_github()` -- pushes dashboard HTML to GitHub after each session. `save_session()` now auto-regenerates dashboard. |
| `pipeline.py` | Passes `user_name` and `pw_hash` to `save_session()` |
| `src/config.py` | Fixed `SONNET_MODEL` to `claude-sonnet-4-6` |
| `bot.py` | Added extensive boot diagnostics (ZUMO env vars, user loading, etc.) to stderr |
| `.env.example` | Added `DASHBOARD_BASE_URL`, `USERS_CONFIG`, `ZUMO_USER_*` docs |

#### External Setup (DONE)
- **GitHub data repo**: `dartaryan/zumo-data` (private) -- initialized with README, has session data from a successful test run
- **Netlify**: `zumobot.netlify.app` -- connected to `dartaryan/zumo-data`, serves dashboard HTML
- **Railway**: Project created, connected to `dartaryan/ZumoBot`, Dockerfile builds successfully

#### Railway Env Vars (currently set)
```
DASHBOARD_BASE_URL=https://zumobot.netlify.app
GITHUB_BRANCH=main
GITHUB_REPO=dartaryan/zumo-data
GITHUB_TOKEN=<PAT with repo contents write>
HUGGINGFACE_TOKEN=<optional>
TELEGRAM_BOT_TOKEN=<from @BotFather>
ZUMO_USER_ANTHROPIC_KEY=sk-ant-api03-...
ZUMO_USER_HEBREW_AI_KEY=sk_4b6zqbvj4phavrp2_f2a771606c5b62379bd4
ZUMO_USER_LANGUAGE=he
ZUMO_USER_NAME=Ben Akiva
ZUMO_USER_SLUG=ben-akiva
ZUMO_USER_TELEGRAM_ID=8553241584
```

---

## THE BLOCKER

### Problem
`os.getenv("ZUMO_USER_HEBREW_AI_KEY")` returns `""` in the Railway container, even though:
1. The variable IS set in Railway's UI (screenshot confirmed, value visible)
2. Other `ZUMO_USER_*` vars work fine (ANTHROPIC_KEY, SLUG, NAME, TELEGRAM_ID all load correctly)
3. The code is identical for all vars: `os.getenv("ZUMO_USER_HEBREW_AI_KEY", "")`

### What We Tried
1. `USERS_CONFIG` single JSON env var -- Railway truncated it (char 361 limit?)
2. Individual `ZUMO_USER_*` env vars -- most work, HEBREW_AI_KEY doesn't
3. Multiple redeploys
4. Added debug logging showing all ZUMO_* env vars (but latest code may not have deployed)

### Theories
- Railway may have a character limit or encoding issue with certain env var values
- The value `sk_4b6zqbvj4phavrp2_f2a771606c5b62379bd4` might contain a character Railway doesn't like
- Railway might cache env vars and not update on restart vs rebuild
- The "Redeploy" button re-deploys old code, not the latest commit -- need "Trigger Deploy" or a new push

### Next Steps to Debug
1. Use Railway's **Raw Editor** to inspect the actual env vars being passed
2. Try renaming the var (e.g., `HEBREW_AI_KEY` instead of `ZUMO_USER_HEBREW_AI_KEY`)
3. Try setting the value to something simple (like `test123`) to rule out value encoding
4. Check if the latest commit (`10995c0`) is actually deployed (the ZUMO env var dump wasn't showing)
5. Alternative: skip env vars entirely -- store user config in the `zumo-data` GitHub repo and fetch on startup

---

## Secondary Issues

### 409 Conflict on Startup
Telegram `getUpdates` returns 409 because Railway briefly runs old + new containers during deploy transitions. This resolves in ~20 seconds. Not a real problem -- can be suppressed with an error handler.

### Dashboard Not Loading on Netlify
`zumobot.netlify.app` shows "Page not found". The root has no index.html -- the dashboard is at `zumobot.netlify.app/ben-akiva/`. Needs either:
- A redirect from root to the user dashboard
- Ben to bookmark `zumobot.netlify.app/ben-akiva/`

### Zoom Links
"This recording does not exist" -- the specific Zoom recordings Ben tested with are expired/deleted. Not a code bug. Test with a valid recording.

### Dashboard Password
`web_password_hash` must be a SHA-256 hex string, not a plain number. Hash of `305065575` is: `45087792706dfed4db7cf6b004a57896ebf03988b58e4f0a7e79f9b595080eaa`. Set via `ZUMO_USER_PASSWORD_HASH` env var.

---

## Architecture Overview

```
[Telegram User] --sends file--> [Bot on Railway]
                                      |
                                 process_file()
                                      |
                          [Hebrew AI] transcribe
                          [Claude] analyze
                                      |
                              save to GitHub
                              (dartaryan/zumo-data)
                                      |
                          push index.html dashboard
                                      |
                              [Netlify serves it]
                              zumobot.netlify.app
```

---

## Key Files to Read First

1. `src/users.py` -- User config loading + `_ensure_users_from_env()` (the problematic area)
2. `bot.py` -- Telegram bot with boot diagnostics
3. `src/config.py` -- All env vars and constants
4. `pipeline.py` -- Full 8-step pipeline, `process_file()`
5. `src/storage.py` -- GitHub storage + dashboard push
6. `src/dashboard.py` -- Dashboard generation (local + GitHub modes)

---

## What Worked Earlier (Before Auth Broke)

The bot DID successfully process a voice recording once (commit `7a0d9a6` in zumo-data shows "Update dashboard for ben-akiva"). So the full pipeline works:
- Telegram file download: OK
- Audio extraction + silence removal: OK
- Transcription via Hebrew AI: OK
- Claude analysis: failed (wrong model ID, now fixed to `claude-sonnet-4-6`)
- GitHub save: OK
- Dashboard generation + push: OK

---

## Ben's Preferences (Unchanged)

- No emojis in UI or outputs. Geometric shapes OK.
- Hebrew for content, English for code/technical.
- Don't over-engineer. 5 users max. Keep it simple.
- Dark mode only. Rubik font. Very rounded. Thick strokes.
- He builds cathedrals when houses would do -- nudge him to ship.

---

## Debug Logging Currently in Code

`bot.py` and `src/users.py` have extensive boot diagnostics that print to stderr:
- `[BOOT] ZUMO env vars: {...}` -- all env vars starting with ZUMO
- `[BOOT] name = ...` etc. -- each field value
- `[BOOT] Wrote user from env vars: ben-akiva`
- `[BOOT] list_users() = [...]`
- `[BOOT] FAILED username: error message`

**Remove this debug logging** once the env var issue is resolved.
