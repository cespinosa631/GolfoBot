"""
Database connection and models for AoE3 integration.

This module handles all PostgreSQL database operations for:
- Player registration and tracking
- Match history recording
- Civilization data caching
- Community strategies and voting
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger, Text, 
    Boolean, DateTime, ForeignKey, CheckConstraint, JSON, Index
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.future import select
import logging

logger = logging.getLogger('aoe3.database')

# Get database URL from Railway environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    logger.warning("DATABASE_URL not set - AoE3 database features will be disabled")
    # Create a dummy base for when DB is not configured
    Base = declarative_base()
    engine = None
    AsyncSessionLocal = None
else:
    # Railway uses postgres://, SQLAlchemy 1.4+ requires postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    
    # For async operations, use asyncpg driver
    ASYNC_DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://')
    
    # Create async engine with connection pooling
    engine = create_async_engine(
        ASYNC_DATABASE_URL, 
        echo=False,  # Set to True for SQL debugging
        pool_pre_ping=True,  # Verify connections before using
        pool_size=5,  # Connection pool size
        max_overflow=10  # Extra connections beyond pool_size
    )
    
    AsyncSessionLocal = async_sessionmaker(
        engine, 
        class_=AsyncSession, 
        expire_on_commit=False
    )
    
    Base = declarative_base()


# ==================== Models ====================

class Player(Base):
    """Represents a Discord user registered for AoE3 tracking."""
    __tablename__ = 'players'
    
    discord_id = Column(BigInteger, primary_key=True)
    discord_username = Column(String(255), nullable=False)
    aoe3_username = Column(String(255), nullable=False, unique=True)
    aoe3_profile_url = Column(Text)
    elo_1v1 = Column(Integer)
    elo_team = Column(Integer)
    favorite_civ = Column(String(100))
    last_checked_at = Column(DateTime)
    last_match_id = Column(String(255))
    registered_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    won_matches = relationship(
        "Match", 
        foreign_keys="Match.winner_discord_id", 
        back_populates="winner"
    )
    lost_matches = relationship(
        "Match", 
        foreign_keys="Match.loser_discord_id", 
        back_populates="loser"
    )
    strategies = relationship("Strategy", back_populates="author")
    
    def __repr__(self):
        return f"<Player(discord_id={self.discord_id}, aoe3={self.aoe3_username})>"


class Match(Base):
    """Represents a recorded AoE3 match."""
    __tablename__ = 'matches'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String(255), unique=True, nullable=False)
    
    # Winner details
    winner_discord_id = Column(BigInteger, ForeignKey('players.discord_id', ondelete='SET NULL'))
    winner_aoe3_name = Column(String(255), nullable=False)
    winner_civ = Column(String(100))
    winner_elo_change = Column(Integer)
    
    # Loser details
    loser_discord_id = Column(BigInteger, ForeignKey('players.discord_id', ondelete='SET NULL'))
    loser_aoe3_name = Column(String(255), nullable=False)
    loser_civ = Column(String(100))
    loser_elo_change = Column(Integer)
    
    # Match metadata
    map_name = Column(String(255))
    duration_seconds = Column(Integer)
    played_at = Column(DateTime)
    posted_to_discord = Column(Boolean, default=False)
    posted_at = Column(DateTime)
    
    # Relationships
    winner = relationship(
        "Player", 
        foreign_keys=[winner_discord_id], 
        back_populates="won_matches"
    )
    loser = relationship(
        "Player", 
        foreign_keys=[loser_discord_id], 
        back_populates="lost_matches"
    )
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_matches_played_at', 'played_at'),
        Index('idx_matches_discord_ids', 'winner_discord_id', 'loser_discord_id'),
    )
    
    def __repr__(self):
        return f"<Match(id={self.id}, {self.winner_aoe3_name} vs {self.loser_aoe3_name})>"


class Civilization(Base):
    """Represents an AoE3 civilization with cached data."""
    __tablename__ = 'civilizations'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    bonuses = Column(JSON)  # Array of civilization bonuses
    unique_units = Column(JSON)  # Array of unique units
    unique_buildings = Column(JSON)  # Array of unique buildings
    home_city_cards = Column(JSON)  # Array of home city cards
    strengths = Column(JSON)  # Array of strengths
    weaknesses = Column(JSON)  # Array of weaknesses
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<Civilization(name={self.name})>"


class Strategy(Base):
    """Represents a community-submitted strategy."""
    __tablename__ = 'strategies'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    civ = Column(String(100), nullable=False)
    vs_civ = Column(String(100))  # Optional: strategy against specific civ
    map = Column(String(255))  # Optional: map-specific strategy
    strategy_text = Column(Text, nullable=False)
    author_discord_id = Column(
        BigInteger, 
        ForeignKey('players.discord_id', ondelete='CASCADE'), 
        nullable=False
    )
    votes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    author = relationship("Player", back_populates="strategies")
    vote_records = relationship("StrategyVote", back_populates="strategy")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_strategies_civ', 'civ', 'vs_civ'),
        Index('idx_strategies_votes', 'votes'),
    )
    
    def __repr__(self):
        return f"<Strategy(id={self.id}, civ={self.civ}, votes={self.votes})>"


class StrategyVote(Base):
    """Represents a vote on a strategy (upvote/downvote)."""
    __tablename__ = 'strategy_votes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(
        Integer, 
        ForeignKey('strategies.id', ondelete='CASCADE'), 
        nullable=False
    )
    voter_discord_id = Column(
        BigInteger, 
        ForeignKey('players.discord_id', ondelete='CASCADE'), 
        nullable=False
    )
    vote_value = Column(Integer, CheckConstraint('vote_value IN (-1, 1)'), nullable=False)
    voted_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    strategy = relationship("Strategy", back_populates="vote_records")
    
    # Ensure one vote per user per strategy
    __table_args__ = (
        Index('idx_strategy_votes_unique', 'strategy_id', 'voter_discord_id', unique=True),
    )
    
    def __repr__(self):
        return f"<StrategyVote(strategy_id={self.strategy_id}, vote={self.vote_value})>"


# ==================== Database Initialization ====================

async def init_db():
    """Initialize database tables. Safe to call multiple times."""
    if not engine:
        logger.warning("Database engine not initialized - skipping table creation")
        return
    
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"❌ Failed to create database tables: {e}")
        raise


# ==================== Database Operations ====================

async def register_player(
    discord_id: str, 
    discord_username: str, 
    aoe3_username: str, 
    aoe3_player_id: str = None,
    team_elo: int = None,
    solo_elo: int = None
) -> Dict:
    """Register a new player or update existing player."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        # Check if player already exists
        result = await session.execute(
            select(Player).where(Player.discord_id == int(discord_id))
        )
        player = result.scalar_one_or_none()
        
        if player:
            # Update existing player
            player.discord_username = discord_username
            player.aoe3_username = aoe3_username
            if aoe3_player_id:
                player.aoe3_player_id = aoe3_player_id
            if team_elo is not None:
                player.team_elo = team_elo
            if solo_elo is not None:
                player.solo_elo = solo_elo
        else:
            # Create new player
            player = Player(
                discord_id=int(discord_id),
                discord_username=discord_username,
                aoe3_username=aoe3_username,
                aoe3_player_id=aoe3_player_id,
                team_elo=team_elo,
                solo_elo=solo_elo
            )
            session.add(player)
        
        await session.commit()
        await session.refresh(player)
        
        # Return as dict for easier use
        return {
            'id': player.id,
            'discord_id': str(player.discord_id),
            'discord_username': player.discord_username,
            'aoe3_username': player.aoe3_username,
            'aoe3_player_id': player.aoe3_player_id,
            'team_elo': player.team_elo,
            'solo_elo': player.solo_elo
        }


