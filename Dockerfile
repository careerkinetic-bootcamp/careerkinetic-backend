FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for Docker layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --frozen --no-dev --no-editable

# Copy application code
COPY app/ ./app/

# Default port exposure
EXPOSE 8080 10000

# Run with Gunicorn + UvicornWorker for production-grade concurrency
CMD ["sh", "-c", "uv run gunicorn app.main:app -w ${WEB_CONCURRENCY:-2} -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8080}"]
