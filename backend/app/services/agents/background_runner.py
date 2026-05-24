from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.session import get_session
from app.models.domain import Agent, AgentMcpGrant, AgentRun, Connector
from app.services.agents.airflow_failure_agent import run_airflow_failure_agent
from app.services.agents.alert_llm_filter import should_alert
from app.services.agents.dbt_failure_agent import run_dbt_failure_agent
from app.services.agents.docs_agent import run_docs_agent
from app.services.agents.freshness_agent import run_freshness_agent
from app.services.agents.lineage_agent import run_lineage_agent
from app.services.agents.metadata_agent import run_metadata_agent
from app.services.agents.monitoring_common import (
    connector_credentials,
    create_alert_once,
    finish_agent_run,
    workspace_or_raise,
)
from app.services.agents.query_cost_agent import run_query_cost_agent
from app.services.agents.runtime import BudgetExceeded, apply_default_budgets, enforce_run_budget
from app.services.agents.schema_drift_agent import run_schema_drift_agent
from app.services.connectors.adapters import adapter_for
from app.services.connectors.catalog import CATALOG_BY_SLUG, ConnectorCategory
from app.services.ingestion.auto_sync import auto_sync_all_connectors
from app.services.ingestion.reconciler import reconcile_wiki_disk_edits
from app.services.knowledge_compile.service import CompileService
from app.services.mcp_executor import execute_mcp_tool
from app.services.retrieval import BrainRetriever

BackgroundHandler = Callable[[AsyncSession], Awaitable[AgentRun | int | None]]
logger = logging.getLogger("dataclaw.background_runner")
LEASE_SECONDS = 120


async def _run_alerting(session: AsyncSession) -> AgentRun | None:
    await run_airflow_failure_agent(session)
    await run_dbt_failure_agent(session)
    return await _run_generic_orchestration_failure_agent(session)


async def _run_data_quality(session: AsyncSession) -> AgentRun | None:
    await run_schema_drift_agent(session)
    return await run_query_cost_agent(session)


FAILURE_STATES = {"failed", "failure", "error", "errored", "cancelled", "canceled", "crashed", "timeout", "timed_out"}


async def _run_generic_orchestration_failure_agent(session: AsyncSession) -> AgentRun:
    workspace = await workspace_or_raise(session)
    alerting_agent = await session.scalar(
        select(Agent).where(
            Agent.workspace_id == workspace.id,
            Agent.name == "alerting",
            Agent.kind == "background",
            Agent.enabled.is_(True),
        )
    )
    if alerting_agent is None:
        run = AgentRun(
            workspace_id=workspace.id,
            agent_name="Generic Orchestration Failure Agent",
            status="completed",
            summary="Alerting agent is disabled; no generic orchestration connectors scanned.",
            timeline=[],
        )
        return await finish_agent_run(session, run)
    grants = list(
        (
            await session.scalars(
                select(AgentMcpGrant).where(
                    AgentMcpGrant.agent_id == alerting_agent.id,
                    AgentMcpGrant.read_enabled.is_(True),
                )
            )
        ).all()
    )
    orchestration_slugs = {
        slug
        for slug, definition in CATALOG_BY_SLUG.items()
        if definition.category == ConnectorCategory.ORCHESTRATION
    }
    connector_slugs = ({grant.connector_slug for grant in grants} & orchestration_slugs) - {"airflow", "dbt"}
    connectors = (
        list(
            (
                await session.scalars(
                    select(Connector).where(
                        Connector.workspace_id == workspace.id,
                        Connector.slug.in_(connector_slugs),
                        Connector.credential_state == "configured",
                    )
                )
            ).all()
        )
        if connector_slugs
        else []
    )
    checked = 0
    created = 0
    since = datetime.now(UTC) - timedelta(minutes=max(alerting_agent.cadence_minutes or 5, 5))
    for connector in connectors:
        try:
            failed_runs = await adapter_for(connector.slug).list_failed_runs(connector_credentials(connector), since=since)
        except Exception as exc:
            alert = await create_alert_once(
                session,
                None,
                workspace_id=workspace.id,
                fingerprint=f"orchestration_adapter_error:{connector.id}:{exc.__class__.__name__}",
                severity="warning",
                title=f"{connector.display_name} scan failed",
                detail=f"{connector.slug} adapter could not fetch run status: {exc}",
                requires_approval=False,
            )
            if alert is not None:
                created += 1
            continue
        for item in failed_runs:
            checked += 1
            label = _failure_label(item)
            brain_context = await _background_brain_context(
                session,
                workspace.id,
                connector.slug,
                f"{label} {item.get('name') or ''} {item.get('status') or item.get('state') or ''}",
            )
            keep, rationale = await should_alert(
                session,
                alerting_agent,
                {
                    "connector": connector.slug,
                    "label": label,
                    "status": item.get("status") or item.get("state"),
                    "payload": item,
                    "brain_context": brain_context,
                },
            )
            if not keep:
                continue
            alert = await create_alert_once(
                session,
                None,
                workspace_id=workspace.id,
                fingerprint=f"orchestration_failure:{connector.id}:{label}",
                severity="critical",
                title=f"{label} failed in {connector.display_name}",
                detail=_alert_detail_with_brain_context(connector.slug, label, rationale, brain_context),
                requires_approval=False,
            )
            if alert is not None:
                created += 1
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Generic Orchestration Failure Agent",
        status="completed",
        summary=f"Scanned {len(connectors)} orchestration connectors; checked {checked} failed items; created {created} alerts.",
        timeline=[
            {"step": "load_connectors", "status": "completed", "detail": f"{len(connectors)} granted connectors."},
            {"step": "scan_failures", "status": "completed", "detail": f"{checked} failed items found."},
        ],
    )
    return await finish_agent_run(session, run)


