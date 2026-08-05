from __future__ import annotations

import os
import sys
import types

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Connector, Workspace
from app.services.mcp_executor import McpExecutionError, _bigquery_tool


class FakeRow(dict):
    def items(self):  # type: ignore[override]
        return super().items()


class FakeJob:
    def __init__(self, job_id: str = "job-1", rows: list[dict] | None = None):
        self.job_id = job_id
        self.state = "DONE"
        self._rows = [FakeRow(row) for row in (rows or [])]
        self.query_plan = [{"name": "dry-run-plan"}]
        self.total_bytes_processed = 42

    def result(self):
        return self._rows


class FakeDataset:
    def __init__(self, dataset_id: str):
        self.dataset_id = dataset_id


class FakeTableRef:
    def __init__(self, table_id: str, reference: str):
        self.table_id = table_id
        self.reference = reference


class FakeField:
    def __init__(self, name: str, field_type: str = "STRING", mode: str = "NULLABLE"):
        self.name = name
        self.field_type = field_type
        self.mode = mode


class FakeTable:
    def __init__(self):
        self.schema = [FakeField("customer_id"), FakeField("updated_at", "TIMESTAMP")]
        self.num_bytes = 128
        self.modified = None


class FakeBigQueryClient:
    last: FakeBigQueryClient | None = None
    loaded: list[tuple[str, str]] = []
    extracted: list[tuple[str, str]] = []
    created_datasets: list[tuple[str, bool]] = []
    queries: list[str] = []

    def __init__(self, project: str, credentials=None, client_options=None):
        self.project = project
        self.credentials = credentials
        self.client_options = client_options
        FakeBigQueryClient.last = self

    def query(self, sql: str, job_config=None):
        FakeBigQueryClient.queries.append(sql)
        if job_config is not None and getattr(job_config, "dry_run", False):
            return FakeJob("dry-run")
        if sql.startswith("select count(*)"):
            return FakeJob(rows=[{"row_count": 7}])
        if "JOBS_BY_PROJECT" in sql and "sum(total_slot_ms)" in sql:
            return FakeJob(rows=[{"total_slot_ms": 1234}])
        if "JOBS_BY_PROJECT" in sql:
            return FakeJob(rows=[{"job_id": "history-1", "state": "DONE"}])
        if sql.startswith("explain"):
            return FakeJob(rows=[{"plan": "scan"}])
        return FakeJob(rows=[{"ok": True}])

    def list_jobs(self, max_results: int = 20):
        return [FakeJob("job-list-1")]

    def list_datasets(self, project: str):
        return [FakeDataset("analytics")]

    def list_tables(self, dataset_ref: str):
        return [FakeTableRef("customers", f"{dataset_ref}.customers")]

    def get_table(self, table_ref: str):
        return FakeTable()

    def load_table_from_uri(self, uri: str, destination: str, job_config=None):
        FakeBigQueryClient.loaded.append((uri, destination))
        return FakeJob("load-1")

    def extract_table(self, source: str, uri: str):
        FakeBigQueryClient.extracted.append((source, uri))
        return FakeJob("extract-1")

    def create_dataset(self, dataset_ref: str, exists_ok: bool = True):
        FakeBigQueryClient.created_datasets.append((dataset_ref, exists_ok))
        return FakeDataset(dataset_ref.rsplit(".", 1)[-1])


@pytest.fixture(scope="module")
async def bigquery_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("bigquery")
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    get_settings.cache_clear()
    FakeBigQueryClient.loaded = []
    FakeBigQueryClient.extracted = []
    FakeBigQueryClient.created_datasets = []
    FakeBigQueryClient.queries = []
    module_names = [
        "google",
        "google.auth",
        "google.auth.credentials",
        "google.cloud",
        "google.cloud.bigquery",
        "google.oauth2",
        "google.oauth2.service_account",
    ]
    original_modules = {name: sys.modules.get(name) for name in module_names}

    google_module = types.ModuleType("google")
    auth_module = types.ModuleType("google.auth")
    auth_credentials_module = types.ModuleType("google.auth.credentials")
    auth_credentials_module.AnonymousCredentials = lambda: {"anonymous": True}
    cloud_module = types.ModuleType("google.cloud")
    bigquery_module = types.ModuleType("google.cloud.bigquery")
    bigquery_module.Client = FakeBigQueryClient
    bigquery_module.QueryJobConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)
    bigquery_module.LoadJobConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)
    bigquery_module.ScalarQueryParameter = lambda name, parameter_type, value: types.SimpleNamespace(
        name=name,
        parameter_type=parameter_type,
        value=value,
    )
    oauth_module = types.ModuleType("google.oauth2")
    service_account_module = types.ModuleType("google.oauth2.service_account")
    service_account_module.Credentials = types.SimpleNamespace(from_service_account_info=lambda info: {"info": info})
    cloud_module.bigquery = bigquery_module
    auth_module.credentials = auth_credentials_module
    oauth_module.service_account = service_account_module
    sys.modules["google"] = google_module
    sys.modules["google.auth"] = auth_module
    sys.modules["google.auth.credentials"] = auth_credentials_module
    sys.modules["google.cloud"] = cloud_module
    sys.modules["google.cloud.bigquery"] = bigquery_module
    sys.modules["google.oauth2"] = oauth_module
    sys.modules["google.oauth2.service_account"] = service_account_module

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
                slug="bigquery",
                category="data_store",
                display_name="BigQuery",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"project_id": "dataclaw-test", "dataset": "analytics", "service_account_json": {"project_id": "dataclaw-test"}},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()
    for name, module in original_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


