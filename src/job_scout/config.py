"""Settings loaded from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_match: str = "claude-haiku-5-5"
    model_package: str = "claude-sonnet-5-5"
    monthly_budget_eur: float = 5.0
    digest_max_jobs: int = 7
    reminder_days: int = 14  # nudge for applications without news after this many days
    fit_threshold: int = 5
    reach_threshold: int = 4  # 4 = stretch (3 to 4 years asked): the core FDE roles often sit here
    instant_push_threshold: int = 9
    instant_reach_threshold: int = 6
    include_abroad: bool = False
    eur_per_usd: float = 0.92
    profile_yaml: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
