"""
payments_reconciliation — reconciles core.payments against Stripe and core.refunds.

Owner: finance-eng@dataclaw.com (FinOps oncall: #finops-alerts)
SLA: daily 06:00 UTC, must complete before 08:00 UTC for the daily revenue email

Sources: core.payments (Stripe webhook ingest), core.refunds, Stripe Reporting API
Output: derived.payments_reconciled (matched + unmatched flags)

CRITICAL: this DAG raises a high-severity alert if more than 0.5% of payments are
unmatched. Do NOT mute — finance uses the daily revenue number for cash forecasting.
The threshold is hard-coded below; change requires CFO sign-off.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator


def check_unmatched_threshold(**_):
    """Fail the DAG if unmatched_pct > 0.5%."""
    pass


with DAG(
    dag_id="payments_reconciliation",
    description="Daily reconciliation of core.payments vs Stripe + refunds",
    start_date=datetime(2025, 1, 1),
    schedule="0 6 * * *",
    catchup=False,
    tags=[
        "owner:finance-eng",
        "sla:120min",
        "tier:platinum",
        "consumes:core.payments",
        "consumes:core.refunds",
        "produces:derived.payments_reconciled",
        "alert:high-severity",
    ],
    default_args={"retries": 1, "retry_delay": timedelta(minutes=15)},
) as dag:
    pull_stripe = BashOperator(
        task_id="pull_stripe_balance_transactions",
        bash_command="echo 'curl https://api.stripe.com/v1/balance_transactions?...'",
    )
    match = BashOperator(
        task_id="match_payments_to_stripe",
        bash_command="echo 'SELECT p.id, p.amount, s.id, s.amount, abs(p.amount - s.amount) AS diff FROM core.payments p LEFT JOIN stripe_pull s ...'",
    )
    apply_refunds = BashOperator(
        task_id="apply_refund_offsets",
        bash_command="echo 'UPDATE matched SET net_amount = amount - coalesce(refund.amount, 0) FROM core.refunds ...'",
    )
    threshold = PythonOperator(
        task_id="enforce_unmatched_threshold",
        python_callable=check_unmatched_threshold,
    )
    pull_stripe >> match >> apply_refunds >> threshold
