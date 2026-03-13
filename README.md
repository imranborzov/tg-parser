# TG Parser

A self-hosted Telegram channel monitor. Watch any number of channels for keywords and forward matching messages to a webhook or Telegram bot — in real time.

Built with Python, FastAPI, and Telethon.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

---

## Features

- **Keyword monitoring** — watch multiple Telegram channels for any set of keywords
- **Webhook delivery** — POST matching messages as JSON to any URL (n8n, Make, Zapier, your own server)
- **Telegram bot forwarding** — send matches directly to a Telegram chat via a bot
- **Activity log** — live feed of recent matches in the UI
- **Web UI** — configure everything from a browser, no code required
- **Self-hosted** — your credentials never leave your server

---

## Requirements

- Python 3.10+
- A Telegram account
- Telegram API credentials (free — see setup below)

---

## Setup

### 1. Get Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in
2. Click **API development tools**
3. Create an app — name and description can be anything
4. Copy your **App api_id** and **App api_hash**

### 2. Clone and configure

```bash
git clone https://github.com/your-username/tg-parser.git
cd tg-parser
cp .env.example .env
```

Open `.env` and fill in your values:

```env
API_ID=your_api_id
API_HASH=your_api_hash
PHONE_NUMBER=+1234567890
```

### 3. Run

**Linux / macOS:**
```bash
./start.sh
```

**Windows:**
```bat
start.bat
```

**Or manually:**
```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

---

## Usage

### 1. Authenticate

On first launch, click **Request Login Code**. Enter the code sent to your Telegram app. If you have 2FA enabled, enter your cloud password when prompted.

Your session is saved locally and reused on subsequent startups — you only need to do this once.

### 2. Configure

| Field | Description |
|---|---|
| **Webhook URL** | Any HTTP endpoint that accepts POST JSON |
| **Telegram Bot Token** | From [@BotFather](https://t.me/BotFather) — optional |
| **Telegram Chat ID** | Where the bot should forward matches |
| **Target Channels** | Channel usernames (without `@`) or numeric IDs |
| **Keywords** | Words to watch for — case-insensitive |

Click **Save Settings** when done.

### 3. Getting a channel ID

For public channels, the username works (e.g. `durov`).

For private channels or groups, forward any message from the chat to [@userinfobot](https://t.me/userinfobot) — it will reply with the numeric ID.

### 4. Webhook payload

When a keyword is matched, a POST request is sent with this JSON body:

```json
{
  "channel_id": "-1001234567890",
  "channel_name": "Channel Name",
  "message_id": 123,
  "message_text": "Full message text...",
  "message_link": "https://t.me/c/1234567890/123",
  "matched_keyword": "keyword",
  "date": "2024-01-01T12:00:00+00:00",
  "sender_id": "987654321"
}
```

---

## Project Structure

```
tg-parser/
├── main.py                  # FastAPI app, routes
├── requirements.txt
├── start.sh / start.bat     # Quick-start scripts
├── .env.example             # Copy to .env and fill in your credentials
└── src/
    ├── config.py            # Loads .env variables
    ├── database_manager.py  # SQLite via aiosqlite
    ├── telegram_client.py   # Telethon client, message handler
    ├── static/
    │   ├── app.js
    │   └── index.css
    └── templates/
        └── index.html
```

---

## License

MIT — see [LICENSE](LICENSE).
