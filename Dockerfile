# Unified image for the dashboard API + arq worker.
# Build context is the repo root so we can install both the root
# `tradingagents` package and the `server` app into the same image.

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy the root tradingagents package (needed by the worker)
COPY pyproject.toml requirements.txt ./
COPY tradingagents ./tradingagents

# Copy the server app and sync its deps (which include path-dep on ..)
COPY server ./server
WORKDIR /app/server
RUN uv sync --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
