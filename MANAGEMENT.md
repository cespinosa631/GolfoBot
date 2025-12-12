# 🤖 GolfoStreams Bot - Management Guide

## Quick Start

### Option 1: One-Command Startup (Recommended)

```bash
cd /Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams
./start_bot.sh
```

This starts both the Flask server and the automatic ngrok monitor.

### Option 2: Interactive Control Center

```bash
./control.sh
```

This opens a menu where you can:

- Start/stop services
- View logs
- Check status
- Manually restart ngrok
- And more!

### Option 3: Manual Startup

```bash
# Terminal 1: Start Flask server
python server.py

# Terminal 2: Start ngrok monitor
./monitor_ngrok.sh
```

---

## Scripts Explained

### `start_bot.sh`

**One-command startup** - Launches both the Flask server and ngrok monitor with auto-restart capabilities.

**Usage:**

```bash
./start_bot.sh
```

**What it does:**

- Kills any existing processes
- Starts Flask server on port 5000
- Starts ngrok monitor to keep tunnel alive
- Shows you the PIDs and log locations

---

### `monitor_ngrok.sh`

**Automatic ngrok tunnel monitor** - Keeps your ngrok tunnel alive and restarts it if it disconnects.

**Features:**

- Checks tunnel every 30 seconds
- Auto-restarts if disconnected
- Logs to `/tmp/ngrok_monitor.log`
- Retry logic (up to 5 attempts)
- Shows tunnel URL in logs

**Usage:**

```bash
./monitor_ngrok.sh
```

**View logs:**

```bash
tail -f /tmp/ngrok_monitor.log
```

---

### `control.sh`

**Control center** - Interactive menu for managing the bot.

**Features:**

- Start/stop/restart services
- View Flask and ngrok logs
- Check real-time service status
- Get ngrok URL
- Manually restart ngrok

**Usage:**

```bash
./control.sh
```

Then select option from menu:

```
1) Start bot
2) Stop all services
3) Restart bot
4) View Flask logs
5) View ngrok monitor logs
6) Check service status
7) Manually restart ngrok
8) Exit
```

---

## Common Tasks

### Check if bot is running

```bash
./control.sh
# Select option 6
```

### View ngrok tunnel status and URL

```bash
./control.sh
# Select option 6
```

Or check logs:

```bash
tail -f /tmp/ngrok_monitor.log
```

### Restart ngrok tunnel

```bash
./control.sh
# Select option 7
```

### Stop everything

```bash
pkill -f "python.*server.py" && pkill -f "ngrok http" && pkill -f "monitor_ngrok"
```

Or use:

```bash
./control.sh
# Select option 2
```

### View Flask server logs

```bash
tail -f /tmp/flask_server.log
```

Or use:

```bash
./control.sh
# Select option 4
```

---

## Troubleshooting

### ngrok keeps disconnecting

- The monitor script will automatically restart it
- Check logs: `tail -f /tmp/ngrok_monitor.log`
- Make sure ngrok is installed: `which ngrok`
- Verify port 5000 isn't blocked

### Flask server won't start

```bash
# Check if port 5000 is already in use
lsof -i :5000

# If something is there, kill it
kill -9 <PID>

# Then restart
./start_bot.sh
```

### ngrok URL not working

- Check if Flask server is running: `curl http://localhost:5000/health`
- Check ngrok status: `curl http://localhost:4040/api/tunnels`
- Restart ngrok monitor: `./control.sh` → option 7

### Scripts not executable

```bash
chmod +x start_bot.sh monitor_ngrok.sh control.sh
```

---

## Log Locations

- **Flask Server:** `/tmp/flask_server.log`
- **ngrok Monitor:** `/tmp/ngrok_monitor.log`
- **ngrok Tunnel:** `/tmp/ngrok.log`

---

## Environment Variables

All required variables are in `.env`:

- `DISCORD_PUBLIC_KEY` - Bot public key
- `DISCORD_BOT_TOKEN` - Bot token
- `DISCORD_CHANNEL_ID` - Primary channel
- `TEST_CHANNEL_ID` - Test channel (1446331936204132423)
- `ANNOUNCE_CHANNEL_ID` - Announcements channel
- `GEMINI_API_KEY` - Google Gemini API key
- `ALLOW_DEV_ENDPOINTS` - Enable dev endpoints (set to 1)

---

## Testing the Bot

Once running, test in your Discord test channel (1446331936204132423):

1. **Greeting test:**

   ```
   Hey GolfoBot! What's up?
   ```

2. **Team organization test:**

   ```
   GolfoBot, arma los equipos 2v2
   ```

3. **Other formats:**
   ```
   GolfoBot, organiza los equipos 3v3
   GolfoBot, sepáranos pa' jugar 4v4
   ```

---

## Production Notes

For production deployment, consider:

- Use a proper WSGI server (gunicorn, uWSGI) instead of Flask dev server
- Use ngrok paid plan for stable URLs
- Set `debug=False` in Flask
- Use proper logging service
- Monitor script stability

---

**Created:** December 4, 2025
**Bot:** GolfoStreams Discord Bot
**Location:** `/Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams`
