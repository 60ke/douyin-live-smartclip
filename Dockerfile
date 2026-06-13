FROM python:3.11-slim

# system deps (ffmpeg for recording/export)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# pyproject + lock first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# source
COPY src/ ./src/
COPY configs/ ./configs/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# runtime dirs
RUN mkdir -p /app/data /app/cache /app/logs

EXPOSE 8000

# .env / data / cache are volume-mounted at runtime
CMD ["uv", "run", "liveclip", "api", "serve", "--host", "0.0.0.0", "--port", "8000"]
