from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
ACME_ROOT = REPO_ROOT / "tests" / "integration" / "acme"
ACME_IDS_PATH = ACME_ROOT / "seed" / "acme_ids.json"
COVERAGE_FIXTURES_PATH = ACME_ROOT / "coverage" / "fixtures.yml"
EXPECTED_ACME_CONNECTORS = [
    "notion",
    "github",
    "confluence",
    "bigquery",
    "snowflake",
    "databricks",
    "redshift",
    "fivetran",
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
]
ACME_EXCLUDED_CONNECTORS = {
    "google_docs": "Unsupported in the public catalog: OAuth consent flow is not wired for full Drive coverage.",
    "openai": "OpenAI is the LLM provider for Acme chat/retrieval, not a connector in the MCP coverage matrix.",
    "quip": "Unsupported in the public catalog: Quip was discontinued by Salesforce in 2024.",
}

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def load_acme_ids(path: Path = ACME_IDS_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run make acme-seed first.")
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def status_from_required_env(names: list[str]) -> str:
    missing = [name for name in names if not env(name)]
    return "configured" if not missing else f"missing: {', '.join(missing)}"
