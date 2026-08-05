from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ACME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ACME_ROOT.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(ACME_ROOT) not in sys.path:
    sys.path.insert(0, str(ACME_ROOT))

from tests.integration.acme.common import write_json  # noqa: E402
from tests.integration.acme.seed.containers.seed_airbyte import seed_airbyte  # noqa: E402
from tests.integration.acme.seed.containers.seed_dagster import seed_dagster  # noqa: E402
from tests.integration.acme.seed.containers.seed_dbt import seed_dbt  # noqa: E402
from tests.integration.acme.seed.containers.seed_prefect import seed_prefect  # noqa: E402
from tests.integration.acme.seed.containers.seed_trino import seed_trino  # noqa: E402
from tests.integration.acme.seed.saas.common import (  # noqa: E402,F401
    SAAS_ENV,
    EnvRequirement,
)
from tests.integration.acme.seed.saas.seed_bigquery import seed_bigquery  # noqa: E402
from tests.integration.acme.seed.saas.seed_confluence import seed_confluence  # noqa: E402
from tests.integration.acme.seed.saas.seed_databricks import seed_databricks  # noqa: E402
from tests.integration.acme.seed.saas.seed_fivetran import seed_fivetran  # noqa: E402
from tests.integration.acme.seed.saas.seed_github import seed_github  # noqa: E402
from tests.integration.acme.seed.saas.seed_notion import seed_notion  # noqa: E402
from tests.integration.acme.seed.saas.seed_redshift import seed_redshift  # noqa: E402
from tests.integration.acme.seed.saas.seed_snowflake import seed_snowflake  # noqa: E402

ACME_IDS_PATH = Path(__file__).resolve().parent / "acme_ids.json"
COMPOSE_FILE = REPO_ROOT / "tests" / "integration" / "docker-compose.yml"
SEED_RUNNER = REPO_ROOT / "tests" / "integration" / "seed" / "run.py"

CONTAINER_SERVICES = [
    "postgres",
    "mysql",
    "sql_server",
    "trino",
    "airflow",
    "fixture-api",
    "dbt",
    "prefect",
    "dagster",
    "chroma",
]


def _load_seed_runner():
    spec = importlib.util.spec_from_file_location("dataclaw_integration_seed_runner", SEED_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SEED_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(command: list[str], *, input_text: str | None = None) -> None:
    subprocess.run(command, cwd=REPO_ROOT, check=True, input=input_text, text=True)


def boot_containers() -> None:
    _run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "up",
            "-d",
            "--wait",
            *CONTAINER_SERVICES,
        ]
    )


def seed_containers(selected_connectors: set[str] | None = None) -> dict[str, Any]:
    if selected_connectors is not None:
        return _seed_selected_containers(selected_connectors)
    runner = _load_seed_runner()
    runner.seed_sql()
    runner.seed_sql_server()
    _seed_acme_postgres()
    _seed_acme_mysql()
    _seed_acme_sql_server()
    _write_acme_airflow_dags()
    airflow_run_id = _seed_acme_airflow_run()
    return {
        "postgres": {
            "schema": "raw",
            "tables": ["customers", "orders", "products", "churn_events"],
            "row_counts": {"customers": 1000, "orders": 5000, "products": 200, "churn_events": 300},
        },
        "mysql": {
            "database": "acme_billing",
            "tables": ["invoices"],
            "row_counts": {"invoices": 300},
        },
        "sql_server": {
            "database": "dataclaw_integration",
            "schema": "dbo",
            "tables": ["legacy_orders"],
            "row_counts": {"legacy_orders": 200},
        },
        "trino": seed_trino(),
        "airflow": {
            "dags": ["acme_etl_daily", "acme_churn_calc"],
            "failed_dag": "acme_churn_calc",
            "failed_run_id": airflow_run_id,
        },
        "dbt": seed_dbt(),
        "prefect": seed_prefect(),
        "dagster": seed_dagster(),
        "airbyte": seed_airbyte(),
        "sqlite": {"mode": "bundled_demo"},
    }


