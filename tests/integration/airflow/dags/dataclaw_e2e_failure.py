"""A deterministic failed DAG for the v0.1 background-agent release gate."""

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="dataclaw_e2e_failure",
    description="Always fails so DataClaw can verify Airflow alert dispatch.",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["dataclaw:e2e", "alert:critical"],
) as dag:
    fail = BashOperator(
        task_id="fail_for_dataclaw_e2e",
        bash_command="echo 'DataClaw E2E failure fixture' && exit 1",
    )
