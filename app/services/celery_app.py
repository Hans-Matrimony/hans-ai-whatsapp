"""
Celery application for background task processing
"""
import os
from celery import Celery

# Get Redis URL from environment
redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    "hans_ai_whatsapp",
    broker=redis_url,
    backend=redis_url,
)

# Configure Celery
celery_app.conf.update(
    # Task settings
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    task_acks_late=True,  # Ack only after task completes
    task_reject_on_worker_lost=True,  # Re-queue if worker dies

    # Result backend
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,

    # Rate limiting
    task_annotations={
        'app.services.tasks.process_message_task': {'rate_limit': '10/m'}
    },

    # Routing (optional - for multiple queues)
    task_routes={
        'app.services.tasks.process_message_task': {'queue': 'whatsapp'},
        'app.services.tasks.send_message_task': {'queue': 'whatsapp'},
    },

    # Worker settings
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
)

# Schedule periodic tasks (optional)
celery_app.conf.beat_schedule = {
    'health-check-every-5-minutes': {
        'task': 'app.services.tasks.health_check_task',
        'schedule': 300.0,  # 5 minutes
    },
}
