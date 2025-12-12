# Gateway Bot (discord.py) - Quick Run

This file explains how to run the Gateway-based listener which forwards MESSAGE_CREATE events
into your existing Flask handlers via the `/dev/simulate_message` endpoint.

Prerequisites

- `DISCORD_BOT_TOKEN` must be set in `.env`.
- `TEST_CHANNEL_ID` should be set to the channel you want the bot to listen in.
- Install dependencies:

```bash
pip install -r requirements.txt
```

Run

```bash
# Stop existing gateway bot (if running)
pkill -f gateway_bot.py || true

# Start the bot
python gateway_bot.py
```

Notes

- The gateway bot uses `message_content` intent; ensure the bot has "Message Content Intent" enabled in the Discord Developer Portal.
- It will forward messages only from `TEST_CHANNEL_ID` (if set) to avoid unexpected behavior in other channels.
- The bot forwards messages to the Flask dev endpoint so your existing handlers are reused.
