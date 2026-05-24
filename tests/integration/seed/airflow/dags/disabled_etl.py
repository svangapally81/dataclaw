from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator


with DAG(
    dag_id="disabled_etl",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    is_paused_upon_creation=True,
    tags=["dataclaw", "phase-h", "paused"],
) as dag:
    EmptyOperator(task_id="paused_by_default")
