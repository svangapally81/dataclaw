"""
legacy_orders_archive — DEPRECATED 2024-08. Archived rows from `core.orders_v1` to cold storage.

Owner: NONE (orphaned — was originally owned by core-data; the v1 schema was removed
when daily_orders_refresh was rewritten to write directly to core.orders).

This DAG remains in the repo for historical reference. It is paused and the underlying
table `core.orders_v1` no longer exists. DO NOT unpause without first restoring v1
schema from the cold-storage snapshot — see the runbook in Notion.

If the data-quality alert "core.orders_v1 missing" fires, it's because someone
accidentally unpaused this DAG. Re-pause it.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="legacy_orders_archive",
    description="DEPRECATED 2024-08 — do not unpause",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False,
    is_paused_upon_creation=True,
    tags=["DEPRECATED", "owner:none", "do-not-run"],
    default_args={"retries": 0},
) as dag:
    archive = BashOperator(
        task_id="archive_to_cold_storage",
        bash_command="echo 'pg_dump -t core.orders_v1 ... | aws s3 cp - s3://dataclaw-cold-archive/...'",
    )
    delete = BashOperator(
        task_id="delete_archived_rows",
        bash_command="echo 'DELETE FROM core.orders_v1 WHERE created_at < now() - interval 2 years'",
    )
    archive >> delete
