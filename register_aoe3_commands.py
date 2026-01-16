"""
Register AoE3 slash commands with Discord.
Run this script once to register commands, then they'll work via the interactions endpoint.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISCORD_APP_ID = os.environ.get('DISCORD_APP_ID')

if not DISCORD_BOT_TOKEN or not DISCORD_APP_ID:
    print("❌ Missing DISCORD_BOT_TOKEN or DISCORD_APP_ID in environment")
    exit(1)

# Discord API endpoint for global commands
url = f"https://discord.com/api/v10/applications/{DISCORD_APP_ID}/commands"

headers = {
    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    "Content-Type": "application/json"
}

# Define all AoE3 commands
commands = [
    {
        "name": "aoe3_registro",
        "description": "Registra tu usuario de AoE3 para seguimiento de ELO",
        "options": [
            {
                "name": "username",
                "description": "Tu nombre de usuario en Age of Empires 3: Definitive Edition",
                "type": 3,  # STRING
                "required": True
            }
        ]
    },
    {
        "name": "aoe3_elo",
        "description": "Consulta el ELO de un jugador",
        "options": [
            {
                "name": "usuario",
                "description": "Usuario de Discord o nombre en AoE3 (opcional, por defecto tu propio ELO)",
                "type": 3,  # STRING
                "required": False
            }
        ]
    },
    {
        "name": "aoe3_leaderboard",
        "description": "Muestra el ranking de jugadores registrados",
        "options": [
            {
                "name": "modo",
                "description": "Tipo de ranking: team (equipos) o solo (1v1)",
                "type": 3,  # STRING
                "required": True,
                "choices": [
                    {"name": "Equipos (Team)", "value": "team"},
                    {"name": "1v1 (Solo)", "value": "solo"}
                ]
            },
            {
                "name": "limite",
                "description": "Número de jugadores a mostrar (por defecto 10)",
                "type": 4,  # INTEGER
                "required": False
            }
        ]
    },
    {
        "name": "aoe3_partidas",
        "description": "Muestra las partidas recientes de un jugador",
        "options": [
            {
                "name": "usuario",
                "description": "Usuario de Discord o nombre en AoE3 (opcional, por defecto tus partidas)",
                "type": 3,  # STRING
                "required": False
            }
        ]
    },
    {
        "name": "aoe3_civ",
        "description": "Información sobre una civilización",
        "options": [
            {
                "name": "nombre",
                "description": "Nombre de la civilización (ej: Españoles, Británicos, Otomanos)",
                "type": 3,  # STRING
                "required": True
            }
        ]
    },
    {
        "name": "aoe3_estrategia",
        "description": "Comparte una estrategia para AoE3",
        "options": [
            {
                "name": "civilizacion",
                "description": "Civilización para la estrategia",
                "type": 3,  # STRING
                "required": True
            },
            {
                "name": "titulo",
                "description": "Título breve de la estrategia",
                "type": 3,  # STRING
                "required": True
            },
            {
                "name": "descripcion",
                "description": "Descripción detallada de la estrategia",
                "type": 3,  # STRING
                "required": True
            }
        ]
    },
    {
        "name": "aoe3_estrategias",
        "description": "Ver estrategias de la comunidad",
        "options": [
            {
                "name": "civilizacion",
                "description": "Filtrar por civilización (opcional)",
                "type": 3,  # STRING
                "required": False
            }
        ]
    }
]

print("📝 Registering AoE3 slash commands with Discord...")
print(f"App ID: {DISCORD_APP_ID}")
print(f"Registering {len(commands)} commands...")

# Register each command
for command in commands:
    print(f"\n  Registering: /{command['name']}")
    response = requests.post(url, headers=headers, json=command)
    
    if response.status_code == 200 or response.status_code == 201:
        print(f"  ✅ Success: /{command['name']}")
    else:
        print(f"  ❌ Failed: /{command['name']}")
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text}")

print("\n✅ Command registration complete!")
print("\nℹ️  Commands may take up to 1 hour to appear globally.")
print("ℹ️  They should appear immediately in guilds where the bot is already installed.")
