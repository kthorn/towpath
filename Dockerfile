FROM node:24-alpine AS web-builder

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
RUN test -n "$VITE_GOOGLE_MAPS_API_KEY" \
    && test -n "$VITE_GOOGLE_MAP_ID" \
    && npm run build

FROM python:3.14-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/pound-core/ packages/pound-core/
COPY packages/pound-web/ packages/pound-web/
RUN uv sync --package pound-web --no-dev --frozen
RUN .venv/bin/python -c "from importlib.util import find_spec; assert all(find_spec(name) is None for name in ('pound_build', 'requests', 'flask', 'osmium')); import pound, pound_web"
COPY artifacts/ /app/artifacts/
COPY data/ /app/data/
RUN test -f /app/artifacts/england.pkl
RUN .venv/bin/python -c "from pathlib import Path; from pound.catalog.artifact import load_catalog; load_catalog(Path('/app/artifacts/england-catalog.pkl'))"
COPY --from=web-builder /build/web/dist /app/web/dist

RUN useradd --create-home --uid 10001 pound \
    && chown -R pound:pound /app
USER pound

ENV PATH="/app/.venv/bin:${PATH}" \
    POUND_ARTIFACT_PATH=/app/artifacts/england.pkl \
    POUND_STATIC_DIR=/app/web/dist \
    POUND_BOAT_HIRE_ENRICHMENT_PATH=/app/data/boat-hire-enrichment.csv
EXPOSE 8000

CMD ["uvicorn", "pound_web.app:app", "--host", "0.0.0.0", "--port", "8000"]
