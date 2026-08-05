from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import KnowledgeEdge, KnowledgeNode
from app.services.knowledge_compile.extractor import EdgeCandidate, NodeCandidate


@dataclass
class GraphWriteStats:
    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0


async def write_graph(
    session: AsyncSession,
    workspace_id: str,
    nodes: list[NodeCandidate],
    edges: list[EdgeCandidate],
    compile_run_id: str,
    edge_source_scope: set[str] | None = None,
) -> GraphWriteStats:
    stats = GraphWriteStats()
    existing_nodes = {
        (node.type, node.canonical_name, node.connector_slug): node
        for node in (await session.scalars(select(KnowledgeNode).where(KnowledgeNode.workspace_id == workspace_id))).all()
    }
    node_rows: dict[tuple[str, str, str], KnowledgeNode] = {}
    for candidate in nodes:
        key = (candidate.type, candidate.name, candidate.connector_slug)
        row = existing_nodes.get(key)
        if row is None:
            row = KnowledgeNode(
                workspace_id=workspace_id,
                type=candidate.type,
                canonical_name=candidate.name,
                connector_slug=candidate.connector_slug,
                source_type=candidate.source_type,
                aliases=list(candidate.aliases),
                summary=_node_summary(candidate),
                primary_wiki_page_id=candidate.page_id,
                compile_run_id=compile_run_id,
            )
            session.add(row)
            stats.nodes_created += 1
        else:
            row.connector_slug = candidate.connector_slug
            row.source_type = candidate.source_type
            row.aliases = sorted(set(row.aliases or []) | set(candidate.aliases))
            row.summary = _node_summary(candidate)
            row.primary_wiki_page_id = candidate.page_id
            row.compile_run_id = compile_run_id
            stats.nodes_updated += 1
        node_rows[key] = row
    await session.flush()

    scoped_src_ids: set[str] | None = None
    if edge_source_scope is not None:
        scoped_src_ids = {
            row.id
            for (node_type, node_name, _connector_slug), row in node_rows.items()
            if node_type == "doc" and node_name in edge_source_scope
        }
    existing_edge_rows = list(
        (await session.scalars(select(KnowledgeEdge).where(KnowledgeEdge.workspace_id == workspace_id))).all()
    )
    if scoped_src_ids is not None:
        existing_edge_rows = [edge for edge in existing_edge_rows if edge.src_node_id in scoped_src_ids]
    existing_edges = {
        (edge.src_node_id, edge.dst_node_id, edge.relationship, edge.source): edge
        for edge in existing_edge_rows
    }
    seen_edges: set[tuple[str, str, str, str]] = set()
    for candidate in edges:
        src = node_rows.get((candidate.src_type, candidate.src, candidate.src_connector_slug)) or node_rows.get(
            ("doc", candidate.src, candidate.src_connector_slug)
        )
        dst = node_rows.get((candidate.dst_type, candidate.dst, candidate.dst_connector_slug)) or node_rows.get(
            ("table", candidate.dst, candidate.dst_connector_slug)
        )
        if src is None or dst is None or src.id == dst.id:
            continue
        edge_key = (src.id, dst.id, candidate.relationship, candidate.source)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        row = existing_edges.get(edge_key)
        if row is None:
            session.add(
                KnowledgeEdge(
                    workspace_id=workspace_id,
                    src_node_id=src.id,
                    dst_node_id=dst.id,
                    relationship=candidate.relationship,
                    evidence=candidate.evidence,
                    confidence=candidate.confidence,
                    source=candidate.source,
                    compile_run_id=compile_run_id,
                )
            )
            stats.edges_created += 1
        else:
            row.evidence = candidate.evidence
            row.confidence = candidate.confidence
            row.compile_run_id = compile_run_id
    stale_ids = [edge.id for key, edge in existing_edges.items() if key not in seen_edges]
    if stale_ids:
        await session.execute(
            delete(KnowledgeEdge).where(
                KnowledgeEdge.workspace_id == workspace_id,
                KnowledgeEdge.id.in_(stale_ids),
            )
        )
    await session.flush()
    return stats


def _node_summary(candidate: NodeCandidate) -> str:
    alias_text = ", ".join(candidate.aliases[:3])
    source = candidate.connector_slug or candidate.source_type or "unknown"
    if alias_text:
        return f"{candidate.type} {candidate.name} from {source}; aliases: {alias_text}."
    return f"{candidate.type} {candidate.name} from {source}."
