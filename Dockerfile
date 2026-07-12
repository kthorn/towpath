FROM node:22-alpine AS web-builder

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./

ARG VITE_GOOGLE_MAPS_API_KEY
ARG VITE_GOOGLE_MAP_ID
ARG VITE_TRANSFER_MODE
ENV VITE_GOOGLE_MAPS_API_KEY=${VITE_GOOGLE_MAPS_API_KEY} \
    VITE_GOOGLE_MAP_ID=${VITE_GOOGLE_MAP_ID} \
    VITE_TRANSFER_MODE=${VITE_TRANSFER_MODE}
RUN npm run build

FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY pound/ pound/
RUN uv sync --locked --no-dev --no-editable
COPY --from=web-builder /build/web/dist /app/web/dist

RUN useradd --create-home --uid 10001 pound \
    && chown -R pound:pound /app
USER pound

ENV PATH="/app/.venv/bin:${PATH}" \
    POUND_STATIC_DIR=/app/web/dist
EXPOSE 8000

CMD ["uvicorn", "pound.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
