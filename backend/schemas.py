from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


DISCOVERY_PREVIEW_KINDS = {"video", "image", "link"}


class RedditDiscoveryRequest(BaseModel):
    topic_markers: list[str] = Field(..., min_length=1, max_length=20)
    max_results: int = Field(default=12, ge=1, le=50)
    page: int = Field(default=1, ge=1, le=100)

    @field_validator("topic_markers")
    @classmethod
    def validate_entries(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()

        for raw_value in values:
            value = raw_value.strip()
            value = value.lower().replace(" ", "_")
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(value)

        if not cleaned:
            raise ValueError("At least one topic marker is required.")

        return cleaned


class RedditClipRead(BaseModel):
    external_id: str
    title: str
    source: str
    subreddit: str
    topic_markers: list[str] = Field(default_factory=list)
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
    searched_subreddits: list[str] = Field(default_factory=list)
    page: int = 1
    page_size: int = 0
    has_more: bool = False
    next_page: int | None = None
    source_mode: str = "public"
    warnings: list[str] = Field(default_factory=list)


class RedditTopicMarkerRead(BaseModel):
    key: str
    label: str
    subreddits: list[str] = Field(default_factory=list)


class RedditTopicCatalogResponse(BaseModel):
    items: list[RedditTopicMarkerRead] = Field(default_factory=list)


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
