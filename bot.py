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
(
    WAITING_TYPE,
    WAITING_SPEAKERS,
    WAITING_PURPOSE,
    WAITING_FORMAT,
    WAITING_CONVERSATION,
    WAITING_CONFIRM,
) = range(6)

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
    "extra_context", "gemini_text", "hebrew_ai_text",
    "preprocess_task", "preprocess_done",
    "proceed_started", "confirm_started", "last_prompt_msg_id",
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
        await status_msg.edit_text(f"⏳ Large file ({size_mb:.1f} MB) — downloading via MTProto...")
        try:
            from src.telegram_downloader import download_large_file

            await download_large_file(
                file_id=file_obj.file_id,
                chat_id=msg.chat_id,
                message_id=msg.message_id,
                dest_path=file_path,
            )
        except RuntimeError as e:
            await status_msg.edit_text(f"❌ Large file download failed:\n{str(e)}")
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
                    f"⏳ Processing: {file_name}\n"
                    f"    Type: {session_type}\n"
                    f"    Stage: {stage}...\n"
                    f"    Elapsed: {time_str}"
                )
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def _run_preprocess(file_path, user, language):
    """Run compression + dual transcription in background.

    Returns (hebrew_ai_text, gemini_text).
    Runs in executor since Hebrew AI uses blocking requests.
    """
    from src.audio import compress_for_upload, get_duration, detect_silence, remove_silence
    from src.config import SILENCE_THRESHOLD_DB

    loop = asyncio.get_event_loop()

    def _do_preprocess():
        import tempfile as _tf
        tmp = Path(_tf.mkdtemp(prefix="zumo-pre-"))

        # Silence removal
        silences = detect_silence(
            file_path, SILENCE_THRESHOLD_DB, user.silence_threshold_seconds,
        )
        trimmed_path = tmp / "trimmed.mp3"
        remove_silence(file_path, silences, trimmed_path)

        # Compress
        upload_path = tmp / "compressed.mp3"
        compress_for_upload(trimmed_path, upload_path)

        # Dual transcription (parallel)
        from concurrent.futures import ThreadPoolExecutor
        from src.transcriber import transcribe
        from src.gemini_transcriber import transcribe_with_diarization

        gemini_key = os.getenv("GEMINI_API_KEY", "")
        h_text = ""
        g_text = ""

        def _hebrew():
            t, _ = transcribe(upload_path, user.hebrew_ai_api_key, language)
            return t

        def _gemini():
            if not gemini_key:
                return ""
            return transcribe_with_diarization(upload_path, api_key=gemini_key)

        with ThreadPoolExecutor(max_workers=2) as pool:
            fh = pool.submit(_hebrew)
            fg = pool.submit(_gemini)
            try:
                h_text = fh.result()
            except Exception as e:
                logger.error(f"Hebrew AI preprocess failed: {e}")
            try:
                g_text = fg.result()
            except Exception as e:
                logger.error(f"Gemini preprocess failed: {e}")

        # Cleanup temp
        shutil.rmtree(tmp, ignore_errors=True)
        return h_text, g_text

    return await loop.run_in_executor(None, _do_preprocess)


def _analyze_gemini_speakers(gemini_text: str) -> dict:
    """Quick analysis of Gemini transcript to extract speaker info.

    Returns dict with:
      - num_speakers: int
      - speaker_labels: list of unique labels found
      - summary_hint: short string describing what was detected
    """
    if not gemini_text:
        return {"num_speakers": 0, "speaker_labels": [], "summary_hint": ""}

    labels = re.findall(r"(Speaker [A-Z])", gemini_text)
    unique = list(dict.fromkeys(labels))  # preserve order
    return {
        "num_speakers": len(unique),
        "speaker_labels": unique,
        "summary_hint": f"זוהו {len(unique)} דוברים" if unique else "",
    }


