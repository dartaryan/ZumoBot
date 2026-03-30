"""Zumo Telegram Bot -- send recordings, get transcripts."""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
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

# Conversation states
WAITING_TYPE, WAITING_SPEAKERS, WAITING_PURPOSE, WAITING_FORMAT = range(4)

# Session type labels for inline keyboard
SESSION_TYPE_LABELS = [
    ("ישיבת צוות (Team Meeting)", "team-meeting"),
    ("הדרכה (Training)", "training"),
    ("שיחת לקוח (Client Call)", "client-call"),
    ("שיחת טלפון (Phone Call)", "phone-call"),
    ("אימון (Coaching)", "coaching"),
    ("אחר (Other)", "other"),
]

_CONVERSATION_KEYS = [
    "tmp_dir", "file_path", "file_name", "user", "language",
    "status_msg", "session_type", "speakers", "purpose", "output_format",
]


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


def _has_caption_metadata(caption: str | None) -> bool:
    """Check if caption contains type: or speakers: metadata for fast-path."""
    if not caption:
        return False
    return bool(
        re.search(r"(?:type|session)[:\s]", caption, re.IGNORECASE)
        or re.search(r"speakers?[:\s]", caption, re.IGNORECASE)
    )


def _get_file_info(msg):
    """Extract file object and name from a message."""
    if msg.audio:
        return msg.audio, msg.audio.file_name or "audio.mp3"
    if msg.voice:
        return msg.voice, "voice.ogg"
    if msg.video:
        return msg.video, msg.video.file_name or "video.mp4"
    if msg.video_note:
        return msg.video_note, "video_note.mp4"
    if msg.document:
        file_name = msg.document.file_name or "file"
        ext = Path(file_name).suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            return None, file_name
        return msg.document, file_name
    return None, None


