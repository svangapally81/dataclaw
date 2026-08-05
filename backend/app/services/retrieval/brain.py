from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import KnowledgeEdge, KnowledgeNode
from app.services.knowledge_compile.extractor import normalize_name
from app.services.settings_store import hydrate_vector_store
from app.services.vector_store import VectorResult, vector_store


@dataclass(frozen=True)
class BrainNode:
    id: str
    type: str
    canonical_name: str
    connector_slug: str
    source_type: str
    aliases: list[str]
    summary: str
    primary_wiki_page_id: str | None


@dataclass(frozen=True)
class BrainChunk:
    id: str
    node_id: str
    document: str
    metadata: dict[str, Any]
    distance: float | None = None


@dataclass(frozen=True)
class BrainContext:
    nodes: list[BrainNode] = field(default_factory=list)
    chunks: list[BrainChunk] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class BrainRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def retrieve(
        self,
        workspace_id: str,
        question: str,
        *,
        top_k_nodes: int = 20,
        max_hops: int = 2,
        chunks_per_node: int = 3,
        connector_slugs: list[str] | None = None,
    ) -> BrainContext:
        await hydrate_vector_store(self.session, workspace_id)
        candidates = await vector_store.search_brain_summaries(
            workspace_id,
            question,
            top_k=top_k_nodes,
            connector_slugs=connector_slugs,
        )
        candidate_ids = [
            str(result.metadata.get("node_id"))
            for result in candidates
            if result.metadata.get("node_id")
        ]
        if not candidate_ids:
            candidate_ids = await self._keyword_candidates(workspace_id, question, top_k_nodes)
        if not candidate_ids:
            return BrainContext(trace={"candidate_node_ids": [], "expanded_node_ids": [], "edge_ids": []})

        node_map = await self._load_nodes(workspace_id, candidate_ids)
        expanded_ids, traversed_edge_ids = await self._expand(
            workspace_id,
            list(node_map),
            max_hops=max_hops,
            connector_slugs=connector_slugs,
        )
        node_map.update(await self._load_nodes(workspace_id, expanded_ids))
        nodes = [node_map[node_id] for node_id in expanded_ids if node_id in node_map]
        if connector_slugs:
            allowed = set(connector_slugs)
            nodes = [node for node in nodes if node.connector_slug in allowed]

        chunks: list[BrainChunk] = []
        for node in nodes[:top_k_nodes]:
            chunks.extend(await self._chunks_for_node(workspace_id, question, node, limit=chunks_per_node))

        return BrainContext(
            nodes=[self._to_brain_node(node) for node in nodes[:top_k_nodes]],
            chunks=chunks,
            trace={
                "candidate_node_ids": candidate_ids,
                "expanded_node_ids": [node.id for node in nodes[:top_k_nodes]],
                "edge_ids": traversed_edge_ids,
                "connector_slugs": connector_slugs or [],
            },
        )

    async def _keyword_candidates(self, workspace_id: str, question: str, limit: int) -> list[str]:
        terms = [normalize_name(part) for part in question.split() if len(part) > 2]
        if not terms:
            return []
        stmt = (
            select(KnowledgeNode)
            .where(
                KnowledgeNode.workspace_id == workspace_id,
                or_(*[KnowledgeNode.canonical_name.contains(term) for term in terms]),
            )
            .limit(limit)
        )
        return [node.id for node in (await self.session.scalars(stmt)).all()]

    async def _load_nodes(self, workspace_id: str, node_ids: list[str]) -> dict[str, KnowledgeNode]:
        if not node_ids:
            return {}
        nodes = list(
            (
                await self.session.scalars(
                    select(KnowledgeNode).where(
                        KnowledgeNode.workspace_id == workspace_id,
                        KnowledgeNode.id.in_(node_ids),
                    )
                )
            ).all()
        )
        return {node.id: node for node in nodes}

    async def _expand(
        self,
        workspace_id: str,
        start_ids: list[str],
        *,
        max_hops: int,
        connector_slugs: list[str] | None,
    ) -> tuple[list[str], list[str]]:
        visible: list[str] = []
        visible_set: set[str] = set()
        frontier = list(dict.fromkeys(start_ids))
        edge_ids: list[str] = []
        allowed = set(connector_slugs or [])

        for node_id in frontier:
            if node_id not in visible_set:
                visible.append(node_id)
                visible_set.add(node_id)

        for _ in range(max_hops):
            if not frontier:
                break
            edges = list(
                (
                    await self.session.scalars(
                        select(KnowledgeEdge).where(
                            KnowledgeEdge.workspace_id == workspace_id,
                            or_(KnowledgeEdge.src_node_id.in_(frontier), KnowledgeEdge.dst_node_id.in_(frontier)),
                        )
                    )
                ).all()
            )
            neighbor_ids = {
                edge.dst_node_id if edge.src_node_id in frontier else edge.src_node_id
                for edge in edges
            }
            neighbors = await self._load_nodes(workspace_id, list(neighbor_ids))
            next_frontier: list[str] = []
            for edge in edges:
                neighbor_id = edge.dst_node_id if edge.src_node_id in frontier else edge.src_node_id
                neighbor = neighbors.get(neighbor_id)
                if neighbor is None:
                    continue
                if allowed and neighbor.connector_slug not in allowed:
                    continue
                edge_ids.append(edge.id)
                if neighbor_id not in visible_set:
                    visible.append(neighbor_id)
                    visible_set.add(neighbor_id)
                    next_frontier.append(neighbor_id)
            frontier = next_frontier
        return visible, edge_ids

    async def _chunks_for_node(
        self,
        workspace_id: str,
        question: str,
        node: KnowledgeNode,
        *,
        limit: int,
    ) -> list[BrainChunk]:
        asset_ids = [node.primary_wiki_page_id] if node.primary_wiki_page_id else None
        results = await vector_store.search(
            workspace_id,
            f"{node.canonical_name} {question}",
            top_k=limit,
            connector_slugs=[node.connector_slug],
            asset_ids=asset_ids,
        )
        return [self._to_brain_chunk(node.id, result) for result in results]

    def _to_brain_node(self, node: KnowledgeNode) -> BrainNode:
        return BrainNode(
            id=node.id,
            type=node.type,
            canonical_name=node.canonical_name,
            connector_slug=node.connector_slug,
            source_type=node.source_type,
            aliases=node.aliases or [],
            summary=node.summary,
            primary_wiki_page_id=node.primary_wiki_page_id,
        )

    def _to_brain_chunk(self, node_id: str, result: VectorResult) -> BrainChunk:
        metadata = {**result.metadata, "node_id": node_id}
        return BrainChunk(
            id=result.id,
            node_id=node_id,
            document=result.document,
            metadata=metadata,
            distance=result.distance,
        )
