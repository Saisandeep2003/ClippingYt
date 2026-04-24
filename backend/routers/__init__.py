from __future__ import annotations

from fastapi import APIRouter

from routers.compilation_router import router as compilation_router
from routers.health_router import router as health_router
from routers.reddit_router import router as reddit_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(reddit_router)
api_router.include_router(compilation_router)
