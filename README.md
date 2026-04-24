# Clipping Automation

Clipping Automation is a two-part app for discovering Reddit clips, filtering them for compilation use, and rendering a short-form countdown video.

The current codebase is split into:

- `backend/`: FastAPI API for Reddit discovery, clip playback, compilation rendering, and used-clip tracking
- `frontend/`: React app for discovery, five-clip selection, render orchestration, and rendered-video download

## Current Workflow

1. Open the discovery screen in the frontend.
2. Search using tags such as `funny`, `animal`, or `fails`.
3. Let the backend discover relevant subreddits, fetch posts, score candidates, and filter unsafe or already-used items.
4. Select exactly 5 compilation-ready clips.
5. Move to the compilation screen, optionally remove clips, and render the final video.
6. Download the rendered output and mark the source clips as used so they do not show up again.

## Repository Layout

```text
backend/
  main.py
  config.py
  schemas.py
  routers/
  services/
  tests/
  utils/
frontend/
  public/
  src/
    components/
    pages/
    services/
data/
  assets/
    approved/
    compiled/
  exports/
  state/
README.md
plan.md
```

## Backend Overview

The FastAPI backend lives in `backend/` and exposes the API under `/api`.

Key routes:

- `GET /` - API status landing page
- `GET /api/health` - health/version check
- `POST /api/reddit/discover` - discover and rank Reddit clips from tags or supplied subreddits
- `GET /api/reddit/clips/{external_id}/playback` - cached playback proxy for a discovered Reddit clip
- `POST /api/compilation/render` - render a countdown compilation video with FFmpeg
- `POST /api/compilation/mark-used` - record clips as consumed after download

Core backend modules:

- `services/reddit_discovery_service.py`: subreddit discovery, Reddit fetches, ranking, duplicate avoidance, playback caching
- `services/copyright_service.py`: audio and metadata heuristics for copyright risk assessment
- `services/compilation_service.py`: FFmpeg-based clip normalization, overlay generation, outro handling, and final concat
- `schemas.py`: request/response models and validation rules
- `config.py`: directory setup, API settings, database path, Reddit credentials, and frontend CORS origins

### Backend Requirements

- Python 3.11+
- `ffmpeg` and `ffprobe` available on `PATH`

### Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend default URL:

- `http://127.0.0.1:8000`
- API base: `http://127.0.0.1:8000/api`
- Swagger docs: `http://127.0.0.1:8000/docs`

### Backend Environment Variables

Optional environment variables:

- `DATABASE_URL`: overrides the default SQLite path at `data/state/clipping_automation.db`
- `REDDIT_CLIENT_ID`: enables authenticated Reddit API access
- `REDDIT_CLIENT_SECRET`: Reddit API secret
- `REDDIT_USER_AGENT`: overrides the default Reddit user agent string
- `FRONTEND_ORIGINS`: comma-separated CORS origins for the React app

The backend now loads `.env` files from either the repo root or `backend/.env` automatically.
You can start from `backend/.env.example`.

If Reddit credentials are not set, discovery falls back to public Reddit access where possible.

## Frontend Overview

The frontend is a React app in `frontend/` built with `react-scripts`.

Main screens:

- `DashboardPage`: workflow overview and entry points
- `RedditDiscoveryPage`: tag input, subreddit discovery, paginated results, clip selection
- `CompilationPage`: selected lineup review, render trigger, rendered-video preview and download

Frontend API integration is defined in `frontend/src/services/api.js` and points to:

- `http://127.0.0.1:8000/api` by default
- `REACT_APP_API_URL` when explicitly set

### Frontend Setup

```bash
cd frontend
npm install
npm start
```

Frontend default URL:

- `http://localhost:3000`

To point the UI at a different backend:

```bash
REACT_APP_API_URL=http://127.0.0.1:8000/api npm start
```

## Rendering Notes

Compilation rendering depends on local FFmpeg tools and the bundled outro file:

- default outro asset: `data/exports/Extras/Outro.mp4`
- rendered outputs: `data/assets/compiled/`
- cached Reddit playback files: `data/assets/approved/reddit-playback-cache/`

The renderer currently:

- expects 1 to 5 selected clips
- limits individual clip duration to 24 seconds
- formats output for 1080x1920 vertical video
- overlays ranking and wrapped titles on each clip
- appends the outro clip to the final render

## Testing

Current automated coverage is focused on the Reddit discovery service.

Run backend tests with:

```bash
cd backend
python -m unittest discover -s tests
```

## Current Status

This repository is mid-migration from an older CLI-oriented version to the current web app structure. The active implementation is the FastAPI backend plus the React frontend already present in the root `backend/` and `frontend/` directories.
