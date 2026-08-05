"""
signup_to_activation_funnel — daily activation-funnel rebuild.

Owner: product-analytics@dataclaw.com
SLA: daily 05:00 UTC
Sources: core.customers, events.product_events, core.subscriptions
Output: derived.activation_funnel (one row per customer, columns for each milestone reached)

Funnel milestones (in order):
    signed_up -> verified_email -> created_first_workspace
        -> imported_first_dataset -> ran_first_query -> activated

"Activated" is currently defined as 3+ queries within first 7 days. This is the
North Star metric for the growth team. If you change this definition, update:
  1. The metrics handbook in Notion
  2. The Looker dashboard "Growth — Activation Funnel" (model: activation_v2)
  3. This DAG's `is_activated()` helper below
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="signup_to_activation_funnel",
    description="Daily activation-funnel rebuild for growth analytics",
    start_date=datetime(2025, 1, 1),
    schedule="0 5 * * *",
    catchup=False,
    tags=[
        "owner:product-analytics",
        "sla:30min",
        "tier:gold",
        "produces:derived.activation_funnel",
        "consumes:core.customers",
        "consumes:events.product_events",
    ],
    default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
) as dag:
    materialize_milestones = BashOperator(
        task_id="materialize_milestone_events",
        bash_command="echo 'SELECT user_id, event_type, min(created_at) FROM events.product_events WHERE event_type IN (signed_up, verified_email, ...) GROUP BY 1, 2'",
    )
    pivot = BashOperator(
        task_id="pivot_milestones_to_columns",
        bash_command="echo 'INSERT INTO derived.activation_funnel (customer_id, signed_up_at, verified_email_at, ...) SELECT ...'",
    )
    flag_activated = BashOperator(
        task_id="flag_activated_users",
        bash_command="echo 'UPDATE derived.activation_funnel SET activated = (queries_in_first_7d >= 3) WHERE activated IS NULL'",
    )
    materialize_milestones >> pivot >> flag_activated
