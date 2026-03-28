"""Per-user configuration management."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import USERS_DIR, DEFAULT_SILENCE_MIN_DURATION


def _ensure_users_from_env() -> None:
    """Populate users/ from USERS_CONFIG env var (for containerized deploys).

    USERS_CONFIG is a JSON object: {"username": {config}, ...}
    """
    import sys
    raw = os.getenv("USERS_CONFIG")
    if not raw:
        return
    print(f"[USERS_CONFIG] Raw (first 120): {raw[:120]!r}", file=sys.stderr)
    try:
        users = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[USERS_CONFIG] JSON parse failed: {e}", file=sys.stderr)
        return
    print(f"[USERS_CONFIG] Parsed type={type(users).__name__}, keys={list(users.keys()) if isinstance(users, dict) else 'N/A'}", file=sys.stderr)
    if not isinstance(users, dict):
        print(f"[USERS_CONFIG] Expected dict, got {type(users).__name__}", file=sys.stderr)
        return
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    for username, data in users.items():
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                print(f"[USERS_CONFIG] Skipping {username}: value is not valid JSON", file=sys.stderr)
                continue
        if not isinstance(data, dict):
            print(f"[USERS_CONFIG] Skipping {username}: expected dict, got {type(data).__name__}", file=sys.stderr)
            continue
        path = USERS_DIR / f"{username}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[USERS_CONFIG] Wrote {path.name}", file=sys.stderr)


_ensure_users_from_env()


@dataclass
class UserConfig:
    name: str
    hebrew_ai_api_key: str
    anthropic_api_key: str
    default_language: str
    silence_threshold_seconds: int
    dashboard_slug: str
    telegram_user_id: int | None = None
    web_password_hash: str | None = None


def load_user(username: str) -> UserConfig:
    """Load users/{username}.json and return a UserConfig."""
    filepath = USERS_DIR / f"{username}.json"

    if not filepath.exists():
        available = list_users()
        available_str = ", ".join(available) if available else "(none)"
        raise FileNotFoundError(
            f"User config not found: {filepath}\n"
            f"Available users: {available_str}"
        )

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        # Handle double-encoded JSON (e.g. from env vars)
        if isinstance(data, str):
            data = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {filepath}: {e}") from e

    if not data.get("hebrew_ai_api_key"):
        raise ValueError(f"Missing required field 'hebrew_ai_api_key' in {filepath}")

    return UserConfig(
        name=data["name"],
        hebrew_ai_api_key=data["hebrew_ai_api_key"],
        anthropic_api_key=data.get("anthropic_api_key", ""),
        default_language=data.get("default_language", "he"),
        silence_threshold_seconds=data.get("silence_threshold_seconds", DEFAULT_SILENCE_MIN_DURATION),
        dashboard_slug=data.get("dashboard_slug", username),
        telegram_user_id=data.get("telegram_user_id"),
        web_password_hash=data.get("web_password_hash"),
    )


def list_users() -> list[str]:
    """Return list of available usernames (based on .json files in users/)."""
    if not USERS_DIR.exists():
        return []
    return [
        f.stem for f in USERS_DIR.glob("*.json")
        if f.suffix == ".json" and not f.name.endswith(".example")
    ]


def find_user_by_telegram_id(telegram_id: int) -> tuple[str, UserConfig] | None:
    """Find a user by their Telegram user ID. Returns (username, config) or None."""
    for username in list_users():
        try:
            user = load_user(username)
            if user.telegram_user_id == telegram_id:
                return (username, user)
        except (FileNotFoundError, ValueError):
            continue
    return None
