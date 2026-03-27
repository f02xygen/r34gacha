import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql.expression import func
from sqlalchemy.orm import selectinload
from models import Character, UserCollection
from parser import get_best_post_for_character
from .utils import get_user, get_rank_condition, calculate_rank
from .keyboards import get_char_view_keyboard

router = Router()

class ConversionState(StatesGroup):
    choosing_rarity = State()
    selecting_characters = State()

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
        
    await state.update_data(from_rank=from_rank, to_rank=to_rank, selected_ids={}, total_selected=0, page=0)
    await state.set_state(ConversionState.selecting_characters)
    
    await update_conversion_picker(callback.message, state, collections)
    await callback.answer()

async def update_conversion_picker(message: Message, state: FSMContext, collections):
    data = await state.get_data()
    selected = data.get("selected_ids", {})
    total = data.get("total_selected", 0)
    from_rank = data.get("from_rank")
    to_rank = data.get("to_rank")
    page = data.get("page", 0)
    page_size = 8
    
    start = page * page_size
    end = start + page_size
    page_items = collections[start:end]
    total_pages = (len(collections) + page_size - 1) // page_size
    
    buttons = []
    for c in page_items:
        count_in_pool = selected.get(str(c.id), 0)
        fav_icon = "❤️ " if c.is_favorite else ""
        label = f"{fav_icon}[{count_in_pool}/{c.amount}] {c.character.tag_name}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"conv_toggle:{c.id}")])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"conv_page:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"conv_page:{page+1}"))
    if nav:
        buttons.append(nav)
    
    control_row = []
    if total == 10:
        control_row.append(InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ", callback_data="conv_confirm"))
    control_row.append(InlineKeyboardButton(text="❌ Отмена", callback_data="conv_cancel"))
    buttons.append(control_row)
    
    text = (
        f"♻️ <b>Подготовка к конвертации: {from_rank} ➔ {to_rank}</b>\n\n"
        f"Выбрано: <b>{total}/10</b> персонажей.\n"
        f"Страница: <b>{page+1}/{total_pages}</b>\n"
        f"Нажимайте на персонажей ниже, чтобы добавить их в пул."
    )
    
    try:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except:
        await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("conv_page:"), ConversionState.selecting_characters)
async def cb_conv_page(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    await state.update_data(page=page)
    data = await state.get_data()
    
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

@router.callback_query(F.data.startswith("conv_toggle:"), ConversionState.selecting_characters)
async def cb_conv_toggle_char(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    coll_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data["selected_ids"]
    total = data["total_selected"]
    
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
        if current_count > 0:
            selected[str(coll_id)] = current_count - 1
            total -= 1
            
    await state.update_data(selected_ids=selected, total_selected=total)
    
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
            
    stmt_random = select(Character).where(get_rank_condition(to_rank)).order_by(func.random()).limit(1)
    res_reward = await session.execute(stmt_random)
    reward_char = res_reward.scalars().first()
    
    if not reward_char:
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