def _seed_selected_containers(selected_connectors: set[str]) -> dict[str, Any]:
    unknown = selected_connectors - {
        "postgres",
        "mysql",
        "sql_server",
        "trino",
        "airflow",
        "dbt",
        "prefect",
        "dagster",
        "airbyte",
        "sqlite",
    }
    if unknown:
        raise ValueError(f"Unknown Acme container connector(s): {', '.join(sorted(unknown))}")

    payload: dict[str, Any] = {}
    if "postgres" in selected_connectors:
        _seed_acme_postgres()
        payload["postgres"] = {
            "schema": "raw",
            "tables": ["customers", "orders", "products", "churn_events"],
            "row_counts": {"customers": 1000, "orders": 5000, "products": 200, "churn_events": 300},
        }
    if "mysql" in selected_connectors:
        _seed_acme_mysql()
        payload["mysql"] = {
            "database": "acme_billing",
            "tables": ["invoices"],
            "row_counts": {"invoices": 300},
        }
    if "sql_server" in selected_connectors:
        runner = _load_seed_runner()
        runner.seed_sql_server()
        _seed_acme_sql_server()
        payload["sql_server"] = {
            "database": "dataclaw_integration",
            "schema": "dbo",
            "tables": ["legacy_orders"],
            "row_counts": {"legacy_orders": 200},
        }
    if "trino" in selected_connectors:
        payload["trino"] = seed_trino()
    if "airflow" in selected_connectors:
        _write_acme_airflow_dags()
        airflow_run_id = _seed_acme_airflow_run()
        payload["airflow"] = {
            "dags": ["acme_etl_daily", "acme_churn_calc"],
            "failed_dag": "acme_churn_calc",
            "failed_run_id": airflow_run_id,
        }
    if "dbt" in selected_connectors:
        payload["dbt"] = seed_dbt()
    if "prefect" in selected_connectors:
        payload["prefect"] = seed_prefect()
    if "dagster" in selected_connectors:
        payload["dagster"] = seed_dagster()
    if "airbyte" in selected_connectors:
        payload["airbyte"] = seed_airbyte()
    if "sqlite" in selected_connectors:
        payload["sqlite"] = {"mode": "bundled_demo"}
    return payload


def _seed_acme_postgres() -> None:
    sql = """
    create schema if not exists raw;
    drop table if exists raw.churn_events;
    drop table if exists raw.orders;
    drop table if exists raw.products;
    drop table if exists raw.customers;
    create table raw.customers (
      customer_id integer primary key,
      email text,
      segment text not null,
      created_at timestamptz not null
    );
    create table raw.products (
      product_id integer primary key,
      sku text not null,
      category text not null,
      price_cents integer not null
    );
    create table raw.orders (
      order_id integer primary key,
      customer_id integer not null references raw.customers(customer_id),
      product_id integer not null references raw.products(product_id),
      status text not null,
      arr_usd numeric(12,2) not null,
      ordered_at timestamptz not null
    );
    create table raw.churn_events (
      event_id integer primary key,
      customer_id integer not null references raw.customers(customer_id),
      event_type text not null,
      event_at timestamptz not null
    );
    insert into raw.customers
    select g, 'customer' || g || '@acme.test',
      case g % 3 when 0 then 'enterprise' when 1 then 'growth' else 'self_serve' end,
      now() - (g % 365) * interval '1 day'
    from generate_series(1, 1000) as g;
    insert into raw.products
    select g, 'ACME-SKU-' || g,
      case g % 4 when 0 then 'platform' when 1 then 'connector' when 2 then 'seat' else 'usage' end,
      1000 + (g * 137 % 20000)
    from generate_series(1, 200) as g;
    insert into raw.orders
    select g, 1 + (g * 13 % 1000), 1 + (g * 7 % 200),
      case when g % 19 = 0 then 'refunded' when g % 11 = 0 then 'cancelled' else 'paid' end,
      100 + (g * 17 % 5000),
      now() - (g % 90) * interval '1 day'
    from generate_series(1, 5000) as g;
    insert into raw.churn_events
    select g, 1 + (g * 23 % 1000),
      case g % 3 when 0 then 'downgrade' when 1 then 'cancellation' else 'inactive_30d' end,
      now() - (g % 60) * interval '1 day'
    from generate_series(1, 300) as g;
    """
    _run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "postgres", "psql", "-U", "dataclaw", "-d", "dataclaw_integration"],
        input_text=textwrap.dedent(sql),
    )


