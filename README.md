# GolfoBot - Discord Voice & Chat Bot

GolfoBot is a Discord bot with voice conversation capabilities, powered by Groq LLM and ElevenLabs TTS.

## Features

- 🎤 **Voice Conversations**: Listen to users in voice channels and respond with natural speech
- 💬 **Chat Commands**: Join/leave voice channels, greet users, and more
- 🤖 **AI-Powered**: Uses Groq (Llama 3.3) for intelligent responses
- 🗣️ **Text-to-Speech**: ElevenLabs for natural-sounding voice
- 🇲🇽 **Mexican Spanish**: Casual, friendly personality

## Prerequisites

- Python 3.10+
- Conda environment named `tensor`
- Discord Bot Token
- Groq API Key
- ElevenLabs API Key

## Installation

1. **Install dependencies:**

```bash
conda activate tensor
pip install discord.py discord-ext-voice-recv SpeechRecognition PyNaCl requests aiohttp python-dotenv
```

2. **Configure environment variables:**
   Create a `.env` file with:

```bash
DISCORD_BOT_TOKEN=your_bot_token
GROQ_API_KEY=your_groq_api_key
ELEVEN_LABS_API_KEY=your_elevenlabs_key
ELEVEN_LABS_VOICE_ID=your_voice_id
TEST_VOICE_CHANNEL_ID=your_channel_id
ALLOW_DEV_ENDPOINTS=1
```

## Running the Bot

### ⚠️ Important: Both Components Required

GolfoBot requires **TWO** processes to run:

1. **Gateway Bot** (`gateway_bot.py`) - Handles Discord voice/chat
2. **Flask Server** (`server.py`) - Provides LLM responses

**Both must be running** for the bot to respond to voice commands!

---

### Quick Start (Recommended)

**1. Activate conda environment:**

```bash
conda activate tensor
cd /Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams
```

**2. Start the Flask server (REQUIRED):**

```bash
python server.py &> /tmp/server.log &
```

**3. Start the gateway bot:**

```bash
python gateway_bot.py &> /tmp/gateway_bot.log &
```

**4. Verify both are running:**

```bash
ps aux | grep -E "gateway_bot|server.py" | grep -v grep
```

You should see:

- `gateway_bot.py` (Discord bot)
- `server.py` (Flask server on port 5000)

**5. View logs in real-time:**

```bash
# Gateway bot logs
tail -f /tmp/gateway_bot.log

# Server logs
tail -f /tmp/server.log
```

---

### Alternative: With Auto-Restart Watchdog

**1. Start Flask server:**

```bash
conda activate tensor
cd /Users/cristianespinosa/Documents/Discord_Bots/GolfoStreams
python server.py &> /tmp/server.log &
```

**2. Start gateway bot with watchdog:**

```bash
nohup ./restart_bot.sh > /tmp/watchdog.log 2>&1 &
```

**3. Verify everything is running:**

```bash
ps aux | grep -E "gateway_bot|server.py|restart_bot" | grep -v grep
```

You should see:

- `restart_bot.sh` (watchdog script)
- `gateway_bot.py` (Discord bot)
- `server.py` (Flask server)

---

### Stopping the Bot

**Stop everything:**

```bash
pkill -f "gateway_bot.py"
pkill -f "restart_bot.sh"  # If using watchdog
pkill -f "server.py"
```

**Stop individual components:**

```bash
# Stop just the gateway bot
pkill -f "gateway_bot.py"

# Stop just the server
pkill -f "server.py"
```

**Force kill if needed:**

```bash
pkill -9 -f "gateway_bot.py"
pkill -9 -f "server.py"
```

## Discord Commands

### Voice Channel Commands

- `@GolfoBot únete` - Join default voice channel
- `@GolfoBot únete a <#CHANNEL_ID>` - Join specific channel (paste channel mention)
- `@GolfoBot únete a [channel name]` - Join channel by name (e.g., "únete a partida 1")
- `@GolfoBot sal` / `vete` / `leave` - Leave voice channel

### Voice Conversations

Just speak in the voice channel! The bot will:

1. Listen to your speech
2. Transcribe it (Spanish)
3. Generate a response using Groq LLM
4. Speak back using ElevenLabs TTS

**Tips for best results:**

- Speak clearly and loud enough
- Use full sentences (at least 2-3 seconds)
- Reduce background noise
- One person at a time for clearest recognition

## Troubleshooting

### Bot not responding to voice

1. Check if bot is in voice channel (should see it in Discord)
2. Check logs: `tail -50 /tmp/gateway_bot.log`
3. Look for "Could not understand audio" - means speech recognition failed
4. Restart bot: `pkill -f "gateway_bot.py"` then run watchdog again

### Bot disconnects after a few minutes

This is a known Discord gateway timeout issue. The watchdog script automatically handles this by restarting the bot.

The bot may also show "User may be having trouble connecting" warnings in Discord - this is normal when Discord resets the voice WebSocket. The bot automatically reconnects within seconds.

### Transcription failures

If Google Speech Recognition consistently fails:

- Ask users to speak louder and clearer
- Check Discord voice region settings
- Ensure only one person speaks at a time

### LLM quota exceeded

If you see quota errors:

- Groq has generous free tier (30 req/min)
- Check your API usage at console.groq.com
- The bot automatically falls back to Gemini if Groq fails

## Architecture

- **gateway_bot.py**: Main Discord bot (voice + chat)
- **server.py**: Flask server for LLM endpoints and webhooks
- **restart_bot.sh**: Watchdog script for auto-recovery
- **VoiceListener**: Custom voice client for receiving audio
- **Speech Recognition**: Google Speech Recognition (Spanish-MX)
- **LLM**: Groq (Llama 3.3 70B) with Gemini fallback
- **TTS**: gTTS (Google Text-to-Speech) - free and unlimited

## TTS Engine Options

You can change the TTS engine by setting `VOICE_ENGINE` in `.env`:

```bash
# Option 1: gTTS (default - free, unlimited, works everywhere)
VOICE_ENGINE=gtts

# Option 2: ElevenLabs (best quality, but requires API key and has quota)
VOICE_ENGINE=elevenlabs
ELEVEN_LABS_API_KEY=your_key
ELEVEN_LABS_VOICE_ID=your_voice_id

# Option 3: macOS say (only works on Mac, requires proper voice names)
VOICE_ENGINE=say
VOICE_SAY_VOICE=Eddy (Spanish (Mexico))
```

**Current setup**: Using gTTS by default (free, no quotas, works on all platforms)

## Performance

- **Response time**: ~4 seconds (optimized from 7-10s)
  - 1.2s silence detection
  - 1-2s transcription
  - 0.5-1s LLM response
  - 0.5s TTS generation

## Credits

Built with ❤️ using:

- discord.py
- discord-ext-voice-recv
- Groq API
- Google Speech Recognition
- gTTS (Google Text-to-Speech)
