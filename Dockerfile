# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

# System deps for psycopg2, Pillow, healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc libpq-dev curl netcat-openbsd \
  && rm -rf /var/lib/apt/lists/*

# non-root user
RUN useradd -m appuser
WORKDIR /app

# use layers for faster rebuilds
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# copy the rest
COPY . /app

# runtime helper
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
