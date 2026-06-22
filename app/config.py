"""
Application configuration using Pydantic Settings.
Loads from environment variables or .env file.
"""

import secrets
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root directory (where this repo is cloned)
_PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API Settings
    api_title: str = "MOE-Router Classification Service"
    api_version: str = "1.0.0"
    api_description: str = "Multilingual text classification using Mixture of Experts routing"
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    debug: bool = False

    # JWT Settings
    jwt_secret_key: str = secrets.token_urlsafe(32)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    # GPU Settings
    cuda_visible_devices: str = "0"
    gpu_memory_fraction: Optional[float] = None

    # Request Settings
    request_timeout_seconds: int = 600
    max_concurrent_gpu_requests: int = 1

    # Database URL — set via DATABASE_URL environment variable
    database_url: str = "postgresql://postgres:[YOUR-PASSWORD]@db.bjfrjsgvbibqsoyhwkvf.supabase.co:5432/postgres"


# Global settings instance
settings = Settings()
