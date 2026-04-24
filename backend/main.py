from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import APPROVED_ASSETS_DIR, COMPILED_ASSETS_DIR, ensure_directories, settings
from routers import api_router


ensure_directories()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media/approved", StaticFiles(directory=str(APPROVED_ASSETS_DIR)), name="approved-media")
app.mount("/media/compiled", StaticFiles(directory=str(COMPILED_ASSETS_DIR)), name="compiled-media")
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Clipping Automation API is running.",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
