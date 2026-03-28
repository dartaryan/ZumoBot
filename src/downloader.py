"""Download Zoom cloud recordings via Zoom's internal API."""

import re
from pathlib import Path
from urllib.parse import urlparse

import requests


def download_zoom_recording(
    url: str,
    output_dir: Path,
    passcode: str | None = None,
    on_progress=None,
) -> Path:
    """Download a Zoom cloud recording from a play/share link.

    Uses Zoom's internal API: validate passcode -> get download URL -> stream to file.
    Returns path to the downloaded audio/video file.
    """
    def _progress(msg: str):
        if on_progress:
            on_progress(msg)

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.hostname}"

    # Normalize URL to /rec/play/ format
    play_url = url.replace("/rec/share/", "/rec/play/")
    file_id = play_url.split("/rec/play/")[1].split("?")[0]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    # Step 1: Load play page for cookies
    _progress("Loading Zoom recording page...")
    session.get(play_url, timeout=30)

    # Step 2: Get play info (contains meeting ID)
    info_url = f"{base}/nws/recording/1.0/play/info/{file_id}"
    resp = session.get(info_url, headers={"Referer": play_url}, timeout=30)
    data = resp.json()

    if not data.get("status"):
        raise RuntimeError(f"Zoom API error: {data.get('errorMessage', 'Unknown')}")

    result = data["result"]

    # Step 3: Validate passcode if needed
    if result.get("componentName") == "need-password":
        if not passcode:
            raise RuntimeError("Recording requires a passcode. Use --passcode.")

        meeting_id = result["meetingId"]
        _progress("Validating passcode...")

        resp2 = session.post(
            f"{base}/nws/recording/1.0/validate-meeting-passwd",
            data={"id": meeting_id, "passwd": passcode, "action": "viewdetailpage"},
            headers={"Referer": play_url},
            timeout=30,
        )
        validate = resp2.json()
        if not validate.get("status"):
            raise RuntimeError(f"Invalid passcode: {validate.get('errorMessage', 'Check passcode')}")

        # Re-fetch play info with validated session
        resp = session.get(info_url, headers={"Referer": play_url}, timeout=30)
        data = resp.json()
        result = data["result"]

    # Step 4: Extract download URL
    download_url = result.get("viewMp4Url") or result.get("mp4Url")
    if not download_url:
        raise RuntimeError("Could not find download URL in Zoom response")

    # Determine filename from URL
    url_path = urlparse(download_url).path
    filename = Path(url_path).name or "recording.m4a"
    output_path = output_dir / filename

    # Step 5: Download the file
    _progress(f"Downloading {filename}...")
    resp3 = session.get(
        download_url,
        stream=True,
        timeout=600,
        headers={"Referer": play_url},
    )
    resp3.raise_for_status()

    total_size = int(resp3.headers.get("content-length", 0))
    downloaded = 0
    last_reported_pct = -1

    with open(output_path, "wb") as f:
        for chunk in resp3.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size and on_progress:
                pct = int(downloaded / total_size * 100)
                # Report every 10%
                if pct // 10 > last_reported_pct // 10:
                    last_reported_pct = pct
                    _progress(f"Downloading... {pct}% ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)")

    _progress(f"Downloaded: {output_path.name} ({downloaded // 1024 // 1024}MB)")
    return output_path


def is_zoom_url(text: str) -> bool:
    """Check if text looks like a Zoom recording URL."""
    return "zoom.us/rec/" in text or "zoom.us/recording/" in text
