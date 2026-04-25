from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import APPROVED_ASSETS_DIR, COMPILED_ASSETS_DIR, ROOT_DIR, ensure_directories, settings
from routers import api_router


ensure_directories()
FRONTEND_BUILD_DIR = ROOT_DIR / "frontend" / "build"
FRONTEND_INDEX_PATH = FRONTEND_BUILD_DIR / "index.html"
SERVE_FRONTEND = os.getenv("SERVE_FRONTEND", "").strip().lower() in {"1", "true", "yes"}


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


@app.get("/", response_model=None)
def root() -> dict[str, str] | FileResponse:
    if SERVE_FRONTEND and FRONTEND_INDEX_PATH.exists():
        return FileResponse(FRONTEND_INDEX_PATH)

    return {
        "message": "Clipping Automation API is running.",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


if SERVE_FRONTEND and FRONTEND_BUILD_DIR.exists():
    static_dir = FRONTEND_BUILD_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="frontend-static")


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
def serve_frontend_app(full_path: str) -> FileResponse:
    if SERVE_FRONTEND and FRONTEND_INDEX_PATH.exists():
        return FileResponse(FRONTEND_INDEX_PATH)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
