from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from schemas import RedditDiscoveryRequest  # noqa: E402
from services.reddit_discovery_service import (  # noqa: E402
    _build_search_query_plans,
    _build_subreddit_query_terms,
    _build_tag_profile,
    _external_media_type,
    _filter_used_clips,
    _normalize_post,
    _score_clip_tag_relevance,
    mark_reddit_clips_as_used,
)


class RedditDiscoveryServiceTests(unittest.TestCase):
    def test_build_search_query_plans_prioritizes_tag_words(self) -> None:
        plans = _build_search_query_plans(["funny cat", "reaction"])
        queries = [plan.query for plan in plans]

        self.assertIn("funny cat", queries)
        self.assertIn("reaction", queries)
        self.assertTrue(any("funny" in query and "cat" in query for query in queries))

    def test_build_subreddit_query_terms_uses_words_from_tags(self) -> None:
        queries = _build_subreddit_query_terms(["indian street food", "vendor reaction"])

        self.assertIn("indian street food", queries)
        self.assertIn("street", queries)
        self.assertIn("food", queries)
        self.assertIn("reaction", queries)

    def test_score_clip_tag_relevance_prefers_phrase_matches_in_title(self) -> None:
        profile = _build_tag_profile(["funny cat", "reaction"])
        clip = {
            "title": "Funny cat reaction that breaks the internet",
            "description": "",
            "subreddit": "cats",
            "author": "clipmaker",
            "metadata": {
                "link_flair_text": "reaction",
            },
        }

        score = _score_clip_tag_relevance(clip, profile)

        self.assertGreaterEqual(score, 10)

    def test_external_media_type_detects_direct_and_embeds(self) -> None:
        self.assertEqual(_external_media_type("https://cdn.example.com/video.mp4"), ("direct_video", "video", True))
        self.assertEqual(_external_media_type("https://streamable.com/abcd12"), ("external_video", "image", False))

    def test_normalize_post_keeps_audio_ready_reddit_video(self) -> None:
        payload = RedditDiscoveryRequest(tags=["funny cat"])
        post = {
            "id": "abc123",
            "title": "Funny cat clip",
            "selftext": "",
            "subreddit": "cats",
            "score": 100,
            "num_comments": 20,
            "permalink": "/r/cats/comments/abc123/funny_cat_clip/",
            "domain": "v.redd.it",
            "is_video": True,
            "over_18": False,
            "created_utc": 1713643200,
            "secure_media": {
                "reddit_video": {
                    "fallback_url": "https://v.redd.it/example/DASH_720.mp4",
                    "hls_url": "https://v.redd.it/example/HLSPlaylist.m3u8",
                    "has_audio": True,
                    "duration": 12,
                }
            },
            "preview": {
                "images": [
                    {
                        "source": {
                            "url": "https://example.com/thumb.jpg",
                        }
                    }
                ]
            },
        }

        clip = _normalize_post(post, payload=payload)

        self.assertIsNotNone(clip)
        self.assertEqual(clip["media_type"], "reddit_video")
        self.assertTrue(clip["compilation_ready"])

    def test_used_clips_are_filtered_only_after_marking(self) -> None:
        clips = [
            {"external_id": "abc123"},
            {"external_id": "def456"},
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "reddit_used_clips.json"
            with patch("services.reddit_discovery_service.USED_CLIPS_PATH", history_path):
                initial, initial_filtered = _filter_used_clips(clips)
                marked_count = mark_reddit_clips_as_used(["abc123"])
                remaining, filtered_count = _filter_used_clips(clips)

        self.assertEqual([clip["external_id"] for clip in initial], ["abc123", "def456"])
        self.assertEqual(initial_filtered, 0)
        self.assertEqual(marked_count, 1)
        self.assertEqual([clip["external_id"] for clip in remaining], ["def456"])
        self.assertEqual(filtered_count, 1)


if __name__ == "__main__":
    unittest.main()
