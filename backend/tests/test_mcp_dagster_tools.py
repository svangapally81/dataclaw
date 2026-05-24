from __future__ import annotations

import json
import os

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Connector, Workspace
from app.services.mcp_executor import _dagster_tool


@pytest.fixture(scope="module")
async def dagster_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("dagster")
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="Test")
        session.add(workspace)
        await session.flush()
        session.add(
            Connector(
                workspace_id=workspace.id,
                slug="dagster",
                category="etl_orchestration",
                display_name="Dagster",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"graphql_url": "http://dagster/graphql", "api_key": "dagster-key"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_dagster_operational_reads_use_graphql_variables(
    dagster_session: AsyncSession,
) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://dagster/graphql"
        body = json.loads(request.content.decode())
        seen.append(body)
        query = body["query"]
        if "assetsOrError" in query:
            return httpx.Response(200, json={"data": {"assetsOrError": {"nodes": [{"id": "asset-1", "key": {"path": ["core", "customers"]}}]}}})
        if "RunEvents" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "runOrError": {
                            "runId": "run/1",
                            "status": "FAILURE",
                            "stepKeysToExecute": ["extract"],
                        },
                        "logsForRun": {"events": [{"message": "failed", "stepKey": "extract"}]},
                    }
                },
            )
        if "AssetMaterializations" in query:
            return httpx.Response(
                200,
                json={"data": {"assetNodeOrError": {"assetMaterializations": [{"runId": "run-1"}]}}},
            )
        if "repositoriesOrError" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "repositoriesOrError": {
                            "nodes": [
                                {
                                    "name": "repo",
                                    "pipelines": [{"name": "daily"}],
                                    "sensors": [{"name": "sensor", "sensorState": {"status": "RUNNING"}}],
                                    "schedules": [{"name": "schedule", "scheduleState": {"status": "RUNNING"}}],
                                }
                            ]
                        }
                    }
                },
            )
        if "AssetPartitions" in query:
            return httpx.Response(200, json={"data": {"assetNodeOrError": {"partitionKeys": ["2026-05-01"]}}})
        if "AssetChecks" in query:
            return httpx.Response(200, json={"data": {"assetNodeOrError": {"assetChecksOrError": {"checks": [{"name": "not_null"}]}}}})
        if "InstigatorState" in query:
            return httpx.Response(200, json={"data": {"instigationStateOrError": {"name": body["variables"]["selector"]["name"], "status": "RUNNING"}}})
        if "Run($runId" in query:
            return httpx.Response(200, json={"data": {"runOrError": {"runId": "run/1", "status": "SUCCESS"}}})
        return httpx.Response(500, json={"query": query})

    respx.route(url__regex=r"http://dagster/.*").mock(side_effect=handler)
    session = dagster_session

    assets = await _dagster_tool(session, "read_list_assets", {}, "agent-1")
    run = await _dagster_tool(session, "read_get_run", {"run_id": "run/1"}, "agent-1")
    logs = await _dagster_tool(session, "read_get_event_logs", {"run_id": "run/1", "limit": 2}, "agent-1")
    steps = await _dagster_tool(session, "read_get_run_steps", {"run_id": "run/1"}, "agent-1")
    materializations = await _dagster_tool(session, "read_get_asset_materializations", {"asset_key": "core.customers"}, "agent-1")
    jobs = await _dagster_tool(session, "read_list_jobs", {}, "agent-1")
    partitions = await _dagster_tool(session, "read_list_partitions", {"asset_key": ["core", "customers"]}, "agent-1")
    checks = await _dagster_tool(session, "read_get_asset_checks", {"asset_key": "core.customers"}, "agent-1")
    sensors = await _dagster_tool(session, "read_list_sensors", {}, "agent-1")
    schedules = await _dagster_tool(session, "read_list_schedules", {}, "agent-1")
    sensor_state = await _dagster_tool(session, "read_get_sensor_state", {"name": "sensor"}, "agent-1")
    schedule_state = await _dagster_tool(session, "read_get_schedule_state", {"name": "schedule"}, "agent-1")

    assert assets["assets"][0]["id"] == "asset-1"
    assert run["run"]["status"] == "SUCCESS"
    assert logs["events"] == [{"message": "failed", "stepKey": "extract"}]
    assert steps["steps"] == ["extract"]
    assert materializations["materializations"] == [{"runId": "run-1"}]
    assert jobs["jobs"] == [{"name": "daily"}]
    assert partitions["partitions"] == ["2026-05-01"]
    assert checks["checks"] == [{"name": "not_null"}]
    assert sensors["sensors"][0]["name"] == "sensor"
    assert schedules["schedules"][0]["name"] == "schedule"
    assert sensor_state["sensorState"]["status"] == "RUNNING"
    assert schedule_state["scheduleState"]["status"] == "RUNNING"
    assert any(item["variables"] == {"runId": "run/1", "limit": 2} for item in seen)
    assert any(item["variables"] == {"assetKey": ["core", "customers"], "limit": 100} for item in seen)
    assert any(
        item["variables"]
        == {"selector": {"repositoryName": "dataclaw", "repositoryLocationName": "default", "name": "sensor"}}
        for item in seen
    )