async def get_player_by_discord_id(discord_id: str) -> Optional[Dict]:
    """Get player by Discord ID."""
    if not AsyncSessionLocal:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.discord_id == int(discord_id))
        )
        player = result.scalar_one_or_none()
        if not player:
            return None
        
        return {
            'id': player.id,
            'discord_id': str(player.discord_id),
            'discord_username': player.discord_username,
            'aoe3_username': player.aoe3_username,
            'aoe3_player_id': player.aoe3_player_id,
            'team_elo': player.team_elo,
            'solo_elo': player.solo_elo,
            'last_updated': player.last_updated
        }


async def get_player_by_aoe3_username(aoe3_username: str) -> Optional[Dict]:
    """Get player by AoE3 username."""
    if not AsyncSessionLocal:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.aoe3_username == aoe3_username)
        )
        player = result.scalar_one_or_none()
        if not player:
            return None
        
        return {
            'id': player.id,
            'discord_id': str(player.discord_id),
            'discord_username': player.discord_username,
            'aoe3_username': player.aoe3_username,
            'aoe3_player_id': player.aoe3_player_id,
            'team_elo': player.team_elo,
            'solo_elo': player.solo_elo,
            'last_updated': player.last_updated
        }


async def get_all_players() -> List[Dict]:
    """Get all registered players."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Player))
        players = result.scalars().all()
        
        return [{
            'id': p.id,
            'discord_id': str(p.discord_id),
            'discord_username': p.discord_username,
            'aoe3_username': p.aoe3_username,
            'aoe3_player_id': p.aoe3_player_id,
            'team_elo': p.team_elo,
            'solo_elo': p.solo_elo,
            'last_updated': p.last_updated
        } for p in players]


async def update_player_elo(
    player_id: int, 
    team_elo: int = None, 
    solo_elo: int = None
):
    """Update player ELO ratings."""
    if not AsyncSessionLocal:
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.id == player_id)
        )
        player = result.scalar_one_or_none()
        
        if player:
            if team_elo is not None:
                player.team_elo = team_elo
            if solo_elo is not None:
                player.solo_elo = solo_elo
            player.last_updated = datetime.utcnow()
            await session.commit()


async def add_match(
    match_id: str,
    player_id: int,
    opponent_username: str = None,
    player_civilization: str = None,
    opponent_civilization: str = None,
    result: str = None,
    game_mode: str = 'Supremacía',
    map_name: str = None,
    played_at: datetime = None
) -> Dict:
    """Add a new match to database."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        match = Match(
            match_id=match_id,
            player_id=player_id,
            opponent_username=opponent_username,
            player_civilization=player_civilization,
            opponent_civilization=opponent_civilization,
            result=result,
            game_mode=game_mode,
            map_name=map_name,
            played_at=played_at or datetime.utcnow()
        )
        session.add(match)
        await session.commit()
        await session.refresh(match)
        
        return {
            'id': match.id,
            'match_id': match.match_id,
            'player_id': match.player_id,
            'opponent_username': match.opponent_username,
            'result': match.result,
            'game_mode': match.game_mode,
            'map_name': match.map_name,
            'played_at': match.played_at
        }


