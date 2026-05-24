from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SQL_SEED_FILES = {
    "postgres": Path("tests/integration/postgres/01_seed.sql"),
    "mysql": Path("tests/integration/mysql/01_seed.sql"),
    "sql_server": Path("tests/integration/seed/sql/sql_server/01_seed.sql"),
    "trino": Path("tests/integration/seed/sql/trino/01_seed.sql"),
}
EXECUTABLE_SQL_SEEDS = ("postgres", "mysql")
BIGQUERY_PROJECT_ID = "dataclaw-integration"
BIGQUERY_EMULATOR_API = "http://127.0.0.1:19050"
BIGQUERY_DATA_DIR = Path("tests/integration/seed/bigquery/data")
BIGQUERY_SEED_SCRIPT = Path("tests/integration/seed/bigquery/load.py")
SQL_SERVER_HOST = "127.0.0.1"
SQL_SERVER_PORT = 11433
SQL_SERVER_USER = "sa"
SQL_SERVER_PASSWORD = "DataClaw!Passw0rd"

AIRFLOW_API_BASE = "http://127.0.0.1:18080/api/v1"
AIRFLOW_USERNAME = "admin"
AIRFLOW_PASSWORD = "admin"
AIRFLOW_FAILURE_DAG_ID = "dataclaw_e2e_failure"


def _run(command: list[str], *, stdin: Path | None = None) -> None:
    data = stdin.read_bytes() if stdin else None
    subprocess.run(command, input=data, check=True, cwd=REPO_ROOT)


def seed_sql() -> None:
    _run(
        [
            "docker",
            "compose",
            "-f",
            "tests/integration/docker-compose.yml",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "dataclaw",
            "-d",
            "dataclaw_integration",
        ],
        stdin=REPO_ROOT / SQL_SEED_FILES["postgres"],
    )
    _run(
        [
            "docker",
            "compose",
            "-f",
            "tests/integration/docker-compose.yml",
            "exec",
            "-T",
            "mysql",
            "mysql",
            "-uroot",
            "-pdataclaw",
            "dataclaw_integration",
        ],
        stdin=REPO_ROOT / SQL_SEED_FILES["mysql"],
    )


def _split_sql_server_batches(sql: str) -> list[str]:
    batches: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        if line.strip().lower() == "go":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
            continue
        current.append(line)
    batch = "\n".join(current).strip()
    if batch:
        batches.append(batch)
    return batches


def _connect_sql_server():
    import pymssql

    return pymssql.connect(
        server=SQL_SERVER_HOST,
        port=SQL_SERVER_PORT,
        user=SQL_SERVER_USER,
        password=SQL_SERVER_PASSWORD,
        database="master",
        login_timeout=10,
        timeout=60,
        autocommit=True,
    )


def seed_sql_server() -> None:
    sql = (REPO_ROOT / SQL_SEED_FILES["sql_server"]).read_text()
    batches = _split_sql_server_batches(sql)
    deadline = time.time() + 180
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with _connect_sql_server() as conn:
                with conn.cursor() as cursor:
                    for batch in batches:
                        cursor.execute(batch)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Could not seed SQL Server: {last_error}") from last_error


