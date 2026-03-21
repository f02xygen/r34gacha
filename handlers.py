import logging
import random
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql.expression import func
from sqlalchemy.orm import selectinload
from models import User, Character, UserCollection
from parser import get_best_post_for_character

router = Router()

# Per-user cooldown tracking (in-memory, resets on restart)
ROLL_COOLDOWN_SECONDS = 10
_last_roll: dict[int, datetime] = {}

# ─── Keyboards ────────────────────────────────────────────────

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="🗂 Моя коллекция")]
        ],
        resize_keyboard=True
    )

def get_collection_keyboard(collections, page: int = 0, page_size: int = 8):
    """Build inline keyboard for collection browsing."""
    start = page * page_size
    end = start + page_size
    page_items = collections[start:end]
    total_pages = (len(collections) + page_size - 1) // page_size
    
    buttons = []
    for c in page_items:
        rank = calculate_rank(c.character.post_count)
        label = f"[{rank}] {c.character.tag_name}"
        buttons.append([InlineKeyboardButton(
            text=label[:40],
            callback_data=f"char:{c.character.id}"
        )])
    
    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"coll_page:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"coll_page:{page+1}"))
    if nav:
        buttons.append(nav)
    
    buttons.append([InlineKeyboardButton(text="🔍 Поиск по имени", callback_data="coll_search")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ─── Helpers ──────────────────────────────────────────────────

def calculate_rank(post_count: int) -> str:
    if post_count > 20000: return "SSS 💎💎💎"
    if post_count > 10000: return "SS 💎💎"
    if post_count > 5000: return "S 💎"
    if post_count > 2000: return "A ⭐⭐⭐"
    if post_count > 1000: return "B ⭐⭐"
    if post_count > 400: return "C ⭐"
    return "D"

def calculate_rank_short(post_count: int) -> str:
    if post_count > 20000: return "SSS"
    if post_count > 10000: return "SS"
    if post_count > 5000: return "S"
    if post_count > 2000: return "A"
    if post_count > 1000: return "B"
    if post_count > 400: return "C"
    return "D"

def get_rank_condition(rank: str):
    if rank == "SSS": return Character.post_count > 20000
    if rank == "SS": return Character.post_count.between(10001, 20000)
    if rank == "S": return Character.post_count.between(5001, 10000)
    if rank == "A": return Character.post_count.between(2001, 5000)
    if rank == "B": return Character.post_count.between(1001, 2000)
    if rank == "C": return Character.post_count.between(401, 1000)
    return Character.post_count.between(20, 400)

async def get_user(session: AsyncSession, telegram_id: int):
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await session.execute(stmt)
    return res.scalars().first()

async def get_user_collections(session: AsyncSession, user_id: int):
    stmt = (
        select(UserCollection)
        .where(UserCollection.user_id == user_id)
        .options(selectinload(UserCollection.character))
    )
    res = await session.execute(stmt)
    collections = res.scalars().all()
    collections.sort(key=lambda c: c.character.post_count, reverse=True)
    return collections

# ─── Handlers ─────────────────────────────────────────────────

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

@router.message(F.text == "🎲 Крутить")
async def cmd_roll(message: Message, session: AsyncSession):
    user = await get_user(session, message.from_user.id)
    
    if not user:
        await message.answer("Пожалуйста, нажмите /start для регистрации.")
        return

    # Rate limit
    now = datetime.now()
    last = _last_roll.get(message.from_user.id)
    if last:
        remaining = ROLL_COOLDOWN_SECONDS - (now - last).total_seconds()
        if remaining > 0:
            await message.answer(f"⏳ Подождите ещё <b>{remaining:.0f} сек.</b> перед следующей круткой.")
            return
    _last_roll[message.from_user.id] = now

    drop_rates = {
        "SSS": 0.005,
        "SS": 0.015,
        "S": 0.05,
        "A": 0.08,
        "B": 0.25,
        "C": 0.25,
        "D": 0.35
    }
    tiers = list(drop_rates.keys())
    weights = list(drop_rates.values())
    
    character = None
    for _ in range(3):
        rolled_rank = random.choices(tiers, weights=weights, k=1)[0]
        stmt_random = select(Character).where(get_rank_condition(rolled_rank)).order_by(func.random()).limit(1)
        res_char = await session.execute(stmt_random)
        character = res_char.scalars().first()
        if character:
            break
            
    if not character:
        stmt_random = select(Character).order_by(func.random()).limit(1)
        res_char = await session.execute(stmt_random)
        character = res_char.scalars().first()

    if not character:
        await message.answer("База персонажей пуста! Запустите <code>python sync.py</code> для заполнения базы.")
        return
        
    status_msg = await message.answer("⏳ Подбираем крутой арт...")
    
    try:
        image_url = character.best_image_url
        if not image_url:
            image_url = await get_best_post_for_character(character.tag_name)
            if image_url:
                character.best_image_url = image_url
                await session.commit()
                
        stmt_coll = select(UserCollection).where(
            UserCollection.user_id == user.id,
            UserCollection.character_id == character.id
        )
        res_coll = await session.execute(stmt_coll)
        collection = res_coll.scalars().first()
        
        if collection:
            collection.amount += 1
        else:
            new_coll = UserCollection(user_id=user.id, character_id=character.id, amount=1)
            session.add(new_coll)
            
        await session.commit()
        
        rank = calculate_rank(character.post_count)
        caption = (
            f"🎉 Вы выбили: <b>{character.tag_name}</b>\n\n"
            f"🖼 Всего постов: {character.post_count}\n"
            f"💪 Ранг: {rank}"
        )
            
        await status_msg.delete()
        if image_url:
            try:
                await message.answer_photo(photo=URLInputFile(image_url), caption=caption, parse_mode="HTML")
            except Exception:
                await message.answer(f"{caption}\n\n<a href='{image_url}'>Медиафайл</a>", parse_mode="HTML")
        else:
            await message.answer(f"{caption}\n\n[Изображение не найдено]", parse_mode="HTML")
            
    except Exception as e:
        logging.error(f"Error in roll logic: {e}")
        try:
            await status_msg.delete()
        except: pass
        await message.answer("Произошла ошибка при получении персонажа.")

@router.message(F.text == "🗂 Моя коллекция")
async def cmd_collection(message: Message, session: AsyncSession):
    user = await get_user(session, message.from_user.id)
    if not user:
        await message.answer("Пожалуйста, нажмите /start для регистрации.")
        return
        
    collections = await get_user_collections(session, user.id)
    
    if not collections:
        await message.answer("Ваша коллекция пуста. Нажмите <b>🎲 Крутить</b>, чтобы получить персонажей!")
        return
    
    total = len(collections)
    await message.answer(
        f"🗂 <b>Ваша коллекция</b> — {total} персонажей\n\nВыберите персонажа, чтобы посмотреть карточку:",
        reply_markup=get_collection_keyboard(collections, page=0)
    )

# ─── Inline callbacks ─────────────────────────────────────────

@router.callback_query(F.data.startswith("coll_page:"))
async def cb_collection_page(callback: CallbackQuery, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    if not user:
        await callback.answer("Пожалуйста, нажмите /start.")
        return
    
    collections = await get_user_collections(session, user.id)
    total = len(collections)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_collection_keyboard(collections, page=page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("char:"))
async def cb_view_character(callback: CallbackQuery, session: AsyncSession):
    char_id = int(callback.data.split(":")[1])
    
    stmt = select(Character).where(Character.id == char_id)
    res = await session.execute(stmt)
    character = res.scalars().first()
    
    if not character:
        await callback.answer("Персонаж не найден.", show_alert=True)
        return
    
    await callback.answer("⏳ Загружаем арт...")
    
    image_url = character.best_image_url
    if not image_url:
        image_url = await get_best_post_for_character(character.tag_name)
        if image_url:
            character.best_image_url = image_url
            await session.commit()
    
    rank = calculate_rank(character.post_count)
    caption = (
        f"🃏 <b>{character.tag_name}</b>\n\n"
        f"🖼 Постов: {character.post_count}\n"
        f"💪 Ранг: {rank}"
    )
    
    if image_url:
        try:
            await callback.message.answer_photo(
                photo=URLInputFile(image_url),
                caption=caption,
                parse_mode="HTML"
            )
        except Exception:
            await callback.message.answer(
                f"{caption}\n\n<a href='{image_url}'>Открыть арт</a>",
                parse_mode="HTML"
            )
    else:
        await callback.message.answer(f"{caption}\n\n[Изображение не найдено]", parse_mode="HTML")

@router.callback_query(F.data == "coll_search")
async def cb_search_prompt(callback: CallbackQuery, session: AsyncSession):
    await callback.message.answer(
        "🔍 Введите имя персонажа для поиска в вашей коллекции:\n"
        "(например: <code>hatsune_miku</code>)"
    )
    await callback.answer()

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_({"🎲 Крутить", "🗂 Моя коллекция"}))
async def cmd_search_collection(message: Message, session: AsyncSession):
    """Search collection by character name substring."""
    user = await get_user(session, message.from_user.id)
    if not user:
        return
    
    query = message.text.strip().lower().replace(" ", "_")
    
    stmt = (
        select(UserCollection)
        .join(UserCollection.character)
        .where(
            UserCollection.user_id == user.id,
            Character.tag_name.ilike(f"%{query}%")
        )
        .options(selectinload(UserCollection.character))
    )
    res = await session.execute(stmt)
    results = res.scalars().all()
    
    if not results:
        await message.answer(f"Персонажи с именем <b>{message.text}</b> не найдены в вашей коллекции.")
        return
    
    results.sort(key=lambda c: c.character.post_count, reverse=True)
    
    await message.answer(
        f"🔍 Результаты поиска по <b>\"{message.text}\"</b>:\n\nВыберите персонажа:",
        reply_markup=get_collection_keyboard(results, page=0)
    )
