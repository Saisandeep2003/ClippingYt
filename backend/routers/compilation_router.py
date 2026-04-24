from __future__ import annotations

from fastapi import APIRouter, status

from schemas import CompilationRenderRequest, CompilationRenderResponse, CompilationUsageRequest
from services.compilation_service import render_compilation
from services.reddit_discovery_service import mark_reddit_clips_as_used


router = APIRouter(prefix="/compilation", tags=["compilation"])


@router.post("/render", response_model=CompilationRenderResponse, status_code=status.HTTP_201_CREATED)
def render_compilation_endpoint(payload: CompilationRenderRequest) -> CompilationRenderResponse:
    return render_compilation(payload)


@router.post("/mark-used", status_code=status.HTTP_200_OK)
def mark_compilation_clips_used(payload: CompilationUsageRequest) -> dict[str, int]:
    return {
        "marked_count": mark_reddit_clips_as_used(payload.external_ids),
    }
