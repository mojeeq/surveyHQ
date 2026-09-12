# ---- Backend image: FastAPI + Celery share one image, different commands ----
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is used by the container health check; build-essential and libpq-dev are
# build dependencies for pyreadstat and psycopg2.
#
# r-base-core is here so that R_SCRIPTS_ENABLED is one setting rather than a
# rebuild. bubblewrap is the security boundary for arbitrary project R code:
# it gives each run a private filesystem/network namespace with only that
# project's workspace writable. Installing R does not switch the feature on.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        r-base-core \
        bubblewrap \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pyproject.toml .
COPY bin/surveyhq-rscript /usr/local/bin/surveyhq-rscript
RUN chmod 0755 /usr/local/bin/surveyhq-rscript

# Run as a non-root user; /data is a mounted volume so it needs to be writable.
RUN useradd --create-home --uid 10001 surveyhq \
    && mkdir -p /data \
    && chown -R surveyhq:surveyhq /app /data
USER surveyhq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]