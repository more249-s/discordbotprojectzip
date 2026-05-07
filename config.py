import os
from dotenv import load_dotenv

load_dotenv()

def get_int(key, default=0):
    val = os.getenv(key)
    if not val or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    
    # Google Drive
    GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    GOFILE_TOKEN = os.getenv("GOFILE_TOKEN")
    
    GEMINI_CHANNEL_ID = get_int("DISCORD_GEMINI_CHANNEL_ID")
    GUILD_ID = get_int("DISCORD_GUILD_ID")
    ERROR_CHANNEL_ID = get_int("DISCORD_ERROR_CHANNEL_ID")
    
    ALLOWED_USER_IDS = [int(uid.strip()) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip() and uid.strip().isdigit()]

    @classmethod
    def is_allowed(cls, user_id):
        return user_id in cls.ALLOWED_USER_IDS
