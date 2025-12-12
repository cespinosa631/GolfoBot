# Railway.app Deployment Guide for GolfoBot

## Quick Start

### 1. Create Railway Account

- Go to https://railway.app/
- Sign up with GitHub (easiest)
- You get **$5 free credit + 30-day trial** (no credit card required)

### 2. Create New Project

**Option A: Deploy from GitHub (Recommended)**

1. Push your code to GitHub first
2. In Railway dashboard: "New Project" → "Deploy from GitHub repo"
3. Select your GolfoStreams repository
4. Railway will auto-detect Python and install dependencies

**Option B: Deploy via Railway CLI**

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize project in your repo
cd /Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams
railway init

# Deploy
railway up
```

### 3. Create Two Services

Railway needs to run both the gateway bot AND the Flask server as separate services:

**Service 1: Gateway Bot**

1. In Railway dashboard, click your project
2. Click "New Service" → "Empty Service"
3. Name it: `gateway-bot`
4. Under "Settings" → "Start Command": `python gateway_bot.py`
5. Under "Settings" → "Restart Policy": Set to "On Failure" with 10 retries

**Service 2: Flask Server**

1. Click "New Service" → "Empty Service"
2. Name it: `server`
3. Under "Settings" → "Start Command": `python server.py`
4. Under "Settings" → "Restart Policy": Set to "On Failure" with 10 retries

### 4. Set Environment Variables

For **BOTH services**, add these environment variables:

**Required:**

```
DISCORD_BOT_TOKEN=your_bot_token_here
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
```

**Optional (customize if needed):**

```
VOICE_ENGINE=gtts
TEST_VOICE_CHANNEL_ID=your_channel_id
PARTIDA_1_VOICE_CHANNEL_ID=your_channel_id
ALLOW_DEV_ENDPOINTS=1
```

**Server-specific (add to server service only):**

```
FLASK_HOST=http://server.railway.internal:5000
```

**Gateway-specific (add to gateway-bot service only):**

```
FLASK_HOST=http://server.railway.internal:5000
```

To add variables in Railway:

1. Click on a service
2. Go to "Variables" tab
3. Click "New Variable"
4. Add key-value pairs
5. Click "Add" for each

### 5. Deploy and Monitor

**Deploy:**

- Railway auto-deploys when you push to GitHub
- Or click "Deploy" button in dashboard

**Monitor:**

- Click on each service to see logs in real-time
- Check "Metrics" tab for CPU/RAM usage
- Logs will show if bot connected successfully

**Expected logs:**

- Gateway bot: "Logged in as GolfoStreams#2542"
- Server: "Running on http://0.0.0.0:5000"

### 6. Free Tier Limits

**What you get free:**

- $5 credit (lasts ~1 month with light usage)
- 512 MB RAM per service
- 1 vCPU per service
- 500 GB outbound bandwidth

**Usage monitoring:**

- Dashboard shows credit usage
- Will warn you when approaching $5 limit
- Bot will stop when credit runs out

**If free tier isn't enough:**

- Upgrade to Hobby plan: $5/month
- Gives you execution-based pricing (pay for what you use)
- Typically costs $3-8/month for voice bots like GolfoBot

## Troubleshooting

### Bot crashes with "Out of Memory"

**Solution:** Free tier's 512 MB might be tight. Options:

1. Wait 5 minutes and check if it auto-restarts
2. Upgrade to Hobby plan ($5/month) for more RAM
3. Reduce `CONTEXT_MAX_ENTRIES` in code to 3 (currently 5)

### "Connection refused" errors

**Solution:** Make sure both services are running:

1. Check that gateway-bot service is "Active"
2. Check that server service is "Active"
3. Verify `FLASK_HOST` env var is set correctly

### Voice commands not working

**Checklist:**

1. Bot shows as online in Discord? ✓
2. Gateway logs show "Logged in as..."? ✓
3. Server logs show "Running on..."? ✓
4. Environment variables set? ✓
5. Bot has permissions in Discord server? ✓

### High costs

**If approaching $5 quickly:**

- Check Metrics tab - look for CPU/RAM spikes
- Voice processing uses more resources
- Consider switching to Fly.io free tier (better for light usage)

## Cost Estimation

**Your usage (3 hours/day):**

- Expected cost: $3-4/month
- Free credit covers first month
- After that, add payment method or upgrade to Hobby

**To reduce costs:**

1. Only run when needed (not recommended - bot won't respond)
2. Use Fly.io free tier instead (better for light usage)
3. Reduce conversation context size in code

## Alternative: Fly.io Free Tier

If Railway becomes too expensive, Fly.io has a better free tier:

- 3 VMs × 256 MB RAM (768 MB total)
- Free forever, no credit card needed
- Better for light usage (3 hours/day)

Let me know if you want Fly.io deployment files instead!

## Support

- Railway Discord: https://discord.gg/railway
- Railway Docs: https://docs.railway.app/
- Check logs first - they usually show the problem
