# Helios backend.
#
# Multi-stage: the builder gets a compiler and produces a virtualenv; the runtime gets the
# virtualenv and nothing else. That difference is most of the image size and most of the
# attack surface — a production container has no business carrying gcc.
#
# Base images are pinned to an exact patch version, never to `latest` or to a floating
# minor. That is the minimum. A stronger pin is by digest — `python:3.11.9-slim-bookworm`
# is itself rebuilt periodically, so two builds a week apart can differ from identical
# source — and the way to adopt one is:
#
#     docker buildx imagetools inspect python:3.11.9-slim-bookworm --format '{{.Manifest.Digest}}'
#
# then append `@sha256:...` to the FROM lines. Digests are deliberately not committed here
# unresolved: a wrong or invented digest fails the build in a way that looks like a
# registry problem, and refreshing them is a reviewed change rather than a guess.

# ---------------------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------------------
FROM python:3.11.9-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is needed by a handful of scientific wheels on architectures without a
# prebuilt one. It stays in this stage and never reaches the runtime image.
RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies are copied and installed before the source. Docker caches layers by input,
# so a change to a route handler — which is most changes — reuses the dependency layer
# instead of reinstalling numpy and scikit-learn.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------------------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------------------
FROM python:3.11.9-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Containers ship structured logs so the aggregator can index fields rather than
    # regexing them back out of a sentence.
    SOLAR_JSON_LOGS=true

# curl is here only for the container healthcheck below. It is the one runtime tool this
# image carries that the application itself does not use.
RUN apt-get update \
 && apt-get install --no-install-recommends -y curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin helios

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=helios:helios alembic.ini ./
COPY --chown=helios:helios alembic ./alembic
COPY --chown=helios:helios app ./app

# `var` exists because the cache's local fallback tier writes here when Redis is
# unreachable. Nothing durable lives in it: estimates, experiments and sessions are all in
# PostgreSQL or Redis, which is what makes this container disposable.
RUN mkdir -p /app/var/cache /app/var/store && chown -R helios:helios /app/var

USER helios

EXPOSE 8000

# Liveness only. The container runtime should restart a process that has died; it must not
# restart one whose database is briefly unreachable, which is what a readiness-based
# healthcheck here would cause during any PostgreSQL blip — a dependency outage plus a
# cold fleet. The load balancer polls /api/health/ready for routing instead.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health/live || exit 1

# One worker per container, scaled by running more containers.
#
# The alternative — several uvicorn workers in one container — would put the analysis
# cache in one process's memory while requests were spread across siblings, so a follow-up
# request for an analysis would miss two times in three. Scaling by container keeps each
# instance a single coherent process and lets the orchestrator do the placement.
#
# --timeout-graceful-shutdown gives in-flight work time to finish on SIGTERM. A console
# model comparison can legitimately run for tens of seconds, and killing it mid-flight
# during a rolling deploy is a dropped request the user sees.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "45", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--no-access-log"]
