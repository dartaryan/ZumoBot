"""Per-user configuration management."""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import USERS_DIR, DEFAULT_SILENCE_MIN_DURATION


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
