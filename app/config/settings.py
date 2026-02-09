"""
Application settings
"""
import os
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # WhatsApp Configuration
    whatsapp_verify_token: str = Field(..., description="Webhook verification token")
    whatsapp_phone_id: str = Field(..., description="Phone ID from Meta")
    whatsapp_access_token: str = Field(..., description="Access token from Meta")
    whatsapp_business_id: Optional[str] = Field(None, description="Business account ID")
    whatsapp_phone_number: str = Field(default="", description="Business phone number")

    # OpenClaw Configuration
    openclaw_url: str = Field(..., description="OpenClaw Gateway URL")
    openclaw_api_key: Optional[str] = Field(None, description="Optional API key")
    openclaw_timeout: int = Field(default=60, description="Timeout in seconds")

    # Message Processing
    message_timeout: int = Field(default=30, description="Message processing timeout")
    max_message_length: int = Field(default=4096, description="Max message length")
    enable_message_queue: bool = Field(default=True, description="Enable background queue")

    # Rate Limiting
    rate_limit_per_minute: int = Field(default=60, description="Rate limit per minute")
    rate_limit_burst: int = Field(default=10, description="Rate limit burst")

    # Redis/Celery
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/0")

    # Logging
    log_level: str = Field(default="info")
    log_format: str = Field(default="json")
    debug: bool = Field(default=False)

    # CORS
    cors_origins: List[str] = Field(default=["*"])

    # Features
    enable_media_handling: bool = Field(default=True)
    enable_interactive_messages: bool = Field(default=True)
    enable_message_status: bool = Field(default=False)

    # Retry
    max_retries: int = Field(default=3)
    retry_delay: float = Field(default=1.0)

    # Application
    app_name: str = "WhatsApp Webhook Handler"
    app_version: str = "1.0.0"
    port: int = Field(default=8003)


settings = Settings()
