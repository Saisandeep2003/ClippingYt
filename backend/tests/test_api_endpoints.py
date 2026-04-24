from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.requests import Request


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import root  # noqa: E402
from routers.compilation_router import (  # noqa: E402
    mark_compilation_clips_used,
    render_compilation_endpoint,
)
from routers.health_router import health_check  # noqa: E402
from routers.reddit_router import (  # noqa: E402
    discover_reddit_clips,
    get_reddit_topic_markers,
)
from schemas import (  # noqa: E402
    CompilationUsageRequest,
    CompilationRenderResponse,
    CompilationRenderRequest,
    RedditClipRead,
    RedditDiscoveryRequest,
    RedditDiscoveryResponse,
    RedditTopicCatalogResponse,
    RedditTopicMarkerRead,
)


def _make_test_video(path: Path, duration_seconds: int = 1) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=720x1280:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000",
            "-t",
            str(duration_seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


class ApiEndpointTests(unittest.TestCase):
    def test_root_endpoint_reports_docs_links(self) -> None:
        response = root()

        self.assertEqual(response["message"], "Clipping Automation API is running.")
        self.assertEqual(response["docs"], "/docs")

    def test_health_endpoint_reports_status(self) -> None:
        response = health_check()

        self.assertEqual(response.status, "ok")
        self.assertTrue(response.version)

    def test_topic_catalog_endpoint_returns_items(self) -> None:
        catalog = RedditTopicCatalogResponse(
            items=[
                RedditTopicMarkerRead(
                    key="animal",
                    label="Animal",
                    subreddits=["animalsdoingstuff"],
                )
            ]
        )

        with patch("routers.reddit_router.list_reddit_topic_markers", return_value=catalog):
            response = get_reddit_topic_markers()

        self.assertEqual(response.items[0].key, "animal")

    def test_discovery_endpoint_returns_absolute_clip_urls(self) -> None:
        response_model = RedditDiscoveryResponse(
            items=[
                RedditClipRead(
                    external_id="abc123",
                    title="Short clip",
                    source="reddit",
                    subreddit="animalsdoingstuff",
                    topic_markers=["animal"],
                    source_url="https://reddit.com/r/test/comments/abc123",
                    video_url="/api/reddit/clips/abc123/playback",
                    preview_url="/api/reddit/clips/abc123/playback",
                    thumbnail_url=None,
                    preview_kind="video",
                    media_type="reddit_video",
                    domain="v.redd.it",
                    upvotes=12,
                    comments=3,
                    engagement=15,
                    duration_seconds=6,
                    permalink="/r/test/comments/abc123",
                    created_at="2026-04-24T12:00:00Z",
                    final_score=42.0,
                    relevance_score=0.0,
                    rank_position=1,
                    compilation_ready=True,
                    selection_reason="Shortest clip from the selected topics.",
                )
            ],
            total_safe=1,
            total_results=1,
            searched_subreddits=["animalsdoingstuff"],
            page=1,
            page_size=1,
            has_more=False,
            next_page=None,
            source_mode="oauth",
            warnings=[],
        )

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/reddit/discover",
                "headers": [],
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
            }
        )

        with patch(
            "routers.reddit_router.discover_safe_reddit_clips",
            new=AsyncMock(return_value=response_model),
        ):
            response = asyncio.run(
                discover_reddit_clips(
                    request,
                    RedditDiscoveryRequest(topic_markers=["animal"], max_results=12, page=1),
                )
            )

        item = response.items[0]
        self.assertEqual(item.video_url, "http://testserver/api/reddit/clips/abc123/playback")
        self.assertEqual(item.preview_url, "http://testserver/api/reddit/clips/abc123/playback")

    def test_mark_used_endpoint_returns_marked_count(self) -> None:
        with patch("routers.compilation_router.mark_reddit_clips_as_used", return_value=2):
            response = mark_compilation_clips_used(
                CompilationUsageRequest(external_ids=["abc123", "def456"])
            )

        self.assertEqual(response, {"marked_count": 2})

    def test_render_endpoint_renders_a_compilation_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_raw:
            tmp_dir = Path(tmp_dir_raw)
            source_path = tmp_dir / "source.mp4"
            outro_path = tmp_dir / "outro.mp4"
            compiled_dir = tmp_dir / "compiled"
            compiled_dir.mkdir()

            _make_test_video(source_path, duration_seconds=1)
            _make_test_video(outro_path, duration_seconds=1)

            with patch("services.compilation_service.OUTRO_PATH", outro_path), patch(
                "services.compilation_service.COMPILED_ASSETS_DIR",
                compiled_dir,
            ):
                response = render_compilation_endpoint(
                    CompilationRenderRequest(
                        title="API render smoke",
                        selected_clips=[
                            {
                                "external_id": "clip-1",
                                "url": str(source_path),
                                "title": "Generated test clip",
                                "source": "reddit",
                                "rank": 1,
                                "subreddit": "animalsdoingstuff",
                                "duration_seconds": 1,
                            }
                        ],
                    )
                )

                payload = CompilationRenderResponse.model_validate(response.model_dump())
                self.assertEqual(payload.clip_count, 1)
                self.assertGreaterEqual(payload.total_duration_seconds, 2)
                self.assertTrue(Path(payload.output_path).exists())


if __name__ == "__main__":
    unittest.main()
