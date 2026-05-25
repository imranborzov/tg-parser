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
    logger.info(
        "No API_ID/API_HASH/PHONE_NUMBER in .env — set credentials per instance "
        "in the web UI."
    )

# Data directory — holds the settings DB and per-instance session files.
# Defaults next to this file; override with TG_DATA_DIR (handy for tests or
# relocating state).
DATA_DIR = Path(os.getenv("TG_DATA_DIR") or (Path(__file__).parent / "database"))
os.makedirs(DATA_DIR, exist_ok=True)

# Settings Database Path
DB_PATH = str(DATA_DIR / "settings.sqlite")
