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

    # LiveKit Inference model strings (Option A). All swappable via .env.
    # LLM is the "brain"; changing it to e.g. "google/gemini-3.8-flash" is a
    # one-line config change (PRD §4 swappable-LLM requirement).
    llm_model: str = "openai/gpt-4o-mini"
    stt_model: str = "deepgram/flux-general"
    tts_model: str = "cartesia/sonic-3"
    # Optional Cartesia voice id. None uses the model's default voice.
    tts_voice: str | None = None

    # Agent name used by `python agent.py dev` and the Agent Console.
    agent_name: str = "voice-agent"

    # The organisation the agent calls on behalf of (agent's own branding,
    # shown in the greeting disclosure). Not customer data.
    company_name: str = "Meridian Finance"

    # Which seeded customer the demo call is about.
    customer_id: str = "CUST-001"

    # Local paths (not secrets; overridable via env if desired).
    db_path: str = "data/collections.db"
    logs_dir: str = "logs"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
