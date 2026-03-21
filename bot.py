import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from config import settings
from database import init_models, async_session
from models import Base
from handlers import router

async def inject_session(handler, event, data):
    # Dependency injection for SQLAlchemy session
    async with async_session() as session:
        data['session'] = session
        return await handler(event, data)

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    if not settings.bot_token or settings.bot_token == "your_telegram_bot_token_here":
        logging.error("BOT_TOKEN is not set in .env! Find it via @BotFather")
        return

    # Initialize DB (creates tables if not exist)
    logging.info("Initializing database models...")
    await init_models(Base)
    
    # Foreground sync for initial setup is now skipped. 
    # Use sync.py locally or via docker compose run.
    
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher()
    dp.include_router(router)
    
    # Middleware for injecting DB sessions into handlers
    router.message.middleware(inject_session)
    router.callback_query.middleware(inject_session)
    
    logging.info("Starting bot polling. Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot)
    finally:
        from parser import close_session
        await close_session()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
