#!/bin/bash
# Health check script - only applies to web service
# Worker service (SERVICE_TYPE=worker) always returns healthy

SERVICE_TYPE=${SERVICE_TYPE:-web}

if [ "$SERVICE_TYPE" = "worker" ] || [ "$SERVICE_TYPE" = "beat" ]; then
    # Worker/beat services don't have HTTP endpoints
    # If Celery is running, container is healthy
    exit 0
fi

# For web service, check the HTTP endpoint
curl -f http://localhost:${PORT:-8003}/health || exit 1
