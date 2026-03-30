# Railway Environment Variable Issue -- Debug Prompt

I'm deploying a Python Telegram bot on Railway using a Dockerfile. The bot needs user configuration (API keys, user ID, etc.) passed via environment variables.

## The Setup
- Railway project connected to a GitHub repo
- Dockerfile: Python 3.11-slim + ffmpeg
- Bot reads env vars on startup using os.getenv() in Python
- I have ~12 env vars set in Railway's dashboard

## The Problem
One specific env var returns empty string despite being correctly set in Railway's UI.

Working vars: TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, GITHUB_REPO, ZUMO_USER_SLUG, ZUMO_USER_NAME, ZUMO_USER_TELEGRAM_ID, ZUMO_USER_ANTHROPIC_KEY, ZUMO_USER_LANGUAGE -- all return correct values via os.getenv().

NOT working: ZUMO_USER_HEBREW_AI_KEY -- returns "" even though Railway UI shows the value "sk_4b6zqbvj4phavrp2_f2a771606c5b62379bd4" when I click to reveal it.

The Python code is identical for all vars:

```python
"anthropic_api_key": os.getenv("ZUMO_USER_ANTHROPIC_KEY", ""),  # WORKS
"hebrew_ai_api_key": os.getenv("ZUMO_USER_HEBREW_AI_KEY", ""),  # RETURNS ""
```

## What I've Tried
1. Redeploy from Railway dashboard -- same result
2. Deleting and re-creating the variable -- same result
3. Confirming the value is visible in Railway UI when revealed
4. Adding debug logging that prints all env vars starting with "ZUMO" to stderr -- but this latest code doesn't seem to deploy (Railway might be stuck on old build)
5. Previously tried a single USERS_CONFIG env var with JSON containing all user fields -- Railway truncated the JSON at ~360 characters with "Unterminated string" error

## Boot Logs Showing the Problem

```
[BOOT]   name = 'Ben Akiva'
[BOOT]   telegram_user_id = 8553241584
[BOOT]   hebrew_ai_api_key = ''
[BOOT]   anthropic_api_key = 'sk-ant-api03-3UCmbNV...'
[BOOT]   default_language = 'he'
[BOOT]   silence_threshold_seconds = 30
[BOOT]   dashboard_slug = 'ben-akiva'
[BOOT]   web_password_hash = None
[BOOT] Wrote user from env vars: ben-akiva
[BOOT] FAILED ben-akiva: Missing required field 'hebrew_ai_api_key'
```

## Additional Context
- Railway uses Dockerfile builder (configured in railway.toml)
- Some env var changes trigger container restart but NOT rebuild -- old code keeps running
- The "Redeploy" button in Railway seems to redeploy the same old build, not build from latest commit
- The bot DID work once with a different env var approach (USERS_CONFIG JSON) before it broke due to JSON truncation
- The 409 Conflict error on Telegram getUpdates is a known issue during Railway deploy transitions (old + new container overlap) and resolves in ~20 seconds

## My Dockerfile

```dockerfile
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
```

## My railway.toml

```toml
[build]
builder = "dockerfile"

[deploy]
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 10
```

## Questions
1. Is there a known issue with Railway env vars not being passed to Docker containers?
2. Could Railway have a character limit or encoding issue with certain env var names or values?
3. Is there a difference between Railway restart (env var change) vs rebuild (new commit)?
4. What's the correct way to force Railway to build from the latest commit?
5. Is there a better pattern for passing complex config (user JSON with API keys) to a Railway Docker deployment?
6. Should I use Railway's Raw Editor instead of the individual variable UI to ensure values are passed correctly?
7. Could the underscore-heavy variable name ZUMO_USER_HEBREW_AI_KEY be causing issues?