async def _background_brain_context(
    session: AsyncSession,
    workspace_id: str,
    connector_slug: str,
    subject: str,
) -> list[dict[str, str]]:
    context = await BrainRetriever(session).retrieve(
        workspace_id,
        f"Assess orchestration failure from {connector_slug}: {subject}".strip(),
        connector_slugs=[connector_slug],
        top_k_nodes=5,
        chunks_per_node=1,
    )
    return [
        {
            "name": node.canonical_name,
            "connector_slug": node.connector_slug,
            "summary": node.summary,
        }
        for node in context.nodes[:5]
        if getattr(node, "summary", "")
    ]


def _alert_detail_with_brain_context(
    connector_slug: str,
    label: str,
    rationale: str,
    brain_context: list[dict[str, str]],
) -> str:
    detail = f"{connector_slug} reported failed item {label}. LLM filter: {rationale}"
    if not brain_context:
        return detail
    summaries = "; ".join(f"{item['name']}: {item['summary']}" for item in brain_context[:3])
    return f"{detail}. Related brain context: {summaries}"


def _failure_items(payload: object) -> list[dict]:
    failures: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        status = str(value.get("status") or value.get("state") or value.get("sync_state") or value.get("last_sync_state") or "").lower()
        if status in FAILURE_STATES or any(term in status for term in ("fail", "error")):
            failures.append(value)
            return
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                visit(nested)

    visit(payload)
    return failures


def _failure_label(item: dict) -> str:
    for key in ("id", "run_id", "job_id", "connection_id", "connector_id", "name", "flow_run_id"):
        if item.get(key):
            return str(item[key])
    return str(abs(hash(json.dumps(item, sort_keys=True, default=str))))


async def _run_reconciler(session: AsyncSession) -> AgentRun:
    workspace = await workspace_or_raise(session)
    changed = await reconcile_wiki_disk_edits(session, workspace.id)
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Reconciliation Agent",
        status="completed",
        summary=f"Reconciled {changed} disk-edited wiki pages.",
        timeline=[
            {"step": "scan_wiki_pages", "status": "completed", "detail": f"{changed} page(s) changed on disk."},
        ],
    )
    return await finish_agent_run(session, run)


async def _run_compile_agent(session: AsyncSession) -> int:
    from app.models.domain import Workspace

    count = 0
    for workspace in (await session.scalars(select(Workspace))).all():
        await CompileService(session).compile(workspace.id)
        count += 1
    return count


SYSTEM_HANDLERS: dict[str, BackgroundHandler] = {
    "alerting": _run_alerting,
    "data_quality": _run_data_quality,
    "docs": run_docs_agent,
    "freshness": run_freshness_agent,
    "ingestion": auto_sync_all_connectors,
    "lineage": run_lineage_agent,
    "metadata": run_metadata_agent,
    "reconciliation": _run_reconciler,
    "reconciler": _run_reconciler,
    "compile-agent": _run_compile_agent,
}

SYSTEM_RUN_NAMES: dict[str, tuple[str, ...]] = {
    "alerting": ("Airflow Failure Agent", "dbt Failure Agent"),
    "data_quality": ("Schema Drift Agent", "Query Cost Agent"),
    "docs": ("Docs Agent",),
    "freshness": ("Freshness Agent",),
    "ingestion": ("auto_sync",),
    "lineage": ("Lineage Agent",),
    "metadata": ("Metadata Agent",),
    "compile-agent": ("knowledge_compile",),
}


