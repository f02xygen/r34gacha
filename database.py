from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_models(base):
    async with engine.begin() as conn:
        await conn.run_sync(base.metadata.create_all)
        # Automatic Migration: Add is_favorite column if it doesn't exist
        try:
            await conn.execute(text("ALTER TABLE user_collections ADD COLUMN is_favorite INTEGER DEFAULT 0"))
        except Exception:
            # Column already exists
            pass