async def match_exists(match_id: str) -> bool:
    """Check if a match has already been recorded."""
    if not AsyncSessionLocal:
        return False
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Match).where(Match.match_id == match_id)
        )
        return result.scalar_one_or_none() is not None


async def get_recent_matches(limit: int = 10) -> List[Match]:
    """Get recent matches, ordered by play date."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Match)
            .order_by(Match.played_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


async def get_player_matches(player_id: int, limit: int = 20) -> List[Dict]:
    """Get matches for a specific player."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Match)
            .where(Match.player_id == player_id)
            .order_by(Match.played_at.desc())
            .limit(limit)
        )
        matches = result.scalars().all()
        
        return [{
            'id': m.id,
            'match_id': m.match_id,
            'player_id': m.player_id,
            'opponent_username': m.opponent_username,
            'player_civilization': m.player_civilization,
            'opponent_civilization': m.opponent_civilization,
            'result': m.result,
            'game_mode': m.game_mode,
            'map_name': m.map_name,
            'played_at': m.played_at
        } for m in matches]


async def get_leaderboard(is_team: bool = False, limit: int = 10) -> List[Dict]:
    """Get ELO leaderboard."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        if is_team:
            result = await session.execute(
                select(Player)
                .where(Player.team_elo.isnot(None))
                .order_by(Player.team_elo.desc())
                .limit(limit)
            )
        else:  # solo/1v1
            result = await session.execute(
                select(Player)
                .where(Player.solo_elo.isnot(None))
                .order_by(Player.solo_elo.desc())
                .limit(limit)
            )
        players = result.scalars().all()
        
        return [{
            'id': p.id,
            'discord_id': str(p.discord_id),
            'aoe3_username': p.aoe3_username,
            'team_elo': p.team_elo,
            'solo_elo': p.solo_elo
        } for p in players]


# ==================== Civilization Operations ====================

async def upsert_civilization(
    name: str,
    description: str = None,
    bonuses: List[str] = None,
    unique_units: List[str] = None,
    unique_buildings: List[str] = None
) -> Dict:
    """Create or update civilization data."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        # Check if civ exists
        result = await session.execute(
            select(Civilization).where(Civilization.name == name)
        )
        civ = result.scalar_one_or_none()
        
        if civ:
            # Update existing
            if description is not None:
                civ.description = description
            if bonuses is not None:
                civ.bonuses = bonuses
            if unique_units is not None:
                civ.unique_units = unique_units
            if unique_buildings is not None:
                civ.unique_buildings = unique_buildings
            civ.last_updated = datetime.utcnow()
        else:
            # Create new
            civ = Civilization(
                name=name,
                description=description,
                bonuses=bonuses or [],
                unique_units=unique_units or [],
                unique_buildings=unique_buildings or []
            )
            session.add(civ)
        
        await session.commit()
        await session.refresh(civ)
        
        return {
            'name': civ.name,
            'description': civ.description,
            'bonuses': civ.bonuses,
            'unique_units': civ.unique_units,
            'unique_buildings': civ.unique_buildings
        }


