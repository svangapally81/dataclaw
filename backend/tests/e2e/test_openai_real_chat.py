from __future__ import annotations

import importlib
import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_real_openai_chat_path_uses_configured_key(monkeypatch, tmp_path) -> None:
    if os.getenv("RUN_OPENAI_E2E") != "1":
        pytest.skip("Set RUN_OPENAI_E2E=1 and OPENAI_API_KEY to run the real OpenAI chat E2E.")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for the real OpenAI chat E2E.")

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    monkeypatch.setenv("DEMO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'demo.sqlite'}")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("MASTER_KEY", "test-master-key-please-change")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-please-change")

    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.db.session as session_module

    importlib.reload(session_module)
    from app import main as main_module

    importlib.reload(main_module)

    transport = ASGITransport(app=main_module.app)
    async with main_module.app.router.lifespan_context(main_module.app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            login = await ac.post(
                "/auth/login",
                json={"email": "admin@dataclaw.local", "password": "dataclaw-local-admin"},
            )
            assert login.status_code == 200
            assert (await ac.post("/connectors/sqlite/test", json={"credentials": {}})).status_code == 200
            assert (await ac.post("/connectors/sqlite/sync")).status_code == 200

            response = await ac.post(
                "/ide/chat",
                json={"question": "Reply exactly DATACLAW_OPENAI_E2E_OK. Do not call tools."},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["provider"] == "openai"
            assert body["llm_status"] in {"no_tool_call", "completed"}
            assert "DATACLAW_OPENAI_E2E_OK" in body["answer"]
