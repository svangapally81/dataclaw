from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ACME_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ACME_ROOT.parents[2] / "backend"
if str(ACME_ROOT) not in sys.path:
    sys.path.insert(0, str(ACME_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def require_acme_live() -> None:
    if os.getenv("RUN_ACME_E2E") != "1":
        pytest.skip("Set RUN_ACME_E2E=1 after make acme-seed to run live Acme E2E tests.")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for Acme chat/retrieval scenarios.")


@pytest_asyncio.fixture
async def acme_client(tmp_path: Path):
    require_acme_live()
    if base_url := os.getenv("DATACLAW_API_URL"):
        async with AsyncClient(base_url=base_url.rstrip("/"), timeout=180) as client:
            await login(client)
            yield client
        return

    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'app.sqlite'}")
    os.environ.setdefault("DEMO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'demo.sqlite'}")
    os.environ.setdefault("DATACLAW_HOME", str(tmp_path / "home"))
    os.environ.setdefault("WIKI_ROOT", str(tmp_path / "wiki"))
    os.environ.setdefault("MASTER_KEY", "test-master-key-please-change")
    os.environ.setdefault("SESSION_SECRET", "test-session-secret-please-change")
    os.environ.setdefault("DATACLAW_TEST_AUTO_CREATE_SCHEMA", "true")
    os.environ.setdefault("DATACLAW_BCRYPT_ROUNDS", "4")

    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.db.session as session_module

    importlib.reload(session_module)
    from app import main as main_module

    importlib.reload(main_module)
    transport = ASGITransport(app=main_module.app)
    async with main_module.app.router.lifespan_context(main_module.app):
        async with AsyncClient(transport=transport, base_url="http://test", timeout=180) as client:
            await login(client)
            yield client


async def login(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        json={"email": "admin@dataclaw.local", "password": "dataclaw-local-admin"},
    )
    response.raise_for_status()
