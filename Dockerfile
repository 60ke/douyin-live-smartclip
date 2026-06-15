FROM python:3.11-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
    HF_ENDPOINT=https://hf-mirror.com \
    HUGGINGFACE_HUB_BASE_URL=https://hf-mirror.com \
    HF_HUB_ENDPOINT=https://hf-mirror.com

# Use Tsinghua Debian mirrors for apt.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
          -e 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
          -e 's|http://security.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
          -e 's|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
          /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
          -e 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
          -e 's|http://security.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
          -e 's|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
          /etc/apt/sources.list; \
    fi

# system deps (ffmpeg for recording/export; build tools for source-only wheels on arm64)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install uv from the configured Tsinghua PyPI mirror
RUN python -m pip install --no-cache-dir uv

# pyproject + lock first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --index-url https://pypi.tuna.tsinghua.edu.cn/simple

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
