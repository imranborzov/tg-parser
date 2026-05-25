# TG Parser

A self-hosted Telegram channel monitor. Watch any number of channels for keywords and forward matching messages to a webhook or Telegram bot — in real time.

Built with Python, FastAPI, and Telethon.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue.svg)

---

## Features

- **Multiple instances** — run several independent monitors from one dashboard, each with its own channels, keywords, destination, and activity log
- **Per-instance Telegram accounts** — every instance logs into its own Telegram account (its own `api_id`/`api_hash`/`phone`), so you can monitor from different accounts side by side
- **Whole-word keyword matching** — case-insensitive, Unicode-aware; `ремонт` matches `нужен ремонт` but not `авторемонт`. Multi-word phrases supported
- **Excluded words** — suppress a match when an unwanted word is present (e.g. keyword `rent` + excluded `car` ignores "rent a car")
- **Webhook delivery** — POST matching messages as JSON to any URL (n8n, Make, Zapier, your own server)
- **Telegram bot forwarding** — send matches directly to a Telegram chat via a bot
- **Activity log** — live, per-instance feed of recent matches in the UI
- **Web UI** — configure everything from a browser, no code required
- **Self-hosted** — your credentials never leave your server

---

## Requirements

- Python 3.9+
- One or more Telegram accounts
- Telegram API credentials for each account (free — see setup below)

---

## Setup

### 1. Get Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in
2. Click **API development tools**
3. Create an app — name and description can be anything
4. Copy your **App api_id** and **App api_hash**

You enter these credentials per instance in the web UI (step 3 below). Each instance can use a different account.

### 2. Clone and run

```bash
git clone https://github.com/your-username/tg-parser.git
cd tg-parser
```

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

> **`.env` is optional.** If you create a `.env` (`cp .env.example .env`) with `API_ID`/`API_HASH`/`PHONE_NUMBER`, those values seed the credentials of the **first** instance for convenience. Otherwise, just enter credentials for each instance in the UI.

---

## Usage

### 1. Pick or create an instance

The **Instance** bar at the top switches between monitors. Use **+ New** to create one, **Rename** to label it (e.g. "rent", "jobs"), and **Delete** to remove it. Each instance is fully isolated.

### 2. Connect the instance's Telegram account

In the **Telegram Account** card, enter that instance's **API ID**, **API Hash**, and **Phone Number**, then click **Save & Send Login Code**. Enter the code Telegram sends to that account. If the account has two-step verification, enter its cloud password.

Each instance's session is saved locally (`session_<id>.session`) and reused on later startups — you only authenticate once per account.

### 3. Configure monitoring

| Field | Description |
|---|---|
| **Webhook URL** | Any HTTP endpoint that accepts POST JSON |
| **Telegram Bot Token** | From [@BotFather](https://t.me/BotFather) — optional |
| **Telegram Chat ID** | Where the bot should forward matches |
| **Target Channels** | Channel usernames (without `@`) or numeric IDs |
| **Keywords** | Whole words/phrases to watch for — case-insensitive |
| **Excluded Words** | If any appears in a message, the match is suppressed |
| **Match Cooldown** | Seconds to ignore the same keyword+channel after a hit (0 = off) |

Click **Save Settings** when done.

### 4. Getting a channel ID

For public channels, the username works (e.g. `durov`).

For private channels or groups, forward any message from the chat to [@userinfobot](https://t.me/userinfobot) — it will reply with the numeric ID.

The account for that instance must be a **member** of any channel it monitors.

### 5. Webhook payload

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

## Configuration

| Environment variable | Description |
|---|---|
| `API_ID`, `API_HASH`, `PHONE_NUMBER` | Optional. Seed the first instance's credentials on first run. |
| `TG_DATA_DIR` | Optional. Directory for the settings database and session files. Defaults to `src/database`. |

---

## Project Structure

```
tg-parser/
├── main.py                  # FastAPI app, routes (instances, auth, settings)
├── requirements.txt
├── start.sh / start.bat     # Quick-start scripts
├── .env.example             # Optional — seeds the first instance's credentials
└── src/
    ├── config.py            # Env loading, data-dir resolution
    ├── database_manager.py  # SQLite via aiosqlite (instances, events)
    ├── telegram_client.py   # One Telethon client per instance, matching logic
    ├── database/            # settings.sqlite + session_<id>.session files
    ├── static/
    │   ├── app.js
    │   └── index.css
    └── templates/
        └── index.html
```

---

## License

MIT — see [LICENSE](LICENSE).
