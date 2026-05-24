"""
email_send_loader — loads marketing.email_sends from SendGrid Events API.

Owner: marketing-eng@dataclaw.com (Slack: #marketing-data)
SLA: hourly, freshness lag must stay under 90 minutes
Source: SendGrid Events API (https://docs.sendgrid.com/api-reference/event-webhooks)
Output: marketing.email_sends (raw event rows; one row per send/open/click/bounce)

KNOWN ISSUE: SendGrid occasionally returns duplicate event_ids after delivery
retries. The merge step uses ON CONFLICT (event_id) DO NOTHING which silently
drops duplicates. If you see open_rate calculations off by ~2%, check the
ratio of dropped events in the run log.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="email_send_loader",
    description="Hourly load of SendGrid email events into marketing.email_sends",
    start_date=datetime(2025, 1, 1),
    schedule="@hourly",
    catchup=False,
    tags=["owner:marketing-eng", "sla:90min", "tier:silver", "produces:marketing.email_sends", "external:sendgrid"],
    default_args={"retries": 3, "retry_delay": timedelta(minutes=2)},
) as dag:
    fetch = BashOperator(
        task_id="fetch_sendgrid_events",
        bash_command="echo 'curl -H Authorization:Bearer ${SENDGRID_API_KEY} https://api.sendgrid.com/v3/messages/events?...'",
    )
    parse = BashOperator(
        task_id="parse_and_normalize",
        bash_command="echo 'jq < raw.json -c .events[] | psql -c COPY staging.email_events FROM STDIN'",
    )
    merge = BashOperator(
        task_id="merge_into_marketing",
        bash_command="echo 'INSERT INTO marketing.email_sends SELECT * FROM staging.email_events ON CONFLICT (event_id) DO NOTHING'",
    )
    fetch >> parse >> merge
