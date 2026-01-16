"""
Flask interaction handler for AoE3 slash commands.
This handles slash commands that come through Discord's interactions endpoint.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger('aoe3.interaction_handler')


async def handle_aoe3_command(interaction_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle AoE3 slash command interactions.
    
    Args:
        interaction_data: The interaction payload from Discord
    
    Returns:
        Discord interaction response dict
    """
    try:
        # Extract command data
        data = interaction_data.get('data', {})
        command_name = data.get('name')
        options = {opt['name']: opt['value'] for opt in data.get('options', [])}
        
        # Get user info
        member = interaction_data.get('member')
        if member and isinstance(member, dict) and 'user' in member:
            user = member['user']
        else:
            user = interaction_data.get('user', {})
        
        user_id = user.get('id')
        username = user.get('username', 'Unknown')
        
        logger.info(f"Processing AoE3 command: /{command_name} from {username} ({user_id})")
        
        # Route to appropriate handler
        if command_name == 'aoe3_registro':
            return await handle_register(user_id, username, options, interaction_data)
        elif command_name == 'aoe3_elo':
            return await handle_elo(user_id, options)
        elif command_name == 'aoe3_leaderboard':
            return await handle_leaderboard(options)
        elif command_name == 'aoe3_partidas':
            return await handle_matches(user_id, options)
        elif command_name == 'aoe3_civ':
            return await handle_civilization(options)
        elif command_name == 'aoe3_estrategia':
            return await handle_add_strategy(user_id, username, options)
        elif command_name == 'aoe3_estrategias':
            return await handle_view_strategies(options)
        else:
            return {
                "type": 4,
                "data": {
                    "content": f"❌ Comando no reconocido: {command_name}",
                    "flags": 64  # Ephemeral
                }
            }
    
    except Exception as e:
        logger.error(f"Error handling AoE3 command: {e}", exc_info=True)
        return {
            "type": 4,
            "data": {
                "content": "❌ Error al procesar el comando. Intenta de nuevo más tarde.",
                "flags": 64
            }
        }


async def handle_register(user_id: str, username: str, options: Dict, interaction_data: Dict = None) -> Dict:
    """Handle /aoe3_registro command."""
    from .database import register_player, get_player_by_discord_id
    from .scraper import AoE3Scraper
    import aiohttp
    import os
    import asyncio
    
    aoe3_username = options.get('username')
    
    if not aoe3_username:
        return {
            "type": 4,
            "data": {
                "content": "❌ Debes proporcionar tu nombre de usuario de AoE3.",
                "flags": 64
            }
        }
    
    # Check if already registered
    existing = await get_player_by_discord_id(user_id)
    if existing:
        return {
            "type": 4,
            "data": {
                "content": f"❌ Ya estás registrado con el usuario `{existing['aoe3_username']}`.\nPara cambiar tu usuario, contacta a un administrador.",
                "flags": 64
            }
        }
    
    # For long operations, defer the response and send a follow-up
    if interaction_data:
        # Start background thread to process registration
        import threading
        thread = threading.Thread(
            target=_run_registration_background,
            args=(user_id, username, aoe3_username, interaction_data),
            daemon=True
        )
        thread.start()
        
        # Return deferred response immediately
        return {
            "type": 5  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
        }
    
    # Fallback: process synchronously (shouldn't normally reach here)
    return await _process_registration(user_id, username, aoe3_username)