@pytest.mark.asyncio
async def test_bigquery_matrix_reads_and_writes(bigquery_session: AsyncSession) -> None:
    session = bigquery_session

    datasets = await _bigquery_tool(session, "read_list_datasets", {}, "agent-1")
    history = await _bigquery_tool(session, "read_get_query_history", {"since": "2026-05-01T00:00:00Z"}, "agent-1")
    explained = await _bigquery_tool(session, "read_explain_query", {"sql": "select * from analytics.customers"}, "agent-1")
    slots = await _bigquery_tool(session, "read_get_slot_usage", {}, "agent-1")
    loaded = await _bigquery_tool(
        session,
        "write_load_from_gcs",
        {"uri": "gs://bucket/customers.json", "table": "customers", "source_format": "NEWLINE_DELIMITED_JSON"},
        "agent-1",
    )
    exported = await _bigquery_tool(session, "write_export_to_gcs", {"table": "customers", "uri": "gs://bucket/out.json"}, "agent-1")
    view = await _bigquery_tool(session, "write_create_view", {"view": "active_customers", "select_sql": "select * from analytics.customers"}, "agent-1")
    dataset = await _bigquery_tool(session, "write_create_dataset", {"dataset": "sandbox", "exists_ok": False}, "agent-1")

    client = FakeBigQueryClient.last
    assert client is not None
    assert datasets["datasets"] == [{"dataset_id": "analytics"}]
    assert history["queries"][0]["job_id"] == "history-1"
    assert explained["plan"] == [{"name": "dry-run-plan"}]
    assert slots["slot_usage"]["total_slot_ms"] == 1234
    assert loaded["job_id"] == "load-1"
    assert FakeBigQueryClient.loaded == [("gs://bucket/customers.json", "dataclaw-test.analytics.customers")]
    assert exported["job_id"] == "extract-1"
    assert FakeBigQueryClient.extracted == [("dataclaw-test.analytics.customers", "gs://bucket/out.json")]
    assert view["status"] == "executed"
    assert any("create or replace view `dataclaw-test.analytics.active_customers`" in query for query in FakeBigQueryClient.queries)
    assert dataset["dataset"] == "sandbox"
    assert FakeBigQueryClient.created_datasets == [("dataclaw-test.sandbox", False)]
    assert any("`dataclaw-test`.`region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT" in query for query in FakeBigQueryClient.queries)


@pytest.mark.asyncio
async def test_bigquery_rejects_unsafe_destinations_and_load_formats(bigquery_session: AsyncSession) -> None:
    session = bigquery_session

    with pytest.raises(McpExecutionError, match="destination_table"):
        await _bigquery_tool(
            session,
            "write_run_query_save_to_table",
            {"destination_table": "analytics.bad`table", "select_sql": "select 1"},
            "agent-1",
        )

    with pytest.raises(McpExecutionError, match="source_format"):
        await _bigquery_tool(
            session,
            "write_load_from_gcs",
            {"uri": "gs://bucket/customers.bin", "table": "customers", "source_format": "BINARY"},
            "agent-1",
        )


@pytest.mark.asyncio
async def test_bigquery_mcp_uses_emulator_host_with_anonymous_credentials(bigquery_session: AsyncSession) -> None:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.security import encrypt_json
    from app.models.domain import Connector

    session = bigquery_session
    connector = await session.scalar(select(Connector).where(Connector.slug == "bigquery"))
    assert connector is not None
    connector.encrypted_credentials = encrypt_json(
        get_settings().master_key,
        {"project_id": "dataclaw-integration", "dataset": "core", "emulator_host": "http://127.0.0.1:19050/"},
    )
    await session.commit()

    datasets = await _bigquery_tool(session, "read_list_datasets", {}, "agent-1")

    client = FakeBigQueryClient.last
    assert datasets["datasets"] == [{"dataset_id": "analytics"}]
    assert client is not None
    assert client.project == "dataclaw-integration"
    assert client.credentials == {"anonymous": True}
    assert client.client_options == {"api_endpoint": "http://127.0.0.1:19050"}
