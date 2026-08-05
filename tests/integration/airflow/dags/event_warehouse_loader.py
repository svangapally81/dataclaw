"""
event_warehouse_loader — streams Kafka product-event topic into events.product_events.

Owner: data-platform@dataclaw.com
Cadence: every 5 minutes (microbatch — true streaming sink is on the v0.4 roadmap)
Source: Kafka topic `product-events-v3` (NOTE: v1 and v2 topics are decommissioned)
Output: events.product_events (~5M rows/day in production; partitioned by event_date)

Schema-evolution caveat: the v3 topic has a new optional `device_context` column
(struct of os/browser/version). If a downstream model breaks because of an unknown
column, that's why — `device_context` is added as JSONB and won't fail strict-schema
consumers, but anything using SELECT * will pick it up.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="event_warehouse_loader",
    description="5-minute microbatch from Kafka product-events-v3 into events.product_events",
    start_date=datetime(2025, 1, 1),
    schedule="*/5 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=[
        "owner:data-platform",
        "sla:10min",
        "tier:gold",
        "produces:events.product_events",
        "external:kafka",
    ],
    default_args={"retries": 5, "retry_delay": timedelta(minutes=1)},
) as dag:
    consume = BashOperator(
        task_id="consume_kafka_microbatch",
        bash_command="echo 'kcat -C -b broker:9092 -t product-events-v3 -o stored -e | jq -c .'",
    )
    parse = BashOperator(
        task_id="parse_and_validate_schema",
        bash_command="echo 'python parse_events.py --schema product_events_v3.avsc'",
    )
    load = BashOperator(
        task_id="copy_into_partition",
        bash_command="echo 'COPY events.product_events FROM STDIN WITH (FORMAT csv)'",
    )
    consume >> parse >> load
