from __future__ import annotations

import base64
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from tests.integration.acme.seed.saas.common import (
    SAAS_ENV,
    env_first,
    missing_env,
    sdk_missing,
    skipped,
)

NOTEBOOK_PATH = "/Shared/dataclaw/acme/events_refresh"
JOB_NAME = "dataclaw-acme-events-refresh"
SCHEMA_NAME = "silver"


def seed_databricks() -> dict[str, Any]:
    missing = missing_env(SAAS_ENV["databricks"])
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        from databricks import sql
    except ImportError as exc:
        return sdk_missing("databricks-sql-connector", exc)

    workspace_url = env_first("DATABRICKS_WORKSPACE_URL", "DATABRICKS_HOST")
    assert workspace_url is not None
    host = _databricks_hostname(workspace_url)
    workspace_base = _databricks_workspace_base(workspace_url)
    headers = {"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"}
    with sql.connect(
        server_hostname=host,
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    ) as conn:
        cur = conn.cursor()
        catalog = _writable_catalog(cur)
        table_name = f"{catalog}.{SCHEMA_NAME}.events"
        cur.execute(f"create schema if not exists {catalog}.{SCHEMA_NAME}")
        cur.execute(
            f"""
            create or replace table {table_name} as
            select
              concat('evt-', cast(id + 1 as string)) as event_id,
              cast(1 + ((id * 13) % 1000) as int) as customer_id,
              case id % 4
                when 0 then 'trial_started'
                when 1 then 'order_paid'
                when 2 then 'downgrade'
                else 'feature_adopted'
              end as event_name
            from range(1000)
            """
        )
    job_info = _seed_databricks_job(workspace_base, headers, table_name)
    return {
        "status": "seeded",
        "workspace_url": workspace_url,
        "catalog": catalog,
        "schema": SCHEMA_NAME,
        "table": table_name,
        "row_count": 1000,
        **job_info,
    }


__all__ = ["seed_databricks"]


def _databricks_hostname(value: str) -> str:
    raw = value.strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return parsed.hostname or raw.split("/", 1)[0]


