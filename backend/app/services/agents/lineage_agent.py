"""Lineage agent — derives FK-style relationships from synced columns.

Strategy:
  - For every pair of distinct table *names* (A != B) in a workspace, look for
    a column in A that matches a primary-key-shaped column in B (`id`,
    `<name>_id`, `<name>id`).
  - Persist a single `LineageEdge` per (source_table, target_table) — even if
    multiple datasets contain a table with that name.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AgentRun, LineageEdge, TableAsset, Workspace
from app.services.settings_store import hydrate_vector_store
from app.services.vector_store import vector_store


def _candidate_keys(table_name: str, columns: list[dict]) -> list[str]:
    keys: list[str] = []
    for column in columns or []:
        name = column.get("name") if isinstance(column, dict) else None
        if not name:
            continue
        if name == "id":
            keys.append(name)
            continue
        if name.endswith("_id") and name[:-3] == table_name.rstrip("s"):
            keys.append(name)
            continue
        if name.endswith("_id") and name == f"{table_name.rstrip('s')}_id":
            keys.append(name)
    return keys


async def run_lineage_agent(session: AsyncSession) -> AgentRun:
    workspace = await session.scalar(select(Workspace).limit(1))
    if workspace is None:
        raise RuntimeError("Workspace has not been seeded.")
    await hydrate_vector_store(session, workspace.id)

    tables = list((await session.scalars(select(TableAsset))).all())
    by_name: dict[str, list[TableAsset]] = {}
    for table in tables:
        by_name.setdefault(table.name, []).append(table)

    existing = {
        (edge.source_table, edge.target_table): edge
        for edge in (
            await session.scalars(
                select(LineageEdge).where(
                    LineageEdge.workspace_id == workspace.id,
                    LineageEdge.relationship == "references",
                )
            )
        ).all()
    }

    discovered: dict[tuple[str, str], str] = {}
    for source_name, source_tables in by_name.items():
        source_columns = {
            col.get("name")
            for table in source_tables
            for col in (table.columns or [])
            if isinstance(col, dict)
        }
        for target_name, target_tables in by_name.items():
            if source_name == target_name:
                continue
            for target in target_tables:
                for key in _candidate_keys(target_name, target.columns or []):
                    if key in source_columns and key != "id":
                        discovered[(source_name, target_name)] = key
                        break

    new_edges = 0
    for (source_table, target_table), key in discovered.items():
        edge = existing.get((source_table, target_table))
        if edge is not None:
            edge.evidence = f"Detected via column {key}."
            continue
        session.add(
            LineageEdge(
                workspace_id=workspace.id,
                source_table=source_table,
                target_table=target_table,
                relationship="references",
                evidence=f"Detected via column {key}.",
            )
        )
        new_edges += 1

    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Lineage Agent",
        status="completed",
        summary=(
            f"Examined {len(by_name)} table names and {len(discovered)} candidate edges; "
            f"persisted {new_edges} new lineage links."
        ),
        timeline=[
            {"step": "scan_tables", "status": "completed", "detail": f"{len(by_name)} unique table names."},
            {"step": "match_keys", "status": "completed", "detail": f"{len(discovered)} candidate references."},
            {"step": "persist_edges", "status": "completed", "detail": f"{new_edges} new edges."},
        ],
    )
    session.add(run)
    await session.flush()
    edges = list(
        (
            await session.scalars(
                select(LineageEdge).where(LineageEdge.workspace_id == workspace.id)
            )
        ).all()
    )
    await vector_store.upsert_lineage_edges(workspace.id, edges)
    await vector_store.upsert_agent_runs(workspace.id, [run])
    await session.commit()
    await session.refresh(run)
    return run
