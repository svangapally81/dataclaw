# DataClaw — single-image build.
#
# Stage 1 builds the React frontend with Node 22.
# Stage 2 builds a Python 3.12 image, copies the prebuilt frontend into
# `app/static`, and installs the backend as a pipx-style application so the
# `dataclaw` CLI is on $PATH.

FROM node:22-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATACLAW_HOME=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/dataclaw
COPY backend/pyproject.toml backend/README.md* ./
COPY backend/app ./app
COPY --from=frontend /src/dist ./app/static

# Install build deps for native wheels (asyncpg/aiomysql/pymssql), then prune.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential freetds-dev freetds-bin \
    && pip install --upgrade pip \
    && pip install . \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/* /root/.cache

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["dataclaw"]
CMD ["start", "--host", "0.0.0.0", "--port", "8000", "--no-browser", "--foreground"]
