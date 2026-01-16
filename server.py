from flask import Flask, request, jsonify
import requests
import threading
import os
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import hmac
import hashlib
import random
import re

# Use backports.zoneinfo for Python 3.8 compatibility
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
load_dotenv()

# Optional official Google client for Generative AI (used if installed)
try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None

# For Discord signature verification
def verify_discord_signature(public_key, signature, timestamp, body):
    """Verify Discord's request signature using Ed25519
    
    Args:
        public_key: DISCORD_PUBLIC_KEY from env (hex string for Ed25519 public key)
        signature: X-Signature-Ed25519 header (hex string)
        timestamp: X-Signature-Timestamp header
        body: Raw request body bytes
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not public_key or not signature or not timestamp:
        logger.warning("Missing signature components")
        return False
    
    try:
        # Construct the message Discord signed (timestamp + body)
        message = timestamp.encode() + body

        # Convert hex strings to bytes
        pk_bytes = bytes.fromhex(public_key)
        sig_bytes = bytes.fromhex(signature)

        # Try ed25519 module first (if available)
        try:
            import ed25519
            vk = ed25519.VerifyingKey(pk_bytes)
            vk.verify(sig_bytes, message)
            logger.debug("Discord signature verified successfully (ed25519)")
            return True
        except ImportError:
            # ed25519 not installed; try PyNaCl
            pass
        except Exception as e:
            logger.warning(f"ed25519 verification failed: {e}")

        # Fallback to PyNaCl (nacl.signing)
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            vk = VerifyKey(pk_bytes)
            # Verify detached signature: VerifyKey.verify(message, signature)
            vk.verify(message, sig_bytes)
            logger.debug("Discord signature verified successfully (PyNaCl)")
            return True
        except ImportError:
            logger.warning("Neither 'ed25519' nor 'PyNaCl' are installed for signature verification")
            return False
        except BadSignatureError as bse:
            logger.warning(f"PyNaCl signature verification failed: {bse}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error during signature verification: {e}")
            return False

    except Exception as e:
        logger.warning(f"Discord signature verification failed: {e}")
        return False


def verify_key_decorator(public_key):
    """Decorator to verify Discord request signatures on the /interactions endpoint."""
    def decorator(f):
        def wrapper(*args, **kwargs):
            # Get headers from Flask request
            signature = request.headers.get('X-Signature-Ed25519')
            timestamp = request.headers.get('X-Signature-Timestamp')
            
            # Get raw body
            body = request.get_data()
            
            # Verify signature
            valid = verify_discord_signature(public_key, signature, timestamp, body)
            if not valid:
                # Log useful debugging info (do not log entire body in production)
                body_preview = body[:1024] if body else b''
                try:
                    body_preview_text = body_preview.decode('utf-8', errors='replace')
                except Exception:
                    body_preview_text = str(body_preview)

                logger.warning("Invalid Discord signature detected; rejecting request")
                logger.debug("Signature header: %s", signature)
                logger.debug("Timestamp header: %s", timestamp)
                logger.debug("Request body (preview up to 1024 bytes): %s", body_preview_text)
                return jsonify({"error": "Invalid signature"}), 401
            
            return f(*args, **kwargs)
        
        wrapper.__name__ = f.__name__
        return wrapper
    
    return decorator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
DISCORD_PUBLIC_KEY = os.environ.get('DISCORD_PUBLIC_KEY')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISCORD_APP_ID = os.environ.get('DISCORD_APP_ID')
DISCORD_CHANNEL_ID = os.environ.get('DISCORD_CHANNEL_ID')

# Test channel for development and chat interactions
TEST_CHANNEL_ID = os.environ.get('TEST_CHANNEL_ID')

# Announcement channel (user-provided). This is where Gemini-generated announcements will be posted.
# Falls back to DISCORD_CHANNEL_ID if not provided.
ANNOUNCE_CHANNEL_ID = os.environ.get('ANNOUNCE_CHANNEL_ID')

# Gemini / Google Generative API configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
# Model name: defaults to 'gemini-2.5-flash' (latest, works with v1beta1 endpoint)
# For other models, use 'text-bison-001' (v1beta2), 'gemini-pro' (v1beta1), or 'gemini-1.5-pro' (v1beta1)
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

# Groq API configuration
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')  # Latest Llama model

# Note: we'll call Gemini (Google Generative API) via REST using an API key.
# The GEMINI_API_KEY environment variable must be set to a valid API key.

# Button configuration - customize your button responses here
BUTTON_CONFIGS = {
    "revo_yes": {
        "prompt": "The user clicked YES on the revocation button. Generate a friendly confirmation message explaining that their revocation has been processed.",
        "acknowledgment": "Procesando tu respuesta... ✅",
        "include_user_mention": True
    },
    "revo_no": {
        "prompt": "The user clicked NO on the revocation button. Generate a friendly message acknowledging that they chose not to proceed with the revocation.",
        "acknowledgment": "Understood. Canceling revocation... ❌",
        "include_user_mention": True
    }
}


def get_button_config(custom_id):
    """Get configuration for a specific button, with fallback to default"""
    return BUTTON_CONFIGS.get(custom_id, {
        "prompt": f"The user clicked a button with ID: {custom_id}. Generate an appropriate response.",
        "acknowledgment": "Processing your request... ⏳",
        "include_user_mention": False
    })


# ===== MEXICAN PERSONA & HUMOR UTILITIES =====

def get_mexican_greeting():
    """Return a random charismatic Mexican greeting"""
    greetings = [
        "¿Qué pasó mi rey/reina? 😎🌵",
        "¡Ey, compa! ¿A qué se debe el honor? 🌶️",
        "¡Órale! Habla, ¿qué se ofrece? 🎉",
        "¿Qué me cuentas, jefe? 💪",
        "¡Ay, mi lindo! ¿Me necesitabas? 🤠",
    ]
    return random.choice(greetings)


def get_team_formation_response(team_format):
    """Return a charismatic response when organizing teams"""
    responses = {
        "default": [
            f"Arre, compas. Déjenme los mezclo como si fueran carne pa' las carnitas… ¡Equipos listos! 🍖",
            f"Ya está, banda. Cada quien pa' su rancho. No se me pierdan. 🤠",
            f"¡Listo mi gente! Ya armé los equipos con más precisión que un jugador de póker en Las Vegas. 🎰",
            f"Compárenme a un chef mexicano, porque acabo de preparar unos equipos bien sabrosos. 👨‍🍳",
            f"¡Arre! Equipos armados como aguachiles — bien picosos y balanceados. 🌶️",
        ]
    }
    available = responses.get("default", [])
    return random.choice(available) if available else "¡Equipos listos, jefas!"


def get_moving_to_channels_response():
    """Return a charismatic response when moving users to voice channels"""
    responses = [
        "Ya está, banda. Cada quien pa' su rancho. No se me pierdan. 🎮",
        "¡Órale! Ya los acomodé en sus canales. Que gane el mejor. 💪",
        "Listo, compas. Mándenme los highlights después, ¿eh? 🎬",
        "¡Ezo! Ya están en sus equipos. Ahora, a darle candela. 🔥",
        "Cada quien con su escuadra. ¡Que empiece la batalla! ⚔️",
    ]
    return random.choice(responses)


def get_error_response_persona():
    """Return a humorous error response in persona"""
    responses = [
        "¡Ay, hermano! Me atascaste. Dame detalles claros, ¿sí? 🤔",
        "Órale, necesito que me expliques bien de dónde se supone que debo agarrar gente. 🧐",
        "Mi rey, algo no cuadra aquí. ¿Me das más info, porfa? 🤨",
        "¡Ey, jefe! Creo que algo se perdió en la traducción. Cuéntame de nuevo. 📱",
    ]
    return random.choice(responses)


# ===== MEAN-MESSAGE DETECTION & ROASTING =====
def is_mean_message(text):
    """Basic heuristic to detect mean/insulting messages.

    This is intentionally conservative: it looks for common insults or
    profanity patterns. It returns True when the message appears to be
    abusive/mean but not when it contains explicit self-harm or violent
    threats (these are handled separately and will not be roasted).
    """
    if not text:
        return False

    lower = text.lower()

    # Patterns that indicate self-harm or explicit violent instructions.
    # If present, do NOT roast — these should be handled differently.
    dangerous_patterns = [
        "kill yourself", "kys", "muérete", "muerete", "mátate", "matate"
    ]
    for p in dangerous_patterns:
        if p in lower:
            return False

    # Conservative insult/profanity tokens (English + common Spanish variants)
    mean_tokens = [
        "idiot", "stupid", "stfu", "shut up", "fuck", "fucking", "bitch",
        "noob", "n00b", "trash", "sucks", "suck", "loser", "troll",
        "pendejo", "cabron", "culero", "puta"
    ]

    # Check token presence
    for tok in mean_tokens:
        if tok in lower:
            return True

    # Heuristic: many repeated punctuation or ALL CAPS often signal aggression
    if lower != text and sum(1 for c in text if c.isupper()) > max(10, len(text) // 3):
        return True

    if text.count("!") >= 4 or text.count("?") >= 4:
        return True

    return False


def get_roast_response(message_text, username=None):
    """Generate a short, spicy roast in Spanish aimed at the author.

    Preferred method: call the LLM (Gemini) to craft a playful roast. If
    the LLM fails, fall back to a local template-based roast.
    The roast must avoid slurs, threats, and protected-class attacks.
    """
    mention = f"<@{username}>" if username and username.isdigit() else (username or "compa")

    # LLM prompt: keep it short, snarky, non-violent, no slurs
    prompt = (
        "Eres GolfoBot, una personalidad mexicana divertida y pícar a. "
        "La siguiente frase es un mensaje agresivo o grosero: \"" + message_text + "\". "
        "Responde con una réplica corta en español (máximo 2 frases) que sea un 'roast' ingenioso, "
        "con chispa y tono de burla amistosa. No uses insultos que ataquen grupos protegidos, "
        "no incites violencia ni amenazas, y evita lenguaje sexual explícito o palabras de odio. "
        "Si es posible, menciona al autor de forma juguetona (por ejemplo usando su nombre o 'compa'). "
        "Devuelve solo el texto de la réplica, sin explicaciones adicionales."
    )

    try:
        logger.info("Generating roast via LLM for message: %s", message_text[:120])
        roast = call_llm(prompt, max_tokens=120)
        if roast and isinstance(roast, str) and roast.strip():
            return roast.strip()
    except Exception as e:
        logger.warning("LLM roast generation failed: %s", e)

    # Fallback local roast templates (keep them playful, not hateful)
    fallbacks = [
        f"{mention}, ¿en serio? Me recuerda a cuando intentas hacer algo y terminas pidiendo tutoriales. 😏",
        f"¡Ay {mention}! Te escuché... pero mi abuela cocina mejor argumentos que tú. 😂",
        f"{mention}, tranquilo, que la vida no es un torneo y aún así pierdes la liga. 🤝",
        f"Hermano {mention}, baja dos rayitas — que aquí venimos a jugar, no a abrir heridas. 😅",
        f"{mention}, tu comentario tiene menos impacto que una notificación sin sonido. 🔕",
    ]
    return random.choice(fallbacks)

# ===== END MEAN-MESSAGE DETECTION & ROASTING =====


# ===== DANGEROUS MESSAGE DETECTION & MOD MENTION =====
def is_dangerous_message(text):
    """Detect messages that include self-harm instructions or severe threats.

    Returns True for messages that require moderator attention and should not
    be roasted. This includes phrases encouraging self-harm or explicit
    instructions to kill/harm someone.
    """
    if not text:
        return False
    lower = text.lower()

    dangerous_patterns = [
        "kill yourself", "kys", "muérete", "muerete", "mátate", "matate",
        "i will kill", "te voy a matar", "voy a matarte", "voy a matarlos"
    ]
    for p in dangerous_patterns:
        if p in lower:
            return True
    return False


def get_moderator_mentions():
    """Return a string with moderator role mentions from env vars.

    Looks for `GRAN_LIDER_ROLE_ID` and `GENERAL_ROLE_ID` environment variables.
    Only include roles that are set.
    """
    mentions = []
    gran = os.environ.get('GRAN_LIDER_ROLE_ID')
    general = os.environ.get('GENERAL_ROLE_ID')
    if gran:
        mentions.append(f"<@&{gran}>")
    if general:
        mentions.append(f"<@&{general}>")
    return " ".join(mentions)

# ===== END DANGEROUS MESSAGE DETECTION & MOD MENTION =====



# ===== TEAM ORGANIZATION LOGIC =====

def parse_team_format(text):
    """Parse team format from text (e.g., '2v2', '3v3', '2v2v2v2')
    
    Returns:
        tuple: (team_size, num_teams) or None if invalid
        Example: '2v2' → (2, 2), '3v3' → (3, 2), '2v2v2v2' → (2, 4)
    """
    # Match patterns like "2v2", "3v3", "2v2v2v2", etc.
    match = re.search(r'(\d+)v(\d+)(?:v\d+)*', text, re.IGNORECASE)
    if not match:
        return None
    
    # Extract all team sizes: "2v2v2v2" → [2, 2, 2, 2]
    team_sizes = re.findall(r'\d+', match.group(0))
    team_sizes = [int(x) for x in team_sizes]
    
    # Check if all teams are same size
    if not all(s == team_sizes[0] for s in team_sizes):
        logger.warning(f"Uneven teams in format: {match.group(0)}")
        return None
    
    team_size = team_sizes[0]
    num_teams = len(team_sizes)
    total_players_needed = team_size * num_teams
    
    return team_size, num_teams, total_players_needed


def get_voice_channel_members(guild_id):
    """Get list of users currently in voice channels in a guild
    
    Returns:
        list: List of dicts with {'user_id': str, 'username': str, 'voice_channel_id': str}
    """
    try:
        # Fetch guild information to get voice channels
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Get guild channels
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/channels",
            headers=headers,
            timeout=10
        )
        
        if resp.status_code != 200:
            logger.error(f"Failed to fetch guild channels: {resp.status_code}")
            return []
        
        channels = resp.json()
        voice_channels = [ch for ch in channels if ch.get('type') == 2]  # type 2 = voice
        
        members_in_voice = []
        for voice_ch in voice_channels:
            channel_id = voice_ch.get('id')
            # Try to get channel details (includes voice state data in newer API)
            # For now, we'll need to use a different approach or get guild members
            pass
        
        # Get guild members who are in voice
        # This is a simplified approach; in production, you'd use Discord.py or fetch from guild
        resp_members = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/members?limit=1000",
            headers=headers,
            timeout=10
        )
        
        if resp_members.status_code != 200:
            logger.error(f"Failed to fetch guild members: {resp_members.status_code}")
            return []
        
        # Note: REST API doesn't directly expose which members are in voice.
        # This would require a Discord.py bot or Gateway connection.
        # For now, return empty and note this limitation.
        logger.warning("Voice member detection requires Discord.py or Gateway connection")
        return []
        
    except Exception as e:
        logger.error(f"Error fetching voice channel members: {e}")
        return []


def create_or_get_team_channels(guild_id, num_teams, base_channel_id=None):
    """Create or reuse voice channels for teams
    
    Returns:
        list: List of channel IDs for each team
    """
    try:
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Get or create category for team channels
        category_name = "🏆 Team Channels"
        
        # Fetch guild channels
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/channels",
            headers=headers,
            timeout=10
        )
        
        if resp.status_code != 200:
            logger.error(f"Failed to fetch channels: {resp.status_code}")
            return []
        
        channels = resp.json()
        
        # Look for existing category or voice channels
        team_channels = []
        for i in range(1, num_teams + 1):
            ch_name = f"🎮 Equipo {i}"
            existing = next((ch for ch in channels if ch.get('name') == ch_name and ch.get('type') == 2), None)
            if existing:
                team_channels.append(existing['id'])
                logger.info(f"Using existing team channel: {ch_name} ({existing['id']})")
            else:
                # Create new channel
                create_resp = requests.post(
                    f"https://discord.com/api/v10/guilds/{guild_id}/channels",
                    headers=headers,
                    json={
                        "name": ch_name,
                        "type": 2,  # Voice channel
                        "position": i - 1
                    },
                    timeout=10
                )
                if create_resp.status_code in (200, 201):
                    new_ch = create_resp.json()
                    team_channels.append(new_ch['id'])
                    logger.info(f"Created new team channel: {ch_name} ({new_ch['id']})")
                else:
                    logger.error(f"Failed to create team channel {ch_name}: {create_resp.status_code}")
        
        return team_channels
        
    except Exception as e:
        logger.error(f"Error creating/getting team channels: {e}")
        return []


def move_user_to_channel(user_id, guild_id, channel_id):
    """Move a user from one voice channel to another
    
    Note: Requires user to be in a voice channel already
    """
    try:
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        
        resp = requests.patch(
            f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}",
            headers=headers,
            json={"channel_id": channel_id},
            timeout=10
        )
        
        if resp.status_code == 204:
            logger.info(f"Moved user {user_id} to channel {channel_id}")
            return True
        else:
            logger.warning(f"Failed to move user {user_id} to channel {channel_id}: {resp.status_code} - {resp.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error moving user to channel: {e}")
        return False


# ===== END TEAM ORGANIZATION LOGIC =====

def call_llm(prompt, max_tokens=1000):
    """Call LLM API - prefers Groq if available, falls back to Gemini.
    
    Args:
        prompt: The text prompt to send to the LLM
        max_tokens: Maximum tokens in the response
    
    Returns:
        str: The generated text response
    """
    logger.debug(f"call_llm: GROQ_API_KEY={'set' if GROQ_API_KEY else 'not set'}, GEMINI_API_KEY={'set' if GEMINI_API_KEY else 'not set'}")
    
    # Try Groq first (faster and more generous free tier)
    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content']
            else:
                logger.warning(f"Groq API returned {response.status_code}: {response.text}")
                # Fall through to Gemini
        except Exception as e:
            logger.warning(f"Groq API error, falling back to Gemini: {e}")
            # Fall through to Gemini
    
    # Fallback to Gemini
    if not GEMINI_API_KEY:
        raise RuntimeError("No LLM API key configured (GROQ_API_KEY or GEMINI_API_KEY)")

    # Try using the official client if installed
    try:
        if genai is None:
            import google.generativeai as genai_local  # type: ignore
        else:
            genai_local = genai

        # Configure client
        try:
            genai_local.configure(api_key=GEMINI_API_KEY)
        except Exception:
            pass

        model = genai_local.GenerativeModel(GEMINI_MODEL)
        # Call generate_content using the client version's default signature.
        # Older/newer client versions may accept different kwargs; keep call minimal for compatibility.
        response = model.generate_content([prompt])

        # Extract text from response in flexible ways
        candidates = None
        if isinstance(response, dict):
            candidates = response.get('candidates')
        else:
            candidates = getattr(response, 'candidates', None)

        if candidates:
            first = candidates[0]
            # dict-like
            if isinstance(first, dict):
                content = first.get('content') or {}
                parts = content.get('parts') or []
                if parts:
                    part0 = parts[0]
                    if isinstance(part0, dict):
                        return part0.get('text') or str(part0)
                    else:
                        return getattr(part0, 'text', str(part0))
            else:
                # object-like
                content = getattr(first, 'content', None)
                parts = getattr(content, 'parts', None)
                if parts and len(parts) > 0:
                    part0 = parts[0]
                    return getattr(part0, 'text', str(part0))

        # Fallback to response.text or str(response)
        if isinstance(response, dict) and 'text' in response:
            return response['text']
        if hasattr(response, 'text'):
            return response.text

        return str(response)

    except Exception as e:
        logger.error(f"LLM (google.generativeai) error: {e}")
        # Surface the underlying error to callers so they can fallback as needed
        raise


def post_to_discord(channel_id, content, embeds=None, components=None):
    """Post a message to Discord with error handling"""
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {"content": content}
    if embeds:
        payload["embeds"] = embeds
    # components for interactive buttons, action rows, etc.
    # Example structure for buttons:
    # components=[{"type":1,"components":[{"type":2,"style":3,"label":"Yes","custom_id":"revo_yes"}, ...]}]
    if components:
        payload["components"] = components
    
    response = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers=headers,
        json=payload,
        timeout=10
    )
    
    # Discord returns 200 or 201 for created messages depending on endpoint/version
    if response.status_code in (200, 201):
        logger.info(f"Successfully posted message to Discord channel {channel_id}")
        return True
    else:
        logger.error(f"Failed to post to Discord: {response.status_code} - {response.text}")
        return False


def update_interaction_message(interaction_token, content):
    """Update the original interaction message (the ephemeral one)"""
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {"content": content}
    
    response = requests.patch(
        f"https://discord.com/api/v10/webhooks/{DISCORD_APP_ID}/{interaction_token}/messages/@original",
        headers=headers,
        json=payload,
        timeout=10
    )
    
    return response.status_code == 200


def process_button_click(custom_id, user_id, username, interaction_token=None):
    """
    Background task to process button click with LLM and post to user's DM.
    During testing, uses a template response. Will be replaced with Gemini LLM call.
    """
    try:
        logger.info(f"Processing button click: {custom_id} by {username} ({user_id})")
        
        # Get button configuration
        config = get_button_config(custom_id)
        
        # Determine a human-friendly label for the clicked response
        if 'yes' in custom_id.lower():
            resp_label = 'Yes'
        elif 'no' in custom_id.lower():
            resp_label = 'No'
        else:
            resp_label = custom_id

        # Call Gemini LLM API to generate an announcement in Spanish.
        # If the LLM fails for any reason, fall back to a safe template message.
        try:
            if 'yes' in custom_id.lower():
                prompt = (
                    "Eres un asistente creativo que escribe anuncios cortos en español para una comunidad "
                    "de videojuegos llamada 'Revolucionarios' que se dedican a jugar Age of Empires III: Definitive Edition. Escribe un anuncio amistoso, fresco y con humor "
                    "(emojis permitidos) anunciando que Golfo de México va a hacer un stream en vivo para el "
                    "RevoWeekend. Mantén el tono cercano y divertido, menciona a los 'Revolucionarios', incluye una "
                    "llamada a la acción para que la gente se una, y asegúrate de que el texto sea adecuado para "
                    "publicar en Discord. Devuelve sólo el texto del anuncio (sin explicaciones adicionales)."
                )
            elif 'no' in custom_id.lower():
                prompt = (
                    "Eres un asistente creativo que escribe anuncios cortos en español para una comunidad "
                    "de videojuegos llamada 'Revolucionarios' que se dedican a jugar Age of Empires III: Definitive Edition. Escribe un anuncio con tono apenado y melancólico, "
                    "pero respetuoso y cercano, comunicando que Golfo de México NO podrá hacer el stream del "
                    "RevoWeekend. Incluye un toque de humor suave para atenuar la decepción, menciona a los "
                    "'Revolucionarios', y sugiere mantenerse atentos a futuros anuncios. Devuelve sólo el texto "
                    "del anuncio (sin explicaciones adicionales)."
                )
            else:
                # Generic fallback prompt for unknown buttons
                prompt = (
                    f"Eres un asistente que escribe anuncios breves en español para la comunidad 'Revolucionarios'. "
                    f"Crea un anuncio breve y amistoso sobre: {resp_label}. Devuelve sólo el texto del anuncio."
                )

            # Ask the LLM for a compact announcement (limit tokens reasonably)
            generated_text = call_llm(prompt, max_tokens=200)

            # Ensure we have a string; if the model returned structured data, coerce to string
            if not isinstance(generated_text, str):
                generated_text = str(generated_text)

            # Trim whitespace
            generated_text = generated_text.strip()

            # Safety: if empty, fallback
            if not generated_text:
                raise ValueError("LLM returned empty response")

        except Exception as e:
            logger.error("LLM generation failed, using fallback message: %s", e)
            if 'yes' in custom_id.lower():
                generated_text = "¡Perfecto! Stream confirmado para mañana. Gracias por confirmar 🎮"
            elif 'no' in custom_id.lower():
                generated_text = "Entendido, no habrá stream mañana. ¡Nos vemos pronto! 👋"
            else:
                generated_text = f"Respuesta registrada: {resp_label}"
        
        # Format the message for DM (simpler format for direct DM)
        dm_message = f"**Tu respuesta ha sido registrada:**\n\n{generated_text}"
        
        # Add embed for better formatting
        embed = {
            "title": f"Respuesta: {resp_label}",
            "description": generated_text,
            "color": 0x00ff00 if "yes" in custom_id else 0xff0000,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": f"RevoWeekend Stream Check"
            }
        }
        
        # Post the Gemini-generated announcement to the community channel (text only, no embed)
        channel_id_to_post = ANNOUNCE_CHANNEL_ID or DISCORD_CHANNEL_ID
        channel_posted = post_to_discord(channel_id_to_post, generated_text)

        if channel_posted:
            logger.info(f"Successfully posted announcement to channel {channel_id_to_post}")
        else:
            logger.error(f"Failed to post announcement to channel {channel_id_to_post}; falling back to DM to user {username}")
            # If channel post fails, send the announcement to the user via DM (text only)
            send_dm_to_user(user_id, f"**Anuncio (fallback):**\n\n{generated_text}")

        # Also send a private confirmation DM to the user that their response was recorded
        success = send_dm_to_user(user_id, dm_message, embeds=[embed])
        if success:
            logger.info(f"Successfully sent response confirmation to user {username} via DM")
        else:
            logger.error(f"Failed to send response confirmation DM to user {username}")
        
        # Optionally update the ephemeral message
        if interaction_token:
            update_interaction_message(
                interaction_token,
                "✅ Tu respuesta ha sido registrada y enviada a tu DM!"
            )

        logger.info(f"Successfully processed button click for {username}")
        
    except Exception as e:
        logger.error(f"Error processing button click: {str(e)}", exc_info=True)
        
        # Try to notify the user of the error
        if interaction_token:
            update_interaction_message(
                interaction_token,
                "❌ Sorry, there was an error processing your request. Please try again later."
            )


def send_dm_to_user(user_id, content, embeds=None, components=None):
    """Open a DM channel with the user and send a message there.

    Returns True on success, False otherwise.
    """
    try:
        headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
        resp = requests.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers=headers,
            json={"recipient_id": user_id},
            timeout=10
        )
        if resp.status_code not in (200, 201):
            logger.error(f"Failed to open DM channel for user {user_id}: {resp.status_code} - {resp.text}")
            return False

        dm_channel_id = resp.json().get("id")
        if not dm_channel_id:
            logger.error(f"DM channel response missing id: {resp.text}")
            return False

        return post_to_discord(dm_channel_id, content, embeds=embeds, components=components)
    except Exception as e:
        logger.error(f"Error sending DM to user {user_id}: {e}", exc_info=True)
        return False


def send_weekly_prompt():
    """Send the weekly Friday 6pm prompt asking about Saturday's livestream.

    This posts a message to `DISCORD_CHANNEL_ID` with two buttons: Yes and No.
    If DISCORD_CHANNEL_ID is a user ID, it will open a DM first.
    """
    try:
        channel_id = DISCORD_CHANNEL_ID
        logger.info("Sending weekly Friday prompt to channel/user %s", channel_id)

        content = "Hola Golfo! Habrá stream mañana para el RevoWeekend?"

        # Discord component structure: an action row (type 1) containing buttons (type 2)
        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 3,  # green (Success)
                        "label": "Ahuevo!",
                        "custom_id": "revo_yes"
                    },
                    {
                        "type": 2,
                        "style": 4,  # red (Danger)
                        "label": "Nel",
                        "custom_id": "revo_no"
                    }
                ]
            }
        ]

        # Optionally include a simple embed for nicer formatting
        embed = {
            "title": "Weekly Stream Check",
            "description": "Please indicate whether there will be a live stream on Saturday.",
            "color": 0x0099ff,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Try posting directly first (works for guild channels)
        success = post_to_discord(channel_id, content, embeds=[embed], components=components)
        
        # If direct post fails with 404, try opening a DM channel first (for user DMs)
        if not success:
            logger.info("Direct post failed; attempting to open DM channel for user %s", channel_id)
            dm_response = requests.post(
                f"https://discord.com/api/v10/users/@me/channels",
                headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
                json={"recipient_id": channel_id},
                timeout=10
            )
            if dm_response.status_code in (200, 201):
                dm_channel_id = dm_response.json().get("id")
                logger.info("DM channel opened: %s", dm_channel_id)
                post_to_discord(dm_channel_id, content, embeds=[embed], components=components)
            else:
                logger.error(f"Failed to open DM channel: {dm_response.status_code} - {dm_response.text}")

    except Exception as e:
        logger.error(f"Error sending weekly prompt: {e}", exc_info=True)


@app.route('/interactions', methods=['POST'])
@verify_key_decorator(DISCORD_PUBLIC_KEY)
def interactions():
    """
    Main endpoint for Discord interactions.
    """
    try:
        interaction_data = request.json
        interaction_type = interaction_data.get('type')
        
        # Type 1: Ping/Verification
        if interaction_type == 1:
            logger.info("Received verification ping from Discord")
            return jsonify({"type": 1})
        
        # Type 2: Application Command (slash commands)
        if interaction_type == 2:
            data = interaction_data.get('data', {})
            command_name = data.get('name', '')
            
            # Check if it's an AoE3 command
            if command_name.startswith('aoe3_'):
                logger.info(f"Received AoE3 slash command: /{command_name}")
                # Import and handle asynchronously
                import asyncio
                from aoe3.interaction_handler import handle_aoe3_command
                
                # Run async handler in a way that allows background tasks
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Don't close the loop - let background tasks complete
                response = loop.run_until_complete(handle_aoe3_command(interaction_data))
                
                return jsonify(response)
            
            # Unknown command
            logger.warning(f"Unknown slash command: /{command_name}")
            return jsonify({
                "type": 4,
                "data": {
                    "content": f"❌ Comando desconocido: {command_name}",
                    "flags": 64
                }
            })
        
        # Type 3: Message Component (buttons)
        if interaction_type == 3:
            custom_id = interaction_data['data']['custom_id']

            # Discord sends different shapes depending on context:
            # - In guilds the user info is under interaction_data['member']['user']
            # - In DMs the user info is under interaction_data['user']
            member = interaction_data.get('member')
            if member and isinstance(member, dict) and 'user' in member:
                user = member['user']
            else:
                user = interaction_data.get('user', {})

            user_id = user.get('id')
            username = user.get('username') or user.get('global_name') or 'Unknown'
            interaction_token = interaction_data.get('token')
            
            logger.info(f"Button clicked: {custom_id} by {username} ({user_id})")
            
            # Get button-specific acknowledgment message
            config = get_button_config(custom_id)
            
            # Immediate acknowledgment
            acknowledgment = {
                "type": 4,
                "data": {
                    "content": config["acknowledgment"],
                    "flags": 64  # Ephemeral
                }
            }
            
            # Start background processing
            thread = threading.Thread(
                target=process_button_click,
                args=(custom_id, user_id, username, interaction_token)
            )
            thread.daemon = True
            thread.start()
            
            return jsonify(acknowledgment)
        
        logger.warning(f"Unknown interaction type: {interaction_type}")
        return jsonify({"error": "Unknown interaction type"}), 400
        
    except Exception as e:
        logger.error(f"Error handling interaction: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route('/message', methods=['POST'])
@verify_key_decorator(DISCORD_PUBLIC_KEY)
def message_handler():
    """
    Handler for Discord message events (via gateway webhooks or similar).
    Listens for:
    - Bot mentions/tags
    - Voice commands like "GolfoBot, arma los equipos"
    """
    try:
        data = request.json
        event_type = data.get('t')  # Event type
        
        # Only handle MESSAGE_CREATE events
        if event_type != 'MESSAGE_CREATE':
            return jsonify({"ok": True}), 200
        
        d = data.get('d', {})  # Event data
        
        # Ignore bot messages
        author = d.get('author', {})
        if author.get('bot'):
            return jsonify({"ok": True}), 200
        
        content = d.get('content', '').strip()
        user_id = author.get('id')
        username = author.get('username') or author.get('global_name') or 'Unknown'
        guild_id = d.get('guild_id')
        channel_id = d.get('channel_id')
        
        if not content or not user_id:
            return jsonify({"ok": True}), 200
        
        logger.info(f"Message from {username}: {content[:100]}")
        
        # Use TEST_CHANNEL_ID for bot interactions if set, otherwise use the message channel
        response_channel_id = TEST_CHANNEL_ID or channel_id
        
        # Check if bot is mentioned (tagged)
        mentions = d.get('mentions', [])
        bot_mentioned = any(m.get('id') == DISCORD_BOT_TOKEN.split('.')[0] for m in mentions)  # Rough check
        
        # Also check for direct bot name mentions
        is_bot_tagged = f"<@{DISCORD_BOT_TOKEN.split('.')[0]}>" in content or "golfobot" in content.lower()
        
        if is_bot_tagged or bot_mentioned:
            # Bot is tagged - respond with greeting
            greeting = get_mexican_greeting()
            response_thread = threading.Thread(
                target=lambda: post_to_discord(response_channel_id, greeting)
            )
            response_thread.daemon = True
            response_thread.start()
            return jsonify({"ok": True}), 200
        
        # Check for voice command patterns
        content_lower = content.lower()
        
        # Pattern: "GolfoBot, arma los equipos" or similar
        if re.search(r'(arma|organiza|separa|mueve).*equipo', content_lower):
            logger.info(f"Detected team organization command from {username}")
            
            # Extract team format if specified (e.g., "2v2", "3v3")
            team_format = parse_team_format(content)
            
            if team_format:
                team_size, num_teams, total_needed = team_format
                logger.info(f"Parsed team format: {team_size}v{team_size} ({num_teams} teams, {total_needed} players needed)")
                
                # Get members in voice channels
                members = get_voice_channel_members(guild_id)
                
                if not members:
                    # Try alternative: get from message metadata or request actual voice state
                    # For now, return error in persona
                    error_msg = f"{get_error_response_persona()} (No pude detectar quién está en voz, hermano. ¿Estás seguro que todos están conectados?)"
                    response_thread = threading.Thread(
                        target=lambda: post_to_discord(response_channel_id, error_msg)
                    )
                    response_thread.daemon = True
                    response_thread.start()
                    return jsonify({"ok": True}), 200
                
                # Check if we have enough players
                if len(members) < total_needed:
                    error_msg = f"¡Ay, compa! Necesito {total_needed} jugadores pero solo encontré {len(members)}. Más gente en voz, porfa. 🎤"
                    response_thread = threading.Thread(
                        target=lambda: post_to_discord(response_channel_id, error_msg)
                    )
                    response_thread.daemon = True
                    response_thread.start()
                    return jsonify({"ok": True}), 200
                
                # Randomize teams
                random.shuffle(members)
                teams = [members[i*team_size:(i+1)*team_size] for i in range(num_teams)]
                
                # Create/get team channels
                team_channels = create_or_get_team_channels(guild_id, num_teams)
                
                if len(team_channels) != num_teams:
                    error_msg = f"Tuve un problema creando los canales, jefe. Intenta de nuevo. 🤷"
                    response_thread = threading.Thread(
                        target=lambda: post_to_discord(response_channel_id, error_msg)
                    )
                    response_thread.daemon = True
                    response_thread.start()
                    return jsonify({"ok": True}), 200
                
                # Move players to team channels
                for team_idx, team in enumerate(teams):
                    for member in team:
                        move_user_to_channel(member['user_id'], guild_id, team_channels[team_idx])
                
                # Build team announcement
                team_lines = []
                for i, team in enumerate(teams):
                    team_names = ", ".join([m['username'] for m in team])
                    team_lines.append(f"**Equipo {i+1}:** {team_names}")
                
                team_announcement = "\n".join(team_lines)
                formation_response = get_team_formation_response(f"{team_size}v{team_size}")
                moving_response = get_moving_to_channels_response()
                
                full_response = f"{formation_response}\n\n{team_announcement}\n\n{moving_response}"
                
                response_thread = threading.Thread(
                    target=lambda: post_to_discord(response_channel_id, full_response)
                )
                response_thread.daemon = True
                response_thread.start()
                return jsonify({"ok": True}), 200
            else:
                # Team command but no format parsed
                error_msg = f"{get_error_response_persona()} Dime en qué formato: 2v2, 3v3, etc. 🎮"
                response_thread = threading.Thread(
                    target=lambda: post_to_discord(response_channel_id, error_msg)
                )
                response_thread.daemon = True
                response_thread.start()
                return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"Error handling message: {str(e)}", exc_info=True)
        return jsonify({"ok": True}), 200


@app.route('/dev/simulate', methods=['POST'])
def dev_simulate():
    """Dev-only endpoint to simulate an interaction payload (guild or dm).

    Request JSON fields:
    - mode: "guild" or "dm" (default: "guild")
    - custom_id: button custom id (default: "revo_yes")
    - user_id: user id to simulate (default: `DISCORD_CHANNEL_ID`)
    - username: display name (default: "DevUser")

    Guarded by `ALLOW_DEV_ENDPOINTS` env var (must be set to 1/true/yes).
    This endpoint returns the same ephemeral acknowledgement JSON used by interactions.
    """
    if os.environ.get('ALLOW_DEV_ENDPOINTS', '').lower() not in ('1', 'true', 'yes'):
        return jsonify({"error":"Dev endpoints disabled"}), 403

    body = request.json or {}
    mode = body.get('mode', 'guild')
    custom_id = body.get('custom_id', 'revo_yes')
    user_id = str(body.get('user_id') or DISCORD_CHANNEL_ID)
    username = body.get('username', 'DevUser')

    # Build a payload-like structure but we directly call background processor
    # For guild mode, emulate member.user; for dm mode, emulate user
    if mode == 'guild':
        member = {'user': {'id': user_id, 'username': username}}
        user_obj = member['user']
    else:
        user_obj = {'id': user_id, 'username': username}

    interaction_token = 'dev-token'

    # Start background processing to mimic real interactions
    thread = threading.Thread(
        target=process_button_click,
        args=(custom_id, user_obj['id'], user_obj.get('username', 'DevUser'), interaction_token)
    )
    thread.daemon = True
    thread.start()

    # Immediate ephemeral acknowledgement (same shape as real interactions)
    acknowledgment = {
        "type": 4,
        "data": {
            "content": get_button_config(custom_id)["acknowledgment"],
            "flags": 64
        }
    }
    return jsonify(acknowledgment), 200


@app.route('/dev/llm_reply', methods=['POST'])
def dev_llm_reply():
    """Dev endpoint for voice chat - sends user speech to LLM and returns reply."""
    if os.environ.get('ALLOW_DEV_ENDPOINTS', '').lower() not in ('1', 'true', 'yes'):
        return jsonify({"error": "Dev endpoints disabled"}), 403
    
    try:
        data = request.json
        content = data.get('content', '').strip()
        username = data.get('username', 'Usuario')
        context = data.get('context', '')  # Recent conversation context
        
        if not content:
            return jsonify({"error": "No content provided"}), 400
        
        # Build prompt for LLM
        if context:
            prompt = f"""Eres GolfoBot, un bot de Discord con personalidad mexicana alegre y casual.

