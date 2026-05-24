"""
cohort_analysis — weekly retention cohort table for product analytics.

Owner: product-analytics@dataclaw.com
SLA: every Sunday 23:00 UTC, ready by Monday morning standup
Sources: core.customers, core.orders, events.product_events
Output: derived.cohort_retention (cohort_month, weeks_since_signup, active_customers, retention_pct)

Definition of "active": at least one tracked event in events.product_events in the
window. The exact event-list is in `analytics-models/active_user_definition.sql` —
this DAG just calls that view.

Last redefined 2025-01: we changed from "any login event" to "any meaningful action"
(checkout_started, dashboard_viewed, report_generated). Comparing pre-2025 cohorts
to post-2025 cohorts is misleading; the migration note is in the metrics handbook.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="cohort_analysis",
    description="Weekly retention cohort recompute",
    start_date=datetime(2025, 1, 1),
    schedule="0 23 * * SUN",
    catchup=False,
    tags=[
        "owner:product-analytics",
        "sla:60min",
        "tier:silver",
        "produces:derived.cohort_retention",
        "consumes:core.customers",
        "consumes:events.product_events",
    ],
    default_args={"retries": 1, "retry_delay": timedelta(minutes=15)},
) as dag:
    build_cohorts = BashOperator(
        task_id="build_signup_cohorts",
        bash_command="echo 'CREATE TEMP TABLE cohorts AS SELECT id, date_trunc(month, created_at) AS cohort FROM core.customers'",
    )
    measure_activity = BashOperator(
        task_id="measure_weekly_activity",
        bash_command="echo 'SELECT user_id, week, count(*) FROM events.product_events WHERE event_type IN (checkout_started, dashboard_viewed, report_generated) GROUP BY 1, 2'",
    )
    pivot = BashOperator(
        task_id="pivot_cohort_x_week",
        bash_command="echo 'INSERT INTO derived.cohort_retention SELECT cohort, week, count(distinct user_id) FROM activity JOIN cohorts ...'",
    )
    build_cohorts >> measure_activity >> pivot
