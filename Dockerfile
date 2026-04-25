FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund
COPY frontend/ ./
ENV CI=true
RUN npm run build


FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1
ENV FFMPEG_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
ENV SERVE_FRONTEND=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY data/reddit_topic_markers.json ./data/reddit_topic_markers.json
COPY data/exports/Extras/Outro.mp4 ./data/exports/Extras/Outro.mp4
COPY --from=frontend-build /app/frontend/build ./frontend/build

WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
