"""Acme daily ETL: Postgres raw tables to BigQuery raw landing."""

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="acme_etl_daily",
    start_date=datetime(2025, 1, 1),
    schedule="0 2 * * *",
    catchup=False,
    tags=["acme", "postgres", "bigquery"],
) as dag:
    extract = BashOperator(task_id="extract", bash_command="echo extract raw.customers raw.orders")
    load = BashOperator(task_id="load_bq", bash_command="echo load bq_raw")
    extract >> load
