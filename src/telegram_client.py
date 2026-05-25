import os
import time
import asyncio
import logging
from pathlib import Path
from collections import defaultdict, deque
import httpx
from typing import Optional
from telethon import TelegramClient, events, errors
from src.config import API_ID, API_HASH, PHONE_NUMBER
from src.database_manager import get_all_instances_full, insert_event

logger = logging.getLogger(__name__)

# --- Rate limiting ---
# If a monitored channel sends ≥ FLOOD_THRESHOLD messages within FLOOD_WINDOW seconds,
# stop processing it for FLOOD_PAUSE seconds.
FLOOD_THRESHOLD = 15       # messages
FLOOD_WINDOW    = 10       # seconds
FLOOD_PAUSE     = 60       # seconds

# After a keyword+channel match fires a notification, ignore the same pair for this long.
# This default is overridden at runtime by the value stored in settings.
MATCH_COOLDOWN  = 60       # seconds (fallback only)

_channel_message_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
_channel_flood_until:   dict[str, float] = {}
_match_cooldowns:       dict[str, float] = {}

# --- Active client ---
client: Optional[TelegramClient] = None
_bg_task: Optional[asyncio.Task] = None
SESSION_FILE = str(Path(__file__).parent / "database" / "session")


def _start_bg_task(c: TelegramClient) -> None:
    """Start run_until_disconnected as a background task, skipping if one is already live."""
    global _bg_task
    if _bg_task is None or _bg_task.done():
        _bg_task = asyncio.create_task(c.run_until_disconnected())

async def setup_client():
    global client
    if client is None:
        client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH)
        
        # Add message handler
        @client.on(events.NewMessage)
        async def my_event_handler(event):
            await process_new_message(event)

    return client

async def get_client():
    if client is None:
        await setup_client()
    return client

async def start_client_bg():
    c = await get_client()
    if not c.is_connected():
        await c.connect()
    
    if await c.is_user_authorized():
        logger.info("Telegram client authorized. Starting background task...")
        _start_bg_task(c)
    else:
        logger.warning("Telegram client not authorized. Authenticate via the UI.")

async def stop_client():
    global client, _bg_task
    if _bg_task is not None and not _bg_task.done():
        _bg_task.cancel()
        _bg_task = None
    if client is not None and client.is_connected():
        await client.disconnect()
        logger.info("Telegram client disconnected.")

async def send_code():
    c = await get_client()
    if not c.is_connected():
        await c.connect()
    result = await c.send_code_request(PHONE_NUMBER)
    return result.phone_code_hash

