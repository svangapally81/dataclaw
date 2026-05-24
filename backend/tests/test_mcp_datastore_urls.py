from __future__ import annotations

import pytest

from app.services.mcp_executor import McpExecutionError, _sqlalchemy_url_for_datastore


def test_redshift_url_uses_postgres_protocol_and_default_port() -> None:
    url = _sqlalchemy_url_for_datastore(
        "redshift",
        {
            "cluster_endpoint": "redshift-cluster.example.us-east-1.redshift.amazonaws.com",
            "database": "analytics",
            "user": "data user",
            "password": "p@ss word",
        },
    )

    assert url == (
        "postgresql+psycopg://data+user:p%40ss+word@"
        "redshift-cluster.example.us-east-1.redshift.amazonaws.com:5439/analytics"
    )


def test_redshift_url_accepts_explicit_database_url() -> None:
    url = _sqlalchemy_url_for_datastore("redshift", {"database_url": "postgresql+psycopg://u:p@h:5439/d"})

    assert url == "postgresql+psycopg://u:p@h:5439/d"


def test_redshift_url_requires_credentials() -> None:
    with pytest.raises(McpExecutionError, match="Redshift requires"):
        _sqlalchemy_url_for_datastore("redshift", {"cluster_endpoint": "host"})


def test_trino_url_uses_trino_protocol_and_defaults() -> None:
    url = _sqlalchemy_url_for_datastore(
        "trino",
        {
            "host": "127.0.0.1",
            "catalog": "memory",
            "schema": "core",
            "user": "data user",
        },
    )

    assert url == "trino://data+user@127.0.0.1:8080/memory/core"


def test_trino_url_requires_credentials() -> None:
    with pytest.raises(McpExecutionError, match="Trino requires"):
        _sqlalchemy_url_for_datastore("trino", {"host": "127.0.0.1"})
