FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS backend-builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.10.10
COPY . .
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim-bookworm AS runtime

ARG VERSION=dev
ARG REVISION=unknown

LABEL org.opencontainers.image.title="QuantHub" \
      org.opencontainers.image.description="Multi-market quantitative research and simulated trading workspace" \
      org.opencontainers.image.source="https://github.com/1634594707/QuantHub" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

RUN mkdir -p /data

WORKDIR /app
COPY --from=backend-builder /app /app
COPY --from=frontend-builder /app/web/dist /app/web/dist

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    QUANTHUB_DEPLOYMENT_MODE=local \
    QUANTHUB_ENV_PATH=/data/quanthub.env \
    QUANTHUB_STORE_PATH=/data/quanthub.db

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5)"

ENTRYPOINT ["uvicorn", "apps.api.container:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
