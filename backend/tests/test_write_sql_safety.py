from __future__ import annotations

import pytest

from app.services.sql_safety import UnsafeSqlError, validate_write_sql


def test_write_sql_allows_bounded_update() -> None:
    decision = validate_write_sql("update customers set segment = 'vip' where id = 1")
    assert decision.action == "allow"
    assert decision.statement_type == "UPDATE"
    assert decision.target == "customers"


def test_write_sql_requires_approval_for_drop_table() -> None:
    decision = validate_write_sql("drop table test_summary")
    assert decision.action == "requires_approval"
    assert decision.statement_type == "DROP_TABLE"
    assert decision.target == "test_summary"


def test_write_sql_allows_sql_server_idempotent_create_table() -> None:
    decision = validate_write_sql(
        "if object_id(N'dbo.phase_h_sql_server_summary', N'U') is null "
        "create table [dbo].[phase_h_sql_server_summary] ([month] NVARCHAR(MAX))"
    )
    assert decision.action == "allow"
    assert decision.statement_type == "CREATE_TABLE"
    assert decision.target == "dbo.phase_h_sql_server_summary"


def test_write_sql_blocks_multi_statement() -> None:
    with pytest.raises(UnsafeSqlError):
        validate_write_sql("insert into a values (1); insert into b values (2)")
