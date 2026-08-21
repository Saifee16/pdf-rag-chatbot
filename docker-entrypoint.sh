#!/bin/sh
set -eu

case "${1:-api}" in
  api)
    echo "Applying database migrations..."
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO
    ;;
  *)
    exec "$@"
    ;;
esac
