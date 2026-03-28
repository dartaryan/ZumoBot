"""Zoom Server-to-Server OAuth API client for downloading recordings + transcripts."""

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests


class ZoomAuth:
    """Manages S2S OAuth tokens (auto-refreshes on expiry)."""

    TOKEN_URL = "https://zoom.us/oauth/token"

    def __init__(
        self,
        account_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.account_id = account_id or os.getenv("ZOOM_ACCOUNT_ID", "")
        self.client_id = client_id or os.getenv("ZOOM_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("ZOOM_CLIENT_SECRET", "")
        self._token: str | None = None
        self._expires_at: float = 0

    def is_configured(self) -> bool:
        return bool(self.account_id and self.client_id and self.client_secret)

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        resp = requests.post(
            self.TOKEN_URL,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "account_credentials",
                "account_id": self.account_id,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        self._token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_token()}"}


def _extract_share_token(share_url: str) -> str:
    """Extract the opaque token from a Zoom share/play URL."""
    # /rec/share/XXXXX or /rec/play/XXXXX
    m = re.search(r"/rec/(?:share|play)/([^?\s]+)", share_url)
    if not m:
        raise ValueError(f"Cannot parse Zoom share URL: {share_url}")
    return m.group(1).split("?")[0]


def resolve_share_url(auth: ZoomAuth, share_url: str) -> dict:
    """Find the meeting recording matching a share URL.

    Strategy: extract startTime from URL to match by date, since share tokens
    are regenerated per API call and cannot be matched directly.

    Returns the full recording object from the API, including recording_files.
    """
    from datetime import datetime, timedelta, timezone

    headers = auth.headers()

    # Try to extract startTime from URL (epoch milliseconds)
    target_time = None
    m = re.search(r"[?&]startTime=(\d+)", share_url)
    if m:
        target_time = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)

    # Search window: if we have a target time, search ±3 days. Otherwise last 60 days.
    if target_time:
        from_date = (target_time - timedelta(days=3)).strftime("%Y-%m-%d")
        to_date = (target_time + timedelta(days=3)).strftime("%Y-%m-%d")
    else:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    # Fetch all recordings in the window
    all_meetings = []
    next_page = ""
    while True:
        params = {"from": from_date, "to": to_date, "page_size": 100}
        if next_page:
            params["next_page_token"] = next_page

        resp = requests.get(
            "https://api.zoom.us/v2/users/me/recordings",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        all_meetings.extend(data.get("meetings", []))

        next_page = data.get("next_page_token", "")
        if not next_page:
            break

    if not all_meetings:
        raise ValueError("No recordings found in your Zoom account for this date range.")

    # Match by startTime proximity
    if target_time:
        best_match = None
        best_delta = float("inf")
        for meeting in all_meetings:
            start_str = meeting.get("start_time", "")
            if not start_str:
                continue
            meeting_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            delta = abs((meeting_time - target_time).total_seconds())
            if delta < best_delta:
                best_delta = delta
                best_match = meeting

        if best_match and best_delta < 86400:  # Within 24 hours
            return _get_recording_files(auth, best_match["uuid"])

    # If only 1 recording in window, use it
    if len(all_meetings) == 1:
        return _get_recording_files(auth, all_meetings[0]["uuid"])

    # Can't auto-resolve -- list what we found
    listing = "\n".join(
        f"  - {m.get('topic', '?')} ({m.get('start_time', '?')[:10]})"
        for m in all_meetings[:10]
    )
    raise ValueError(
        f"Could not auto-match recording. Found {len(all_meetings)} recordings:\n{listing}\n"
        f"Tip: use a link with startTime parameter, or send the file directly."
    )


def _get_recording_files(auth: ZoomAuth, meeting_uuid: str) -> dict:
    """Fetch recording files for a specific meeting UUID."""
    # Double-encode UUID if it contains / or =
    encoded_id = quote(quote(meeting_uuid, safe=""), safe="")
    resp = requests.get(
        f"https://api.zoom.us/v2/meetings/{encoded_id}/recordings",
        headers=auth.headers(),
        params={"include_fields": "download_access_token"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def download_recording_files(
    auth: ZoomAuth,
    recording: dict,
    output_dir: Path,
    on_progress=None,
) -> dict[str, Path]:
    """Download recording files (video, audio, transcript) to output_dir.

    Returns dict mapping file type to local path, e.g.:
    {"video": Path("...mp4"), "audio": Path("...m4a"), "transcript": Path("...vtt")}
    """
    def _progress(msg: str):
        if on_progress:
            on_progress(msg)

    headers = auth.headers()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {}
    topic = recording.get("topic", "recording").replace("/", "-")

    for f in recording.get("recording_files", []):
        file_type = f.get("file_type", "").upper()
        rec_type = f.get("recording_type", "")
        download_url = f.get("download_url")

        if not download_url:
            continue

        # Pick the files we care about
        if file_type == "MP4" and "video" not in files:
            key = "video"
            ext = "mp4"
        elif file_type == "M4A" and "audio" not in files:
            key = "audio"
            ext = "m4a"
        elif rec_type == "audio_transcript" or (file_type == "TRANSCRIPT" and "transcript" not in files):
            key = "transcript"
            ext = "vtt"
        else:
            continue

        filename = f"{topic}.{ext}"
        output_path = output_dir / filename
        _progress(f"Downloading {key} ({ext})...")

        resp = requests.get(download_url, headers=headers, stream=True, timeout=600)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(output_path, "wb") as fout:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                fout.write(chunk)
                downloaded += len(chunk)
                if total and on_progress:
                    pct = int(downloaded / total * 100)
                    if pct % 20 == 0:
                        _progress(f"Downloading {key}... {pct}%")

        size_mb = output_path.stat().st_size / 1024 / 1024
        _progress(f"Downloaded {key}: {filename} ({size_mb:.1f}MB)")
        files[key] = output_path

    if not files:
        raise RuntimeError("No downloadable files found in recording")

    return files


def download_zoom_via_api(
    share_url: str,
    output_dir: Path,
    on_progress=None,
) -> dict[str, Path]:
    """Full flow: share URL -> resolve -> download files.

    Returns dict of downloaded file paths.
    """
    auth = ZoomAuth()
    if not auth.is_configured():
        raise RuntimeError(
            "Zoom API not configured. Set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET."
        )

    if on_progress:
        on_progress("Resolving Zoom recording via API...")

    recording = resolve_share_url(auth, share_url)

    if on_progress:
        topic = recording.get("topic", "Unknown")
        on_progress(f"Found: {topic}")

    return download_recording_files(auth, recording, output_dir, on_progress)
