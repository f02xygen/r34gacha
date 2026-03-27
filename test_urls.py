import asyncio
from parser import get_posts_for_character

async def main():
    items = await get_posts_for_character("iruma_miu", limit=10, page=1)
    for item in items:
        print(item["url"])

asyncio.run(main())
