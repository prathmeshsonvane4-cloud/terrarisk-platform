# syntax=docker/dockerfile:1

# python:3.14-slim-bookworm matches the interpreter this codebase is
# actually developed and tested against (confirmed via the local venv's
# __pycache__ tags) — not an approximation to "whatever 3.x is handy".

FROM python:3.14-slim-bookworm AS builder

WORKDIR /build

# build-essential + libgeos-dev: build-time only. Python 3.14 is new enough
# that a couple of transitive/native dependencies (notably shapely, which
# links against GEOS) may not yet publish a prebuilt wheel for every
# platform — this lets pip fall back to a source build instead of failing
# outright. None of this ships in the runtime stage below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.14-slim-bookworm AS runtime

# libgeos-c1v5: shapely's runtime shared-library dependency. Only needed if
# the builder stage above had to compile shapely from source rather than use
# a prebuilt manylinux wheel (see comment above) — cheap to include either
# way, and the image stays slim since only the runtime .so ships here, not
# the -dev headers or a compiler.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-c1v5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin terrarisk

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts
COPY docker-entrypoint.sh .

RUN chmod +x docker-entrypoint.sh \
    && mkdir -p var/pdf_cache app/uploads \
    && chown -R terrarisk:terrarisk /app

USER terrarisk

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Hits the cheap liveness probe (/health, unchanged since M0) — no curl
# installed just for this; Python's stdlib is already on PATH.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request as u; import sys; sys.exit(0 if u.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
