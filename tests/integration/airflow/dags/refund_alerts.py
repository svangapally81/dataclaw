"""
refund_alerts — every-15-min refund spike detector.

Owner: finance-eng@dataclaw.com
Cadence: every 15 minutes
Trigger: PagerDuty page if refund_count_15min > 3x rolling-7d average for the same window-of-day

Sources: core.refunds
No table is produced — this DAG only emits Slack messages and PagerDuty incidents.

Why so aggressive: in 2024 a fraud ring opened ~200 trial accounts and refund-charged
back through Stripe before our fraud team noticed. We lost ~$45k. This alert reduces
the detection window from "next morning" to "within 30 minutes". Don't tune the
threshold lower without finance + security signoff.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="refund_alerts",
    description="15-minute refund-spike pager",
    start_date=datetime(2025, 1, 1),
    schedule="*/15 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["owner:finance-eng", "sla:15min", "tier:platinum", "consumes:core.refunds", "alert:pagerduty"],
    default_args={"retries": 0},
) as dag:
    measure = BashOperator(
        task_id="measure_refund_rate_15min",
        bash_command="echo 'SELECT count(*) FROM core.refunds WHERE created_at > now() - interval 15 minutes'",
    )
    compare = BashOperator(
        task_id="compare_to_rolling_7d_baseline",
        bash_command="echo 'SELECT avg(c) FROM (SELECT count(*) AS c FROM core.refunds WHERE created_at BETWEEN ... GROUP BY ...)'",
    )
    page = BashOperator(
        task_id="raise_pagerduty_if_spike",
        bash_command="echo 'curl -X POST https://events.pagerduty.com/v2/enqueue -d ... only if ratio > 3.0'",
    )
    measure >> compare >> page
