#!/bin/bash
# Entrypoint script for Hans AI WhatsApp Webhook
# Supports running as web server, Celery worker, or Celery beat scheduler

set -e

# Default to web server if SERVICE_TYPE is not set
SERVICE_TYPE=${SERVICE_TYPE:-web}

echo "Starting Hans AI WhatsApp Webhook..."
echo "Service Type: $SERVICE_TYPE"

case "$SERVICE_TYPE" in
    web)
        echo "Starting FastAPI web server..."
        exec uvicorn whatsapp_webhook:app --host 0.0.0.0 --port ${PORT:-8003}
        ;;

    worker)
        echo "Starting Celery worker..."
        exec celery -A app.services.celery_app worker \
            --loglevel=info \
            --concurrency=${CELERY_CONCURRENCY:-50} \
            --max-tasks-per-child=100 \
            --queues=celery,whatsapp
        ;;

    beat)
        echo "Starting Celery beat scheduler..."
        exec celery -A app.services.celery_app beat \
            --loglevel=info
        ;;

    flower)
        echo "Starting Flower monitoring..."
        exec celery -A app.services.celery_app flower \
            --port=5555 \
            --broker=${CELERY_BROKER_URL}
        ;;

    *)
        echo "Error: Unknown SERVICE_TYPE='$SERVICE_TYPE'"
        echo "Valid options: web, worker, beat, flower"
        exit 1
        ;;
esac
