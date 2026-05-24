import pytest

from app.services.sql_safety import UnsafeSqlError, validate_read_only_sql


def test_select_gets_limit() -> None:
    assert validate_read_only_sql("select * from orders") == "select * from orders limit 100"


def test_cte_allowed() -> None:
    sql = validate_read_only_sql("with x as (select * from orders) select * from x", limit=25)
    assert sql.endswith("limit 25")


def test_comment_markers_inside_string_literals_allowed() -> None:
    sql = validate_read_only_sql(
        "select '-- not a comment' as dash, '/* not a block */' as block, \"*/\" as quoted"
    )
    assert "'-- not a comment'" in sql
    assert "'/* not a block */'" in sql
    assert sql.endswith("limit 100")


def test_trailing_semicolon_allowed() -> None:
    assert validate_read_only_sql("select * from orders;") == "select * from orders limit 100"


def test_backslash_does_not_escape_single_quote() -> None:
    with pytest.raises(UnsafeSqlError):
        validate_read_only_sql("select 'broken\\'; select 2; --'")


@pytest.mark.parametrize(
    "sql",
    [
        "delete from orders",
        "select * from orders; select * from customers",
        "select * from orders -- nope",
        "select * from orders /* nope */",
        "drop table orders",
        "update orders set net_revenue = 0",
    ],
)
def test_unsafe_sql_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        validate_read_only_sql(sql)
