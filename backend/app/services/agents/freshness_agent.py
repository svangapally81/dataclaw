"""Freshness agent — flags empty, slow-growing, or stagnating tables.

For every table in the workspace it compares the synced row_count to a stored
high-water mark (kept in `tags` as `freshness:<count>`). If the table is empty
or the row count has not changed since the last run, it raises an Alert.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AgentRun, Alert, TableAsset, Workspace
from app.services.settings_store import hydrate_vector_store
from app.services.vector_store import vector_store

PREFIX = "freshness_hwm:"


def _high_water_mark(table: TableAsset) -> int | None:
    for tag in table.tags or []:
        if tag.startswith(PREFIX):
            try:
                return int(tag.split(":", 1)[1])
            except ValueError:
                return None
    return None


def _set_high_water_mark(table: TableAsset, value: int) -> None:
    rest = [tag for tag in (table.tags or []) if not tag.startswith(PREFIX)]
    rest.append(f"{PREFIX}{value}")
    table.tags = sorted(rest)


async def run_freshness_agent(session: AsyncSession) -> AgentRun:
    workspace = await session.scalar(select(Workspace).limit(1))
    if workspace is None:
        raise RuntimeError("Workspace has not been seeded.")
    await hydrate_vector_store(session, workspace.id)

    tables = list((await session.scalars(select(TableAsset))).all())
    fresh = 0
    flagged: list[TableAsset] = []
    new_alerts: list[Alert] = []
    for table in tables:
        previous = _high_water_mark(table)
        current = table.row_count
        if current == 0:
            table.freshness_status = "empty"
            flagged.append(table)
        elif previous is not None and current == previous:
            table.freshness_status = "stale"
            flagged.append(table)
        else:
            table.freshness_status = "fresh"
            fresh += 1
        _set_high_water_mark(table, current)

    for table in flagged:
        already = await session.scalar(
            select(Alert).where(
                Alert.workspace_id == workspace.id,
                Alert.title == f"Freshness: {table.name}",
                Alert.resolved.is_(False),
            )
        )
        if already:
            continue
        severity = "critical" if table.freshness_status == "empty" else "warning"
        alert = Alert(
                workspace_id=workspace.id,
                severity=severity,
                title=f"Freshness: {table.name}",
                detail=(
                    f"Table {table.name} is {table.freshness_status} "
                    f"(row_count={table.row_count})."
                ),
                requires_approval=True,
            )
        session.add(alert)
        new_alerts.append(alert)

    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Freshness Agent",
        status="completed",
        summary=f"Checked {len(tables)} tables; {fresh} fresh, {len(flagged)} flagged.",
        timeline=[
            {"step": "load_tables", "status": "completed", "detail": f"{len(tables)} tables."},
            {"step": "evaluate_freshness", "status": "completed", "detail": f"{fresh} fresh, {len(flagged)} flagged."},
        ],
    )
    session.add(run)
    await session.flush()
    all_alerts = list(
        (
            await session.scalars(
                select(Alert).where(Alert.workspace_id == workspace.id, Alert.resolved.is_(False))
            )
        ).all()
    )
    await vector_store.upsert_agent_runs(workspace.id, [run], all_alerts)
    await session.commit()
    await session.refresh(run)
    return run
