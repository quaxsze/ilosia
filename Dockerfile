FROM ghcr.io/astral-sh/uv:0.11.15 AS uv

FROM alpine/helm:3.19.0 AS helm

FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 app
RUN mkdir -p /tmp/prometheus && chmod 0777 /tmp/prometheus

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=helm /usr/bin/helm /usr/local/bin/helm
COPY --chown=app:app . .

RUN python manage.py collectstatic --noinput

RUN chmod +x scripts/start.sh

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=2)" || exit 1

CMD ["scripts/start.sh"]
