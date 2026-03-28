"""Download Zoom cloud recordings via yt-dlp."""

import subprocess
import sys
from pathlib import Path


def download_zoom_recording(
    url: str,
    output_dir: Path,
    passcode: str | None = None,
    on_progress=None,
) -> Path:
    """Download a Zoom cloud recording using yt-dlp.

    Returns path to the downloaded audio/video file.
    """
    def _progress(msg: str):
        if on_progress:
            on_progress(msg)

    _progress("Downloading Zoom recording via yt-dlp...")

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

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Give a clear error message
        if "password" in stderr.lower() or "passcode" in stderr.lower():
            raise RuntimeError("Recording requires a passcode. Include it in your message: Passcode: XXXX")
        raise RuntimeError(f"yt-dlp failed: {stderr[-500:]}")

    # Find the downloaded file
    files = list(output_dir.iterdir())
    if not files:
        raise RuntimeError("yt-dlp completed but no file was downloaded")

    downloaded = max(files, key=lambda f: f.stat().st_size)
    _progress(f"Downloaded: {downloaded.name} ({downloaded.stat().st_size // 1024 // 1024}MB)")
    return downloaded


def is_zoom_url(text: str) -> bool:
    """Check if text looks like a Zoom recording URL."""
    return "zoom.us/rec/" in text or "zoom.us/recording/" in text
