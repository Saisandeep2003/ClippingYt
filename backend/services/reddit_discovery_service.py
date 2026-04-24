from __future__ import annotations

import asyncio
import base64
import json
import math
import re
import ssl
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import certifi
from fastapi import HTTPException, status
from fastapi.responses import FileResponse

from config import APPROVED_ASSETS_DIR, STATE_DIR, settings
from schemas import RankingWeights, RedditClipRead, RedditDiscoveryRequest, RedditDiscoveryResponse


PUBLIC_REDDIT_BASE_URL = "https://www.reddit.com"
OAUTH_REDDIT_BASE_URL = "https://oauth.reddit.com"
OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_USER_AGENT = settings.reddit_user_agent
MAX_QUERY_MULTIPLIER = 4
MAX_QUERY_LIMIT = 75
MAX_RELATED_SUBREDDITS = 12
MAX_SEARCH_QUERY_PLANS = 5
MAX_SUBREDDIT_QUERY_PLANS = 10
MAX_QUERY_TERMS = 4
MIN_SEARCH_TOKEN_LENGTH = 2
MAX_CLIP_DURATION_SECONDS = 60
DISCOVERY_HISTORY_MAX_IDS = 10000
CLIP_SOURCE_REGISTRY_MAX_ENTRIES = 5000
SEARCH_CACHE_TTL_SECONDS = 180
SEARCH_CACHE_MAX_ENTRIES = 512
SEARCH_REQUEST_CONCURRENCY = 3
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_MAX_ATTEMPTS = 3
PLAYBACK_TIMEOUT_SECONDS = 180
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
SEARCH_CACHE_LOCK = threading.Lock()
SEARCH_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
TOKEN_CACHE_LOCK = threading.Lock()
TOKEN_CACHE: tuple[float, str] | None = None
USED_CLIPS_LOCK = threading.Lock()
USED_CLIPS_PATH = STATE_DIR / "reddit_used_clips.json"
CLIP_SOURCE_REGISTRY_LOCK = threading.Lock()
CLIP_SOURCE_REGISTRY_PATH = STATE_DIR / "reddit_clip_sources.json"
PLAYBACK_CACHE_LOCK = threading.Lock()
PLAYBACK_CACHE_DIR = APPROVED_ASSETS_DIR / "reddit-playback-cache"
SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_'-]*")
DIRECT_VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v")
EXTERNAL_MEDIA_DOMAINS = {
    "clips.twitch.tv",
    "streamable.com",
    "youtube.com",
    "youtu.be",
}
TAG_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "best",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "our",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "vs",
    "with",
}


@dataclass(frozen=True)
class SearchQueryPlan:
    query: str
    syntax: str = "plain"


@dataclass(frozen=True)
class TagProfile:
    phrases: tuple[str, ...]
    terms: tuple[str, ...]


@dataclass(frozen=True)
class ApiContext:
    base_url: str
    headers: dict[str, str]
    source_mode: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    return url.replace("&amp;", "&").strip()


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().split())


def _tokenize_search_text(value: str | None) -> list[str]:
    return SEARCH_TOKEN_PATTERN.findall(_normalize_text(value).lower())


def _unique_terms(terms: list[str]) -> list[str]:
    unique_terms: list[str] = []
    seen: set[str] = set()

    for term in terms:
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_terms.append(lowered)

    return unique_terms


def _significant_terms_for_tag(tag: str) -> list[str]:
    tokens = _tokenize_search_text(tag)
    preferred = [
        token
        for token in tokens
        if len(token) >= MIN_SEARCH_TOKEN_LENGTH and (len(token) > 2 or token.isdigit()) and token not in TAG_STOPWORDS
    ]
    if preferred:
        return _unique_terms(preferred)

    fallback = [token for token in tokens if len(token) >= MIN_SEARCH_TOKEN_LENGTH or token.isdigit()]
    return _unique_terms(fallback)


def _build_tag_profile(tags: list[str]) -> TagProfile:
    normalized_tags = [_normalize_text(tag).lower() for tag in tags if _normalize_text(tag)]
    phrases = tuple(
        phrase
        for phrase in _unique_terms([tag for tag in normalized_tags if len(_tokenize_search_text(tag)) > 1])
    )

    terms: list[str] = []
    for tag in normalized_tags:
        terms.extend(_significant_terms_for_tag(tag))

    return TagProfile(
        phrases=phrases,
        terms=tuple(_unique_terms(terms)),
    )


def _rank_tag_terms(tags: list[str]) -> list[str]:
    frequency: dict[str, int] = {}
    first_seen: dict[str, int] = {}

    for index, tag in enumerate(tags):
        for term in _significant_terms_for_tag(tag):
            frequency[term] = frequency.get(term, 0) + 1
            first_seen.setdefault(term, index)

    return sorted(
        frequency,
        key=lambda term: (-frequency[term], -len(term), first_seen[term], term),
    )


