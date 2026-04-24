from __future__ import annotations

import math
import re
import subprocess
import sys
from array import array
from datetime import datetime, timezone
from statistics import median
from typing import Any


SCAN_METHOD = "audio_heuristic_v2"
COPYRIGHT_ENGINE_VERSION = "youtube_match_policy_v2"
SAMPLE_RATE = 16000
FRAME_SIZE = 2048
HOP_SIZE = 1024
MAX_ANALYSIS_SECONDS = 25
MATCH_BASELINE_RISK = 0.35

THIRD_PARTY_SOURCE_KEYWORDS = {
    "adult swim",
    "anime",
    "cartoon network",
    "concert",
    "crunchyroll",
    "disney",
    "disney+",
    "dreamworks",
    "episode",
    "espn",
    "film",
    "fox",
    "hbo",
    "hulu",
    "live performance",
    "lyrics",
    "marvel",
    "movie",
    "music video",
    "nba",
    "netflix",
    "nfl",
    "nickelodeon",
    "official video",
    "paramount",
    "peacock",
    "pixar",
    "prime video",
    "scene",
    "series",
    "show",
    "sitcom",
    "sony pictures",
    "soundtrack",
    "sports broadcast",
    "trailer",
    "tv",
    "vevo",
    "warner bros",
    "wwe",
}

WATERMARK_KEYWORDS = {
    "instagram",
    "reel",
    "shorts",
    "snapchat",
    "tiktok",
    "watermark",
    "youtube",
    "youtu.be",
}

REUPLOAD_KEYWORDS = {
    "borrowed from",
    "credit:",
    "credits:",
    "found on",
    "from instagram",
    "from tiktok",
    "not mine",
    "re-upload",
    "reupload",
    "repost",
    "stolen",
    "via @",
}

RISKY_SOURCE_CONTEXT_KEYWORDS = {
    "anime",
    "cartoon",
    "celeb",
    "film",
    "movie",
    "music",
    "netflix",
    "show",
    "sitcom",
    "television",
    "tv",
}

CLEAR_LICENSE_KEYWORDS = {
    "all rights owned",
    "authorized",
    "creative commons",
    "creator consent",
    "licensed",
    "permission granted",
    "public domain",
    "rights cleared",
    "royalty free",
    "used with permission",
}

