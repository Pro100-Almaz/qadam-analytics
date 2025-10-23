#!/usr/bin/env bash
set -e

# Wait for DB
if [ -n "$DB_HOST" ]; then
  echo "Waiting for Postgres at $DB_HOST:$DB_PORT..."
  while ! nc -z "$DB_HOST" "$DB_PORT"; do sleep 1; done
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Start Gunicorn
exec gunicorn core.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers ${GUNICORN_WORKERS:-3} \
  --timeout ${GUNICORN_TIMEOUT:-30} \
  --access-logfile '-' \
  --error-logfile '-'
#  --capture-output \
#  --log-level debug