def _build_search_query_plans(tags: list[str]) -> list[SearchQueryPlan]:
    normalized_tags = [_normalize_text(tag).lower() for tag in tags if _normalize_text(tag)]
    if not normalized_tags:
        return []

    ranked_tags = sorted(
        normalized_tags,
        key=lambda value: (-len(_significant_terms_for_tag(value)), -len(value)),
    )
    ranked_terms = _rank_tag_terms(ranked_tags)
    plans: list[SearchQueryPlan] = []
    seen: set[str] = set()

    def add_plan(query: str) -> None:
        normalized_query = _normalize_text(query)
        if not normalized_query or normalized_query in seen or len(plans) >= MAX_SEARCH_QUERY_PLANS:
            return
        seen.add(normalized_query)
        plans.append(SearchQueryPlan(query=normalized_query))

    combined_terms = list(ranked_terms[:MAX_QUERY_TERMS])
    if len(combined_terms) > 1:
        add_plan(" ".join(combined_terms))

    for tag in ranked_tags:
        add_plan(tag)

    for term in ranked_terms:
        add_plan(term)

    return plans[:MAX_SEARCH_QUERY_PLANS]


def _build_subreddit_query_terms(tags: list[str]) -> list[str]:
    normalized_tags = [_normalize_text(tag).lower() for tag in tags if _normalize_text(tag)]
    if not normalized_tags:
        return []

    ranked_tags = sorted(
        normalized_tags,
        key=lambda value: (-len(_significant_terms_for_tag(value)), -len(value)),
    )
    ranked_terms = _rank_tag_terms(ranked_tags)
    queries: list[str] = []
    seen: set[str] = set()

    def add_query(query: str) -> None:
        normalized_query = _normalize_text(query).lower()
        if not normalized_query or normalized_query in seen or len(queries) >= MAX_SUBREDDIT_QUERY_PLANS:
            return
        seen.add(normalized_query)
        queries.append(normalized_query)

    for tag in ranked_tags:
        add_query(tag)

    combined_terms = list(ranked_terms[:MAX_QUERY_TERMS])
    if len(combined_terms) > 1:
        add_query(" ".join(combined_terms))

    for term in ranked_terms:
        add_query(term)

    return queries[:MAX_SUBREDDIT_QUERY_PLANS]


def _cached_search_payload(url: str, source_mode: str) -> dict[str, Any] | None:
    cache_key = (url, source_mode)
    now = time.monotonic()

    with SEARCH_CACHE_LOCK:
        cached_entry = SEARCH_CACHE.get(cache_key)
        if cached_entry is None:
            return None

        cached_at, payload = cached_entry
        if now - cached_at > SEARCH_CACHE_TTL_SECONDS:
            SEARCH_CACHE.pop(cache_key, None)
            return None

        return payload


def _store_search_payload(url: str, source_mode: str, payload: dict[str, Any]) -> dict[str, Any]:
    cache_key = (url, source_mode)

    with SEARCH_CACHE_LOCK:
        SEARCH_CACHE[cache_key] = (time.monotonic(), payload)
        if len(SEARCH_CACHE) > SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(SEARCH_CACHE.items(), key=lambda item: item[1][0])[0]
            SEARCH_CACHE.pop(oldest_key, None)

    return payload


def _sleep_for_retry(retry_after: str | None, attempt: int) -> None:
    if retry_after:
        try:
            time.sleep(max(0.0, min(float(retry_after), 8.0)))
            return
        except ValueError:
            pass
    time.sleep(min(2**attempt, 8))


def _parse_reddit_error_detail(detail: str, status_code: int) -> str:
    cleaned = detail.strip()
    if not cleaned:
        return f"Reddit request failed with status {status_code}."

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned

    if isinstance(payload, dict):
        reason = _normalize_text(str(payload.get("reason") or ""))
        message = _normalize_text(str(payload.get("message") or ""))
        if reason and message:
            return f"{message}: {reason}"
        if message:
            return message
        if reason:
            return reason

    return cleaned


def _request_json_via_curl(
    url: str,
    *,
    headers: dict[str, str],
    source_mode: str,
    method: str = "GET",
    data: str | None = None,
    original_error: Exception | None = None,
) -> dict[str, Any]:
    marker = "__HTTP_STATUS__:"
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--compressed",
        "--request",
        method,
        "--write-out",
        f"\n{marker}%{{http_code}}",
        "--connect-timeout",
        str(REQUEST_TIMEOUT_SECONDS),
        "--max-time",
        str(REQUEST_TIMEOUT_SECONDS),
        "--cacert",
        certifi.where(),
    ]

    for header_name, header_value in headers.items():
        command.extend(["--header", f"{header_name}: {header_value}"])

    if data is not None:
        command.extend(["--data", data])

    command.append(url)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=REQUEST_TIMEOUT_SECONDS + 5,
        )
    except FileNotFoundError as exc:
        detail = "Unable to reach Reddit for clip discovery."
        if original_error is not None:
            detail = f"{detail} Python SSL error: {original_error}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timed out while reaching Reddit for clip discovery.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = stderr or "Unable to reach Reddit for clip discovery."
        if original_error is not None:
            detail = f"{detail} Python SSL error: {original_error}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc

    payload, _, status_line = result.stdout.rpartition(f"\n{marker}")
    http_status = _to_int(status_line.strip())

    if http_status == 429:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reddit rate-limited the discovery request. Please try again in a moment.",
        )

    if http_status in {403, 404}:
        body_snippet = payload.strip()[:500]
        raise HTTPException(
            status_code=http_status,
            detail=_parse_reddit_error_detail(body_snippet, http_status),
        )

    if http_status >= 400:
        body_snippet = payload.strip()[:500]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_parse_reddit_error_detail(body_snippet, http_status),
        )

    try:
        return _store_search_payload(url, source_mode, json.loads(payload))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Reddit returned an unreadable response.",
        ) from exc


