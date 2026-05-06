# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc libpq-dev curl netcat-openbsd \
      libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
      libffi-dev libcairo2 fonts-noto-core \
  && rm -rf /var/lib/apt/lists/*

RUN useradd -m appuser
WORKDIR /app

# deps first for caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools && pip install -r requirements.txt

# app source
COPY . /app

# make static dir & permissions
RUN mkdir -p /vol/static && chown -R appuser:appuser /vol /app

# entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
