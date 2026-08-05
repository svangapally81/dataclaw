from __future__ import annotations

import os
import sys
import types

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Connector, Workspace
from app.services.mcp_executor import McpExecutionError, _snowflake_tool


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        FakeSnowflakeConnector.queries.append((sql, params))
        self.sql = sql.lower()
        self.rowcount = 1

    def fetchall(self):
        if self.sql.startswith("show warehouses"):
            return [{"name": "COMPUTE_WH"}]
        if self.sql.startswith("show pipes"):
            return [{"name": "LOAD_CUSTOMERS"}]
        if self.sql.startswith("show streams"):
            return [{"name": "CUSTOMERS_STREAM"}]
        if self.sql.startswith("show tasks"):
            return [{"name": "REFRESH_CUSTOMERS"}]
        if "query_history" in self.sql:
            return [{"QUERY_ID": "q1"}]
        if "warehouse_metering_history" in self.sql:
            return [{"WAREHOUSE_NAME": "COMPUTE_WH", "CREDITS_USED": 1.25}]
        return []


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return FakeCursor()


class FakeSnowflakeConnector:
    DictCursor = object()
    queries: list[tuple[str, object]] = []

    @staticmethod
    def connect(**kwargs):
        FakeSnowflakeConnector.last_connect = kwargs
        return FakeConnection()


@pytest.fixture(scope="module")
async def snowflake_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("snowflake")
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    get_settings.cache_clear()
    FakeSnowflakeConnector.queries = []
    module_names = ["snowflake", "snowflake.connector"]
    original_modules = {name: sys.modules.get(name) for name in module_names}
    snowflake_module = types.ModuleType("snowflake")
    connector_module = types.ModuleType("snowflake.connector")
    connector_module.connect = FakeSnowflakeConnector.connect
    connector_module.DictCursor = FakeSnowflakeConnector.DictCursor
    snowflake_module.connector = connector_module
    sys.modules["snowflake"] = snowflake_module
    sys.modules["snowflake.connector"] = connector_module

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="Test")
        session.add(workspace)
        await session.flush()
        session.add(
            Connector(
                workspace_id=workspace.id,
                slug="snowflake",
                category="data_store",
                display_name="Snowflake",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {
                        "account": "example",
                        "warehouse": "COMPUTE_WH",
                        "database": "ANALYTICS",
                        "schema": "PUBLIC",
                        "user": "DATA",
                        "password": "secret",
                    },
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()
    for name, module in original_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


@pytest.mark.asyncio
async def test_snowflake_matrix_reads_and_writes(snowflake_session: AsyncSession) -> None:
    session = snowflake_session

    warehouses = await _snowflake_tool(session, "read_list_warehouses", {}, "agent-1")
    pipes = await _snowflake_tool(session, "read_list_pipes", {}, "agent-1")
    streams = await _snowflake_tool(session, "read_list_streams", {}, "agent-1")
    tasks = await _snowflake_tool(session, "read_list_tasks", {}, "agent-1")
    history = await _snowflake_tool(session, "read_query_history", {"since": "2026-05-01T00:00:00Z"}, "agent-1")
    usage = await _snowflake_tool(session, "read_get_credit_usage", {"since": "2026-05-01T00:00:00Z"}, "agent-1")
    resumed = await _snowflake_tool(session, "write_resume_warehouse", {"name": "COMPUTE_WH"}, "agent-1")
    suspended = await _snowflake_tool(session, "write_suspend_warehouse", {"name": "COMPUTE_WH"}, "agent-1")
    pipe = await _snowflake_tool(session, "write_create_pipe", {"name": "LOAD_CUSTOMERS", "table": "CUSTOMERS", "stage": "CUSTOMER_STAGE", "file_format": "JSON"}, "agent-1")
    task = await _snowflake_tool(session, "write_create_task", {"name": "REFRESH_CUSTOMERS", "sql": "select * from PUBLIC.CUSTOMERS"}, "agent-1")

    assert warehouses["warehouses"] == [{"name": "COMPUTE_WH"}]
    assert pipes["pipes"] == [{"name": "LOAD_CUSTOMERS"}]
    assert streams["streams"] == [{"name": "CUSTOMERS_STREAM"}]
    assert tasks["tasks"] == [{"name": "REFRESH_CUSTOMERS"}]
    assert history["queries"] == [{"QUERY_ID": "q1"}]
    assert usage["usage"][0]["CREDITS_USED"] == 1.25
    assert resumed["status"] == "executed"
    assert suspended["status"] == "executed"
    assert 'create pipe if not exists "PUBLIC"."LOAD_CUSTOMERS"' in pipe["sql"]
    assert 'create task if not exists "PUBLIC"."REFRESH_CUSTOMERS"' in task["sql"]
    assert any(query == 'alter warehouse "COMPUTE_WH" resume' for query, _ in FakeSnowflakeConnector.queries)
    assert any(query == 'alter warehouse "COMPUTE_WH" suspend' for query, _ in FakeSnowflakeConnector.queries)


@pytest.mark.asyncio
async def test_snowflake_query_history_rejects_invalid_since(snowflake_session: AsyncSession) -> None:
    with pytest.raises(McpExecutionError, match="ISO-8601"):
        await _snowflake_tool(snowflake_session, "read_query_history", {"since": "not a timestamp"}, "agent-1")
