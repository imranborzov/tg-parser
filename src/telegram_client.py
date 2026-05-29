import os
import re
import time
import random
import asyncio
import logging
from pathlib import Path
from collections import defaultdict, deque
import httpx
from typing import Optional
from telethon import TelegramClient, events, errors, utils
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from src.config import DATA_DIR
from src.database_manager import (
    get_instance,
    list_instances,
    insert_event,
    update_instance,
    get_next_pending_join,
    get_pending_join_instance_ids,
    update_join_status,
    count_joins_today,
)

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

# Flood/cooldown state is keyed per instance (e.g. "<instance_id>:<chat_id>") so
# instances never interfere with each other.
_channel_message_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
_channel_flood_until:   dict[str, float] = {}
_match_cooldowns:       dict[str, float] = {}

# --- One Telegram client per instance ---
DB_DIR = DATA_DIR
LEGACY_SESSION = DB_DIR / "session.session"  # pre-multi-account single session

_clients:  dict[int, TelegramClient] = {}
_bg_tasks: dict[int, asyncio.Task] = {}
_paused_instances: set[int] = set()


def pause_instance(instance_id: int) -> None:
    _paused_instances.add(instance_id)


def resume_instance(instance_id: int) -> None:
    _paused_instances.discard(instance_id)


def is_instance_paused(instance_id: int) -> bool:
    return instance_id in _paused_instances


def _session_path(instance_id: int) -> str:
    """Telethon session file stem for an instance (file is <stem>.session)."""
    return str(DB_DIR / f"session_{instance_id}")


def _has_credentials(inst: dict) -> bool:
    if not inst:
        return False
    api_id = str(inst.get("api_id", "")).strip()
    api_hash = str(inst.get("api_hash", "")).strip()
    phone = str(inst.get("phone", "")).strip()
    return bool(api_id and api_id.isdigit() and api_hash and phone)


def _build_client(inst: dict) -> TelegramClient:
    """Construct a TelegramClient for an instance and bind its message handler."""
    instance_id = inst["id"]
    client = TelegramClient(_session_path(instance_id), int(inst["api_id"]), inst["api_hash"])

    async def _handler(event, _iid=instance_id):
        await process_message_for_instance(_iid, event)

    client.add_event_handler(_handler, events.NewMessage)
    return client


async def get_client(instance_id: int) -> Optional[TelegramClient]:
    """Return (building if needed) the client for an instance, or None if it has
    no usable credentials yet."""
    client = _clients.get(instance_id)
    if client is not None:
        return client
    inst = await get_instance(instance_id)
    if not _has_credentials(inst):
        return None
    client = _build_client(inst)
    _clients[instance_id] = client
    return client


def _start_bg_task(instance_id: int, client: TelegramClient) -> None:
    task = _bg_tasks.get(instance_id)
    if task is None or task.done():
        _bg_tasks[instance_id] = asyncio.create_task(client.run_until_disconnected())


async def _adopt_legacy_session():
    """Migration: hand the old single `session.session` to the oldest instance so
    upgrades stay logged in instead of forcing a re-auth."""
    if not LEGACY_SESSION.exists():
        return
    instances = await list_instances()
    if not instances:
        return
    target_id = instances[0]["id"]
    target = Path(_session_path(target_id) + ".session")
    if target.exists():
        return  # Instance already has its own session
    try:
        LEGACY_SESSION.rename(target)
        logger.info("Adopted legacy session for instance %s.", target_id)
    except OSError as e:
        logger.warning("Could not adopt legacy session: %s", e)


async def start_all_clients_bg():
    """On boot, connect every instance that has credentials and start listening
    for those already authorized."""
    await _adopt_legacy_session()
    for meta in await list_instances():
        instance_id = meta["id"]
        try:
            client = await get_client(instance_id)
            if client is None:
                continue
            if not client.is_connected():
                await client.connect()
            if await client.is_user_authorized():
                logger.info("Instance %s authorized — listening.", instance_id)
                _start_bg_task(instance_id, client)
            else:
                logger.info("Instance %s has credentials but is not authorized yet.", instance_id)
        except Exception as e:
            logger.error("Failed to start client for instance %s: %s", instance_id, e)
    # Drains bulk-upload join queues across all instances.
    start_join_worker()


