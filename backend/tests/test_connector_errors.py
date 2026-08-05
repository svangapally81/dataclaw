from __future__ import annotations

import httpx

from app.services.connectors.adapters import (
    AdapterAuthError,
    AdapterRateLimitError,
    AdapterReachabilityError,
    clean_connector_error,
)


def test_http_401_maps_to_clean_auth_error() -> None:
    request = httpx.Request("GET", "https://example.test/health")
    response = httpx.Response(401, request=request, text="secret stack-shaped body")

    error = clean_connector_error("postgres", httpx.HTTPStatusError("boom", request=request, response=response))

    assert isinstance(error, AdapterAuthError)
    assert error.clean_message() == "Authentication failed: PostgreSQL rejected credentials."


def test_http_429_maps_to_rate_limit_error() -> None:
    request = httpx.Request("GET", "https://example.test/health")
    response = httpx.Response(429, request=request)

    error = clean_connector_error("notion", httpx.HTTPStatusError("boom", request=request, response=response))

    assert isinstance(error, AdapterRateLimitError)
    assert error.clean_message() == "Connector rate limited: Notion rate limit exceeded."


def test_timeout_maps_to_reachability_error() -> None:
    error = clean_connector_error("airflow", httpx.TimeoutException("timed out"))

    assert isinstance(error, AdapterReachabilityError)
    assert error.clean_message() == "Connector unreachable: Airflow did not respond before the timeout."