def _request_json(url: str, *, headers: dict[str, str], source_mode: str) -> dict[str, Any]:
    cached_payload = _cached_search_payload(url, source_mode)
    if cached_payload is not None:
        return cached_payload

    last_error: Exception | None = None

    for attempt in range(REQUEST_MAX_ATTEMPTS):
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=SSL_CONTEXT) as response:
                payload = response.read().decode("utf-8")
            return _store_search_payload(url, source_mode, json.loads(payload))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            last_error = exc
            if exc.code == 429:
                if attempt < REQUEST_MAX_ATTEMPTS - 1:
                    _sleep_for_retry(exc.headers.get("Retry-After"), attempt)
                    continue
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Reddit rate-limited the discovery request. Please try again in a moment.",
                ) from exc
            if exc.code in {403, 404}:
                raise HTTPException(
                    status_code=exc.code,
                    detail=_parse_reddit_error_detail(detail, exc.code),
                ) from exc
            if 500 <= exc.code < 600 and attempt < REQUEST_MAX_ATTEMPTS - 1:
                _sleep_for_retry(exc.headers.get("Retry-After"), attempt)
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_parse_reddit_error_detail(detail, exc.code),
            ) from exc
        except URLError as exc:
            last_error = exc
            reason = getattr(exc, "reason", exc)
            if "CERTIFICATE_VERIFY_FAILED" in str(reason):
                return _request_json_via_curl(
                    url,
                    headers=headers,
                    source_mode=source_mode,
                    original_error=reason,
                )
            if attempt < REQUEST_MAX_ATTEMPTS - 1:
                _sleep_for_retry(None, attempt)
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to reach Reddit for clip discovery: {reason}",
            ) from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Reddit returned an unreadable response.",
            ) from exc

    if last_error is not None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach Reddit for clip discovery.",
        ) from last_error

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Unable to reach Reddit for clip discovery.",
    )


def _get_cached_oauth_token() -> str | None:
    with TOKEN_CACHE_LOCK:
        if TOKEN_CACHE is None:
            return None
        expires_at, token = TOKEN_CACHE
        if time.monotonic() >= expires_at:
            return None
        return token


def _store_oauth_token(token: str, expires_in: int) -> None:
    global TOKEN_CACHE
    with TOKEN_CACHE_LOCK:
        TOKEN_CACHE = (time.monotonic() + max(30, expires_in - 60), token)


def _fetch_oauth_token() -> str:
    cached_token = _get_cached_oauth_token()
    if cached_token is not None:
        return cached_token

    client_id = settings.reddit_client_id
    client_secret = settings.reddit_client_secret
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth credentials are not configured.",
        )

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = Request(
        OAUTH_TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=b"grant_type=client_credentials",
        method="POST",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=SSL_CONTEXT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        if "CERTIFICATE_VERIFY_FAILED" in str(reason):
            payload = _request_json_via_curl(
                OAUTH_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                source_mode="oauth_token",
                method="POST",
                data="grant_type=client_credentials",
                original_error=reason,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to initialize Reddit OAuth access.",
            ) from exc
    except (HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to initialize Reddit OAuth access.",
        ) from exc

    access_token = str(payload.get("access_token") or "").strip()
    expires_in = _to_int(payload.get("expires_in")) or 3600
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reddit OAuth did not return an access token.",
        )

    _store_oauth_token(access_token, expires_in)
    return access_token


def _build_api_context() -> tuple[ApiContext, list[str]]:
    warnings: list[str] = []

    if settings.reddit_client_id and settings.reddit_client_secret:
        try:
            access_token = _fetch_oauth_token()
            return (
                ApiContext(
                    base_url=OAUTH_REDDIT_BASE_URL,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {access_token}",
                        "User-Agent": DEFAULT_USER_AGENT,
                    },
                    source_mode="oauth",
                ),
                warnings,
            )
        except HTTPException:
            warnings.append("OAuth access was unavailable, so discovery fell back to Reddit's public endpoints.")

    return (
        ApiContext(
            base_url=PUBLIC_REDDIT_BASE_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            source_mode="public",
        ),
        warnings,
    )