async def reset_client(instance_id: int):
    """Tear down an instance's client (e.g. after credentials change) so the next
    use rebuilds it. The session file is left in place."""
    task = _bg_tasks.pop(instance_id, None)
    if task is not None and not task.done():
        task.cancel()
    client = _clients.pop(instance_id, None)
    if client is not None and client.is_connected():
        try:
            await client.disconnect()
        except Exception:
            pass


async def delete_client(instance_id: int):
    """Stop an instance's client and remove its session file(s)."""
    await reset_client(instance_id)
    stem = _session_path(instance_id)
    for suffix in (".session", ".session-journal"):
        try:
            os.remove(stem + suffix)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not remove session file %s%s: %s", stem, suffix, e)


async def stop_all_clients():
    await stop_join_worker()
    for instance_id in list(_clients.keys()):
        await reset_client(instance_id)


# --- Per-instance auth flow ---

async def send_code(instance_id: int):
    client = await get_client(instance_id)
    if client is None:
        raise ValueError("Set this instance's API ID, API hash, and phone first.")
    if not client.is_connected():
        await client.connect()
    inst = await get_instance(instance_id)
    result = await client.send_code_request(inst["phone"])
    return result.phone_code_hash


async def verify_code(instance_id: int, code: str, phone_code_hash: str):
    client = await get_client(instance_id)
    if client is None:
        return {"status": "error", "message": "Credentials not configured."}
    inst = await get_instance(instance_id)
    try:
        await client.sign_in(inst["phone"], code, phone_code_hash=phone_code_hash)
        _start_bg_task(instance_id, client)
        return {"status": "success"}
    except errors.SessionPasswordNeededError:
        return {"status": "2fa_required"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def verify_2fa(instance_id: int, password: str):
    client = await get_client(instance_id)
    if client is None:
        return {"status": "error", "message": "Credentials not configured."}
    try:
        await client.sign_in(password=password)
        _start_bg_task(instance_id, client)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def is_authorized(instance_id: int) -> bool:
    client = await get_client(instance_id)
    if client is None:
        return False
    try:
        if not client.is_connected():
            await client.connect()
        return await client.is_user_authorized()
    except Exception as e:
        logger.error("Authorization check failed for instance %s: %s", instance_id, e)
        return False


# --- Bulk channel joining ---
# Joining channels is heavily rate-limited by Telegram. We pace joins per
# instance with a RANDOM gap (so the cadence doesn't look botlike) and stop
# after DAILY_JOIN_CAP successes per account per day to avoid getting flagged.
JOIN_MIN_INTERVAL = 60    # seconds — shortest gap between joins for one instance
JOIN_MAX_INTERVAL = 150   # seconds — longest gap
DAILY_JOIN_CAP    = 45    # max successful joins per instance per UTC day
_JOIN_TICK        = 5     # how often the worker wakes to look for work

_join_worker_task: Optional[asyncio.Task] = None
# instance_id -> monotonic time before which the instance may not join again.
_next_join_at: dict[int, float] = {}
# Instances whose join queue is manually paused (in-memory, resets on restart).
_joins_paused: set[int] = set()


def _schedule_next_join(instance_id: int, now: float) -> None:
    """Set a randomized cooldown before this instance's next join attempt."""
    _next_join_at[instance_id] = now + random.uniform(JOIN_MIN_INTERVAL, JOIN_MAX_INTERVAL)


def pause_joins(instance_id: int) -> None:
    _joins_paused.add(instance_id)


def resume_joins(instance_id: int) -> None:
    _joins_paused.discard(instance_id)


def is_joins_paused(instance_id: int) -> bool:
    return instance_id in _joins_paused

# t.me/+HASH or t.me/joinchat/HASH -> private invite; t.me/NAME -> public username.
_INVITE_RE = re.compile(r"(?:t\.me/|telegram\.me/)(?:joinchat/|\+)([\w-]+)", re.IGNORECASE)
_PUBLIC_RE = re.compile(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]{4,32})/?$", re.IGNORECASE)
# Bare usernames must be explicitly @-prefixed. We deliberately do NOT treat an
# unadorned word as a username — a spreadsheet has arbitrary text columns
# (names, notes, headers) and capturing those would waste the daily join cap.
_USERNAME_RE = re.compile(r"^@([A-Za-z0-9_]{4,32})$")