async def _process_registration(user_id: str, username: str, aoe3_username: str) -> Dict:
    """Process player registration."""
    from .database import register_player
    from .scraper import AoE3Scraper
    
    # Search for player
    try:
        async with AoE3Scraper() as scraper:
            player_data = await scraper.search_player(aoe3_username)
            
            if not player_data:
                return {
                    "type": 4,
                    "data": {
                        "content": f"❌ No se encontró el jugador `{aoe3_username}` en aoe3-homecity.com.\nVerifica que el nombre sea correcto.",
                        "flags": 64
                    }
                }
            
            # Fetch current ELO
            profile = await scraper.get_player_profile(player_data['player_id'])
            team_elo = profile.get('team_elo') if profile else None
            solo_elo = profile.get('solo_elo') if profile else None
        
        # Register in database
        await register_player(
            discord_id=user_id,
            discord_username=username,
            aoe3_username=player_data['username'],
            aoe3_player_id=player_data['player_id'],
            team_elo=team_elo,
            solo_elo=solo_elo
        )
        
        # Build success embed
        embed = {
            "title": "✅ Registro Exitoso",
            "description": f"Usuario **{player_data['username']}** registrado correctamente.",
            "color": 0x2ecc71,
            "fields": []
        }
        
        if team_elo or solo_elo:
            elo_text = []
            if team_elo:
                elo_text.append(f"**Equipo:** {team_elo}")
            if solo_elo:
                elo_text.append(f"**1v1:** {solo_elo}")
            embed["fields"].append({
                "name": "ELO Actual",
                "value": " | ".join(elo_text),
                "inline": False
            })
        
        embed["fields"].append({
            "name": "Seguimiento Automático",
            "value": "Tu ELO se actualizará automáticamente cada 30 minutos.",
            "inline": False
        })
        
        return {
            "type": 4,
            "data": {
                "embeds": [embed]
            }
        }
        
    except Exception as e:
        logger.error(f"Error registering player: {e}", exc_info=True)
        return {
            "type": 4,
            "data": {
                "content": "❌ Error al registrar usuario. Intenta nuevamente más tarde.",
                "flags": 64
            }
        }


async def _process_registration_background(user_id: str, username: str, aoe3_username: str, interaction_data: Dict):
    """Process registration in background and send follow-up webhook."""
    import aiohttp
    import os
    
    try:
        # Process registration
        result = await _process_registration(user_id, username, aoe3_username)
        
        # Send follow-up via webhook
        app_id = interaction_data.get('application_id')
        interaction_token = interaction_data.get('token')
        
        if not app_id or not interaction_token:
            logger.error("Missing application_id or token for follow-up")
            return
        
        webhook_url = f"https://discord.com/api/v10/webhooks/{app_id}/{interaction_token}"
        
        # Extract the response data
        response_data = result.get('data', {})
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=response_data) as response:
                if response.status not in (200, 204):
                    logger.error(f"Failed to send follow-up: HTTP {response.status}")
                else:
                    logger.info("Successfully sent registration follow-up")
    
    except Exception as e:
        logger.error(f"Error in background registration: {e}", exc_info=True)
        
        # Try to send error message
        try:
            app_id = interaction_data.get('application_id')
            interaction_token = interaction_data.get('token')
            webhook_url = f"https://discord.com/api/v10/webhooks/{app_id}/{interaction_token}"
            
            async with aiohttp.ClientSession() as session:
                await session.post(webhook_url, json={
                    "content": "❌ Error al procesar el registro. Intenta nuevamente.",
                    "flags": 64
                })
        except:
            pass


def _run_registration_background(user_id: str, username: str, aoe3_username: str, interaction_data: Dict):
    """Thread wrapper to run async registration in background."""
    import asyncio
    
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the async function
        loop.run_until_complete(_process_registration_background(
            user_id, username, aoe3_username, interaction_data
        ))
        
        loop.close()
    except Exception as e:
        logger.error(f"Error in registration thread: {e}", exc_info=True)


async def handle_elo(user_id: str, options: Dict) -> Dict:
    """Handle /aoe3_elo command."""
    from .database import get_player_by_discord_id, get_player_by_aoe3_username
    
    usuario = options.get('usuario')
    
    player = None
    if usuario is None:
        player = await get_player_by_discord_id(user_id)
        if not player:
            return {
                "type": 4,
                "data": {
                    "content": "❌ No estás registrado. Usa `/aoe3_registro` para registrarte.",
                    "flags": 64
                }
            }
    else:
        # Try to find by mention or username
        if usuario.startswith('<@') and usuario.endswith('>'):
            discord_id = usuario.strip('<@!>')
            player = await get_player_by_discord_id(discord_id)
        
        if not player:
            player = await get_player_by_aoe3_username(usuario)
        
        if not player:
            return {
                "type": 4,
                "data": {
                    "content": f"❌ No se encontró el jugador `{usuario}`.",
                    "flags": 64
                }
            }
    
    # Build embed response
    embed = {
        "title": f"📊 ELO de {player['aoe3_username']}",
        "color": 0x3498db,
        "fields": []
    }
    
    if player['team_elo'] or player['solo_elo']:
        if player['team_elo']:
            embed['fields'].append({
                "name": "Equipo (Team)",
                "value": str(player['team_elo']),
                "inline": True
            })
        if player['solo_elo']:
            embed['fields'].append({
                "name": "1v1 (Solo)",
                "value": str(player['solo_elo']),
                "inline": True
            })
    else:
        embed['description'] = "No hay datos de ELO disponibles."
    
    if player.get('last_updated'):
        timestamp = int(player['last_updated'].timestamp())
        embed['fields'].append({
            "name": "Última Actualización",
            "value": f"<t:{timestamp}:R>",
            "inline": False
        })
    
    return {
        "type": 4,
        "data": {
            "embeds": [embed]
        }
    }


