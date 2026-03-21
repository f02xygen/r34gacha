import logging
import random
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql.expression import func
from sqlalchemy.orm import selectinload
from models import User, Character, UserCollection
from parser import get_best_post_for_character

router = Router()

class ConversionState(StatesGroup):
    choosing_rarity = State()
    selecting_characters = State()

# Per-user cooldown tracking (in-memory, resets on restart)
ROLL_COOLDOWN_SECONDS = 10
_last_roll: dict[int, datetime] = {}

# ─── Keyboards ────────────────────────────────────────────────

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="🗂 Моя коллекция")],
            [KeyboardButton(text="♻️ Конвертация")]
        ],
        resize_keyboard=True
    )

def get_collection_keyboard(collections, page: int = 0, page_size: int = 8, only_favorites: bool = False):
    """Build inline keyboard for collection browsing."""
    start = page * page_size
    end = start + page_size
    page_items = collections[start:end]
    total_pages = (len(collections) + page_size - 1) // page_size
    
    buttons = []
    for c in page_items:
        rank = calculate_rank_short(c.character.post_count)
        fav_icon = "❤️ " if c.is_favorite else ""
        label = f"{fav_icon}[{rank}] {c.character.tag_name}"
        buttons.append([InlineKeyboardButton(
            text=label[:40],
            callback_data=f"char:{c.character.id}"
        )])
    
    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"coll_page:{page-1}:{int(only_favorites)}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"coll_page:{page+1}:{int(only_favorites)}"))
    if nav:
        buttons.append(nav)
    
    # Bottom row: Search and Favorites Toggle
    bottom_row = [InlineKeyboardButton(text="🔍 Поиск", callback_data="coll_search")]
    if only_favorites:
        bottom_row.append(InlineKeyboardButton(text="📜 Вся коллекция", callback_data="coll_page:0:0"))
    else:
        bottom_row.append(InlineKeyboardButton(text="❤️ Избранное", callback_data="coll_page:0:1"))
    
    buttons.append(bottom_row)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_char_view_keyboard(character_id: int, is_favorite: bool):
    """Buttons for character card view."""
    fav_text = "💔 Убрать из избранного" if is_favorite else "❤️ В избранное"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav_toggle:{character_id}")]
    ])

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

async def get_user_collections(session: AsyncSession, user_id: int, only_favorites: bool = False):
    stmt = (
        select(UserCollection)
        .where(UserCollection.user_id == user_id)
        .options(selectinload(UserCollection.character))
    )
    if only_favorites:
        stmt = stmt.where(UserCollection.is_favorite == 1)
        
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
        "SSS": 0.005, "SS": 0.015, "S": 0.05,
        "A": 0.08, "B": 0.25, "C": 0.25, "D": 0.35
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
            collection = UserCollection(user_id=user.id, character_id=character.id, amount=1)
            session.add(collection)
            
        await session.commit()
        
        rank = calculate_rank(character.post_count)
        caption = (
            f"🎉 Вы выбили: <b>{character.tag_name}</b>\n\n"
            f"🖼 Всего постов: {character.post_count}\n"
            f"💪 Ранг: {rank}"
        )
            
        await status_msg.delete()
        
        markup = get_char_view_keyboard(character.id, collection.is_favorite)
        
        if image_url:
            try:
                await message.answer_photo(photo=URLInputFile(image_url), caption=caption, parse_mode="HTML", reply_markup=markup)
            except Exception:
                await message.answer(f"{caption}\n\n<a href='{image_url}'>Медиафайл</a>", parse_mode="HTML", reply_markup=markup)
        else:
            await message.answer(f"{caption}\n\n[Изображение не найдено]", parse_mode="HTML", reply_markup=markup)
            
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
        f"🗂 <b>Ваша коллекция</b> — {total} персонажей",
        reply_markup=get_collection_keyboard(collections, page=0)
    )

# ─── Inline callbacks ─────────────────────────────────────────

@router.callback_query(F.data.startswith("coll_page:"))
async def cb_collection_page(callback: CallbackQuery, session: AsyncSession):
    data = callback.data.split(":")
    page = int(data[1])
    only_favorites = bool(int(data[2])) if len(data) > 2 else False
    
    user = await get_user(session, callback.from_user.id)
    if not user:
        await callback.answer("Пожалуйста, нажмите /start.")
        return
    
    collections = await get_user_collections(session, user.id, only_favorites=only_favorites)
    
    if only_favorites and not collections:
        await callback.answer("У вас пока нет избранных персонажей.", show_alert=True)
        return

    text = f"🗂 <b>{'Избранное' if only_favorites else 'Ваша коллекция'}</b> — {len(collections)} персонажей"
    
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_collection_keyboard(collections, page=page, only_favorites=only_favorites)
        )
    except Exception:
        # Avoid error if text remains the same
        await callback.message.edit_reply_markup(
            reply_markup=get_collection_keyboard(collections, page=page, only_favorites=only_favorites)
        )
    await callback.answer()

