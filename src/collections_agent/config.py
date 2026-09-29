"""Typed application settings, loaded from environment / .env.

Secrets live only in .env (gitignored). Never hard-code values here.
Phase 1 needs none of the provider keys, so they are optional and default
to None; later phases validate that the ones they use are present.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings sourced from environment variables and the .env file.

    Field names map to upper-case env vars automatically
    (e.g. ``livekit_url`` <- ``LIVEKIT_URL``), case-insensitively.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LiveKit (Phase 2)
    livekit_url: str | None = None
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None

    # Providers (Phase 2)
    deepgram_api_key: str | None = None
    openai_api_key: str | None = None
    cartesia_api_key: str | None = None

    # LLM model id, swappable via config.
    llm_model: str = "gpt-4o-mini"

    # Which seeded customer the demo call is about.
    customer_id: str = "CUST-001"

    # Local paths (not secrets; overridable via env if desired).
    db_path: str = "data/collections.db"
    logs_dir: str = "logs"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
