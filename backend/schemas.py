from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


DISCOVERY_SORT_MODES = {"relevance", "top", "hot", "new", "rising"}
DISCOVERY_TIME_FILTERS = {"day", "week", "month", "year", "all"}
DISCOVERY_PREVIEW_KINDS = {"video", "image", "link"}


class RankingWeights(BaseModel):
    relevance: float = Field(default=0.45, ge=0.0, le=1.0)
    upvotes: float = Field(default=0.30, ge=0.0, le=1.0)
    comments: float = Field(default=0.15, ge=0.0, le=1.0)
    recency: float = Field(default=0.10, ge=0.0, le=1.0)

    @field_validator("recency")
    @classmethod
    def validate_total_weight(cls, value: float, info: Any) -> float:
        data = info.data
        total = (
            float(data.get("relevance", 0.45))
            + float(data.get("upvotes", 0.30))
            + float(data.get("comments", 0.15))
            + float(value)
        )
        if total <= 0:
            raise ValueError("At least one ranking weight must be greater than zero.")
        return value


class RedditDiscoveryRequest(BaseModel):
    tags: list[str] = Field(..., min_length=1, max_length=20)
    subreddits: list[str] | None = Field(default=None, max_length=20)
    max_results: int = Field(default=12, ge=1, le=50)
    page: int = Field(default=1, ge=1, le=100)
    sort_mode: str = Field(default="relevance", min_length=3, max_length=20)
    time_filter: str = Field(default="week", min_length=3, max_length=20)
    allow_nsfw: bool = False
    include_external_media: bool = False
    ranking_weights: RankingWeights | None = None

    @field_validator("tags", "subreddits")
    @classmethod
    def validate_entries(cls, values: list[str] | None, info: Any) -> list[str] | None:
        if values is None:
            if info.field_name == "subreddits":
                return None
            raise ValueError("At least one non-empty value is required.")

        cleaned: list[str] = []
        seen: set[str] = set()

        for raw_value in values:
            value = raw_value.strip()
            if info.field_name == "subreddits" and value.lower().startswith("r/"):
                value = value[2:].strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(value)

        if not cleaned:
            if info.field_name == "subreddits":
                return None
            raise ValueError("At least one non-empty value is required.")

        return cleaned

    @field_validator("sort_mode")
    @classmethod
    def validate_sort_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in DISCOVERY_SORT_MODES:
            raise ValueError(f"sort_mode must be one of: {', '.join(sorted(DISCOVERY_SORT_MODES))}.")
        return normalized

    @field_validator("time_filter")
    @classmethod
    def validate_time_filter(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in DISCOVERY_TIME_FILTERS:
            raise ValueError(f"time_filter must be one of: {', '.join(sorted(DISCOVERY_TIME_FILTERS))}.")
        return normalized


class RedditClipRead(BaseModel):
    external_id: str
    title: str
    source: str
    subreddit: str
    source_url: str
    video_url: str
    preview_url: str
    thumbnail_url: str | None = None
    preview_kind: str = "video"
    media_type: str = "reddit_video"
    domain: str | None = None
    upvotes: int = 0
    comments: int = 0
    engagement: int = 0
    duration_seconds: int | None = None
    permalink: str
    created_at: str | None = None
    final_score: float = 0.0
    relevance_score: float = 0.0
    rank_position: int = 0
    compilation_ready: bool = True
    selection_reason: str

    @field_validator("preview_kind")
    @classmethod
    def validate_preview_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in DISCOVERY_PREVIEW_KINDS:
            raise ValueError(f"preview_kind must be one of: {', '.join(sorted(DISCOVERY_PREVIEW_KINDS))}.")
        return normalized


class RedditDiscoveryResponse(BaseModel):
    items: list[RedditClipRead]
    total_safe: int
    total_results: int
    checked_count: int
    rejected_count: int
    cached_count: int
    searched_subreddits: list[str] = Field(default_factory=list)
    page: int = 1
    page_size: int = 0
    has_more: bool = False
    next_page: int | None = None
    sort_mode: str = "relevance"
    time_filter: str = "week"
    source_mode: str = "public"
    warnings: list[str] = Field(default_factory=list)


class CompilationClipInput(BaseModel):
    external_id: str | None = Field(default=None, max_length=255)
    url: str = Field(..., min_length=1, max_length=2000)
    title: str = Field(..., min_length=1, max_length=500)
    source: str = Field(..., min_length=1, max_length=255)
    rank: int = Field(..., ge=1, le=5)
    subreddit: str | None = Field(default=None, max_length=255)
    duration_seconds: int | None = Field(default=None, ge=0, le=24)


class CompilationRenderRequest(BaseModel):
    selected_clips: list[CompilationClipInput] = Field(..., min_length=1, max_length=5)
    title: str | None = Field(default=None, max_length=255)


class CompilationRenderResponse(BaseModel):
    title: str
    output_url: str
    output_path: str
    clip_count: int
    total_duration_seconds: int


class CompilationUsageRequest(BaseModel):
    external_ids: list[str] = Field(..., min_length=1, max_length=20)

    @field_validator("external_ids")
    @classmethod
    def validate_external_ids(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()

        for raw_value in values:
            value = raw_value.strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(value)

        if not cleaned:
            raise ValueError("At least one non-empty external id is required.")

        return cleaned


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
