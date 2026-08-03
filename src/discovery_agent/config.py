"""Runtime configuration (discovery-agent 1.3). All env-driven; see .env.example."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database (the shared contract with Pulse; local sample DB in the demo).
    database_url: str = "postgresql://pulse:pulse@localhost:5433/pulse"

    # Optional Supabase backend. When both are set, the store talks PostgREST instead
    # of opening a Postgres socket — the hosted contract needs no DB password.
    supabase_url: str = ""
    supabase_service_key: str = ""

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    # LLM — model-agnostic via the OpenAI-compatible gateway (OpenRouter).
    openai_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    # Strong-first per the workshop: establish the ceiling, benchmark cheaper later (A2).
    scout_model: str = "openai/gpt-5.2"

    # Per-publisher budgets — hard caps, recorded in the trace on abort.
    scout_max_fetches: int = 8
    scout_max_usd: float = 0.50
    scout_max_llm_calls: int = 12

    # Run-level caps.
    run_max_publishers: int = 50
    rescout_days: int = 75          # staleness re-scout window (60-90d per spec)
    none_cooldown_days: int = 90

    # Langfuse (optional — absent keys mean tracing is a no-op).
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
