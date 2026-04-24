from __future__ import annotations

import re
import subprocess
import tempfile
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, status

from config import COMPILED_ASSETS_DIR, DEFAULT_OUTRO_PATH
from schemas import CompilationRenderRequest, CompilationRenderResponse


TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 30
MAX_CLIP_DURATION = 24
FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
OUTRO_PATH = DEFAULT_OUTRO_PATH
TITLE_WRAP_WIDTH = 24
TITLE_MAX_LINES = 2


def _timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "compilation"


def _run_command(command: list[str], error_message: str) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ffmpeg is required to render compilation videos.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=error_message,
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=stderr or error_message,
        ) from exc


def _clip_duration(clip_duration: int | None) -> int:
    if clip_duration is None:
        return MAX_CLIP_DURATION
    return min(MAX_CLIP_DURATION, max(1, clip_duration))


def _probe_duration_seconds(source: Path) -> int:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ffprobe is required to render compilation videos.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timed out while probing the outro clip.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=stderr or "Unable to inspect the outro clip.",
        ) from exc

    try:
        return max(1, int(round(float((result.stdout or "0").strip()))))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Outro clip duration could not be parsed.",
        ) from exc


def _escape_drawtext_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")
    return escaped


def _layout_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    title = cleaned or "Reddit clip"
    wrapped = textwrap.wrap(
        title,
        width=TITLE_WRAP_WIDTH,
        break_long_words=False,
        break_on_hyphens=False,
    )
    lines = wrapped[:TITLE_MAX_LINES] or [title]
    if len(wrapped) > TITLE_MAX_LINES:
        lines[-1] = f"{lines[-1].rstrip('.')}..."
    return "\n".join(lines)


def _filter_for_clip(rank: int, title_file: Path, clip_duration: int) -> str:
    font = str(FONT_PATH).replace("\\", "\\\\").replace(":", r"\:")
    title_path = str(title_file).replace("\\", "\\\\").replace(":", r"\:")
    rank_label = _escape_drawtext_text(f"#{rank}")

    return (
        f"[0:v]fps={TARGET_FPS},scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1,"
        f"drawbox=x=0:y=0:w={TARGET_WIDTH}:h=240:color=black@0.24:t=fill,"
        f"drawbox=x=36:y=70:w=120:h=78:color=black@0.38:t=fill,"
        f"drawbox=x=36:y=70:w=120:h=78:color=white@0.18:t=3,"
        f"drawtext=fontfile='{font}':text='{rank_label}':x=(96-text_w/2):y=89:"
        f"fontsize=46:fontcolor=white:borderw=2:bordercolor=black@0.55:"
        f"shadowx=2:shadowy=2:shadowcolor=black@0.45,"
        f"drawtext=fontfile='{font}':textfile='{title_path}':reload=0:x=(w-text_w)/2:y=112:"
        f"fontsize=54:line_spacing=12:fontcolor=white:borderw=2:bordercolor=black@0.55:"
        f"shadowx=2:shadowy=2:shadowcolor=black@0.40,"
        f"setsar=1,format=yuv420p[vout]"
    )


def _outro_filter(outro_duration: int) -> str:
    return (
        f"color=c=black:s={TARGET_WIDTH}x{TARGET_HEIGHT}:r={TARGET_FPS}:d={outro_duration}[base];"
        f"[0:v]fps={TARGET_FPS},scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[clip];"
        f"[base][clip]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[vout]"
    )


def render_compilation(payload: CompilationRenderRequest) -> CompilationRenderResponse:
    if not OUTRO_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Outro clip not found at {OUTRO_PATH}.",
        )

    ordered_clips = sorted(payload.selected_clips, key=lambda clip: clip.rank, reverse=True)
    title = payload.title or "Top 5 Reddit compilation"
    output_slug = _slugify(title)
    timestamp = _timestamp_slug()
    output_name = f"{output_slug}-{timestamp}.mp4"
    output_path = COMPILED_ASSETS_DIR / output_name

    with tempfile.TemporaryDirectory(prefix="compilation-build-", dir=str(COMPILED_ASSETS_DIR)) as build_dir_raw:
        build_dir = Path(build_dir_raw)
        processed_paths: list[Path] = []
        total_duration_seconds = 0

        for index, clip in enumerate(ordered_clips, start=1):
            clip_duration = _clip_duration(clip.duration_seconds)
            total_duration_seconds += clip_duration

            title_file = build_dir / f"title_{index:02d}.txt"
            title_file.write_text(_layout_title(clip.title), encoding="utf-8")

            processed_path = build_dir / f"clip_{index:02d}.mp4"
            processed_paths.append(processed_path)

            command = [
                "ffmpeg",
                "-y",
                "-i",
                clip.url,
                "-t",
                str(clip_duration),
                "-filter_complex",
                _filter_for_clip(clip.rank, title_file, clip_duration),
                "-map",
                "[vout]",
                "-map",
                "0:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-b:a",
                "192k",
                str(processed_path),
            ]
            _run_command(command, f"Timed out while rendering clip {clip.rank}.")

        outro_duration = _probe_duration_seconds(OUTRO_PATH)
        total_duration_seconds += outro_duration
        outro_path = build_dir / "clip_99_outro.mp4"
        processed_paths.append(outro_path)

        outro_command = [
            "ffmpeg",
            "-y",
            "-i",
            str(OUTRO_PATH),
            "-filter_complex",
            _outro_filter(outro_duration),
            "-map",
            "[vout]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            str(outro_path),
        ]
        _run_command(outro_command, "Timed out while rendering the outro clip.")

        concat_file = build_dir / "concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in processed_paths),
            encoding="utf-8",
        )

        concat_command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        _run_command(concat_command, "Timed out while combining the compilation video.")

    return CompilationRenderResponse(
        title=title,
        output_url=f"/media/compiled/{output_name}",
        output_path=str(output_path),
        clip_count=len(ordered_clips),
        total_duration_seconds=total_duration_seconds,
    )