def _databricks_workspace_base(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    return f"{parsed.scheme}://{parsed.netloc}"


def _writable_catalog(cur: Any) -> str:
    preferred = [
        value
        for value in (
            env_first("ACME_DATABRICKS_CATALOG", "DATABRICKS_CATALOG"),
            _current_catalog(cur),
            "hive_metastore",
            "main",
        )
        if value
    ]
    seen: set[str] = set()
    for catalog in preferred:
        if catalog in seen:
            continue
        seen.add(catalog)
        try:
            cur.execute(f"create schema if not exists {catalog}.{SCHEMA_NAME}")
            return catalog
        except Exception:
            continue
    raise RuntimeError("No writable Databricks catalog found for Acme seed.")


def _current_catalog(cur: Any) -> str | None:
    try:
        cur.execute("select current_catalog()")
        row = cur.fetchone()
    except Exception:
        return None
    if isinstance(row, dict):
        value = row.get("current_catalog()") or next(iter(row.values()), None)
    elif isinstance(row, (list, tuple)) and row:
        value = row[0]
    else:
        value = None
    return str(value) if value else None


def _seed_databricks_job(workspace_base: str, headers: dict[str, str], table_name: str) -> dict[str, Any]:
    """Create a tiny reusable notebook job and return real IDs for MCP coverage.

    The Acme catalog exercises Databricks job, run, notebook, and cluster tools.
    The SQL table alone is not enough to produce live fixture IDs, so the seeder
    creates an idempotent notebook job using an ephemeral single-node cluster.
    """
    with httpx.Client(base_url=workspace_base, headers=headers, timeout=60) as client:
        try:
            _import_notebook(client, table_name)
            job_id = _ensure_job(client)
            run_id = _ensure_completed_run(client, job_id)
            cluster_id = env_first("DATABRICKS_CLUSTER_ID", "ACME_DATABRICKS_CLUSTER_ID") or _run_cluster_id(client, run_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {403, 404}:
                raise
            return _fixture_job_info(exc)
    return {
        "workspace_api": "live",
        "notebook_path": NOTEBOOK_PATH,
        "job_name": JOB_NAME,
        "job_id": str(job_id),
        "run_id": str(run_id),
        "cluster_id": str(cluster_id) if cluster_id else "",
    }


def _fixture_job_info(exc: httpx.HTTPStatusError) -> dict[str, Any]:
    return {
        "workspace_api": "fixture",
        "workspace_api_reason": f"{exc.response.status_code} {exc.response.reason_phrase}",
        "notebook_path": NOTEBOOK_PATH,
        "job_name": JOB_NAME,
        "job_id": "fixture-databricks-job",
        "run_id": "fixture-databricks-run",
        "cluster_id": "fixture-databricks-cluster",
    }


def _import_notebook(client: httpx.Client, table_name: str) -> None:
    content = base64.b64encode(
        (
            "# DataClaw Acme events refresh\n"
            'display(spark.sql("""\n'
            "select event_id, customer_id, event_name\n"
            f"from {table_name}\n"
            "limit 10\n"
            '"""))\n'
        ).encode()
    ).decode("ascii")
    response = client.post(
        "/api/2.0/workspace/import",
        json={
            "path": NOTEBOOK_PATH,
            "format": "SOURCE",
            "language": "PYTHON",
            "overwrite": True,
            "content": content,
        },
    )
    response.raise_for_status()


def _ensure_job(client: httpx.Client) -> int:
    explicit = env_first("DATABRICKS_JOB_ID", "ACME_DATABRICKS_JOB_ID")
    if explicit:
        return int(explicit)
    existing = _find_job(client)
    if existing is not None:
        _reset_job(client, existing)
        return existing
    response = client.post("/api/2.1/jobs/create", json=_job_settings(client))
    response.raise_for_status()
    return int(response.json()["job_id"])


def _find_job(client: httpx.Client) -> int | None:
    response = client.get("/api/2.1/jobs/list", params={"limit": 100, "expand_tasks": "true"})
    response.raise_for_status()
    for job in response.json().get("jobs", []):
        if job.get("settings", {}).get("name") == JOB_NAME:
            return int(job["job_id"])
    return None


def _reset_job(client: httpx.Client, job_id: int) -> None:
    response = client.post(
        "/api/2.1/jobs/reset",
        json={"job_id": job_id, "new_settings": _job_settings(client)},
    )
    response.raise_for_status()


def _job_settings(client: httpx.Client) -> dict[str, Any]:
    spark_version = os.getenv("DATABRICKS_SPARK_VERSION") or _default_spark_version(client)
    node_type = os.getenv("DATABRICKS_NODE_TYPE_ID") or _default_node_type(client)
    return {
        "name": JOB_NAME,
        "max_concurrent_runs": 1,
        "tasks": [
            {
                "task_key": "events_refresh",
                "notebook_task": {"notebook_path": NOTEBOOK_PATH},
                "new_cluster": {
                    "spark_version": spark_version,
                    "node_type_id": node_type,
                    "num_workers": 0,
                    "spark_conf": {
                        "spark.databricks.cluster.profile": "singleNode",
                        "spark.master": "local[*]",
                    },
                    "custom_tags": {"ResourceClass": "SingleNode"},
                    "autotermination_minutes": 10,
                },
            }
        ],
    }


def _default_spark_version(client: httpx.Client) -> str:
    response = client.get("/api/2.0/clusters/spark-versions")
    response.raise_for_status()
    versions = response.json().get("versions", [])
    for version in versions:
        key = str(version.get("key") or "")
        name = str(version.get("name") or "")
        if version.get("long_term_support") and not _is_ml_or_gpu_runtime(key, name):
            return key
    for version in versions:
        key = str(version.get("key") or "")
        name = str(version.get("name") or "")
        if key and not _is_ml_or_gpu_runtime(key, name):
            return key
    return "14.3.x-scala2.12"


def _default_node_type(client: httpx.Client) -> str:
    response = client.get("/api/2.0/clusters/list-node-types")
    response.raise_for_status()
    node_types = response.json().get("node_types", [])
    candidates = [
        node
        for node in node_types
        if node.get("node_type_id")
        and not node.get("is_deprecated")
        and not _is_gpu_node(str(node.get("node_type_id") or ""), str(node.get("description") or ""))
    ]
    if not candidates:
        return "i3.xlarge"
    candidates.sort(
        key=lambda node: (
            float(node.get("num_cores") or 9999),
            int(node.get("memory_mb") or 999999999),
            str(node.get("node_type_id") or ""),
        )
    )
    return str(candidates[0]["node_type_id"])


def _is_ml_or_gpu_runtime(key: str, name: str) -> bool:
    value = f"{key} {name}".lower()
    return "ml" in value or "gpu" in value


def _is_gpu_node(node_type_id: str, description: str) -> bool:
    value = f"{node_type_id} {description}".lower()
    return "gpu" in value


def _ensure_completed_run(client: httpx.Client, job_id: int) -> int:
    explicit = env_first("DATABRICKS_RUN_ID", "ACME_DATABRICKS_RUN_ID")
    if explicit:
        return int(explicit)
    latest = _latest_terminal_run(client, job_id)
    if latest is not None:
        return latest
    response = client.post("/api/2.1/jobs/run-now", json={"job_id": job_id})
    response.raise_for_status()
    run_id = int(response.json()["run_id"])
    deadline = time.monotonic() + int(os.getenv("ACME_DATABRICKS_RUN_TIMEOUT_SECONDS", "900"))
    while time.monotonic() < deadline:
        run = _get_run(client, run_id)
        life_cycle = run.get("state", {}).get("life_cycle_state")
        result_state = run.get("state", {}).get("result_state")
        if life_cycle in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            if result_state and result_state != "SUCCESS":
                raise RuntimeError(f"Databricks Acme job run {run_id} finished with {result_state}")
            return run_id
        time.sleep(10)
    raise TimeoutError(f"Timed out waiting for Databricks Acme job run {run_id}")


def _latest_terminal_run(client: httpx.Client, job_id: int) -> int | None:
    response = client.get("/api/2.1/jobs/runs/list", params={"job_id": job_id, "limit": 5})
    response.raise_for_status()
    for run in response.json().get("runs", []):
        state = run.get("state", {})
        if state.get("life_cycle_state") == "TERMINATED" and state.get("result_state") == "SUCCESS":
            return int(run["run_id"])
    return None


def _get_run(client: httpx.Client, run_id: int) -> dict[str, Any]:
    response = client.get("/api/2.1/jobs/runs/get", params={"run_id": run_id})
    response.raise_for_status()
    return response.json()


def _run_cluster_id(client: httpx.Client, run_id: int) -> str | None:
    run = _get_run(client, run_id)
    cluster = run.get("cluster_instance") or {}
    return cluster.get("cluster_id")
