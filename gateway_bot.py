"""
Gateway-based bot using discord.py to handle MESSAGE_CREATE events.
This runs alongside your Flask server and will forward mentions and voice
commands to the same internal handlers (by calling internal helper
functions via an HTTP POST to `/dev/simulate_message`), keeping behavior
consistent with your Flask-only flow.

Usage:
  - Ensure `.env` has DISCORD_BOT_TOKEN set (same token you're using)
  - Install requirements: `pip install -r requirements.txt`
  - Run: `python gateway_bot.py`

Notes:
  - This bot uses intents to read messages and members (for voice state)
  - It will POST a small MESSAGE_CREATE-shaped JSON to the Flask server's
    `/dev/simulate_message` endpoint so the existing handlers are reused.
"""

import os
import asyncio
import logging
import json
import aiohttp
import re
import tempfile
import random
import gc  # Garbage collection for memory optimization
from datetime import datetime
from dotenv import load_dotenv
from gtts import gTTS
import io
import wave

load_dotenv()

# Print to stdout before anything else (Railway will see this)
print("=" * 80, flush=True)
print("🚀 GOLFOBOT GATEWAY STARTING - LOADING MODULES", flush=True)
print("=" * 80, flush=True)

import discord
from discord import Intents, FFmpegPCMAudio
from discord.ext import voice_recv
import shutil
import subprocess
from aiohttp import web
import hashlib
from pathlib import Path
import time

print("=" * 80, flush=True)
print("📦 Discord modules loaded, configuring logging...", flush=True)
print("=" * 80, flush=True)

# Configure logging FIRST with immediate flushing
import sys
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    force=True
)
sys.stdout.flush()
logger = logging.getLogger('gateway_bot')

logger.info("=" * 60)
logger.info("🚀 GolfoBot Gateway Starting...")
logger.info("=" * 60)
sys.stdout.flush()

print("=" * 80, flush=True)
print("🔧 About to load Opus library...", flush=True)
print("=" * 80, flush=True)

# CRITICAL: Load Opus library for voice support
logger.info("🔧 Loading Opus library for voice support...")
sys.stdout.flush()

try:
    import discord.opus
    import ctypes.util
    
    # Add common library paths to search
    import os
    lib_paths = os.environ.get('LD_LIBRARY_PATH', '').split(':')
    additional_paths = [
        '/usr/lib/x86_64-linux-gnu',
        '/usr/lib',
        '/usr/local/lib',
        '/lib/x86_64-linux-gnu',
    ]
    for path in additional_paths:
        if path and path not in lib_paths:
            lib_paths.append(path)
    os.environ['LD_LIBRARY_PATH'] = ':'.join(filter(None, lib_paths))
    
    logger.info(f"LD_LIBRARY_PATH: {os.environ.get('LD_LIBRARY_PATH')}")
    sys.stdout.flush()
    
    # Try to find libopus using ctypes
    opus_path = ctypes.util.find_library('opus')
    logger.info(f"ctypes.util.find_library('opus'): {opus_path}")
    sys.stdout.flush()
    
    if not discord.opus.is_loaded():
        import glob
        
        # Search multiple locations
        search_paths = [
            '/usr/lib/x86_64-linux-gnu/libopus.so*',
            '/usr/lib/libopus.so*',
            '/usr/local/lib/libopus.so*',
            '/lib/x86_64-linux-gnu/libopus.so*',
            '/nix/store/*/lib/libopus.so*',
        ]
        
        found_libs = []
        for pattern in search_paths:
            found_libs.extend(glob.glob(pattern))
        
        logger.info(f"Found {len(found_libs)} libopus files: {found_libs[:3]}")
        sys.stdout.flush()
        
        # Try different loading strategies
        load_attempts = [
            'opus',
            'libopus.so.0',
            'libopus.so',
            'libopus',
        ] + found_libs
        
        for i, lib_path in enumerate(load_attempts):
            try:
                logger.info(f"Attempt {i+1}: Trying to load {lib_path}")
                sys.stdout.flush()
                discord.opus.load_opus(lib_path)
                logger.info(f"✅ SUCCESS! Loaded Opus from: {lib_path}")
                sys.stdout.flush()
                break
            except Exception as e:
                logger.debug(f"  Failed: {e}")
                continue
        
        if not discord.opus.is_loaded():
            logger.error("❌ CRITICAL: Failed to load Opus library!")
            logger.error("Voice receiving will NOT work without Opus!")
            sys.stdout.flush()
    else:
        logger.info("✅ Opus already loaded")
        sys.stdout.flush()
        
except Exception as e:
    logger.error(f"❌ Error during Opus loading: {e}")
    import traceback
    logger.error(traceback.format_exc())
    sys.stdout.flush()

# Suppress Discord voice_recv opus errors (malformed packets during reconnections)
logging.getLogger('discord.ext.voice_recv.router').setLevel(logging.CRITICAL)
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.WARNING)
logging.getLogger('discord.voice_state').setLevel(logging.WARNING)  # Reduce voice reconnection noise

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
FLASK_HOST = os.environ.get('FLASK_HOST')
DEV_SIMULATE_ENDPOINT = f"{FLASK_HOST}/dev/simulate_message"
TEST_CHANNEL_ID = os.environ.get('TEST_CHANNEL_ID')
PARTIDA_1_VOICE_CHANNEL_ID = os.environ.get('PARTIDA_1_VOICE_CHANNEL_ID')
TEST_VOICE_CHANNEL_ID = os.environ.get('TEST_VOICE_CHANNEL_ID')

if not DISCORD_BOT_TOKEN:
    logger.error('DISCORD_BOT_TOKEN not set in environment. Exiting.')
    raise SystemExit(1)

intents = Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True
intents.guilds = True
intents.voice_states = True

# Increase gateway timeout to prevent disconnections
client = discord.Client(
    intents=intents,
    heartbeat_timeout=90.0,  # Increase from default 60s
    guild_ready_timeout=10.0  # Increase from default 2s
)

MENTION_REGEX = re.compile(r'<@!?(\d+)>', re.I)

# Voice listening state
voice_listeners = {}  # guild_id -> dict with listener info
audio_buffers = {}  # (guild_id, user_id) -> list of audio chunks
last_speech_time = {}  # (guild_id, user_id) -> timestamp
processing_speech = set()  # (guild_id, user_id) tuples currently being processed
conversation_context = {}  # guild_id -> list of recent speech [(username, text, timestamp)]
last_voice_packet_time = {}  # guild_id -> timestamp of last voice packet received
voice_reconnect_in_progress = set()  # guild_ids currently reconnecting
bot_is_speaking = set()  # guild_ids where bot is currently playing TTS (pause listening)
voice_reconnect_time = {}  # guild_id -> timestamp of last reconnection (to ignore stale packets)

# Conversation settings
RANDOM_REPLY_PROBABILITY = 0.20  # 20% chance to reply even when not addressed
CONTEXT_MAX_ENTRIES = 5  # Keep last 5 speech entries for context (reduced from 10 for memory)
CONTEXT_TIMEOUT = 300  # 5 minutes - clear context after this
VOICE_HEALTH_CHECK_INTERVAL = 20  # Check voice connection health every 20 seconds (more frequent)
VOICE_PACKET_TIMEOUT = 60  # Reconnect if no packets received for 1 minute (more aggressive)
VOICE_KEEPALIVE_INTERVAL = 30  # Send speaking state update every 30s to keep connection alive
RECONNECT_GRACE_PERIOD = 3  # Ignore packets received within 3 seconds after reconnection
MAX_AUDIO_BUFFER_PACKETS = 250  # Max packets to buffer per user (prevent memory overflow, ~10 seconds)

# Bot names that indicate someone is talking to it
BOT_TRIGGER_NAMES = [
    'golfito', 'golfobot', 'golfostreams', 'bot', 'streams',
    'golfo', 'golf', 'compa', 'compadre', 'amigo', 'bro',
    'asistente', 'ayudante', 'ai'
]

# Attention-getting words that indicate direct address
ATTENTION_WORDS = ['oye', 'hey', 'escucha', 'ey', 'eh', 'mira', 've', 'ven', 'oiga', 'hola']

def add_to_context(guild_id: int, username: str, text: str):
    """Add speech to conversation context."""
    if guild_id not in conversation_context:
        conversation_context[guild_id] = []
    
    # Add new entry
    conversation_context[guild_id].append({
        'username': username,
        'text': text,
        'timestamp': time.time()
    })
    
    # Remove old entries
    cutoff_time = time.time() - CONTEXT_TIMEOUT
    conversation_context[guild_id] = [
        entry for entry in conversation_context[guild_id]
        if entry['timestamp'] > cutoff_time
    ]
    
    # Keep only recent entries
    if len(conversation_context[guild_id]) > CONTEXT_MAX_ENTRIES:
        conversation_context[guild_id] = conversation_context[guild_id][-CONTEXT_MAX_ENTRIES:]

def get_context_summary(guild_id: int) -> str:
    """Get a summary of recent conversation context."""
    if guild_id not in conversation_context or not conversation_context[guild_id]:
        return ""
    
    context_lines = []
    for entry in conversation_context[guild_id][-5:]:  # Last 5 entries
        context_lines.append(f"{entry['username']}: {entry['text']}")
    
    return "\n".join(context_lines)

