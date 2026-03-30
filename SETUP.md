# Zumo Bot — Setup Guide

## What You Need

| Credential | Required? | Where to get it |
|---|---|---|
| Telegram Bot Token | Required | Create bot via [@BotFather](https://t.me/BotFather) |
| GitHub PAT | Required | GitHub → Settings → Developer Settings → Fine-grained tokens (needs `Contents: Read/Write` on data repo) |
| GitHub Data Repo | Required | Create an empty repo (e.g., `zumo-data`) |
| Anthropic API Key | Required | [console.anthropic.com](https://console.anthropic.com/) |
| Hebrew AI API Key | Required | [hebrew-ai.com](https://hebrew-ai.com/) |
| Telegram API ID/Hash | Recommended | [my.telegram.org](https://my.telegram.org/) → API development tools (needed for files > 20MB) |
| Zoom S2S Credentials | Optional | Zoom App Marketplace → Server-to-Server OAuth app |
| HuggingFace Token | Optional | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) (for speaker diarization) |

## Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/dartaryan/zumo.git
   cd zumo
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   Fill in `TELEGRAM_BOT_TOKEN`, `GITHUB_TOKEN`, and `GITHUB_REPO` at minimum.

4. **Initialize the data repo**
   The GitHub data repo needs an initial commit. Create it on GitHub and push at least one file (e.g., a README).

5. **Add a user** (see below)

6. **Run the bot**
   ```bash
   python bot.py
   ```

## Adding a User

Create a JSON file in the `users/` directory named `{slug}.json`:

```json
{
  "name": "Jane Doe",
  "telegram_user_id": 123456789,
  "hebrew_ai_api_key": "sk_...",
  "anthropic_api_key": "sk-ant-...",
  "default_language": "he",
  "silence_threshold_seconds": 30,
  "dashboard_slug": "jane-doe",
  "web_password_hash": null
}
```

| Field | Description |
|---|---|
| `name` | Display name shown in bot messages |
| `telegram_user_id` | Send `/start` to [@userinfobot](https://t.me/userinfobot) on Telegram to get your numeric ID |
| `hebrew_ai_api_key` | API key for Hebrew transcription |
| `anthropic_api_key` | Claude API key for analysis |
| `default_language` | `"he"` or `"en"` |
| `silence_threshold_seconds` | Min silence gap for segmentation (default: 30) |
| `dashboard_slug` | URL-safe identifier, usually same as filename |
| `web_password_hash` | SHA-256 hash of dashboard password, or `null` for no password |

**Generate a password hash:**
```bash
python -c "import hashlib; print(hashlib.sha256(b'your-password').hexdigest())"
```

**Single-user shortcut:** Instead of a JSON file, set `ZUMO_USER_*` env vars in `.env`. See `.env.example` for the full list.

## Deploy to Railway

1. Push the repo to GitHub.
2. Create a new Railway project and connect it to the GitHub repo.
3. Set all required environment variables in Railway's dashboard.
4. Railway auto-builds from the `Dockerfile` on each push.

For multi-user deploys without committing user JSON files to the repo, set the `USERS_CONFIG` env var with a JSON object mapping slugs to user configs.

## Netlify Dashboard

1. Create a Netlify site connected to the **data repo** (not the bot repo).
2. Set `DASHBOARD_BASE_URL` in the bot's environment to the Netlify URL (e.g., `https://zumobot.netlify.app`).
3. Processed sessions will include a link to the dashboard in the bot's reply.
