# Stock Alerts

Monitors **SPCX**, **GLD**, and **TSLA** for ±5% daily moves and sends Telegram alerts when triggered.

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/botfather) and copy the bot token.
2. Edit `stock_alerts.py` and set your `TELEGRAM_BOT_TOKEN`.
3. Run manually or schedule via cron:

```bash
python3 stock_alerts.py
```

## Cron (7 AM Pacific daily)

The cron job is managed separately in OpenClaw. Schedule with:
```
0 7 * * * America/Los_Angeles
```

## Alert Threshold

Default is ±5% change from previous close. Adjust `THRESHOLD` in the script.
