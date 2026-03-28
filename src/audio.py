"""Audio extraction and silence removal via ffmpeg."""

import shutil
import subprocess
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}


def get_duration(file_path: str | Path) -> float:
    """Get audio/video duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not determine duration for {file_path}")


def is_audio_file(file_path: str | Path) -> bool:
    """Check if file extension is a known audio format."""
    return Path(file_path).suffix.lower() in AUDIO_EXTENSIONS


def extract_audio(video_path: str | Path, output_path: str | Path) -> Path:
    """Extract audio track from video as MP3."""
    subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-vn", "-acodec", "libmp3lame",
         "-q:a", "2", str(output_path), "-y"],
        check=True, capture_output=True, text=True,
    )
    return Path(output_path)


def detect_silence(
    audio_path: str | Path,
    threshold_db: int = -30,
    min_duration: int = 30,
) -> list[tuple[float, float]]:
    """Detect silent segments longer than min_duration using ffmpeg silencedetect."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(audio_path),
         "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )

    silences = []
    current_start = None

    for line in result.stderr.split("\n"):
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[1].strip().split()[0])
            except (IndexError, ValueError):
                current_start = None
        elif "silence_end:" in line and current_start is not None:
            try:
                end = float(line.split("silence_end:")[1].strip().split()[0])
                silences.append((current_start, end))
            except (IndexError, ValueError):
                pass
            current_start = None

    return silences


def remove_silence(
    audio_path: str | Path,
    silences: list[tuple[float, float]],
    output_path: str | Path,
) -> tuple[Path, float]:
    """Remove silent segments and concatenate remaining audio.
    Returns (output_path, total_seconds_removed).
    """
    if not silences:
        shutil.copy2(str(audio_path), str(output_path))
        return Path(output_path), 0.0

    total_duration = get_duration(audio_path)

    # Build non-silent segments
    segments = []
    prev_end = 0.0
    for start, end in sorted(silences):
        if start > prev_end + 0.1:
            segments.append((prev_end, start))
        prev_end = end
    if prev_end < total_duration - 0.1:
        segments.append((prev_end, total_duration))

    if not segments:
        shutil.copy2(str(audio_path), str(output_path))
        return Path(output_path), 0.0

    # Build ffmpeg filter_complex
    filter_parts = []
    for i, (start, end) in enumerate(segments):
        filter_parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )

    concat_inputs = "".join(f"[a{i}]" for i in range(len(segments)))
    filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=0:a=1[out]")
    filter_complex = ";".join(filter_parts)

    subprocess.run(
        ["ffmpeg", "-i", str(audio_path),
         "-filter_complex", filter_complex,
         "-map", "[out]",
         str(output_path), "-y"],
        check=True, capture_output=True, text=True,
    )

    removed = sum(end - start for start, end in silences)
    return Path(output_path), removed


MAX_UPLOAD_SIZE_MB = 25


def compress_audio(audio_path: str | Path, output_path: str | Path) -> Path:
    """Re-encode audio to a smaller MP3 if it exceeds the upload size limit.
    Returns the original path if already small enough.
    """
    size_mb = Path(audio_path).stat().st_size / 1024 / 1024
    if size_mb <= MAX_UPLOAD_SIZE_MB:
        return Path(audio_path)

    subprocess.run(
        ["ffmpeg", "-i", str(audio_path),
         "-acodec", "libmp3lame", "-b:a", "32k",
         "-ar", "16000", "-ac", "1",
         str(output_path), "-y"],
        check=True, capture_output=True, text=True,
    )
    return Path(output_path)


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    seconds = int(seconds)
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
