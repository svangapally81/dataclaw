"""Boot-time guard rails: refuse to start with default secrets."""
from __future__ import annotations

import importlib

import pytest

from app.core.security import verify_password
from app.models.domain import User


@pytest.mark.parametrize(
    "env_overrides",
    [
        {"MASTER_KEY": "change-me-32-byte-fernet-key", "SESSION_SECRET": "real-secret-32bytes-1234567890ab"},
        {"MASTER_KEY": "real-master-key-32bytes-1234567890", "SESSION_SECRET": "change-me-session-secret"},
        {"MASTER_KEY": "", "SESSION_SECRET": "real-secret-32bytes-1234567890ab"},
    ],
)
def test_default_secrets_refuse_boot(monkeypatch, env_overrides):
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DEMO_MODE", "false")

    config = importlib.reload(importlib.import_module("app.core.config"))
    security = importlib.reload(importlib.import_module("app.core.security"))
    settings = config.get_settings()

    with pytest.raises((RuntimeError, ValueError)):
        security.validate_runtime_secrets(settings.master_key, settings.session_secret)


def test_strong_secrets_accept_boot(monkeypatch):
    monkeypatch.setenv("MASTER_KEY", "strong-master-key-32bytes-1234567890")
    monkeypatch.setenv("SESSION_SECRET", "strong-session-secret-32bytes-1234567890")
    monkeypatch.setenv("DEMO_MODE", "false")

    config = importlib.reload(importlib.import_module("app.core.config"))
    security = importlib.reload(importlib.import_module("app.core.security"))
    settings = config.get_settings()

    security.validate_runtime_secrets(settings.master_key, settings.session_secret)


@pytest.mark.asyncio
async def test_first_admin_bootstrap_uses_env_credentials(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "admin_email", "owner@example.com")
    monkeypatch.setattr(main_module.settings, "admin_password", "change-this-now")

    class FakeSession:
        def __init__(self) -> None:
            self.users: list[User] = []

        async def scalar(self, _statement):  # noqa: ANN001
            return len(self.users)

        def add(self, user: User) -> None:
            self.users.append(user)

        async def flush(self) -> None:
            return None

    session = FakeSession()
    user, created = await main_module._ensure_first_admin(session)
    assert created is True
    assert user is not None
    assert user.email == "owner@example.com"
    assert user.is_admin is True
    assert verify_password("change-this-now", user.password_hash)

    _, created_again = await main_module._ensure_first_admin(session)
    assert created_again is False
