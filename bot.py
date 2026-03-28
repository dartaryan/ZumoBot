"""Zumo Telegram Bot -- send recordings, get transcripts."""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from src.config import SESSION_TYPES, validate_config
from src.users import find_user_by_telegram_id, diagnose_telegram_id
from src.audio import format_duration

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ZOOM_URL_PATTERN = re.compile(
    r"https?://[\w.-]*zoom\.us/rec/(?:share|play)/\S+"
)

MEDIA_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma",
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".3gp",
}


def parse_caption(caption: str | None) -> dict:
    """Parse caption for session metadata.

    Supported in caption text:
        type:training  speakers:Ben,Omri  lang:he
    """
    result = {"session_type": "other", "speakers": "", "language": None}
    if not caption:
        return result

    m = re.search(r"(?:type|session)[:\s](\S+)", caption, re.IGNORECASE)
    if m and m.group(1).lower() in SESSION_TYPES:
        result["session_type"] = m.group(1).lower()

    m = re.search(r"speakers?[:\s]([^\n]+)", caption, re.IGNORECASE)
    if m:
        result["speakers"] = m.group(1).strip()

    m = re.search(r"lang(?:uage)?[:\s](he|en)", caption, re.IGNORECASE)
    if m:
        result["language"] = m.group(1).lower()

    return result


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_info = find_user_by_telegram_id(update.effective_user.id)
    name = user_info[1].name if user_info else (update.effective_user.first_name or "there")

    types_list = ", ".join(SESSION_TYPES.keys())
    await update.message.reply_text(
        f"Zumo -- Transcription Pipeline\n\n"
        f"Hey {name}.\n"
        f"Send me an audio or video file and I'll transcribe and analyze it.\n"
        f"You can also paste a Zoom recording link.\n\n"
        f"Add metadata in the file caption:\n"
        f"  type:training speakers:Ben,Omri lang:he\n\n"
        f"Session types: {types_list}"
    )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process audio/video files sent to the bot."""
    telegram_id = update.effective_user.id
    user_info = find_user_by_telegram_id(telegram_id)

    if not user_info:
        diag = diagnose_telegram_id(telegram_id)
        if diag:
            await update.message.reply_text(f"[!] {diag}")
        else:
            await update.message.reply_text(
                f"Access denied. Your Telegram ID is not registered.\n"
                f"Your ID: {telegram_id}"
            )
        return

    _username, user = user_info

    # Determine which file object to use
    msg = update.message
    if msg.audio:
        file_obj = msg.audio
        file_name = file_obj.file_name or "audio.mp3"
    elif msg.voice:
        file_obj = msg.voice
        file_name = "voice.ogg"
    elif msg.video:
        file_obj = msg.video
        file_name = file_obj.file_name or "video.mp4"
    elif msg.video_note:
        file_obj = msg.video_note
        file_name = "video_note.mp4"
    elif msg.document:
        file_obj = msg.document
        file_name = file_obj.file_name or "file"
        ext = Path(file_name).suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            await msg.reply_text(f"Unsupported file type: {ext}\nSend audio or video files.")
            return
    else:
        return

    meta = parse_caption(msg.caption)
    language = meta["language"] or user.default_language

    status_msg = await msg.reply_text("[>] Downloading file...")

    tmp_dir = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="zumo-tg-"))
        file_path = tmp_dir / file_name

        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(str(file_path))

        await status_msg.edit_text(
            f"[>] Processing: {file_name}\n"
            f"    Type: {meta['session_type']}\n"
            f"    This may take several minutes..."
        )

        from pipeline import process_file

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: process_file(
                file_path=file_path,
                user=user,
                session_type=meta["session_type"],
                speakers=meta["speakers"],
                language=language,
                local_mode=False,
                skip_analysis=False,
                skip_diarization=False,
            ),
        )

        if result["status"] == "success":
            duration_str = format_duration(result.get("original_duration", 0))
            chars = result.get("transcript_length", 0)
            link = result.get("dashboard_url", "")

            await status_msg.edit_text(
                f"[=] Done\n\n"
                f"Duration: {duration_str}\n"
                f"Transcript: {chars:,} characters\n"
                f"Folder: {result.get('folder_name', '')}\n\n"
                f"{link}"
            )
        else:
            await status_msg.edit_text(f"[x] Error:\n{result.get('error', 'Unknown')[:500]}")

    except Exception as e:
        logger.error(f"Error processing file from {telegram_id}: {e}")
        try:
            await status_msg.edit_text(f"[x] Error:\n{str(e)[:500]}")
        except Exception:
            pass
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def handle_zoom_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process text messages containing Zoom recording links."""
    telegram_id = update.effective_user.id
    user_info = find_user_by_telegram_id(telegram_id)

    if not user_info:
        diag = diagnose_telegram_id(telegram_id)
        if diag:
            await update.message.reply_text(f"[!] {diag}")
        else:
            await update.message.reply_text(
                f"Access denied. Your Telegram ID is not registered.\n"
                f"Your ID: {telegram_id}"
            )
        return

    text = update.message.text or ""
    urls = ZOOM_URL_PATTERN.findall(text)
    if not urls:
        return  # Not a Zoom link -- ignore silently

    _username, user = user_info
    language = user.default_language

    for url in urls:
        status_msg = await update.message.reply_text("[>] Downloading Zoom recording...")

        tmp_dir = None
        try:
            from src.downloader import download_zoom_recording
            from pipeline import process_file

            tmp_dir = Path(tempfile.mkdtemp(prefix="zumo-zoom-"))

            # Extract passcode from URL query string if present
            passcode = None
            m = re.search(r"[?&]pwd=(\w+)", url)
            if m:
                passcode = m.group(1)

            file_path = download_zoom_recording(url, tmp_dir, passcode)

            await status_msg.edit_text(
                "[>] Processing Zoom recording...\n"
                "    This may take several minutes..."
            )

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: process_file(
                    file_path=file_path,
                    user=user,
                    session_type="team-meeting",
                    speakers="",
                    language=language,
                    local_mode=False,
                    skip_analysis=False,
                    skip_diarization=False,
                ),
            )

            if result["status"] == "success":
                duration_str = format_duration(result.get("original_duration", 0))
                chars = result.get("transcript_length", 0)
                link = result.get("dashboard_url", "")

                await status_msg.edit_text(
                    f"[=] Done\n\n"
                    f"Duration: {duration_str}\n"
                    f"Transcript: {chars:,} characters\n"
                    f"Folder: {result.get('folder_name', '')}\n\n"
                    f"{link}"
                )
            else:
                await status_msg.edit_text(f"[x] Error:\n{result.get('error', 'Unknown')[:500]}")

        except Exception as e:
            logger.error(f"Error processing Zoom link from {telegram_id}: {e}")
            try:
                await status_msg.edit_text(f"[x] Error:\n{str(e)[:500]}")
            except Exception:
                pass
        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    validate_config(local_mode=False)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VIDEO | filters.VOICE | filters.VIDEO_NOTE | filters.Document.ALL,
        handle_file,
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_zoom_link,
    ))

    # Debug: show loaded users
    import sys
    from src.users import list_users, load_user
    users_found = list_users()
    print(f"[BOOT] USERS_CONFIG set: {bool(os.getenv('USERS_CONFIG'))}", file=sys.stderr)
    print(f"[BOOT] USERS_DIR: {os.path.exists('users/')}, files: {list(Path('users/').glob('*.json')) if Path('users/').exists() else 'N/A'}", file=sys.stderr)
    print(f"[BOOT] list_users() = {users_found}", file=sys.stderr)
    for uname in users_found:
        try:
            u = load_user(uname)
            print(f"[BOOT] User {uname}: telegram_id={u.telegram_user_id} (type={type(u.telegram_user_id).__name__})", file=sys.stderr)
        except Exception as e:
            print(f"[BOOT] FAILED {uname}: {e}", file=sys.stderr)

    logger.info("Zumo bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
