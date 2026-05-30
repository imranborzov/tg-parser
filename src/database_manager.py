import json
from datetime import datetime, timezone
import aiosqlite
from src.config import DB_PATH, API_ID, API_HASH, PHONE_NUMBER

DEFAULT_INSTANCE_NAME = "Default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        # --- instances: one row per isolated monitor ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                channels TEXT DEFAULT '[]',
                keywords TEXT DEFAULT '[]',
                webhook_url TEXT DEFAULT '',
                tg_bot_token TEXT DEFAULT '',
                tg_chat_id TEXT DEFAULT '',
                match_cooldown INTEGER DEFAULT 60,
                excluded_keywords TEXT DEFAULT '[]',
                api_id TEXT DEFAULT '',
                api_hash TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                include_channels INTEGER DEFAULT 0,
                created_at TEXT
            )
        ''')

        # Add columns introduced after the initial instances schema (idempotent)
        for ddl in (
            "ALTER TABLE instances ADD COLUMN excluded_keywords TEXT DEFAULT '[]'",
            "ALTER TABLE instances ADD COLUMN api_id TEXT DEFAULT ''",
            "ALTER TABLE instances ADD COLUMN api_hash TEXT DEFAULT ''",
            "ALTER TABLE instances ADD COLUMN phone TEXT DEFAULT ''",
            "ALTER TABLE instances ADD COLUMN include_channels INTEGER DEFAULT 0",
        ):
            try:
                await conn.execute(ddl)
            except aiosqlite.OperationalError:
                pass  # Column already exists

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                keyword TEXT,
                message_text TEXT,
                message_link TEXT,
                matched_at TEXT,
                sender_id TEXT,
                sender_username TEXT,
                sender_name TEXT
            )
        ''')

        # Add columns introduced after the initial events schema (idempotent)
        for ddl in (
            "ALTER TABLE events ADD COLUMN instance_id INTEGER",
            "ALTER TABLE events ADD COLUMN sender_id TEXT",
            "ALTER TABLE events ADD COLUMN sender_username TEXT",
            "ALTER TABLE events ADD COLUMN sender_name TEXT",
        ):
            try:
                await conn.execute(ddl)
            except aiosqlite.OperationalError:
                pass  # Column already exists

        # --- join_queue: pending/in-progress channel joins from bulk uploads ---
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS join_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id INTEGER NOT NULL,
                raw_link TEXT,
                kind TEXT,            -- 'public' | 'invite'
                identifier TEXT,      -- username (public) or invite hash (private)
                status TEXT DEFAULT 'pending',  -- pending | joined | failed
                result TEXT DEFAULT '',         -- stored channel value, or error message
                created_at TEXT,
                updated_at TEXT
            )
        ''')

        await conn.commit()

        # --- One-time migration from the old single-row settings table ---
        await _migrate_legacy_settings(conn)

        # Ensure at least one instance exists
        async with conn.execute('SELECT COUNT(*) FROM instances') as cursor:
            (count,) = await cursor.fetchone()
        if count == 0:
            await conn.execute(
                'INSERT INTO instances (name, api_id, api_hash, phone, created_at) VALUES (?, ?, ?, ?, ?)',
                (DEFAULT_INSTANCE_NAME, API_ID or '', API_HASH or '', PHONE_NUMBER or '', _now_iso()),
            )
            await conn.commit()

        # Backfill the legacy account (.env creds) onto the original instance so
        # upgrades keep working with the existing session. Only touches the oldest
        # instance, and only if it has no creds yet.
        await _backfill_default_credentials(conn)


async def _backfill_default_credentials(conn):
    if not (API_ID and API_HASH and PHONE_NUMBER):
        return
    async with conn.execute(
        'SELECT id, api_id, phone FROM instances ORDER BY id ASC LIMIT 1'
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    inst_id, api_id, phone = row
    if (api_id or '').strip() or (phone or '').strip():
        return  # Already has credentials — leave it alone
    await conn.execute(
        'UPDATE instances SET api_id = ?, api_hash = ?, phone = ? WHERE id = ?',
        (API_ID, API_HASH, PHONE_NUMBER, inst_id),
    )
    await conn.commit()


async def _migrate_legacy_settings(conn):
    """If an old `settings` table with a row exists and no instances do yet,
    copy it into a Default instance and attach orphaned events to it."""
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
    ) as cursor:
        if await cursor.fetchone() is None:
            return  # Nothing to migrate

    async with conn.execute('SELECT COUNT(*) FROM instances') as cursor:
        (instance_count,) = await cursor.fetchone()
    if instance_count > 0:
        return  # Already migrated

    # Read the legacy row (columns may vary; select defensively)
    try:
        async with conn.execute(
            'SELECT channels, keywords, webhook_url, tg_bot_token, tg_chat_id, match_cooldown '
            'FROM settings WHERE id = 1'
        ) as cursor:
            row = await cursor.fetchone()
    except aiosqlite.OperationalError:
        row = None

    if row is None:
        return

    cur = await conn.execute(
        '''INSERT INTO instances
           (name, channels, keywords, webhook_url, tg_bot_token, tg_chat_id, match_cooldown,
            api_id, api_hash, phone, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            DEFAULT_INSTANCE_NAME,
            row[0] or '[]',
            row[1] or '[]',
            row[2] or '',
            row[3] or '',
            row[4] or '',
            row[5] if row[5] is not None else 60,
            API_ID or '',
            API_HASH or '',
            PHONE_NUMBER or '',
            _now_iso(),
        ),
    )
    new_id = cur.lastrowid
    # Attach any pre-existing events to the migrated instance
    await conn.execute(
        'UPDATE events SET instance_id = ? WHERE instance_id IS NULL', (new_id,)
    )
    await conn.commit()


