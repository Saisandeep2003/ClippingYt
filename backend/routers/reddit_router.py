from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from schemas import RedditDiscoveryRequest, RedditDiscoveryResponse
from services.reddit_discovery_service import discover_safe_reddit_clips, get_reddit_clip_playback_response


router = APIRouter(prefix="/reddit", tags=["reddit"])


@router.post("/discover", response_model=RedditDiscoveryResponse)
async def discover_reddit_clips(
    request: Request,
    payload: RedditDiscoveryRequest,
) -> RedditDiscoveryResponse:
    response = await discover_safe_reddit_clips(payload)
    for item in response.items:
        if item.video_url.startswith("/"):
            item.video_url = str(request.base_url).rstrip("/") + item.video_url
        if item.preview_url.startswith("/"):
            item.preview_url = str(request.base_url).rstrip("/") + item.preview_url
    return response


@router.get("/clips/{external_id}/playback", name="reddit_clip_playback")
def get_reddit_clip_playback(external_id: str) -> FileResponse:
    return get_reddit_clip_playback_response(external_id)
