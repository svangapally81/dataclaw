from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_json
from app.models.domain import Connector, Workspace
from app.services.connectors.adapters import adapter_for
from app.services.ingestion.chunker import chunk_text
from app.services.ingestion.summarizer import WikiPageDraft, content_hash, summarize_artifact
from app.services.ingestion.wiki_store import WikiStore
from app.services.settings_store import hydrate_vector_store, resolve_openai
from app.services.vector_store import vector_store

logger = logging.getLogger("dataclaw.ingestion")
LLM_ARTIFACT_LIMIT = 1
VECTOR_CHUNK_UPSERT_TIMEOUT_SECONDS = 10.0


@dataclass
class IngestionResult:
    artifacts_processed: int = 0
    pages_written: int = 0
    raw_chunks_written: int = 0
    page_paths: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "artifacts_processed": self.artifacts_processed,
            "pages_written": self.pages_written,
            "raw_chunks_written": self.raw_chunks_written,
            "page_paths": self.page_paths,
        }


class IngestionService:
    def __init__(self, session: AsyncSession, wiki_store: WikiStore | None = None) -> None:
        self.session = session
        self.wiki_store = wiki_store or WikiStore()

    async def ingest_connector(self, connector: Connector, credentials: dict[str, Any]) -> IngestionResult:
        adapter = adapter_for(connector.slug)
        if hasattr(adapter, "fetch_content"):
            payload = await adapter.fetch_content(credentials)  # type: ignore[attr-defined]
        else:
            payload = await adapter.sync(credentials)
        return await self.ingest_payload(connector.workspace_id, connector.slug, payload)

    async def ingest_payload(self, workspace_id: str, source_type: str, payload: dict[str, Any]) -> IngestionResult:
        result = IngestionResult()
        artifacts = self._artifacts(source_type, payload)
        page_summaries: list[tuple[str, str]] = []
        await hydrate_vector_store(self.session, workspace_id)
        existing_pages = await self.wiki_store.list_pages(self.session, workspace_id, source_type=source_type, tier=1)
        existing_by_source_id = {page.source_id: page for page in existing_pages}
        raw_chunk_batches: list[tuple[str, str, list[Any]]] = []
        openai_config = await resolve_openai(self.session)
        llm_used = 0
        for artifact_id, content in artifacts:
            existing = existing_by_source_id.get(artifact_id)
            digest = content_hash(content)
            unchanged = bool(existing and existing.frontmatter.get("last_content_hash") == digest)
            artifact_openai_config = openai_config if llm_used < LLM_ARTIFACT_LIMIT else (None, None, None, None)
            page = await self.ingest_artifact(
                workspace_id,
                source_type,
                artifact_id,
                content,
                existing_by_source_id=existing_by_source_id,
                openai_config=artifact_openai_config,
            )
            if artifact_openai_config[0]:
                llm_used += 1
            existing_by_source_id[artifact_id] = page
            result.artifacts_processed += 1
            if unchanged:
                continue
            result.pages_written += 1
            result.page_paths.append(page.path)
            page_summaries.append((page.path, page.title))
            raw_text = content if isinstance(content, str) else json.dumps(content, sort_keys=True, default=str)
            chunks = chunk_text(raw_text, metadata={"source_type": source_type, "source_id": artifact_id})
            raw_chunk_batches.append((source_type, artifact_id, chunks))
            result.raw_chunks_written += len(chunks)
        if page_summaries:
            index_body = "\n".join(f"- [[{path}]] - {title}" for path, title in page_summaries)
            draft = WikiPageDraft(
                workspace_id=workspace_id,
                path=f"wiki/{source_type}/index.md",
                tier=1,
                source_type=source_type,
                source_id=f"{source_type}:index",
                title=f"{source_type} index",
                body=f"# {source_type} index\n\n{index_body}\n",
                frontmatter={"title": f"{source_type} index", "source_type": source_type, "entities": []},
                entities=[],
                content_hash=content_hash(index_body),
            )
            page = await self.wiki_store.upsert_page(self.session, draft)
            result.pages_written += 1
            result.page_paths.append(page.path)
        await self.session.commit()
        for batch_source_type, artifact_id, chunks in raw_chunk_batches:
            try:
                await asyncio.wait_for(
                    vector_store.upsert_raw_chunks(workspace_id, batch_source_type, artifact_id, chunks),
                    timeout=VECTOR_CHUNK_UPSERT_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logger.warning(
                    "raw_chunk_vector_upsert_skipped",
                    extra={
                        "_source_type": batch_source_type,
                        "_artifact_id": artifact_id,
                        "_error": exc.__class__.__name__,
                    },
                )
        return result

    async def ingest_artifact(
        self,
        workspace_id: str,
        source_type: str,
        source_id: str,
        content: Any,
        *,
        existing_by_source_id: dict[str, Any] | None = None,
        openai_config: tuple[str | None, str | None, str | None, str | None] | None = None,
    ):
        if existing_by_source_id is None:
            existing_pages = await self.wiki_store.list_pages(self.session, workspace_id, source_type=source_type, tier=1)
            existing_by_source_id = {page.source_id: page for page in existing_pages}
        existing = existing_by_source_id.get(source_id)
        digest = content_hash(content)
        if existing and existing.frontmatter.get("last_content_hash") == digest:
            return existing
        if openai_config is None:
            openai_config = await resolve_openai(self.session)
        draft = await summarize_artifact(
            workspace_id=workspace_id,
            source_type=source_type,
            source_id=source_id,
            content=content,
            existing_page=existing.body if existing else None,
            openai_config=openai_config,
        )
        return await self.wiki_store.upsert_page(self.session, draft)

    def _artifacts(self, source_type: str, payload: dict[str, Any]) -> list[tuple[str, Any]]:
        if "pages" in payload:
            return [(str(item.get("id") or item.get("title")), item) for item in payload.get("pages") or []]
        if "repos" in payload:
            artifacts = []
            for repo in payload.get("repos") or []:
                for file in repo.get("files") or []:
                    artifacts.append((f"{repo.get('full_name')}/{file.get('path')}", {**file, "repo": repo.get("full_name")}))
            return artifacts
        if "dags" in payload:
            return [(str(item.get("dag_id")), item) for item in payload.get("dags") or []]
        if "models" in payload:
            return [(str(item.get("name")), item) for item in payload.get("models") or []]
        if "tables" in payload:
            return [(f"{item.get('schema') or payload.get('schema_name') or 'public'}.{item.get('name')}", item) for item in payload.get("tables") or []]
        return [(source_type, payload)]


async def ingest_configured_connector(session: AsyncSession, connector: Connector) -> IngestionResult:
    credentials = {}
    if connector.encrypted_credentials:
        credentials = decrypt_json(get_settings().master_key, connector.encrypted_credentials)
    return await IngestionService(session).ingest_connector(connector, credentials)


async def ingest_all_configured(session: AsyncSession) -> list[IngestionResult]:
    workspace = await session.scalar(select(Workspace).limit(1))
    if workspace is None:
        return []
    connectors = list(
        (
            await session.scalars(
                select(Connector).where(
                    Connector.credential_state == "configured",
                    Connector.sync_state != "syncing",
                )
            )
        ).all()
    )
    return [await ingest_configured_connector(session, connector) for connector in connectors]