Contexto de la conversación reciente:
{context}

El usuario {username} acaba de decir: "{content}"

Responde de forma natural y relevante al contexto. Puedes comentar sobre lo que otros dijeron o hacer una observación graciosa. Sé breve (máximo 2-3 oraciones). Usa español mexicano casual."""
        else:
            prompt = f"""Eres GolfoBot, un bot de Discord con personalidad mexicana alegre y casual.
Un usuario llamado {username} te dijo en voz: "{content}"

Responde de forma natural, breve y amigable (máximo 2-3 oraciones). Usa español mexicano casual."""
        
        # Call LLM
        reply = call_llm(prompt, max_tokens=150)
        
        return jsonify({"reply": reply.strip()}), 200
        
    except Exception as e:
        logger.error(f"Error in /dev/llm_reply: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/dev/echo', methods=['POST', 'GET'])
def dev_echo():
    """Dev-only endpoint to echo request headers and a small body preview.

    Guarded by `ALLOW_DEV_ENDPOINTS` to avoid accidental exposure.
    Useful to debug Discord webhook delivery and signature headers after restarting the server.
    """
    if os.environ.get('ALLOW_DEV_ENDPOINTS', '').lower() not in ('1', 'true', 'yes'):
        return jsonify({"error": "Dev endpoints disabled"}), 403

    # Collect headers (convert to plain dict)
    headers = {k: v for k, v in request.headers.items()}
    body = request.get_data() or b''
    try:
        body_text = body.decode('utf-8', errors='replace')
    except Exception:
        body_text = str(body)

    # Limit body preview size
    body_preview = body_text[:2048]

    return jsonify({
        "headers": headers,
        "body_preview": body_preview
    }), 200


@app.route('/dev/simulate_message', methods=['POST'])
def dev_simulate_message():
    """Dev-only endpoint to simulate a message event for testing team commands.
    
    Request JSON fields:
    - content: message content (default: "GolfoBot, arma los equipos 2v2")
    - username: author name (default: "TestUser")
    - user_id: user id (default: "123456789")
    - guild_id: guild id (default: DISCORD_CHANNEL_ID)
    - channel_id: channel id (default: DISCORD_CHANNEL_ID)
    
    Guarded by ALLOW_DEV_ENDPOINTS env var.
    """
    try:
        logger.info(f"[DEV] /dev/simulate_message endpoint called")
        
        if os.environ.get('ALLOW_DEV_ENDPOINTS', '').lower() not in ('1', 'true', 'yes'):
            logger.warning("[DEV] Dev endpoints disabled - rejecting request")
            return jsonify({"error": "Dev endpoints disabled"}), 403
        
        body = request.json or {}
        content = body.get('content', 'GolfoBot, arma los equipos 2v2')
        username = body.get('username', 'TestUser')
        user_id = body.get('user_id', '123456789')
        guild_id = body.get('guild_id', DISCORD_CHANNEL_ID)
        channel_id = body.get('channel_id', TEST_CHANNEL_ID or DISCORD_CHANNEL_ID)
        mentions = body.get('mentions', [])
        
        logger.info(f"[DEV] Simulating message: '{content}' from {username} (user_id={user_id}, channel_id={channel_id})")
        
        # Build a minimal Discord MESSAGE_CREATE event
        event_data = {
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "sim_msg_id",
                "content": content,
                "author": {
                    "id": user_id,
                    "username": username,
                    "global_name": username,
                    "bot": False
                },
                "guild_id": guild_id,
                "channel_id": channel_id,
                "mentions": mentions,
                "type": 0
            }
        }
        
        # Process the simulated event in a thread
        response_thread = threading.Thread(
            target=lambda: message_handler_internal(event_data)
        )
        response_thread.daemon = True
        response_thread.start()
        
        logger.info("[DEV] Message processing thread started, returning 200")
        
        return jsonify({
            "ok": True,
            "message": f"Simulated message: {content[:50]}..."
        }), 200
        
    except Exception as e:
        logger.error(f"[DEV] Error in dev_simulate_message endpoint: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500


def message_handler_internal(event_data):
    """Internal message handler logic (extracted from message_handler for reuse)"""
    try:
        d = event_data.get('d', {})
        
        # Ignore bot messages
        author = d.get('author', {})
        if author.get('bot'):
            return
        
        content = d.get('content', '').strip()
        user_id = author.get('id')
        username = author.get('username') or author.get('global_name') or 'Unknown'
        guild_id = d.get('guild_id')
        channel_id = d.get('channel_id')
        
        if not content or not user_id:
            return
        
        logger.info(f"Message from {username}: {content[:100]}")
        
        # Use the channel where the message came from (so bot replies in the same channel)
        response_channel_id = channel_id

        # Check if bot is mentioned
        mentions = d.get('mentions', [])
        mention_ids = [m.get('id') for m in mentions] if mentions else []

        # Prefer explicit bot user id if provided via env var `DISCORD_BOT_USER_ID`
        bot_user_id = os.environ.get('DISCORD_BOT_USER_ID') or os.environ.get('BOT_USER_ID')

        is_bot_tagged = False
        if mention_ids:
            if bot_user_id:
                is_bot_tagged = str(bot_user_id) in mention_ids
            else:
                # If no bot id provided, treat any mention as intended for the bot
                is_bot_tagged = True

        # Also accept textual name triggers
        if not is_bot_tagged and "golfobot" in content.lower():
            is_bot_tagged = True

        # If the message is dangerous (self-harm instructions or explicit threats),
        # tag moderators and remind the user to behave. Do not roast these messages.
        try:
            if is_dangerous_message(content):
                logger.info(f"Detected dangerous message from %s; alerting moderators", username)
                mod_mentions = get_moderator_mentions()
                user_mention = f"<@{user_id}>" if user_id else username
                pieces = [f"{user_mention}, por favor respeta a los demás y evita incitar daño."]
                if mod_mentions:
                    pieces.append(f"{mod_mentions} — por favor revisen este mensaje.")
                else:
                    pieces.append("Moderadores: por favor revisen este mensaje.")

                alert_msg = " ".join(pieces)
                logger.info(f"Prepared moderator alert: %s", alert_msg)
                post_to_discord(response_channel_id, alert_msg)
                return
        except Exception as e:
            logger.warning(f"Error during dangerous-message detection/alert: {e}")

        # If the message appears mean/abusive, reply with a short roast (spicy but non-violent)
        try:
            if is_mean_message(content):
                logger.info(f"Detected mean message from %s, generating roast", username)
                roast = get_roast_response(content, user_id)
                # Mention the user who sent the mean message (keeps context)
                try:
                    mention = f"<@{user_id}>" if user_id else username
                except Exception:
                    mention = username
                post_to_discord(response_channel_id, f"{mention} {roast}")
                return
        except Exception as e:
            logger.warning(f"Error during mean-message detection/roast: {e}")
        if is_bot_tagged or mentions:
            # Generate a short persona-aware reply using the LLM
            try:
                # Clean content: remove bot mentions to avoid LLM confusion
                cleaned_content = content
                for mention in mentions:
                    mention_id = mention.get('id')
                    if mention_id:
                        # Remove <@ID> and <@!ID> patterns
                        cleaned_content = re.sub(rf'<@!?{mention_id}>', '', cleaned_content)
                cleaned_content = cleaned_content.strip()
                
                persona_instructions = (
                    "You are GolfoBot, a funny, charismatic Mexican persona — más Mexicano que un nopal. "
                    "Speak with warmth, humor, playful roasts, and Mexican slang. Keep replies short, punchy, and never mean-spirited. "
                    "If asked to perform an action, confirm it."
                )

                prompt = (
                    f"{persona_instructions}\n\nUser {username} said: \"{cleaned_content}\"\n\n"
                    "Reply as GolfoBot in Spanish with a short, energetic response (<= 2 sentences). "
                    "Do NOT include any Discord mentions like @username or <@ID> in your reply."
                )

                logger.info(f"Calling LLM for conversational reply to {username}")
                generated_text = call_llm(prompt, max_tokens=200)
                if not generated_text:
                    raise RuntimeError("LLM returned empty response")

                # Prepend user mention to the reply
                user_mention = f"<@{user_id}>" if user_id else username
                full_reply = f"{user_mention} {generated_text}"
                
                # Post LLM-generated reply to the channel
                post_to_discord(response_channel_id, full_reply)
            except Exception as e:
                logger.warning(f"LLM conversational reply failed: {e}")
                # Fallback to a friendly persona greeting
                greeting = get_mexican_greeting()
                post_to_discord(response_channel_id, greeting)

            return
        
        # Check for voice command patterns
        content_lower = content.lower()
        
        if re.search(r'(arma|organiza|separa|mueve).*equipo', content_lower):
            logger.info(f"Detected team organization command from {username}")
            
            team_format = parse_team_format(content)
            
            if team_format:
                team_size, num_teams, total_needed = team_format
                logger.info(f"Parsed team format: {team_size}v{team_size} ({num_teams} teams, {total_needed} players needed)")
                
                # For dev: just acknowledge the command
                formation_response = get_team_formation_response(f"{team_size}v{team_size}")
                post_to_discord(channel_id, formation_response)
            else:
                error_msg = f"{get_error_response_persona()} Dime en qué formato: 2v2, 3v3, etc. 🎮"
                post_to_discord(channel_id, error_msg)
    
    except Exception as e:
        logger.error(f"Error in message_handler_internal: {str(e)}", exc_info=True)


@app.route('/', methods=['GET'])
def root():
    """Root endpoint for Railway health checks"""
    return jsonify({"status": "ok", "service": "GolfoBot Flask Server"}), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint with system status"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "channel_id": DISCORD_CHANNEL_ID
    }), 200


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    # Verify environment variables
    required_vars = [
        'DISCORD_PUBLIC_KEY',
        'DISCORD_BOT_TOKEN',
        'DISCORD_APP_ID',
        'DISCORD_CHANNEL_ID'
    ]
    
    # At least one LLM key is required
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        logger.error("Missing LLM API key: Either GROQ_API_KEY or GEMINI_API_KEY must be set")
        exit(1)
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
    
    # Log which LLM is configured
    if GROQ_API_KEY:
        logger.info(f"Using Groq API with model: {GROQ_MODEL}")
    if GEMINI_API_KEY:
        logger.info(f"Gemini API available as fallback with model: {GEMINI_MODEL}")
    
    logger.info("=" * 50)
    logger.info("Discord Interaction Handler Starting")
    logger.info(f"Channel ID: {DISCORD_CHANNEL_ID}")
    logger.info(f"Registered buttons: {', '.join(BUTTON_CONFIGS.keys())}")
    logger.info("=" * 50)
    # Scheduler timezone: use SCHEDULE_TZ env or fall back to system TZ or UTC
    tz_name = os.environ.get('SCHEDULE_TZ') or os.environ.get('TZ') or 'UTC'
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning(f"Invalid timezone '{tz_name}', falling back to UTC")
        tz = ZoneInfo('UTC')

    # Start background scheduler to send message every Friday at 18:00 (6pm) in the configured tz
    try:
        scheduler = BackgroundScheduler(timezone=tz)
        trigger = CronTrigger(day_of_week='fri', hour=18, minute=0, timezone=tz)
        scheduler.add_job(send_weekly_prompt, trigger=trigger, id='weekly_friday_prompt')
        scheduler.start()
        logger.info(f"Scheduled weekly Friday prompt at 18:00 {tz_name}")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}", exc_info=True)

    # For testing: optionally send the scheduled prompt immediately when the server starts
    if os.environ.get('SEND_PROMPT_ON_START', '').lower() in ('1', 'true', 'yes'):
        try:
            logger.info("SEND_PROMPT_ON_START is enabled, sending prompt now...")
            send_weekly_prompt()
            logger.info("SEND_PROMPT_ON_START enabled — sent prompt immediately on startup")
        except Exception as e:
            logger.error(f"Error sending immediate prompt on start: {e}", exc_info=True)

    # Use Railway's PORT environment variable if available, otherwise default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)