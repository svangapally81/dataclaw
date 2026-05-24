from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any


def _prefect_base_url() -> str:
    return os.getenv("ACME_PREFECT_API_URL", "http://127.0.0.1:18082/api").rstrip("/")


def _request(method: str, path: str, payload: Any | None = None, *, ok_statuses: tuple[int, ...] = (200, 201)) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{_prefect_base_url()}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            if response.status not in ok_statuses:
                raise RuntimeError(f"Prefect returned HTTP {response.status}: {body}")
            return json.loads(body) if body and body != "null" else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in ok_statuses:
            return json.loads(body) if body and body != "null" else None
        raise RuntimeError(f"Prefect returned HTTP {exc.code}: {body}") from exc


def _get_flow(name: str) -> dict[str, Any] | None:
    try:
        return _request("GET", f"/flows/name/{urllib.parse.quote(name, safe='')}")
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def _get_deployment(flow_name: str, deployment_name: str) -> dict[str, Any] | None:
    try:
        return _request(
            "GET",
            f"/deployments/name/{urllib.parse.quote(flow_name, safe='')}/{urllib.parse.quote(deployment_name, safe='')}",
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def _get_task_run(task_run_id: str) -> dict[str, Any] | None:
    try:
        return _request("GET", f"/task_runs/{task_run_id}")
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def _flow_run_logs_exist(flow_run_id: str) -> bool:
    payload = _request(
        "POST",
        "/logs/filter",
        {"logs": {"flow_run_id": {"any_": [flow_run_id]}}, "limit": 1, "sort": "TIMESTAMP_DESC"},
    )
    return bool(payload)


def seed_prefect() -> dict[str, Any]:
    try:
        return _seed_prefect_live()
    except RuntimeError as exc:
        if "HTTP 503" not in str(exc):
            raise
        return _fixture_prefect_manifest()


def _seed_prefect_live() -> dict[str, Any]:
    flow_name = "acme_revenue_recalc"
    deployment_name = "default"
    flow = _get_flow(flow_name) or _request("POST", "/flows/", {"name": flow_name, "tags": ["acme"]})
    flow_id = str(flow["id"])
    deployment = _get_deployment(flow_name, deployment_name) or _request(
        "POST",
        "/deployments/",
        {
            "name": deployment_name,
            "flow_id": flow_id,
            "entrypoint": "flows/acme.py:acme_revenue_recalc",
            "parameters": {},
            "tags": ["acme"],
            "description": "Acme revenue recalculation fixture.",
        },
    )
    deployment_id = str(deployment["id"])
    flow_run = _request(
        "POST",
        "/flow_runs/",
        {
            "name": "acme-revenue-recalc-fixture",
            "flow_id": flow_id,
            "deployment_id": deployment_id,
            "idempotency_key": "acme-revenue-recalc-fixture",
            "state": {"type": "COMPLETED", "name": "Completed"},
        },
    )
    flow_run_id = str(flow_run["id"])
    task_run_id = "00000000-0000-4000-8000-000000000101"
    task_run = _get_task_run(task_run_id) or _request(
        "POST",
        "/task_runs/",
        {
            "id": task_run_id,
            "name": "load_revenue_daily",
            "flow_run_id": flow_run_id,
            "task_key": "load_revenue_daily",
            "dynamic_key": "0",
            "state": {"type": "COMPLETED", "name": "Completed"},
        },
    )
    task_run_id = str(task_run["id"])
    if not _flow_run_logs_exist(flow_run_id):
        now = datetime.now(UTC).isoformat()
        _request(
            "POST",
            "/logs/",
            [
                {
                    "name": "acme.prefect",
                    "level": 20,
                    "message": "Acme revenue recalc completed",
                    "timestamp": now,
                    "flow_run_id": flow_run_id,
                },
                {
                    "name": "acme.prefect",
                    "level": 20,
                    "message": "Loaded revenue_daily",
                    "timestamp": now,
                    "flow_run_id": flow_run_id,
                    "task_run_id": task_run_id,
                },
            ],
        )
    return {
        "api_url": "http://127.0.0.1:18082/api",
        "flow": flow_name,
        "flow_id": flow_id,
        "deployment_id": deployment_id,
        "deployment_name": f"{flow_name}/{deployment_name}",
        "run_id": flow_run_id,
        "task_run_id": task_run_id,
    }


def _fixture_prefect_manifest() -> dict[str, Any]:
    return {
        "api_url": "http://127.0.0.1:18082/api",
        "flow": "acme_revenue_recalc",
        "flow_id": "00000000-0000-4000-8000-000000000201",
        "deployment_id": "00000000-0000-4000-8000-000000000202",
        "deployment_name": "acme_revenue_recalc/default",
        "run_id": "00000000-0000-4000-8000-000000000203",
        "task_run_id": "00000000-0000-4000-8000-000000000101",
        "fixture": True,
        "fixture_reason": "Prefect API returned HTTP 503 during Acme container seeding.",
    }


__all__ = ["seed_prefect"]
