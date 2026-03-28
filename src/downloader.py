"""Download Zoom cloud recordings via official API (primary) or yt-dlp (fallback)."""

import subprocess
import sys
from pathlib import Path

from .zoom_api import ZoomAuth, download_zoom_via_api


def download_zoom_recording(
    url: str,
    output_dir: Path,
    passcode: str | None = None,
    on_progress=None,
) -> dict[str, Path]:
    """Download a Zoom recording. Returns dict of file paths.

    Primary: Zoom S2S OAuth API (ignores passcode -- Bearer auth bypasses it).
    Fallback: yt-dlp with --video-password (if API not configured).
    """
    auth = ZoomAuth()
    if auth.is_configured():
        return download_zoom_via_api(url, output_dir, on_progress)

    # Fallback: yt-dlp
    return _download_via_ytdlp(url, output_dir, passcode, on_progress)


def _download_via_ytdlp(
    url: str,
    output_dir: Path,
    passcode: str | None = None,
    on_progress=None,
) -> dict[str, Path]:
    """Fallback: download via yt-dlp."""
    if on_progress:
        on_progress("Downloading via yt-dlp (fallback)...")

    output_template = str(output_dir / "%(title)s.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-warnings",
        "--output", output_template,
        "--no-playlist",
    ]
    if passcode:
        cmd.extend(["--video-password", passcode])
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "password" in stderr.lower() or "passcode" in stderr.lower():
            raise RuntimeError("Recording requires a passcode. Include it: Passcode: XXXX")
        raise RuntimeError(f"yt-dlp failed: {stderr[-500:]}")

    files = list(output_dir.iterdir())
    if not files:
        raise RuntimeError("yt-dlp completed but no file was downloaded")

    downloaded = max(files, key=lambda f: f.stat().st_size)
    if on_progress:
        on_progress(f"Downloaded: {downloaded.name}")
    return {"video": downloaded}


def is_zoom_url(text: str) -> bool:
    """Check if text looks like a Zoom recording URL."""
    return "zoom.us/rec/" in text or "zoom.us/recording/" in text
