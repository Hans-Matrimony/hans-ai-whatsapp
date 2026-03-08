#!/bin/bash
# Health check script - only applies to web service
# Worker, beat, and flower services always return healthy

SERVICE_TYPE=${SERVICE_TYPE:-web}

if [ "$SERVICE_TYPE" = "worker" ] || [ "$SERVICE_TYPE" = "beat" ] || [ "$SERVICE_TYPE" = "flower" ]; then
    # Worker/beat/flower services - if running, container is healthy
    exit 0
fi

# For web service, check the HTTP endpoint
curl -f http://localhost:${PORT:-8003}/health || exit 1
