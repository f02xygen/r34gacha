from aiogram import Router
from .common import router as common_router
from .gacha import router as gacha_router
from .collection import router as collection_router
from .conversion import router as conversion_router

router = Router()
router.include_routers(
    common_router,
    gacha_router,
    collection_router,
    conversion_router
)