async def handle_leaderboard(options: Dict) -> Dict:
    """Handle /aoe3_leaderboard command."""
    from .database import get_leaderboard
    
    modo = options.get('modo', 'team')
    limite = options.get('limite', 10)
    
    is_team = modo == 'team'
    players = await get_leaderboard(is_team=is_team, limit=min(limite, 25))
    
    if not players:
        return {
            "type": 4,
            "data": {
                "content": "❌ No hay jugadores registrados todavía.",
                "flags": 64
            }
        }
    
    # Build leaderboard text
    leaderboard_lines = []
    medals = ["🥇", "🥈", "🥉"]
    
    for i, player in enumerate(players, 1):
        medal = medals[i-1] if i <= 3 else f"`{i}.`"
        elo = player['team_elo'] if is_team else player['solo_elo']
        leaderboard_lines.append(f"{medal} **{player['aoe3_username']}** - {elo} ELO")
    
    embed = {
        "title": f"🏆 Ranking - {'Equipos (Team)' if is_team else '1v1 (Solo)'}",
        "description": "\n".join(leaderboard_lines),
        "color": 0xffd700
    }
    
    return {
        "type": 4,
        "data": {
            "embeds": [embed]
        }
    }


async def handle_matches(user_id: str, options: Dict) -> Dict:
    """Handle /aoe3_partidas command."""
    from .database import get_player_by_discord_id, get_player_by_aoe3_username, get_player_matches
    
    usuario = options.get('usuario')
    
    player = None
    if usuario is None:
        player = await get_player_by_discord_id(user_id)
        if not player:
            return {
                "type": 4,
                "data": {
                    "content": "❌ No estás registrado. Usa `/aoe3_registro` para registrarte.",
                    "flags": 64
                }
            }
    else:
        if usuario.startswith('<@') and usuario.endswith('>'):
            discord_id = usuario.strip('<@!>')
            player = await get_player_by_discord_id(discord_id)
        
        if not player:
            player = await get_player_by_aoe3_username(usuario)
        
        if not player:
            return {
                "type": 4,
                "data": {
                    "content": f"❌ No se encontró el jugador `{usuario}`.",
                    "flags": 64
                }
            }
    
    # Get matches
    matches = await get_player_matches(player['id'], limit=10)
    
    if not matches:
        return {
            "type": 4,
            "data": {
                "content": f"No hay partidas registradas para **{player['aoe3_username']}** todavía.",
                "flags": 64
            }
        }
    
    # Build embed
    embed = {
        "title": f"🎮 Partidas Recientes - {player['aoe3_username']}",
        "color": 0x3498db,
        "fields": []
    }
    
    for match in matches[:5]:
        result_emoji = "✅" if match['result'] == 'win' else "❌"
        map_name = match.get('map_name', 'Desconocido')
        opponent = match.get('opponent_username', 'Desconocido')
        
        timestamp = int(match['played_at'].timestamp())
        field_value = (
            f"{result_emoji} vs **{opponent}**\n"
            f"Mapa: {map_name} | <t:{timestamp}:R>"
        )
        
        embed['fields'].append({
            "name": match['game_mode'],
            "value": field_value,
            "inline": False
        })
    
    return {
        "type": 4,
        "data": {
            "embeds": [embed]
        }
    }