async def _process_and_reply(
    status_msg, file_path, file_name, user,
    session_type, speakers, language, user_requests, telegram_id,
    hebrew_ai_text="", gemini_text="",
):
    """Run the pipeline and send the result.

    If hebrew_ai_text and gemini_text are provided (from preprocess),
    skip the transcription steps and go straight to analysis.
    """
    await status_msg.edit_text(
        f"⏳ Processing: {file_name}\n"
        f"    Type: {session_type}\n"
        f"    Starting pipeline..."
    )

    ticker = asyncio.create_task(
        _progress_ticker(status_msg, file_name, session_type)
    )

    try:
        if hebrew_ai_text or gemini_text:
            # We already have transcriptions — run analysis directly
            from src.processor import analyze_transcript, generate_summary
            from src.formatter import format_analysis_md, format_transcript_md, generate_folder_name
            from src.storage import ensure_repo_structure, save_session
            from src.audio import get_duration
            from datetime import datetime

            if hebrew_ai_text:
                primary_text = hebrew_ai_text
                side_gemini_text = gemini_text
                transcriber_used = "both" if gemini_text else "hebrew-ai"
            else:
                primary_text = gemini_text
                side_gemini_text = ""
                transcriber_used = "gemini-only"

            loop = asyncio.get_event_loop()

            original_duration = await loop.run_in_executor(None, lambda: get_duration(file_path))
            timestamp = datetime.now()

            # Summary — non-fatal if it fails
            try:
                summary = await loop.run_in_executor(
                    None, lambda: generate_summary(primary_text, user.anthropic_api_key)
                )
            except Exception as e:
                logger.error(f"Summary generation failed: {e}")
                summary = ""

            # Analysis — non-fatal. On failure we still publish transcript-only.
            analysis = None
            analysis_error = ""
            try:
                analysis = await loop.run_in_executor(
                    None, lambda: analyze_transcript(
                        primary_text, user.anthropic_api_key,
                        session_type, speakers, language,
                        user_requests=user_requests,
                        gemini_text=side_gemini_text,
                    )
                )
            except Exception as e:
                analysis_error = str(e)
                logger.error(f"Analysis failed, publishing transcript-only: {e}")

            analysis_failed = not analysis  # covers exception AND empty/None

            folder_name = generate_folder_name(
                session_type, speakers or file_path.stem, timestamp,
            )
            transcript_md = format_transcript_md(
                primary_text, file_path.stem, session_type, speakers, language,
                original_duration, original_duration, 0, timestamp,
            )
            analysis_md = format_analysis_md(
                analysis, summary, session_type, speakers, timestamp,
            ) if analysis else None

            ensure_repo_structure(user.dashboard_slug)
            dashboard_url = await loop.run_in_executor(
                None, lambda: save_session(
                    user.dashboard_slug, folder_name,
                    transcript_md, analysis_md, summary,
                    user_name=user.name,
                    pw_hash=user.web_password_hash,
                )
            )

            result = {
                "status": "success",
                "folder_name": folder_name,
                "transcript_length": len(primary_text),
                "original_duration": original_duration,
                "dashboard_url": dashboard_url,
                "transcriber_used": transcriber_used,
                "analysis_failed": analysis_failed,
                "analysis_error": analysis_error,
            }
        else:
            # Fallback: run the full pipeline
            from pipeline import process_file

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

        notes = []
        if result.get("transcriber_used") == "gemini-only":
            reason = result.get("fallback_reason", "")
            note = "⚠️ תמלול נעשה ב-Gemini בלבד (Hebrew AI לא זמין"
            if reason:
                note += f": {reason[:100]}"
            note += ")"
            notes.append(note)
        if result.get("analysis_failed"):
            reason = result.get("analysis_error", "")
            note = "⚠️ ניתוח נכשל — תמלול בלבד זמין בעמוד"
            if reason:
                note += f" ({reason[:100]})"
            notes.append(note)

        head = "🎉 הסתיים" if not notes else "✅ הסתיים עם הערות"
        summary_text = (
            f"{head}\n"
            + ("\n".join(notes) + "\n\n" if notes else "\n")
            + f"Duration: {duration_str}\n"
            + f"Transcript: {chars:,} characters\n"
            + f"Folder: {result.get('folder_name', '')}\n\n"
            + f"{link}"
        )

        try:
            await status_msg.edit_text(head)
        except Exception:
            pass
        # Send a NEW message so Telegram fires a push notification
        await status_msg.reply_text(summary_text)
    else:
        err = result.get("error", "Unknown")[:500]
        try:
            await status_msg.edit_text("❌ נכשל")
        except Exception:
            pass
        await status_msg.reply_text(f"❌ Error:\n{err}")


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
            await update.message.reply_text(f"⚠️ {diag}")
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

    status_msg = await msg.reply_text("⏳ Downloading file...")

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
                await status_msg.edit_text("❌ נכשל")
            except Exception:
                pass
            try:
                await status_msg.reply_text(f"❌ Error:\n{str(e)[:500]}")
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
    context.user_data["extra_context"] = []
    context.user_data["preprocess_done"] = False

    await status_msg.edit_text(
        "✅ File downloaded.\n"
        "⏳ Starting transcription in background..."
    )

    # Start preprocessing (compression + dual transcription) in background
    preprocess_task = asyncio.create_task(
        _run_preprocess(file_path, user, language)
    )
    context.user_data["preprocess_task"] = preprocess_task

    # Ask session type while transcription runs in background
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

    type_label = dict(SESSION_TYPE_LABELS).get(value, value) if value != "skip" else "דלג"
    await query.edit_message_text(f"סוג: {type_label}")

    # Check if preprocess is done — if so, suggest speakers from Gemini
    preprocess_task = context.user_data.get("preprocess_task")
    gemini_hint = ""

    if preprocess_task and preprocess_task.done():
        try:
            h_text, g_text = preprocess_task.result()
            context.user_data["hebrew_ai_text"] = h_text
            context.user_data["gemini_text"] = g_text
            context.user_data["preprocess_done"] = True

            info = _analyze_gemini_speakers(g_text)
            if info["num_speakers"] > 0:
                gemini_hint = f"\n\n{info['summary_hint']} בהקלטה."
        except Exception:
            pass

    keyboard = [[InlineKeyboardButton("דלג (Skip)", callback_data="speakers:skip")]]
    await query.message.reply_text(
        f"מי הדוברים? (שמות מופרדים בפסיק, או לחץ דלג){gemini_hint}",
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
    """Handle output format selection — move to free-text conversation."""
    query = update.callback_query
    await query.answer()

    value = query.data.replace("format:", "")
    context.user_data["output_format"] = value

    format_label = "מסמך מקור ידע" if value == "knowledge-base" else "ניתוח מובנה"
    await query.edit_message_text(f"פורמט: {format_label}")

    # Ask for additional context (WAITING_CONVERSATION)
    keyboard = [
        [InlineKeyboardButton("המשך (Continue)", callback_data="conversation:done")],
    ]
    prompt = await query.message.reply_text(
        "יש משהו נוסף שחשוב לי לדעת על השיחה הזאת?\n"
        "אפשר לכתוב הקשר, רקע, או בקשות מיוחדות.\n"
        "או לחץ המשך.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.user_data["last_prompt_msg_id"] = prompt.message_id
    return WAITING_CONVERSATION


async def handle_conversation_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text additional context from user.

    Long texts that Telegram splits into multiple messages arrive as separate
    updates. To avoid showing multiple live "המשך" buttons (which can spawn
    parallel pipelines if pressed), we strip the previous prompt's buttons
    before sending a new one.
    """
    text = update.message.text.strip()

    # Check for "done" signals
    done_signals = {"זהו", "המשך", "סיים", "done", "continue", "go", "יאללה"}
    if text.lower() in done_signals:
        return await _proceed_to_confirm(update.message, context)

    # Accumulate context
    context.user_data.setdefault("extra_context", []).append(text)

    # Remove the previous "המשך" button so only the newest one is live
    prev_id = context.user_data.get("last_prompt_msg_id")
    if prev_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=prev_id,
                reply_markup=None,
            )
        except Exception:
            pass

    keyboard = [
        [InlineKeyboardButton("זהו, המשך (Done)", callback_data="conversation:done")],
    ]
    prompt = await update.message.reply_text(
        "קיבלתי. עוד משהו? או לחץ המשך.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.user_data["last_prompt_msg_id"] = prompt.message_id
    return WAITING_CONVERSATION


async def handle_conversation_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle conversation done button.

    Idempotent: if the flow already advanced (e.g. user double-clicked, or
    pressed multiple live buttons from split messages), silently toast and
    return instead of triggering _proceed_to_confirm again.
    """
    query = update.callback_query
    if context.user_data.get("proceed_started"):
        await query.answer(text="⏳ כבר בעיבוד", show_alert=False)
        return WAITING_CONFIRM
    context.user_data["proceed_started"] = True
    await query.answer()
    await query.edit_message_text("ממשיכים...")
    return await _proceed_to_confirm(query.message, context)


async def _proceed_to_confirm(message, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation summary before processing."""
    session_type = context.user_data.get("session_type", "other")
    speakers = context.user_data.get("speakers", "")
    purpose = context.user_data.get("purpose", "")
    output_format = context.user_data.get("output_format", "standard")
    extra = context.user_data.get("extra_context", [])

    type_info = SESSION_TYPES.get(session_type, {})
    type_label = type_info.get("he", session_type)
    format_label = "מסמך מקור ידע" if output_format == "knowledge-base" else "ניתוח מובנה"

    summary_lines = [
        f"סוג: {type_label}",
        f"דוברים: {speakers or 'לא צוין'}",
        f"מטרה: {purpose or 'ניתוח מלא'}",
        f"פורמט: {format_label}",
    ]
    if extra:
        summary_lines.append(f"הקשר נוסף: {'; '.join(extra)}")

    # Check preprocess status
    preprocess_task = context.user_data.get("preprocess_task")
    preprocess_done = context.user_data.get("preprocess_done", False)
    if preprocess_task and preprocess_task.done() and not preprocess_done:
        try:
            h_text, g_text = preprocess_task.result()
            context.user_data["hebrew_ai_text"] = h_text
            context.user_data["gemini_text"] = g_text
            context.user_data["preprocess_done"] = True
        except Exception:
            pass

    if context.user_data.get("preprocess_done"):
        summary_lines.append("\nתמלול הושלם ברקע -- מוכן לעיבוד.")
    else:
        summary_lines.append("\nתמלול עדיין רץ ברקע -- העיבוד ימשיך כשיסיים.")

    keyboard = [
        [InlineKeyboardButton("מאשר (Confirm)", callback_data="confirm:yes")],
        [InlineKeyboardButton("ביטול (Cancel)", callback_data="confirm:cancel")],
    ]
    await message.reply_text(
        "סיכום:\n" + "\n".join(summary_lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation — start processing.

    Idempotent on "yes": second click answers with toast and returns, so a
    double-tap or a lingering button from a retried flow cannot spawn a
    second pipeline.
    """
    query = update.callback_query

    value = query.data.replace("confirm:", "")
    if value == "cancel":
        await query.answer()
        await query.edit_message_text("בוטל.")
        _cleanup_conversation(context)
        return ConversationHandler.END

    if context.user_data.get("confirm_started"):
        await query.answer(text="⏳ כבר בעיבוד", show_alert=False)
        return ConversationHandler.END
    context.user_data["confirm_started"] = True
    await query.answer()

    await query.edit_message_text("מאושר. מתחיל עיבוד...")

    # Build user_requests
    purpose = context.user_data.get("purpose", "")
    output_format = context.user_data.get("output_format", "standard")
    extra = context.user_data.get("extra_context", [])

    parts = [output_format]
    if purpose:
        parts.append(purpose)
    if extra:
        parts.extend(extra)
    user_requests = ": ".join(parts[:2])
    if extra:
        user_requests += "\n\nAdditional context from user:\n" + "\n".join(extra)
    if not purpose and not extra:
        user_requests = f"{output_format}: full analysis"

    file_path = context.user_data["file_path"]
    file_name = context.user_data["file_name"]
    user = context.user_data["user"]
    session_type = context.user_data["session_type"]
    speakers = context.user_data["speakers"]
    language = context.user_data["language"]
    status_msg = context.user_data["status_msg"]
    telegram_id = update.effective_user.id

    # Wait for preprocess if not done
    preprocess_task = context.user_data.get("preprocess_task")
    hebrew_ai_text = context.user_data.get("hebrew_ai_text", "")
    gemini_text = context.user_data.get("gemini_text", "")

    if preprocess_task and not context.user_data.get("preprocess_done"):
        await status_msg.edit_text(
            f"⏳ Processing: {file_name}\n"
            f"    Waiting for transcription to complete..."
        )
        try:
            hebrew_ai_text, gemini_text = await preprocess_task
            context.user_data["hebrew_ai_text"] = hebrew_ai_text
            context.user_data["gemini_text"] = gemini_text
        except Exception as e:
            logger.error(f"Preprocess failed: {e}")
            hebrew_ai_text = ""
            gemini_text = ""

    try:
        await _process_and_reply(
            status_msg, file_path, file_name, user,
            session_type, speakers, language,
            user_requests, telegram_id,
            hebrew_ai_text=hebrew_ai_text,
            gemini_text=gemini_text,
        )
    except Exception as e:
        logger.error(f"Error processing file from {telegram_id}: {e}")
        try:
            await status_msg.edit_text("❌ נכשל")
        except Exception:
            pass
        try:
            await status_msg.reply_text(f"❌ Error:\n{str(e)[:500]}")
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
    """Handle conversation timeout -- clean up temp files."""
    _cleanup_conversation(context)
    return ConversationHandler.END


async def handle_zoom_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process text messages containing Zoom recording links."""
    telegram_id = update.effective_user.id
    user_info = find_user_by_telegram_id(telegram_id)

    if not user_info:
        diag = diagnose_telegram_id(telegram_id)
        if diag:
            await update.message.reply_text(f"⚠️ {diag}")
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
        status_msg = await update.message.reply_text("⏳ Downloading Zoom recording...")

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
                "⏳ Processing Zoom recording...\n"
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

                notes = []
                if result.get("transcriber_used") == "gemini-only":
                    reason = result.get("fallback_reason", "")
                    note = "⚠️ תמלול נעשה ב-Gemini בלבד (Hebrew AI לא זמין"
                    if reason:
                        note += f": {reason[:100]}"
                    note += ")"
                    notes.append(note)

                head = "🎉 הסתיים" if not notes else "✅ הסתיים עם הערות"
                summary_text = (
                    f"{head}\n"
                    + ("\n".join(notes) + "\n\n" if notes else "\n")
                    + f"Duration: {duration_str}\n"
                    + f"Transcript: {chars:,} characters\n"
                    + f"Folder: {result.get('folder_name', '')}\n\n"
                    + f"{link}"
                )

                try:
                    await status_msg.edit_text(head)
                except Exception:
                    pass
                await status_msg.reply_text(summary_text)
            else:
                err = result.get("error", "Unknown")[:500]
                try:
                    await status_msg.edit_text("❌ נכשל")
                except Exception:
                    pass
                await status_msg.reply_text(f"❌ Error:\n{err}")

        except Exception as e:
            logger.error(f"Error processing Zoom link from {telegram_id}: {e}")
            try:
                await status_msg.edit_text("❌ נכשל")
            except Exception:
                pass
            try:
                await status_msg.reply_text(f"❌ Error:\n{str(e)[:500]}")
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
            WAITING_CONVERSATION: [
                CallbackQueryHandler(handle_conversation_done, pattern=r"^conversation:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation_text),
            ],
            WAITING_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=r"^confirm:"),
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
