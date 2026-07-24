FROM python:3.11-slim

ENV PIP_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.mirrors.ustc.edu.cn \
    UV_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple \
    UV_DEFAULT_INDEX=https://pypi.mirrors.ustc.edu.cn/simple \
    HF_ENDPOINT=https://hf-mirror.com \
    HUGGINGFACE_HUB_BASE_URL=https://hf-mirror.com \
    HF_HUB_ENDPOINT=https://hf-mirror.com \
    PYTHONPATH=/app/src

# 中科大 Debian 源
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
          -e 's|deb.debian.org|mirrors.ustc.edu.cn|g' \
          -e 's|security.debian.org|mirrors.ustc.edu.cn|g' \
          /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
          -e 's|deb.debian.org|mirrors.ustc.edu.cn|g' \
          -e 's|security.debian.org|mirrors.ustc.edu.cn|g' \
          /etc/apt/sources.list; \
    fi

# system deps (ffmpeg for recording/export; build tools for source-only wheels on arm64)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install uv from USTC PyPI
RUN python -m pip install --no-cache-dir uv

# pyproject + lock first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# runtime font for Chinese cover rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# source
COPY src/ ./src/
COPY configs/ ./configs/
COPY assets/ ./assets/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# runtime dirs
RUN mkdir -p /app/data /app/cache /app/logs

EXPOSE 8000

# .env / data / cache are volume-mounted at runtime
CMD ["/app/.venv/bin/liveclip", "api", "serve", "--host", "0.0.0.0", "--port", "8000"]