def _read_used_clips_unlocked() -> list[str]:
    if not USED_CLIPS_PATH.exists():
        return []

    try:
        payload = json.loads(USED_CLIPS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []

    clip_ids = payload.get("clip_ids")
    if not isinstance(clip_ids, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()

    for value in clip_ids:
        if not isinstance(value, str):
            continue
        normalized_value = value.strip().lower()
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        cleaned.append(normalized_value)

    return cleaned


def _write_used_clips_unlocked(clip_ids: list[str]) -> None:
    deduped = _unique_terms([clip_id.strip().lower() for clip_id in clip_ids if clip_id.strip()])
    payload = {
        "updated_at": _utc_now_iso(),
        "clip_ids": deduped[-DISCOVERY_HISTORY_MAX_IDS:],
    }
    USED_CLIPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USED_CLIPS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def mark_reddit_clips_as_used(external_ids: list[str]) -> int:
    normalized_ids = _unique_terms([external_id.strip().lower() for external_id in external_ids if external_id.strip()])
    if not normalized_ids:
        return 0

    with USED_CLIPS_LOCK:
        existing_ids = _read_used_clips_unlocked()
        existing_lookup = set(existing_ids)
        new_ids = [external_id for external_id in normalized_ids if external_id not in existing_lookup]
        if not new_ids:
            return 0
        _write_used_clips_unlocked(existing_ids + new_ids)
        return len(new_ids)


def _read_clip_source_registry_unlocked() -> dict[str, dict[str, Any]]:
    if not CLIP_SOURCE_REGISTRY_PATH.exists():
        return {}

    try:
        payload = json.loads(CLIP_SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    clips = payload.get("clips")
    if not isinstance(clips, dict):
        return {}

    cleaned: dict[str, dict[str, Any]] = {}
    for key, value in clips.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        normalized_key = key.strip().lower()
        if not normalized_key:
            continue
        cleaned[normalized_key] = value
    return cleaned


def _write_clip_source_registry_unlocked(registry: dict[str, dict[str, Any]]) -> None:
    ordered_items = sorted(
        registry.items(),
        key=lambda item: str(item[1].get("stored_at") or ""),
    )
    trimmed_items = ordered_items[-CLIP_SOURCE_REGISTRY_MAX_ENTRIES:]
    payload = {
        "updated_at": _utc_now_iso(),
        "clips": {key: value for key, value in trimmed_items},
    }
    CLIP_SOURCE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLIP_SOURCE_REGISTRY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _store_clip_sources(clips: list[dict[str, Any]]) -> None:
    if not clips:
        return

    with CLIP_SOURCE_REGISTRY_LOCK:
        registry = _read_clip_source_registry_unlocked()
        stored_at = _utc_now_iso()

        for clip in clips:
            external_id = str(clip.get("external_id") or "").strip().lower()
            if not external_id:
                continue
            metadata = clip.get("metadata") or {}
            registry[external_id] = {
                "hls_url": _normalize_url(metadata.get("hls_url")),
                "fallback_url": _normalize_url(metadata.get("fallback_url")),
                "source_url": _normalize_url(clip.get("source_url")),
                "stored_at": stored_at,
            }

        _write_clip_source_registry_unlocked(registry)


def _get_clip_source(external_id: str) -> dict[str, Any] | None:
    with CLIP_SOURCE_REGISTRY_LOCK:
        registry = _read_clip_source_registry_unlocked()
        return registry.get(external_id.strip().lower())


def _clip_playback_api_path(external_id: str) -> str:
    return f"/api/reddit/clips/{quote(external_id)}/playback"


def _clip_playback_file_path(external_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", external_id).strip("-") or "reddit-clip"
    return PLAYBACK_CACHE_DIR / f"{safe_id}.mp4"


async def _run_limited_searches(tasks: list[Any]) -> list[Any]:
    semaphore = asyncio.Semaphore(SEARCH_REQUEST_CONCURRENCY)

    async def run_task(task: Any) -> Any:
        async with semaphore:
            return await task

    return await asyncio.gather(*(run_task(task) for task in tasks))


def _build_json_url(base_url: str, path: str, params: dict[str, str | int | None]) -> str:
    filtered = {key: str(value) for key, value in params.items() if value is not None and value != ""}
    return f"{base_url}{path}?{urlencode(filtered)}"


async def _search_related_subreddits(
    *,
    query: str,
    allow_nsfw: bool,
    api_context: ApiContext,
    warnings: list[str],
) -> list[dict[str, Any]]:
    url = _build_json_url(
        api_context.base_url,
        "/subreddits/search.json",
        {
            "q": query,
            "limit": MAX_RELATED_SUBREDDITS,
            "include_over_18": "on" if allow_nsfw else "off",
            "raw_json": 1,
        },
    )

    try:
        payload = await asyncio.to_thread(_request_json, url, headers=api_context.headers, source_mode=api_context.source_mode)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}:
            warnings.append(f"Skipped restricted subreddit matches for query '{query}'.")
            return []
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            warnings.append("Reddit rate-limited some subreddit discovery requests, so results may be incomplete.")
            return []
        raise

    return [child.get("data") or {} for child in payload.get("data", {}).get("children", [])]


def _score_subreddit_match(subreddit_data: dict[str, Any], tag_profile: TagProfile) -> int:
    name = _normalize_text(str(subreddit_data.get("display_name") or "")).lower()
    title = _normalize_text(str(subreddit_data.get("title") or "")).lower()
    description = _normalize_text(
        " ".join(
            [
                str(subreddit_data.get("public_description") or ""),
                str(subreddit_data.get("description") or ""),
            ]
        )
    ).lower()
    name_tokens = set(_tokenize_search_text(name))
    title_tokens = set(_tokenize_search_text(title))
    description_tokens = set(_tokenize_search_text(description))

    score = 0
    for phrase in tag_profile.phrases:
        if phrase in name:
            score += 14
        elif phrase in title:
            score += 10
        elif phrase in description:
            score += 6

    for term in tag_profile.terms:
        if term in name_tokens:
            score += 5
        elif term in title_tokens:
            score += 3
        elif term in description_tokens:
            score += 1

    return score


async def _discover_related_subreddits(
    *,
    tags: list[str],
    allow_nsfw: bool,
    api_context: ApiContext,
    warnings: list[str],
) -> list[str]:
    tag_profile = _build_tag_profile(tags)
    queries = _build_subreddit_query_terms(tags)
    if not queries:
        return []

    search_results = await _run_limited_searches(
        [
            _search_related_subreddits(
                query=query,
                allow_nsfw=allow_nsfw,
                api_context=api_context,
                warnings=warnings,
            )
            for query in queries
        ]
    )

    ranked: dict[str, tuple[int, int, str]] = {}
    for index, results in enumerate(search_results):
        query_bonus = max(1, len(queries) - index)
        for subreddit_data in results:
            subreddit_name = _normalize_text(str(subreddit_data.get("display_name") or ""))
            if not subreddit_name:
                continue
            lowered = subreddit_name.lower()
            if not allow_nsfw and bool(subreddit_data.get("over18")):
                continue

            match_score = _score_subreddit_match(subreddit_data, tag_profile)
            if match_score <= 0:
                continue

            subscribers = _to_int(subreddit_data.get("subscribers"))
            candidate = (match_score + query_bonus, subscribers, subreddit_name)
            if lowered not in ranked or candidate > ranked[lowered]:
                ranked[lowered] = candidate

    sorted_names = [
        subreddit_name
        for _, _, subreddit_name in sorted(
            ranked.values(),
            key=lambda item: (-item[0], -item[1], item[2].lower()),
        )
    ]
    return sorted_names[:MAX_RELATED_SUBREDDITS]


async def _fetch_subreddit_search_posts(
    *,
    subreddit: str,
    plan: SearchQueryPlan,
    sort_mode: str,
    time_filter: str,
    limit: int,
    api_context: ApiContext,
    warnings: list[str],
) -> list[dict[str, Any]]:
    url = _build_json_url(
        api_context.base_url,
        f"/r/{quote(subreddit)}/search.json",
        {
            "q": plan.query,
            "restrict_sr": "on",
            "sort": sort_mode,
            "syntax": plan.syntax,
            "t": time_filter,
            "type": "link",
            "limit": limit,
            "raw_json": 1,
        },
    )

    try:
        payload = await asyncio.to_thread(_request_json, url, headers=api_context.headers, source_mode=api_context.source_mode)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}:
            return []
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            warnings.append(f"Reddit rate-limited search requests for r/{subreddit}, so some results may be missing.")
            return []
        raise

    results = [child.get("data") or {} for child in payload.get("data", {}).get("children", [])]
    for post in results:
        post["_discovery_query"] = plan.query
    return results


async def _fetch_subreddit_listing_posts(
    *,
    subreddit: str,
    sort_mode: str,
    time_filter: str,
    limit: int,
    api_context: ApiContext,
    warnings: list[str],
) -> list[dict[str, Any]]:
    url = _build_json_url(
        api_context.base_url,
        f"/r/{quote(subreddit)}/{sort_mode}.json",
        {
            "limit": limit,
            "t": time_filter if sort_mode == "top" else None,
            "raw_json": 1,
        },
    )

    try:
        payload = await asyncio.to_thread(_request_json, url, headers=api_context.headers, source_mode=api_context.source_mode)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}:
            return []
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            warnings.append(f"Reddit rate-limited listing requests for r/{subreddit}, so some results may be missing.")
            return []
        raise

    results = [child.get("data") or {} for child in payload.get("data", {}).get("children", [])]
    for post in results:
        post["_discovery_query"] = subreddit
    return results


async def _fetch_matching_posts(
    *,
    payload: RedditDiscoveryRequest,
    searched_subreddits: list[str],
    api_context: ApiContext,
    warnings: list[str],
) -> list[dict[str, Any]]:
    query_limit = min(
        MAX_QUERY_LIMIT,
        max(payload.max_results * payload.page * MAX_QUERY_MULTIPLIER, payload.max_results * 3),
    )

    if not searched_subreddits:
        return []

    search_plans = _build_search_query_plans(payload.tags)
    search_tasks: list[Any] = []

    if payload.sort_mode in {"relevance", "top", "new"} and search_plans:
        active_plans = search_plans[:2]
        for subreddit in searched_subreddits:
            for plan in active_plans:
                search_tasks.append(
                    _fetch_subreddit_search_posts(
                        subreddit=subreddit,
                        plan=plan,
                        sort_mode=payload.sort_mode,
                        time_filter=payload.time_filter,
                        limit=query_limit,
                        api_context=api_context,
                        warnings=warnings,
                    )
                )
    else:
        for subreddit in searched_subreddits:
            search_tasks.append(
                _fetch_subreddit_listing_posts(
                    subreddit=subreddit,
                    sort_mode=payload.sort_mode,
                    time_filter=payload.time_filter,
                    limit=query_limit,
                    api_context=api_context,
                    warnings=warnings,
                )
            )

    search_results = await _run_limited_searches(search_tasks)
    return [post for result in search_results for post in result]


def _thumbnail_for(post: dict[str, Any]) -> str | None:
    thumbnail = _normalize_url(post.get("thumbnail"))
    if thumbnail.startswith("http://") or thumbnail.startswith("https://"):
        return thumbnail

    preview = post.get("preview") or {}
    images = preview.get("images") or []
    if not images:
        return None

    source = images[0].get("source") or {}
    url = _normalize_url(source.get("url"))
    return url or None


def _post_source_url(post: dict[str, Any]) -> str:
    permalink = post.get("permalink") or ""
    if permalink.startswith("/"):
        return f"{PUBLIC_REDDIT_BASE_URL}{permalink}"
    return permalink or _normalize_url(post.get("url"))


def _external_media_type(url: str) -> tuple[str, str, bool]:
    normalized = _normalize_url(url).lower()
    if not normalized:
        return "link", "link", False
    base_url = normalized.split("?", 1)[0]
    if base_url.endswith(DIRECT_VIDEO_SUFFIXES):
        return "direct_video", "video", True
    if any(domain in normalized for domain in EXTERNAL_MEDIA_DOMAINS):
        return "external_video", "image", False
    return "link", "link", False


def _extract_reddit_video(post: dict[str, Any]) -> dict[str, Any]:
    secure_media = post.get("secure_media") or {}
    media = post.get("media") or {}
    return secure_media.get("reddit_video") or media.get("reddit_video") or {}


def _normalize_post(post: dict[str, Any], *, payload: RedditDiscoveryRequest) -> dict[str, Any] | None:
    if post.get("is_self"):
        return None
    if not payload.allow_nsfw and bool(post.get("over_18")):
        return None

    external_id = str(post.get("id") or "").strip()
    if not external_id:
        return None

    created_at: datetime | None = None
    created_utc = post.get("created_utc")
    if created_utc:
        try:
            created_at = datetime.fromtimestamp(float(created_utc), tz=UTC)
        except (TypeError, ValueError, OSError):
            created_at = None

    title = _normalize_text(str(post.get("title") or "Untitled Reddit clip"))
    description = _normalize_text(str(post.get("selftext") or ""))
    subreddit = _normalize_text(str(post.get("subreddit") or ""))
    permalink = _normalize_text(str(post.get("permalink") or ""))
    source_url = _post_source_url(post)
    thumbnail_url = _thumbnail_for(post)
    upvotes = _to_int(post.get("score"))
    comments = _to_int(post.get("num_comments"))
    domain = _normalize_text(str(post.get("domain") or "")) or None

    reddit_video = _extract_reddit_video(post)
    fallback_url = _normalize_url(reddit_video.get("fallback_url"))
    hls_url = _normalize_url(reddit_video.get("hls_url")) or None
    duration_seconds = _to_int(reddit_video.get("duration")) or None
    has_audio = bool(reddit_video.get("has_audio"))

    media_url = ""
    preview_url = ""
    preview_kind = "image"
    media_type = "link"
    compilation_ready = False

    if fallback_url and "v.redd.it" in fallback_url.lower() and hls_url and has_audio:
        media_url = _clip_playback_api_path(external_id)
        preview_url = media_url
        preview_kind = "video"
        media_type = "reddit_video"
        compilation_ready = True
    else:
        external_url = _normalize_url(post.get("url_overridden_by_dest") or post.get("url"))
        external_media_type, external_preview_kind, external_compilation_ready = _external_media_type(external_url)
        if payload.include_external_media and external_media_type != "link":
            media_url = external_url
            preview_url = thumbnail_url or external_url
            preview_kind = external_preview_kind
            media_type = external_media_type
            compilation_ready = external_compilation_ready

    if not media_url:
        return None
    if duration_seconds is not None and duration_seconds > MAX_CLIP_DURATION_SECONDS and media_type == "reddit_video":
        return None

    engagement = upvotes + (comments * 3)

    return {
        "external_id": external_id,
        "title": title,
        "description": description,
        "author": _normalize_text(str(post.get("author") or "")) or None,
        "subreddit": subreddit,
        "source_url": source_url,
        "permalink": f"{PUBLIC_REDDIT_BASE_URL}{permalink}" if permalink.startswith("/") else source_url,
        "media_url": media_url,
        "preview_url": preview_url or thumbnail_url or source_url,
        "preview_kind": preview_kind,
        "thumbnail_url": thumbnail_url,
        "created_at": created_at,
        "duration_seconds": duration_seconds,
        "upvotes": upvotes,
        "comments": comments,
        "engagement": engagement,
        "domain": domain,
        "media_type": media_type,
        "compilation_ready": compilation_ready,
        "metadata": {
            "source_label": f"r/{subreddit}" if subreddit else "reddit",
            "domain": domain,
            "is_video": bool(post.get("is_video")),
            "link_flair_text": post.get("link_flair_text"),
            "over_18": bool(post.get("over_18")),
            "fallback_url": fallback_url,
            "hls_url": hls_url,
            "has_audio": has_audio,
            "matched_query": post.get("_discovery_query"),
        },
    }


def _score_clip_tag_relevance(clip: dict[str, Any], tag_profile: TagProfile) -> float:
    metadata = clip.get("metadata") or {}
    title = _normalize_text(str(clip.get("title") or "")).lower()
    description = _normalize_text(str(clip.get("description") or "")).lower()
    subreddit = _normalize_text(str(clip.get("subreddit") or "")).lower()
    flair = _normalize_text(str(metadata.get("link_flair_text") or "")).lower()
    author = _normalize_text(str(clip.get("author") or "")).lower()

    title_tokens = set(_tokenize_search_text(title))
    description_tokens = set(_tokenize_search_text(description))
    subreddit_tokens = set(_tokenize_search_text(subreddit))
    flair_tokens = set(_tokenize_search_text(flair))
    author_tokens = set(_tokenize_search_text(author))

    score = 0.0
    for phrase in tag_profile.phrases:
        if phrase in title:
            score += 10
        elif phrase in flair:
            score += 8
        elif phrase in subreddit:
            score += 6
        elif phrase in description:
            score += 4

    for term in tag_profile.terms:
        if term in title_tokens:
            score += 4
        elif term in flair_tokens or term in subreddit_tokens:
            score += 3
        elif term in description_tokens or term in author_tokens:
            score += 1

    return score


def _resolve_ranking_weights(weights: RankingWeights | None) -> RankingWeights:
    if weights is None:
        return RankingWeights()
    total = weights.relevance + weights.upvotes + weights.comments + weights.recency
    if total <= 0:
        return RankingWeights()
    return RankingWeights(
        relevance=weights.relevance / total,
        upvotes=weights.upvotes / total,
        comments=weights.comments / total,
        recency=weights.recency / total,
    )


def _recency_window_seconds(time_filter: str) -> int:
    if time_filter == "day":
        return 24 * 3600
    if time_filter == "week":
        return 7 * 24 * 3600
    if time_filter == "month":
        return 30 * 24 * 3600
    if time_filter == "year":
        return 365 * 24 * 3600
    return 730 * 24 * 3600


def _recency_score(created_at: datetime | None, *, time_filter: str) -> float:
    if created_at is None:
        return 0.0
    age_seconds = max(0.0, (_utc_now() - created_at).total_seconds())
    window = float(_recency_window_seconds(time_filter))
    return math.exp(-(age_seconds / max(window, 1.0)))


def _title_signature(title: str) -> str:
    terms = [term for term in _tokenize_search_text(title) if term not in TAG_STOPWORDS]
    return " ".join(terms[:8])


def _normalized_metric(value: int, max_value: int) -> float:
    if value <= 0 or max_value <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(max_value)


def _rank_and_dedupe_posts(
    posts: list[dict[str, Any]],
    *,
    payload: RedditDiscoveryRequest,
    tag_profile: TagProfile,
) -> tuple[list[dict[str, Any]], int]:
    normalized_clips: list[dict[str, Any]] = []

    for post in posts:
        clip = _normalize_post(post, payload=payload)
        if clip is None:
            continue
        clip["relevance_raw"] = _score_clip_tag_relevance(clip, tag_profile)
        if clip["relevance_raw"] <= 0:
            continue
        normalized_clips.append(clip)

    if not normalized_clips:
        return [], len(posts)

    max_relevance = max(clip["relevance_raw"] for clip in normalized_clips) or 1.0
    max_upvotes = max(_to_int(clip["upvotes"]) for clip in normalized_clips) or 1
    max_comments = max(_to_int(clip["comments"]) for clip in normalized_clips) or 1
    weights = _resolve_ranking_weights(payload.ranking_weights)

    for clip in normalized_clips:
        clip["relevance_score"] = clip["relevance_raw"] / max_relevance
        clip["upvotes_score"] = _normalized_metric(_to_int(clip["upvotes"]), max_upvotes)
        clip["comments_score"] = _normalized_metric(_to_int(clip["comments"]), max_comments)
        clip["recency_score"] = _recency_score(clip.get("created_at"), time_filter=payload.time_filter)
        clip["final_score"] = (
            weights.relevance * clip["relevance_score"]
            + weights.upvotes * clip["upvotes_score"]
            + weights.comments * clip["comments_score"]
            + weights.recency * clip["recency_score"]
        )

    normalized_clips.sort(
        key=lambda item: (
            -item["final_score"],
            -item["comments"],
            -item["upvotes"],
            item["title"].lower(),
        )
    )

    unique_posts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_media: set[str] = set()
    seen_titles: set[str] = set()

    for clip in normalized_clips:
        external_id = clip["external_id"].lower()
        media_key = clip["media_url"].split("?", 1)[0].lower()
        title_key = _title_signature(clip["title"])
        if external_id in seen_ids or media_key in seen_media or (title_key and title_key in seen_titles):
            continue
        seen_ids.add(external_id)
        seen_media.add(media_key)
        if title_key:
            seen_titles.add(title_key)
        unique_posts.append(clip)

    return unique_posts, max(0, len(posts) - len(unique_posts))


def _filter_used_clips(clips: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    with USED_CLIPS_LOCK:
        used_lookup = set(_read_used_clips_unlocked())

    available: list[dict[str, Any]] = []
    filtered_count = 0

    for clip in clips:
        external_id = clip["external_id"].strip().lower()
        if external_id in used_lookup:
            filtered_count += 1
            continue
        available.append(clip)

    return available, filtered_count


def _clip_read(clip: dict[str, Any], *, rank_position: int) -> RedditClipRead:
    metadata = clip.get("metadata") or {}
    source_label = metadata.get("source_label") or (f"r/{clip['subreddit']}" if clip.get("subreddit") else "reddit")
    selection_reason = (
        f"Ranked for strong tag relevance plus Reddit traction: {clip['upvotes']} upvotes, "
        f"{clip['comments']} comments, score {clip['final_score']:.3f}."
    )
    return RedditClipRead(
        external_id=clip["external_id"],
        title=clip["title"],
        source=source_label,
        subreddit=clip["subreddit"],
        source_url=clip["source_url"],
        permalink=clip["permalink"],
        video_url=clip["media_url"],
        preview_url=clip["preview_url"],
        thumbnail_url=clip["thumbnail_url"],
        preview_kind=clip["preview_kind"],
        media_type=clip["media_type"],
        domain=clip["domain"],
        upvotes=clip["upvotes"],
        comments=clip["comments"],
        engagement=clip["engagement"],
        duration_seconds=clip["duration_seconds"],
        created_at=clip["created_at"].isoformat() if clip.get("created_at") else None,
        final_score=round(float(clip["final_score"]), 6),
        relevance_score=round(float(clip["relevance_score"]), 6),
        rank_position=rank_position,
        compilation_ready=bool(clip["compilation_ready"]),
        selection_reason=selection_reason,
    )


def _ensure_playable_clip_file(external_id: str) -> Path:
    normalized_id = external_id.strip().lower()
    if not normalized_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")

    output_path = _clip_playback_file_path(normalized_id)
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    clip_source = _get_clip_source(normalized_id)
    if not clip_source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip source details expired. Discover clips again to refresh playback.",
        )

    hls_url = _normalize_url(str(clip_source.get("hls_url") or ""))
    if not hls_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No playable audio stream is available for this clip.",
        )

    with PLAYBACK_CACHE_LOCK:
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        PLAYBACK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp_output_path = output_path.with_suffix(".tmp.mp4")

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-user_agent",
                    DEFAULT_USER_AGENT,
                    "-i",
                    hls_url,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-movflags",
                    "+faststart",
                    str(temp_output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=PLAYBACK_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ffmpeg is required to prepare Reddit clip playback.",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timed out while preparing the Reddit clip playback.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=stderr or "Unable to prepare the Reddit clip playback.",
            ) from exc

        temp_output_path.replace(output_path)

    return output_path


