from __future__ import annotations

from tests.integration.acme.seed.seed_acme import _seed_acme_airflow_run, _write_acme_airflow_dags


def seed_airflow() -> dict[str, object]:
    _write_acme_airflow_dags()
    return {
        "dags": ["acme_etl_daily", "acme_churn_calc"],
        "failed_dag": "acme_churn_calc",
        "failed_run_id": _seed_acme_airflow_run(),
    }


__all__ = ["seed_airflow"]
