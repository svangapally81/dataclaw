"""
subscription_lifecycle — hourly subscription state machine update.

Owner: billing-eng@dataclaw.com
SLA: hourly, freshness lag must stay under 75 minutes
Sources: core.subscriptions, core.payments, Stripe webhook events
Output: core.subscriptions (in-place state transitions: trial -> active -> past_due -> canceled)

State diagram:
    trial -> active        : on first successful payment
    active -> past_due     : on first failed payment attempt
    past_due -> active     : on successful retry
    past_due -> canceled   : after 3 consecutive failed attempts (dunning policy)
    active/past_due -> paused : on customer self-pause via portal
    paused -> active       : on customer resume

Dunning thresholds are configured in `billing/dunning_policy.yml` (NOT in this DAG).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="subscription_lifecycle",
    description="Hourly Stripe-driven subscription state machine",
    start_date=datetime(2025, 1, 1),
    schedule="@hourly",
    catchup=False,
    tags=[
        "owner:billing-eng",
        "sla:75min",
        "tier:platinum",
        "produces:core.subscriptions",
        "consumes:core.payments",
        "external:stripe",
    ],
    default_args={"retries": 3, "retry_delay": timedelta(minutes=5)},
) as dag:
    pull_events = BashOperator(
        task_id="pull_stripe_webhook_events",
        bash_command="echo 'SELECT * FROM staging.stripe_webhook_events WHERE processed = false ORDER BY received_at'",
    )
    apply_transitions = BashOperator(
        task_id="apply_state_transitions",
        bash_command="echo 'UPDATE core.subscriptions SET status = case ... when ... end, status_changed_at = now() WHERE id = ANY(...)'",
    )
    expire_trials = BashOperator(
        task_id="expire_outstanding_trials",
        bash_command="echo 'UPDATE core.subscriptions SET status = canceled WHERE status = trial AND trial_ends_at < now()'",
    )
    pull_events >> apply_transitions >> expire_trials
