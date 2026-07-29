"""Runtime configuration, loaded from the environment (see .env.example)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database (the shared contract with Pulse; a local sample DB in the demo).
    database_url: str = "postgresql://pulse:pulse@localhost:5433/pulse"

    # LLM — model-agnostic via an OpenAI-compatible gateway (OpenRouter by default).
    openai_base_url: str = "https://openrouter.ai/api/v1"
    openai_api_key: str = ""
    scout_model: str = "openai/gpt-4o-mini"

    # Cost / scope controls.
    scout_max_venues: int = 25
    scout_rescout_days: int = 21


settings = Settings()
