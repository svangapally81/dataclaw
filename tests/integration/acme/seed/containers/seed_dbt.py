from __future__ import annotations


def seed_dbt() -> dict[str, str]:
    return {
        "fixture": "dbt",
        "project": "dataclaw-acme-dbt",
        "project_id": "1",
        "project_path": ".",
        "run_id": "1",
        "failed_run_id": "2",
        "models": "stg_customers,dim_customers,fct_orders",
    }


__all__ = ["seed_dbt"]
