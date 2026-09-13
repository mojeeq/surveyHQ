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
# rebuild. Installing it does not switch the feature on: the setting defaults
# to false, because running R is a decision for whoever deploys the platform,
# not for its image.
#
# libseccomp builds and then runs the sandbox launcher below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        r-base-core \
        libseccomp-dev \
    && rm -rf /var/lib/apt/lists/*

# The sandbox R is run through.
#
# It applies a Landlock filesystem allowlist and a seccomp syscall policy and
# then execs /usr/bin/Rscript, so a project's script reaches its own workspace
# and nothing else. /usr/bin/Rscript keeps its ordinary name beside it, which
# is what lets the platform tell the two apart: it probes what R_BINARY names
# and refuses to run if the answer is not this launcher.
COPY sandbox/r-sandbox.c /tmp/r-sandbox.c
RUN cc -O2 -Wall -Wextra -Werror /tmp/r-sandbox.c -lseccomp \
        -o /usr/local/bin/surveyhq-r-sandbox \
    && chmod 0755 /usr/local/bin/surveyhq-r-sandbox \
    && rm /tmp/r-sandbox.c

# The same check the platform makes, as a command an administrator can run
# before turning R on: docker compose exec api surveyhq-check-r-sandbox
COPY sandbox/check-r-sandbox.sh /usr/local/bin/surveyhq-check-r-sandbox
RUN chmod 0755 /usr/local/bin/surveyhq-check-r-sandbox

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pyproject.toml .

# Run as a non-root user; /data is a mounted volume so it needs to be writable.
RUN useradd --create-home --uid 10001 surveyhq \
    && mkdir -p /data \
    && chown -R surveyhq:surveyhq /app /data
USER surveyhq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
