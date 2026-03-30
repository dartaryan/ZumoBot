"""Download large Telegram files via MTProto (pyrogram).

The Telegram Bot API HTTP interface has a hard 20MB download limit.
For files exceeding this, we use pyrogram's MTProto client to download
directly from Telegram's servers.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BOT_API_SIZE = 20 * 1024 * 1024  # 20 MB


async def download_large_file(
    file_id: str,
    chat_id: int,
    message_id: int,
    dest_path: Path,
) -> Path:
    """Download a Telegram file via MTProto for large files.

    Uses pyrogram Client with in_memory=True (no session files on disk).
    Authenticates as a bot using api_id + api_hash + bot_token.

    Returns the destination Path on success.
    """
    try:
        from pyrogram import Client
    except ImportError:
        raise RuntimeError(
            "pyrogram is not installed. Install it to download files > 20MB:\n"
            "  pip install pyrogram>=2.0.0"
        )

    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    if not api_id or not api_hash:
        raise RuntimeError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for large file downloads.\n"
            "Get them from https://my.telegram.org -> API development tools.\n"
            "Add them to your .env file."
        )

    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

    logger.info(f"Downloading large file via MTProto: message {message_id} in chat {chat_id}")

    async with Client(
        name="zumo_bot_downloader",
        api_id=int(api_id),
        api_hash=api_hash,
        bot_token=bot_token,
        in_memory=True,
    ) as app:
        msg = await app.get_messages(chat_id, message_id)
        await app.download_media(msg, file_name=str(dest_path))

    logger.info(f"Large file downloaded to {dest_path}")
    return dest_path
