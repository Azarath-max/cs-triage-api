from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value has a safe default so the app boots in CI."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    repository: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/cs_automation"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    webhook_secret: str = ""

    min_confidence: float = 0.70
    auto_send_confidence: float = 0.80

    test_recipient: str = ""

    @property
    def llm_enabled(self) -> bool:
        """Without a key the API falls back to deterministic classification."""
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
