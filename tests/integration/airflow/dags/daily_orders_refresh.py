"""
daily_orders_refresh — refreshes core.orders and core.order_items from the OLTP replica.

Owner: core-data@dataclaw.com (Slack: #core-data-oncall)
SLA: 30 minutes after midnight UTC
Downstream: derived.customer_360, derived.cohort_retention, marketing.attribution_touchpoints

Source-of-truth note: this DAG is the ONLY producer of core.orders. If you want to backfill,
coordinate with the data engineering oncall — running it concurrently with the OLTP replica
sync corrupts order_items_idx_orderid (incident PG-2024-1129).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="daily_orders_refresh",
    description="Refresh core.orders + core.order_items nightly from OLTP replica",
    start_date=datetime(2025, 1, 1),
    schedule="0 0 * * *",
    catchup=False,
    tags=["owner:core-data", "sla:30min", "tier:gold", "produces:core.orders", "produces:core.order_items"],
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
) as dag:
    extract = BashOperator(
        task_id="extract_oltp_replica",
        bash_command="echo 'COPY (SELECT * FROM oltp_replica.orders WHERE updated_at > NOW() - INTERVAL 1 day) TO ...'",
    )
    transform = BashOperator(
        task_id="apply_business_rules",
        bash_command="echo 'UPDATE staging.orders SET status = case when refunded_at is not null then ...'",
    )
    load_orders = BashOperator(
        task_id="load_core_orders",
        bash_command="echo 'INSERT INTO core.orders SELECT * FROM staging.orders ON CONFLICT DO UPDATE'",
    )
    load_items = BashOperator(
        task_id="load_core_order_items",
        bash_command="echo 'INSERT INTO core.order_items SELECT * FROM staging.order_items ON CONFLICT DO UPDATE'",
    )
    extract >> transform >> [load_orders, load_items]
