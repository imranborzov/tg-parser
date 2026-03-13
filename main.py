import logging
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
from contextlib import asynccontextmanager

BASE_DIR = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from src.database_manager import init_db, get_settings, update_settings, get_events
from src.telegram_client import (
    start_client_bg,
    send_code,
    verify_code,
    verify_2fa,
    is_authorized,
    stop_client,
    send_to_webhook,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database
    await init_db()
    # Try to start telegram client in background if already authorized
    await start_client_bg()
    try:
        yield
    finally:
        # Cleanup
        await stop_client()

app = FastAPI(lifespan=lifespan)

# Mount static files (CSS/JS)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "src" / "static")), name="static")

# Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "templates"))

class SetupData(BaseModel):
    channels: list[str]
    keywords: list[str]
    webhook_url: str
    tg_bot_token: str = ""
    tg_chat_id: str = ""

class AuthData(BaseModel):
    code: str
    phone_code_hash: str

class TwoFAData(BaseModel):
    password: str


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    authorized = await is_authorized()
    settings = await get_settings()
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "authorized": authorized,
            "settings": settings
        }
    )

@app.post("/api/auth/send_code")
async def api_send_code():
    try:
        phone_code_hash = await send_code()
        return {"status": "success", "phone_code_hash": phone_code_hash}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/auth/verify_code")
async def api_verify_code(data: AuthData):
    result = await verify_code(data.code, data.phone_code_hash)
    return result

@app.post("/api/auth/verify_2fa")
async def api_verify_2fa(data: TwoFAData):
    result = await verify_2fa(data.password)
    return result

@app.get("/api/events")
async def api_events():
    return await get_events()

@app.get("/api/status")
async def api_status():
    authorized = await is_authorized()
    return {"authorized": authorized}

@app.get("/api/settings")
async def api_get_settings():
    return await get_settings()

@app.post("/api/webhook/test")
async def api_test_webhook():
    settings = await get_settings()
    webhook_url = settings.get("webhook_url", "")
    if not webhook_url:
        return {"status": "error", "message": "No webhook URL configured."}
    sample = {
        "channel_id": "-1001234567890",
        "channel_name": "Test Channel",
        "message_id": 1,
        "message_text": "This is a test message from TG Parser.",
        "message_link": "https://t.me/c/1234567890/1",
        "matched_keyword": "test",
        "date": "2024-01-01T00:00:00+00:00",
        "sender_id": None,
    }
    await send_to_webhook(webhook_url, sample)
    return {"status": "success"}

@app.post("/api/settings")
async def api_update_settings(data: SetupData):
    await update_settings(data.channels, data.keywords, data.webhook_url, data.tg_bot_token, data.tg_chat_id)
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
