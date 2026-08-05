from __future__ import annotations

import os
from typing import Any

from tests.integration.acme.seed.saas.common import (
    DEFAULT_SNOWFLAKE_WAREHOUSE,
    SAAS_ENV,
    missing_env,
    normalize_snowflake_account,
    sdk_missing,
    skipped,
)


def seed_snowflake() -> dict[str, Any]:
    missing = missing_env(SAAS_ENV["snowflake"])
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        import snowflake.connector
    except ImportError as exc:
        return sdk_missing("snowflake-connector-python", exc)

    database = os.getenv("SNOWFLAKE_DATABASE") or "ACME"
    schema = os.getenv("SNOWFLAKE_SCHEMA") or "MARTS"
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE") or DEFAULT_SNOWFLAKE_WAREHOUSE
    account = normalize_snowflake_account(os.environ["SNOWFLAKE_ACCOUNT"])
    kwargs: dict[str, Any] = {
        "account": account,
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": warehouse,
    }
    if os.getenv("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    if os.getenv("SNOWFLAKE_PRIVATE_KEY"):
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(
            os.environ["SNOWFLAKE_PRIVATE_KEY"].encode(),
            password=os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "").encode() or None,
        )
        kwargs["private_key"] = key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    with snowflake.connector.connect(**{k: v for k, v in kwargs.items() if v}) as conn:
        cur = conn.cursor()
        cur.execute(f"create database if not exists {database}")
        cur.execute(f"create schema if not exists {database}.{schema}")
        cur.execute(f"use database {database}")
        cur.execute(f"use schema {schema}")
        cur.execute(f"create stage if not exists {database}.{schema}.ACME_COVERAGE_STAGE")
        cur.execute(
            f"""
            create or replace table {database}.{schema}.CHURN_EVENTS as
            select
              seq4() + 1 as customer_id,
              case mod(seq4(), 3) when 0 then 'downgrade' when 1 then 'cancellation' else 'inactive_30d' end as event_type,
              dateadd(day, -mod(seq4(), 60), current_timestamp()) as event_at
            from table(generator(rowcount => 300))
            """
        )
        cur.execute(
            f"""
            create or replace table {database}.{schema}.REVENUE_DAILY as
            select
              dateadd(day, -seq4(), current_date()) as day,
              case mod(seq4(), 3) when 0 then 'enterprise' when 1 then 'growth' else 'self_serve' end as segment,
              100000 + mod(seq4() * 1700, 250000) as arr_usd
            from table(generator(rowcount => 90))
            """
        )
    return {
        "status": "seeded",
        "account": account,
        "warehouse": warehouse,
        "database": database,
        "schema": schema,
        "tables": ["CHURN_EVENTS", "REVENUE_DAILY"],
        "stage": "ACME_COVERAGE_STAGE",
    }


__all__ = ["seed_snowflake"]