def is_addressing_bot(text: str) -> bool:
    """Check if the transcribed text is addressing the bot."""
    if not text:
        return False
    
    text_lower = text.lower()
    
    # Check for specific bot names (not just "golfo" alone)
    for trigger in BOT_TRIGGER_NAMES:
        if trigger in text_lower:
            return True
    
    # Check for "golfo" + attention word combination (e.g., "oye golfo", "hey golfo")
    # This distinguishes "Golfo [the bot]" from "Golfo de México [the server]"
    if 'golfo' in text_lower:
        for attention in ATTENTION_WORDS:
            if attention in text_lower:
                return True
    
    # Check for questions directed at bot (attention word + question)
    question_words = ['qué', 'que', 'cómo', 'como', 'cuál', 'cual', 'dónde', 'donde', 
                     'cuándo', 'cuando', 'por qué', 'porque', 'quién', 'quien']
    
    has_attention = any(attention in text_lower for attention in ATTENTION_WORDS)
    has_question = any(q in text_lower for q in question_words)
    
    # If it starts with attention word AND has a question AND is short (< 20 words)
    words = text_lower.split()
    if has_attention and has_question and len(words) <= 20:
        return True
    
    return False


class VoiceListener(voice_recv.VoiceRecvClient):
    """Voice client that can receive and process audio."""
    
    def __init__(self, client, channel):
        super().__init__(client, channel)
        # Set reconnect to True to automatically handle disconnections
        self.reconnect = True
        logger.info(f"VoiceListener initialized for channel {channel.id}")
        
    async def on_voice_member_packet(self, member, packet):
        """Called when audio packet is received from a member."""
        
        # Log first packet received to confirm voice is working
        if not hasattr(self, '_first_packet_logged'):
            self._first_packet_logged = True
            logger.info(f"🎙️ First voice packet received from {member.name if member else 'unknown'}")
        
        logger.debug(f"Received packet from {member.name if member else 'unknown'}")
        
        if not member or member.bot:
            return
        
        # Skip malformed packets (ssrc=0 packets from Discord)
        if hasattr(packet, 'ssrc') and packet.ssrc == 0:
            return
            
        guild_id = self.guild.id
        
        # Skip packets received during grace period after reconnection (stale buffered packets)
        if guild_id in voice_reconnect_time:
            time_since_reconnect = time.time() - voice_reconnect_time[guild_id]
            if time_since_reconnect < RECONNECT_GRACE_PERIOD:
                logger.debug(f"Ignoring stale packet from {member.name} during reconnect grace period ({time_since_reconnect:.1f}s)")
                return
        
        # Skip processing if bot is currently speaking (prevents Silk codec crash)
        if guild_id in bot_is_speaking:
            logger.debug(f"Bot is speaking in guild {guild_id}, skipping packet processing")
            return
        
        user_id = member.id
        key = (guild_id, user_id)
        
        # Track voice packet activity for health monitoring
        last_voice_packet_time[guild_id] = time.time()
        
        logger.info(f"Processing voice packet from {member.name} (user_id={user_id})")
        
        # Initialize buffer if needed
        if key not in audio_buffers:
            audio_buffers[key] = []
            logger.info(f"Initialized audio buffer for {member.name}")
            
        # Decode opus packet to PCM
        try:
            # Since wants_opus()=False, packet.pcm should contain decoded PCM audio
            if not hasattr(packet, 'pcm') and not hasattr(packet, 'data'):
                logger.error(f"❌ Packet has no pcm or data attribute - Opus decoder may not be working!")
                return
                
            pcm_data = packet.pcm if hasattr(packet, 'pcm') else getattr(packet, 'data', None)
            
            if pcm_data is None:
                logger.error(f"❌ PCM data is None - Opus decoding failed!")
                return
                
            if len(pcm_data) == 0:
                logger.debug(f"Empty PCM data from {member.name}")
                return
                
            if pcm_data and len(pcm_data) > 0:
                # Enforce max buffer size to prevent memory overflow
                if len(audio_buffers[key]) >= MAX_AUDIO_BUFFER_PACKETS:
                    logger.warning(f"Audio buffer full for {member.name} ({MAX_AUDIO_BUFFER_PACKETS} packets), dropping oldest")
                    audio_buffers[key].pop(0)  # Remove oldest packet
                
                audio_buffers[key].append(pcm_data)
                last_speech_time[key] = time.time()
                
                if len(audio_buffers[key]) % 10 == 0:  # Log every 10 packets
                    logger.info(f"Buffered {len(audio_buffers[key])} packets from {member.name}")
                
                # Schedule processing check
                asyncio.create_task(self.check_speech_end(guild_id, user_id, member))
        except Exception as e:
            logger.error(f"Error decoding audio packet: {e}", exc_info=True)
            
    async def check_speech_end(self, guild_id, user_id, member):
        """Check if user stopped speaking and process audio."""
        await asyncio.sleep(1.2)
        
        key = (guild_id, user_id)
        if key not in last_speech_time or key in processing_speech:
            return
            
        # If no new audio in last 1.0s, process what we have
        if time.time() - last_speech_time[key] >= 1.0:
            await self.process_speech(guild_id, user_id, member)
            
    async def process_speech(self, guild_id, user_id, member):
        """Transcribe and respond to speech."""
        key = (guild_id, user_id)
        
        if key in processing_speech:
            return
            
        if key not in audio_buffers or not audio_buffers[key]:
            return
            
        processing_speech.add(key)
        
        try:
            # Get audio chunks
            chunks = audio_buffers[key]
            audio_buffers[key] = []  # Clear buffer
            
            if len(chunks) < 5:  # Too short, probably noise
                logger.debug(f"Skipping audio from {member.display_name}: only {len(chunks)} chunks (need 5+)")
                del chunks  # Explicitly free memory
                return
                
            # Combine audio (PCM is 48kHz 16-bit stereo)
            audio_bytes = b''.join(chunks)
            del chunks  # Free chunk list immediately after combining
            
            logger.info(f"Processing {len(audio_bytes)} bytes of audio from {member.display_name}")
            
            # Transcribe
            text = await self.transcribe_audio(audio_bytes)
            del audio_bytes  # Free audio data immediately after transcription
            
            if text and len(text.strip()) > 0:
                logger.info(f"Transcribed from {member.display_name}: {text}")
                
                # Add to conversation context
                add_to_context(guild_id, member.display_name, text)
                
                # Check if the bot is being addressed
                is_addressed = is_addressing_bot(text)
                
                # Random chance to reply even when not addressed
                random_reply = random.random() < RANDOM_REPLY_PROBABILITY
                
                if is_addressed:
                    logger.info(f"Bot detected it's being addressed - responding to {member.display_name}")
                    await self.respond_to_speech(text, member.display_name, guild_id, context_aware=True)
                elif random_reply:
                    logger.info(f"Bot randomly chiming in to conversation (20% chance) - responding to {member.display_name}")
                    await self.respond_to_speech(text, member.display_name, guild_id, context_aware=True)
                else:
                    logger.info(f"Bot not addressed - ignoring speech from {member.display_name}")
                
        except Exception as e:
            logger.error(f"Error processing speech: {e}", exc_info=True)
        finally:
            processing_speech.discard(key)
            if key in last_speech_time:
                del last_speech_time[key]
            
    def _transcribe_audio_sync(self, audio_bytes: bytes) -> str:
        """Synchronous transcription helper (runs in thread)."""
        import speech_recognition as sr
        
        # Create WAV file from PCM data - Discord sends 48kHz 16-bit stereo PCM
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
            wav_path = wav_file.name
            
            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(2)  # Stereo
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(48000)  # 48kHz
                wf.writeframes(audio_bytes)
        
        try:
            logger.info(f"Processing {len(audio_bytes)} bytes audio")
            
            # Transcribe with aggressive settings
            recognizer = sr.Recognizer()
            recognizer.energy_threshold = 50  # Very low threshold
            recognizer.dynamic_energy_threshold = False
            recognizer.pause_threshold = 0.5  # Shorter pauses
            
            with sr.AudioFile(wav_path) as source:
                # Don't adjust for ambient noise - sometimes makes it worse
                audio = recognizer.record(source)
                logger.info(f"Audio loaded, attempting transcription...")
                
            # Try Spanish first, then English
            try:
                text = recognizer.recognize_google(audio, language='es-MX', show_all=False)
                logger.info(f"✅ Transcribed (es-MX): {text}")
                return text
            except sr.UnknownValueError:
                logger.warning("Spanish failed, trying English...")
                try:
                    text = recognizer.recognize_google(audio, language='en-US', show_all=False)
                    logger.info(f"✅ Transcribed (en-US): {text}")
                    return text
                except sr.UnknownValueError:
                    logger.error("❌ Could not understand audio in any language")
                    raise
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            raise
        finally:
            # Cleanup
            try:
                os.remove(wav_path)
            except:
                pass
    
    async def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe audio to text (runs in executor to avoid blocking)."""
        import speech_recognition as sr
        
        try:
            # Run in thread executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._transcribe_audio_sync, audio_bytes)
            return text
            
        except sr.UnknownValueError:
            logger.warning(f"Could not understand audio (UnknownValueError)")
            return None
        except sr.RequestError as e:
            logger.error(f"Speech recognition service error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Transcription failed: {e}")
            return None
            
    async def respond_to_speech(self, text: str, username: str, guild_id: int, context_aware: bool = False):
        """Send transcribed text to LLM and speak response."""
        try:
            payload = {
                'content': text,
                'username': username,
                'user_id': str(guild_id),
                'guild_id': str(guild_id),
                'channel_id': str(self.channel.id)
            }
            
            # Add conversation context if enabled
            if context_aware:
                context = get_context_summary(guild_id)
                if context:
                    payload['context'] = context
                    logger.info(f"Including conversation context: {len(context)} chars")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{FLASK_HOST}/dev/llm_reply", json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        reply = data.get('reply', '')
                        
                        if reply:
                            logger.info(f"Speaking reply: {reply[:100]}")
                            # Speak immediately without delay
                            await tts_play(self, reply)
                    else:
                        logger.warning(f"LLM endpoint returned {resp.status}")
                        
        except Exception as e:
            logger.error(f"Error responding to speech: {e}")


async def start_voice_listening(vc):
    """Enable voice listening for the voice client."""
    if not isinstance(vc, VoiceListener):
        logger.warning("Voice client is not a VoiceListener, cannot enable listening")
        return
        
    guild_id = vc.guild.id
    
    # Check if already listening with THIS specific voice client
    if guild_id in voice_listeners and voice_listeners[guild_id].get('vc') == vc:
        logger.info(f"Already listening in guild {guild_id} with this voice client")
        return
    
    # If switching to a new voice client in same guild, clean up old listener first
    if guild_id in voice_listeners:
        logger.info(f"Switching voice client in guild {guild_id}, cleaning up old listener")
        await stop_voice_listening(guild_id)
    
    # Start listening mode with a custom sink
    try:
        # Create a simple sink that processes packets via on_voice_member_packet
        class CustomSink(voice_recv.AudioSink):
            def __init__(self, vc_instance):
                self.vc_instance = vc_instance
                self.loop = asyncio.get_event_loop()
                
            def wants_opus(self):
                return False  # We want decoded PCM
                
            def write(self, user, data):
                # Forward to VoiceListener's packet handler in the event loop
                asyncio.run_coroutine_threadsafe(
                    self.vc_instance.on_voice_member_packet(user, data),
                    self.loop
                )
                
            def cleanup(self):
                # Called when sink is stopped
                pass
        
        # Check if Opus is loaded before starting
        try:
            import discord.opus
            if not discord.opus.is_loaded():
                logger.error("❌ Opus not loaded! Voice listening will fail. Check Aptfile/nixpacks.toml")
                raise RuntimeError("Opus codec not loaded - cannot decode voice packets")
        except ImportError:
            logger.error("❌ discord.opus module not available!")
            raise
            
        sink = CustomSink(vc)
        vc.listen(sink)
        logger.info(f"✅ Started listening with CustomSink for guild {guild_id}")
        logger.info(f"✅ Opus status: loaded={discord.opus.is_loaded()}")
    except Exception as e:
        logger.error(f"❌ Failed to start listening: {e}", exc_info=True)
        raise
        
    # Mark as listening
    voice_listeners[guild_id] = {'active': True, 'vc': vc}
    logger.info(f"🎤 Voice listening enabled for guild {guild_id} - GolfoBot will now respond to speech!")


async def stop_voice_listening(guild_id: int):
    """Disable voice listening in a guild."""
    if guild_id in voice_listeners:
        del voice_listeners[guild_id]
        # Clear buffers for this guild
        keys_to_remove = [k for k in audio_buffers.keys() if k[0] == guild_id]
        for k in keys_to_remove:
            if k in audio_buffers:
                del audio_buffers[k]
            if k in last_speech_time:
                del last_speech_time[k]
            processing_speech.discard(k)
        logger.info(f"Voice listening disabled for guild {guild_id}")


async def forward_to_flask(payload: dict):
    """POST the MESSAGE_CREATE-shaped payload to the Flask dev simulate endpoint."""
    try:
        # Build the top-level shape expected by /dev/simulate_message
        # If payload is already in top-level shape, use it; otherwise extract from MESSAGE_CREATE shape
        if payload.get('content'):
            dev_payload = payload
        else:
            d = payload.get('d', {})
            dev_payload = {
                'content': d.get('content', ''),
                'username': d.get('author', {}).get('username'),
                'user_id': d.get('author', {}).get('id'),
                'guild_id': d.get('guild_id'),
                'channel_id': d.get('channel_id'),
                'mentions': d.get('mentions', [])
            }

        async with aiohttp.ClientSession() as session:
            async with session.post(DEV_SIMULATE_ENDPOINT, json=dev_payload, timeout=10) as resp:
                text = await resp.text()
                logger.info(f"Forwarded message to Flask dev endpoint, response: {resp.status} {text[:200]}")
    except Exception as e:
        logger.error(f"Error forwarding to Flask dev endpoint: {e}")


# --- Voice and Match Management State ---
# Per-guild queues for voice matches
match_queues = {}  # guild_id -> list of member objects (discord.Member)
# Track guilds where a voice connect is in progress to avoid concurrent attempts
voice_connecting = set()


def parse_team_format(text: str):
    """Parse strings like '2v2', '3v3', '2v2v2' into (team_size, num_teams, total_needed)"""
    m = re.search(r'((?:\d+v)+\d+)', text)
    if not m:
        # try simple like '2v2' anywhere
        m2 = re.search(r'(\d+)v(\d+)', text)
        if not m2:
            return None
        team_sizes = [int(m2.group(1)), int(m2.group(2))]
    else:
        nums = re.findall(r'\d+', m.group(1))
        team_sizes = [int(n) for n in nums]

    if not team_sizes:
        return None
    if not all(s == team_sizes[0] for s in team_sizes):
        return None
    team_size = team_sizes[0]
    num_teams = len(team_sizes)
    total_needed = team_size * num_teams
    return team_size, num_teams, total_needed


async def preprocess_laugh(text: str) -> str:
    """Reduce excessive laugh repetitions to sound more natural."""
    import re
    
    # Replace long laugh strings with shorter, more natural versions
    # This prevents the TTS from droning on with "jajajajajajaja..."
    
    laugh_replacements = [
        # Spanish laughs - limit to max 3-4 repetitions
        (r'\b(ja){5,}\b', 'jajaja'),      # jajajaja+ -> jajaja (3 repetitions)
        (r'\b(JA){5,}\b', 'Jajaja'),
        
        # English laughs
        (r'\b(ha){5,}\b', 'hahaha'),
        (r'\b(HA){5,}\b', 'Hahaha'),
        
        # Other variants
        (r'\b(je){5,}\b', 'jejeje'),
        (r'\b(ji){5,}\b', 'jijiji'),
    ]
    
    for pattern, replacement in laugh_replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    return text


async def tts_play(voice_client: discord.VoiceClient, text: str, lang: str = 'es-us', engine: str = None, say_voice: str = None):
    """Create TTS audio (gTTS) and play it in a connected voice client."""
    guild_id = None
    try:
        if not voice_client or not voice_client.is_connected():
            logger.warning("Voice client not connected, cannot play TTS")
            return False

        guild_id = voice_client.guild.id
        
        # Mark bot as speaking to pause voice listening (prevents Silk codec crash)
        bot_is_speaking.add(guild_id)
        logger.info(f"Bot started speaking in guild {guild_id}, pausing voice listening")

        # Preprocess text to handle laughs more naturally
        text = await preprocess_laugh(text)

        # Determine engine: runtime override 'engine' -> env VOICE_ENGINE -> default 'gtts'
        engine = (engine or os.environ.get('VOICE_ENGINE', 'gtts')).lower()
        say_voice = say_voice or os.environ.get('VOICE_SAY_VOICE', 'Eddy (Spanish (Mexico))')

        # Create initial audio file (mp3) depending on engine
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf:
            tmp_path = tf.name

        ffmpeg_exe = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')

        # Helper to generate audio with Tortoise TTS if requested. This is a best-effort
        # guarded integration: Tortoise is heavy and may not be installed. Attempt a few
        # common import patterns and functions; if any step fails, raise and let caller
        # fallback to gTTS.
        def generate_tortoise_audio(text_in: str, out_path: str, voice_name: str = None):
            try:
                import importlib
                # Try common module path
                mod = importlib.import_module('tortoise.api')
                # Preferred: class-based API
                if hasattr(mod, 'TextToSpeech'):
                    TTS = getattr(mod, 'TextToSpeech')
                    tts = TTS()
                    # Try a few method names used in different forks
                    if hasattr(tts, 'save'):
                        # save(text, out_path, voice=...)
                        tts.save(text_in, out_path, voice=voice_name)
                        return True
                    if hasattr(tts, 'tts'):
                        tts.tts(text_in, out_path, voice=voice_name)
                        return True
                    if hasattr(tts, 'generate_and_save'):
                        tts.generate_and_save(text_in, out_path, voice=voice_name)
                        return True

                # Fallback: functional API
                if hasattr(mod, 'text_to_speech'):
                    func = getattr(mod, 'text_to_speech')
                    func(text_in, out_path, voice=voice_name)
                    return True

                # Last resort: try top-level package exports
                top = importlib.import_module('tortoise')
                if hasattr(top, 'text_to_speech'):
                    top.text_to_speech(text_in, out_path, voice=voice_name)
                    return True

                raise ImportError('No supported Tortoise API found')
            except Exception as e:
                logger.warning(f'Tortoise generation failed: {e}')
                raise

        if engine == 'say' and shutil.which('say'):
            # Use macOS `say` to generate an AIFF, then convert to mp3 via ffmpeg
            aiff_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.aiff', delete=False) as ta:
                    aiff_path = ta.name
                voice_arg = []
                if say_voice:
                    voice_arg = ['-v', say_voice]
                # Create AIFF with 22050 Hz LE signed 16-bit to keep size reasonable
                say_cmd = ['say'] + voice_arg + ['-o', aiff_path, '--data-format=LEI16@22050', text]
                logger.info(f"Running say command: {' '.join(say_cmd[:6])} ...")
                subprocess.run(say_cmd, check=False)
                if ffmpeg_exe:
                    conv_cmd = [ffmpeg_exe, '-y', '-i', aiff_path, tmp_path]
                    subprocess.run(conv_cmd, check=False)
                else:
                    # If ffmpeg missing, fallback: try writing raw aiff to mp3 by renaming (best-effort)
                    shutil.copy(aiff_path, tmp_path)
            except Exception as e:
                logger.warning(f"say engine failed, falling back to gTTS: {e}")
                tts = gTTS(text=text, lang='es', tld='com.mx')
                tts.save(tmp_path)
            finally:
                try:
                    if aiff_path and os.path.exists(aiff_path):
                        os.remove(aiff_path)
                except Exception:
                    pass
        elif engine == 'tortoise':
            # Best-effort: try to generate using tortoise. If it fails, fall back to gTTS.
            try:
                generate_tortoise_audio(text, tmp_path, voice_name=os.environ.get('VOICE_TORTOISE_VOICE'))
            except Exception:
                logger.warning('Tortoise engine requested but failed; falling back to gTTS')
                tts = gTTS(text=text, lang='es', tld='com.mx')
                tts.save(tmp_path)
        elif engine == 'piper':
            # Piper TTS: local, fast, high-quality voice synthesis
            try:
                import piper
                import wave
                piper_model = os.environ.get('PIPER_MODEL', './piper_models/es_MX-ald-medium.onnx')
                if not os.path.exists(piper_model):
                    logger.warning(f'Piper model not found at {piper_model}; falling back to gTTS')
                    tts = gTTS(text=text, lang='es', tld='com.mx')
                    tts.save(tmp_path)
                else:
                    # Generate WAV file with Piper
                    wav_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tw:
                            wav_path = tw.name
                        
                        logger.info(f'Loading Piper model: {piper_model}')
                        voice = piper.PiperVoice.load(piper_model)
                        
                        # Piper's synthesize() returns an iterable of AudioChunk objects
                        # Collect audio bytes from all chunks
                        audio_chunks = []
                        for chunk in voice.synthesize(text):
                            audio_chunks.append(chunk.audio_int16_bytes)
                        
                        # Combine all audio data
                        audio_bytes = b''.join(audio_chunks)
                        logger.info(f'Piper generated {len(audio_bytes):,} bytes of audio')
                        
                        # Write as proper WAV file
                        with wave.open(wav_path, 'wb') as wav_file:
                            wav_file.setnchannels(1)  # Mono
                            wav_file.setsampwidth(2)  # 16-bit
                            wav_file.setframerate(voice.config.sample_rate)  # Use model's sample rate (typically 22050)
                            wav_file.writeframes(audio_bytes)
                        
                        # Convert WAV to MP3 if ffmpeg available
                        if ffmpeg_exe:
                            conv_cmd = [ffmpeg_exe, '-y', '-i', wav_path, tmp_path]
                            subprocess.run(conv_cmd, check=False, capture_output=True)
                            logger.info(f'Converted Piper WAV to MP3: {tmp_path}')
                        else:
                            shutil.copy(wav_path, tmp_path)
                            logger.info(f'Using Piper WAV directly (no ffmpeg): {tmp_path}')
                    finally:
                        if wav_path and os.path.exists(wav_path):
                            try:
                                os.remove(wav_path)
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(f'Piper engine failed: {e}; falling back to gTTS')
                tts = gTTS(text=text, lang='es', tld='com.mx')
                tts.save(tmp_path)
        elif engine == 'elevenlabs':
            # ElevenLabs TTS integration. Support both ELEVENLABS_API_KEY and ELEVEN_LABS_API_KEY env names.
            eleven_key = os.environ.get('ELEVENLABS_API_KEY') or os.environ.get('ELEVEN_LABS_API_KEY')
            eleven_voice = (say_voice or os.environ.get('ELEVENLABS_VOICE_ID') or os.environ.get('ELEVEN_LABS_VOICE_ID'))
            eleven_model = os.environ.get('ELEVENLABS_MODEL', 'eleven_multilingual_v1')
            if not eleven_key or not eleven_voice:
                logger.warning('ElevenLabs engine requested but API key or voice_id missing; falling back to gTTS')
                tts = gTTS(text=text, lang='es', tld='com.mx')
                tts.save(tmp_path)
            else:
                try:
                    import requests
                    url = f'https://api.elevenlabs.io/v1/text-to-speech/{eleven_voice}'
                    headers = {'xi-api-key': eleven_key, 'Content-Type': 'application/json'}
                    payload = {'text': text, 'model': eleven_model}
                    logger.info(f"Calling ElevenLabs API for text: {text[:50]}...")
                    resp = requests.post(url, json=payload, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        with open(tmp_path, 'wb') as f:
                            f.write(resp.content)
                        logger.info(f"ElevenLabs TTS successful ({len(resp.content)} bytes)")
                    else:
                        logger.error(f'❌ ElevenLabs TTS failed {resp.status_code}: {resp.text[:500]}')
                        logger.warning('Falling back to gTTS due to ElevenLabs error')
                        tts = gTTS(text=text, lang='es', tld='com.mx')
                        tts.save(tmp_path)
                except Exception as e:
                    logger.error(f'❌ Error calling ElevenLabs API: {e}; falling back to gTTS')
                    tts = gTTS(text=text, lang='es', tld='com.mx')
                    tts.save(tmp_path)
        else:
            # Default: gTTS (Google Translate TTS) with Mexican accent
            logger.info(f"Using gTTS engine with Mexican Spanish (tld=com.mx), text length: {len(text)}")
            tts = gTTS(text=text, lang='es', tld='com.mx')
            tts.save(tmp_path)
            # Verify file was created
            if os.path.exists(tmp_path):
                file_size = os.path.getsize(tmp_path)
                logger.info(f"gTTS saved to {tmp_path}, size: {file_size} bytes")
                if file_size == 0:
                    logger.error("gTTS file is 0 bytes! Regenerating...")
                    # Try again
                    tts = gTTS(text=text, lang='es', tld='com.mx')
                    tts.save(tmp_path)
                    file_size = os.path.getsize(tmp_path)
                    logger.info(f"Second attempt size: {file_size} bytes")
            else:
                logger.error(f"gTTS file was not created at {tmp_path}")

        # Apply optional voice styling via ffmpeg post-processing
        voice_style = os.environ.get('VOICE_STYLE', '').lower()
        if voice_style == 'ranchero':
            # Create a processed temp file
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf2:
                proc_path = tf2.name
            try:
                ffmpeg_exe = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
                if not ffmpeg_exe:
                    logger.warning('VOICE_STYLE=ranchero requested but ffmpeg not found; skipping style processing')
                    proc_path = tmp_path
                else:
                    # Tuned ranchero voice settings (young, playful, slightly nasal, energetic)
                    # Expose tuning via env vars:
                    # - VOICE_PITCH_MULT (default 1.06): small pitch-up for energy
                    # - VOICE_EQ_LOW_GAIN (default 1.5): subtle low boost for warmth
                    # - VOICE_EQ_MID_GAIN (default 3.0): mid boost to emphasize 'nasal' character
                    # - VOICE_EQ_HIGH_GAIN (default 1.5): high boost for presence
                    # - VOICE_ECHO_DELAY_MS (default 60): short echo to add liveliness
                    # - VOICE_ECHO_DECAY (default 0.18): echo decay
                    # Default pitch multiplier: if using 'say' or user requested male voice, use lower pitch
                    default_pitch = '1.06'
                    if engine == 'say' or os.environ.get('VOICE_MALE', '') == '1':
                        default_pitch = os.environ.get('VOICE_PITCH_MULT_MALE', '0.90')
                    pitch = float(os.environ.get('VOICE_PITCH_MULT', default_pitch))
                    atempo = max(0.75, min(1.5, 1.0 / pitch))
                    low_gain = float(os.environ.get('VOICE_EQ_LOW_GAIN', '1.5'))
                    mid_gain = float(os.environ.get('VOICE_EQ_MID_GAIN', '3.0'))
                    high_gain = float(os.environ.get('VOICE_EQ_HIGH_GAIN', '1.5'))
                    echo_delay = int(os.environ.get('VOICE_ECHO_DELAY_MS', '60'))
                    echo_decay = float(os.environ.get('VOICE_ECHO_DECAY', '0.18'))

                    # Build a multi-stage equalizer and short echo chain:
                    #  - boost around 120Hz for warmth, 800Hz-1k for nasal character, 2.5k for presence
                    #  - short echo (60ms) and light feedback for energetic room feel
                    afilter = (
                        f"asetrate=44100*{pitch},aresample=44100,atempo={atempo:.3f},"
                        f"equalizer=f=120:width_type=o:width=1:g={low_gain},"
                        f"equalizer=f=900:width_type=o:width=1.5:g={mid_gain},"
                        f"equalizer=f=2500:width_type=o:width=2:g={high_gain},"
                        f"aecho=0.08:0.08:{echo_delay}:{echo_decay}"
                    )
                    cmd = [ffmpeg_exe, '-y', '-i', tmp_path, '-af', afilter, proc_path]
                    logger.info(f"Running ffmpeg style command: {' '.join(cmd[:6])} ...")
                    subprocess.run(cmd, check=False)
            except Exception as e:
                logger.warning(f'Error applying voice style: {e}')
                proc_path = tmp_path
        else:
            proc_path = tmp_path

        # Locate ffmpeg executable and pass it to FFmpegPCMAudio for reliability
        ffmpeg_exe = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
        if not ffmpeg_exe:
            logger.warning("ffmpeg executable not found in PATH; FFmpegPCMAudio may fail")

        # Use FFmpegPCMAudio to stream the file (pass executable when available)
        if ffmpeg_exe:
            source = FFmpegPCMAudio(proc_path, executable=ffmpeg_exe)
        else:
            source = FFmpegPCMAudio(proc_path)
        # Stop previous audio if playing
        if voice_client.is_playing():
            voice_client.stop()

        voice_client.play(source)

        # Wait for playback to finish
        while voice_client.is_playing():
            await asyncio.sleep(0.2)

        try:
            # Remove intermediate files (original and processed if different)
            if proc_path and proc_path != tmp_path:
                try:
                    os.remove(proc_path)
                except Exception:
                    pass
            os.remove(tmp_path)
        except Exception:
            pass

        # Resume voice listening after TTS completes
        if guild_id:
            bot_is_speaking.discard(guild_id)
            logger.info(f"Bot finished speaking in guild {guild_id}, resuming voice listening")

        return True
    except Exception as e:
        logger.error(f"Error during TTS playback: {e}")
        # Ensure flag is cleared even on error
        if guild_id:
            bot_is_speaking.discard(guild_id)
            logger.info(f"Bot stopped speaking (error) in guild {guild_id}, resuming voice listening")
        return False


async def ensure_voice_connected(guild: discord.Guild):
    """Ensure the bot is connected to the configured PARTIDA_1_VOICE_CHANNEL_ID in the guild."""
    try:
        gid = str(guild.id)
        if gid in voice_connecting:
            # Another task is already attempting to connect; wait a short time and return existing client if present
            logger.debug(f"ensure_voice_connected: already connecting for guild {guild.id}, waiting briefly")
            await asyncio.sleep(0.5)
            for vc in client.voice_clients:
                try:
                    if vc.guild.id == guild.id and vc.is_connected():
                        logger.debug(f"ensure_voice_connected: found existing connected voice client for guild {guild.id}")
                        return vc
                except Exception:
                    logger.exception("ensure_voice_connected: error while inspecting existing voice clients")
            return None
        voice_connecting.add(gid)
        if not PARTIDA_1_VOICE_CHANNEL_ID:
            logger.warning("No PARTIDA_1_VOICE_CHANNEL_ID configured; skipping voice connect")
            try:
                voice_connecting.discard(gid)
            except Exception:
                logger.exception("ensure_voice_connected: failed to discard gid after missing PARTIDA_1_VOICE_CHANNEL_ID")
            return None
        channel = guild.get_channel(int(PARTIDA_1_VOICE_CHANNEL_ID)) or await guild.fetch_channel(int(PARTIDA_1_VOICE_CHANNEL_ID))
        if not channel:
            logger.warning(f"Configured voice channel {PARTIDA_1_VOICE_CHANNEL_ID} not found in guild {guild.id}")
            try:
                voice_connecting.discard(gid)
            except Exception:
                logger.exception("ensure_voice_connected: failed to discard gid after missing channel")
            return None
        # If already connected to the guild voice, return that client
        for vc in client.voice_clients:
            try:
                if vc.guild.id == guild.id and vc.is_connected():
                    logger.debug(f"ensure_voice_connected: returning existing voice client for guild {guild.id}")
                    try:
                        voice_connecting.discard(gid)
                    except Exception:
                        logger.exception("ensure_voice_connected: failed to discard gid when returning existing client")
                    return vc
            except Exception:
                logger.exception("ensure_voice_connected: error while checking voice client connected state")
        # Connect
        try:
            logger.info(f"ensure_voice_connected: attempting connect to channel id={channel.id} name={getattr(channel, 'name', None)} guild={guild.id}")
            vc = await channel.connect(timeout=30, cls=VoiceListener)
            logger.info(f"ensure_voice_connected: successful connection to channel {channel.id} -> vc={vc}")
            
            # Enable voice listening
            await start_voice_listening(vc)
            
            return vc
        except Exception as e:
            logger.exception(f"Error connecting to voice channel {getattr(channel, 'id', 'unknown')}: {e}")
            return None
        finally:
            try:
                voice_connecting.discard(gid)
            except Exception:
                logger.exception("ensure_voice_connected: failed to discard guild from voice_connecting set")
    except Exception as e:
        logger.exception(f"Failed to ensure voice connection for guild {locals().get('gid', 'unknown')}: {e}")
        try:
            voice_connecting.discard(gid)
        except Exception:
            logger.exception("Failed to discard guild from voice_connecting in outer exception handler")
        return None


async def create_team_voice_channels(guild: discord.Guild, num_teams: int):
    """Create temporary team voice channels and return list of channels."""
    channels = []
    try:
        for i in range(1, num_teams + 1):
            name = f"🎮 Equipo {i}"
            ch = await guild.create_voice_channel(name)
            channels.append(ch)
        return channels
    except Exception as e:
        logger.error(f"Error creating team voice channels: {e}")
        return channels


async def move_member_to_channel(member: discord.Member, channel: discord.abc.GuildChannel):
    try:
        await member.move_to(channel)
        return True
    except Exception as e:
        logger.warning(f"Failed to move {member} to {channel}: {e}")
        return False


async def voice_health_monitor():
    """Monitor voice connection health and reconnect if packets stop arriving."""
    await client.wait_until_ready()
    logger.info("Voice health monitor started")
    
    last_keepalive = {}
    last_gc = time.time()  # Track last garbage collection
    
    while not client.is_closed():
        try:
            await asyncio.sleep(VOICE_HEALTH_CHECK_INTERVAL)
            
            current_time = time.time()
            
            # Periodic garbage collection (every 5 minutes) to free memory
            if current_time - last_gc > 300:
                collected = gc.collect()
                logger.info(f"Periodic garbage collection: freed {collected} objects")
                last_gc = current_time
            
            for vc in client.voice_clients:
                if not vc.is_connected():
                    continue
                
                guild_id = vc.guild.id
                channel = vc.channel
                
                # Send periodic keepalive by updating speaking state
                last_ka = last_keepalive.get(guild_id, 0)
                if current_time - last_ka > VOICE_KEEPALIVE_INTERVAL:
                    try:
                        # Toggle speaking state to keep connection alive
                        if hasattr(vc, 'ws') and vc.ws:
                            await vc.ws.speak(False)
                            last_keepalive[guild_id] = current_time
                            logger.info(f"✓ Sent voice keepalive to {channel.name}")
                    except Exception as e:
                        logger.warning(f"Keepalive failed for {channel.name}: {e}")
                
                # Check if we've received any voice packets recently
                last_packet = last_voice_packet_time.get(guild_id, 0)
                time_since_packet = current_time - last_packet
                
                # If there are people in the channel and we haven't received packets in a while
                if len(channel.members) > 1:  # More than just the bot
                    if time_since_packet > VOICE_PACKET_TIMEOUT:
                        if guild_id not in voice_reconnect_in_progress:
                            logger.warning(f"Voice connection unhealthy in {channel.name} (no packets for {time_since_packet:.0f}s) - reconnecting...")
                            voice_reconnect_in_progress.add(guild_id)
                            
                            try:
                                # Stop listening
                                await stop_voice_listening(guild_id)
                                
                                # Force cleanup of websocket
                                if hasattr(vc, 'ws') and vc.ws:
                                    try:
                                        await vc.ws.close()
                                    except Exception as ws_err:
                                        logger.debug(f"WebSocket close error: {ws_err}")
                                
                                # Disconnect (ignore timeout errors and proceed)
                                try:
                                    await vc.disconnect(force=True)
                                except Exception as disc_err:
                                    logger.warning(f"Disconnect timed out; proceeding with reconnect: {disc_err}")
                                await asyncio.sleep(2)
                                
                                # Check if we're already reconnected (race condition with manual join)
                                existing_vc = discord.utils.get(client.voice_clients, guild=vc.guild)
                                if existing_vc and existing_vc.is_connected():
                                    logger.info(f"Already reconnected to {channel.name} (manual join?), skipping auto-reconnect")
                                    voice_reconnect_in_progress.discard(guild_id)
                                    return
                                
                                # Reconnect
                                new_vc = await channel.connect(cls=VoiceListener, reconnect=True, timeout=30)
                                
                                # Set grace period to ignore stale packets
                                voice_reconnect_time[guild_id] = time.time()
                                
                                await start_voice_listening(new_vc)
                                
                                # Reset packet timer and keepalive
                                last_voice_packet_time[guild_id] = current_time
                                last_keepalive[guild_id] = current_time
                                
                                logger.info(f"✓ Successfully reconnected to {channel.name}")
                            except Exception as e:
                                logger.error(f"❌ Failed to reconnect voice in {channel.name}: {e}", exc_info=True)
                            finally:
                                voice_reconnect_in_progress.discard(guild_id)
                
        except Exception as e:
            logger.error(f"Error in voice health monitor: {e}", exc_info=True)


@client.event
async def on_ready():
    print("=" * 80, flush=True)
    print("🎯 ON_READY EVENT TRIGGERED", flush=True)
    print("=" * 80, flush=True)
    
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    logger.info('Gateway bot ready and listening for messages')
    
    # Log Opus status with EXTRA visibility
    print("=" * 80, flush=True)
    print("🔍 CHECKING OPUS LIBRARY STATUS...", flush=True)
    print("=" * 80, flush=True)
    
    try:
        import discord.opus
        opus_loaded = discord.opus.is_loaded()
        
        status_msg = f"Opus library status: {'✅ LOADED' if opus_loaded else '❌ NOT LOADED'}"
        logger.info(status_msg)
        print(status_msg, flush=True)
        
        if not opus_loaded:
            error_msg = "⚠️ CRITICAL: Voice receiving will NOT work without Opus!"
            logger.error(error_msg)
            print(error_msg, flush=True)
            
            # Search for libopus files
            try:
                import subprocess
                import glob
                
                # Try multiple search methods
                apt_libs = glob.glob('/usr/lib/*/libopus.so*')
                print(f"Found {len(apt_libs)} libopus files in /usr/lib: {apt_libs[:3]}", flush=True)
                
                # Check if apt packages were installed
                result = subprocess.run(['dpkg', '-l'], capture_output=True, text=True, timeout=5)
                if 'libopus' in result.stdout:
                    print("✅ libopus0 package is installed via apt", flush=True)
                else:
                    print("❌ libopus0 package NOT found in dpkg", flush=True)
                    
            except Exception as find_err:
                logger.debug(f"Could not search for Opus: {find_err}")
                print(f"Search error: {find_err}", flush=True)
    except Exception as e:
        logger.error(f"Error checking Opus status: {e}")
        print(f"ERROR checking Opus: {e}", flush=True)
    except Exception as e:
        logger.error(f"Error checking Opus status: {e}")
    
    # Start a small local HTTP server for test triggers (only binds to localhost)
    try:
        asyncio.create_task(start_debug_http_server())
        asyncio.create_task(voice_health_monitor())
        logger.info('Started voice health monitor')
    except Exception as e:
        logger.warning(f'Failed to start background tasks: {e}')
    except Exception as e:
        logger.warning(f"Failed to start debug HTTP server: {e}")
    # Note: voice connection will be performed on explicit user request ("GolfoBot, únete").
    # Auto-joining on startup was removed to avoid repeated connect/disconnect behavior.

@client.event
async def on_voice_state_update(member, before, after):
    """Called when a member's voice state changes."""
    # Ignore bot's own voice state changes
    if member.bot:
        return
    
    # Check if user joined a voice channel (for greeting)
    if before.channel is None and after.channel is not None:
        # User joined a voice channel
        joined_channel = after.channel
        guild = member.guild
        
        # Check if bot is in the same voice channel
        bot_voice_client = None
        for vc in client.voice_clients:
            if vc.guild.id == guild.id and vc.channel.id == joined_channel.id:
                bot_voice_client = vc
                break
        
        if bot_voice_client:
            # Bot is in the same channel, greet the user
            greeting = f"{member.display_name}, ¡sálte!"
            logger.info(f"User {member.display_name} joined voice channel, greeting them")
            
            # Wait a moment for the user to fully connect
            await asyncio.sleep(1.0)
            
            # Speak the greeting
            try:
                await tts_play(bot_voice_client, greeting)
            except Exception as e:
                logger.error(f"Failed to greet {member.display_name}: {e}")

