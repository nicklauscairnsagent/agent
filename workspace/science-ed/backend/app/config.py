"""
ScienceEd Backend Configuration.

All settings are loaded from environment variables with SCIENCE_ED_ prefix
(or DATABASE_URL directly for the DB connection string).
"""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic_settings import BaseSettings


# Compute the repository root: backend/app/../.. = repo root
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


class Settings(BaseSettings):
    model_config: ClassVar[dict] = {
        "env_prefix": "SCIENCE_ED_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    # --- Observability ---
    sentry_dsn: str = ""

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./science_ed.db"

    # --- Auth ---
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_seconds: int = 86400  # 24 hours
    magic_link_expire_minutes: int = 15

    # --- CORS ---
    allowed_origins: str = "http://localhost:4000,https://sims.science,https://api.sims.science"

    # --- AI ---
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 512

    # --- Catalog Sync ---
    github_pages_url: str = "https://sims.science"
    catalog_json_path: str = "/_data/catalog.json"

    # --- Observability ---
    sentry_dsn: str = ""

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    # --- Frontend URLs (no hardcoded URLs — use env vars) ---
    frontend_login_url: str = "https://sims.science/login"
    frontend_register_url: str = "https://sims.science/register"

    # --- Redis (optional, for caching + rate limiting) ---
    redis_url: str = ""

    @property
    def origins_list(self) -> list[str]:
        """Parse ALLOWED_ORIGINS comma-separated string into a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def repo_root(self) -> str:
        """Absolute path to the repository root (where _includes/, en/ live)."""
        return _REPO_ROOT

    @property
    def tasks_content_dir(self) -> str:
        """Absolute path to the Jekyll _includes/tasks directory."""
        return os.path.join(_REPO_ROOT, "_includes", "tasks")

    @property
    def ngss_content_dir(self) -> str:
        """Absolute path to the NGSS documentation directory (en/ngss/)."""
        return os.path.join(_REPO_ROOT, "en", "ngss")


settings = Settings()