async def handle_civilization(options: Dict) -> Dict:
    """Handle /aoe3_civ command."""
    from .database import get_civilization, upsert_civilization
    from .scraper import AoE3Scraper
    
    nombre = options.get('nombre')
    
    # Try database first
    civ_data = await get_civilization(nombre)
    
    # If not found, scrape it
    if not civ_data:
        async with AoE3Scraper() as scraper:
            civ_id = nombre.lower().replace(' ', '_')
            civ_data = await scraper.get_civilization_details(civ_id)
            
            if not civ_data:
                return {
                    "type": 4,
                    "data": {
                        "content": f"❌ No se encontró información sobre la civilización `{nombre}`.",
                        "flags": 64
                    }
                }
            
            # Save to database
            await upsert_civilization(
                name=civ_data['name'],
                description=civ_data.get('description'),
                bonuses=civ_data.get('bonuses', []),
                unique_units=civ_data.get('unique_units', []),
                unique_buildings=civ_data.get('unique_buildings', [])
            )
    
    # Build embed
    embed = {
        "title": f"🏛️ {civ_data['name']}",
        "description": civ_data.get('description', 'Sin descripción disponible.'),
        "color": 0x9b59b6,
        "fields": []
    }
    
    if civ_data.get('bonuses'):
        bonuses_text = "\n".join(f"• {bonus}" for bonus in civ_data['bonuses'][:5])
        embed['fields'].append({
            "name": "Bonos",
            "value": bonuses_text,
            "inline": False
        })
    
    if civ_data.get('unique_units'):
        units_text = "\n".join(f"• {unit}" for unit in civ_data['unique_units'][:5])
        embed['fields'].append({
            "name": "Unidades Únicas",
            "value": units_text,
            "inline": False
        })
    
    return {
        "type": 4,
        "data": {
            "embeds": [embed]
        }
    }


async def handle_add_strategy(user_id: str, username: str, options: Dict) -> Dict:
    """Handle /aoe3_estrategia command."""
    from .database import get_player_by_discord_id, add_strategy
    
    # Verify user is registered
    player = await get_player_by_discord_id(user_id)
    if not player:
        return {
            "type": 4,
            "data": {
                "content": "❌ Debes estar registrado para compartir estrategias. Usa `/aoe3_registro`.",
                "flags": 64
            }
        }
    
    civilizacion = options.get('civilizacion')
    titulo = options.get('titulo')
    descripcion = options.get('descripcion')
    
    # Add to database
    strategy_id = await add_strategy(
        player_id=player['id'],
        civilization=civilizacion,
        title=titulo,
        description=descripcion
    )
    
    # Build response
    embed = {
        "title": "✅ Estrategia Compartida",
        "description": f"**{titulo}**\n\n{descripcion[:200]}{'...' if len(descripcion) > 200 else ''}",
        "color": 0x2ecc71,
        "fields": [
            {"name": "Civilización", "value": civilizacion, "inline": True},
            {"name": "Autor", "value": f"<@{user_id}>", "inline": True}
        ],
        "footer": {"text": "Los jugadores pueden votar con /aoe3_votar"}
    }
    
    return {
        "type": 4,
        "data": {
            "embeds": [embed]
        }
    }


async def handle_view_strategies(options: Dict) -> Dict:
    """Handle /aoe3_estrategias command."""
    from .database import get_strategies
    
    civilizacion = options.get('civilizacion')
    
    strategies = await get_strategies(civilization=civilizacion, limit=10)
    
    if not strategies:
        msg = "No hay estrategias disponibles"
        if civilizacion:
            msg += f" para {civilizacion}"
        msg += "."
        return {
            "type": 4,
            "data": {
                "content": msg,
                "flags": 64
            }
        }
    
    # Build embed
    title = "📚 Estrategias de la Comunidad"
    if civilizacion:
        title += f" - {civilizacion}"
    
    embed = {
        "title": title,
        "color": 0x3498db,
        "fields": [],
        "footer": {"text": "Usa /aoe3_votar <estrategia> para votar"}
    }
    
    for strat in strategies[:5]:
        votes = strat.get('vote_count', 0)
        vote_emoji = "⬆️" if votes > 0 else "➡️"
        
        field_value = (
            f"{strat['description'][:150]}{'...' if len(strat['description']) > 150 else ''}\n"
            f"{vote_emoji} {votes} votos | Por: {strat.get('author_username', 'Anónimo')}"
        )
        
        embed['fields'].append({
            "name": f"{strat['title']} ({strat['civilization']})",
            "value": field_value,
            "inline": False
        })
    
    return {
        "type": 4,
        "data": {
            "embeds": [embed]
        }
    }
