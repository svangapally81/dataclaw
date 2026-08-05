from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Agent, AgentRun
from app.services.agents.alert_llm_filter import should_alert
from app.services.agents.monitoring_common import (
    MONITORING_AGENTS,
    connector_credentials,
    create_alert_once,
    enabled_monitoring_configs,
    finish_agent_run,
    workspace_or_raise,
)

AGENT_NAME = "dbt_failure_agent"
FAILED_STATUSES = {20, 30, 99}  # dbt Cloud: 20=error, 30=cancelled, 99=skipped/failed


async def _fetch_recent_runs(credentials: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the latest dbt Cloud runs for the configured account."""
    account_id = credentials.get("account_id")
    api_token = credentials.get("api_token")
    if not account_id or not api_token:
        return []
    base_url = (
        credentials.get("base_url")
        or f"https://cloud.getdbt.com/api/v2/accounts/{account_id}"
    ).rstrip("/")
    headers = {"Authorization": f"Token {api_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{base_url}/runs/", headers=headers, params={"limit": 50, "order_by": "-id"})
        if response.status_code >= 400:
            return []
        payload = response.json()
    return payload.get("data") or []


async def run_dbt_failure_agent(session: AsyncSession) -> AgentRun:
    workspace = await workspace_or_raise(session)
    alerting_agent = await session.scalar(
        select(Agent).where(
            Agent.workspace_id == workspace.id,
            Agent.name == "alerting",
            Agent.kind == "background",
            Agent.enabled.is_(True),
        )
    )
    configs = await enabled_monitoring_configs(
        session,
        workspace.id,
        AGENT_NAME,
        MONITORING_AGENTS[AGENT_NAME]["connectors"],
    )
    created = 0
    checked = 0
    for config, connector in configs:
        runs = await _fetch_recent_runs(connector_credentials(connector))
        for run in runs:
            checked += 1
            status = run.get("status")
            try:
                status_int = int(status) if status is not None else None
            except (TypeError, ValueError):
                status_int = None
            if status_int not in FAILED_STATUSES:
                continue
            run_id = str(run.get("id") or "")
            job_id = str(run.get("job_id") or run.get("job", {}).get("id") or "")
            if not run_id:
                continue
            project_name = run.get("project", {}).get("name") if isinstance(run.get("project"), dict) else None
            label = project_name or job_id or "dbt"
            rationale = "LLM filter not configured."
            if alerting_agent is not None:
                keep, rationale = await should_alert(
                    session,
                    alerting_agent,
                    {
                        "connector": "dbt",
                        "run_id": run_id,
                        "job_id": job_id,
                        "status": status,
                        "label": label,
                    },
                )
                if not keep:
                    continue
            alert = await create_alert_once(
                session,
                config,
                workspace_id=workspace.id,
                fingerprint=f"dbt_failure:{connector.id}:{run_id}",
                severity="warning",
                title=f"{label} dbt run failed",
                detail=f"dbt run {run_id} (job {job_id}) ended in status {status}. LLM filter: {rationale}",
                requires_approval=False,
            )
            if alert is not None:
                created += 1

    run_record = AgentRun(
        workspace_id=workspace.id,
        agent_name=MONITORING_AGENTS[AGENT_NAME]["display_name"],
        status="completed",
        summary=f"Checked {checked} dbt runs; created {created} alerts.",
        timeline=[
            {"step": "load_configs", "status": "completed", "detail": f"{len(configs)} enabled configs."},
            {"step": "scan_runs", "status": "completed", "detail": f"{checked} runs checked."},
        ],
    )
    return await finish_agent_run(session, run_record)