def _parse_seed_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _load_bigquery_seed_module() -> ModuleType:
    script = REPO_ROOT / BIGQUERY_SEED_SCRIPT
    spec = importlib.util.spec_from_file_location("dataclaw_bigquery_seed_load", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load BigQuery seed script: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bigquery_api_request(method: str, url: str, payload: dict | None = None, *, ok_statuses: tuple[int, ...] = (200,)) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            if response.status not in ok_statuses:
                raise RuntimeError(f"BigQuery emulator returned HTTP {response.status}: {body.decode('utf-8', errors='replace')}")
            return json.loads(body.decode("utf-8")) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in ok_statuses:
            return json.loads(body) if body else {}
        raise RuntimeError(f"BigQuery emulator returned HTTP {exc.code}: {body}") from exc


def _load_bigquery_table(
    *,
    api_endpoint: str,
    project_id: str,
    data_dir: Path,
    table: object,
) -> None:
    endpoint = api_endpoint.rstrip("/")
    dataset = str(getattr(table, "dataset"))
    table_name = str(getattr(table, "table"))
    try:
        _bigquery_api_request(
            "POST",
            f"{endpoint}/bigquery/v2/projects/{project_id}/datasets",
            {"datasetReference": {"projectId": project_id, "datasetId": dataset}},
            ok_statuses=(200, 409),
        )
    except RuntimeError as exc:
        if "already created" not in str(exc).lower():
            raise
    sql = _bigquery_seed_sql(project_id, f"{dataset}.{table_name}")
    _bigquery_api_request(
        "POST",
        f"{endpoint}/bigquery/v2/projects/{project_id}/queries",
        {"query": sql, "useLegacySql": False},
    )


def _bigquery_seed_sql(project_id: str, fqtn: str) -> str:
    table_ref = f"`{project_id}.{fqtn}`"
    if fqtn == "core.customers":
        return f"""
create or replace table {table_ref} as
select
  n as id,
  if(mod(n, 33) = 0, null, concat('user', cast(n as string), '@dataclaw.test')) as email,
  concat('Customer ', cast(n as string)) as full_name,
  concat('Company-', cast(mod(n, 1000) as string)) as company,
  case mod(n, 5) when 0 then 'enterprise' when 1 then 'pro' when 2 then 'starter' else 'free' end as plan_slug,
  case mod(n, 5) when 0 then 'US' when 1 then 'GB' when 2 then 'DE' when 3 then 'IN' else 'CA' end as country_code,
  timestamp_sub(current_timestamp(), interval mod(n, 700) day) as created_at
from unnest(generate_array(1, 10000)) as n
""".strip()
    if fqtn == "core.products":
        return f"""
create or replace table {table_ref} as
select
  n as id,
  concat('SKU-', lpad(cast(n as string), 4, '0')) as sku,
  case mod(n, 5)
    when 0 then 'DataClaw Starter'
    when 1 then 'DataClaw Pro'
    when 2 then 'DataClaw Enterprise'
    when 3 then 'DataClaw Add-on Connector'
    else 'DataClaw Add-on Seat'
  end as name,
  case mod(n, 3) when 0 then 'plan' when 1 then 'addon' else 'usage' end as category,
  1900 + mod(n * 137, 30000) as price_cents,
  mod(n, 11) != 0 as active
from unnest(generate_array(1, 1000)) as n
""".strip()
    if fqtn == "core.orders":
        return f"""
create or replace table {table_ref} as
select
  n as id,
  1 + mod(n * 13, 10000) as customer_id,
  case
    when mod(n, 100) = 0 then 'stuck_in_3ds'
    when mod(n, 100) in (1, 2) then 'canceled'
    when mod(n, 100) in (3, 4) then 'pending'
    when mod(n, 100) between 5 and 10 then 'refunded'
    else 'fulfilled'
  end as status,
  2900 + mod(n * 379, 95000) as total_cents,
  case mod(n, 5) when 0 then 'USD' when 1 then 'USD' when 2 then 'EUR' when 3 then 'GBP' else 'CAD' end as currency,
  timestamp_sub(current_timestamp(), interval mod(n * 4, 700) hour) as placed_at
from unnest(generate_array(1, 50000)) as n
""".strip()
    if fqtn == "marketing.campaigns":
        return f"""
create or replace table {table_ref} as
select
  n as id,
  concat('Campaign-', cast(n as string)) as name,
  case mod(n, 5) when 0 then 'google_ads' when 1 then 'meta' when 2 then 'linkedin' when 3 then 'tiktok' else 'email' end as platform,
  date(timestamp_sub(current_timestamp(), interval mod(n * 5, 300) day)) as starts_on,
  cast(1000 + mod(n * 1379, 50000) as numeric) as budget_usd
from unnest(generate_array(1, 200)) as n
""".strip()
    if fqtn == "events.product_events":
        return f"""
create or replace table {table_ref} as
select
  n as id,
  1 + mod(n * 7, 10000) as user_id,
  case mod(n, 10)
    when 0 then 'signup'
    when 1 then 'signed_up'
    when 2 then 'verified_email'
    when 3 then 'created_first_workspace'
    when 4 then 'imported_first_dataset'
    when 5 then 'ran_first_query'
    when 6 then 'checkout_started'
    when 7 then 'checkout_completed'
    when 8 then 'agent_run_completed'
    else 'session_started'
  end as event_type,
  to_json(struct('bigquery-seed' as source, concat('3.', cast(mod(n, 10) as string)) as version)) as properties,
  timestamp_sub(current_timestamp(), interval mod(n * 5, 720) minute) as created_at
from unnest(generate_array(1, 100000)) as n
""".strip()
    raise RuntimeError(f"Unhandled BigQuery seed table: {fqtn}")


def _airflow_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict | None]:
    import base64

    url = f"{AIRFLOW_API_BASE}{path}"
    body = json.dumps(json_body).encode() if json_body is not None else None
    auth = base64.b64encode(f"{AIRFLOW_USERNAME}:{AIRFLOW_PASSWORD}".encode()).decode()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Basic {auth}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, (json.loads(raw) if raw else None)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode(errors="replace")}


