"""
Standalone character sync script.
Run manually to populate/update the character database from Danbooru.

Usage:
    docker compose run --rm bot python sync.py
    # or locally:
    python sync.py
"""
import asyncio
import logging
from database import init_models, async_session
from models import Base
from parser import sync_characters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main():
    logging.info("Initializing database...")
    await init_models(Base)
    
    try:
        logging.info("Starting character sync from Danbooru...")
        async with async_session() as session:
            await sync_characters(session)
    finally:
        from parser import close_session
        await close_session()
    
    logging.info("Sync completed.")

if __name__ == "__main__":
    asyncio.run(main())