def _seed_acme_mysql() -> None:
    sql = """
    create database if not exists acme_billing;
    grant all privileges on acme_billing.* to 'dataclaw'@'%';
    use acme_billing;
    drop table if exists invoices;
    create table invoices (
      invoice_id int primary key,
      customer_id int not null,
      invoice_status varchar(40) not null,
      amount_usd decimal(12,2) not null,
      issued_at timestamp not null
    );
    insert into invoices
    with recursive seq(n) as (
      select 1 union all select n + 1 from seq where n < 300
    )
    select n, 1 + (n * 13 % 1000),
      case n % 5 when 0 then 'past_due' when 1 then 'void' else 'paid' end,
      100 + (n * 37 % 10000),
      timestampadd(day, -(n % 120), current_timestamp)
    from seq;
    """
    _run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "mysql", "mysql", "-uroot", "-pdataclaw"],
        input_text=textwrap.dedent(sql),
    )


def _seed_acme_sql_server() -> None:
    import pymssql

    deadline = time.time() + 180
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            conn = pymssql.connect(
                server="127.0.0.1",
                port=11433,
                user="sa",
                password="DataClaw!Passw0rd",
                database="dataclaw_integration",
                login_timeout=10,
                timeout=60,
                autocommit=True,
            )
            break
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    else:
        raise RuntimeError(f"Could not connect to SQL Server for Acme seed: {last_error}") from last_error

    try:
        with conn.cursor() as cur:
            cur.execute("drop table if exists dbo.legacy_orders")
            cur.execute("create table dbo.legacy_orders (legacy_order_id int primary key, customer_id int not null, status nvarchar(40) not null, amount_usd decimal(12,2) not null)")
            cur.executemany(
                "insert into dbo.legacy_orders (legacy_order_id, customer_id, status, amount_usd) values (%s, %s, %s, %s)",
                [(n, 1 + (n * 17 % 1000), "archived" if n % 9 else "needs_review", 50 + (n * 29 % 5000)) for n in range(1, 201)],
            )
    finally:
        conn.close()


def _write_acme_airflow_dags() -> None:
    dags_dir = REPO_ROOT / "tests" / "integration" / "airflow" / "dags"
    dags_dir.mkdir(parents=True, exist_ok=True)
    (dags_dir / "acme_etl_daily.py").write_text(
        textwrap.dedent(
            '''
            """Acme daily ETL: Postgres raw tables to BigQuery raw landing."""

            from datetime import datetime

            from airflow import DAG
            from airflow.operators.bash import BashOperator


            with DAG(
                dag_id="acme_etl_daily",
                start_date=datetime(2025, 1, 1),
                schedule="0 2 * * *",
                catchup=False,
                tags=["acme", "postgres", "bigquery"],
            ) as dag:
                extract = BashOperator(task_id="extract", bash_command="echo extract raw.customers raw.orders")
                load = BashOperator(task_id="load_bq", bash_command="echo load bq_raw")
                extract >> load
            '''
        ).lstrip(),
        encoding="utf-8",
    )
    (dags_dir / "acme_churn_calc.py").write_text(
        textwrap.dedent(
            '''
            """Acme churn calculation: BigQuery modeled customers to Snowflake churn marts."""

            from datetime import datetime

            from airflow import DAG
            from airflow.operators.bash import BashOperator


            with DAG(
                dag_id="acme_churn_calc",
                start_date=datetime(2025, 1, 1),
                schedule="0 4 * * *",
                catchup=False,
                tags=["acme", "churn", "failed-fixture"],
            ) as dag:
                score = BashOperator(task_id="score_churn", bash_command="echo score churn && exit 1")
            '''
        ).lstrip(),
        encoding="utf-8",
    )


