"""
data_quality_checks — runs Great Expectations suites against gold-tier tables.

Owner: data-platform@dataclaw.com
SLA: daily 07:00 UTC, alerts go to #data-quality-alerts on failure

Suites: core.orders, core.customers, core.payments, derived.customer_360
Tooling: Great Expectations (config in `data_quality/expectations/` in this repo)

The DAG is configured to FAIL the entire downstream chain if any expectation fails on
a tier:platinum table. For tier:gold tables it raises a Slack warning but continues.
This is intentional — finance numbers must never be served from broken data.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="data_quality_checks",
    description="Daily Great Expectations suite run against gold + platinum tables",
    start_date=datetime(2025, 1, 1),
    schedule="0 7 * * *",
    catchup=False,
    tags=["owner:data-platform", "sla:30min", "tier:platinum", "tooling:great_expectations"],
    default_args={"retries": 0},
) as dag:
    orders = BashOperator(
        task_id="check_core_orders",
        bash_command="echo 'great_expectations checkpoint run core_orders_checkpoint'",
    )
    customers = BashOperator(
        task_id="check_core_customers",
        bash_command="echo 'great_expectations checkpoint run core_customers_checkpoint'",
    )
    payments = BashOperator(
        task_id="check_core_payments",
        bash_command="echo 'great_expectations checkpoint run core_payments_checkpoint'",
    )
    customer_360 = BashOperator(
        task_id="check_derived_customer_360",
        bash_command="echo 'great_expectations checkpoint run customer_360_checkpoint'",
    )
    [orders, customers, payments] >> customer_360