def seed_airflow(*, dag_id: str = AIRFLOW_FAILURE_DAG_ID, wait_seconds: int = 240) -> None:
    """Trigger the e2e_failure DAG and wait for it to actually fail.

    The Acme test rig relies on a real failed run existing for Scenario 3
    ("ETL question: show me the latest failed run"). Boot-time auto-discovery
    of DAG files is not enough — Airflow needs at least one materialized run
    with state=failed before any background-agent or chat query can see it.
    """
    # Wait for the API to come up.
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status, _ = _airflow_request("GET", "/health", timeout=10)
        if status == 200:
            break
        time.sleep(2)
    else:
        print(f"[seed-airflow] Airflow API did not become healthy in {wait_seconds}s; skipping seed.", file=sys.stderr)
        return

    # Wait for the DAG to be loaded (scheduler picks up files on a parser loop).
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status, payload = _airflow_request("GET", f"/dags/{dag_id}", timeout=10)
        if status == 200:
            break
        time.sleep(3)
    else:
        print(f"[seed-airflow] DAG {dag_id} did not register; skipping seed.", file=sys.stderr)
        return

    # Unpause the DAG (always-failing DAGs are paused by default in some configs).
    _airflow_request("PATCH", f"/dags/{dag_id}", json_body={"is_paused": False}, timeout=10)

    # Check whether we already have a failed run; if so, this is a no-op (idempotent).
    status, payload = _airflow_request(
        "GET",
        f"/dags/{dag_id}/dagRuns?order_by=-execution_date&limit=5",
        timeout=10,
    )
    if status == 200 and payload and any(run.get("state") == "failed" for run in payload.get("dag_runs", [])):
        print(f"[seed-airflow] DAG {dag_id} already has a failed run; skipping trigger.")
        return

    # Trigger a new run.
    logical_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    run_id = f"seed_failure_{int(time.time())}"
    status, payload = _airflow_request(
        "POST",
        f"/dags/{dag_id}/dagRuns",
        json_body={"dag_run_id": run_id, "logical_date": logical_date},
        timeout=15,
    )
    if status not in (200, 201):
        print(f"[seed-airflow] trigger returned HTTP {status}: {payload!r}", file=sys.stderr)
        return

    # Poll for terminal state.
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status, payload = _airflow_request("GET", f"/dags/{dag_id}/dagRuns/{run_id}", timeout=10)
        if status == 200 and payload and payload.get("state") in {"failed", "success"}:
            print(f"[seed-airflow] DAG {dag_id} run {run_id} terminal state: {payload.get('state')}")
            return
        time.sleep(3)
    print(f"[seed-airflow] DAG {dag_id} run {run_id} did not reach terminal state in {wait_seconds}s.", file=sys.stderr)


def seed_bigquery(*, seed_date: str | None = None, api_endpoint: str | None = None) -> None:
    bigquery_seed = _load_bigquery_seed_module()
    data_dir = REPO_ROOT / BIGQUERY_DATA_DIR
    bigquery_seed.write_seed_files(data_dir, seed_date=_parse_seed_date(seed_date))
    endpoint = (api_endpoint or BIGQUERY_EMULATOR_API).rstrip("/")
    for table in bigquery_seed.TABLES:
        _load_bigquery_table(api_endpoint=endpoint, project_id=BIGQUERY_PROJECT_ID, data_dir=data_dir, table=table)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the DataClaw integration stack.")
    parser.add_argument("--seed-date", default=None, help="Reserved for deterministic timestamped fixtures.")
    parser.add_argument(
        "--only",
        choices=["all", "sql", "sql_server", "bigquery", "airflow"],
        default="all",
        help="Limit seeding to a subset for one-connector integration runs.",
    )
    parser.add_argument(
        "--bigquery-api",
        default=os.getenv("BIGQUERY_EMULATOR_API", BIGQUERY_EMULATOR_API),
        help="Optional bq --api endpoint for the BigQuery emulator.",
    )
    parser.add_argument(
        "--skip-airflow",
        action="store_true",
        help="Skip triggering the always-failing Airflow DAG (e.g., when the Airflow service is not running).",
    )
    args = parser.parse_args()
    if args.only in {"all", "sql"}:
        seed_sql()
    if args.only in {"all", "sql_server"}:
        seed_sql_server()
    if args.only in {"all", "bigquery"}:
        seed_bigquery(seed_date=args.seed_date, api_endpoint=args.bigquery_api or None)
    if args.only in {"all", "airflow"} and not args.skip_airflow:
        seed_airflow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
