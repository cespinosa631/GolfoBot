"""
Background tasks for periodic match checking and data updates.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict

from .database import (
    get_all_players, update_player_elo, add_match, match_exists
)
from .scraper import AoE3Scraper

logger = logging.getLogger('aoe3.tasks')


class MatchChecker:
    """Background task to periodically check for new matches."""
    
    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self.task = None
    
    def start(self):
        """Start the match checking task."""
        if self.running:
            logger.warning("Match checker already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._check_matches_loop())
        logger.info("Match checker task started")
    
    def stop(self):
        """Stop the match checking task."""
        if not self.running:
            return
        
        self.running = False
        if self.task:
            self.task.cancel()
        logger.info("Match checker task stopped")
    
    async def _check_matches_loop(self):
        """Main loop for checking matches every 30 minutes."""
        # Wait for bot to be ready
        await self.bot.wait_until_ready()
        
        logger.info("Match checker loop starting...")
        
        while self.running and not self.bot.is_closed():
            try:
                await self._check_all_players()
            except Exception as e:
                logger.error(f"Error in match checking loop: {e}", exc_info=True)
            
            # Wait 30 minutes before next check
            await asyncio.sleep(1800)  # 30 minutes
    
    async def _check_all_players(self):
        """Check all registered players for new matches and ELO updates."""
        try:
            players = await get_all_players()
            logger.info(f"Checking {len(players)} registered players for updates")
            
            async with AoE3Scraper() as scraper:
                for player in players:
                    try:
                        await self._check_player(player, scraper)
                        # Small delay between players to avoid overwhelming the website
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.error(f"Error checking player {player['aoe3_username']}: {e}")
                        continue
            
            logger.info("Finished checking all players")
            
        except Exception as e:
            logger.error(f"Error checking all players: {e}", exc_info=True)
    
    async def _check_player(self, player: Dict, scraper: AoE3Scraper):
        """Check a single player for ELO updates and new matches."""
        try:
            player_id = player['aoe3_player_id']
            aoe3_username = player['aoe3_username']
            
            # Fetch current profile
            profile = await scraper.get_player_profile(player_id)
            if not profile:
                logger.warning(f"Could not fetch profile for {aoe3_username}")
                return
            
            # Update ELO if changed
            new_team_elo = profile.get('team_elo')
            new_solo_elo = profile.get('solo_elo')
            
            elo_changed = False
            if new_team_elo and new_team_elo != player.get('team_elo'):
                elo_changed = True
            if new_solo_elo and new_solo_elo != player.get('solo_elo'):
                elo_changed = True
            
            if elo_changed:
                await update_player_elo(
                    player['id'],
                    team_elo=new_team_elo,
                    solo_elo=new_solo_elo
                )
                logger.info(f"Updated ELO for {aoe3_username}: Team={new_team_elo}, Solo={new_solo_elo}")
            
            # Fetch recent matches
            matches = await scraper.get_match_history(player_id, limit=20)
            
            if not matches:
                return
            
            # Process new matches
            new_match_count = 0
            for match_data in matches:
                match_id = match_data.get('match_id')
                if not match_id:
                    continue
                
                # Check if match already exists
                if await match_exists(match_id):
                    continue
                
                # Add new match to database
                try:
                    await add_match(
                        match_id=match_id,
                        player_id=player['id'],
                        opponent_username=match_data.get('opponent'),
                        player_civilization=match_data.get('player_civ'),
                        opponent_civilization=match_data.get('opponent_civ'),
                        result=match_data.get('result'),
                        game_mode=match_data.get('game_mode', 'Supremacía'),
                        map_name=match_data.get('map_name'),
                        played_at=match_data.get('date') or datetime.utcnow()
                    )
                    new_match_count += 1
                except Exception as match_error:
                    logger.error(f"Error adding match {match_id}: {match_error}")
                    continue
            
            if new_match_count > 0:
                logger.info(f"Added {new_match_count} new matches for {aoe3_username}")
                
                # Notify in Discord thread if available
                await self._post_new_matches(player, new_match_count)
            
        except Exception as e:
            logger.error(f"Error checking player {player.get('aoe3_username', 'unknown')}: {e}")
    
    async def _post_new_matches(self, player: Dict, count: int):
        """Post notification about new matches to the results thread."""
        try:
            # Get the results thread
            RESULTADOS_THREAD_ID = 1461461460214349844
            
            for guild in self.bot.guilds:
                thread = guild.get_thread(RESULTADOS_THREAD_ID)
                if thread:
                    # Get Discord user mention if possible
                    discord_id = player.get('discord_id')
                    user_mention = f"<@{discord_id}>" if discord_id else player['aoe3_username']
                    
                    message = (
                        f"🎮 **Nuevas partidas detectadas**\n\n"
                        f"{user_mention} ha jugado {count} partida{'s' if count > 1 else ''} nueva{'s' if count > 1 else ''}.\n"
                        f"Usa `/aoe3_partidas {player['aoe3_username']}` para ver los detalles."
                    )
                    
                    await thread.send(message)
                    logger.info(f"Posted match notification for {player['aoe3_username']} to thread")
                    break
            
        except Exception as e:
            logger.error(f"Error posting match notification: {e}")


class ELOUpdater:
    """Background task to periodically update all player ELOs."""
    
    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self.task = None
    
    def start(self):
        """Start the ELO update task."""
        if self.running:
            logger.warning("ELO updater already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._update_elo_loop())
        logger.info("ELO updater task started")
    
    def stop(self):
        """Stop the ELO update task."""
        if not self.running:
            return
        
        self.running = False
        if self.task:
            self.task.cancel()
        logger.info("ELO updater task stopped")
    
    async def _update_elo_loop(self):
        """Main loop for updating ELOs every hour."""
        await self.bot.wait_until_ready()
        
        logger.info("ELO updater loop starting...")
        
        while self.running and not self.bot.is_closed():
            try:
                await self._update_all_elos()
            except Exception as e:
                logger.error(f"Error in ELO update loop: {e}", exc_info=True)
            
            # Wait 1 hour before next update
            await asyncio.sleep(3600)  # 1 hour
    
    async def _update_all_elos(self):
        """Update ELO for all registered players."""
        try:
            players = await get_all_players()
            logger.info(f"Updating ELO for {len(players)} players")
            
            async with AoE3Scraper() as scraper:
                for player in players:
                    try:
                        player_id = player['aoe3_player_id']
                        profile = await scraper.get_player_profile(player_id)
                        
                        if profile:
                            await update_player_elo(
                                player['id'],
                                team_elo=profile.get('team_elo'),
                                solo_elo=profile.get('solo_elo')
                            )
                            logger.debug(f"Updated ELO for {player['aoe3_username']}")
                        
                        # Small delay to avoid overwhelming the server
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"Error updating ELO for {player.get('aoe3_username', 'unknown')}: {e}")
                        continue
            
            logger.info("Finished updating all ELOs")
            
        except Exception as e:
            logger.error(f"Error updating all ELOs: {e}", exc_info=True)


def setup_tasks(bot):
    """Setup and start all background tasks."""
    match_checker = MatchChecker(bot)
    elo_updater = ELOUpdater(bot)
    
    match_checker.start()
    elo_updater.start()
    
    return match_checker, elo_updater
