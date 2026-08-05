from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class BigQuerySeedTable:
    dataset: str
    table: str
    rows: int
    schema: tuple[tuple[str, str], ...]

    @property
    def fqtn(self) -> str:
        return f"{self.dataset}.{self.table}"


TABLES = (
    BigQuerySeedTable(
        dataset="core",
        table="customers",
        rows=10_000,
        schema=(
            ("id", "INTEGER"),
            ("email", "STRING"),
            ("full_name", "STRING"),
            ("company", "STRING"),
            ("plan_slug", "STRING"),
            ("country_code", "STRING"),
            ("created_at", "TIMESTAMP"),
        ),
    ),
    BigQuerySeedTable(
        dataset="core",
        table="products",
        rows=1_000,
        schema=(
            ("id", "INTEGER"),
            ("sku", "STRING"),
            ("name", "STRING"),
            ("category", "STRING"),
            ("price_cents", "INTEGER"),
            ("active", "BOOLEAN"),
        ),
    ),
    BigQuerySeedTable(
        dataset="core",
        table="orders",
        rows=50_000,
        schema=(
            ("id", "INTEGER"),
            ("customer_id", "INTEGER"),
            ("status", "STRING"),
            ("total_cents", "INTEGER"),
            ("currency", "STRING"),
            ("placed_at", "TIMESTAMP"),
        ),
    ),
    BigQuerySeedTable(
        dataset="marketing",
        table="campaigns",
        rows=200,
        schema=(
            ("id", "INTEGER"),
            ("name", "STRING"),
            ("platform", "STRING"),
            ("starts_on", "DATE"),
            ("budget_usd", "NUMERIC"),
        ),
    ),
    BigQuerySeedTable(
        dataset="events",
        table="product_events",
        rows=100_000,
        schema=(
            ("id", "INTEGER"),
            ("user_id", "INTEGER"),
            ("event_type", "STRING"),
            ("properties", "JSON"),
            ("created_at", "TIMESTAMP"),
        ),
    ),
)


def schema_arg(table: BigQuerySeedTable) -> str:
    return ",".join(f"{name}:{kind}" for name, kind in table.schema)


def bq_load_commands(*, project_id: str, data_dir: Path, api_endpoint: str | None = None) -> list[list[str]]:
    global_flags = ["--project_id", project_id]
    if api_endpoint:
        global_flags = ["--api", api_endpoint.rstrip("/"), *global_flags]
    return [
        [
            "bq",
            *global_flags,
            "load",
            "--source_format=NEWLINE_DELIMITED_JSON",
            f"{table.dataset}.{table.table}",
            str(data_dir / table.dataset / f"{table.table}.ndjson"),
            schema_arg(table),
        ]
        for table in TABLES
    ]


def expected_row_counts() -> dict[str, int]:
    return {table.fqtn: table.rows for table in TABLES}


def iter_rows(table: BigQuerySeedTable, *, seed_date: datetime | None = None) -> Iterable[dict[str, Any]]:
    base = seed_date or datetime(2026, 5, 12, tzinfo=UTC)
    for n in range(1, table.rows + 1):
        if table.fqtn == "core.customers":
            yield {
                "id": n,
                "email": None if n % 33 == 0 else f"user{n}@dataclaw.test",
                "full_name": f"Customer {n}",
                "company": f"Company-{n % 1000}",
                "plan_slug": ["enterprise", "pro", "starter", "free", "free"][n % 5],
                "country_code": ["US", "GB", "DE", "IN", "CA"][n % 5],
                "created_at": (base - timedelta(days=n % 700)).isoformat(),
            }
        elif table.fqtn == "core.products":
            yield {
                "id": n,
                "sku": f"SKU-{n:04d}",
                "name": [
                    "DataClaw Starter",
                    "DataClaw Pro",
                    "DataClaw Enterprise",
                    "DataClaw Add-on Connector",
                    "DataClaw Add-on Seat",
                ][n % 5],
                "category": ["plan", "addon", "usage"][n % 3],
                "price_cents": 1900 + (n * 137 % 30000),
                "active": n % 11 != 0,
            }
        elif table.fqtn == "core.orders":
            status = "fulfilled"
            if n % 100 == 0:
                status = "stuck_in_3ds"
            elif n % 100 in {1, 2}:
                status = "canceled"
            elif n % 100 in {3, 4}:
                status = "pending"
            elif 5 <= n % 100 <= 10:
                status = "refunded"
            yield {
                "id": n,
                "customer_id": 1 + (n * 13 % 10000),
                "status": status,
                "total_cents": 2900 + (n * 379 % 95000),
                "currency": ["USD", "USD", "EUR", "GBP", "CAD"][n % 5],
                "placed_at": (base - timedelta(hours=n * 4 % 700)).isoformat(),
            }
        elif table.fqtn == "marketing.campaigns":
            yield {
                "id": n,
                "name": f"Campaign-{n}",
                "platform": ["google_ads", "meta", "linkedin", "tiktok", "email"][n % 5],
                "starts_on": (base - timedelta(days=n * 5 % 300)).date().isoformat(),
                "budget_usd": str(1000 + (n * 1379 % 50000)),
            }
        elif table.fqtn == "events.product_events":
            yield {
                "id": n,
                "user_id": 1 + (n * 7 % 10000),
                "event_type": [
                    "signup",
                    "signed_up",
                    "verified_email",
                    "created_first_workspace",
                    "imported_first_dataset",
                    "ran_first_query",
                    "checkout_started",
                    "checkout_completed",
                    "agent_run_completed",
                    "session_started",
                ][n % 10],
                "properties": {"source": "bigquery-seed", "version": f"3.{n % 10}"},
                "created_at": (base - timedelta(minutes=n * 5 % 720)).isoformat(),
            }
        else:  # pragma: no cover - TABLES is exhaustive.
            raise ValueError(f"Unhandled BigQuery seed table: {table.fqtn}")


def write_seed_files(data_dir: Path, *, seed_date: datetime | None = None) -> dict[str, int]:
    written: dict[str, int] = {}
    for table in TABLES:
        path = data_dir / table.dataset / f"{table.table}.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("w") as handle:
            for row in iter_rows(table, seed_date=seed_date):
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                count += 1
        written[table.fqtn] = count
    return written


if __name__ == "__main__":
    output_dir = Path("tests/integration/seed/bigquery/data")
    write_seed_files(output_dir)
    for command in bq_load_commands(project_id="dataclaw-integration", data_dir=output_dir):
        print(" ".join(command))
