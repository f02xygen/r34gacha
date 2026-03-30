from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .utils import calculate_rank_short

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="🗂 Моя коллекция")],
            [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🔍 Игрок")],
            [KeyboardButton(text="♻️ Конвертация")]
        ],
        resize_keyboard=True
    )

def get_collection_keyboard(collections, target_user_id: int, page: int = 0, page_size: int = 8, only_favorites: bool = False, is_owner: bool = True):
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
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"coll_page:{target_user_id}:{page-1}:{int(only_favorites)}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"coll_page:{target_user_id}:{page+1}:{int(only_favorites)}"))
    if nav:
        buttons.append(nav)
    
    # Bottom row: Search and Favorites Toggle
    bottom_row = []
    if is_owner:
        bottom_row.append(InlineKeyboardButton(text="🔍 Поиск", callback_data="coll_search"))
    
    if only_favorites:
        bottom_row.append(InlineKeyboardButton(text="📜 Вся коллекция", callback_data=f"coll_page:{target_user_id}:0:0"))
    else:
        bottom_row.append(InlineKeyboardButton(text="❤️ Избранное", callback_data=f"coll_page:{target_user_id}:0:1"))
    
    buttons.append(bottom_row)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_char_view_keyboard(character_id: int, is_favorite: bool, page: int = 1, show_favorite_btn: bool = True):
    """Buttons for character card view."""
    buttons = []
    
    if show_favorite_btn:
        fav_text = "💔 Убрать из избранного" if is_favorite else "❤️ В избранное"
        buttons.append([InlineKeyboardButton(text=fav_text, callback_data=f"fav_toggle:{character_id}")])
        
    buttons.append([InlineKeyboardButton(text="🖼 Показать больше артов", callback_data=f"more_arts:{character_id}:{page}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


