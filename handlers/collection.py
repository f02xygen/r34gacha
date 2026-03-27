import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, URLInputFile, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, UserCollection
from parser import get_best_post_for_character, get_posts_for_character
from .utils import get_user, get_user_collections, calculate_rank, ACTION_COOLDOWN_SECONDS, _last_action
from .keyboards import get_collection_keyboard, get_char_view_keyboard

router = Router()

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
    page_size = 8
    total_pages = (total + page_size - 1) // page_size
    
    await message.answer(
        f"🗂 <b>Ваша коллекция</b> — {total} персонажей\n"
        f"Страница: <b>1/{total_pages}</b>",
        reply_markup=get_collection_keyboard(collections, page=0)
    )

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

    total = len(collections)
    page_size = 8
    total_pages = (total + page_size - 1) // page_size
    
    label = 'Избранное' if only_favorites else 'Ваша коллекция'
    text = f"🗂 <b>{label}</b> — {total} персонажей\nСтраница: <b>{page+1}/{total_pages}</b>"
    
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_collection_keyboard(collections, page=page, only_favorites=only_favorites)
        )
    except Exception:
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
    
    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_char_view_keyboard(char_id, coll.is_favorite)
        )
    except:
        pass
        
    status = "добавлен в избранное ❤️" if coll.is_favorite else "удалён из избранного 💔"
    await callback.answer(f"Персонаж {status}")

@router.callback_query(F.data.startswith("more_arts:"))
async def cb_more_arts(callback: CallbackQuery, session: AsyncSession):
    data = callback.data.split(":")
    char_id = int(data[1])
    page = int(data[2])
    user_id = callback.from_user.id
    
    now = datetime.now()
    last = _last_action.get(user_id)
    if last:
        remaining = ACTION_COOLDOWN_SECONDS - (now - last).total_seconds()
        if remaining > 0:
            await callback.answer(f"⏳ Подождите {remaining:.0f} сек. (Rate Limit)", show_alert=True)
            return
    _last_action[user_id] = now
    
    stmt = select(Character).where(Character.id == char_id)
    res = await session.execute(stmt)
    character = res.scalars().first()
    
    if not character:
        await callback.answer("Персонаж не найден.", show_alert=True)
        return
        
    await callback.answer("⏳ Загружаем арты...")
    
    items = await get_posts_for_character(character.tag_name, limit=10, page=page)
    
    if not items:
        await callback.message.answer("Больше артов не найдено.")
        return
        
    media_group = []
    for item in items:
        if item["type"] == "photo":
            media_group.append(InputMediaPhoto(media=item["url"]))
        else:
            media_group.append(InputMediaVideo(media=item["url"]))
    
    try:
        await callback.message.answer_media_group(media=media_group)
    except Exception as e:
        logging.error(f"Failed to send media group for {character.tag_name}: {e}")
        await callback.message.answer("К сожалению, некоторые арты отправить не удалось.")
        return
        
    next_page = page + 1
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Следующие 10 артов", callback_data=f"more_arts:{char_id}:{next_page}")]
    ])
    
    try:
        await callback.message.answer(
            f"🖼 <b>{character.tag_name}</b> (Стр. {page})", 
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        logging.error(f"Failed to send follow_up more_arts for {character.tag_name}: {e}")

@router.callback_query(F.data == "coll_search")
async def cb_search_prompt(callback: CallbackQuery, session: AsyncSession):
    await callback.message.answer(
        "🔍 Введите имя персонажа для поиска в вашей коллекции:\n"
        "(например: <code>hatsune_miku</code>)"
    )
    await callback.answer()

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_({"🎲 Крутить", "🗂 Моя коллекция", "♻️ Конвертация"}))
async def cmd_search_collection(message: Message, session: AsyncSession):
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
    
    total = len(results)
    page_size = 8
    total_pages = (total + page_size - 1) // page_size
    
    await message.answer(
        f"🔍 Результаты поиска по <b>\"{message.text}\"</b>:\n"
        f"Страница: <b>1/{total_pages}</b>",
        reply_markup=get_collection_keyboard(results, page=0)
    )