@client.event
async def on_message(message: discord.Message):
    # Ignore messages from the bot itself
    if message.author.bot:
        return

    content = message.content or ""
    author = message.author
    guild_id = str(message.guild.id) if message.guild else None
    channel_id = str(message.channel.id)

    logger.info(f"Received message from {author} ({author.id}) in channel {channel_id}: {content[:120]}")

    # If TEST_CHANNEL_ID is set, only act on that channel — unless the bot is mentioned
    if TEST_CHANNEL_ID and channel_id != str(TEST_CHANNEL_ID):
        # allow forwarding if the bot was explicitly mentioned by id or name
        content_lower = content.lower()
        bot_mentioned_here = any(str(m.id) == str(client.user.id) for m in message.mentions) if client.user else False
        if 'golfobot' not in content_lower and not bot_mentioned_here:
            logger.debug('Message not in TEST_CHANNEL_ID and not mentioning bot, ignoring')
            return

    # Build a MESSAGE_CREATE-shaped event to forward
    payload = {
        "t": "MESSAGE_CREATE",
        "d": {
            "id": str(message.id),
            "content": content,
            "author": {
                "id": str(author.id),
                "username": author.name,
                "global_name": author.display_name,
                "bot": False
            },
            "guild_id": guild_id,
            "channel_id": channel_id,
            "mentions": [{"id": str(m.id)} for m in message.mentions] if message.mentions else [],
            "type": 0
        }
    }

    # Forward to Flask dev simulate endpoint which will reuse the existing handlers
    asyncio.create_task(forward_to_flask(payload))

    # Voice/TTS and match management triggers
    content_lower = content.lower()
    called_name = 'golfobot'
    # If bot is called by name or mentioned, handle voice actions
    if called_name in content_lower or any(str(m.id) == str(client.user.id) for m in message.mentions):
        reply_text = None

        # Join queue trigger: 'me apunto'
        if re.search(r'\bme apunto\b', content_lower):
            q = match_queues.setdefault(str(guild_id), [])
            if author not in q:
                q.append(author)
                reply_text = f"{author.display_name}, ¡te apunté! Ahora somos {len(q)}."
            else:
                reply_text = f"{author.display_name}, ya estabas apuntado."

        # Team formation trigger: parse formats like '2v2', '3v3', '2v2v2'
        tf = parse_team_format(content_lower)
        if tf:
            team_size, num_teams, total_needed = tf
            participants = []
            q = match_queues.get(str(guild_id), [])
            if q and len(q) >= total_needed:
                participants = list(q[:total_needed])
                match_queues[str(guild_id)] = q[total_needed:]
            else:
                # fallback: use members in author's voice channel
                if author.voice and author.voice.channel:
                    members_here = [m for m in author.voice.channel.members if not m.bot]
                    participants = members_here[:total_needed]

            if not participants or len(participants) < total_needed:
                reply_text = f"Necesito {total_needed} jugadores pero solo hay {len(participants)} disponibles. Pide a más gente que diga 'me apunto'."
            else:
                import random as _rand
                _rand.shuffle(participants)
                # Create team channels
                created = await create_team_voice_channels(message.guild, num_teams)
                if not created or len(created) < num_teams:
                    reply_text = "No pude crear los canales de equipo. Revisa permisos del bot."
                else:
                    # Move players into created channels
                    for idx, ch in enumerate(created):
                        team_members = participants[idx*team_size:(idx+1)*team_size]
                        for m in team_members:
                            try:
                                await move_member_to_channel(m, ch)
                            except Exception:
                                logger.warning(f"Could not move member {m} to channel {ch}")
                    # Announce teams
                    lines = []
                    for i in range(num_teams):
                        team_slice = participants[i*team_size:(i+1)*team_size]
                        names = ', '.join([m.display_name for m in team_slice])
                        lines.append(f"Equipo {i+1}: {names}")
                    reply_text = "¡Equipos listos!\n" + "\n".join(lines)

        # If we prepared a reply, send it and attempt to TTS-speak it in voice
        if reply_text:
            try:
                await message.channel.send(reply_text)
            except Exception:
                logger.warning("Failed to send text reply in channel")

            # Try to speak: prefer existing voice client or configured channel
            vc = None
            if message.guild:
                vc = next((v for v in client.voice_clients if v.guild.id == message.guild.id), None)
                if not vc:
                    vc = await ensure_voice_connected(message.guild)
            if vc:
                await tts_play(vc, reply_text)

        # Additional quick command: ask the bot to join the test voice channel or your current voice channel
        if re.search(r'\b(únete|unete|join)\b', content_lower):
            # Check if user specified a channel ID (e.g., "únete a <#1234567890>") or channel name
            target_channel_id = TEST_VOICE_CHANNEL_ID or PARTIDA_1_VOICE_CHANNEL_ID
            target_channel_name = None
            specified_channel_id = None
            
            # Try to extract channel ID from Discord mention format <#ID>
            channel_mention_match = re.search(r'<#(\d+)>', message.content)
            if channel_mention_match:
                specified_channel_id = int(channel_mention_match.group(1))
                logger.info(f"User specified channel ID via mention: {specified_channel_id}")
            else:
                # Try to extract channel name from message
                match = re.search(r'(?:únete|unete|join)\s+(?:a\s+)?(.+)', content_lower)
                if match:
                    target_channel_name = match.group(1).strip()
                    logger.info(f"User requested to join channel: {target_channel_name}")
            
            connected_vc = None
            try:
                # If a channel ID was specified via mention, join that channel
                if specified_channel_id and message.guild:
                    ch = message.guild.get_channel(specified_channel_id)
                    if ch and isinstance(ch, discord.VoiceChannel):
                        connected_vc = next((v for v in client.voice_clients if v.guild.id == message.guild.id), None)
                        if connected_vc and connected_vc.channel.id == ch.id:
                            await message.channel.send(f"Ya estoy en {ch.name}")
                            return
                        elif connected_vc:
                            await connected_vc.disconnect()
                            
                        logger.info(f"Joining specified channel by ID: {ch.name} ({ch.id})")
                        connected_vc = await ch.connect(cls=VoiceListener)
                        await start_voice_listening(connected_vc)
                        await message.channel.send(f"Me uní al canal de voz: {ch.name}")
                        await asyncio.sleep(0.5)
                        await tts_play(connected_vc, "¡Listo, me uno a la partida!")
                        return
                    else:
                        await message.channel.send(f"No encontré ese canal de voz")
                        return
                
                # If a channel name was specified, search for it
                if target_channel_name and message.guild:
                    ch = None
                    for voice_channel in message.guild.voice_channels:
                        if target_channel_name in voice_channel.name.lower():
                            ch = voice_channel
                            logger.info(f"Found matching channel: {ch.name} (id={ch.id})")
                            break
                    
                    if ch:
                        connected_vc = next((v for v in client.voice_clients if v.guild.id == message.guild.id), None)
                        if connected_vc and connected_vc.channel.id == ch.id:
                            await message.channel.send(f"Ya estoy en {ch.name}")
                            return
                        elif connected_vc:
                            await connected_vc.disconnect()
                            
                        logger.info(f"Joining specified channel: {ch.name}")
                        connected_vc = await ch.connect(cls=VoiceListener)
                        await start_voice_listening(connected_vc)
                        await message.channel.send(f"Me uní al canal de voz: {ch.name}")
                        await asyncio.sleep(0.5)
                        await tts_play(connected_vc, "¡Listo, me uno a la partida!")
                        return
                    else:
                        await message.channel.send(f"No encontré ningún canal de voz con el nombre '{target_channel_name}'")
                        return
                
                # Otherwise, try to connect to TEST_VOICE_CHANNEL_ID first, then PARTIDA_1, then author's voice
                if target_channel_id and message.guild:
                    logger.info(f"Join command: target_channel_id={target_channel_id} guild={message.guild.id}")
                    ch = None
                    try:
                        ch = message.guild.get_channel(int(target_channel_id)) or await message.guild.fetch_channel(int(target_channel_id))
                    except Exception as e:
                        logger.warning(f"Could not fetch target channel {target_channel_id}: {e}")
                        ch = None

                    if ch and isinstance(ch, discord.VoiceChannel):
                        # log channel state and permissions
                        try:
                            me = message.guild.get_member(client.user.id)
                        except Exception:
                            me = None
                        perms = ch.permissions_for(me) if me else None
                        logger.info(f"Target channel found: id={ch.id} name={ch.name} members={len(ch.members)} perms={perms}")
                        # connect if not already
                        connected_vc = next((v for v in client.voice_clients if v.guild.id == message.guild.id), None)
                        if not connected_vc:
                            logger.info("Attempting voice connect to channel %s", ch.id)
                            try:
                                connected_vc = await ch.connect(cls=VoiceListener)
                                await start_voice_listening(connected_vc)
                                logger.info("Voice connect returned vc=%s", getattr(connected_vc, 'channel', None))
                            except Exception as e:
                                logger.exception(f"Failed to connect to configured channel {ch.id}: {e}")
                                connected_vc = None

                # If still not connected and the author is in a voice channel, join that one
                if not connected_vc and author.voice and author.voice.channel:
                    ch2 = author.voice.channel
                    logger.info(f"Fallback to author's channel id={ch2.id} name={ch2.name} members={len(ch2.members)}")
                    connected_vc = next((v for v in client.voice_clients if v.guild.id == message.guild.id), None)
                    if not connected_vc:
                        logger.info("Attempting voice connect to author's channel %s", ch2.id)
                        try:
                            connected_vc = await ch2.connect(cls=VoiceListener)
                            await start_voice_listening(connected_vc)
                            logger.info("Voice connect returned vc=%s", getattr(connected_vc, 'channel', None))
                        except Exception as e:
                            logger.exception(f"Failed to connect to author's channel {ch2.id}: {e}")
                            connected_vc = None

                if connected_vc:
                    # Double-check connection state
                    logger.info(f"Connected voice client state: is_connected={connected_vc.is_connected()} is_playing={connected_vc.is_playing()}")
                    await message.channel.send(f"Me uní al canal de voz: {connected_vc.channel.name}")
                    # Try a short TTS after a small delay to let the connection stabilise
                    await asyncio.sleep(0.5)
                    played = await tts_play(connected_vc, "¡Listo, me uno a la partida!")
                    logger.info(f"TTS play result: {played}")
                else:
                    await message.channel.send("No pude unirme a ningún canal de voz. Revisa permisos o especifica el canal de prueba en `TEST_VOICE_CHANNEL_ID`.")
            except Exception as e:
                logger.error(f"Error trying to join voice channel on command: {e}")
                try:
                    await message.channel.send("Error al intentar unirme al canal de voz: revisa los logs.")
                except Exception:
                    pass

        # Leave/disconnect command: ask the bot to leave the voice channel
        if re.search(r'\b(sal|salte|vete|leave|disconnect|desconecta)\b', content_lower):
            # Special case: ignore leave requests from specific user
            BLOCKED_USER_ID = 242461108521140244
            if str(author.id) == str(BLOCKED_USER_ID):
                try:
                    reply_text = f"¡Sálte tú {author.display_name}!"
                    await message.channel.send(reply_text)
                    logger.info(f"Ignored leave request from blocked user {author.display_name} ({author.id})")
                    # Don't speak in voice - it would interrupt bot's own speech
                except Exception as e:
                    logger.error(f"Error responding to blocked user leave request: {e}")
            else:
                try:
                    # Find voice client for this guild
                    vc = next((v for v in client.voice_clients if v.guild.id == message.guild.id), None)
                    if vc:
                        channel_name = vc.channel.name
                        # Stop voice listening
                        await stop_voice_listening(message.guild.id)
                        # Disconnect
                        await vc.disconnect()
                        await message.channel.send(f"Me salí del canal de voz: {channel_name}")
                        logger.info(f"Bot disconnected from voice channel {channel_name} in guild {message.guild.id}")
                    else:
                        await message.channel.send("No estoy en ningún canal de voz.")
                except Exception as e:
                    logger.error(f"Error trying to leave voice channel: {e}")
                    try:
                        await message.channel.send("Error al intentar salir del canal de voz.")
                    except Exception:
                        pass


