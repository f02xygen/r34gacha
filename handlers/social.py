from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc
from models import User, UserCollection

from .utils import get_user_collections
from .keyboards import get_collection_keyboard

router = Router()

@router.message(F.text == "🏆 Топ")
@router.message(Command("top"))
async def cmd_top(message: Message, session: AsyncSession):
    stmt = (
        select(User, func.count(func.distinct(UserCollection.character_id)).label("char_count"))
        .join(UserCollection, User.id == UserCollection.user_id)
        .group_by(User.id)
        .order_by(desc("char_count"))
        .limit(10)
    )
    res = await session.execute(stmt)
    top_users = res.all()
    
    if not top_users:
        await message.answer("🏆 Лидерборд пока пуст.")
        return
        
    lines = ["🏆 <b>Топ игроков по уникальным персонажам:</b>\n"]
    for i, (user, count) in enumerate(top_users, 1):
        name = f"@{user.username}" if user.username else f"ID {user.telegram_id}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
        lines.append(f"{medal} <b>{i}.</b> {name} — <b>{count}</b> перс.")
        
    await message.answer("\n".join(lines))

@router.message(Command("user"))
async def cmd_user(message: Message, command: CommandObject, session: AsyncSession):
    if not command.args:
        await message.answer("⚠️ Использование: <code>/user @username</code> или <code>/user &lt;id&gt;</code>")
        return
        
    arg = command.args.strip()
    
    if arg.startswith('@'):
        arg = arg[1:]
        
    if arg.isdigit():
        stmt = select(User).where(User.telegram_id == int(arg))
    else:
        # Case insensitive match for username
        stmt = select(User).where(func.lower(User.username) == arg.lower())
        
    res = await session.execute(stmt)
    target_user = res.scalars().first()
    
    if not target_user:
        await message.answer("❌ Пользователь не найден в базе данных.\nВозможно, он еще не запускал бота.")
        return
        
    collections = await get_user_collections(session, target_user.id)
    
    if not collections:
        name_display = f"@{target_user.username}" if target_user.username else f"ID {target_user.telegram_id}"
        await message.answer(f" У {name_display} пока пустая коллекция.")
        return
        
    total = len(collections)
    page_size = 8
    total_pages = max(1, (total + page_size - 1) // page_size)
    
    name_display = f"@{target_user.username}" if target_user.username else f"ID {target_user.telegram_id}"
    
    # Send collection
    await message.answer(
        f"🗂 <b>Коллекция {name_display}</b> — {total} персонажей\n"
        f"Страница: <b>1/{total_pages}</b>",
        reply_markup=get_collection_keyboard(collections, target_user_id=target_user.id, page=0, is_owner=False)
    )

@router.message(F.text == "🔍 Игрок")
async def cmd_search_user_prompt(message: Message):
    await message.answer(
        "🔍 Чтобы посмотреть коллекцию другого игрока, используйте команду:\n"
        "<code>/user @username</code> или <code>/user id_телеграма</code>\n\n"
        "<i>Пример: /user @durov</i>"
    )
