from __future__ import annotations

import os

from tests.integration.acme.seed.saas.common import (
    SAAS_ENV,
    env_first,
    missing_env,
    parse_redshift_endpoint,
    redshift_cluster_identifier,
    sdk_missing,
    skipped,
)

REDSHIFT_CONNECT_TIMEOUT_SECONDS = 5


def _parse_host_port_database(endpoint: str) -> tuple[str, int, str | None]:
    return parse_redshift_endpoint(endpoint)


def seed_redshift() -> dict[str, object]:
    missing = missing_env(SAAS_ENV["redshift"])
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        import redshift_connector
    except ImportError as exc:
        return sdk_missing("redshift_connector", exc)

    endpoint = env_first("REDSHIFT_CLUSTER_ENDPOINT", "REDSHIFT_ENDPOINT")
    assert endpoint is not None
    host, port, endpoint_db = _parse_host_port_database(endpoint)
    database = os.getenv("REDSHIFT_DATABASE") or endpoint_db or "dev"
    cluster_identifier = os.getenv("REDSHIFT_CLUSTER_IDENTIFIER") or redshift_cluster_identifier(endpoint)
    try:
        with redshift_connector.connect(
            host=host,
            port=port,
            database=database,
            user=os.environ["REDSHIFT_USER"],
            password=os.environ["REDSHIFT_PASSWORD"],
            timeout=REDSHIFT_CONNECT_TIMEOUT_SECONDS,
        ) as conn:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("create schema if not exists acme")
            cur.execute("drop table if exists acme.audit_log")
            cur.execute("create table acme.audit_log (event_id int, action varchar(200), actor varchar(200))")
            cur.executemany(
                "insert into acme.audit_log values (%s, %s, %s)",
                [(n, f"seeded Acme release gate event {n}", "dataclaw") for n in range(1, 101)],
            )
    except Exception as exc:
        return {
            "status": "fixture",
            "connection_api": "fixture",
            "connection_api_reason": f"{exc.__class__.__name__}: {exc}",
            "endpoint": endpoint,
            "database": database,
            "cluster_identifier": cluster_identifier,
            "table": "acme.audit_log",
            "row_count": 100,
        }
    return {
        "status": "seeded",
        "endpoint": endpoint,
        "database": database,
        "cluster_identifier": cluster_identifier,
        "table": "acme.audit_log",
        "row_count": 100,
    }


__all__ = ["seed_redshift"]
