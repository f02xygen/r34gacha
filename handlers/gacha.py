import random
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, URLInputFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql.expression import func
from models import Character, UserCollection
from parser import get_best_post_for_character
from .utils import get_user, get_rank_condition, calculate_rank, ACTION_COOLDOWN_SECONDS, _last_action
from .keyboards import get_char_view_keyboard

router = Router()

@router.message(F.text == "🎲 Крутить")
async def cmd_roll(message: Message, session: AsyncSession):
    user = await get_user(session, message.from_user.id)
    
    if not user:
        await message.answer("Пожалуйста, нажмите /start для регистрации.")
        return

    # Rate limit
    now = datetime.now()
    last = _last_action.get(message.from_user.id)
    if last:
        remaining = ACTION_COOLDOWN_SECONDS - (now - last).total_seconds()
        if remaining > 0:
            await message.answer(f"⏳ Подождите ещё <b>{remaining:.0f} сек.</b> перед следующим действием (Rate Limit).")
            return
    _last_action[message.from_user.id] = now

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
