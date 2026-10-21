# 🚨 Ukrainian Alerts Telegram Bot

A production-ready Telegram bot that monitors and notifies users about air raid alerts in Ukraine using the `alerts.in.ua` API. Designed to run on **Render.com Free Tier** as a Background Worker.

## 📋 Features

- **Real-time Alert Monitoring**: Polls `alerts.in.ua` API every 10 seconds with conditional requests (`If-Modified-Since`)
- **Smart Change Detection**: Identifies new alerts, new threats, and cancelled alerts
- **User Subscriptions**: Users can subscribe to specific regions/districts/territorial communities
- **Ukrainian Interface**: Fully localized Telegram bot interface and notifications
- **Efficient Caching**: Uses HTTP conditional requests to minimize API load
- **Single Process Architecture**: Combines Telegram bot and background poller in one asyncio loop
- **Persistent Storage**: CSV-based storage for users and API responses (ephemeral disk-friendly)

## 🗂️ Project Structure

```
bot/
├── bot.py                          # Main bot application
├── requirements.txt                # Python dependencies
├── README.md                        # This file
├── users.csv                        # User subscriptions (auto-created)
├── last_api_response.json          # Cached API response (auto-created)
└── locations.csv                    # Available locations (auto-created)
```

## 🚀 Deployment on Render.com

### Step 1: Prepare Your Repository

1. Clone this repository or push these files to GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git push -u origin main
   ```

### Step 2: Create a Render Background Worker

1. Go to [render.com](https://render.com) and sign in
2. Click **"New +"** → **"Background Worker"**
3. Fill in the following:
   - **Name**: `ukrainian-alerts-bot` (or your preferred name)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
   - **Instance Type**: Free

### Step 3: Set Environment Variables

In the Render dashboard, go to **Environment** and add:

| Variable | Value | Notes |
|----------|-------|-------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token | Get from [@BotFather](https://t.me/BotFather) on Telegram |
| `ALERTS_API_TOKEN` | Your alerts.in.ua API token | Get from [alerts.in.ua](https://alerts.in.ua) |

### Step 4: Deploy

Click **"Deploy"** and your bot will start running immediately.

## 🎮 Using the Bot

1. Start the bot with `/start`
2. Choose an action:
   - **➕ Додати локацію** (Add Location): Subscribe to alerts for a region/district
   - **➖ Видалити локацію** (Remove Location): Unsubscribe from a location
   - **📋 Мої підписки** (My Subscriptions): View your current subscriptions

3. Select regions, districts, or territorial communities via inline menus

## 📊 API Response Handling

The bot uses the following logic:

### Polling Strategy
- **Interval**: Every 10 seconds
- **Conditional Requests**: Sends `If-Modified-Since` header with the previous response's `Last-Modified` value
- **304 Handling**: When API returns 304 Not Modified, processing is skipped entirely

### Change Detection
The bot identifies three types of changes per location:

1. **New Alert Started**: Location has no active alert in the previous state
2. **New Threat Added**: Location has new threat entries compared to the previous state
3. **Alert Cancelled**: Location was active before but is now absent

### Notification Messages

All messages are in Ukrainian and use emoji icons based on alert level:

| Scenario | Format |
|----------|--------|
| New alert (no threats) | `🔴 Назва: Тип тривоги` or `🟡 Назва: Тип тривоги` |
| New/added threat | `🔴 Назва: Текст загрози` or `🟡 Назва: Текст загрози` |
| Alert cancelled | `🟢 Назва: відбій тривоги` |

## 💾 Data Storage

### users.csv
Stores user subscriptions in the format:
```csv
userId,locations
123456789,31,4,27
987654321,9,28
```

### last_api_response.json
Caches the last API response to detect changes:
```json
{
  "alerts": {
    "31": { "id": 1, "location_uid": "31", ... },
    "4": { "id": 2, "location_uid": "4", ... }
  },
  "last_modified": "2026-10-22T10:30:00.000Z",
  "timestamp": "2026-10-22T10:30:05.123456+00:00"
}
```

### locations.csv
Pre-populated location hierarchy for user selection.

## 🔧 Development & Local Testing

### Prerequisites
- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd bot

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export TELEGRAM_BOT_TOKEN="your_token_here"
export ALERTS_API_TOKEN="your_api_token_here"

# Run the bot
python bot.py
```

### Testing Changes
1. Make changes to `bot.py`
2. Stop the bot (Ctrl+C)
3. Re-run `python bot.py`
4. Test via Telegram

## 📝 Configuration

### Polling Interval
To change the polling interval, modify this line in `bot.py`:
```python
await asyncio.sleep(10)  # Change 10 to your desired interval in seconds
```

### Location Hierarchy
The location data is loaded from `locations.csv`. To update available locations, modify the data in the `_create_locations_from_data()` method.

## 🛡️ Error Handling

- **API Failures**: Logged and skipped; next poll continues normally
- **Network Issues**: HTTP client automatically retries with timeouts
- **User Not Found**: Messages to invalid user IDs are logged but don't crash the bot
- **CSV Errors**: File I/O errors are logged; bot continues operation

## 📊 Monitoring

View bot logs in the Render dashboard:
1. Go to your Background Worker
2. Click **"Logs"** tab
3. Filter by log level or search for keywords

Key log messages to watch:
- `Starting alerts poller` - Bot initialized
- `Loaded X locations` - Location data loaded
- `API returned 304 Not Modified` - Efficient caching working
- `Error polling alerts` - API connection issues

## 🔐 Security Considerations

1. **API Token**: Never commit tokens to git; use Render environment variables
2. **User Data**: User subscriptions are stored in CSV files; access is unrestricted on Render disk
3. **Telegram Token**: Treated as sensitive; never exposed in logs

For production, consider:
- Using a database instead of CSV files
- Implementing rate limiting per user
- Adding bot command authentication/admin features

## 📞 Troubleshooting

### Bot doesn't respond to /start
- Check `TELEGRAM_BOT_TOKEN` is set correctly
- Verify the bot token with [@BotFather](https://t.me/BotFather)
- Check Render logs for errors

### Alerts not being sent
- Verify `ALERTS_API_TOKEN` is valid
- Check bot logs for API errors
- Ensure users are subscribed to locations that have active alerts
- Verify alert location UID matches subscription

### Performance Issues
- Rendering free tier may experience cold starts (first request slower)
- If polling seems slow, check API response times in logs
- Consider upgrading instance type for production use

## 📈 Scaling

For production use beyond the free tier:
1. Migrate to **Render Standard** instance type
2. Replace CSV storage with a database (PostgreSQL, MongoDB, etc.)
3. Implement Redis caching for user subscriptions
4. Add Telegram webhook instead of polling for better performance
5. Implement rate limiting and command throttling

## 📄 License

This project is provided as-is for monitoring Ukrainian air raid alerts.

## 🤝 Contributing

Contributions are welcome! Please:
1. Test locally before submitting
2. Keep Ukrainian localization consistent
3. Follow the existing code structure

## 📚 Resources

- [python-telegram-bot Documentation](https://python-telegram-bot.readthedocs.io/)
- [alerts.in.ua API](https://alerts.in.ua)
- [Render.com Docs](https://render.com/docs)
- [Telegram Bot API](https://core.telegram.org/bots)

---

**Stay safe and informed! 🇺🇦**