def _cleanup_conversation(context: ContextTypes.DEFAULT_TYPE):
    """Clean up conversation state and temp files."""
    tmp_dir = context.user_data.get("tmp_dir")
    if tmp_dir and Path(tmp_dir).exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    for key in _CONVERSATION_KEYS:
        context.user_data.pop(key, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _download_file(file_obj, file_size, msg, status_msg, file_path):
    """Download a Telegram file, handling large files via MTProto."""
    from src.telegram_downloader import MAX_BOT_API_SIZE

    if file_size > MAX_BOT_API_SIZE:
        size_mb = file_size / (1024 * 1024)
        await status_msg.edit_text(f"[>] Large file ({size_mb:.1f} MB) — downloading via MTProto...")
        try:
            from src.telegram_downloader import download_large_file

            await download_large_file(
                file_id=file_obj.file_id,
                chat_id=msg.chat_id,
                message_id=msg.message_id,
                dest_path=file_path,
            )
        except RuntimeError as e:
            await status_msg.edit_text(f"[x] Large file download failed:\n{str(e)}")
            return False
    else:
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(str(file_path))
    return True


async def _progress_ticker(status_msg, file_name, session_type):
    """Update the status message periodically so the user knows it's alive."""
    stages = [
        "Transcribing audio",
        "Identifying speakers",
        "Analyzing content",
        "Generating output",
    ]
    try:
        elapsed = 0
        while True:
            await asyncio.sleep(30)
            elapsed += 30
            mins = elapsed // 60
            secs = elapsed % 60
            stage_idx = min(elapsed // 60, len(stages) - 1)
            stage = stages[stage_idx]
            time_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
            try:
                await status_msg.edit_text(
                    f"[>] Processing: {file_name}\n"
                    f"    Type: {session_type}\n"
                    f"    Stage: {stage}...\n"
                    f"    Elapsed: {time_str}"
                )
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def _process_and_reply(
    status_msg, file_path, file_name, user,
    session_type, speakers, language, user_requests, telegram_id,
):
    """Run the pipeline and send the result."""
    await status_msg.edit_text(
        f"[>] Processing: {file_name}\n"
        f"    Type: {session_type}\n"
        f"    Starting pipeline..."
    )

    ticker = asyncio.create_task(
        _progress_ticker(status_msg, file_name, session_type)
    )

    from pipeline import process_file

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: process_file(
                file_path=file_path,
                user=user,
                session_type=session_type,
                speakers=speakers,
                language=language,
                local_mode=False,
                skip_analysis=False,
                skip_diarization=False,
                user_requests=user_requests,
            ),
        )
    finally:
        ticker.cancel()

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


async def handle_file_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: receive file, download it, then start interactive flow or fast-path."""
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
        return ConversationHandler.END

    _username, user = user_info
    msg = update.message

    file_obj, file_name = _get_file_info(msg)
    if file_obj is None:
        if file_name:
            ext = Path(file_name).suffix.lower()
            await msg.reply_text(f"Unsupported file type: {ext}\nSend audio or video files.")
        return ConversationHandler.END

    meta = parse_caption(msg.caption)
    language = meta["language"] or user.default_language
    file_size = file_obj.file_size or 0

    status_msg = await msg.reply_text("[>] Downloading file...")

    tmp_dir = Path(tempfile.mkdtemp(prefix="zumo-tg-"))
    file_path = tmp_dir / file_name

    ok = await _download_file(file_obj, file_size, msg, status_msg, file_path)
    if not ok:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return ConversationHandler.END

    # Caption fast-path: skip interactive flow
    if _has_caption_metadata(msg.caption):
        try:
            await _process_and_reply(
                status_msg, file_path, file_name, user,
                meta["session_type"], meta["speakers"], language,
                "full analysis", telegram_id,
            )
        except Exception as e:
            logger.error(f"Error processing file from {telegram_id}: {e}")
            try:
                await status_msg.edit_text(f"[x] Error:\n{str(e)[:500]}")
            except Exception:
                pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return ConversationHandler.END

    # Store data for interactive flow
    context.user_data["tmp_dir"] = tmp_dir
    context.user_data["file_path"] = file_path
    context.user_data["file_name"] = file_name
    context.user_data["user"] = user
    context.user_data["language"] = language
    context.user_data["status_msg"] = status_msg
    context.user_data["session_type"] = "other"
    context.user_data["speakers"] = ""
    context.user_data["purpose"] = ""
    context.user_data["output_format"] = "standard"

    await status_msg.edit_text("[OK] File downloaded.")

    # Ask session type
    keyboard = []
    for label, value in SESSION_TYPE_LABELS:
        keyboard.append([InlineKeyboardButton(label, callback_data=f"type:{value}")])
    keyboard.append([InlineKeyboardButton("דלג (Skip)", callback_data="type:skip")])

    await msg.reply_text(
        "מה סוג השיחה?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_TYPE


async def handle_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle session type selection."""
    query = update.callback_query
    await query.answer()

    value = query.data.replace("type:", "")
    if value != "skip":
        context.user_data["session_type"] = value

    await query.edit_message_text(f"סוג: {value}")

    keyboard = [[InlineKeyboardButton("דלג (Skip)", callback_data="speakers:skip")]]
    await query.message.reply_text(
        "מי הדוברים? (שמות מופרדים בפסיק, או לחץ דלג)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_SPEAKERS


async def handle_speakers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle speakers skip button."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("דוברים: דלג")

    keyboard = [[InlineKeyboardButton("דלג (Skip)", callback_data="purpose:skip")]]
    await query.message.reply_text(
        "מה המטרה או הפוקוס המיוחד? (או לחץ דלג לניתוח מלא)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_PURPOSE


async def handle_speakers_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle speakers typed as text."""
    context.user_data["speakers"] = update.message.text.strip()

    keyboard = [[InlineKeyboardButton("דלג (Skip)", callback_data="purpose:skip")]]
    await update.message.reply_text(
        "מה המטרה או הפוקוס המיוחד? (או לחץ דלג לניתוח מלא)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_PURPOSE


async def handle_purpose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle purpose skip button."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("מטרה: דלג")

    keyboard = [
        [InlineKeyboardButton("מסמך מקור ידע (Knowledge Base)", callback_data="format:knowledge-base")],
        [InlineKeyboardButton("ניתוח מובנה (Structured Analysis)", callback_data="format:standard")],
    ]
    await query.message.reply_text(
        "באיזה פורמט להפיק את הפלט?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_FORMAT


async def handle_purpose_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle purpose typed as text."""
    context.user_data["purpose"] = update.message.text.strip()

    keyboard = [
        [InlineKeyboardButton("מסמך מקור ידע (Knowledge Base)", callback_data="format:knowledge-base")],
        [InlineKeyboardButton("ניתוח מובנה (Structured Analysis)", callback_data="format:standard")],
    ]
    await update.message.reply_text(
        "באיזה פורמט להפיק את הפלט?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_FORMAT


async def handle_format_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle output format selection and start processing."""
    query = update.callback_query
    await query.answer()

    value = query.data.replace("format:", "")
    context.user_data["output_format"] = value

    format_label = "מסמך מקור ידע" if value == "knowledge-base" else "ניתוח מובנה"
    await query.edit_message_text(f"פורמט: {format_label}")

    # Build user_requests
    purpose = context.user_data.get("purpose", "")
    output_format = context.user_data["output_format"]
    user_requests = f"{output_format}: {purpose}" if purpose else f"{output_format}: full analysis"

    file_path = context.user_data["file_path"]
    file_name = context.user_data["file_name"]
    user = context.user_data["user"]
    session_type = context.user_data["session_type"]
    speakers = context.user_data["speakers"]
    language = context.user_data["language"]
    status_msg = context.user_data["status_msg"]
    telegram_id = update.effective_user.id

    try:
        await _process_and_reply(
            status_msg, file_path, file_name, user,
            session_type, speakers, language,
            user_requests, telegram_id,
        )
    except Exception as e:
        logger.error(f"Error processing file from {telegram_id}: {e}")
        try:
            await status_msg.edit_text(f"[x] Error:\n{str(e)[:500]}")
        except Exception:
            pass
    finally:
        _cleanup_conversation(context)

    return ConversationHandler.END


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command during interactive flow."""
    _cleanup_conversation(context)
    await update.message.reply_text("בוטל.")
    return ConversationHandler.END


async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle conversation timeout — clean up temp files."""
    _cleanup_conversation(context)
    return ConversationHandler.END


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

            # Extract passcode from URL query param or message text (for yt-dlp fallback)
            passcode = None
            m = re.search(r"[?&]pwd=(\w+)", url)
            if m:
                passcode = m.group(1)
            else:
                m = re.search(r"[Pp]asscode[:\s]+(\S+)", text)
                if m:
                    passcode = m.group(1)

            loop = asyncio.get_event_loop()

            # Download via Zoom API (returns dict of file paths)
            zoom_files = await loop.run_in_executor(
                None,
                lambda: download_zoom_recording(url, tmp_dir, passcode),
            )

            # Use audio file for transcription, fall back to video
            file_path = zoom_files.get("audio") or zoom_files.get("video")
            if not file_path:
                raise RuntimeError("No audio/video file downloaded from Zoom")

            vtt_path = zoom_files.get("transcript")

            await status_msg.edit_text(
                "[>] Processing Zoom recording...\n"
                "    This may take several minutes..."
            )

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
                    zoom_vtt_path=vtt_path,
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

    # Interactive file processing conversation
    file_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.AUDIO | filters.VIDEO | filters.VOICE | filters.VIDEO_NOTE | filters.Document.ALL,
                handle_file_entry,
            ),
        ],
        states={
            WAITING_TYPE: [
                CallbackQueryHandler(handle_type_choice, pattern=r"^type:"),
            ],
            WAITING_SPEAKERS: [
                CallbackQueryHandler(handle_speakers_callback, pattern=r"^speakers:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_speakers_text),
            ],
            WAITING_PURPOSE: [
                CallbackQueryHandler(handle_purpose_callback, pattern=r"^purpose:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_purpose_text),
            ],
            WAITING_FORMAT: [
                CallbackQueryHandler(handle_format_choice, pattern=r"^format:"),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, handle_timeout),
                CallbackQueryHandler(handle_timeout),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handle_cancel),
        ],
        conversation_timeout=600,
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(file_conv)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_zoom_link,
    ))

    logger.info("Zumo bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