async def verify_code(code: str, phone_code_hash: str):
    c = await get_client()
    try:
        await c.sign_in(PHONE_NUMBER, code, phone_code_hash=phone_code_hash)
        _start_bg_task(c)
        return {"status": "success"}
    except errors.SessionPasswordNeededError:
        return {"status": "2fa_required"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def verify_2fa(password: str):
    c = await get_client()
    try:
        await c.sign_in(password=password)
        _start_bg_task(c)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def is_authorized():
    c = await get_client()
    if not c.is_connected():
        await c.connect()
    return await c.is_user_authorized()

def _channel_in_list(channels, chat_id: str, chat_username: str) -> bool:
    """True if this chat matches any entry in an instance's channel list."""
    for c in channels:
        c_str = str(c).strip().lstrip("@")
        if not c_str:
            continue
        if c_str == chat_id or (chat_username and c_str.lower() == chat_username.lower()):
            return True
    return False


async def process_new_message(event):
    """Route a single incoming message through every configured instance.

    There is one Telegram connection (one account), so each message is offered
    to every instance independently: an instance only acts on it if the channel
    is in *its* list and the text matches *its* keywords. Cooldowns and the
    activity log are tracked per instance, so instances stay fully isolated.
    """
    instances = await get_all_instances_full()
    if not instances:
        return

    chat = await event.get_chat()
    chat_id = str(event.chat_id)
    chat_username = getattr(chat, 'username', '') or ''

    # Is this channel monitored by *any* instance? (early exit before rate logic)
    relevant = [
        inst for inst in instances
        if _channel_in_list(inst.get("channels", []), chat_id, chat_username)
    ]
    if not relevant:
        return

    now = time.monotonic()

    # --- Flood guard (per channel, shared across instances) ---
    flood_until = _channel_flood_until.get(chat_id, 0)
    if now < flood_until:
        logger.debug("Flood guard active for %s — dropping message.", chat_id)
        return

    times = _channel_message_times[chat_id]
    times.append(now)
    recent = sum(1 for t in times if now - t < FLOOD_WINDOW)
    if recent >= FLOOD_THRESHOLD:
        _channel_flood_until[chat_id] = now + FLOOD_PAUSE
        logger.warning(
            "Flood guard triggered for channel %s (%d msgs in %ds). "
            "Pausing processing for %ds.",
            chat_id, recent, FLOOD_WINDOW, FLOOD_PAUSE
        )
        return

    message_text = event.message.message or ""

    # Build the message link once — it's the same for every instance.
    if chat_id.startswith("-100"):
        message_link = f"https://t.me/c/{chat_id[4:]}/{event.message.id}"
    elif getattr(chat, 'username', None):
        message_link = f"https://t.me/{chat.username}/{event.message.id}"
    else:
        message_link = "No link available"

    channel_name = getattr(chat, 'title', None) or getattr(chat, 'username', 'Unknown')

    for inst in relevant:
        await _dispatch_for_instance(
            inst, now, chat_id, channel_name, message_text, message_link, event
        )


async def _dispatch_for_instance(inst, now, chat_id, channel_name, message_text, message_link, event):
    keywords = inst.get("keywords", [])
    excluded_keywords = inst.get("excluded_keywords", [])
    webhook_url = inst.get("webhook_url", "")
    tg_bot_token = inst.get("tg_bot_token", "")
    tg_chat_id = inst.get("tg_chat_id", "")
    match_cooldown = inst.get("match_cooldown", MATCH_COOLDOWN)
    instance_id = inst["id"]

    if not keywords or (not webhook_url and not (tg_bot_token and tg_chat_id)):
        return

    text_lower = message_text.lower()

    matched_keyword = next((kw for kw in keywords if kw.lower() in text_lower), None)
    if not matched_keyword:
        return

    # --- Exclusion filter ---
    # If any excluded word appears in the message, suppress the match entirely.
    excluded_hit = next(
        (ex for ex in excluded_keywords if ex.strip() and ex.lower() in text_lower),
        None,
    )
    if excluded_hit:
        logger.debug("Excluded word '%s' present — suppressing match '%s' in %s (instance %s).",
                     excluded_hit, matched_keyword, chat_id, instance_id)
        return

    # --- Match cooldown (per instance + channel + keyword) ---
    cooldown_key = f"{instance_id}:{chat_id}:{matched_keyword.lower()}"
    if match_cooldown > 0:
        if now < _match_cooldowns.get(cooldown_key, 0):
            logger.debug("Match cooldown active for '%s' in %s (instance %s) — skipping.",
                         matched_keyword, chat_id, instance_id)
            return
        _match_cooldowns[cooldown_key] = now + match_cooldown

    payload = {
        "channel_id": chat_id,
        "channel_name": channel_name,
        "message_id": event.message.id,
        "message_text": message_text,
        "message_link": message_link,
        "matched_keyword": matched_keyword,
        "date": event.message.date.isoformat(),
        "sender_id": str(event.message.sender_id) if event.message.sender_id else None,
    }

    # Persist to this instance's activity log
    asyncio.create_task(insert_event(
        instance_id=instance_id,
        channel_id=chat_id,
        channel_name=channel_name,
        keyword=matched_keyword,
        message_text=message_text[:500],
        message_link=message_link,
        matched_at=payload["date"],
    ))

    if webhook_url:
        asyncio.create_task(send_to_webhook(webhook_url, payload))

    if tg_bot_token and tg_chat_id:
        asyncio.create_task(send_to_tg_bot(tg_bot_token, tg_chat_id, payload))

async def send_to_webhook(url: str, payload: dict):
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            response = await http.post(url, json=payload)
        if response.status_code >= 400:
            logger.error("Webhook failed with status %s", response.status_code)
    except Exception as e:
        logger.error("Failed to send webhook: %s", e)

def _escape_md(text: str) -> str:
    """Escape special characters for Telegram Markdown v1."""
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text

async def send_to_tg_bot(bot_token: str, chat_id: str, payload: dict):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Ensure chat_id is properly formatted if it's a username
    chat_id_str = str(chat_id).strip()
    if not chat_id_str.startswith('@') and not chat_id_str.replace('-', '').isdigit():
        chat_id_str = f"@{chat_id_str}"

    text = (
        f"🔔 *New Match:* {_escape_md(payload.get('matched_keyword', ''))}\n"
        f"📢 *Channel:* {_escape_md(payload.get('channel_name', ''))}\n"
        f"🔗 *Link:* {payload.get('message_link', '')}\n\n"
        f"{payload.get('message_text', '')}"
    )
    
    data = {
        "chat_id": chat_id_str,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            response = await http.post(url, json=data)
        if response.status_code >= 400:
            logger.error("TG Bot send failed with status %s: %s", response.status_code, response.text)
    except Exception as e:
        logger.error("Failed to send to TG bot: %s", e)
