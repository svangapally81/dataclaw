from __future__ import annotations

import time
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def wait_for_partner_export() -> str:
    time.sleep(10)
    return "partner export completed after 10 seconds"


with DAG(
    dag_id="slow_etl",
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    tags=["dataclaw", "phase-h", "sla:slow"],
) as dag:
    PythonOperator(task_id="wait_for_partner_export", python_callable=wait_for_partner_export)