@router.callback_query(F.data.startswith("char:"))
async def cb_view_character(callback: CallbackQuery, session: AsyncSession):
    char_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    
    stmt = (
        select(UserCollection)
        .where(UserCollection.user_id == user.id, UserCollection.character_id == char_id)
        .options(selectinload(UserCollection.character))
    )
    res = await session.execute(stmt)
    coll = res.scalars().first()
    
    if not coll:
        await callback.answer("Персонаж не найден в вашей коллекции.", show_alert=True)
        return
    
    character = coll.character
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
    
    markup = get_char_view_keyboard(character.id, coll.is_favorite)
    
    if image_url:
        try:
            await callback.message.answer_photo(
                photo=URLInputFile(image_url),
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup
            )
        except Exception:
            await callback.message.answer(
                f"{caption}\n\n<a href='{image_url}'>Открыть арт</a>",
                parse_mode="HTML",
                reply_markup=markup
            )
    else:
        await callback.message.answer(f"{caption}\n\n[Изображение не найдено]", parse_mode="HTML", reply_markup=markup)

@router.callback_query(F.data.startswith("fav_toggle:"))
async def cb_fav_toggle(callback: CallbackQuery, session: AsyncSession):
    char_id = int(callback.data.split(":")[1])
    user = await get_user(session, callback.from_user.id)
    
    stmt = select(UserCollection).where(
        UserCollection.user_id == user.id,
        UserCollection.character_id == char_id
    )
    res = await session.execute(stmt)
    coll = res.scalars().first()
    
    if not coll:
        await callback.answer("Персонаж не найден.", show_alert=True)
        return
    
    coll.is_favorite = 1 if not coll.is_favorite else 0
    await session.commit()
    
    # Update current message keyboard
    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_char_view_keyboard(char_id, coll.is_favorite)
        )
    except:
        pass
        
    status = "добавлен в избранное ❤️" if coll.is_favorite else "удалён из избранного 💔"
    await callback.answer(f"Персонаж {status}")

@router.callback_query(F.data == "coll_search")
async def cb_search_prompt(callback: CallbackQuery, session: AsyncSession):
    await callback.message.answer(
        "🔍 Введите имя персонажа для поиска в вашей коллекции:\n"
        "(например: <code>hatsune_miku</code>)"
    )
    await callback.answer()

# ─── Conversion / Crafting ───────────────────────────────────

@router.message(F.text == "♻️ Конвертация")
async def cmd_conversion(message: Message, state: FSMContext):
    await state.clear()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="D ➔ C", callback_data="conv_start:D:C")],
        [InlineKeyboardButton(text="C ➔ B", callback_data="conv_start:C:B")],
        [InlineKeyboardButton(text="B ➔ A", callback_data="conv_start:B:A")],
        [InlineKeyboardButton(text="A ➔ S", callback_data="conv_start:A:S")],
        [InlineKeyboardButton(text="S ➔ SS", callback_data="conv_start:S:SS")],
        [InlineKeyboardButton(text="SS ➔ SSS", callback_data="conv_start:SS:SSS")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="conv_cancel")]
    ])
    await message.answer(
        "♻️ <b>Конвертация персонажей</b>\n\n"
        "Вы можете объединить <b>10 персонажей</b> одной редкости, "
        "чтобы получить одного случайного персонажа редкости выше.\n\n"
        "Выберите путь конвертации:",
        reply_markup=markup
    )

@router.callback_query(F.data == "conv_cancel")
async def cb_conv_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Конвертация отменена.")
    await callback.answer()

