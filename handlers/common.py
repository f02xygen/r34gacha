from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from models import User
from .utils import get_user
from .keyboards import get_main_keyboard

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    user = await get_user(session, message.from_user.id)
    
    if not user:
        user = User(telegram_id=message.from_user.id, username=message.from_user.username)
        session.add(user)
        await session.commit()
    
    await message.answer(
        "Добро пожаловать в <b>r34gacha</b>! 🎰\n\nНажмите <b>🎲 Крутить</b>, чтобы выбить случайного персонажа.",
        reply_markup=get_main_keyboard()
    )
