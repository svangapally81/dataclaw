"""Minimal Dagster project for the integration container.

Defines three assets that mirror the database fixtures so the Dagster adapter
can introspect a real running webserver via GraphQL.
"""

from dagster import (
    AssetSelection,
    DailyPartitionsDefinition,
    Definitions,
    RunRequest,
    ScheduleDefinition,
    asset,
    define_asset_job,
    sensor,
)

daily_partitions = DailyPartitionsDefinition(start_date="2026-05-20")


@asset(group_name="revenue", partitions_def=daily_partitions)
def customers() -> int:
    return 3


@asset(group_name="revenue", partitions_def=daily_partitions)
def orders(customers: int) -> int:
    return 4


@asset(group_name="revenue", partitions_def=daily_partitions)
def revenue_by_segment(orders: int, customers: int) -> dict:
    return {"Enterprise": 248000, "Mid-Market": 196500, "Commercial": 121900}


acme_assets = define_asset_job("acme_assets", selection=AssetSelection.assets(customers, orders, revenue_by_segment))

acme_assets_daily = ScheduleDefinition(job=acme_assets, cron_schedule="0 5 * * *", name="acme_assets_daily")


@sensor(job=acme_assets, name="acme_asset_sensor")
def acme_asset_sensor():
    yield RunRequest(run_key="acme-asset-sensor", partition_key="2026-05-20")


defs = Definitions(
    assets=[customers, orders, revenue_by_segment],
    jobs=[acme_assets],
    schedules=[acme_assets_daily],
    sensors=[acme_asset_sensor],
)
