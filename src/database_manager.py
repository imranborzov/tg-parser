import json
import aiosqlite
from src.config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY DEFAULT 1,
                channels TEXT DEFAULT '[]',
                keywords TEXT DEFAULT '[]',
                webhook_url TEXT DEFAULT '',
                tg_bot_token TEXT DEFAULT '',
                tg_chat_id TEXT DEFAULT ''
            )
        ''')

        # Add columns introduced after initial schema (idempotent)
        for column in ("tg_bot_token", "tg_chat_id"):
            try:
                await conn.execute(f"ALTER TABLE settings ADD COLUMN {column} TEXT DEFAULT ''")
            except aiosqlite.OperationalError:
                pass  # Column already exists

        try:
            await conn.execute("ALTER TABLE settings ADD COLUMN match_cooldown INTEGER DEFAULT 60")
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Ensure the single settings row exists
        async with conn.execute('SELECT COUNT(*) FROM settings') as cursor:
            (count,) = await cursor.fetchone()
        if count == 0:
            await conn.execute('''
                INSERT INTO settings (id, channels, keywords, webhook_url, tg_bot_token, tg_chat_id)
                VALUES (1, '[]', '[]', '', '', '')
            ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                channel_name TEXT,
                keyword TEXT,
                message_text TEXT,
                message_link TEXT,
                matched_at TEXT
            )
        ''')

        await conn.commit()

async def get_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            'SELECT channels, keywords, webhook_url, tg_bot_token, tg_chat_id, match_cooldown FROM settings WHERE id = 1'
        ) as cursor:
            row = await cursor.fetchone()

    if row:
        return {
            "channels": json.loads(row[0]),
            "keywords": json.loads(row[1]),
            "webhook_url": row[2],
            "tg_bot_token": row[3] or "",
            "tg_chat_id": row[4] or "",
            "match_cooldown": row[5] if row[5] is not None else 60,
        }
    return {"channels": [], "keywords": [], "webhook_url": "", "tg_bot_token": "", "tg_chat_id": "", "match_cooldown": 60}

async def insert_event(channel_id: str, channel_name: str, keyword: str, message_text: str, message_link: str, matched_at: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            INSERT INTO events (channel_id, channel_name, keyword, message_text, message_link, matched_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (channel_id, channel_name, keyword, message_text, message_link, matched_at))
        # Keep only the latest 200 events
        await conn.execute('''
            DELETE FROM events WHERE id NOT IN (
                SELECT id FROM events ORDER BY id DESC LIMIT 200
            )
        ''')
        await conn.commit()

async def get_events(limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            'SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]

async def update_settings(channels, keywords, webhook_url, tg_bot_token="", tg_chat_id="", match_cooldown=60):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            UPDATE settings
            SET channels = ?, keywords = ?, webhook_url = ?, tg_bot_token = ?, tg_chat_id = ?, match_cooldown = ?
            WHERE id = 1
        ''', (json.dumps(channels), json.dumps(keywords), webhook_url, tg_bot_token, tg_chat_id, match_cooldown))
        await conn.commit()
