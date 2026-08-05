from __future__ import annotations

# ruff: noqa: I001

import os
from typing import Any

import httpx

from tests.integration.acme.seed.saas.common import SAAS_ENV, env_first, missing_env, sdk_missing, skipped


def _connector_status_events(connector: dict[str, Any]) -> list[dict[str, Any]]:
    status = connector.get("status") if isinstance(connector.get("status"), dict) else {}
    events: list[dict[str, Any]] = []
    for key in ("tasks", "warnings"):
        values = status.get(key)
        if isinstance(values, list):
            for value in values:
                events.append({"type": key.removesuffix("s"), "detail": value})
    for key in ("succeeded_at", "failed_at", "last_sync", "sync_state"):
        value = connector.get(key) or status.get(key)
        if value:
            events.append({"type": key, "detail": value})
    return events


def _connector_score(connector: dict[str, Any]) -> tuple[int, str]:
    schema = str(connector.get("schema") or connector.get("name") or "").lower()
    service = str(connector.get("service") or "").lower()
    if connector.get("id") == env_first("FIVETRAN_CONNECTOR_ID", "ACME_FIVETRAN_CONNECTOR_ID"):
        return (0, schema)
    if schema == "postgres_to_bq":
        return (1, schema)
    if "postgres" in schema and ("bq" in schema or "bigquery" in schema):
        return (2, schema)
    if service == "postgres":
        return (3, schema)
    if _connector_status_events(connector):
        return (4, schema)
    return (5, schema)


def _choose_connector(connectors: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not connectors:
        return None
    return sorted(connectors, key=_connector_score)[0]


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        items = data.get("items") or data.get("connections") or data.get("connectors")
        return items if isinstance(items, list) else []
    return data if isinstance(data, list) else []


def _get_json(client: Any, *paths: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for path in paths:
        response = client.get(path)
        if response.status_code == 404:
            last_error = httpx.HTTPStatusError("not found", request=response.request, response=response)
            continue
        response.raise_for_status()
        return response.json()
    if last_error:
        raise last_error
    return {}


def _list_connections(client: Any) -> list[dict[str, Any]]:
    try:
        return _items(_get_json(client, "/connections", "/connectors"))
    except httpx.HTTPStatusError:
        groups = _items(_get_json(client, "/groups"))
        connections: list[dict[str, Any]] = []
        for group in groups:
            group_id = group.get("id")
            if not group_id:
                continue
            try:
                connections.extend(_items(_get_json(client, f"/groups/{group_id}/connections", f"/groups/{group_id}/connectors")))
            except httpx.HTTPStatusError:
                continue
        return connections


def _get_connection(client: Any, connection_id: str) -> dict[str, Any]:
    payload = _get_json(client, f"/connections/{connection_id}", f"/connectors/{connection_id}")
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def seed_fivetran() -> dict[str, Any]:
    missing = missing_env(SAAS_ENV["fivetran"])
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        import httpx
    except ImportError as exc:
        return sdk_missing("httpx", exc)

    auth = (os.environ["FIVETRAN_API_KEY"], os.environ["FIVETRAN_API_SECRET"])
    with httpx.Client(base_url="https://api.fivetran.com/v1", timeout=60) as client:
        client.auth = auth
        connectors = _list_connections(client)
        try:
            destinations = _items(_get_json(client, "/destinations", "/groups"))
        except httpx.HTTPStatusError:
            destinations = []
        explicit_connector_id = env_first("FIVETRAN_CONNECTOR_ID", "ACME_FIVETRAN_CONNECTOR_ID")
        if explicit_connector_id:
            match = _get_connection(client, explicit_connector_id)
        else:
            match = _choose_connector(connectors)
        if match is None:
            return skipped("Fivetran API reachable but no reusable sandbox connector exists")
        sync_history = _connector_status_events(match)
        if not sync_history:
            return skipped(
                f"Fivetran connector {match.get('id')} has no sync status/history evidence; "
                "set FIVETRAN_CONNECTOR_ID to a connector with prior sync activity."
            )
        schema_response = client.get(f"/connections/{match['id']}/schemas")
        if schema_response.status_code == 404:
            schema_response = client.get(f"/connectors/{match['id']}/schemas")
        schema_status = schema_response.status_code
        schema_payload = schema_response.json().get("data", {}) if schema_response.status_code < 400 else {}
    return {
        "status": "seeded",
        "connector_id": match.get("id"),
        "connector_name": match.get("schema") or "postgres_to_bq",
        "destination_id": match.get("group_id") or (destinations[0].get("id") if destinations else None),
        "service": match.get("service"),
        "sync_state": match.get("status", {}).get("sync_state"),
        "sync_history": sync_history,
        "schema_status": schema_status,
        "schema_names": sorted((schema_payload.get("schemas") or {}).keys()),
    }


__all__ = ["seed_fivetran"]
