from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def load_campaigns() -> str:
    return "loaded marketing.campaigns, marketing.email_sends, and marketing.ad_spend_daily"


with DAG(
    dag_id="daily_marketing",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["dataclaw", "phase-h", "produces:marketing.campaigns"],
) as dag:
    PythonOperator(task_id="load_campaigns", python_callable=load_campaigns)