async def due_background_agents(session: AsyncSession, *, now: datetime | None = None) -> list[Agent]:
    now = now or datetime.now(UTC)
    await reclaim_expired_agent_runs(session, now=now)
    agents = list(
        (
            await session.scalars(
                select(Agent).where(
                    Agent.kind == "background",
                    Agent.enabled.is_(True),
                )
            )
        ).all()
    )
    due: list[Agent] = []
    for agent in agents:
        cadence = agent.cadence_minutes or 60
        run_names = (agent.display_name, *SYSTEM_RUN_NAMES.get(agent.name, ()))
        active = await session.scalar(
            select(AgentRun)
            .where(
                AgentRun.workspace_id == agent.workspace_id,
                AgentRun.agent_name.in_(run_names),
                AgentRun.state == "running",
                AgentRun.lease_expires_at.is_not(None),
            )
            .order_by(desc(AgentRun.created_at))
            .limit(1)
        )
        if active is not None:
            lease_expires_at = active.lease_expires_at
            if lease_expires_at and lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
            if lease_expires_at and lease_expires_at > now:
                continue
        if agent.force_run_requested_at is not None:
            due.append(agent)
            continue
        latest = await session.scalar(
            select(AgentRun)
            .where(AgentRun.workspace_id == agent.workspace_id, AgentRun.agent_name.in_(run_names))
            .order_by(desc(AgentRun.created_at))
            .limit(1)
        )
        if latest is None:
            due.append(agent)
            continue
        last_run_at = latest.created_at
        if last_run_at.tzinfo is None:
            last_run_at = last_run_at.replace(tzinfo=UTC)
        if now - last_run_at >= timedelta(minutes=cadence):
            due.append(agent)
    return due


async def _reclaim_expired_agent_runs_in_session(
    session: AsyncSession,
    *,
    now: datetime,
    commit: bool,
) -> int:
    now = now or datetime.now(UTC)
    runs = list(
        (
            await session.scalars(
                select(AgentRun).where(
                    AgentRun.state == "running",
                    AgentRun.lease_expires_at.is_not(None),
                )
            )
        ).all()
    )
    reclaimed = 0
    for run in runs:
        lease_expires_at = run.lease_expires_at
        if lease_expires_at and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        if lease_expires_at is None or lease_expires_at > now:
            continue
        run.state = "failed"
        run.status = "failed"
        run.finished_at = now
        run.error_message = "Lease expired before the background run completed."
        run.summary = run.summary or "Background run lease expired."
        run.duration_ms = _duration_ms(run.started_at, now)
        run.timeline = [
            *(run.timeline or []),
            {"event": "lease_expired", "at": now.isoformat(), "lease_token": run.lease_token},
        ]
        reclaimed += 1
    if reclaimed:
        if commit:
            await session.commit()
        else:
            await session.flush()
    return reclaimed


