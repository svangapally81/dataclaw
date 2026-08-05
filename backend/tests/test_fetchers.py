import httpx
import pytest

from app.services.connectors.adapters import adapter_for


@pytest.fixture
def patch_async_client(monkeypatch):
    def _patch(handler):
        original = httpx.AsyncClient

        def _factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _factory)

    return _patch


@pytest.mark.asyncio
async def test_notion_fetch_content_returns_page_bodies(patch_async_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "p1",
                            "properties": {"Name": {"title": [{"plain_text": "Data Glossary"}]}},
                            "parent": {"page_id": "root"},
                            "last_edited_time": "2026-05-08T00:00:00Z",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/blocks/p1/children":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "orders docs"}]}}
                    ],
                    "has_more": False,
                },
            )
        return httpx.Response(404)

    patch_async_client(handler)
    result = await adapter_for("notion").fetch_content({"integration_token": "secret"})
    assert result["pages"][0]["title"] == "Data Glossary"
    assert result["pages"][0]["body"] == "orders docs"


@pytest.mark.asyncio
async def test_airflow_fetch_content_includes_source_and_runs(patch_async_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/dags":
            return httpx.Response(200, json={"dags": [{"dag_id": "daily_orders_refresh", "owners": ["data"]}]})
        if request.url.path == "/api/v1/dags/daily_orders_refresh/source":
            return httpx.Response(200, json={"source_code": "insert into orders"})
        if request.url.path == "/api/v1/dags/daily_orders_refresh/dagRuns":
            return httpx.Response(200, json={"dag_runs": [{"run_id": "r1"}]})
        return httpx.Response(404)

    patch_async_client(handler)
    result = await adapter_for("airflow").fetch_content({"base_url": "http://airflow"})
    assert result["dags"][0]["source_code"] == "insert into orders"
    assert result["dags"][0]["recent_runs"][0]["run_id"] == "r1"


@pytest.mark.asyncio
async def test_github_fetch_content_recurses_supported_files(patch_async_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/warehouse":
            return httpx.Response(200, json={"full_name": "acme/warehouse", "default_branch": "main"})
        if request.url.path == "/repos/acme/warehouse/contents/":
            return httpx.Response(
                200,
                json=[
                    {"path": "README.md", "type": "file", "download_url": "http://download/readme"},
                    {"path": "models", "type": "dir"},
                    {"path": "package.json", "type": "file", "download_url": "http://download/package"},
                ],
            )
        if request.url.path == "/repos/acme/warehouse/contents/models":
            return httpx.Response(
                200,
                json=[{"path": "models/orders.sql", "type": "file", "download_url": "http://download/orders"}],
            )
        if str(request.url) == "http://download/readme":
            return httpx.Response(200, text="# Warehouse\n\nDocuments orders.")
        if str(request.url) == "http://download/orders":
            return httpx.Response(200, text="select * from orders")
        return httpx.Response(404)

    patch_async_client(handler)
    result = await adapter_for("github").fetch_content(
        {"base_url": "http://github", "token": "secret", "repositories": "acme/warehouse"}
    )
    files = result["repos"][0]["files"]
    assert result["repos"][0]["full_name"] == "acme/warehouse"
    assert {file["path"] for file in files} == {"README.md", "models/orders.sql"}
    assert any(file["content"] == "select * from orders" for file in files)


@pytest.mark.asyncio
async def test_dbt_fetch_content_parses_manifest_models_and_runs(patch_async_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/manifest.json":
            return httpx.Response(
                200,
                json={
                    "nodes": {
                        "model.project.stg_orders": {
                            "resource_type": "model",
                            "name": "stg_orders",
                            "raw_code": "select * from orders",
                            "depends_on": {"nodes": ["source.project.orders"]},
                            "columns": {"order_id": {"name": "order_id"}},
                        },
                        "test.project.not_a_model": {"resource_type": "test", "name": "not_a_model"},
                    }
                },
            )
        if request.url.path == "/runs/":
            return httpx.Response(200, json={"data": [{"id": 123, "status": "success"}]})
        return httpx.Response(404)

    patch_async_client(handler)
    result = await adapter_for("dbt").fetch_content({"base_url": "http://dbt", "api_token": "secret"})
    assert result["models"] == [
        {
            "name": "stg_orders",
            "sql": "select * from orders",
            "depends_on": ["source.project.orders"],
            "columns": [{"name": "order_id"}],
        }
    ]
    assert result["runs"][0]["id"] == 123
