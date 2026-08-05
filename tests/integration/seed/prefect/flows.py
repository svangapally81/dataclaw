from __future__ import annotations

from prefect import flow, task


@task
def fail_task() -> None:
    raise RuntimeError("seeded Phase H Prefect failure: warehouse timeout")


@flow(name="daily_sync")
def daily_sync() -> str:
    return "ok"


@flow(name="failing_flow")
def failing_flow() -> None:
    fail_task()


@flow(name="scheduled_hourly")
def scheduled_hourly() -> str:
    return "scheduled"
