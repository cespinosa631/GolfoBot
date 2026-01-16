"""
Discord slash commands for AoE3 integration.
"""
import logging
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from .database import (
    register_player, get_player_by_discord_id, get_player_by_aoe3_username,
    update_player_elo, get_leaderboard, get_recent_matches, get_player_matches,
    get_civilization, upsert_civilization, get_strategies, add_strategy, vote_strategy
)
from .scraper import AoE3Scraper, scrape_player_elo

logger = logging.getLogger('aoe3.commands')

# Channel and thread IDs for AoE3 content
AOE3_CHANNEL_ID = 1458301427096096933
INFO_THREAD_ID = 1461462009898991717
RESULTADOS_THREAD_ID = 1461461460214349844
ESTRATEGIAS_THREAD_ID = 1461461182417473599


def is_aoe3_channel():
    """Decorator to check if command is used in the AoE3 channel."""
    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != AOE3_CHANNEL_ID:
            return False
        return True
    return app_commands.check(predicate)


class AoE3Commands(commands.Cog):
    """Cog containing all AoE3-related slash commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="aoe3_registro", description="Registra tu usuario de AoE3 para seguimiento de ELO")
    @app_commands.describe(username="Tu nombre de usuario en Age of Empires 3: Definitive Edition")
    async def register_player(self, interaction: discord.Interaction, username: str):
        """Register your AoE3 username for ELO tracking."""
        await interaction.response.defer(thinking=True)
        
        try:
            # Check if user is already registered
            existing = await get_player_by_discord_id(str(interaction.user.id))
            if existing:
                await interaction.followup.send(
                    f"❌ Ya estás registrado con el usuario `{existing['aoe3_username']}`.\n"
                    f"Para cambiar tu usuario, contacta a un administrador.",
                    ephemeral=True
                )
                return
            
            # Search for player on aoe3-homecity.com
            async with AoE3Scraper() as scraper:
                player_data = await scraper.search_player(username)
                
                if not player_data:
                    await interaction.followup.send(
                        f"❌ No se encontró el jugador `{username}` en aoe3-homecity.com.\n"
                        f"Verifica que el nombre sea correcto.",
                        ephemeral=True
                    )
                    return
                
                # Fetch current ELO
                profile = await scraper.get_player_profile(player_data['player_id'])
                team_elo = profile.get('team_elo') if profile else None
                solo_elo = profile.get('solo_elo') if profile else None
            
            # Register in database
            profile_url = f"https://aoe3-homecity.com/en/players/{player_data['player_id']}/teamSupremacy"
            await register_player(
                discord_id=str(interaction.user.id),
                discord_username=interaction.user.name,
                aoe3_username=player_data['username'],
                aoe3_profile_url=profile_url,
                elo_team=team_elo,
                elo_1v1=solo_elo
            )
            
            embed = discord.Embed(
                title="✅ Registro Exitoso",
                description=f"Usuario **{player_data['username']}** registrado correctamente.",
                color=discord.Color.green()
            )
            
            if team_elo or solo_elo:
                elo_text = []
                if team_elo:
                    elo_text.append(f"**Equipo:** {team_elo}")
                if solo_elo:
                    elo_text.append(f"**1v1:** {solo_elo}")
                embed.add_field(name="ELO Actual", value=" | ".join(elo_text), inline=False)
            
            embed.add_field(
                name="Seguimiento Automático",
                value="Tu ELO se actualizará automáticamente cada 30 minutos.",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error registering player: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al registrar usuario. Intenta nuevamente más tarde.",
                ephemeral=True
            )
    
    @app_commands.command(name="aoe3_elo", description="Consulta el ELO de un jugador")
    @app_commands.describe(usuario="Usuario de Discord o nombre en AoE3 (opcional, por defecto tu propio ELO)")
    async def check_elo(self, interaction: discord.Interaction, usuario: Optional[str] = None):
        """Check ELO rating for yourself or another player."""
        await interaction.response.defer(thinking=True)
        
        try:
            player = None
            
            if usuario is None:
                # Check own ELO
                player = await get_player_by_discord_id(str(interaction.user.id))
                if not player:
                    await interaction.followup.send(
                        "❌ No estás registrado. Usa `/aoe3_registro` para registrarte.",
                        ephemeral=True
                    )
                    return
            else:
                # Try to find by mention
                if usuario.startswith('<@') and usuario.endswith('>'):
                    discord_id = usuario.strip('<@!>')
                    player = await get_player_by_discord_id(discord_id)
                
                # Try to find by AoE3 username
                if not player:
                    player = await get_player_by_aoe3_username(usuario)
                
                if not player:
                    await interaction.followup.send(
                        f"❌ No se encontró el jugador `{usuario}`.",
                        ephemeral=True
                    )
                    return
            
            # Create embed with player info
            embed = discord.Embed(
                title=f"📊 ELO de {player['aoe3_username']}",
                color=discord.Color.blue()
            )
            
            if player['elo_team'] or player['elo_1v1']:
                elo_lines = []
                if player['elo_team']:
                    elo_lines.append(f"**Equipo (Team):** {player['elo_team']}")
                if player['elo_1v1']:
                    elo_lines.append(f"**1v1 (Solo):** {player['elo_1v1']}")
                embed.description = "\n".join(elo_lines)
            else:
                embed.description = "No hay datos de ELO disponibles."
            
            # Add last update time
            if player.get('last_updated'):
                timestamp = int(player['last_updated'].timestamp())
                embed.add_field(
                    name="Última Actualización",
                    value=f"<t:{timestamp}:R>",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error checking ELO: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al consultar ELO. Intenta nuevamente más tarde.",
                ephemeral=True
            )
    
    @app_commands.command(name="aoe3_leaderboard", description="Muestra el ranking de jugadores registrados")
    @app_commands.describe(
        modo="Tipo de ranking: team (equipos) o solo (1v1)",
        limite="Número de jugadores a mostrar (por defecto 10)"
    )
    @app_commands.choices(modo=[
        app_commands.Choice(name="Equipos (Team)", value="team"),
        app_commands.Choice(name="1v1 (Solo)", value="solo")
    ])
    async def leaderboard(
        self, 
        interaction: discord.Interaction, 
        modo: app_commands.Choice[str],
        limite: Optional[int] = 10
    ):
        """Show leaderboard of registered players."""
        await interaction.response.defer(thinking=True)
        
        try:
            is_team = modo.value == "team"
            players = await get_leaderboard(is_team=is_team, limit=min(limite, 25))
            
            if not players:
                await interaction.followup.send(
                    "❌ No hay jugadores registrados todavía.",
                    ephemeral=True
                )
                return
            
            # Create leaderboard embed
            embed = discord.Embed(
                title=f"🏆 Ranking - {modo.name}",
                color=discord.Color.gold()
            )
            
            leaderboard_lines = []
            medals = ["🥇", "🥈", "🥉"]
            
            for i, player in enumerate(players, 1):
                medal = medals[i-1] if i <= 3 else f"`{i}.`"
                elo = player['elo_team'] if is_team else player['elo_1v1']
                leaderboard_lines.append(f"{medal} **{player['aoe3_username']}** - {elo} ELO")
            
            embed.description = "\n".join(leaderboard_lines)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al obtener el ranking. Intenta nuevamente más tarde.",
                ephemeral=True
            )
    
    @app_commands.command(name="aoe3_partidas", description="Muestra las partidas recientes de un jugador")
    @app_commands.describe(usuario="Usuario de Discord o nombre en AoE3 (opcional, por defecto tus partidas)")
    async def recent_matches(self, interaction: discord.Interaction, usuario: Optional[str] = None):
        """Show recent matches for a player."""
        await interaction.response.defer(thinking=True)
        
        try:
            player = None
            
            if usuario is None:
                player = await get_player_by_discord_id(str(interaction.user.id))
                if not player:
                    await interaction.followup.send(
                        "❌ No estás registrado. Usa `/aoe3_registro` para registrarte.",
                        ephemeral=True
                    )
                    return
            else:
                if usuario.startswith('<@') and usuario.endswith('>'):
                    discord_id = usuario.strip('<@!>')
                    player = await get_player_by_discord_id(discord_id)
                
                if not player:
                    player = await get_player_by_aoe3_username(usuario)
                
                if not player:
                    await interaction.followup.send(
                        f"❌ No se encontró el jugador `{usuario}`.",
                        ephemeral=True
                    )
                    return
            
            # Get matches from database
            matches = await get_player_matches(player['id'], limit=10)
            
            if not matches:
                await interaction.followup.send(
                    f"No hay partidas registradas para **{player['aoe3_username']}** todavía.",
                    ephemeral=True
                )
                return
            
            # Create matches embed
            embed = discord.Embed(
                title=f"🎮 Partidas Recientes - {player['aoe3_username']}",
                color=discord.Color.blue()
            )
            
            for match in matches[:5]:  # Show up to 5 matches
                result_emoji = "✅" if match['result'] == 'win' else "❌"
                map_name = match.get('map_name', 'Desconocido')
                opponent = match.get('opponent_username', 'Desconocido')
                
                timestamp = int(match['played_at'].timestamp())
                field_value = (
                    f"{result_emoji} vs **{opponent}**\n"
                    f"Mapa: {map_name} | <t:{timestamp}:R>"
                )
                
                embed.add_field(
                    name=f"{match['game_mode']}",
                    value=field_value,
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching matches: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al obtener partidas. Intenta nuevamente más tarde.",
                ephemeral=True
            )
    
    @app_commands.command(name="aoe3_civ", description="Información sobre una civilización")
    @app_commands.describe(nombre="Nombre de la civilización (ej: Españoles, Británicos, Otomanos)")
    async def civilization_info(self, interaction: discord.Interaction, nombre: str):
        """Get information about a civilization."""
        await interaction.response.defer(thinking=True)
        
        try:
            # Try to get from database first
            civ_data = await get_civilization(nombre)
            
            # If not in database, scrape it
            if not civ_data:
                async with AoE3Scraper() as scraper:
                    civ_id = nombre.lower().replace(' ', '_')
                    civ_data = await scraper.get_civilization_details(civ_id)
                    
                    if not civ_data:
                        await interaction.followup.send(
                            f"❌ No se encontró información sobre la civilización `{nombre}`.",
                            ephemeral=True
                        )
                        return
                    
                    # Save to database for future queries
                    await upsert_civilization(
                        name=civ_data['name'],
                        description=civ_data.get('description'),
                        bonuses=civ_data.get('bonuses', []),
                        unique_units=civ_data.get('unique_units', []),
                        unique_buildings=civ_data.get('unique_buildings', [])
                    )
            
            # Create embed
            embed = discord.Embed(
                title=f"🏛️ {civ_data['name']}",
                description=civ_data.get('description', 'Sin descripción disponible.'),
                color=discord.Color.purple()
            )
            
            if civ_data.get('bonuses'):
                bonuses_text = "\n".join(f"• {bonus}" for bonus in civ_data['bonuses'][:5])
                embed.add_field(name="Bonos", value=bonuses_text, inline=False)
            
            if civ_data.get('unique_units'):
                units_text = "\n".join(f"• {unit}" for unit in civ_data['unique_units'][:5])
                embed.add_field(name="Unidades Únicas", value=units_text, inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching civilization info: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al obtener información de civilización. Intenta nuevamente más tarde.",
                ephemeral=True
            )
    
    @app_commands.command(name="aoe3_estrategia", description="Comparte una estrategia para AoE3")
    @app_commands.describe(
        civilizacion="Civilización para la estrategia",
        titulo="Título breve de la estrategia",
        descripcion="Descripción detallada de la estrategia"
    )
    async def add_strategy(
        self, 
        interaction: discord.Interaction, 
        civilizacion: str,
        titulo: str,
        descripcion: str
    ):
        """Submit a strategy for the community."""
        await interaction.response.defer(thinking=True)
        
        try:
            # Verify user is registered
            player = await get_player_by_discord_id(str(interaction.user.id))
            if not player:
                await interaction.followup.send(
                    "❌ Debes estar registrado para compartir estrategias. Usa `/aoe3_registro`.",
                    ephemeral=True
                )
                return
            
            # Add strategy to database
            strategy_id = await add_strategy(
                player_id=player['id'],
                civilization=civilizacion,
                title=titulo,
                description=descripcion
            )
            
            # Create embed for confirmation
            embed = discord.Embed(
                title=f"✅ Estrategia Compartida",
                description=f"**{titulo}**\n\n{descripcion[:200]}{'...' if len(descripcion) > 200 else ''}",
                color=discord.Color.green()
            )
            embed.add_field(name="Civilización", value=civilizacion, inline=True)
            embed.add_field(name="Autor", value=interaction.user.mention, inline=True)
            embed.set_footer(text="Los jugadores pueden votar con /aoe3_votar")
            
            await interaction.followup.send(embed=embed)
            
            # Try to post to strategies thread if available
            try:
                thread = interaction.guild.get_thread(ESTRATEGIAS_THREAD_ID)
                if thread:
                    await thread.send(embed=embed)
            except Exception as thread_error:
                logger.debug(f"Could not post to strategies thread: {thread_error}")
            
        except Exception as e:
            logger.error(f"Error adding strategy: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al guardar estrategia. Intenta nuevamente más tarde.",
                ephemeral=True
            )
    
    @app_commands.command(name="aoe3_estrategias", description="Ver estrategias de la comunidad")
    @app_commands.describe(civilizacion="Filtrar por civilización (opcional)")
    async def view_strategies(self, interaction: discord.Interaction, civilizacion: Optional[str] = None):
        """View community strategies."""
        await interaction.response.defer(thinking=True)
        
        try:
            strategies = await get_strategies(civilization=civilizacion, limit=10)
            
            if not strategies:
                msg = f"No hay estrategias disponibles"
                if civilizacion:
                    msg += f" para {civilizacion}"
                msg += "."
                await interaction.followup.send(msg, ephemeral=True)
                return
            
            # Create embed with strategies
            title = "📚 Estrategias de la Comunidad"
            if civilizacion:
                title += f" - {civilizacion}"
            
            embed = discord.Embed(
                title=title,
                color=discord.Color.blue()
            )
            
            for strat in strategies[:5]:
                votes = strat.get('vote_count', 0)
                vote_emoji = "⬆️" if votes > 0 else "➡️"
                
                field_value = (
                    f"{strat['description'][:150]}{'...' if len(strat['description']) > 150 else ''}\n"
                    f"{vote_emoji} {votes} votos | Por: {strat.get('author_username', 'Anónimo')}"
                )
                
                embed.add_field(
                    name=f"{strat['title']} ({strat['civilization']})",
                    value=field_value,
                    inline=False
                )
            
            embed.set_footer(text="Usa /aoe3_votar <estrategia> para votar")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching strategies: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Error al obtener estrategias. Intenta nuevamente más tarde.",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(AoE3Commands(bot))
