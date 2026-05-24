import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import Connector, Dataset, KnowledgeDocument, TableAsset, Workspace
from app.services.settings_store import hydrate_vector_store
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)


async def materialize_sync(
    session: AsyncSession,
    connector: Connector,
    sync_result: dict[str, Any],
) -> int:
    tables = sync_result.get("tables") or []
    if not tables:
        return 0
    workspace = await session.scalar(select(Workspace).where(Workspace.id == connector.workspace_id))
    if workspace is None:
        return 0
    await hydrate_vector_store(session, workspace.id)
    source_type = sync_result.get("source_type") or connector.slug
    schema_name = sync_result.get("schema_name") or "public"
    dataset = await session.scalar(
        select(Dataset).where(Dataset.connector_id == connector.id)
    )
    if dataset is None:
        dataset = Dataset(
            workspace_id=workspace.id,
            connector_id=connector.id,
            name=f"{connector.display_name} catalog",
            source_type=source_type,
            schema_name=schema_name,
        )
        session.add(dataset)
        await session.flush()
    else:
        dataset.source_type = source_type
        dataset.schema_name = schema_name

    existing_tables = {
        table.name: table
        for table in (await session.scalars(select(TableAsset).where(TableAsset.dataset_id == dataset.id))).all()
    }
    seen: set[str] = set()
    for raw in tables:
        name = raw.get("name")
        if not name:
            continue
        seen.add(name)
        columns = raw.get("columns") or []
        row_count = int(raw.get("row_count") or 0)
        description = str(raw.get("description") or raw.get("comment") or "")
        if name in existing_tables:
            asset = existing_tables[name]
            asset.columns = columns
            asset.row_count = row_count
            if description:
                asset.description = description
        else:
            session.add(
                TableAsset(
                    dataset_id=dataset.id,
                    name=name,
                    description=description,
                    business_summary="",
                    row_count=row_count,
                    tags=[],
                    columns=columns,
                )
            )
    stale_vector_ids: list[str] = []
    for name, asset in existing_tables.items():
        if name not in seen:
            stale_vector_ids.extend(vector_store.ids_for_table(asset))
            await session.delete(asset)
    await session.flush()
    table_assets = list(
        (
            await session.scalars(
                select(TableAsset)
                .options(selectinload(TableAsset.dataset))
                .where(TableAsset.dataset_id == dataset.id)
            )
        ).all()
    )
    try:
        await vector_store.upsert_dataset(workspace.id, source_type, connector.slug, table_assets)
        await vector_store.delete_ids(workspace.id, stale_vector_ids)
    except Exception as exc:
        logger.warning(
            "dataset_vector_materialization_skipped",
            extra={"_connector_slug": connector.slug, "_error": exc.__class__.__name__},
        )
    docs_payload = sync_result.get("knowledge_documents") or sync_result.get("documents") or []
    if docs_payload:
        existing_docs = {
            doc.title: doc
            for doc in (
                await session.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.workspace_id == workspace.id,
                        KnowledgeDocument.connector_slug == connector.slug,
                    )
                )
            ).all()
        }
        docs: list[KnowledgeDocument] = []
        for raw in docs_payload:
            title = str(raw.get("title") or raw.get("name") or "")
            if not title:
                continue
            doc = existing_docs.get(title)
            if doc is None:
                doc = KnowledgeDocument(
                    workspace_id=workspace.id,
                    connector_slug=connector.slug,
                    title=title,
                    body=str(raw.get("body") or raw.get("content") or ""),
                    related_tables=list(raw.get("related_tables") or []),
                )
                session.add(doc)
            else:
                doc.body = str(raw.get("body") or raw.get("content") or doc.body)
                doc.related_tables = list(raw.get("related_tables") or doc.related_tables)
            docs.append(doc)
        await session.flush()
        await vector_store.upsert_knowledge_documents(workspace.id, docs)
    return len(seen)
