import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")

if not API_ID or not API_HASH or not PHONE_NUMBER:
    logger.warning("API_ID, API_HASH, or PHONE_NUMBER not set in .env")

# Settings Database Path — resolved relative to this file, not cwd
DB_PATH = str(Path(__file__).parent / "database" / "settings.sqlite")

# Ensure database directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