def _airflow_headers() -> dict[str, str]:
    token = base64.b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _airflow_api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    ok_statuses: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    base_url = os.getenv("ACME_AIRFLOW_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=_airflow_headers(),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            if response.status not in ok_statuses:
                raise RuntimeError(f"Airflow returned HTTP {response.status}: {body}")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in ok_statuses:
            return json.loads(body) if body else {}
        raise RuntimeError(f"Airflow returned HTTP {exc.code}: {body}") from exc


def _seed_acme_airflow_run() -> str:
    run_id = "manual__acme_coverage"
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            dags = _airflow_api_request("GET", "/api/v1/dags", ok_statuses=(200,))
            dag_ids = {item.get("dag_id") for item in dags.get("dags", [])}
            if {"acme_etl_daily", "acme_churn_calc"}.issubset(dag_ids):
                break
        except RuntimeError:
            pass
        time.sleep(5)
    _airflow_api_request(
        "PATCH",
        "/api/v1/dags/acme_churn_calc",
        {"is_paused": False},
        ok_statuses=(200,),
    )
    _airflow_api_request(
        "PATCH",
        "/api/v1/dags/acme_etl_daily",
        {"is_paused": False},
        ok_statuses=(200,),
    )
    _airflow_api_request(
        "POST",
        "/api/v1/dags/acme_churn_calc/dagRuns",
        {"dag_run_id": run_id, "conf": {"acme": True}},
        ok_statuses=(200, 409),
    )
    _airflow_api_request(
        "POST",
        "/api/v1/dags/acme_etl_daily/dagRuns",
        {"dag_run_id": run_id, "conf": {"acme": True}},
        ok_statuses=(200, 409),
    )
    _airflow_api_request(
        "POST",
        "/api/v1/variables",
        {"key": "acme_coverage_marker", "value": "seeded"},
        ok_statuses=(200, 409),
    )
    return run_id


def seed_saas() -> dict[str, Any]:
    return {
        "notion": seed_notion(),
        "github": seed_github(),
        "confluence": seed_confluence(),
        "bigquery": seed_bigquery(),
        "snowflake": seed_snowflake(),
        "databricks": seed_databricks(),
        "redshift": seed_redshift(),
        "fivetran": seed_fivetran(),
    }


def build_manifest(
    *,
    include_containers: bool,
    include_saas: bool,
    selected_container_connectors: set[str] | None = None,
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if ACME_IDS_PATH.exists():
        existing = json.loads(ACME_IDS_PATH.read_text(encoding="utf-8"))
    payload: dict[str, Any] = {
        "company": "Acme Co",
        "generated_at": datetime.now(UTC).isoformat(),
        "containers": existing.get("containers", {}),
        "saas": existing.get("saas", {}),
    }
    if include_containers:
        seeded_containers = (
            seed_containers()
            if selected_container_connectors is None
            else seed_containers(selected_container_connectors)
        )
        if selected_container_connectors is None:
            payload["containers"] = seeded_containers
        else:
            payload["containers"] = {**payload["containers"], **seeded_containers}
    if include_saas:
        payload["saas"] = seed_saas()
    return payload


def skipped_seed_paths(payload: dict[str, Any], *, include_containers: bool = True, include_saas: bool = True) -> list[str]:
    skipped: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if value.get("status") == "skipped":
                skipped.append(path)
            for key, nested in value.items():
                walk(nested, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")

    if include_containers:
        walk(payload.get("containers", {}), "containers")
    if include_saas:
        walk(payload.get("saas", {}), "saas")
    return sorted(skipped)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Acme Co release-gate fixture manifest.")
    parser.add_argument("--boot-containers", action="store_true", help="Start Docker integration services first.")
    parser.add_argument("--containers-only", action="store_true", help="Seed only Docker/local backends.")
    parser.add_argument("--saas-only", action="store_true", help="Record only SaaS seed metadata.")
    parser.add_argument(
        "--container",
        action="append",
        choices=[
            "postgres",
            "mysql",
            "sql_server",
            "trino",
            "airflow",
            "dbt",
            "prefect",
            "dagster",
            "airbyte",
            "sqlite",
        ],
        help="Seed one Docker/local backend. Repeat to seed multiple focused backends.",
    )
    parser.add_argument("--require-live", action="store_true", help="Fail if any selected seeder returns status=skipped.")
    args = parser.parse_args()
    include_containers = not args.saas_only
    include_saas = not args.containers_only

    if args.boot_containers:
        boot_containers()
    manifest = build_manifest(
        include_containers=include_containers,
        include_saas=include_saas,
        selected_container_connectors=set(args.container) if args.container else None,
    )
    write_json(ACME_IDS_PATH, manifest)
    print(f"Wrote {ACME_IDS_PATH.relative_to(REPO_ROOT)}")
    if args.require_live:
        skipped = skipped_seed_paths(manifest, include_containers=include_containers, include_saas=include_saas)
        if skipped:
            print("Acme seed has skipped live seeders:", file=sys.stderr)
            for path in skipped:
                print(f"- {path}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
