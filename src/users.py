"""Per-user configuration management."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import USERS_DIR, DEFAULT_SILENCE_MIN_DURATION


def _ensure_users_from_env() -> None:
    """Populate users/ from env vars (for containerized deploys).

    Supports two modes:
    1. Individual env vars (recommended): ZUMO_USER_SLUG + ZUMO_USER_*
    2. Single JSON: USERS_CONFIG={"username": {config}, ...}
    """
    import sys

    # Debug: show all ZUMO env vars
    zumo_vars = {k: v[:20] + "..." if len(v) > 20 else v for k, v in os.environ.items() if k.startswith("ZUMO")}
    print(f"[BOOT] ZUMO env vars: {zumo_vars}", file=sys.stderr)

    # Mode 1: Individual env vars (simple, no JSON issues)
    slug = os.getenv("ZUMO_USER_SLUG")
    if slug:
        data = {
            "name": os.getenv("ZUMO_USER_NAME", slug),
            "telegram_user_id": int(os.getenv("ZUMO_USER_TELEGRAM_ID", "0")) or None,
            "hebrew_ai_api_key": os.getenv("ZUMO_USER_HEBREW_AI_KEY", ""),
            "anthropic_api_key": os.getenv("ZUMO_USER_ANTHROPIC_KEY", ""),
            "default_language": os.getenv("ZUMO_USER_LANGUAGE", "he"),
            "silence_threshold_seconds": int(os.getenv("ZUMO_USER_SILENCE_THRESHOLD", "30")),
            "dashboard_slug": slug,
            "web_password_hash": os.getenv("ZUMO_USER_PASSWORD_HASH") or None,
        }
        USERS_DIR.mkdir(parents=True, exist_ok=True)
        path = USERS_DIR / f"{slug}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # Debug: show which fields are populated
        for k, v in data.items():
            val_info = f"{str(v)[:20]}..." if v and len(str(v)) > 20 else v
            print(f"[BOOT]   {k} = {val_info!r}", file=sys.stderr)
        print(f"[BOOT] Wrote user from env vars: {slug}", file=sys.stderr)
        return

    # Mode 2: USERS_CONFIG JSON (fallback)
    raw = os.getenv("USERS_CONFIG")
    if not raw:
        return
    try:
        users = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[USERS_CONFIG] JSON parse failed: {e}", file=sys.stderr)
        return
    if not isinstance(users, dict):
        return
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    for username, data in users.items():
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                continue
        if not isinstance(data, dict):
            continue
        path = USERS_DIR / f"{username}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[BOOT] Wrote user from USERS_CONFIG: {username}", file=sys.stderr)


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

    return UserConfig(
        name=data["name"],
        hebrew_ai_api_key=data.get("hebrew_ai_api_key", ""),
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


def diagnose_telegram_id(telegram_id: int) -> str | None:
    """Check why a Telegram ID might fail to authenticate.
    Returns an error message string, or None if the user loads fine."""
    users = list_users()
    if not users:
        return "No users configured on this server."
    for username in users:
        filepath = USERS_DIR / f"{username}.json"
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if isinstance(data, str):
                data = json.loads(data)
        except (json.JSONDecodeError, FileNotFoundError):
            continue
        if data.get("telegram_user_id") == telegram_id:
            # Found the user entry -- check what's broken
            missing = []
            if not data.get("hebrew_ai_api_key"):
                missing.append("hebrew_ai_api_key")
            if not data.get("anthropic_api_key"):
                missing.append("anthropic_api_key")
            if missing:
                return f"User '{username}' found but missing config: {', '.join(missing)}. Check server env vars."
            return None  # All good
    return None  # Not found at all -- will get the generic "not registered" message


def find_user_by_telegram_id(telegram_id: int) -> tuple[str, UserConfig] | None:
    """Find a user by their Telegram user ID. Returns (username, config) or None."""
    import sys
    for username in list_users():
        try:
            user = load_user(username)
            if user.telegram_user_id == telegram_id:
                return (username, user)
        except FileNotFoundError:
            continue
        except ValueError as e:
            print(f"[AUTH] User '{username}' config error: {e}", file=sys.stderr)
            continue
    return None