def _instance_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "channels": json.loads(row[2]) if row[2] else [],
        "keywords": json.loads(row[3]) if row[3] else [],
        "webhook_url": row[4] or "",
        "tg_bot_token": row[5] or "",
        "tg_chat_id": row[6] or "",
        "match_cooldown": row[7] if row[7] is not None else 60,
        "excluded_keywords": json.loads(row[8]) if len(row) > 8 and row[8] else [],
        "api_id": (row[9] or "") if len(row) > 9 else "",
        "api_hash": (row[10] or "") if len(row) > 10 else "",
        "phone": (row[11] or "") if len(row) > 11 else "",
        "include_channels": bool(row[12]) if len(row) > 12 and row[12] else False,
    }


async def list_instances() -> list:
    """Return all instances (lightweight: id + name), ordered oldest-first."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT id, name FROM instances ORDER BY id ASC'
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


async def get_instance(instance_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT id, name, channels, keywords, webhook_url, tg_bot_token, '
            'tg_chat_id, match_cooldown, excluded_keywords, api_id, api_hash, phone, '
            'include_channels '
            'FROM instances WHERE id = ?',
            (instance_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return _instance_row_to_dict(row) if row else None


async def get_all_instances_full() -> list:
    """Return every instance with full config — used by the message router."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT id, name, channels, keywords, webhook_url, tg_bot_token, '
            'tg_chat_id, match_cooldown, excluded_keywords, api_id, api_hash, phone, '
            'include_channels '
            'FROM instances ORDER BY id ASC'
        ) as cursor:
            rows = await cursor.fetchall()
    return [_instance_row_to_dict(r) for r in rows]


async def create_instance(name: str) -> dict:
    name = (name or "").strip() or "Untitled"
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            'INSERT INTO instances (name, created_at) VALUES (?, ?)',
            (name, _now_iso()),
        )
        await conn.commit()
        new_id = cur.lastrowid
    return {"id": new_id, "name": name}


async def update_instance(instance_id: int, *, name=None, channels=None, keywords=None,
                          webhook_url=None, tg_bot_token=None, tg_chat_id=None,
                          match_cooldown=None, excluded_keywords=None,
                          api_id=None, api_hash=None, phone=None,
                          include_channels=None):
    """Update only the provided fields of an instance."""
    fields = []
    values = []
    if name is not None:
        fields.append('name = ?'); values.append(name.strip() or "Untitled")
    if api_id is not None:
        fields.append('api_id = ?'); values.append(str(api_id).strip())
    if api_hash is not None:
        fields.append('api_hash = ?'); values.append(str(api_hash).strip())
    if phone is not None:
        fields.append('phone = ?'); values.append(str(phone).strip())
    if channels is not None:
        fields.append('channels = ?'); values.append(json.dumps(channels))
    if keywords is not None:
        fields.append('keywords = ?'); values.append(json.dumps(keywords))
    if webhook_url is not None:
        fields.append('webhook_url = ?'); values.append(webhook_url)
    if tg_bot_token is not None:
        fields.append('tg_bot_token = ?'); values.append(tg_bot_token)
    if tg_chat_id is not None:
        fields.append('tg_chat_id = ?'); values.append(tg_chat_id)
    if match_cooldown is not None:
        fields.append('match_cooldown = ?'); values.append(match_cooldown)
    if excluded_keywords is not None:
        fields.append('excluded_keywords = ?'); values.append(json.dumps(excluded_keywords))
    if include_channels is not None:
        fields.append('include_channels = ?'); values.append(1 if include_channels else 0)

    if not fields:
        return
    values.append(instance_id)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            f'UPDATE instances SET {", ".join(fields)} WHERE id = ?', values
        )
        await conn.commit()