async def reclaim_expired_agent_runs(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    bind = session.bind
    if bind is None:
        return await _reclaim_expired_agent_runs_in_session(session, now=now, commit=False)
    SessionLocal = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as reclaim_session:
        return await _reclaim_expired_agent_runs_in_session(reclaim_session, now=now, commit=True)


async def run_due_background_agents(session: AsyncSession, *, now: datetime | None = None) -> list[object]:
    due_agents = await due_background_agents(session, now=now)
    if not due_agents:
        return []

    async def run_one(agent_id: str) -> object:
        async for agent_session in get_session():
            agent = await agent_session.get(Agent, agent_id)
            if agent is None:
                return None
            lease_started_at = datetime.now(UTC)
            queue_run = AgentRun(
                workspace_id=agent.workspace_id,
                agent_name=agent.display_name,
                status="running",
                state="running",
                summary=f"{agent.display_name} queued by background runner.",
                timeline=[{"event": "lease_acquired", "at": lease_started_at.isoformat()}],
                started_at=lease_started_at,
                lease_token=str(uuid.uuid4()),
                lease_expires_at=lease_started_at + timedelta(seconds=LEASE_SECONDS),
                idempotency_key=f"background:{agent.id}:{uuid.uuid4()}",
            )
            apply_default_budgets(queue_run, kind="background")
            agent_session.add(queue_run)
            await agent_session.commit()
            try:
                handler = SYSTEM_HANDLERS.get(agent.name)
                if handler is not None:
                    result = await handler(agent_session)
                elif not agent.is_system:
                    result = await run_custom_background_agent(agent_session, agent, run_id=queue_run.id)
                else:
                    result = None
                agent.force_run_requested_at = None
                lease_finished_at = datetime.now(UTC)
                queue_run.status = "completed"
                queue_run.state = "completed"
                queue_run.finished_at = lease_finished_at
                queue_run.duration_ms = _duration_ms(queue_run.started_at, lease_finished_at)
                queue_run.timeline = [
                    *(queue_run.timeline or []),
                    {"event": "completed", "at": lease_finished_at.isoformat()},
                ]
                await agent_session.commit()
                return result
            except BudgetExceeded as exc:
                lease_finished_at = datetime.now(UTC)
                agent.force_run_requested_at = None
                queue_run.status = "timed_out"
                queue_run.state = "timed_out"
                queue_run.summary = "Agent run exceeded its configured budget."
                queue_run.error_message = exc.__class__.__name__
                queue_run.finished_at = lease_finished_at
                queue_run.duration_ms = _duration_ms(queue_run.started_at, lease_finished_at)
                queue_run.timeline = [
                    *(queue_run.timeline or []),
                    {"event": "timed_out", "at": lease_finished_at.isoformat()},
                ]
                await agent_session.commit()
                return queue_run
            except Exception as exc:
                logger.exception("background_agent_failed", extra={"_agent": agent.name})
                lease_finished_at = datetime.now(UTC)
                agent.force_run_requested_at = None
                queue_run.status = "failed"
                queue_run.state = "failed"
                queue_run.summary = f"{agent.display_name} failed."
                queue_run.error_message = exc.__class__.__name__
                queue_run.finished_at = lease_finished_at
                queue_run.duration_ms = _duration_ms(queue_run.started_at, lease_finished_at)
                queue_run.timeline = [
                    *(queue_run.timeline or []),
                    {"event": "failed", "at": lease_finished_at.isoformat(), "error": exc.__class__.__name__},
                ]
                await agent_session.commit()
                await agent_session.refresh(queue_run)
                return queue_run

    semaphore = asyncio.Semaphore(max(1, min(8, len(due_agents))))

    async def bounded(agent_id: str) -> object:
        async with semaphore:
            return await run_one(agent_id)

    return await asyncio.gather(*(bounded(agent.id) for agent in due_agents), return_exceptions=False)


def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int:
    if started_at is None:
        return 0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return int((finished_at - started_at).total_seconds() * 1000)


async def run_custom_background_agent(session: AsyncSession, agent: Agent, *, run_id: str | None = None) -> AgentRun:
    workspace_id = agent.workspace_id
    connector = await session.get(Connector, agent.target_connector_id) if agent.target_connector_id else None
    sql_query = agent.sql_query
    if not sql_query and (agent.thresholds or {}).get("min_row_count"):
        match = re.search(r"([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)", agent.system_prompt or "")
        if match:
            sql_query = f"select count(*) as row_count from {match.group(1)}"
    if connector is None or not sql_query:
        run = AgentRun(
            workspace_id=workspace_id,
            agent_name=agent.display_name,
            status="skipped",
            summary="Custom background agent needs a target connector and SQL query.",
            timeline=[],
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run

    grant = await session.scalar(
        select(AgentMcpGrant).where(
            AgentMcpGrant.agent_id == agent.id,
            AgentMcpGrant.connector_slug == connector.slug,
            AgentMcpGrant.read_enabled.is_(True),
        )
    )
    if grant is None:
        run = AgentRun(
            workspace_id=workspace_id,
            agent_name=agent.display_name,
            status="skipped",
            summary=f"Custom background agent has no read grant for {connector.slug}.",
            timeline=[],
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run

    engine = create_async_engine(get_settings().demo_database_url, pool_pre_ping=True)
    if connector.slug == "sqlite" and connector.sync_summary and connector.sync_summary.get("database_path"):
        engine = create_async_engine(f"sqlite+aiosqlite:///{connector.sync_summary['database_path']}", pool_pre_ping=True)
    try:
        await enforce_run_budget(session, run_id, estimated_tokens=len(sql_query.split()))
        result = await execute_mcp_tool(
            session=session,
            engine=engine,
            connector_slug=connector.slug,
            tool_name="read_query_select",
            arguments={"sql": sql_query},
            agent_id=agent.id,
            user_email="background-agent@dataclaw.local",
            run_id=run_id,
        )
    finally:
        await engine.dispose()

    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    threshold = int((agent.thresholds or {}).get("rows_gt", 0))
    should_fire = len(rows) > threshold
    created_alert = False
    if should_fire:
        digest = hashlib.sha1(str(rows).encode("utf-8")).hexdigest()[:16]
        alert = await create_alert_once(
            session,
            None,
            workspace_id=workspace_id,
            fingerprint=f"custom:{agent.id}:{digest}",
            severity=str((agent.thresholds or {}).get("severity", "warning")),
            title=f"{agent.display_name} threshold matched",
            detail=f"Custom agent returned {len(rows)} rows (threshold rows_gt={threshold}).",
        )
        created_alert = alert is not None
    run = AgentRun(
        workspace_id=workspace_id,
        agent_name=agent.display_name,
        status="completed",
        summary=f"Custom agent returned {len(rows)} rows; alert {'created' if created_alert else 'not created'}.",
        timeline=[{"step": "execute_sql", "status": "completed", "detail": f"{len(rows)} rows."}],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run
