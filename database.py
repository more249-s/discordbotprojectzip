import aiosqlite
import json
import os

DB_PATH = "data/bot_database.db"

async def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Chat history table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Binance transactions table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS binance_transactions (
                tx_id TEXT PRIMARY KEY,
                amount TEXT,
                asset TEXT,
                timestamp TEXT,
                type TEXT
            )
        """)
        
        # Radar trackers table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
                tracker_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                url TEXT,
                last_chapter REAL,
                custom_msg TEXT,
                interval_hours INTEGER,
                last_checked TEXT,
                download_enabled INTEGER DEFAULT 0
            )
        """)
        
        # Price Alerts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                target_price REAL,
                condition TEXT, -- 'above' or 'below'
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.commit()
        
        # Migrations
        try:
            await db.execute("ALTER TABLE trackers ADD COLUMN download_enabled INTEGER DEFAULT 0")
            await db.commit()
        except:
            pass

async def add_chat_message(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()

async def get_chat_history(user_id, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            # Return in chronological order
            return [{"role": row[0], "parts": [row[1]]} for row in reversed(rows)]

async def is_transaction_new(tx_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM binance_transactions WHERE tx_id = ?", (tx_id,)) as cursor:
            return await cursor.fetchone() is None

async def save_transaction(tx_id, amount, asset, timestamp, tx_type):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO binance_transactions (tx_id, amount, asset, timestamp, type) VALUES (?, ?, ?, ?, ?)",
            (tx_id, amount, asset, timestamp, tx_type)
        )
        await db.commit()

async def add_tracker(guild_id, channel_id, url, custom_msg, interval_hours, current_chapter, download_enabled=0):
    import datetime
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO trackers (guild_id, channel_id, url, last_chapter, custom_msg, interval_hours, last_checked, download_enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, url, current_chapter, custom_msg, interval_hours, now_str, download_enabled)
        )
        await db.commit()

async def get_all_trackers():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tracker_id, guild_id, channel_id, url, last_chapter, custom_msg, interval_hours, last_checked, download_enabled FROM trackers") as cursor:
            return await cursor.fetchall()

async def remove_tracker(tracker_id, guild_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM trackers WHERE tracker_id = ? AND guild_id = ?", (tracker_id, guild_id)) as cursor:
            if await cursor.fetchone() is None:
                return False
        await db.execute("DELETE FROM trackers WHERE tracker_id = ? AND guild_id = ?", (tracker_id, guild_id))
        await db.commit()
        return True

async def update_tracker_time(tracker_id, last_checked_str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE trackers SET last_checked = ? WHERE tracker_id = ?", (last_checked_str, tracker_id))
        await db.commit()

async def update_tracker_chapter(tracker_id, new_chapter, last_checked_str):
    """تحديث رقم الفصل الأخير ووقت الفحص معاً"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE trackers SET last_chapter = ?, last_checked = ? WHERE tracker_id = ?",
            (new_chapter, last_checked_str, tracker_id)
        )
        await db.commit()

async def add_price_alert(user_id, symbol, target_price, condition):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO price_alerts (user_id, symbol, target_price, condition) VALUES (?, ?, ?, ?)",
            (user_id, symbol.upper(), target_price, condition)
        )
        await db.commit()

async def get_active_alerts():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT alert_id, user_id, symbol, target_price, condition FROM price_alerts WHERE is_active = 1") as cursor:
            return await cursor.fetchall()

async def deactivate_alert(alert_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE price_alerts SET is_active = 0 WHERE alert_id = ?", (alert_id,))
        await db.commit()

async def get_user_alerts(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT alert_id, symbol, target_price, condition FROM price_alerts WHERE user_id = ? AND is_active = 1", (user_id,)) as cursor:
            return await cursor.fetchall()

async def remove_alert(alert_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM price_alerts WHERE alert_id = ? AND user_id = ?", (alert_id, user_id))
        await db.commit()