def get_reddit_clip_playback_response(external_id: str) -> FileResponse:
    output_path = _ensure_playable_clip_file(external_id)
    return FileResponse(output_path, media_type="video/mp4", filename=output_path.name)


async def discover_safe_reddit_clips(payload: RedditDiscoveryRequest) -> RedditDiscoveryResponse:
    tag_profile = _build_tag_profile(payload.tags)
    if not tag_profile.terms and not tag_profile.phrases:
        return RedditDiscoveryResponse(
            items=[],
            total_safe=0,
            total_results=0,
            checked_count=0,
            rejected_count=0,
            cached_count=0,
            searched_subreddits=[],
            page=payload.page,
            page_size=payload.max_results,
            has_more=False,
            next_page=None,
            sort_mode=payload.sort_mode,
            time_filter=payload.time_filter,
            source_mode="public",
            warnings=["No searchable tag terms were found in the request."],
        )

    api_context, warnings = _build_api_context()

    searched_subreddits = payload.subreddits or await _discover_related_subreddits(
        tags=payload.tags,
        allow_nsfw=payload.allow_nsfw,
        api_context=api_context,
        warnings=warnings,
    )

    raw_posts = await _fetch_matching_posts(
        payload=payload,
        searched_subreddits=searched_subreddits,
        api_context=api_context,
        warnings=warnings,
    )
    ranked_posts, deduped_out = _rank_and_dedupe_posts(raw_posts, payload=payload, tag_profile=tag_profile)
    available_posts, used_filtered = _filter_used_clips(ranked_posts)

    total_results = len(available_posts)
    start_index = (payload.page - 1) * payload.max_results
    end_index = start_index + payload.max_results
    page_posts = available_posts[start_index:end_index]
    has_more = end_index < total_results
    next_page = payload.page + 1 if has_more else None

    _store_clip_sources(page_posts)

    items = [
        _clip_read(clip, rank_position=start_index + index + 1)
        for index, clip in enumerate(page_posts)
    ]

    if not searched_subreddits:
        warnings.append("No relevant subreddits were discovered for the provided tags.")
    elif not items and total_results == 0:
        warnings.append("No media-rich Reddit posts matched the provided tags and filters.")

    return RedditDiscoveryResponse(
        items=items,
        total_safe=len(items),
        total_results=total_results,
        checked_count=len(raw_posts),
        rejected_count=deduped_out + used_filtered,
        cached_count=0,
        searched_subreddits=searched_subreddits,
        page=payload.page,
        page_size=payload.max_results,
        has_more=has_more,
        next_page=next_page,
        sort_mode=payload.sort_mode,
        time_filter=payload.time_filter,
        source_mode=api_context.source_mode,
        warnings=_unique_terms(warnings),
    )
