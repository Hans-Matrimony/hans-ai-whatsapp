#!/bin/bash
# Start Celery Beat scheduler for periodic tasks

# Load environment
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "Starting Celery beat scheduler..."

celery -A app.services.celery_app beat \
    --loglevel=info \
    --pidfile=/tmp/celery-beat.pid \
    --scheduler=redisbeat.RedisScheduler
