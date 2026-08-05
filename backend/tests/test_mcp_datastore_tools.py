from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.base import Base
from app.models.domain import Agent, Workspace
from app.services.mcp_executor import (
    _sql_for_write_tool,
    _sqlite_explain_query,
    _sqlite_query_select,
    _sqlite_write,
)


@pytest.fixture
async def sqlite_datastore_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="Test")
        session.add(workspace)
        await session.flush()
        agent = Agent(workspace_id=workspace.id, name="chat", display_name="Chat", system_prompt="Use MCP tools.")
        session.add(agent)
        await session.commit()
        yield session, engine, agent
    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_shared_datastore_mutation_tools(sqlite_datastore_session) -> None:
    session, engine, agent = sqlite_datastore_session

    created = await _sqlite_write(
        session=session,
        engine=engine,
        agent=agent,
        tool_name="write_create_table",
        arguments={"table": "ds_accounts", "columns": [{"name": "id", "type": "integer"}, {"name": "status", "type": "text"}]},
        user_email="admin@dataclaw.local",
    )
    inserted = await _sqlite_write(
        session=session,
        engine=engine,
        agent=agent,
        tool_name="write_insert_rows",
        arguments={"table": "ds_accounts", "rows": [{"id": 1, "status": "new"}, {"id": 2, "status": "new"}]},
        user_email="admin@dataclaw.local",
    )
    updated = await _sqlite_write(
        session=session,
        engine=engine,
        agent=agent,
        tool_name="write_update_rows",
        arguments={"table": "ds_accounts", "set": {"status": "active"}, "where": "id = 1"},
        user_email="admin@dataclaw.local",
    )
    indexed = await _sqlite_write(
        session=session,
        engine=engine,
        agent=agent,
        tool_name="write_create_index",
        arguments={"table": "ds_accounts", "columns": ["status"]},
        user_email="admin@dataclaw.local",
    )
    explained = await _sqlite_explain_query(engine, {"sql": "select * from ds_accounts where status = 'active'"})
    rows = await _sqlite_query_select(engine, {"sql": "select id, status from ds_accounts order by id"})
    deleted = await _sqlite_write(
        session=session,
        engine=engine,
        agent=agent,
        tool_name="write_delete_rows",
        arguments={"table": "ds_accounts", "where": "status = 'new'"},
        user_email="admin@dataclaw.local",
    )

    assert created["status"] == "executed"
    assert inserted["affected_rows"] == 2
    assert updated["affected_rows"] == 1
    assert indexed["status"] == "executed"
    assert explained["plan"]
    assert rows["rows"] == [{"id": 1, "status": "active"}, {"id": 2, "status": "new"}]
    assert deleted["affected_rows"] == 1


def test_sql_server_create_table_uses_supported_dialect_sql() -> None:
    sql = _sql_for_write_tool(
        "write_create_table",
        {"table": "phase_h_sql_server_summary", "columns": [{"name": "month", "type": "text"}]},
        "sql_server",
    )

    assert sql == (
        "if object_id(N'dbo.phase_h_sql_server_summary', N'U') is null "
        "create table [dbo].[phase_h_sql_server_summary] ([month] NVARCHAR(MAX))"
    )
    assert "if not exists" not in sql.lower()


@pytest.mark.asyncio
async def test_sqlite_update_and_delete_require_where(sqlite_datastore_session) -> None:
    session, engine, agent = sqlite_datastore_session

    with pytest.raises(Exception, match="where is required"):
        await _sqlite_write(
            session=session,
            engine=engine,
            agent=agent,
            tool_name="write_update_rows",
            arguments={"table": "ds_accounts", "set": {"status": "active"}},
            user_email="admin@dataclaw.local",
        )

    with pytest.raises(Exception, match="where is required"):
        await _sqlite_write(
            session=session,
            engine=engine,
            agent=agent,
            tool_name="write_delete_rows",
            arguments={"table": "ds_accounts"},
            user_email="admin@dataclaw.local",
        )
