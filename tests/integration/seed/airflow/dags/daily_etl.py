from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def extract_customers() -> str:
    return "loaded 1247 customers from the last 30 days"


def refresh_orders() -> str:
    return "refreshed core.orders and derived.customer_360"


with DAG(
    dag_id="daily_etl",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["dataclaw", "phase-h", "produces:core.customers", "produces:core.orders"],
) as dag:
    extract = PythonOperator(task_id="extract_customers", python_callable=extract_customers)
    refresh = PythonOperator(task_id="refresh_orders", python_callable=refresh_orders)
    extract >> refresh
