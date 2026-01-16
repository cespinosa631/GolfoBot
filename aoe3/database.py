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
    discord_id: int, 
    discord_username: str, 
    aoe3_username: str, 
    profile_url: str = None
) -> Player:
    """Register a new player or update existing player."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        # Check if player already exists
        result = await session.execute(
            select(Player).where(Player.discord_id == discord_id)
        )
        player = result.scalar_one_or_none()
        
        if player:
            # Update existing player
            player.discord_username = discord_username
            player.aoe3_username = aoe3_username
            if profile_url:
                player.aoe3_profile_url = profile_url
        else:
            # Create new player
            player = Player(
                discord_id=discord_id,
                discord_username=discord_username,
                aoe3_username=aoe3_username,
                aoe3_profile_url=profile_url or f"https://aoe3-homecity.com/player/{aoe3_username}"
            )
            session.add(player)
        
        await session.commit()
        await session.refresh(player)
        return player


async def get_player_by_discord_id(discord_id: int) -> Optional[Player]:
    """Get player by Discord ID."""
    if not AsyncSessionLocal:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.discord_id == discord_id)
        )
        return result.scalar_one_or_none()


async def get_player_by_aoe3_username(aoe3_username: str) -> Optional[Player]:
    """Get player by AoE3 username."""
    if not AsyncSessionLocal:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.aoe3_username == aoe3_username)
        )
        return result.scalar_one_or_none()


async def get_all_players() -> List[Player]:
    """Get all registered players."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Player))
        return result.scalars().all()


async def update_player_elo(
    discord_id: int, 
    elo_1v1: int = None, 
    elo_team: int = None,
    favorite_civ: str = None
):
    """Update player ELO ratings and stats."""
    if not AsyncSessionLocal:
        return
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.discord_id == discord_id)
        )
        player = result.scalar_one_or_none()
        
        if player:
            if elo_1v1 is not None:
                player.elo_1v1 = elo_1v1
            if elo_team is not None:
                player.elo_team = elo_team
            if favorite_civ is not None:
                player.favorite_civ = favorite_civ
            player.last_checked_at = datetime.utcnow()
            await session.commit()


async def add_match(match_data: Dict[str, Any]) -> Match:
    """Add a new match to database."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        match = Match(**match_data)
        session.add(match)
        await session.commit()
        await session.refresh(match)
        return match


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


async def get_player_matches(discord_id: int, limit: int = 20) -> List[Match]:
    """Get matches for a specific player."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Match)
            .where(
                (Match.winner_discord_id == discord_id) | 
                (Match.loser_discord_id == discord_id)
            )
            .order_by(Match.played_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


async def get_leaderboard(elo_type: str = '1v1', limit: int = 10) -> List[Player]:
    """Get ELO leaderboard."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        if elo_type == '1v1':
            result = await session.execute(
                select(Player)
                .where(Player.elo_1v1.isnot(None))
                .order_by(Player.elo_1v1.desc())
                .limit(limit)
            )
        else:  # team
            result = await session.execute(
                select(Player)
                .where(Player.elo_team.isnot(None))
                .order_by(Player.elo_team.desc())
                .limit(limit)
            )
        return result.scalars().all()


# ==================== Civilization Operations ====================

async def upsert_civilization(civ_data: Dict[str, Any]) -> Civilization:
    """Create or update civilization data."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        # Check if civ exists
        result = await session.execute(
            select(Civilization).where(Civilization.name == civ_data['name'])
        )
        civ = result.scalar_one_or_none()
        
        if civ:
            # Update existing
            for key, value in civ_data.items():
                if key != 'name':
                    setattr(civ, key, value)
            civ.last_updated = datetime.utcnow()
        else:
            # Create new
            civ = Civilization(**civ_data)
            session.add(civ)
        
        await session.commit()
        await session.refresh(civ)
        return civ


async def get_civilization(name: str) -> Optional[Civilization]:
    """Get civilization by name."""
    if not AsyncSessionLocal:
        return None
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Civilization).where(Civilization.name.ilike(f"%{name}%"))
        )
        return result.scalar_one_or_none()


async def get_all_civilizations() -> List[Civilization]:
    """Get all civilizations."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Civilization))
        return result.scalars().all()


# ==================== Strategy Operations ====================

async def add_strategy(
    civ: str,
    strategy_text: str,
    author_discord_id: int,
    vs_civ: str = None,
    map_name: str = None
) -> Strategy:
    """Add a new community strategy."""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    
    async with AsyncSessionLocal() as session:
        strategy = Strategy(
            civ=civ,
            vs_civ=vs_civ,
            map=map_name,
            strategy_text=strategy_text,
            author_discord_id=author_discord_id
        )
        session.add(strategy)
        await session.commit()
        await session.refresh(strategy)
        return strategy


async def get_strategies(civ: str, vs_civ: str = None, limit: int = 5) -> List[Strategy]:
    """Get strategies for a civilization, ordered by votes."""
    if not AsyncSessionLocal:
        return []
    
    async with AsyncSessionLocal() as session:
        query = select(Strategy).where(Strategy.civ.ilike(f"%{civ}%"))
        
        if vs_civ:
            query = query.where(Strategy.vs_civ.ilike(f"%{vs_civ}%"))
        
        query = query.order_by(Strategy.votes.desc()).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()


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
