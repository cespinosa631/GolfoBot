"""
Manually create AoE3 database tables in Railway PostgreSQL.
Run this locally, it will connect to Railway's PostgreSQL and create all tables.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def setup_database():
    """Create all database tables."""
    # Get DATABASE_URL from Railway Postgres
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL not found in environment")
        print("\nTo get the DATABASE_URL:")
        print("1. Go to Railway dashboard → Postgres service")
        print("2. Click 'Variables' tab")
        print("3. Copy the DATABASE_URL value")
        print("4. Add it to your .env file: DATABASE_URL=<value>")
        return
    
    # Fix URL format if needed (Railway sometimes uses postgres:// but we need postgresql://)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    print(f"📊 Connecting to database...")
    print(f"Host: {database_url.split('@')[1].split('/')[0] if '@' in database_url else 'unknown'}")
    
    # Import database module
    from aoe3.database import Base, engine
    from sqlalchemy.ext.asyncio import create_async_engine
    
    # Create engine with the DATABASE_URL
    db_engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True
    )
    
    print("🔨 Creating database tables...")
    
    try:
        async with db_engine.begin() as conn:
            # Drop all tables first (optional - comment out if you want to keep existing data)
            # await conn.run_sync(Base.metadata.drop_all)
            # print("  Dropped existing tables")
            
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
            print("  ✅ Created all tables")
        
        print("\n✅ Database setup complete!")
        print("\nCreated tables:")
        print("  - players")
        print("  - matches")
        print("  - civilizations")
        print("  - strategies")
        print("  - strategy_votes")
        
    except Exception as e:
        print(f"\n❌ Error creating tables: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db_engine.dispose()

if __name__ == '__main__':
    asyncio.run(setup_database())
