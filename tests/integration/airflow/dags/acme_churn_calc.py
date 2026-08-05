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
