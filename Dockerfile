FROM python:3.13-slim-bookworm AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY packvault ./packvault

RUN pip wheel --no-deps -w /wheels .


FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PACKVAULT_CONFIG=/config/config.yaml \
    PACKVAULT_APP_ROOT=/app

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin packvault \
    && mkdir -p /app /config /data/maven /cache/maven \
    && chown -R packvault:packvault /app /config /data /cache

WORKDIR /app

COPY --from=builder /wheels /wheels

RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

COPY alembic.ini ./
COPY alembic ./alembic/

USER packvault

EXPOSE 8080 9090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9090/livez', timeout=3).read()" || exit 1

CMD ["packvault"]