PENDING_PERMISSION_KEYWORDS = {
    "manual permission required",
    "needs permission",
    "pending permission",
    "permission required",
    "rights unconfirmed",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _zero_crossing_ratio(frame: array) -> float:
    if len(frame) < 2:
        return 0.0

    zero_crossings = 0
    previous_sign = frame[0] >= 0
    for sample in frame[1:]:
        current_sign = sample >= 0
        if current_sign != previous_sign:
            zero_crossings += 1
        if sample != 0:
            previous_sign = current_sign
    return zero_crossings / (len(frame) - 1)


def _frame_features(samples: array) -> tuple[list[float], list[float]]:
    rms_values: list[float] = []
    zcr_values: list[float] = []

    if not samples:
        return rms_values, zcr_values

    if len(samples) < FRAME_SIZE:
        padded = array("h", samples)
        padded.extend([0] * (FRAME_SIZE - len(samples)))
        frames = [padded]
    else:
        frame_count = 1 + (len(samples) - FRAME_SIZE) // HOP_SIZE
        frames = [samples[index * HOP_SIZE : index * HOP_SIZE + FRAME_SIZE] for index in range(frame_count)]

    for frame in frames:
        energy = sum(sample * sample for sample in frame) / len(frame)
        rms_values.append(math.sqrt(energy) / 32768.0)
        zcr_values.append(_zero_crossing_ratio(frame))

    return rms_values, zcr_values


def _resample_series(values: list[float], target_size: int = 16) -> list[float]:
    if not values:
        return []

    if len(values) <= target_size:
        return values[:]

    output: list[float] = []
    total = len(values)
    for index in range(target_size):
        start = round(index * total / target_size)
        end = round((index + 1) * total / target_size)
        if end <= start:
            end = start + 1
        chunk = values[start:end]
        output.append(sum(chunk) / len(chunk))

    return output


def _quantize_signature(values: list[float], *, ceiling: float) -> str:
    if not values:
        return ""

    normalized_ceiling = max(ceiling, 1e-6)
    bins = [
        str(min(9, max(0, int(round(min(value / normalized_ceiling, 1.0) * 9)))))
        for value in values
    ]
    return "".join(bins)


def _build_audio_fingerprint(rms_values: list[float], zcr_values: list[float]) -> dict[str, Any]:
    if not rms_values:
        return {}

    sampled_rms = _resample_series(rms_values)
    sampled_zcr = _resample_series(zcr_values)
    return {
        "frame_count": len(rms_values),
        "energy_signature": _quantize_signature(sampled_rms, ceiling=max(sampled_rms) if sampled_rms else 1.0),
        "zcr_signature": _quantize_signature(sampled_zcr, ceiling=0.3),
    }


def _classify_audio(samples: array, sample_rate: int) -> dict[str, Any]:
    if not samples:
        return {
            "status": "no_audio",
            "confidence": 1.0,
            "has_audio": False,
            "music_score": 0.0,
            "speech_score": 0.0,
            "features": {},
            "fingerprint": {},
            "method": SCAN_METHOD,
            "sample_rate": sample_rate,
            "analyzed_at": _utc_now_iso(),
        }

    rms_values, zcr_values = _frame_features(samples)
    if not rms_values:
        return {
            "status": "no_audio",
            "confidence": 1.0,
            "has_audio": False,
            "music_score": 0.0,
            "speech_score": 0.0,
            "features": {},
            "fingerprint": {},
            "method": SCAN_METHOD,
            "sample_rate": sample_rate,
            "analyzed_at": _utc_now_iso(),
        }

    rms_max = max(rms_values)
    fingerprint = _build_audio_fingerprint(rms_values, zcr_values)
    if rms_max < 0.002:
        return {
            "status": "no_audio",
            "confidence": 0.99,
            "has_audio": False,
            "music_score": 0.0,
            "speech_score": 0.0,
            "features": {
                "rms_max": round(rms_max, 4),
            },
            "fingerprint": fingerprint,
            "method": SCAN_METHOD,
            "sample_rate": sample_rate,
            "analyzed_at": _utc_now_iso(),
        }

    normalized_rms = [value / max(rms_max, 1e-6) for value in rms_values]
    silence_ratio = sum(value < 0.08 for value in normalized_rms) / len(normalized_rms)
    active_ratio = sum(value >= 0.08 for value in normalized_rms) / len(normalized_rms)

    rms_mean = sum(rms_values) / len(rms_values)
    variance = sum((value - rms_mean) ** 2 for value in rms_values) / len(rms_values)
    energy_cv = math.sqrt(variance) / max(rms_mean, 1e-9)

    energy_delta_mean = 0.0
    if len(normalized_rms) > 1:
        deltas = [
            abs(normalized_rms[index] - normalized_rms[index - 1])
            for index in range(1, len(normalized_rms))
        ]
        energy_delta_mean = sum(deltas) / len(deltas)

    zcr_median = median(zcr_values) if zcr_values else 0.0

    music_score = 0.0
    speech_score = 0.0

    if silence_ratio < 0.12:
        music_score += 0.28
    elif silence_ratio < 0.22:
        music_score += 0.12
    else:
        speech_score += 0.22

    if active_ratio > 0.82:
        music_score += 0.18
    elif active_ratio < 0.55:
        speech_score += 0.18

    if energy_cv < 0.72:
        music_score += 0.22
    elif energy_cv > 1.05:
        speech_score += 0.22
    else:
        music_score += 0.06
        speech_score += 0.06

    if 0.045 <= zcr_median <= 0.18:
        music_score += 0.12
    elif zcr_median < 0.03:
        speech_score += 0.10
    elif zcr_median > 0.23:
        speech_score += 0.08

    if energy_delta_mean < 0.11:
        music_score += 0.12
    elif energy_delta_mean > 0.24:
        speech_score += 0.12

    score_gap = music_score - speech_score
    if music_score >= 0.68 and score_gap >= 0.14:
        status = "unsafe"
    elif music_score >= 0.42:
        status = "needs_review"
    else:
        status = "safe"

    confidence = min(0.99, max(0.35, 0.5 + abs(score_gap) * 0.8))
    return {
        "status": status,
        "confidence": round(float(confidence), 3),
        "has_audio": True,
        "music_score": round(float(music_score), 3),
        "speech_score": round(float(speech_score), 3),
        "features": {
            "silence_ratio": round(float(silence_ratio), 3),
            "active_ratio": round(float(active_ratio), 3),
            "energy_cv": round(float(energy_cv), 3),
            "energy_delta_mean": round(float(energy_delta_mean), 3),
            "zcr_median": round(float(zcr_median), 3),
            "rms_max": round(float(rms_max), 4),
        },
        "fingerprint": fingerprint,
        "method": SCAN_METHOD,
        "sample_rate": sample_rate,
        "analyzed_at": _utc_now_iso(),
    }


def _ffprobe_has_audio(source: str) -> bool:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                source,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is required for copyright scanning.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out while probing clip audio.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(stderr or "ffprobe could not inspect the clip.") from exc

    return bool(result.stdout.strip())


def _extract_audio_samples(source: str, sample_rate: int = SAMPLE_RATE) -> tuple[array, int]:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-t",
                str(MAX_ANALYSIS_SECONDS),
                "-i",
                source,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
            timeout=45,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required for copyright scanning.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out while reading clip audio.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="ignore").strip()
        raise RuntimeError(stderr or "ffmpeg could not decode the clip audio.") from exc

    samples = array("h")
    if result.stdout:
        samples.frombytes(result.stdout)
        if sys.byteorder != "little":
            samples.byteswap()
    return samples, sample_rate


