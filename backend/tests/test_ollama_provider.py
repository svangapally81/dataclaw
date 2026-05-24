import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models.domain import Workspace
from app.services.agents import chat as chat_service
from app.services.llm_catalog import CATALOG_BY_SLUG
from app.services.settings_store import resolve_openai, update_llm_provider
from app.services.vector_store import OpenAICompatibleEmbeddingFunction


@pytest.fixture
async def settings_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'settings.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


def test_ollama_catalog_entry_is_wired() -> None:
    provider = CATALOG_BY_SLUG["ollama"]

    assert provider.wired is True
    assert provider.default_model == "llama3.1:8b"
    assert provider.default_embedding_model == "nomic-embed-text"
    assert {field.name for field in provider.fields} == {"base_url", "model", "embedding_model"}


@pytest.mark.asyncio
async def test_resolve_openai_can_route_to_ollama(settings_session, monkeypatch) -> None:
    monkeypatch.setenv("DATACLAW_LLM_PROVIDER", "ollama")
    get_settings.cache_clear()

    await update_llm_provider(
        settings_session,
        "ollama",
        {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b",
            "embedding_model": "mxbai-embed-large",
        },
    )

    assert await resolve_openai(settings_session) == (
        "ollama-local",
        "qwen2.5:7b",
        "http://127.0.0.1:11434/v1",
        "mxbai-embed-large",
    )

    monkeypatch.delenv("DATACLAW_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_uses_ollama_base_url(settings_session, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            message = type("Message", (), {"content": "local answer", "tool_calls": None})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            calls.append({"api_key": api_key, "base_url": str(base_url)})
            self.chat = FakeChat()

    monkeypatch.setenv("DATACLAW_LLM_PROVIDER", "ollama")
    get_settings.cache_clear()
    monkeypatch.setattr(chat_service, "AsyncOpenAI", FakeAsyncOpenAI)

    settings_session.add(Workspace(name="Test"))
    await update_llm_provider(
        settings_session,
        "ollama",
        {"base_url": "http://127.0.0.1:11434/v1", "model": "llama3.1:8b"},
    )
    await settings_session.commit()

    result = await chat_service.answer_question(settings_session, "hello")

    assert result["answer"] == "local answer"
    assert result["provider"] == "ollama"
    assert calls[0] == {"api_key": "ollama-local", "base_url": "http://127.0.0.1:11434/v1"}
    assert calls[1]["model"] == "llama3.1:8b"

    monkeypatch.delenv("DATACLAW_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()


def test_openai_compatible_embedding_function_uses_selected_base_url(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeEmbeddings:
        def create(self, *, model: str, input: list[str]):
            calls.append({"model": model, "input": input})
            first = type("Embedding", (), {"index": 1, "embedding": [0.2, 0.3]})()
            second = type("Embedding", (), {"index": 0, "embedding": [0.0, 0.1]})()
            return type("Response", (), {"data": [first, second]})()

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            calls.append({"api_key": api_key, "base_url": base_url})
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("app.services.vector_store.OpenAI", FakeOpenAI)

    embedding_function = OpenAICompatibleEmbeddingFunction(
        api_key="ollama-local",
        base_url="http://127.0.0.1:11434/v1",
        model="nomic-embed-text",
    )

    result = embedding_function(["hello", "world"])
    assert [list(row) for row in result] == [[0.0, 0.1], [0.2, 0.3]]
    assert calls == [
        {"api_key": "ollama-local", "base_url": "http://127.0.0.1:11434/v1"},
        {"model": "nomic-embed-text", "input": ["hello", "world"]},
    ]