@respx.mock
@pytest.mark.asyncio
async def test_dagster_operational_writes_use_graphql_variables(
    dagster_session: AsyncSession,
) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append(body)
        query = body["query"]
        if "launchPipelineExecution" in query:
            return httpx.Response(200, json={"data": {"launchPipelineExecution": {"run": {"runId": "run-1"}}}})
        if "launchPartitionBackfill" in query:
            return httpx.Response(200, json={"data": {"launchPartitionBackfill": {"backfillId": "backfill-1", "launchedRunIds": ["run-2"]}}})
        if "terminateRun" in query:
            return httpx.Response(200, json={"data": {"terminateRun": {"run": {"runId": "run/1", "status": "CANCELED"}}}})
        if "startSensor" in query:
            return httpx.Response(200, json={"data": {"startSensor": {"name": "sensor"}}})
        if "startSchedule" in query:
            return httpx.Response(200, json={"data": {"startSchedule": {"name": "schedule"}}})
        if "stopRunningSchedule" in query:
            return httpx.Response(200, json={"data": {"stopRunningSchedule": {"name": "schedule"}}})
        return httpx.Response(500, json={"query": query})

    respx.route(url__regex=r"http://dagster/.*").mock(side_effect=handler)
    session = dagster_session

    triggered = await _dagster_tool(session, "write_trigger_job", {"job_name": "daily"}, "agent-1")
    backfill = await _dagster_tool(
        session,
        "write_backfill_partitions",
        {"asset_key": ["core", "customers"], "partitions": ["2026-05-10"], "tags": {"source": "dataclaw"}},
        "agent-1",
    )
    terminated = await _dagster_tool(session, "write_terminate_run", {"run_id": "run/1"}, "agent-1")
    sensor = await _dagster_tool(session, "write_launch_sensor", {"name": "sensor"}, "agent-1")
    start_schedule = await _dagster_tool(session, "write_start_schedule", {"name": "schedule"}, "agent-1")
    stop_schedule = await _dagster_tool(session, "write_stop_schedule", {"name": "schedule"}, "agent-1")

    assert triggered["run"] == {"runId": "run-1", "status": "STARTED"}
    assert backfill["backfill"]["backfillId"] == "backfill-1"
    assert terminated["run"]["run"]["status"] == "CANCELED"
    assert sensor["result"]["startSensor"]["name"] == "sensor"
    assert start_schedule["result"]["startSchedule"]["name"] == "schedule"
    assert stop_schedule["result"]["stopRunningSchedule"]["name"] == "schedule"
    assert any(item["variables"]["executionParams"]["selector"]["pipelineName"] == "daily" for item in seen)
    assert any(
        item["variables"].get("backfillParams", {}).get("selector", {}).get("assetSelection") == [{"path": ["core", "customers"]}]
        and item["variables"]["backfillParams"]["partitionNames"] == ["2026-05-10"]
        for item in seen
    )
    assert any(item["variables"] == {"runId": "run/1"} for item in seen)
    assert any(
        item["variables"].get("selector")
        == {"repositoryName": "dataclaw", "repositoryLocationName": "default", "sensorName": "sensor"}
        for item in seen
    )
    assert any(
        item["variables"].get("selector")
        == {"repositoryName": "dataclaw", "repositoryLocationName": "default", "scheduleName": "schedule"}
        for item in seen
    )