def normalize_link(raw: str) -> Optional[dict]:
    """Parse one cell/line into a join job, or None if it isn't a usable link.

    Returns {"kind": "invite"|"public", "identifier": ..., "raw_link": raw}.
    Accepts t.me links (public or invite) and explicit @usernames; plain text is
    ignored so arbitrary spreadsheet columns don't generate junk join attempts.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    m = _INVITE_RE.search(s)
    if m:
        return {"kind": "invite", "identifier": m.group(1), "raw_link": s}

    m = _PUBLIC_RE.search(s)
    if m:
        uname = m.group(1)
        if uname.lower() not in ("joinchat", "c"):
            return {"kind": "public", "identifier": uname.lower(), "raw_link": s}

    m = _USERNAME_RE.match(s)
    if m:
        return {"kind": "public", "identifier": m.group(1).lower(), "raw_link": s}

    return None


async def _add_channel_to_instance(instance_id: int, value: str):
    """Append a resolved channel identifier to the instance's filter list (deduped)."""
    inst = await get_instance(instance_id)
    if not inst:
        return
    channels = list(inst.get("channels", []))
    if value not in channels:
        channels.append(value)
        await update_instance(instance_id, channels=channels)


def _is_broadcast(obj) -> bool:
    """True for a broadcast channel (not a supergroup/megagroup or basic group).
    Works on Channel entities and on ChatInvite previews, which share the flags."""
    return bool(getattr(obj, "broadcast", False)) and not getattr(obj, "megagroup", False)


async def _classify_and_join(client: TelegramClient, job: dict, include_channels: bool):
    """Resolve the target's type *before* joining. Broadcast channels are skipped
    unless `include_channels` is set. Returns (outcome, value) where outcome is
    'joined' (value = stored filter id) or 'skipped' (value = reason). Raises on
    real join errors."""
    kind = job["kind"]
    identifier = job["identifier"]

    if kind == "invite":
        info = await client(CheckChatInviteRequest(identifier))
        existing = getattr(info, "chat", None)  # set when already a member / peek
        if existing is not None:
            if _is_broadcast(existing) and not include_channels:
                return "skipped", "broadcast channel"
            return "joined", str(utils.get_peer_id(existing))
        # Not yet a member — `info` is a ChatInvite preview carrying the flags.
        if _is_broadcast(info) and not include_channels:
            return "skipped", "broadcast channel"
        updates = await client(ImportChatInviteRequest(identifier))
        return "joined", str(utils.get_peer_id(updates.chats[0]))

    # public: resolving the username does not join, so we can inspect type first.
    entity = await client.get_entity(identifier)
    if _is_broadcast(entity) and not include_channels:
        return "skipped", "broadcast channel"
    await client(JoinChannelRequest(identifier))
    return "joined", identifier


async def _process_one_join(instance_id: int) -> None:
    """Attempt the next pending join for an instance, honoring pacing and cap."""
    if instance_id in _joins_paused:
        return
    now = time.monotonic()
    if now < _next_join_at.get(instance_id, 0):
        return
    if await count_joins_today(instance_id) >= DAILY_JOIN_CAP:
        return

    client = _clients.get(instance_id)
    if client is None or not client.is_connected() or not await client.is_user_authorized():
        return

    job = await get_next_pending_join(instance_id)
    if job is None:
        return

    inst = await get_instance(instance_id)
    include_channels = bool(inst.get("include_channels", False)) if inst else False

    _schedule_next_join(instance_id, now)
    try:
        outcome, value = await _classify_and_join(client, job, include_channels)
        if outcome == "skipped":
            await update_join_status(job["id"], "skipped", value)
            # No actual join occurred — only a light resolve — so don't burn a full
            # 60-150s slot; a list full of channels would otherwise take hours.
            _next_join_at[instance_id] = now + random.uniform(5, 15)
            logger.info("Instance %s skipped %s (%s).",
                        instance_id, job["identifier"], value)
        else:
            await _add_channel_to_instance(instance_id, value)
            await update_join_status(job["id"], "joined", value)
            logger.info("Instance %s joined %s (stored as %s).",
                        instance_id, job["identifier"], value)
    except errors.FloodWaitError as e:
        # Back off for at least the duration Telegram demands; leave job pending.
        _next_join_at[instance_id] = now + e.seconds
        logger.warning("Instance %s hit FloodWait (%ss) joining %s — backing off.",
                       instance_id, e.seconds, job["identifier"])
    except Exception as e:
        await update_join_status(job["id"], "failed", str(e)[:300])
        logger.warning("Instance %s failed to join %s: %s",
                       instance_id, job["identifier"], e)


