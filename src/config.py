"""Configuration and environment setup."""

import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Ensure ffmpeg is on PATH (Windows winget installs it outside PATH) ---
if not shutil.which("ffmpeg"):
    _winget_ffmpeg = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for _candidate in _winget_ffmpeg.glob("*FFmpeg*/*/bin"):
        if (_candidate / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(_candidate) + os.pathsep + os.environ.get("PATH", "")
            break

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent.parent
USERS_DIR = PROJECT_ROOT / "users"
OUTPUT_DIR = PROJECT_ROOT / "output"

# --- Audio Processing ---
SILENCE_THRESHOLD_DB = -30
DEFAULT_SILENCE_MIN_DURATION = 30  # seconds

# --- Hebrew AI Polling ---
POLL_INTERVAL = 5  # seconds between status checks
POLL_TIMEOUT = 1800  # 30 minutes max wait

# --- Claude Models ---
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6-20250514"

# --- Speaker Diarization (pyannote) ---
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN", "")

# --- GitHub ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# --- Dashboard ---
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "")

# --- Session Types ---
SESSION_TYPES = {
    "team-meeting": {"he": "ישיבת צוות", "en": "Team Meeting", "emoji": "📋"},
    "training": {"he": "הדרכה", "en": "Training Session", "emoji": "🎓"},
    "client-call": {"he": "שיחת לקוח", "en": "Client Call", "emoji": "🤝"},
    "phone-call": {"he": "שיחת טלפון", "en": "Phone Call", "emoji": "📞"},
    "coaching": {"he": "אימון", "en": "Coaching", "emoji": "💡"},
    "other": {"he": "אחר", "en": "Other", "emoji": "📝"},
}


def validate_config(local_mode: bool = False) -> None:
    """Check that required env vars are set. In local mode, only ffmpeg is needed."""
    if not shutil.which("ffmpeg"):
        raise EnvironmentError(
            "ffmpeg not found on PATH. Install it:\n"
            "  Windows: winget install FFmpeg\n"
            "  Mac: brew install ffmpeg\n"
            "  Linux: sudo apt install ffmpeg"
        )

    if local_mode:
        return

    missing = []
    if not GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not GITHUB_REPO:
        missing.append("GITHUB_REPO")
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in your keys."
        )

    if "/" not in GITHUB_REPO:
        raise EnvironmentError(
            f"GITHUB_REPO must be in 'owner/repo' format, got: '{GITHUB_REPO}'"
        )
