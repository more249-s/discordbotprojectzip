import aiosqlite
import json
import os
import datetime

DB_PATH = "data/bot_database.db"


async def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER,
                role      TEXT,
                content   TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
                tracker_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id         INTEGER,
                channel_id       INTEGER,
                url              TEXT,
                last_chapter     REAL,
                custom_msg       TEXT,
                interval_hours   INTEGER,
                last_checked     TEXT,
                download_enabled INTEGER DEFAULT 0,
                title            TEXT DEFAULT ''
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions (
                user_id  INTEGER PRIMARY KEY,
                rank     INTEGER DEFAULT 1,
                note     TEXT    DEFAULT '',
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_sites (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                domain     TEXT UNIQUE,
                site_type  TEXT DEFAULT 'madara',
                added_by   INTEGER,
                added_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                notes      TEXT DEFAULT ''
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stitch_jobs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                title      TEXT,
                status     TEXT DEFAULT 'pending',
                result_url TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                level     TEXT DEFAULT 'INFO',
                message   TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # Migrations
        migrations = [
            "ALTER TABLE trackers ADD COLUMN download_enabled INTEGER DEFAULT 0",
            "ALTER TABLE trackers ADD COLUMN title TEXT DEFAULT ''",
        ]
        for sql in migrations:
            try:
                await db.execute(sql)
                await db.commit()
            except Exception:
                pass


# ── Bot Logs ──────────────────────────────────────────────────────────────
async def log_event(level: str, message: str):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO bot_logs (level, message) VALUES (?, ?)",
                (level, message[:1000])
            )
            # Keep only last 500 logs
            await db.execute(
                "DELETE FROM bot_logs WHERE id NOT IN (SELECT id FROM bot_logs ORDER BY id DESC LIMIT 500)"
            )
            await db.commit()
    except Exception:
        pass


async def get_recent_logs(limit: int = 100):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT level, message, timestamp FROM bot_logs ORDER BY id DESC LIMIT ?",
            (limit,)
        ) as cursor:
            return await cursor.fetchall()


# ── Chat ──────────────────────────────────────────────────────────────────
async def add_chat_message(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        # Keep last 30 messages per user
        await db.execute(
            "DELETE FROM chat_history WHERE user_id = ? AND id NOT IN "
            "(SELECT id FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 30)",
            (user_id, user_id)
        )
        await db.commit()


async def get_chat_history(user_id, limit=15):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row[0], "parts": [row[1]]} for row in reversed(rows)]


async def clear_chat_history(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await db.commit()


# ── Trackers ──────────────────────────────────────────────────────────────
async def add_tracker(guild_id, channel_id, url, custom_msg, interval_hours,
                      current_chapter, download_enabled=0, title=""):
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO trackers (guild_id, channel_id, url, last_chapter, custom_msg, "
            "interval_hours, last_checked, download_enabled, title) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, url, current_chapter, custom_msg,
             interval_hours, now_str, download_enabled, title)
        )
        await db.commit()


async def get_all_trackers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tracker_id, guild_id, channel_id, url, last_chapter, "
            "custom_msg, interval_hours, last_checked, download_enabled FROM trackers"
        ) as cursor:
            return await cursor.fetchall()


async def remove_tracker(tracker_id, guild_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM trackers WHERE tracker_id = ? AND guild_id = ?",
            (tracker_id, guild_id)
        ) as cursor:
            if await cursor.fetchone() is None:
                return False
        await db.execute(
            "DELETE FROM trackers WHERE tracker_id = ? AND guild_id = ?",
            (tracker_id, guild_id)
        )
        await db.commit()
        return True


async def update_tracker_time(tracker_id, last_checked_str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE trackers SET last_checked = ? WHERE tracker_id = ?",
            (last_checked_str, tracker_id)
        )
        await db.commit()


async def update_tracker_chapter(tracker_id, new_chapter, last_checked_str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE trackers SET last_chapter = ?, last_checked = ? WHERE tracker_id = ?",
            (new_chapter, last_checked_str, tracker_id)
        )
        await db.commit()


async def get_tracker_count():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM trackers") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ── Custom Sites ───────────────────────────────────────────────────────────
async def add_custom_site(domain: str, site_type: str, added_by: int, notes: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO custom_sites (domain, site_type, added_by, notes) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(domain) DO UPDATE SET site_type=excluded.site_type, notes=excluded.notes",
            (domain.lower().strip(), site_type, added_by, notes)
        )
        await db.commit()


async def get_custom_sites():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT domain, site_type, added_by, added_at, notes FROM custom_sites ORDER BY added_at DESC"
        ) as cursor:
            return await cursor.fetchall()


async def remove_custom_site(domain: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM custom_sites WHERE domain = ?", (domain.lower().strip(),))
        await db.commit()


async def get_custom_madara_sites() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT domain FROM custom_sites WHERE site_type = 'madara'"
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


async def get_custom_arabic_sites() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT domain FROM custom_sites WHERE site_type = 'arabic'"
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


# ── Stitch Jobs ────────────────────────────────────────────────────────────
async def create_stitch_job(user_id: int, title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "INSERT INTO stitch_jobs (user_id, title, status) VALUES (?, ?, 'pending')",
            (user_id, title)
        ) as cursor:
            await db.commit()
            return cursor.lastrowid


async def update_stitch_job(job_id: int, status: str, result_url: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await db.execute(
            "UPDATE stitch_jobs SET status=?, result_url=?, updated_at=? WHERE id=?",
            (status, result_url, now, job_id)
        )
        await db.commit()


# ── User Permissions ──────────────────────────────────────────────────────
async def get_user_rank(user_id: int, auto_register: bool = False) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT rank FROM user_permissions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            if auto_register:
                await db.execute(
                    "INSERT OR IGNORE INTO user_permissions (user_id, rank, note) VALUES (?, ?, ?)",
                    (user_id, 1, "Auto-registered")
                )
                await db.commit()
                return 1
            return 0


async def set_user_rank(user_id: int, rank: int, note: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_permissions (user_id, rank, note) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET rank=excluded.rank, note=excluded.note",
            (user_id, rank, note)
        )
        await db.commit()


async def remove_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_all_users() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, rank, note, added_at FROM user_permissions ORDER BY rank DESC"
        ) as cursor:
            return await cursor.fetchall()


async def get_user_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM user_permissions") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
