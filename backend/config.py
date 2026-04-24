from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = ROOT_DIR / "data"
STATE_DIR = DATA_DIR / "state"
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_EXTRAS_DIR = EXPORT_DIR / "Extras"
APPROVED_ASSETS_DIR = DATA_DIR / "assets" / "approved"
COMPILED_ASSETS_DIR = DATA_DIR / "assets" / "compiled"
REDDIT_TOPIC_MARKERS_PATH = DATA_DIR / "reddit_topic_markers.json"
DEFAULT_OUTRO_PATH = EXPORT_EXTRAS_DIR / "Outro.mp4"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key or normalized_key in os.environ:
            continue

        normalized_value = value.strip()
        if len(normalized_value) >= 2 and normalized_value[0] == normalized_value[-1] and normalized_value[0] in {'"', "'"}:
            normalized_value = normalized_value[1:-1]

        os.environ[normalized_key] = normalized_value


def load_local_env() -> None:
    _load_env_file(ROOT_DIR / ".env")
    _load_env_file(BACKEND_DIR / ".env")


def _build_database_url() -> str:
    default_path = STATE_DIR / "clipping_automation.db"
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    return f"sqlite:///{default_path}"


@dataclass(slots=True)
class Settings:
    app_name: str = "Clipping Automation API"
    app_version: str = "2.0.0"
    api_prefix: str = "/api"
    database_url: str = field(default_factory=_build_database_url)
    reddit_client_id: str | None = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID") or None)
    reddit_client_secret: str | None = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET") or None)
    reddit_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "REDDIT_USER_AGENT",
            "ClippingAutomation/2.0 (reddit clip discovery)",
        )
    )
    frontend_origins: list[str] = field(
        default_factory=lambda: [
            origin.strip()
            for origin in os.getenv(
                "FRONTEND_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            ).split(",")
            if origin.strip()
        ]
    )


load_local_env()
settings = Settings()


def ensure_directories() -> None:
    for path in (DATA_DIR, STATE_DIR, EXPORT_DIR, EXPORT_EXTRAS_DIR, APPROVED_ASSETS_DIR, COMPILED_ASSETS_DIR):
        path.mkdir(parents=True, exist_ok=True)