async def delete_instance(instance_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('DELETE FROM events WHERE instance_id = ?', (instance_id,))
        await conn.execute('DELETE FROM instances WHERE id = ?', (instance_id,))
        await conn.commit()


async def count_instances() -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute('SELECT COUNT(*) FROM instances') as cursor:
            (count,) = await cursor.fetchone()
    return count


async def insert_event(instance_id: int, channel_id: str, channel_name: str, keyword: str,
                       message_text: str, message_link: str, matched_at: str,
                       sender_id: str = None, sender_username: str = None,
                       sender_name: str = None):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            INSERT INTO events (instance_id, channel_id, channel_name, keyword, message_text,
                                message_link, matched_at, sender_id, sender_username, sender_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (instance_id, channel_id, channel_name, keyword, message_text, message_link,
              matched_at, sender_id, sender_username, sender_name))
        # Keep only the latest 200 events per instance
        await conn.execute('''
            DELETE FROM events WHERE instance_id = ? AND id NOT IN (
                SELECT id FROM events WHERE instance_id = ? ORDER BY id DESC LIMIT 200
            )
        ''', (instance_id, instance_id))
        await conn.commit()


async def get_events(instance_id: int, limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            'SELECT * FROM events WHERE instance_id = ? ORDER BY id DESC LIMIT ?',
            (instance_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# --- Join queue (bulk channel uploads) ---

async def enqueue_joins(instance_id: int, items: list[dict]) -> int:
    """Insert (instance_id, kind, identifier, raw_link) rows as pending.
    Skips identifiers already present for this instance in a pending/joined state
    so re-uploading a file doesn't duplicate work. Returns the count inserted."""
    if not items:
        return 0
    now = _now_iso()
    inserted = 0
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT identifier FROM join_queue "
            "WHERE instance_id = ? AND status IN ('pending', 'joined')",
            (instance_id,),
        ) as cursor:
            existing = {r[0] for r in await cursor.fetchall()}
        for it in items:
            ident = it["identifier"]
            if ident in existing:
                continue
            existing.add(ident)
            await conn.execute(
                'INSERT INTO join_queue (instance_id, raw_link, kind, identifier, '
                'status, result, created_at, updated_at) '
                "VALUES (?, ?, ?, ?, 'pending', '', ?, ?)",
                (instance_id, it.get("raw_link", ""), it["kind"], ident, now, now),
            )
            inserted += 1
        await conn.commit()
    return inserted


async def get_join_queue(instance_id: int, limit: int = 500) -> list:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            'SELECT * FROM join_queue WHERE instance_id = ? ORDER BY id ASC LIMIT ?',
            (instance_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_join_queue_summary(instance_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT status, COUNT(*) FROM join_queue WHERE instance_id = ? GROUP BY status',
            (instance_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    summary = {"pending": 0, "joined": 0, "failed": 0, "skipped": 0}
    for status, count in rows:
        summary[status] = count
    return summary


async def get_pending_join_instance_ids() -> list[int]:
    """Instance ids that still have at least one pending join."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT DISTINCT instance_id FROM join_queue WHERE status = 'pending'"
        ) as cursor:
            rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_next_pending_join(instance_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM join_queue WHERE instance_id = ? AND status = 'pending' "
            'ORDER BY id ASC LIMIT 1',
            (instance_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def update_join_status(job_id: int, status: str, result: str = ''):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'UPDATE join_queue SET status = ?, result = ?, updated_at = ? WHERE id = ?',
            (status, result, _now_iso(), job_id),
        )
        await conn.commit()


async def count_joins_today(instance_id: int) -> int:
    """How many joins succeeded for this instance since UTC midnight — used to
    enforce a daily cap that keeps the account under Telegram's radar."""
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM join_queue "
            "WHERE instance_id = ? AND status = 'joined' AND updated_at >= ?",
            (instance_id, midnight),
        ) as cursor:
            (count,) = await cursor.fetchone()
    return count


async def clear_finished_joins(instance_id: int) -> int:
    """Remove finished rows (joined/failed/skipped) for an instance; keep pending."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "DELETE FROM join_queue WHERE instance_id = ? "
            "AND status IN ('joined', 'failed', 'skipped')",
            (instance_id,),
        )
        await conn.commit()
        return cur.rowcount
