from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_json
from app.models.domain import (
    Agent,
    AgentMcpGrant,
    AgentRun,
    Alert,
    Connector,
    MonitoringConfig,
    Workspace,
)
from app.services.connectors.catalog import CATALOG_BY_SLUG, ConnectorCategory
from app.services.monitoring.notifier import notify_alert
from app.services.settings_store import hydrate_vector_store
from app.services.vector_store import vector_store

MONITORING_AGENTS: dict[str, dict[str, Any]] = {
    "airflow_failure_agent": {
        "display_name": "Airflow Failure Agent",
        "connectors": ["airflow"],
        "thresholds": {},
    },
    "dbt_failure_agent": {
        "display_name": "dbt Failure Agent",
        "connectors": ["dbt"],
        "thresholds": {},
    },
    "schema_drift_agent": {
        "display_name": "Schema Drift Agent",
        "connectors": [
            slug
            for slug, definition in CATALOG_BY_SLUG.items()
            if definition.category == ConnectorCategory.DATA_STORE
        ],
        "thresholds": {},
    },
    "query_cost_agent": {
        "display_name": "Query Cost Agent",
        "connectors": [
            slug
            for slug, definition in CATALOG_BY_SLUG.items()
            if definition.category == ConnectorCategory.DATA_STORE
        ],
        "thresholds": {"duration_ms": 5000, "rows_returned": 10000},
    },
}


async def workspace_or_raise(session: AsyncSession) -> Workspace:
    workspace = await session.scalar(select(Workspace).limit(1))
    if workspace is None:
        raise RuntimeError("Workspace has not been seeded.")
    return workspace


async def enabled_monitoring_configs(
    session: AsyncSession,
    workspace_id: str,
    agent_name: str,
    connector_slugs: Iterable[str],
) -> list[tuple[MonitoringConfig | None, Connector]]:
    allowed = set(connector_slugs)
    unified_name = {
        "airflow_failure_agent": "alerting",
        "dbt_failure_agent": "alerting",
        "schema_drift_agent": "data_quality",
        "query_cost_agent": "data_quality",
    }.get(agent_name)
    if unified_name is not None:
        agent = await session.scalar(
            select(Agent).where(
                Agent.workspace_id == workspace_id,
                Agent.name == unified_name,
                Agent.enabled.is_(True),
                Agent.kind == "background",
            )
        )
        if agent is not None:
            grants = list(
                (
                    await session.scalars(
                        select(AgentMcpGrant).where(
                            AgentMcpGrant.agent_id == agent.id,
                            AgentMcpGrant.read_enabled.is_(True),
                        )
                    )
                ).all()
            )
            allowed_grants = {grant.connector_slug for grant in grants} & allowed
            if not allowed_grants:
                return []
            connectors = list(
                (
                    await session.scalars(
                        select(Connector).where(
                            Connector.workspace_id == workspace_id,
                            Connector.slug.in_(allowed_grants),
                            Connector.credential_state == "configured",
                        )
                    )
                ).all()
            )
            return [(None, connector) for connector in connectors]

    configs = list(
        (
            await session.scalars(
                select(MonitoringConfig)
                .where(
                    MonitoringConfig.workspace_id == workspace_id,
                    MonitoringConfig.agent_name == agent_name,
                    MonitoringConfig.enabled.is_(True),
                )
                .order_by(MonitoringConfig.created_at)
            )
        ).all()
    )
    pairs: list[tuple[MonitoringConfig | None, Connector]] = []
    for config in configs:
        connector = await session.get(Connector, config.connector_id)
        if connector is None or connector.slug not in allowed or connector.credential_state != "configured":
            continue
        pairs.append((config, connector))
    return pairs


def connector_credentials(connector: Connector) -> dict[str, Any]:
    if not connector.encrypted_credentials:
        return {}
    return decrypt_json(get_settings().master_key, connector.encrypted_credentials)


async def create_alert_once(
    session: AsyncSession,
    config: MonitoringConfig | None,
    *,
    workspace_id: str,
    fingerprint: str,
    severity: str,
    title: str,
    detail: str,
    requires_approval: bool = False,
) -> Alert | None:
    existing = await session.scalar(
        select(Alert).where(
            Alert.workspace_id == workspace_id,
            Alert.fingerprint == fingerprint,
            Alert.resolved.is_(False),
        )
    )
    if existing is not None:
        return None
    alert = Alert(
        workspace_id=workspace_id,
        fingerprint=fingerprint,
        severity=severity,
        title=title,
        detail=detail,
        requires_approval=requires_approval,
    )
    session.add(alert)
    await session.flush()
    await notify_alert(alert, config)
    return alert


async def finish_agent_run(session: AsyncSession, run: AgentRun) -> AgentRun:
    session.add(run)
    await session.flush()
    alerts = list(
        (
            await session.scalars(
                select(Alert).where(Alert.workspace_id == run.workspace_id, Alert.resolved.is_(False))
            )
        ).all()
    )
    await hydrate_vector_store(session, run.workspace_id)
    await vector_store.upsert_agent_runs(run.workspace_id, [run], alerts)
    await session.commit()
    await session.refresh(run)
    return run


def utc_now() -> datetime:
    return datetime.now(UTC)
