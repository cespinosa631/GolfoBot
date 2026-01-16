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
        Search for a player by username on the leaderboard and return their info.
        
        Returns:
            Dict with keys: username, profile_url, player_id
        """
        try:
            # Search on Team Supremacy leaderboard (most common)
            leaderboard_url = f"{BASE_URL}/en/statistics/leaderboard/teamSupremacy"
            logger.info(f"Searching for player '{username}' on Team Supremacy leaderboard")
            html = await self._get_page(leaderboard_url)
            
            if not html:
                logger.warning("Failed to fetch Team Supremacy leaderboard")
                return None
            
            soup = BeautifulSoup(html, 'lxml')
            
            # The leaderboard has player links - look for username match
            # Player links are in format: /en/players/{id}/teamSupremacy
            username_lower = username.lower()
            
            # Find all player links in the table
            player_links = soup.find_all('a', href=re.compile(r'/en/players/\d+/'))
            logger.info(f"Found {len(player_links)} player links on Team Supremacy leaderboard")
            
            # Log first few player names for debugging
            if player_links:
                sample_names = [link.get_text(strip=True) for link in player_links[:10]]
                logger.info(f"Sample player names: {sample_names}")
            
            for link in player_links:
                player_name = link.get_text(strip=True)
                if player_name.lower() == username_lower or username_lower in player_name.lower():
                    # Extract player ID from href
                    href = link['href']
                    player_id_match = re.search(r'/players/(\d+)/', href)
                    
                    if player_id_match:
                        player_id = player_id_match.group(1)
                        profile_url = f"{BASE_URL}/en/players/{player_id}/teamSupremacy"
                        
                        logger.info(f"Found player: {player_name} (ID: {player_id})")
                        
                        return {
                            'username': player_name,
                            'profile_url': profile_url,
                            'player_id': player_id
                        }
            
            # If not found in team supremacy, try 1v1
            leaderboard_url_1v1 = f"{BASE_URL}/en/statistics/leaderboard/1vs1"
            logger.info(f"Player not found on Team Supremacy, trying 1v1 leaderboard")
            html = await self._get_page(leaderboard_url_1v1)
            
            if html:
                soup = BeautifulSoup(html, 'lxml')
                player_links = soup.find_all('a', href=re.compile(r'/en/players/\d+/'))
                logger.info(f"Found {len(player_links)} player links on 1v1 leaderboard")
                
                for link in player_links:
                    player_name = link.get_text(strip=True)
                    if player_name.lower() == username_lower or username_lower in player_name.lower():
                        href = link['href']
                        player_id_match = re.search(r'/players/(\d+)/', href)
                        
                        if player_id_match:
                            player_id = player_id_match.group(1)
                            profile_url = f"{BASE_URL}/en/players/{player_id}/1vs1"
                            
                            logger.info(f"Found player: {player_name} (ID: {player_id})")
                            
                            return {
                                'username': player_name,
                                'profile_url': profile_url,
                                'player_id': player_id
                            }
            
            logger.info(f"No player found for username: {username}")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for player {username}: {e}", exc_info=True)
            return None
    
    async def get_player_by_id(self, player_id: str) -> Optional[Dict]:
        """
        Get player info directly by player ID without searching.
        
        Args:
            player_id: The numerical player ID
            
        Returns:
            Dict with keys: username, profile_url, player_id
        """
        try:
            # Try to fetch the profile to verify it exists and get username
            profile = await self.get_player_profile(player_id)
            
            if profile and profile.get('username'):
                logger.info(f"Found player by ID {player_id}: {profile['username']}")
                return {
                    'username': profile['username'],
                    'profile_url': f"{BASE_URL}/en/players/{player_id}/teamSupremacy",
                    'player_id': player_id
                }
            
            logger.warning(f"Could not verify player with ID: {player_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching player by ID {player_id}: {e}", exc_info=True)
            return None
    
    async def get_player_profile(self, player_id: str) -> Optional[Dict]:
        """
        Fetch detailed player profile including ELO ratings.
        
        Returns:
            Dict with keys: username, team_elo, solo_elo, level, games_played, wins, losses
        """
        try:
            profile_data = {
                'username': None,
                'team_elo': None,
                'solo_elo': None,
                'level': None,
                'games_played': None,
                'wins': None,
                'losses': None
            }
            
            # Fetch Team Supremacy profile
            team_url = f"{BASE_URL}/en/players/{player_id}/teamSupremacy"
            logger.info(f"Fetching team profile: {team_url}")
            team_html = await self._get_page(team_url)
            
            if team_html:
                soup = BeautifulSoup(team_html, 'lxml')
                
                # Extract username from page title
                # Title format: "Profile (Username) | Supremacy (Team) | AOE 3 Home City"
                title = soup.find('title')
                if title:
                    title_text = title.get_text()
                    logger.info(f"Page title: {title_text}")
                    
                    # Extract username from between parentheses
                    match = re.search(r'Profile \((.+?)\)', title_text)
                    if match:
                        profile_data['username'] = match.group(1).strip()
                        logger.info(f"Extracted username: {profile_data['username']}")
                    else:
                        # Fallback: try to find span with player name
                        spans = soup.find_all('span', limit=50)
                        for span in spans:
                            text = span.get_text(strip=True)
                            if text and len(text) > 3 and len(text) < 50 and not text.isdigit():
                                profile_data['username'] = text
                                logger.info(f"Extracted username from span: {text}")
                                break
                
                # Look for ELO - The pattern in the HTML is: {rank}ELO{actual_elo}
                # Example: "1210ELO1409" where 1210 is rank display, 1409 is actual ELO
                text = soup.get_text()
                
                # Find the pattern: number + "ELO" + number
                elo_match = re.search(r'(\d{3,4})ELO(\d{3,4})', text)
                if elo_match:
                    # The second number is the actual ELO rating
                    profile_data['team_elo'] = int(elo_match.group(2))
                    logger.info(f"Found team ELO: {profile_data['team_elo']}")
            
            # Fetch 1v1 profile
            solo_url = f"{BASE_URL}/en/players/{player_id}/1vs1"
            logger.info(f"Fetching 1v1 profile: {solo_url}")
            solo_html = await self._get_page(solo_url)
            
            if solo_html:
                soup = BeautifulSoup(solo_html, 'lxml')
                text = soup.get_text()
                
                # Same pattern for 1v1 ELO: {rank}ELO{actual_elo}
                elo_match = re.search(r'(\d{3,4})ELO(\d{3,4})', text)
                if elo_match:
                    profile_data['solo_elo'] = int(elo_match.group(2))
                    logger.info(f"Found 1v1 ELO: {profile_data['solo_elo']}")
            
            logger.info(f"Fetched profile for player {player_id}: Team ELO={profile_data['team_elo']}, Solo ELO={profile_data['solo_elo']}")
            return profile_data
            
        except Exception as e:
            logger.error(f"Error fetching profile for player {player_id}: {e}", exc_info=True)
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
