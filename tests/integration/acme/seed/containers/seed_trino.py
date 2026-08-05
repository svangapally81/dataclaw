from __future__ import annotations

import time
from typing import Any


def _execute(cursor, sql: str) -> None:
    deadline = time.time() + 90
    while True:
        try:
            cursor.execute(sql)
            cursor.fetchall()
            return
        except Exception as exc:
            if "SERVER_STARTING_UP" not in str(exc) or time.time() >= deadline:
                raise
            time.sleep(3)


def seed_trino() -> dict[str, Any]:
    import trino

    conn = trino.dbapi.connect(host="127.0.0.1", port=18088, user="dataclaw", catalog="memory", schema="default")
    try:
        cursor = conn.cursor()
        _execute(cursor, "create schema if not exists default")
        _execute(cursor, "drop table if exists default.acme_orders")
        _execute(
            cursor,
            """
            create table default.acme_orders as
            select * from (
              values
                (1, 101, 'enterprise', 1200.50, current_timestamp),
                (2, 102, 'growth', 250.00, current_timestamp),
                (3, 103, 'self_serve', 75.00, current_timestamp)
            ) as t(order_id, customer_id, segment, amount_usd, ordered_at)
            """,
        )
    finally:
        conn.close()
    return {"catalog": "memory", "schema": "default", "tables": ["acme_orders"], "row_counts": {"acme_orders": 3}}


__all__ = ["seed_trino"]
