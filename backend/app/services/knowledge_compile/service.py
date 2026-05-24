from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ColumnLineageEdge, KnowledgeEdge, KnowledgeNode, WikiPage
from app.services.knowledge_compile.extractor import (
    ColumnLineageCandidate,
    extract_candidates,
    extract_column_lineage_candidates,
    normalize_name,
)
from app.services.knowledge_compile.graph_writer import write_graph
from app.services.settings_store import resolve_openai
from app.services.vector_store import vector_store

_compile_locks: dict[str, asyncio.Lock] = {}


@dataclass
class CompileResult:
    nodes_created: int
    nodes_updated: int
    edges_created: int
    runtime_ms: int

    def model_dump(self) -> dict:
        return {
            "nodes_created": self.nodes_created,
            "nodes_updated": self.nodes_updated,
            "edges_created": self.edges_created,
            "runtime_ms": self.runtime_ms,
        }


class CompileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compile(self, workspace_id: str) -> CompileResult:
        lock = _compile_locks.setdefault(workspace_id, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("knowledge_compile_already_running")
        async with lock:
            return await self._compile_locked(workspace_id)

    async def _compile_locked(self, workspace_id: str) -> CompileResult:
        start = perf_counter()
        api_key, _model, base_url, embedding_model = await resolve_openai(self.session)
        vector_store.ensure_embedding_model(workspace_id, embedding_model, api_key=api_key, base_url=base_url)
        pages = list(
            (
                await self.session.scalars(
                    select(WikiPage).where(WikiPage.workspace_id == workspace_id, WikiPage.tier == 1)
                )
            ).all()
        )
        nodes, edges = extract_candidates(pages)
        compile_run_id = str(uuid4())
        stats = await write_graph(self.session, workspace_id, nodes, edges, compile_run_id)
        await self._write_column_lineage(workspace_id, extract_column_lineage_candidates(pages), compile_run_id)
        await self._embed_brain_summaries(workspace_id)
        await self.session.commit()
        return CompileResult(stats.nodes_created, stats.nodes_updated, stats.edges_created, round((perf_counter() - start) * 1000))

    async def compile_incremental(self, workspace_id: str, dirty_page_paths: list[str]) -> CompileResult:
        lock = _compile_locks.setdefault(workspace_id, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("knowledge_compile_already_running")
        async with lock:
            return await self._compile_incremental_locked(workspace_id, dirty_page_paths)

    async def _compile_incremental_locked(self, workspace_id: str, dirty_page_paths: list[str]) -> CompileResult:
        start = perf_counter()
        if not dirty_page_paths:
            return CompileResult(0, 0, 0, 0)
        pages = list(
            (
                await self.session.scalars(
                    select(WikiPage).where(
                        WikiPage.workspace_id == workspace_id,
                        WikiPage.tier == 1,
                        WikiPage.path.in_(dirty_page_paths),
                    )
                )
            ).all()
        )
        if not pages:
            return CompileResult(0, 0, 0, round((perf_counter() - start) * 1000))
        nodes, edges = extract_candidates(pages)
        compile_run_id = str(uuid4())
        dirty_doc_names = {
            normalize_name(page.path.removesuffix(".md").split("/")[-1])
            for page in pages
        }
        stats = await write_graph(
            self.session,
            workspace_id,
            nodes,
            edges,
            compile_run_id,
            edge_source_scope=dirty_doc_names,
        )
        await self._write_column_lineage(
            workspace_id,
            extract_column_lineage_candidates(pages),
            compile_run_id,
            source_page_ids={page.id for page in pages},
        )
        await self._embed_brain_summaries(workspace_id)
        await self.session.commit()
        return CompileResult(stats.nodes_created, stats.nodes_updated, stats.edges_created, round((perf_counter() - start) * 1000))

    async def _write_column_lineage(
        self,
        workspace_id: str,
        candidates: list[ColumnLineageCandidate],
        compile_run_id: str,
        *,
        source_page_ids: set[str] | None = None,
    ) -> None:
        stale_stmt = delete(ColumnLineageEdge).where(ColumnLineageEdge.workspace_id == workspace_id)
        if source_page_ids is not None:
            stale_stmt = stale_stmt.where(ColumnLineageEdge.source_page_id.in_(source_page_ids))
        await self.session.execute(stale_stmt)
        seen: set[tuple[str, str, str, str, str, str, str]] = set()
        for candidate in candidates:
            key = (
                candidate.source_connector_slug,
                candidate.source_table,
                candidate.source_column,
                candidate.target_connector_slug,
                candidate.target_table,
                candidate.target_column,
                candidate.relationship,
            )
            if key in seen:
                continue
            seen.add(key)
            self.session.add(
                ColumnLineageEdge(
                    workspace_id=workspace_id,
                    source_connector_slug=candidate.source_connector_slug,
                    source_table=candidate.source_table,
                    source_column=candidate.source_column,
                    target_connector_slug=candidate.target_connector_slug,
                    target_table=candidate.target_table,
                    target_column=candidate.target_column,
                    relationship=candidate.relationship,
                    evidence=candidate.evidence,
                    source_page_id=candidate.page_id,
                    compile_run_id=compile_run_id,
                )
            )

    async def _embed_brain_summaries(self, workspace_id: str) -> None:
        nodes = list(
            (
                await self.session.scalars(
                    select(KnowledgeNode).where(
                        KnowledgeNode.workspace_id == workspace_id,
                        KnowledgeNode.summary != "",
                    )
                )
            ).all()
        )
        if not nodes:
            return
        await vector_store.replace_brain_summaries(workspace_id, nodes)
        embedded_at = datetime.now(UTC)
        for node in nodes:
            node.summary_embedded_at = embedded_at

    async def graph(self, workspace_id: str, root: str | None = None, depth: int = 2) -> dict:
        nodes = list((await self.session.scalars(select(KnowledgeNode).where(KnowledgeNode.workspace_id == workspace_id))).all())
        edges = list((await self.session.scalars(select(KnowledgeEdge).where(KnowledgeEdge.workspace_id == workspace_id))).all())
        if root:
            needle = normalize_name(root)
            root_nodes = [node for node in nodes if node.id == root or node.canonical_name == needle or needle in (node.aliases or [])]
        else:
            counts: dict[str, int] = {}
            for edge in edges:
                counts[edge.src_node_id] = counts.get(edge.src_node_id, 0) + 1
                counts[edge.dst_node_id] = counts.get(edge.dst_node_id, 0) + 1
            root_id = max(counts, key=counts.get) if counts else (nodes[0].id if nodes else None)
            root_nodes = [node for node in nodes if node.id == root_id]
        if root_nodes and depth > 0:
            frontier = {root_nodes[0].id}
            visible = set(frontier)
            for _ in range(depth):
                next_frontier: set[str] = set()
                for edge in edges:
                    if edge.src_node_id in frontier:
                        next_frontier.add(edge.dst_node_id)
                    if edge.dst_node_id in frontier:
                        next_frontier.add(edge.src_node_id)
                visible |= next_frontier
                frontier = next_frontier
            nodes = [node for node in nodes if node.id in visible]
            edges = [edge for edge in edges if edge.src_node_id in visible and edge.dst_node_id in visible]
        node_ids = {node.id for node in nodes}
        return {
            "nodes": [
                {
                    "id": node.id,
                    "type": node.type,
                    "canonical_name": node.canonical_name,
                    "connector_slug": node.connector_slug,
                    "source_type": node.source_type,
                    "summary": node.summary,
                    "aliases": node.aliases,
                    "primary_wiki_page_id": node.primary_wiki_page_id,
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": edge.id,
                    "src_node_id": edge.src_node_id,
                    "dst_node_id": edge.dst_node_id,
                    "relationship": edge.relationship,
                    "evidence": edge.evidence,
                    "confidence": edge.confidence,
                    "source": edge.source,
                }
                for edge in edges
                if edge.src_node_id in node_ids and edge.dst_node_id in node_ids
            ],
        }


async def graph_neighbors(session: AsyncSession, workspace_id: str, query: str) -> list[str]:
    terms = [normalize_name(part) for part in query.split() if len(part) > 2]
    if not terms:
        return []
    stmt = select(KnowledgeNode).where(
        KnowledgeNode.workspace_id == workspace_id,
        or_(*[KnowledgeNode.canonical_name.contains(term) for term in terms]),
    )
    matches = list((await session.scalars(stmt)).all())
    if not matches:
        return []
    ids = {node.id for node in matches}
    edges = list(
        (
            await session.scalars(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.workspace_id == workspace_id,
                    or_(KnowledgeEdge.src_node_id.in_(ids), KnowledgeEdge.dst_node_id.in_(ids)),
                )
            )
        ).all()
    )
    node_map = {node.id: node for node in (await session.scalars(select(KnowledgeNode).where(KnowledgeNode.workspace_id == workspace_id))).all()}
    relationship_priority = {
        "produces": 0,
        "consumes": 1,
        "depends_on": 2,
        "references_fk": 3,
        "derived_from": 4,
        "defines": 5,
        "owns": 6,
        "describes": 7,
    }
    edges.sort(key=lambda edge: (relationship_priority.get(edge.relationship, 99), edge.relationship, edge.evidence))
    summaries = []
    for edge in edges:
        src = node_map.get(edge.src_node_id)
        dst = node_map.get(edge.dst_node_id)
        if src and dst:
            summaries.append(
                f"[source: {src.connector_slug}] {src.canonical_name} -[{edge.relationship}]-> "
                f"[source: {dst.connector_slug}] {dst.canonical_name} ({edge.source}: {edge.evidence})"
            )
    return summaries[:12]
