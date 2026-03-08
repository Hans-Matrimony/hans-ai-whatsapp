#!/bin/bash
# Start Celery worker for processing WhatsApp messages

# Load environment
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "Starting Celery worker for hans-ai-whatsapp..."

celery -A app.services.celery_app worker \
    --loglevel=info \
    --queue=whatsapp \
    --concurrency=4 \
    --max-tasks-per-child=100 \
    --pidfile=/tmp/celery-worker.pid
