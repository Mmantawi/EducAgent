from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration shared by later pipeline phases."""

    model_config = SettingsConfigDict(
        env_prefix="EDUAGENT_KG_", env_file=".env", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_dir: Path = Path("data")
    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_model: str = "gemini-2.5-flash"
    extraction_max_concurrency: int = Field(default=2, ge=1, le=32)
    extraction_rate_limit_per_minute: int = Field(default=30, ge=1)
    extraction_max_retries: int = Field(default=3, ge=0, le=10)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str | None = Field(default=None, repr=False)
    neo4j_database: str = "neo4j"

