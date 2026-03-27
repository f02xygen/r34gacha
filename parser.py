import aiohttp
import asyncio
from urllib.parse import quote_plus
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Character
from database import engine, async_session
from config import settings
import logging

# Global session to be initialized and reused
_session: aiohttp.ClientSession | None = None

def get_auth():
    """Returns aiohttp.BasicAuth if credentials are configured."""
    if settings.danbooru_login and settings.danbooru_api_key:
        return aiohttp.BasicAuth(settings.danbooru_login, settings.danbooru_api_key)
    return None

async def get_session():
    """Returns the global session or creates one if missing/closed."""
    global _session
    if _session is None or _session.closed:
        # Base URL helps with making requests shorter and shared connection pooling
        _session = aiohttp.ClientSession(
            base_url="https://danbooru.donmai.us",
            headers={"User-Agent": "r34gacha-bot/1.0"}
        )
    return _session

async def close_session():
    """Closes the global session safely."""
    global _session
    if _session and not _session.closed:
        await _session.close()

async def fetch_top_character_tags(limit=1000, page=1):
    """
    Fetch top character tags from Danbooru sorted by post count.
    Danbooru API: GET /tags.json?search[category]=4&search[order]=count&limit=200&page=N
    Category 4 = character
    """
    url = "/tags.json"
    params = {
        "search[category]": "4",
        "search[order]": "count",
        "limit": min(limit, 200),  # Danbooru max is 200 per page
        "page": page,
    }
    
    try:
        session = await get_session()
        async with session.get(url, params=params, auth=get_auth()) as response:
            if response.status == 200:
                return await response.json()
            else:
                logging.error(f"Danbooru tags API returned {response.status}")
    except Exception as e:
        logging.error(f"Network error fetching Danbooru tags: {e}")
    return []

async def sync_characters(session: AsyncSession):
    """Fetch TOP character tags from Danbooru and sync to DB."""
    logging.info("Fetching TOP character tags from Danbooru (sorted by post count)...")
    
    all_tags = []
    for page in range(1, 101):  # 100 pages × 200 = 20000 characters max
        tags = await fetch_top_character_tags(limit=200, page=page)
        if not tags:
            break
        all_tags.extend(tags)
        logging.info(f"Fetched page {page}: {len(tags)} tags (total so far: {len(all_tags)})")
        await asyncio.sleep(0.5)
        
    if not all_tags:
        logging.warning("No tags found. Check Danbooru credentials or network.")
        return
    
    logging.info(f"Total {len(all_tags)} character tags fetched. Syncing to DB...")
    
    new_count = 0
    updated_count = 0
    for tag_data in all_tags:
        name = tag_data.get("name")
        post_count = tag_data.get("post_count", 0)
        
        if not name or post_count < 20:
            continue
        
        stmt = select(Character).where(Character.tag_name == name)
        result = await session.execute(stmt)
        char = result.scalars().first()
        
        if not char:
            session.add(Character(tag_name=name, post_count=post_count))
            new_count += 1
        else:
            char.post_count = post_count
            updated_count += 1
    
    await session.commit()
    logging.info(f"Sync done: {new_count} new, {updated_count} updated characters.")

async def get_best_post_for_character(character_name: str):
    """
    Fetch the best image post for a character from Danbooru.
    Strategy:
    1. Fetch top 20 posts sorted by score (2-tag limit: '{char} order:score').
    2. Pass 1: pick highest-scored post with exactly 1 character (tag_count_character == 1) AND a static image.
    3. Pass 2 (fallback): if none found, pick the highest-scored static image regardless of character count.
    All from the same single API response - no duplicate requests.
    """
    params = {"tags": f"{character_name} order:score", "limit": 20}
    posts = []
    
    try:
        session = await get_session()
        async with session.get(
            "/posts.json",
            params=params,
            auth=get_auth()
        ) as response:
            if response.status == 200:
                posts = await response.json()
                if not isinstance(posts, list):
                    posts = []
    except Exception as e:
        logging.error(f"Error fetching posts for '{character_name}': {e}")


    
    if not posts:
        return None
    
    IMAGE_EXTS = ("jpg", "jpeg", "png", "webp")
    MAX_PHOTO_SIZE = 5_000_000 # 5 MB via URL
    
    # Pass 1: single character + image
    for post in posts:
        is_small = post.get("file_size", 0) <= MAX_PHOTO_SIZE
        if post.get("tag_count_character") == 1 and post.get("file_ext", "").lower() in IMAGE_EXTS and is_small:
            return post.get("large_file_url") or post.get("file_url")
    
    # Pass 2: any image (character may have group arts only)
    for post in posts:
        is_small = post.get("file_size", 0) <= MAX_PHOTO_SIZE
        if post.get("file_ext", "").lower() in IMAGE_EXTS and is_small:
            return post.get("large_file_url") or post.get("file_url")
    
    return None

async def get_posts_for_character(character_name: str, limit: int = 10, page: int = 1):
    """
    Fetch a list of top scored images (and videos/gifs) for a character.
    Used for the gallery/show more feature.
    """
    # Fetch more than needed to ensure we hit the requested 'limit' (10) after filtering
    # We fetch 4x because many characters have WebM/GIFs that we must skip for media groups
    params = {
        "tags": f"{character_name} order:score",
        "limit": limit * 4,
        "page": page
    }
    
    try:
        session = await get_session()
        async with session.get("/posts.json", params=params, auth=get_auth()) as response:
            if response.status == 200:
                posts = await response.json()
                if not isinstance(posts, list):
                    return []
                
                IMAGE_EXTS = ("jpg", "jpeg", "png", "webp")
                VIDEO_EXTS = ("mp4",)
                MAX_PHOTO_SIZE = 5_000_000  # 5 MB via URL
                MAX_VIDEO_SIZE = 20_000_000 # 20 MB via URL
                
                valid_items = []
                for post in posts:
                    ext = post.get("file_ext", "").lower()
                    url = post.get("large_file_url") or post.get("file_url")
                    size = post.get("file_size", 0)
                    if not url: continue
                    
                    if ext in IMAGE_EXTS and size <= MAX_PHOTO_SIZE:
                        valid_items.append({"url": url, "type": "photo"})
                    elif ext in VIDEO_EXTS and size <= MAX_VIDEO_SIZE:
                        valid_items.append({"url": url, "type": "video"})
                    
                    if len(valid_items) >= limit:
                        break
                            
                return valid_items
    except Exception as e:
        logging.error(f"Error fetching multiple posts for '{character_name}': {e}")
        
    return []

async def test_parser():
    async with async_session() as session:
        await sync_characters(session)
        stmt = select(Character).limit(1)
        result = await session.execute(stmt)
        char = result.scalars().first()
        if char:
            print(f"Testing post fetch for: {char.tag_name} ({char.post_count} posts)")
            url = await get_best_post_for_character(char.tag_name)
            print(f"Best post URL: {url}")

if __name__ == "__main__":
    from database import init_models
    from models import Base
    async def run_test():
        await init_models(Base)
        try:
            await test_parser()
        finally:
            await close_session()
    asyncio.run(run_test())
