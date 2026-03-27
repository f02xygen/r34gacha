from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import User, Character, UserCollection
from datetime import datetime

# Per-user cooldown tracking (in-memory, resets on restart)
ACTION_COOLDOWN_SECONDS = 10
_last_action: dict[int, datetime] = {}

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