async def _join_worker_loop():
    """Single background loop that drains every instance's join queue, paced."""
    while True:
        try:
            for instance_id in await get_pending_join_instance_ids():
                try:
                    await _process_one_join(instance_id)
                except Exception as e:
                    logger.error("Join worker error for instance %s: %s", instance_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Join worker loop error: %s", e)
        await asyncio.sleep(_JOIN_TICK)


def start_join_worker() -> None:
    global _join_worker_task
    if _join_worker_task is None or _join_worker_task.done():
        _join_worker_task = asyncio.create_task(_join_worker_loop())


async def stop_join_worker() -> None:
    global _join_worker_task
    if _join_worker_task is not None and not _join_worker_task.done():
        _join_worker_task.cancel()
        try:
            await _join_worker_task
        except asyncio.CancelledError:
            pass
    _join_worker_task = None


# --- Message routing (per instance) ---

_word_pattern_cache: dict[str, "re.Pattern"] = {}


def _matches_whole_word(text_lower: str, term: str) -> bool:
    """True if `term` appears in `text_lower` as a whole word/phrase, i.e. not
    glued to surrounding letters or digits. Case-insensitive and Unicode-aware
    (works for Cyrillic), so "ремонт" matches "нужен ремонт" but not
    "авторемонт". Multi-word phrases are matched as-is.
    """
    term = (term or "").strip().lower()
    if not term:
        return False
    pattern = _word_pattern_cache.get(term)
    if pattern is None:
        # (?<!\w) / (?!\w) require a non-word char (or string edge) on each side.
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.UNICODE)
        _word_pattern_cache[term] = pattern
    return pattern.search(text_lower) is not None


def _channel_in_list(channels, chat_id: str, chat_username: str) -> bool:
    """True if this chat matches any entry in an instance's channel list."""
    for c in channels:
        c_str = str(c).strip().lstrip("@")
        if not c_str:
            continue
        if c_str == chat_id or (chat_username and c_str.lower() == chat_username.lower()):
            return True
    return False


async def process_message_for_instance(instance_id: int, event):
    """Handle one incoming message for a single instance's client."""
    inst = await get_instance(instance_id)
    if not inst:
        return

    chat = await event.get_chat()
    chat_id = str(event.chat_id)
    chat_username = getattr(chat, 'username', '') or ''

    if not _channel_in_list(inst.get("channels", []), chat_id, chat_username):
        return

    if instance_id in _paused_instances:
        return

    now = time.monotonic()
    flood_key = f"{instance_id}:{chat_id}"

    # --- Flood guard (per instance + channel) ---
    if now < _channel_flood_until.get(flood_key, 0):
        logger.debug("Flood guard active for %s — dropping message.", flood_key)
        return

    times = _channel_message_times[flood_key]
    times.append(now)
    recent = sum(1 for t in times if now - t < FLOOD_WINDOW)
    if recent >= FLOOD_THRESHOLD:
        _channel_flood_until[flood_key] = now + FLOOD_PAUSE
        logger.warning(
            "Flood guard triggered for %s (%d msgs in %ds). Pausing %ds.",
            flood_key, recent, FLOOD_WINDOW, FLOOD_PAUSE
        )
        return

    message_text = event.message.message or ""

    if chat_id.startswith("-100"):
        message_link = f"https://t.me/c/{chat_id[4:]}/{event.message.id}"
    elif getattr(chat, 'username', None):
        message_link = f"https://t.me/{chat.username}/{event.message.id}"
    else:
        message_link = "No link available"

    channel_name = getattr(chat, 'title', None) or getattr(chat, 'username', 'Unknown')

    await _dispatch_for_instance(inst, now, chat_id, channel_name, message_text, message_link, event)


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

    matched_keyword = next((kw for kw in keywords if _matches_whole_word(text_lower, kw)), None)
    if not matched_keyword:
        return

    # --- Exclusion filter ---
    # If any excluded word appears (as a whole word) in the message, suppress
    # the match entirely.
    excluded_hit = next(
        (ex for ex in excluded_keywords if _matches_whole_word(text_lower, ex)),
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
