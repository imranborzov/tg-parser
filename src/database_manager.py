import json
from datetime import datetime, timezone
import aiosqlite
from src.config import DB_PATH

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
                created_at TEXT
            )
        ''')

        # Add columns introduced after the initial instances schema (idempotent)
        try:
            await conn.execute("ALTER TABLE instances ADD COLUMN excluded_keywords TEXT DEFAULT '[]'")
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
                matched_at TEXT
            )
        ''')

        # Add instance_id to events if upgrading from an older schema (idempotent)
        try:
            await conn.execute("ALTER TABLE events ADD COLUMN instance_id INTEGER")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        await conn.commit()

        # --- One-time migration from the old single-row settings table ---
        await _migrate_legacy_settings(conn)

        # Ensure at least one instance exists
        async with conn.execute('SELECT COUNT(*) FROM instances') as cursor:
            (count,) = await cursor.fetchone()
        if count == 0:
            await conn.execute(
                'INSERT INTO instances (name, created_at) VALUES (?, ?)',
                (DEFAULT_INSTANCE_NAME, _now_iso()),
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
           (name, channels, keywords, webhook_url, tg_bot_token, tg_chat_id, match_cooldown, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            DEFAULT_INSTANCE_NAME,
            row[0] or '[]',
            row[1] or '[]',
            row[2] or '',
            row[3] or '',
            row[4] or '',
            row[5] if row[5] is not None else 60,
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
            'tg_chat_id, match_cooldown, excluded_keywords FROM instances WHERE id = ?',
            (instance_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return _instance_row_to_dict(row) if row else None


async def get_all_instances_full() -> list:
    """Return every instance with full config — used by the message router."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT id, name, channels, keywords, webhook_url, tg_bot_token, '
            'tg_chat_id, match_cooldown, excluded_keywords FROM instances ORDER BY id ASC'
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
                          match_cooldown=None, excluded_keywords=None):
    """Update only the provided fields of an instance."""
    fields = []
    values = []
    if name is not None:
        fields.append('name = ?'); values.append(name.strip() or "Untitled")
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
                       message_text: str, message_link: str, matched_at: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            INSERT INTO events (instance_id, channel_id, channel_name, keyword, message_text, message_link, matched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (instance_id, channel_id, channel_name, keyword, message_text, message_link, matched_at))
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
