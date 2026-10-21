You are an expert Python developer. Please write a complete, robust, and production-ready Telegram Bot in Python using `python-telegram-bot` (v20+) and `httpx` (or `requests`) designed to run as a **Background Worker on Render.com** (using the Free Tier).

### 🚀 Architectural Requirements (Render.com Free Tier)
1. **Single Process Architecture**: Since Render free tier runs a single background worker, combine both the Telegram Bot webhook/polling interface and the background alerts polling loop into a single Python process using `asyncio`.
2. **Persistence & Storage**: Use local CSV files to persist data (since Render disk is ephemeral on free tier, mention this to the user in a README comment or ensure simple file-based atomic writes).
   - `users.csv`: Stores user subscriptions in format `userId,location_uid1,location_uid2,...`
   - `last_api_response.json`: Stores the previous raw JSON response from the alerts API along with the last `Last-Modified` header value.
3. **Keep-Alive (Optional/Recommended for Free Tier)**: Include a lightweight mechanism or comment explaining how to prevent Render from sleeping if required, or design the main `asyncio` loop to continuously poll.

---

### 🌐 API Polling & Caching Logic (`alerts.in.ua`)
1. **Polling Interval**: Poll `https://api.alerts.in.ua/v1/alerts/active.json?token=YOUR_TOKEN` every **10 seconds**.
2. **Conditional Requests (`If-Modified-Since`)**: 
   - Store the `Last-Modified` header received from the previous successful API response.
   - Send `If-Modified-Since` header in subsequent requests.
   - If the API returns `304 Not Modified`, skip processing entirely and do nothing.
3. **Change Detection**:
   - Compare the new active alerts JSON with the saved previous JSON response.
   - Identify changes per location UID:
     - **New Alert Started (no threats)**
     - **New Alert Started with Threats / New Threat added** to an existing alert (`threats[i]`)
     - **Alert Cancelled completely** (was active in previous state, now absent or status changed to inactive/cleared).
4. **Duplicate Prevention**: Ensure no user receives duplicate notifications for the exact same event/state change.
5. **Sample API Response Structure (`samlple.json`)**:
   When parsing the API response, expect a structure similar to this sample JSON format (please adapt parsing to match this schema):
   ```json
   {
     "meta": {
       "last_modified": "2026-10-21T...",
       "alert_count": X
     },
     "alerts": [
       {
         "location_uid": "31",
         "location_type": "city",
         "location_title": "м. Київ",
         "started_at": "2026-10-21T...",
         "updated_at": "2026-10-21T...",
         "alert_level": "red",
         "alert_type": "air_raid",
         "threats": [
           {
             "level": "red",
             "threat_type": "missile",
             "source_message": "Загроза застосування балістичного озброєння з півдня!"
           }
         ]
       }
     ]
   }

---

### 📂 Location Data & Setup
1. Load location hierarchy from the provided CSV file (`alerts.in.ua _ Райони_ області_ громади.xlsx - Sheet2 (1).csv`) or hardcode/parse it on startup so users can select:
   - Step 1: Choose a parent district/city or region from the predefined list.
   - Step 2: Choose a sub-region (if available). If no sub-regions exist, allow selecting the whole district/city and store its `UID`.
2. Provide interactive Telegram Inline Keyboards for location selection, adding new locations, and removing existing subscribed locations.

---

### 💬 Telegram Bot Messages & Localization (Ukrainian)
All bot interactions, menus, and notifications must be in **Ukrainian**.

#### Notification Message Formats:
1. **New alert starts and no threats available**:
   `{circle_icon} {location_title}: {alert_type}`
   *(Where circle icon is red 🔴 or yellow 🟡 based on `alert_level`)*

2. **New alert starts with threats OR new threat `[i]` added to existing alert**:
   `{circle_icon} {location_title}: {source_message}`
   *(Where circle icon is red 🔴 or yellow 🟡 based on `threats[i].level`. If `threats[i].source_message` is undefined or empty, fallback to `threats[i].threat_type`)*

3. **Alert cancelled completely**:
   `🟢 {location_title}: відбій тривоги`

---

### 🛠️ Deliverables Required:
1. `bot.py` containing the complete asynchronous bot logic, API poller, change detector, and CSV storage handlers.
2. `requirements.txt` with all necessary dependencies (`python-telegram-bot`, `httpx`, `pandas` or built-in `csv`, etc.).
3. `README.md` with instructions on how to set environment variables (`TELEGRAM_BOT_TOKEN`, `ALERTS_API_TOKEN`) and deploy on Render.com as a Background Worker.