import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DATA_DIR = Path(os.environ.get("DATACLAW_HOME", str(Path.home() / ".dataclaw")))


def load_env_file(path: Path | None = None) -> None:
    """Merge KEY=VALUE lines from a .env-style file into os.environ.

    Existing process env wins; this only fills in keys that are unset so
    Docker/CI can override the on-disk config without editing the file.
    Safe to call multiple times.
    """
    target = path or (DATA_DIR / ".env")
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "DataClaw"
    environment: str = "local"
    database_url: str = Field(
        f"sqlite+aiosqlite:///{DATA_DIR / 'app.sqlite'}",
        alias="DATABASE_URL",
    )
    demo_database_url: str = Field(
        f"sqlite+aiosqlite:///{DATA_DIR / 'demo.sqlite'}",
        alias="DEMO_DATABASE_URL",
    )
    master_key: str = Field("change-me-32-byte-fernet-key", alias="MASTER_KEY")
    session_secret: str = Field("change-me-session-secret", alias="SESSION_SECRET")
    secure_cookies: bool | None = Field(None, alias="SECURE_COOKIES")
    admin_email: str = Field("admin@dataclaw.local", alias="ADMIN_EMAIL")
    admin_password: str = Field("dataclaw-local-admin", alias="ADMIN_PASSWORD")
    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4.1-mini", alias="OPENAI_MODEL")
    llm_provider: str = Field("openai", alias="DATACLAW_LLM_PROVIDER")
    chroma_url: str | None = Field(None, alias="CHROMA_URL")
    chroma_path: str = Field(str(DATA_DIR / "chroma"), alias="CHROMA_PATH")
    vector_test_double: bool = Field(False, alias="DATACLAW_VECTOR_TEST_DOUBLE")
    test_auto_create_schema: bool = Field(False, alias="DATACLAW_TEST_AUTO_CREATE_SCHEMA")
    embedded_worker: bool = Field(True, alias="DATACLAW_EMBEDDED_WORKER")
    embedding_provider: str = Field("openai", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
    wiki_root: str = Field(str(DATA_DIR / "wiki"), alias="WIKI_ROOT")
    cors_origins_raw: Annotated[str, NoDecode] = Field(
        "http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )
    demo_mode: bool = Field(False, alias="DEMO_MODE")
    observability_mock: bool = Field(False, alias="OBSERVABILITY_MOCK")
    auth_disabled: bool = Field(False, alias="DATACLAW_AUTH_DISABLED")
    smtp_host: str | None = Field(None, alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str | None = Field(None, alias="SMTP_USER")
    smtp_pass: str | None = Field(None, alias="SMTP_PASS")
    smtp_from: str | None = Field(None, alias="SMTP_FROM")
    smtp_use_tls: bool = Field(True, alias="SMTP_USE_TLS")
    pagerduty_routing_key: str | None = Field(None, alias="PAGERDUTY_ROUTING_KEY")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def cookies_secure(self) -> bool:
        if self.secure_cookies is not None:
            return self.secure_cookies
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
