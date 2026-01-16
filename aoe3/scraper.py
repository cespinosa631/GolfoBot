"""
Web scraper for aoe3-homecity.com to fetch player profiles, match history, and civilization data.
"""
import logging
import re
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger('aoe3.scraper')

BASE_URL = "https://aoe3-homecity.com"


class AoE3Scraper:
    """Scraper for aoe3-homecity.com website."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def _get_page(self, url: str) -> Optional[str]:
        """Fetch a page and return HTML content."""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    async def search_player(self, username: str) -> Optional[Dict]:
        """
        Search for a player by username and return their profile URL and basic info.
        
        Returns:
            Dict with keys: username, profile_url, player_id
        """
        try:
            search_url = f"{BASE_URL}/search?query={username}"
            html = await self._get_page(search_url)
            
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'lxml')
            
            # Look for player links in search results
            # The exact selectors will depend on the website structure
            # This is a generic approach that looks for player profile links
            player_links = soup.find_all('a', href=re.compile(r'/player/\d+'))
            
            if not player_links:
                logger.info(f"No player found for username: {username}")
                return None
            
            # Get the first match
            first_link = player_links[0]
            profile_url = BASE_URL + first_link['href']
            
            # Extract player ID from URL
            player_id_match = re.search(r'/player/(\d+)', first_link['href'])
            player_id = player_id_match.group(1) if player_id_match else None
            
            # Try to get the displayed username
            displayed_name = first_link.get_text(strip=True) or username
            
            return {
                'username': displayed_name,
                'profile_url': profile_url,
                'player_id': player_id
            }
            
        except Exception as e:
            logger.error(f"Error searching for player {username}: {e}")
            return None
    
    async def get_player_profile(self, player_id: str) -> Optional[Dict]:
        """
        Fetch detailed player profile including ELO ratings.
        
        Returns:
            Dict with keys: username, team_elo, solo_elo, level, games_played, wins, losses
        """
        try:
            profile_url = f"{BASE_URL}/player/{player_id}"
            html = await self._get_page(profile_url)
            
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'lxml')
            
            # Extract player information
            # These selectors are generic and will need to be adjusted based on actual site structure
            profile_data = {
                'username': None,
                'team_elo': None,
                'solo_elo': None,
                'level': None,
                'games_played': None,
                'wins': None,
                'losses': None
            }
            
            # Try to find username
            username_elem = soup.find('h1', class_=re.compile(r'player.*name', re.I))
            if not username_elem:
                username_elem = soup.find('h1')
            if username_elem:
                profile_data['username'] = username_elem.get_text(strip=True)
            
            # Look for ELO ratings
            # Common patterns: "Team ELO: 1500", "1v1 Rating: 1200", etc.
            text = soup.get_text()
            
            # Team ELO
            team_elo_match = re.search(r'(?:Team|Equipo|2v2|3v3|4v4).*?(?:ELO|Rating|Elo).*?(\d{3,4})', text, re.I)
            if team_elo_match:
                profile_data['team_elo'] = int(team_elo_match.group(1))
            
            # Solo/1v1 ELO
            solo_elo_match = re.search(r'(?:1v1|Solo|Supreme).*?(?:ELO|Rating|Elo).*?(\d{3,4})', text, re.I)
            if solo_elo_match:
                profile_data['solo_elo'] = int(solo_elo_match.group(1))
            
            # Level
            level_match = re.search(r'(?:Level|Nivel).*?(\d+)', text, re.I)
            if level_match:
                profile_data['level'] = int(level_match.group(1))
            
            # Games, wins, losses
            games_match = re.search(r'(?:Games|Partidas|Matches).*?(\d+)', text, re.I)
            if games_match:
                profile_data['games_played'] = int(games_match.group(1))
            
            wins_match = re.search(r'(?:Wins|Victorias).*?(\d+)', text, re.I)
            if wins_match:
                profile_data['wins'] = int(wins_match.group(1))
            
            losses_match = re.search(r'(?:Losses|Derrotas).*?(\d+)', text, re.I)
            if losses_match:
                profile_data['losses'] = int(losses_match.group(1))
            
            return profile_data
            
        except Exception as e:
            logger.error(f"Error fetching profile for player {player_id}: {e}")
            return None
    
    async def get_match_history(self, player_id: str, limit: int = 10) -> List[Dict]:
        """
        Fetch recent match history for a player.
        
        Returns:
            List of dicts with keys: match_id, date, map_name, game_mode, result, 
                                     player_civ, opponent, opponent_civ, duration
        """
        try:
            matches_url = f"{BASE_URL}/player/{player_id}/matches"
            html = await self._get_page(matches_url)
            
            if not html:
                return []
            
            soup = BeautifulSoup(html, 'lxml')
            matches = []
            
            # Look for match entries in tables or lists
            # This is a generic approach - adjust selectors based on actual site
            match_rows = soup.find_all('tr', class_=re.compile(r'match', re.I))
            if not match_rows:
                match_rows = soup.find_all('div', class_=re.compile(r'match', re.I))
            
            for row in match_rows[:limit]:
                try:
                    match_data = {
                        'match_id': None,
                        'date': None,
                        'map_name': None,
                        'game_mode': None,
                        'result': None,
                        'player_civ': None,
                        'opponent': None,
                        'opponent_civ': None,
                        'duration': None
                    }
                    
                    # Extract match ID from link
                    match_link = row.find('a', href=re.compile(r'/match/\d+'))
                    if match_link:
                        match_id = re.search(r'/match/(\d+)', match_link['href'])
                        if match_id:
                            match_data['match_id'] = match_id.group(1)
                    
                    # Extract other data from row text
                    row_text = row.get_text()
                    
                    # Look for win/loss indicators
                    if re.search(r'\b(win|victoria|won)\b', row_text, re.I):
                        match_data['result'] = 'win'
                    elif re.search(r'\b(loss|derrota|lost)\b', row_text, re.I):
                        match_data['result'] = 'loss'
                    
                    matches.append(match_data)
                    
                except Exception as e:
                    logger.debug(f"Error parsing match row: {e}")
                    continue
            
            return matches
            
        except Exception as e:
            logger.error(f"Error fetching match history for player {player_id}: {e}")
            return []
    
    async def get_civilization_list(self) -> List[Dict]:
        """
        Fetch list of all civilizations in the game.
        
        Returns:
            List of dicts with keys: civ_id, name, civ_url
        """
        try:
            civs_url = f"{BASE_URL}/civilizations"
            html = await self._get_page(civs_url)
            
            if not html:
                return []
            
            soup = BeautifulSoup(html, 'lxml')
            civilizations = []
            
            # Look for civilization links
            civ_links = soup.find_all('a', href=re.compile(r'/civilization/'))
            
            for link in civ_links:
                try:
                    civ_name = link.get_text(strip=True)
                    civ_url = BASE_URL + link['href'] if not link['href'].startswith('http') else link['href']
                    
                    # Extract civ ID if present in URL
                    civ_id_match = re.search(r'/civilization/([^/]+)', link['href'])
                    civ_id = civ_id_match.group(1) if civ_id_match else civ_name.lower().replace(' ', '_')
                    
                    civilizations.append({
                        'civ_id': civ_id,
                        'name': civ_name,
                        'civ_url': civ_url
                    })
                    
                except Exception as e:
                    logger.debug(f"Error parsing civilization link: {e}")
                    continue
            
            return civilizations
            
        except Exception as e:
            logger.error(f"Error fetching civilization list: {e}")
            return []
    
    async def get_civilization_details(self, civ_id: str) -> Optional[Dict]:
        """
        Fetch detailed information about a civilization.
        
        Returns:
            Dict with keys: name, description, bonuses, unique_units, unique_buildings, home_city_cards
        """
        try:
            civ_url = f"{BASE_URL}/civilization/{civ_id}"
            html = await self._get_page(civ_url)
            
            if not html:
                return None
            
            soup = BeautifulSoup(html, 'lxml')
            
            civ_data = {
                'name': None,
                'description': None,
                'bonuses': [],
                'unique_units': [],
                'unique_buildings': [],
                'home_city_cards': []
            }
            
            # Extract civilization name
            name_elem = soup.find('h1')
            if name_elem:
                civ_data['name'] = name_elem.get_text(strip=True)
            
            # Extract description
            desc_elem = soup.find('p', class_=re.compile(r'description', re.I))
            if not desc_elem:
                desc_elem = soup.find('div', class_=re.compile(r'description', re.I))
            if desc_elem:
                civ_data['description'] = desc_elem.get_text(strip=True)
            
            # Extract bonuses (look for list items or paragraphs with bonus keywords)
            bonus_section = soup.find(string=re.compile(r'bonus', re.I))
            if bonus_section:
                bonus_parent = bonus_section.parent
                if bonus_parent:
                    bonus_items = bonus_parent.find_next_siblings(['li', 'p'])
                    civ_data['bonuses'] = [item.get_text(strip=True) for item in bonus_items[:10]]
            
            # Extract unique units
            units_section = soup.find(string=re.compile(r'unique.*unit', re.I))
            if units_section:
                units_parent = units_section.parent
                if units_parent:
                    unit_items = units_parent.find_next_siblings(['li', 'p', 'div'])
                    civ_data['unique_units'] = [item.get_text(strip=True) for item in unit_items[:10]]
            
            return civ_data
            
        except Exception as e:
            logger.error(f"Error fetching civilization details for {civ_id}: {e}")
            return None


async def scrape_player_elo(username: str) -> Optional[Tuple[int, int]]:
    """
    Convenience function to quickly scrape player ELO ratings.
    
    Args:
        username: Player username to search for
    
    Returns:
        Tuple of (team_elo, solo_elo) or None if player not found
    """
    async with AoE3Scraper() as scraper:
        player = await scraper.search_player(username)
        if not player:
            return None
        
        profile = await scraper.get_player_profile(player['player_id'])
        if not profile:
            return None
        
        return (profile.get('team_elo'), profile.get('solo_elo'))
