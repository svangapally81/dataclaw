"""
weekly_customer_360 — builds derived.customer_360 wide table for analytics.

Owner: analytics-eng@dataclaw.com
SLA: every Monday 02:00 UTC, completed by 03:00 UTC
Sources: core.customers, core.orders, marketing.email_sends, events.product_events
Output: derived.customer_360 (one row per customer, ~80 columns of LTV/RFM/segment features)

NOTE (2025-Q4): segment definitions live in `dbt_models/customer_360_segments.sql` in
the analytics-models repo, NOT in this DAG. Do not hard-code segment thresholds here.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="weekly_customer_360",
    description="Build derived.customer_360 wide-table for analytics",
    start_date=datetime(2025, 1, 1),
    schedule="0 2 * * MON",
    catchup=False,
    tags=["owner:analytics-eng", "sla:60min", "tier:gold", "produces:derived.customer_360"],
    default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
) as dag:
    aggregate_orders = BashOperator(
        task_id="aggregate_order_history",
        bash_command="echo 'CREATE TEMP TABLE customer_orders AS SELECT customer_id, count(*) ...'",
    )
    aggregate_email = BashOperator(
        task_id="aggregate_email_engagement",
        bash_command="echo 'CREATE TEMP TABLE customer_email AS SELECT customer_id, sum(opens) ...'",
    )
    aggregate_events = BashOperator(
        task_id="aggregate_product_events",
        bash_command="echo 'CREATE TEMP TABLE customer_events AS SELECT user_id, count(*) ...'",
    )
    join_and_segment = BashOperator(
        task_id="join_features_and_segment",
        bash_command="echo 'INSERT INTO derived.customer_360 SELECT c.*, o.*, e.*, p.* FROM ...'",
    )
    [aggregate_orders, aggregate_email, aggregate_events] >> join_and_segment
