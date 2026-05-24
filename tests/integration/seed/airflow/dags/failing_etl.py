from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def fail_with_seeded_error() -> None:
    raise RuntimeError("seeded Phase H failure: upstream payments API returned HTTP 503")


with DAG(
    dag_id="failing_etl",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["dataclaw", "phase-h", "produces:core.orders"],
) as dag:
    PythonOperator(task_id="extract_payments", python_callable=fail_with_seeded_error)
