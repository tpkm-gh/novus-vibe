"""Central settings, loaded from environment / .env.

Every external dependency in this app (Postgres, Adobe PDF Services,
an LLM for reflection) is optional at startup because of one design rule:
the app must always boot and demo without any credentials. See
docs/PLAYBOOK.md, "Decisions worth defending" #1.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://novus:novus@localhost:5432/novus_vibe"
    use_sqlite_fallback: bool = True

    # PDF generation provider: "mock" | "live"
    pdf_provider: str = "mock"
    pdf_services_client_id: str = ""
    pdf_services_client_secret: str = ""

    # Reflection provider: "rule_based" | "llm"
    reflection_provider: str = "rule_based"
    anthropic_api_key: str = ""
    # Verify this is still current at https://docs.claude.com/en/docs/about-claude/models
    # before a live demo -- model IDs get superseded.
    anthropic_model: str = "claude-3-5-haiku-20241022"

    # Misc
    storage_dir: str = "./storage"
    max_generation_retries: int = 2

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
