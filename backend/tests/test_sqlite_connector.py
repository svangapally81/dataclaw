from pathlib import Path

import pytest

from app.services.connectors.adapters import SQLiteAdapter, seed_sqlite_demo


@pytest.fixture
def demo_path(tmp_path: Path) -> Path:
    path = tmp_path / "demo.sqlite"
    seed_sqlite_demo(path)
    return path


@pytest.mark.asyncio
async def test_sqlite_seed_creates_demo_rows(demo_path: Path) -> None:
    import sqlite3

    with sqlite3.connect(demo_path) as conn:
        cursor = conn.cursor()
        cursor.execute("select count(*) from customers")
        assert cursor.fetchone()[0] == 3
        cursor.execute("select count(*) from orders")
        assert cursor.fetchone()[0] == 4
        cursor.execute("select count(*) from products")
        assert cursor.fetchone()[0] == 3
        cursor.execute("select count(*) from test_summary")
        assert cursor.fetchone()[0] == 1


@pytest.mark.asyncio
async def test_sqlite_test_returns_ok(demo_path: Path) -> None:
    adapter = SQLiteAdapter()
    result = await adapter.test({"database_path": str(demo_path)})
    assert result.status == "ok"
    assert result.mode == "real"
    assert "customers" in result.details["tables"]


@pytest.mark.asyncio
async def test_sqlite_sync_returns_table_metadata(demo_path: Path) -> None:
    adapter = SQLiteAdapter()
    result = await adapter.sync({"database_path": str(demo_path)})
    assert result["mode"] == "real"
    assert result["objects_synced"] == 4
    by_name = {table["name"]: table for table in result["tables"]}
    assert by_name["orders"]["row_count"] == 4
    assert by_name["test_summary"]["row_count"] == 1
    assert any(col["name"] == "net_revenue" for col in by_name["orders"]["columns"])


@pytest.mark.asyncio
async def test_sqlite_default_path_seeds_built_in_demo() -> None:
    adapter = SQLiteAdapter()
    result = await adapter.test({})
    assert result.status == "ok"
    assert "/tmp/dataclaw_demo.sqlite" in result.details["database_path"]
