from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services.vector_store import VectorStore


@pytest.mark.asyncio
async def test_vector_store_ping_uses_heartbeat_not_a_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CHROMA_URL", "http://localhost:8001")
    store = VectorStore()
    calls: list[str] = []

    monkeypatch.delenv("DATACLAW_VECTOR_TEST_DOUBLE", raising=False)

    class FakeClient:
        def heartbeat(self) -> int:
            calls.append("heartbeat")
            return 1

    class FakeChromadb:
        @staticmethod
        def HttpClient(*, host: str, port: int) -> FakeClient:
            calls.append(f"http_client:{host}:{port}")
            return FakeClient()

    monkeypatch.setitem(__import__("sys").modules, "chromadb", FakeChromadb)

    await store.ping()
    assert calls[-1] == "heartbeat"
    assert any(c.startswith("http_client:") for c in calls)


@pytest.mark.asyncio
async def test_vector_store_ping_raises_chroma_unreachable_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.vector_store import ChromaUnreachableError

    get_settings.cache_clear()
    monkeypatch.setenv("CHROMA_URL", "http://localhost:8001")
    store = VectorStore()
    monkeypatch.delenv("DATACLAW_VECTOR_TEST_DOUBLE", raising=False)

    class FakeChromadb:
        @staticmethod
        def HttpClient(*, host: str, port: int):
            raise ConnectionError("chroma down")

    monkeypatch.setitem(__import__("sys").modules, "chromadb", FakeChromadb)

    with pytest.raises(ChromaUnreachableError):
        await store.ping()


@pytest.mark.asyncio
async def test_vector_store_ping_uses_persistent_client_when_chroma_url_unset(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    get_settings.cache_clear()
    monkeypatch.delenv("CHROMA_URL", raising=False)
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.delenv("DATACLAW_VECTOR_TEST_DOUBLE", raising=False)
    calls: list[str] = []

    class FakeClient:
        def heartbeat(self) -> int:
            calls.append("heartbeat")
            return 1

    class FakeChromadb:
        @staticmethod
        def PersistentClient(*, path: str) -> FakeClient:
            calls.append(f"persistent_client:{path}")
            return FakeClient()

    monkeypatch.setitem(__import__("sys").modules, "chromadb", FakeChromadb)

    store = VectorStore()
    await store.ping()

    assert calls == [f"persistent_client:{tmp_path / 'chroma'}", "heartbeat"]


@pytest.mark.asyncio
async def test_replace_brain_summaries_updates_in_place_without_recreating(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brain summaries should be replaced via delete+upsert on the existing collection,
    NOT by destroying and re-creating it. Otherwise the backend's cached collection
    object becomes stale (different internal Chroma ID) and chat calls fail."""
    get_settings.cache_clear()
    store = VectorStore()
    monkeypatch.delenv("DATACLAW_VECTOR_TEST_DOUBLE", raising=False)

    deleted_ids: list[list[str]] = []
    upserted_ids: list[list[str]] = []

    class FakeCollection:
        def get(self, *, include):  # noqa: A002 - chroma protocol
            return {"ids": ["old-id-1", "stale-id-2"]}

        def delete(self, *, ids):
            deleted_ids.append(list(ids))

        def upsert(self, *, ids, documents, metadatas):
            upserted_ids.append(list(ids))

    collection = FakeCollection()

    class FakeClient:
        def get_or_create_collection(self, **kwargs):
            return collection

        def delete_collection(self, name: str) -> None:
            raise AssertionError(f"delete_collection must NOT be called (got {name!r})")

    class FakeNode:
        id = "node-1"
        summary = "customer summary"
        type = "table"
        canonical_name = "customers"
        connector_slug = "postgres"
        source_type = "postgres"
        aliases: list[str] = []

    store._client = FakeClient()
    store._embedding_api_key = "test-key"
    store._embedding_function = object()

    await store.replace_brain_summaries("workspace-1", [FakeNode()])

    # Stale ids removed, new id upserted, collection NEVER deleted.
    assert deleted_ids and "old-id-1" in deleted_ids[0] and "stale-id-2" in deleted_ids[0]
    assert upserted_ids and len(upserted_ids[0]) == 1
