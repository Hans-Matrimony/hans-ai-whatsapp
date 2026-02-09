FROM python:3.11-slim

LABEL maintainer="Hans AI <admin@hans-ai.com>"
LABEL description="WhatsApp Webhook Handler for Hans AI Dashboard"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8003

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY whatsapp_webhook.py /app/
COPY app/ /app/app/

# Create non-root user
RUN useradd -m -u 1000 whatsapp && \
    chown -R whatsapp:whatsapp /app
USER whatsapp

# Expose port
EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

# Run application
CMD ["uvicorn", "whatsapp_webhook:app", "--host", "0.0.0.0", "--port", "8003"]
