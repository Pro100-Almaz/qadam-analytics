#!/usr/bin/env bash
set -e
docker compose exec -T app python manage.py migrate --noinput
