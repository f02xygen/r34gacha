import random
import logging
from datetime import datetime
from aiohttp import web
from sqlalchemy.future import select
from sqlalchemy.sql.expression import func
from models import Character, UserCollection
from parser import get_best_post_for_character
from handlers.utils import get_user, get_rank_condition, calculate_rank, ACTION_COOLDOWN_SECONDS, _last_action
from database import async_session
from webapp_auth import validate_webapp_data
from config import settings

routes = web.RouteTableDef()

def _check_auth(request: web.Request) -> dict | None:
    # Validate authorization via Telegram initData passed in Headers or JSON
    init_data = request.headers.get("X-Tg-Init-Data")
    if not init_data:
        return None
    return validate_webapp_data(init_data, settings.bot_token)

import json
def _get_tg_user(user_data: dict) -> dict | None:
    try:
        user_json = user_data.get('user')
        if user_json:
            return json.loads(user_json)
    except Exception:
        pass
    return None

@routes.post("/api/roll")
async def api_roll(request: web.Request):
    auth_data = _check_auth(request)
    if not auth_data:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    tg_user = _get_tg_user(auth_data)
    if not tg_user:
        return web.json_response({"error": "Invalid user data"}, status=400)
        
    user_id = tg_user.get("id")
    
    async with async_session() as session:
        user = await get_user(session, user_id)
        if not user:
            return web.json_response({"error": "Пожалуйста, нажмите /start бота для регистрации."}, status=403)
            
        now = datetime.now()
        last = _last_action.get(user_id)
        if last:
            remaining = ACTION_COOLDOWN_SECONDS - (now - last).total_seconds()
            if remaining > 0:
                return web.json_response({
                    "error": f"Подождите ещё {remaining:.0f} сек. (Rate Limit)",
                    "cooldown": remaining
                }, status=429)
        
        _last_action[user_id] = now
        
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
            return web.json_response({"error": "База персонажей пуста!"}, status=500)
            
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
        
        return web.json_response({
            "character_id": character.id,
            "tag_name": character.tag_name,
            "post_count": character.post_count,
            "rank": rank,
            "image_url": image_url,
            "amount": collection.amount,
            "is_favorite": bool(collection.is_favorite)
        })

@routes.post("/api/favorite")
async def api_favorite(request: web.Request):
    auth_data = _check_auth(request)
    if not auth_data:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    tg_user = _get_tg_user(auth_data)
    if not tg_user:
        return web.json_response({"error": "Invalid user data"}, status=400)
        
    user_id = tg_user.get("id")
    
    try:
        data = await request.json()
        char_id = int(data.get("character_id"))
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    async with async_session() as session:
        user = await get_user(session, user_id)
        if not user:
            return web.json_response({"error": "User not found"}, status=403)
            
        stmt = select(UserCollection).where(
            UserCollection.user_id == user.id,
            UserCollection.character_id == char_id
        )
        res = await session.execute(stmt)
        coll = res.scalars().first()
        
        if not coll:
            return web.json_response({"error": "Персонаж не в вашей коллекции!"}, status=404)
            
        coll.is_favorite = 1 if not coll.is_favorite else 0
        await session.commit()
        
        return web.json_response({
            "character_id": char_id,
            "is_favorite": bool(coll.is_favorite)
        })
