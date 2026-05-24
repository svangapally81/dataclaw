"""
attribution_backfill — multi-touch attribution model for marketing.

Owner: marketing-eng@dataclaw.com (analytics partner: aiyaz@)
SLA: daily 04:00 UTC, completed by 05:00 UTC
Model: position-based attribution (40% first-touch, 40% last-touch, 20% middle)

Sources: marketing.email_sends, marketing.ad_spend_daily, events.product_events
Output: derived.attribution_touchpoints (one row per (order_id, touchpoint_id) pair)

Note: this is a BACKFILL DAG by design — it runs the last 30 days every night to handle
late-arriving SendGrid events and ad-platform corrections. If you need to extend the
window, change ATTRIBUTION_WINDOW_DAYS in marketing/attribution_config.yml in the
analytics-models repo (NOT here — this DAG just reads the config).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="attribution_backfill",
    description="Daily 30-day rolling backfill of multi-touch attribution",
    start_date=datetime(2025, 1, 1),
    schedule="0 4 * * *",
    catchup=False,
    tags=[
        "owner:marketing-eng",
        "sla:60min",
        "tier:gold",
        "produces:derived.attribution_touchpoints",
        "consumes:marketing.email_sends",
        "consumes:marketing.ad_spend_daily",
    ],
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
) as dag:
    collect = BashOperator(
        task_id="collect_touchpoints_30d",
        bash_command="echo 'SELECT customer_id, channel, ts FROM marketing.email_sends UNION ALL SELECT ... FROM marketing.ad_spend_daily ...'",
    )
    weight = BashOperator(
        task_id="apply_position_weights",
        bash_command="echo 'WITH ordered AS (SELECT *, row_number() OVER (PARTITION BY order_id ORDER BY ts) AS pos ...)'",
    )
    write = BashOperator(
        task_id="upsert_attribution_table",
        bash_command="echo 'TRUNCATE derived.attribution_touchpoints; INSERT INTO derived.attribution_touchpoints SELECT * FROM weighted'",
    )
    collect >> weight >> write
