from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AgentRun, QueryAudit
from app.services.agents.monitoring_common import (
    MONITORING_AGENTS,
    create_alert_once,
    enabled_monitoring_configs,
    finish_agent_run,
    utc_now,
    workspace_or_raise,
)

AGENT_NAME = "query_cost_agent"
LOOKBACK = timedelta(minutes=30)


async def run_query_cost_agent(session: AsyncSession) -> AgentRun:
    workspace = await workspace_or_raise(session)
    configs = await enabled_monitoring_configs(
        session,
        workspace.id,
        AGENT_NAME,
        MONITORING_AGENTS[AGENT_NAME]["connectors"],
    )
    cutoff = utc_now() - LOOKBACK
    created = 0
    checked = 0
    for config, connector in configs:
        thresholds = (getattr(config, "thresholds", {}) or {}) | MONITORING_AGENTS[AGENT_NAME].get("thresholds", {})
        max_duration_ms = int(thresholds.get("duration_ms", 5000))
        max_rows = int(thresholds.get("rows_returned", 10000))
        rows = await session.scalars(
            select(QueryAudit).where(
                QueryAudit.workspace_id == workspace.id,
                QueryAudit.connector_slug == connector.slug,
                QueryAudit.executed_at >= cutoff,
            )
        )
        for audit in rows.all():
            checked += 1
            offenders: list[str] = []
            if audit.duration_ms and audit.duration_ms >= max_duration_ms:
                offenders.append(f"duration {audit.duration_ms}ms ≥ {max_duration_ms}ms")
            if audit.rows_returned and audit.rows_returned >= max_rows:
                offenders.append(f"rows {audit.rows_returned} ≥ {max_rows}")
            if not offenders:
                continue
            preview = (audit.sql or "").strip()
            if len(preview) > 120:
                preview = preview[:117] + "…"
            alert = await create_alert_once(
                session,
                config,
                workspace_id=workspace.id,
                fingerprint=f"query_cost:{connector.slug}:{audit.id}",
                severity="info",
                title=f"Slow query on {connector.slug}",
                detail=f"{preview} — {'; '.join(offenders)}",
                requires_approval=False,
            )
            if alert is not None:
                created += 1

    run_record = AgentRun(
        workspace_id=workspace.id,
        agent_name=MONITORING_AGENTS[AGENT_NAME]["display_name"],
        status="completed",
        summary=f"Checked {checked} queries; created {created} alerts.",
        timeline=[
            {"step": "load_configs", "status": "completed", "detail": f"{len(configs)} enabled configs."},
            {"step": "scan_audit", "status": "completed", "detail": f"{checked} queries scanned."},
        ],
    )
    return await finish_agent_run(session, run_record)
