from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.core.security import decrypt_json, encrypt_json


@pytest.fixture
async def rotate_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    monkeypatch.setenv("DEMO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'demo.sqlite'}")
    monkeypatch.setenv("MASTER_KEY", "old-master-key")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-please-change")
    monkeypatch.setenv("DEMO_MODE", "true")

    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.db.session as session_module

    importlib.reload(session_module)
    from app.db.base import Base
    from app.models.domain import AppSetting, Connector, Workspace

    async with session_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_module.SessionLocal() as session:
        workspace = Workspace(name="Rotate")
        session.add(workspace)
        await session.flush()
        session.add(
            Connector(
                workspace_id=workspace.id,
                slug="postgres",
                category="data_store",
                display_name="Postgres",
                status="connected",
                credential_state="configured",
                encrypted_credentials=encrypt_json("old-master-key", {"password": "secret"}),
            )
        )
        session.add(AppSetting(key="llm:openai", encrypted_value=encrypt_json("old-master-key", {"api_key": "sk-test"})))
        await session.commit()
        yield session_module
    await session_module.engine.dispose()


@pytest.mark.asyncio
async def test_rotate_master_key_reencrypts_connectors_and_settings(rotate_session) -> None:
    from app.cli import _rotate_master_key
    from app.models.domain import AppSetting, Connector

    connector_count, setting_count = await _rotate_master_key("old-master-key", "new-master-key")

    assert connector_count == 1
    assert setting_count == 1
    async with rotate_session.SessionLocal() as session:
        connector = await session.scalar(select(Connector).where(Connector.slug == "postgres"))
        setting = await session.get(AppSetting, "llm:openai")
        assert connector is not None
        assert setting is not None
        assert decrypt_json("new-master-key", connector.encrypted_credentials or "") == {"password": "secret"}
        assert decrypt_json("new-master-key", setting.encrypted_value) == {"api_key": "sk-test"}
        with pytest.raises(InvalidToken):
            decrypt_json("old-master-key", connector.encrypted_credentials or "")


@pytest.mark.asyncio
async def test_rotate_master_key_wrong_old_key_rolls_back(rotate_session) -> None:
    from app.cli import _rotate_master_key
    from app.models.domain import Connector

    with pytest.raises(InvalidToken):
        await _rotate_master_key("wrong-master-key", "new-master-key")

    async with rotate_session.SessionLocal() as session:
        connector = await session.scalar(select(Connector).where(Connector.slug == "postgres"))
        assert connector is not None
        assert decrypt_json("old-master-key", connector.encrypted_credentials or "") == {"password": "secret"}


def test_rotate_master_key_rejects_same_key(monkeypatch) -> None:
    from app.cli import cmd_rotate_master_key

    called = False

    async def fake_rotate(old_key: str, new_key: str):  # noqa: ARG001
        nonlocal called
        called = True
        return 0, 0

    monkeypatch.setattr("app.cli._rotate_master_key", fake_rotate)
    monkeypatch.setattr("app.cli._read_pid", lambda: None)
    monkeypatch.setenv("DATACLAW_OLD_MASTER_KEY", "same")
    monkeypatch.setenv("DATACLAW_NEW_MASTER_KEY", "same")

    result = cmd_rotate_master_key(SimpleNamespace())

    assert result == 1
    assert called is False


def test_rotate_master_key_accepts_environment_keys(monkeypatch) -> None:
    from app.cli import cmd_rotate_master_key

    captured = None

    async def fake_rotate(old_key: str, new_key: str):
        nonlocal captured
        captured = old_key, new_key
        return 0, 0

    monkeypatch.setattr("app.cli._rotate_master_key", fake_rotate)
    monkeypatch.setattr("app.cli._read_pid", lambda: None)
    monkeypatch.setenv("DATACLAW_OLD_MASTER_KEY", "old")
    monkeypatch.setenv("DATACLAW_NEW_MASTER_KEY", "new")

    result = cmd_rotate_master_key(SimpleNamespace())

    assert result == 0
    assert captured == ("old", "new")


def test_rotate_master_key_loads_dataclaw_home_env_before_rotating(monkeypatch, tmp_path) -> None:
    """Env in ~/.dataclaw/.env should be visible to rotate_master_key via main()."""
    import app.cli as cli

    env_path = tmp_path / ".env"
    env_path.write_text("DATABASE_URL=sqlite+aiosqlite:///tmp/rotation-home.sqlite\n")
    captured = {}

    async def fake_rotate(old_key: str, new_key: str):  # noqa: ARG001
        captured["database_url"] = os.environ.get("DATABASE_URL")
        captured["dataclaw_home"] = os.environ.get("DATACLAW_HOME")
        return 0, 0

    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "ENV_PATH", env_path)
    monkeypatch.setattr("app.cli._read_pid", lambda: None)
    monkeypatch.setattr("app.cli._rotate_master_key", fake_rotate)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATACLAW_HOME", raising=False)
    monkeypatch.setenv("DATACLAW_OLD_MASTER_KEY", "old")
    monkeypatch.setenv("DATACLAW_NEW_MASTER_KEY", "new")

    result = cli.main(["rotate-master-key"])

    assert result == 0
    assert captured["database_url"] == "sqlite+aiosqlite:///tmp/rotation-home.sqlite"
    assert captured["dataclaw_home"] == str(tmp_path)


def test_rotate_master_key_rejects_running_daemon(monkeypatch) -> None:
    from app.cli import cmd_rotate_master_key

    called = False

    async def fake_rotate(old_key: str, new_key: str):  # noqa: ARG001
        nonlocal called
        called = True
        return 0, 0

    monkeypatch.setattr("app.cli._read_pid", lambda: 123)
    monkeypatch.setattr("app.cli._process_alive", lambda pid: True)
    monkeypatch.setattr("app.cli._rotate_master_key", fake_rotate)
    monkeypatch.setenv("DATACLAW_OLD_MASTER_KEY", "old")
    monkeypatch.setenv("DATACLAW_NEW_MASTER_KEY", "new")

    result = cmd_rotate_master_key(SimpleNamespace())

    assert result == 1
    assert called is False


def test_rotate_master_key_rejects_default_new_key(monkeypatch) -> None:
    from app.cli import cmd_rotate_master_key

    called = False

    async def fake_rotate(old_key: str, new_key: str):  # noqa: ARG001
        nonlocal called
        called = True
        return 0, 0

    monkeypatch.setattr("app.cli._rotate_master_key", fake_rotate)
    monkeypatch.setattr("app.cli._read_pid", lambda: None)
    monkeypatch.setenv("DATACLAW_OLD_MASTER_KEY", "old")
    monkeypatch.setenv("DATACLAW_NEW_MASTER_KEY", "change-me-please")

    result = cmd_rotate_master_key(SimpleNamespace())

    assert result == 1
    assert called is False
