from __future__ import annotations

from dagster import DailyPartitionsDefinition, Definitions, asset


daily_partitions = DailyPartitionsDefinition(start_date="2026-01-01")


@asset(group_name="core_assets")
def core_customers() -> int:
    return 1247


@asset(group_name="core_assets")
def core_orders(core_customers: int) -> int:
    return core_customers * 4


@asset(group_name="marketing_assets")
def marketing_campaigns() -> int:
    return 200


@asset(group_name="marketing_assets")
def campaign_spend(marketing_campaigns: int) -> float:
    return float(marketing_campaigns * 175)


@asset(group_name="failing_assets")
def failing_asset() -> None:
    raise RuntimeError("seeded Phase H Dagster failure: partition source missing")


@asset(group_name="partitioned_daily", partitions_def=daily_partitions)
def daily_revenue_snapshot() -> int:
    return 5000


defs = Definitions(
    assets=[
        core_customers,
        core_orders,
        marketing_campaigns,
        campaign_spend,
        failing_asset,
        daily_revenue_snapshot,
    ]
)
