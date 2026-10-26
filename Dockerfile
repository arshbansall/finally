# syntax=docker/dockerfile:1

# FinAlly — single-container build.
#   Stage 1 (frontend): Node 20 builds the Next.js static export -> /frontend/out
#   Stage 2 (backend-deps): uv resolves the locked Python deps into /app/backend/.venv
#   Stage 3 (runtime): Python 3.12 slim with the venv, backend code and static export
#
#   docker build -t finally .
#   docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally

# ---------------------------------------------------------------------------
# Stage 1: frontend static export (platform-independent output, so build natively)
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:20-slim AS frontend

WORKDIR /frontend
ENV NEXT_TELEMETRY_DISABLED=1

# Dependencies first for layer caching; use the lockfile when there is one.
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

COPY frontend/ ./
RUN npm run build && test -f out/index.html

# ---------------------------------------------------------------------------
# Stage 2: Python dependencies via uv (uv itself stays out of the final image)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS backend-deps

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 3: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/backend/.venv/bin:$PATH" \
    FINALLY_DB_PATH=/app/db/finally.db \
    FINALLY_STATIC_DIR=/app/backend/static

# Non-root user. /app/db is created and owned by it so a fresh named volume
# mounted there inherits that ownership and SQLite can write to it.
RUN groupadd --system --gid 1000 finally \
    && useradd --system --uid 1000 --gid finally --create-home --home-dir /home/finally finally \
    && mkdir -p /app/db \
    && chown finally:finally /app/db

WORKDIR /app/backend

COPY --from=backend-deps /app/backend/.venv /app/backend/.venv
COPY backend/ ./
COPY --from=frontend /frontend/out ./static

USER finally

VOLUME ["/app/db"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5"]