async def get_civilization(name: str) -> Optional[Dict]:
    """Get civilization by name."""
    if not AsyncSessionLocal:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Civilization).where(Civilization.name.ilike(f"%{name}%"))
        )
        civ = result.scalar_one_or_none()
        if not civ:
            return None
        
        return {
            'name': civ.name,
            'description': civ.description,
            'bonuses': civ.bonuses,
            'unique_units': civ.unique_units,
            'unique_buildings': civ.unique_buildings
        }


async def get_all_civilizations() -> List[Dict]:
    """Get all civilizations."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Civilization))
        civs = result.scalars().all()
        
        return [{
            'name': c.name,
            'description': c.description
        } for c in civs]


# ==================== Strategy Operations ====================

async def add_strategy(
    player_id: int,
    civilization: str,
    title: str,
    description: str
) -> int:
    """Add a new community strategy."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        strategy = Strategy(
            player_id=player_id,
            civilization=civilization,
            title=title,
            description=description
        )
        session.add(strategy)
        await session.commit()
        await session.refresh(strategy)
        return strategy.id


async def get_strategies(civilization: str = None, limit: int = 10) -> List[Dict]:
    """Get strategies, optionally filtered by civilization."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        if civilization:
            query = select(Strategy).where(Strategy.civilization.ilike(f"%{civilization}%"))
        else:
            query = select(Strategy)
        
        query = query.order_by(Strategy.votes.desc()).limit(limit)
        
        result = await session.execute(query)
        strategies = result.scalars().all()
        
        # Get author usernames
        strategy_list = []
        for s in strategies:
            # Get player info for author
            player_result = await session.execute(
                select(Player).where(Player.id == s.player_id)
            )
            player = player_result.scalar_one_or_none()
            
            strategy_list.append({
                'id': s.id,
                'civilization': s.civilization,
                'title': s.title,
                'description': s.description,
                'votes': s.votes,
                'vote_count': s.votes,  # Alias for compatibility
                'author_username': player.discord_username if player else 'Unknown',
                'created_at': s.created_at
            })
        
        return strategy_list


async def vote_strategy(strategy_id: int, voter_discord_id: int, vote_value: int) -> bool:
    """Vote on a strategy (1 for upvote, -1 for downvote)."""
    if not AsyncSessionLocal:
        return False
    
    if vote_value not in (-1, 1):
        raise ValueError("vote_value must be 1 or -1")
    
    async with AsyncSessionLocal() as session:
        # Check if user already voted
        result = await session.execute(
            select(StrategyVote).where(
                (StrategyVote.strategy_id == strategy_id) &
                (StrategyVote.voter_discord_id == voter_discord_id)
            )
        )
        existing_vote = result.scalar_one_or_none()
        
        if existing_vote:
            # Update existing vote
            old_value = existing_vote.vote_value
            existing_vote.vote_value = vote_value
            existing_vote.voted_at = datetime.utcnow()
            vote_change = vote_value - old_value
        else:
            # Create new vote
            new_vote = StrategyVote(
                strategy_id=strategy_id,
                voter_discord_id=voter_discord_id,
                vote_value=vote_value
            )
            session.add(new_vote)
            vote_change = vote_value
        
        # Update strategy vote count
        result = await session.execute(
            select(Strategy).where(Strategy.id == strategy_id)
        )
        strategy = result.scalar_one_or_none()
        
        if strategy:
            strategy.votes += vote_change
            await session.commit()
            return True
        
        return False


# ==================== Utility Functions ====================

async def get_session():
    """Get a database session (for use with FastAPI dependency injection, etc.)."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        yield session


async def close_db():
    """Close database connections (call on shutdown)."""
    if engine:
        await engine.dispose()
        logger.info("Database connections closed")