@router.callback_query(F.data.startswith("conv_start:"))
async def cb_conv_rarity_selected(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, from_rank, to_rank = callback.data.split(":")
    user = await get_user(session, callback.from_user.id)
    
    # Get all characters of this rank that user has
    stmt = (
        select(UserCollection)
        .join(UserCollection.character)
        .where(UserCollection.user_id == user.id)
        .where(get_rank_condition(from_rank))
        .options(selectinload(UserCollection.character))
    )
    res = await session.execute(stmt)
    collections = res.scalars().all()
    
    if sum(c.amount for c in collections) < 10:
        await callback.answer(f"У вас недостаточно персонажей ранга {from_rank} (нужно 10).", show_alert=True)
        return
        
    await state.update_data(from_rank=from_rank, to_rank=to_rank, selected_ids={}, total_selected=0)
    await state.set_state(ConversionState.selecting_characters)
    
    await update_conversion_picker(callback.message, state, collections)
    await callback.answer()

async def update_conversion_picker(message: Message, state: FSMContext, collections):
    data = await state.get_data()
    selected = data.get("selected_ids", {})
    total = data.get("total_selected", 0)
    from_rank = data.get("from_rank")
    to_rank = data.get("to_rank")
    
    buttons = []
    # Simplified list for picker (no pagination for now to keep logic clean)
    for c in collections:
        count_in_pool = selected.get(str(c.id), 0)
        label = f"[{count_in_pool}/{c.amount}] {c.character.tag_name}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"conv_toggle:{c.id}")])
    
    control_row = []
    if total == 10:
        control_row.append(InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ", callback_data="conv_confirm"))
    control_row.append(InlineKeyboardButton(text="❌ Отмена", callback_data="conv_cancel"))
    buttons.append(control_row)
    
    text = (
        f"♻️ <b>Подготовка к конвертации: {from_rank} ➔ {to_rank}</b>\n\n"
        f"Выбрано: <b>{total}/10</b> персонажей.\n"
        f"Нажимайте на персонажей ниже, чтобы добавить их в пул."
    )
    
    try:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except:
        await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("conv_toggle:"), ConversionState.selecting_characters)
async def cb_conv_toggle_char(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    coll_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data["selected_ids"]
    total = data["total_selected"]
    
    # Check current amount in DB to be safe
    stmt = select(UserCollection).where(UserCollection.id == coll_id)
    res = await session.execute(stmt)
    coll = res.scalars().first()
    
    current_count = selected.get(str(coll_id), 0)
    
    if current_count < coll.amount:
        if total < 10:
            selected[str(coll_id)] = current_count + 1
            total += 1
        else:
            await callback.answer("Максимум 10 персонажей!", show_alert=True)
            return
    else:
        # Reset if clicked again at max? No, let's just allow decrementing
        if current_count > 0:
            selected[str(coll_id)] = current_count - 1
            total -= 1
            
    await state.update_data(selected_ids=selected, total_selected=total)
    
    # Re-fetch collections to update UI
    user = await get_user(session, callback.from_user.id)
    stmt = (
        select(UserCollection)
        .join(UserCollection.character)
        .where(UserCollection.user_id == user.id)
        .where(get_rank_condition(data["from_rank"]))
        .options(selectinload(UserCollection.character))
    )
    res = await session.execute(stmt)
    collections = res.scalars().all()
    
    await update_conversion_picker(callback.message, state, collections)
    await callback.answer()

@router.callback_query(F.data == "conv_confirm", ConversionState.selecting_characters)
async def cb_conv_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if data["total_selected"] != 10:
        await callback.answer("Нужно выбрать ровно 10!")
        return
        
    to_rank = data["to_rank"]
    selected = data["selected_ids"]
    
    # 1. Sacrifice characters
    for coll_id_str, count in selected.items():
        if count <= 0: continue
        coll_id = int(coll_id_str)
        stmt = select(UserCollection).where(UserCollection.id == coll_id)
        res = await session.execute(stmt)
        coll = res.scalars().first()
        
        if coll.amount > count:
            coll.amount -= count
        else:
            await session.delete(coll)
            
    # 2. Add reward
    stmt_random = select(Character).where(get_rank_condition(to_rank)).order_by(func.random()).limit(1)
    res_reward = await session.execute(stmt_random)
    reward_char = res_reward.scalars().first()
    
    if not reward_char:
        # Fallback if no characters of that rank exist in DB
        await callback.message.answer("Критическая ошибка: персонажи целевого ранга не найдены.")
        await state.clear()
        return

    user = await get_user(session, callback.from_user.id)
    stmt_check = select(UserCollection).where(
        UserCollection.user_id == user.id,
        UserCollection.character_id == reward_char.id
    )
    res_check = await session.execute(stmt_check)
    existing = res_check.scalars().first()
    
    if existing:
        existing.amount += 1
    else:
        new_coll = UserCollection(user_id=user.id, character_id=reward_char.id, amount=1)
        session.add(new_coll)
        
    # 3. Handle image and notification
    status_msg = await callback.message.answer("⏳ Получаем новый арт...")
    try:
        image_url = reward_char.best_image_url
        if not image_url:
            image_url = await get_best_post_for_character(reward_char.tag_name)
            if image_url:
                reward_char.best_image_url = image_url
                await session.commit()
        
        await status_msg.delete()
        
        rank_visual = calculate_rank(reward_char.post_count)
        caption = (
            f"🔥 <b>Конвертация успешна!</b>\n\n"
            f"Вы пожертвовали 10 персонажами и получили нового:\n"
            f"✨ <b>{reward_char.tag_name}</b> ({rank_visual})"
        )
        
        # New collection entry 'is_favorite' is always 0 since it's a new reward
        # (or 0 if it was merged into existing)
        markup = get_char_view_keyboard(reward_char.id, False)

        if image_url:
            try:
                await callback.message.answer_photo(
                    photo=URLInputFile(image_url),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=markup
                )
            except Exception:
                await callback.message.answer(
                    f"{caption}\n\n<a href='{image_url}'>Открыть арт</a>",
                    parse_mode="HTML",
                    reply_markup=markup
                )
        else:
            await callback.message.answer(f"{caption}\n\n[Изображение не найдено]", parse_mode="HTML", reply_markup=markup)
            
    except Exception as e:
        logging.error(f"Error in conversion final view: {e}")
        await callback.message.answer(f"🔥 Конвертация успешна! Вы получили: {reward_char.tag_name}")
    
    await session.commit()
    await state.clear()
    await callback.answer("Успех!")
