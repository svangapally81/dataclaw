from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AgentRun, Dataset, TableAsset
from app.services.agents.monitoring_common import (
    MONITORING_AGENTS,
    connector_credentials,
    create_alert_once,
    enabled_monitoring_configs,
    finish_agent_run,
    workspace_or_raise,
)
from app.services.connectors.adapters import adapter_for

logger = logging.getLogger("dataclaw.agents.schema_drift")

AGENT_NAME = "schema_drift_agent"


def _columns_index(columns: list[dict[str, Any]] | None) -> dict[str, str]:
    if not columns:
        return {}
    out: dict[str, str] = {}
    for column in columns:
        if not isinstance(column, dict):
            continue
        name = column.get("name")
        if not name:
            continue
        out[str(name).lower()] = str(column.get("type") or "").lower()
    return out


def _diff_columns(prev: dict[str, str], curr: dict[str, str]) -> tuple[list[str], list[str], list[tuple[str, str, str]]]:
    dropped = [name for name in prev if name not in curr]
    added = [name for name in curr if name not in prev]
    type_changed: list[tuple[str, str, str]] = []
    for name, prev_type in prev.items():
        if name in curr and curr[name] != prev_type:
            type_changed.append((name, prev_type, curr[name]))
    return dropped, added, type_changed


async def run_schema_drift_agent(session: AsyncSession) -> AgentRun:
    workspace = await workspace_or_raise(session)
    configs = await enabled_monitoring_configs(
        session,
        workspace.id,
        AGENT_NAME,
        MONITORING_AGENTS[AGENT_NAME]["connectors"],
    )
    created = 0
    checked = 0
    for config, connector in configs:
        try:
            payload = await adapter_for(connector.slug).sync(connector_credentials(connector))
        except Exception as exc:
            logger.warning(
                "schema_drift_sync_failed",
                extra={"_connector": connector.slug, "_error": exc.__class__.__name__},
            )
            continue
        live_tables = {t["name"]: t for t in payload.get("tables") or [] if t.get("name")}
        rows = await session.scalars(
            select(TableAsset).join(Dataset).where(
                Dataset.workspace_id == workspace.id,
                Dataset.connector_id == connector.id,
            )
        )
        for asset in rows.all():
            checked += 1
            live = live_tables.get(asset.name)
            if live is None:
                continue
            prev_cols = _columns_index(asset.columns)
            curr_cols = _columns_index(live.get("columns"))
            if not prev_cols or not curr_cols:
                continue
            dropped, added, type_changed = _diff_columns(prev_cols, curr_cols)
            if not (dropped or type_changed):
                continue
            parts: list[str] = []
            if dropped:
                parts.append(f"dropped: {', '.join(dropped)}")
            if type_changed:
                parts.append("type changed: " + ", ".join(f"{n} ({a}→{b})" for n, a, b in type_changed))
            if added:
                parts.append(f"added: {', '.join(added)}")
            detail = "; ".join(parts)
            alert = await create_alert_once(
                session,
                config,
                workspace_id=workspace.id,
                fingerprint=f"schema_drift:{connector.id}:{asset.name}",
                severity="warning",
                title=f"Schema drift in {asset.name}",
                detail=detail,
                requires_approval=False,
            )
            if alert is not None:
                created += 1

    run_record = AgentRun(
        workspace_id=workspace.id,
        agent_name=MONITORING_AGENTS[AGENT_NAME]["display_name"],
        status="completed",
        summary=f"Checked {checked} tables; created {created} drift alerts.",
        timeline=[
            {"step": "load_configs", "status": "completed", "detail": f"{len(configs)} enabled configs."},
            {"step": "diff_columns", "status": "completed", "detail": f"{checked} tables compared."},
        ],
    )
    return await finish_agent_run(session, run_record)
