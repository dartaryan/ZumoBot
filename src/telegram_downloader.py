"""Download large Telegram files via MTProto (pyrogram).

The Telegram Bot API HTTP interface has a hard 20MB download limit.
For files exceeding this, we use pyrogram's MTProto client to download
directly from Telegram's servers.
"""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BOT_API_SIZE = 20 * 1024 * 1024  # 20 MB


def _download_in_own_loop(
    api_id: str,
    api_hash: str,
    bot_token: str,
    chat_id: int,
    message_id: int,
    dest_path: Path,
) -> Path:
    """Run pyrogram download in a fresh event loop (called from a thread)."""
    from pyrogram import Client

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def _do_download():
            async with Client(
                name="zumo_bot_downloader",
                api_id=int(api_id),
                api_hash=api_hash,
                bot_token=bot_token,
                in_memory=True,
                no_updates=True,
            ) as app:
                msg = await app.get_messages(chat_id, message_id)
                await app.download_media(msg, file_name=str(dest_path))

        loop.run_until_complete(_do_download())
    finally:
        loop.close()
    return dest_path


async def download_large_file(
    file_id: str,
    chat_id: int,
    message_id: int,
    dest_path: Path,
) -> Path:
    """Download a Telegram file via MTProto for large files.

    Runs pyrogram in a separate thread with its own event loop to avoid
    conflicts with python-telegram-bot's event loop.
    """
    try:
        from pyrogram import Client  # noqa: F401
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

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _download_in_own_loop,
        api_id, api_hash, bot_token, chat_id, message_id, dest_path,
    )

    logger.info(f"Large file downloaded to {dest_path}")
    return dest_path