def scan_media_for_music(source: str) -> dict[str, Any]:
    if not _ffprobe_has_audio(source):
        return {
            "status": "no_audio",
            "confidence": 1.0,
            "has_audio": False,
            "music_score": 0.0,
            "speech_score": 0.0,
            "features": {},
            "fingerprint": {},
            "method": SCAN_METHOD,
            "sample_rate": SAMPLE_RATE,
            "source_ref": source,
            "analyzed_at": _utc_now_iso(),
        }

    samples, sample_rate = _extract_audio_samples(source, SAMPLE_RATE)
    detection = _classify_audio(samples, sample_rate)
    detection["source_ref"] = source
    return detection


def _find_keyword(text: str, keywords: set[str]) -> str | None:
    lowered = text.lower()
    for keyword in sorted(keywords, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")
        if pattern.search(lowered):
            return keyword
    return None


def _compact_text(*parts: Any) -> str:
    cleaned: list[str] = []
    for part in parts:
        if part is None:
            continue
        value = str(part).strip()
        if value:
            cleaned.append(value)
    return " ".join(cleaned)


def _signal(code: str, severity: str, weight: float, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "weight": round(weight, 3),
        "message": message,
    }


def _effective_music_status(metadata: dict[str, Any], detection: dict[str, Any] | None) -> str:
    review = metadata.get("music_review") or {}
    reviewed_status = review.get("status")
    if reviewed_status:
        return reviewed_status

    if detection:
        detected_status = detection.get("status")
        if detected_status:
            return detected_status

    legacy_risk = review.get("risk")
    if legacy_risk == "low":
        return "safe"
    if legacy_risk == "medium":
        return "needs_review"
    if legacy_risk == "high":
        return "unsafe"

    return "unknown"


def _compose_summary(status: str, signals: list[dict[str, Any]]) -> str:
    risk_messages = [signal["message"] for signal in signals if signal["severity"] in {"danger", "warning"}]
    safe_messages = [signal["message"] for signal in signals if signal["severity"] == "safe"]

    if status == "failed":
        lead = "High-risk copyright profile."
        details = risk_messages[:2] or ["The clip contains multiple reupload or provenance risk indicators."]
        return f"{lead} {' '.join(details)}"

    if status == "needs_review":
        lead = "Manual copyright review recommended."
        details = (risk_messages[:2] + safe_messages[:1])[:3]
        if not details:
            details = ["The clip could not be cleared confidently from metadata and audio signals alone."]
        return f"{lead} {' '.join(details)}"

    lead = "Low-risk copyright profile."
    details = safe_messages[:2]
    if not details:
        details = ["No strong repost, watermark, or third-party source indicators were found."]
    return f"{lead} {' '.join(details)}"


def _confidence_for(status: str, risk_score: float, severe_signal_count: int) -> float:
    if status == "failed":
        base = 0.72 + min(0.18, (risk_score - 0.25) * 0.35)
        if severe_signal_count:
            base += 0.08
        return round(min(0.97, max(0.55, base)), 3)

    if status == "passed":
        base = 0.62 + min(0.24, (0.25 - risk_score) * 0.8)
        return round(min(0.93, max(0.45, base)), 3)

    distance = abs(risk_score - 0.45)
    base = 0.68 - min(0.16, distance * 0.3)
    return round(min(0.82, max(0.45, base)), 3)


def assess_copyright_risk(
    *,
    source_type: str | None,
    title: str | None,
    description: str | None,
    author: str | None,
    source_url: str | None,
    media_url: str | None,
    local_media_path: str | None,
    duration_seconds: int | None,
    rights_status: str | None,
    rights_notes: str | None,
    license_hint: str | None,
    metadata: dict[str, Any] | None,
    detection: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = metadata or {}
    detection = detection or {}
    source_label = metadata.get("source_label") or metadata.get("subreddit") or source_type or "unknown"
    searchable_text = _compact_text(
        title,
        description,
        author,
        source_url,
        media_url,
        source_label,
        metadata.get("domain"),
        metadata.get("source_context"),
        license_hint,
        rights_notes,
    )
    license_text = _compact_text(license_hint, rights_notes)
    source_text = _compact_text(source_label, metadata.get("subreddit"), metadata.get("source_context"))
    signals: list[dict[str, Any]] = []
    risk_score = MATCH_BASELINE_RISK
    severe_signals = 0

    native_reddit = (
        (source_type or "").lower() == "reddit"
        and "v.redd.it" in _compact_text(media_url, metadata.get("url"), metadata.get("dash_url")).lower()
    )
    if native_reddit:
        signals.append(
            _signal(
                "native_upload",
                "safe",
                -0.18,
                "The clip looks like a native Reddit upload rather than an external embed.",
            )
        )
        risk_score -= 0.18
    elif (source_type or "").lower() == "reddit":
        signals.append(
            _signal(
                "external_host",
                "danger",
                0.42,
                "The Reddit post points to a non-native video host, which makes provenance harder to verify.",
            )
        )
        risk_score += 0.42
        severe_signals += 1

    if metadata.get("is_original_content") is True:
        signals.append(
            _signal(
                "original_content_flag",
                "safe",
                -0.16,
                "The source metadata marks the clip as original content.",
            )
        )
        risk_score -= 0.16

    if local_media_path:
        signals.append(
            _signal(
                "local_media",
                "safe",
                -0.08,
                "A local media file is available, which is useful for consistent review and verification.",
            )
        )
        risk_score -= 0.08

    if author and author.strip() and author.strip().lower() != "[deleted]":
        signals.append(
            _signal(
                "named_uploader",
                "safe",
                -0.04,
                "The clip has a named uploader, which is a better provenance signal than an anonymous repost.",
            )
        )
        risk_score -= 0.04
    else:
        signals.append(
            _signal(
                "missing_uploader",
                "warning",
                0.05,
                "The uploader identity is missing or deleted, so provenance is weaker.",
            )
        )
        risk_score += 0.05

    if metadata.get("crosspost_parent") or metadata.get("crosspost_parent_list"):
        signals.append(
            _signal(
                "crosspost",
                "danger",
                0.34,
                "Crosspost metadata is present, which is a common reupload or repost signal.",
            )
        )
        risk_score += 0.34
        severe_signals += 1

    matched_keyword = _find_keyword(searchable_text, REUPLOAD_KEYWORDS)
    if matched_keyword:
        signals.append(
            _signal(
                "reupload_language",
                "danger",
                0.34,
                f'Reupload wording was detected in the clip metadata: "{matched_keyword}".',
            )
        )
        risk_score += 0.34
        severe_signals += 1

    matched_keyword = _find_keyword(searchable_text, WATERMARK_KEYWORDS)
    if matched_keyword:
        signals.append(
            _signal(
                "watermark_language",
                "danger",
                0.34,
                f'Watermark or third-party platform wording was detected: "{matched_keyword}".',
            )
        )
        risk_score += 0.34
        severe_signals += 1

    matched_keyword = _find_keyword(searchable_text, THIRD_PARTY_SOURCE_KEYWORDS)
    if matched_keyword:
        signals.append(
            _signal(
                "third_party_source",
                "warning",
                0.28,
                f'The metadata references a likely copyrighted source category: "{matched_keyword}".',
            )
        )
        risk_score += 0.28

    matched_keyword = _find_keyword(source_text.lower(), RISKY_SOURCE_CONTEXT_KEYWORDS)
    if matched_keyword:
        signals.append(
            _signal(
                "risky_context",
                "warning",
                0.15,
                f'The source context suggests curated copyrighted media rather than original UGC: "{matched_keyword}".',
            )
        )
        risk_score += 0.15

    explicit_clearance = False
    matched_keyword = _find_keyword(license_text.lower(), CLEAR_LICENSE_KEYWORDS)
    if matched_keyword:
        explicit_clearance = True
        signals.append(
            _signal(
                "clearance_hint",
                "safe",
                -0.24,
                f'Rights notes include a positive clearance signal: "{matched_keyword}".',
            )
        )
        risk_score -= 0.24

    matched_keyword = _find_keyword(license_text.lower(), PENDING_PERMISSION_KEYWORDS)
    if matched_keyword:
        signals.append(
            _signal(
                "pending_permission",
                "warning",
                0.12,
                f'Rights notes still indicate unresolved permission work: "{matched_keyword}".',
            )
        )
        risk_score += 0.12

    if duration_seconds is not None:
        if duration_seconds > 180:
            signals.append(
                _signal(
                    "long_duration",
                    "warning",
                    0.16,
                    "Longer clips are more likely to be near-full reuploads than short excerpts.",
                )
            )
            risk_score += 0.16
        elif duration_seconds > 45:
            signals.append(
                _signal(
                    "extended_duration",
                    "warning",
                    0.08,
                    "This clip is longer than the short-form range the workflow is optimized for.",
                )
            )
            risk_score += 0.08

    effective_music_status = _effective_music_status(metadata, detection)
    if effective_music_status == "safe":
        signals.append(
            _signal(
                "audio_safe",
                "safe",
                -0.06,
                "Audio features look closer to speech or ambient sound than a likely music bed.",
            )
        )
        risk_score -= 0.06
    elif effective_music_status == "no_audio":
        signals.append(
            _signal(
                "audio_missing",
                "safe",
                -0.02,
                "No usable audio was detected, so soundtrack matching risk is lower.",
            )
        )
        risk_score -= 0.02
    elif effective_music_status == "unsafe":
        signals.append(
            _signal(
                "audio_music_risk",
                "warning",
                0.22,
                "Audio features suggest a music-heavy track, which commonly needs manual rights confirmation.",
            )
        )
        risk_score += 0.22
    elif effective_music_status == "needs_review":
        signals.append(
            _signal(
                "audio_uncertain",
                "warning",
                0.12,
                "Audio analysis could not confidently clear the soundtrack.",
            )
        )
        risk_score += 0.12
    elif effective_music_status == "scan_failed":
        signals.append(
            _signal(
                "audio_scan_failed",
                "warning",
                0.18,
                "Audio analysis failed, so the clip cannot be cleared automatically.",
            )
        )
        risk_score += 0.18
    else:
        signals.append(
            _signal(
                "audio_unknown",
                "warning",
                0.08,
                "No current audio review is available for this clip.",
            )
        )
        risk_score += 0.08

    risk_score = max(0.0, min(1.0, risk_score))
    if severe_signals and not explicit_clearance:
        status = "failed"
    elif risk_score >= 0.65:
        status = "failed"
    elif risk_score >= 0.25:
        status = "needs_review"
    else:
        status = "passed"

    if severe_signals and explicit_clearance and status == "passed":
        status = "needs_review"

    summary = _compose_summary(status, signals)
    confidence = _confidence_for(status, risk_score, severe_signals)

    return {
        "status": status,
        "confidence": confidence,
        "risk_score": round(risk_score, 3),
        "summary": summary,
        "review_recommendation": {
            "passed": "low_risk_match_profile",
            "needs_review": "manual_rights_review",
            "failed": "reject_or_request_permission",
        }[status],
        "music_status": effective_music_status,
        "audio_detection_status": detection.get("status") or "unknown",
        "audio_detection_confidence": detection.get("confidence"),
        "signals": signals,
        "policy_basis": {
            "engine_version": COPYRIGHT_ENGINE_VERSION,
            "mode": "full_or_near_full_reupload_screening",
            "reference_model": "Inspired by YouTube's Copyright Match Tool guidance: surface likely matches and escalate ambiguous cases to human review.",
            "ownership_limit": "Automation cannot determine ownership, permission, fair use, or public-domain status on its own.",
        },
        "source_ref": detection.get("source_ref") or local_media_path or media_url,
        "rights_status_at_analysis": rights_status,
        "analyzed_at": _utc_now_iso(),
    }

def assess_clip_copyright(clip: dict[str, Any], detection: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = clip.get("metadata") or {}
    return assess_copyright_risk(
        source_type=clip.get("source_type") or "reddit",
        title=clip.get("title"),
        description=clip.get("description"),
        author=clip.get("author"),
        source_url=clip.get("source_url"),
        media_url=clip.get("media_url") or clip.get("analysis_media_url"),
        local_media_path=clip.get("local_media_path"),
        duration_seconds=clip.get("duration_seconds"),
        rights_status=clip.get("rights_status"),
        rights_notes=clip.get("rights_notes"),
        license_hint=clip.get("license_hint"),
        metadata=metadata,
        detection=detection,
    )