def main():
    try:
        client.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Failed to run gateway bot: {e}")


async def handle_debug_join(request):
    """HTTP debug endpoint to instruct the bot to join voice and speak.

    POST JSON fields:
    - guild_id: guild numeric id
    - channel_id: optional voice channel id (if omitted uses PARTIDA_1_VOICE_CHANNEL_ID)
    - text: text to speak (optional)
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    guild_id = data.get('guild_id')
    channel_id = data.get('channel_id')
    text = data.get('text', '¡Hola desde la prueba de voz!')
    # Optional runtime overrides for TTS engine and voice (useful for testing male voices without restart)
    engine = data.get('engine')
    say_voice = data.get('say_voice')

    guild = None
    # If guild_id not provided, try to derive it from channel_id
    try:
        if not guild_id and channel_id:
            ch = await client.fetch_channel(int(channel_id))
            guild = ch.guild
            guild_id = str(guild.id)
        elif guild_id:
            guild = client.get_guild(int(guild_id))
    except Exception:
        guild = None

    if not guild:
        return web.json_response({'error': 'guild not found by bot; provide guild_id or channel_id'}, status=404)

    # Background-play scheduling: by default, schedule the connect+play to run
    # in background and return immediately with {'ok': True, 'scheduled': True}.
    # If caller sets JSON field `blocking: true`, run synchronously (legacy behavior).
    blocking = bool(data.get('blocking'))

    async def _background_connect_and_play(guild_obj, channel_id_in, text_in, engine_in, say_voice_in):
            """Attempt to connect to the provided voice channel (or configured one) with retries/backoff,
            then play the TTS when the voice client reports connected. Logs results."""
            start = time.time()
            max_wait = float(os.environ.get('VOICE_CONNECT_MAX_WAIT', '20'))
            retry_interval = float(os.environ.get('VOICE_CONNECT_RETRY_INTERVAL', '1.0'))
            played_result = False
            last_exc = None

            try:
                guild_local = guild_obj
                # Resolve guild if only id passed
                if not guild_local:
                    logger.debug("background_connect_and_play: resolving guild by id")
                    guild_local = client.get_guild(int(guild_id))

                while time.time() - start < max_wait:
                    try:
                        vc = next((v for v in client.voice_clients if v.guild.id == guild_local.id), None)
                        # If a channel id provided, prefer connecting to that channel
                        if not vc and channel_id_in:
                            try:
                                ch = guild_local.get_channel(int(channel_id_in)) or await guild_local.fetch_channel(int(channel_id_in))
                                logger.info(f"background: attempting connect to channel id={channel_id_in} name={getattr(ch,'name',None)} guild={guild_local.id}")
                                vc = await ch.connect(cls=VoiceListener)
                                await start_voice_listening(vc)
                                await asyncio.sleep(0.6)
                                vc = next((v for v in client.voice_clients if v.guild.id == guild_local.id), vc)
                            except Exception as inner_e:
                                last_exc = inner_e
                                logger.exception(f"background: connect attempt failed for channel {channel_id_in}: {inner_e}")
                                vc = None
                        # If still no vc, try ensure_voice_connected() as fallback
                        if not vc:
                            vc = await ensure_voice_connected(guild_local)

                        if vc:
                            # Wait for a short stabilization window where the client remains connected
                            stable_for = float(os.environ.get('VOICE_STABLE_SECONDS', '1.0'))
                            stable_start = None
                            check_deadline = time.time() + min(max_wait, 5.0)
                            while time.time() < check_deadline:
                                try:
                                    if getattr(vc, 'is_connected', lambda: False)():
                                        if stable_start is None:
                                            stable_start = time.time()
                                        elif time.time() - stable_start >= stable_for:
                                            logger.info(f"background: voice client stable for {stable_for}s, proceeding to TTS play")
                                            played_result = await tts_play(vc, text_in, engine=engine_in, say_voice=say_voice_in)
                                            logger.info(f"background: TTS play finished, played_result={played_result}")
                                            break
                                    else:
                                        stable_start = None
                                except Exception as e:
                                    logger.exception(f"background: error while checking vc.is_connected: {e}")
                                    stable_start = None
                                await asyncio.sleep(0.25)
                            if played_result:
                                break
                    except Exception as e:
                        last_exc = e
                        logger.exception(f"background: unexpected error during connect/play attempt: {e}")

                    # Wait and retry
                    await asyncio.sleep(retry_interval)

                if not played_result:
                    logger.warning(f"background: failed to play after {time.time()-start:.1f}s; last_exc={last_exc}")
            except Exception as e:
                logger.exception(f"background: fatal error in background_connect_and_play: {e}")

    # If blocking requested, run the old synchronous flow
    if blocking:
        # run legacy synchronous behavior: attempt to connect immediately and play
        try:
            vc = None
            if channel_id:
                ch = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
                logger.info(f"handle_debug_join (blocking): fetched channel for id={channel_id}: {ch} (type={type(ch)})")
                if ch and isinstance(ch, discord.VoiceChannel):
                    try:
                        vc = await ch.connect(cls=VoiceListener)
                        await start_voice_listening(vc)
                        await asyncio.sleep(0.6)
                        vc = next((v for v in client.voice_clients if v.guild.id == guild.id), vc)
                    except Exception as e:
                        logger.exception(f"handle_debug_join (blocking): failed to connect to channel {getattr(ch,'id',None)}: {e}")
            else:
                vc = await ensure_voice_connected(guild)

            if not vc or not getattr(vc, 'is_connected', lambda: False)():
                logger.warning('handle_debug_join (blocking): voice client not connected; returning played:false')
                return web.json_response({'ok': True, 'played': False})

            played = await tts_play(vc, text, engine=engine, say_voice=say_voice)
            return web.json_response({'ok': True, 'played': bool(played)})
        except Exception as e:
            logger.exception(f"Debug join error (blocking): {e}")
            return web.json_response({'error': str(e)}, status=500)

    # Non-blocking: schedule background connect+play and return immediately
    try:
        asyncio.create_task(_background_connect_and_play(guild, channel_id, text, engine, say_voice))
        logger.info('handle_debug_join: scheduled background connect+play task')
        return web.json_response({'ok': True, 'scheduled': True})
    except Exception as e:
        logger.exception(f"Failed to schedule background connect+play: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def _ensure_voices_dirs():
    base = Path.cwd() / 'voices'
    cache = Path.cwd() / 'voices_cache'
    base.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    return base, cache


async def handle_voices_list(request):
    """List available uploaded voice sample directories."""
    base, _ = await _ensure_voices_dirs()
    voices = [p.name for p in base.iterdir() if p.is_dir()]
    return web.json_response({'voices': voices})


async def handle_voices_upload(request):
    """Upload sample files for a named voice. multipart/form-data with 'voice_name' and files in 'file'."""
    data = await request.post()
    voice_name = data.get('voice_name') or data.get('name')
    if not voice_name:
        return web.json_response({'error': 'missing voice_name'}, status=400)

    base, _ = await _ensure_voices_dirs()
    dest_dir = base / voice_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for key, field in data.items():
        # field may be a FileField for uploaded files
        if hasattr(field, 'filename') and field.filename:
            filename = Path(field.filename).name
            out_path = dest_dir / filename
            try:
                # field.file is a file-like object
                field.file.seek(0)
                with open(out_path, 'wb') as f:
                    f.write(field.file.read())
                saved.append(str(out_path.name))
            except Exception as e:
                logger.warning(f"Failed to save uploaded file {filename}: {e}")
    return web.json_response({'ok': True, 'saved': saved})


async def _convert_with_vc(input_path: str, voice_name: str, cache_dir: Path, converter_url: str = None):
    """Call a local VC converter server to convert `input_path` into target voice. Returns path to converted file.
    Expects the converter URL to accept multipart POST with field 'file' and param 'voice'.
    Falls back by returning input_path if converter not available or fails.
    """
    if not converter_url:
        return input_path

    # Build a cache key from file contents + voice_name
    h = hashlib.sha256()
    try:
        with open(input_path, 'rb') as f:
            h.update(f.read())
    except Exception:
        return input_path
    h.update(voice_name.encode('utf-8') if voice_name else b'')
    key = h.hexdigest()
    out_dir = cache_dir / voice_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{key}.mp3"
    if out_path.exists():
        return str(out_path)

    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            with open(input_path, 'rb') as fh:
                data = aiohttp.FormData()
                data.add_field('file', fh, filename=Path(input_path).name, content_type='audio/mpeg')
                if voice_name:
                    data.add_field('voice', voice_name)
                async with sess.post(converter_url, data=data) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(out_path, 'wb') as out_f:
                            out_f.write(content)
                        return str(out_path)
                    else:
                        logger.warning(f"VC converter returned status {resp.status}")
                        return input_path
    except Exception as e:
        logger.warning(f"Error calling VC converter at {converter_url}: {e}")
        return input_path


async def handle_voices_preview(request):
    """Generate a preview: synthesize text, optionally convert via VC, apply ranchero styling and return MP3 bytes.
    POST JSON: {voice_name, text, engine}
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({'error': 'invalid json'}, status=400)

    voice_name = data.get('voice_name')
    text = data.get('text') or data.get('prompt') or 'Hola'
    engine = data.get('engine')

    base, cache = await _ensure_voices_dirs()

    # Generate base TTS using existing tts_play logic but write to file instead
    # We'll reuse the earlier flow: generate tmp mp3 via gTTS/say/tortoise
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf:
        tmp_path = tf.name

    # Generate initial audio via same engines used in tts_play
    # For brevity reuse synchronous calls similar to tts_play
    try:
        if engine == 'say' and shutil.which('say'):
            aiff_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.aiff', delete=False) as ta:
                    aiff_path = ta.name
                voice_arg = []
                if voice_name:
                    voice_arg = ['-v', voice_name]
                say_cmd = ['say'] + voice_arg + ['-o', aiff_path, '--data-format=LEI16@22050', text]
                subprocess.run(say_cmd, check=False)
                ffmpeg_exe = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
                if ffmpeg_exe:
                    subprocess.run([ffmpeg_exe, '-y', '-i', aiff_path, tmp_path], check=False)
                else:
                    shutil.copy(aiff_path, tmp_path)
            finally:
                try:
                    if aiff_path and os.path.exists(aiff_path):
                        os.remove(aiff_path)
                except Exception:
                    pass
        elif engine == 'tortoise':
            try:
                # Attempt the guarded tortoise helper
                generate_tortoise_audio(text, tmp_path, voice_name=os.environ.get('VOICE_TORTOISE_VOICE'))
            except Exception:
                tts = gTTS(text=text, lang='es-us')
                tts.save(tmp_path)
        else:
            tts = gTTS(text=text, lang='es-us')
            tts.save(tmp_path)

        # Optionally convert via VC
        converter_url = os.environ.get('VOICE_CONVERTER_URL')
        converted = await _convert_with_vc(tmp_path, voice_name or 'default', cache, converter_url)

        # Optionally apply ranchero style (reuse same filter chain)
        # For preview we will run ffmpeg filter if configured
        voice_style = os.environ.get('VOICE_STYLE', '').lower()
        final_path = converted
        if voice_style == 'ranchero' and shutil.which('ffmpeg'):
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf2:
                proc_path = tf2.name
            ffmpeg_exe = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
            # Simple chain reusing defaults
            pitch = float(os.environ.get('VOICE_PITCH_MULT', '1.06'))
            atempo = max(0.75, min(1.5, 1.0 / pitch))
            low_gain = float(os.environ.get('VOICE_EQ_LOW_GAIN', '1.5'))
            mid_gain = float(os.environ.get('VOICE_EQ_MID_GAIN', '3.0'))
            high_gain = float(os.environ.get('VOICE_EQ_HIGH_GAIN', '1.5'))
            echo_delay = int(os.environ.get('VOICE_ECHO_DELAY_MS', '60'))
            echo_decay = float(os.environ.get('VOICE_ECHO_DECAY', '0.18'))
            afilter = (
                f"asetrate=44100*{pitch},aresample=44100,atempo={atempo:.3f},"
                f"equalizer=f=120:width_type=o:width=1:g={low_gain},"
                f"equalizer=f=900:width_type=o:width=1.5:g={mid_gain},"
                f"equalizer=f=2500:width_type=o:width=2:g={high_gain},"
                f"aecho=0.08:0.08:{echo_delay}:{echo_decay}"
            )
            subprocess.run([ffmpeg_exe, '-y', '-i', converted, '-af', afilter, proc_path], check=False)
            final_path = proc_path

        # Return file bytes
        headers = {'Content-Type': 'audio/mpeg'}
        body = None
        with open(final_path, 'rb') as f:
            body = f.read()

        # Cleanup temporary files
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

        return web.Response(body=body, headers=headers)
    except Exception as e:
        logger.error(f"Voice preview failed: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def handle_status(request):
    """Status endpoint to check bot and Opus health."""
    try:
        import discord.opus
        opus_loaded = discord.opus.is_loaded()
    except:
        opus_loaded = False
    
    status = {
        "bot_ready": client.is_ready() if client else False,
        "opus_loaded": opus_loaded,
        "voice_clients": len(client.voice_clients) if client else 0,
        "guilds": len(client.guilds) if client and client.guilds else 0,
        "voice_listeners": len(voice_listeners)
    }
    
    return web.json_response(status)


async def start_debug_http_server(host='127.0.0.1', port=8765):
    app = web.Application()
    app.router.add_post('/debug/join', handle_debug_join)
    app.router.add_get('/status', handle_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"Debug HTTP server started on http://{host}:{port}")


if __name__ == '__main__':
    main()
