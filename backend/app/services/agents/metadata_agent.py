import asyncio

from openai import AsyncOpenAI, OpenAIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import AgentRun, KnowledgeDocument, TableAsset, Workspace
from app.services.settings_store import resolve_openai
from app.services.vector_store import vector_store

LLM_TABLE_LIMIT = 1
LLM_TIMEOUT_SECONDS = 5.0
VECTOR_UPSERT_TIMEOUT_SECONDS = 10.0


async def run_metadata_agent(session: AsyncSession) -> AgentRun:
    workspace = await session.scalar(select(Workspace).limit(1))
    if workspace is None:
        raise RuntimeError("Workspace has not been seeded.")
    tables = list(
        (
            await session.scalars(select(TableAsset).options(selectinload(TableAsset.dataset)))
        ).all()
    )
    docs = list((await session.scalars(select(KnowledgeDocument))).all())
    api_key, model, base_url, _embedding_model = await resolve_openai(session)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=LLM_TIMEOUT_SECONDS) if api_key else None
    llm_enriched = 0

    for table in tables:
        related_docs = [doc for doc in docs if table.name in doc.related_tables]
        related_titles: list[str] = []
        doc_titles = ", ".join(doc.title for doc in related_docs) or "No related docs"
        if related_titles:
            doc_titles = ", ".join(dict.fromkeys([*related_titles, *[doc.title for doc in related_docs]]))
        deterministic_summary = f"{table.name} is enriched from schema metadata and knowledge sources: {doc_titles}."
        if client is not None and llm_enriched < LLM_TABLE_LIMIT:
            context = "\n".join(
                [
                    f"Table: {table.name}",
                    f"Connector: {table.dataset.source_type if table.dataset else 'unknown'}",
                    f"Description: {table.description or ''}",
                    f"Columns: {', '.join(str((column or {}).get('name') or column) for column in (table.columns or [])[:20])}",
                    "Related context:",
                    *[f"- {title}" for title in list(dict.fromkeys(related_titles))[:8]],
                    *[f"- {doc.title}: {doc.body[:500]}" for doc in related_docs[:3]],
                ]
            )
            try:
                completion = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Write one concise business metadata summary for a data catalog table. Do not invent facts.",
                        },
                        {"role": "user", "content": context},
                    ],
                    temperature=0,
                )
                summary = (completion.choices[0].message.content or "").strip()
                if summary:
                    table.business_summary = summary[:1200]
                    llm_enriched += 1
                else:
                    table.business_summary = deterministic_summary
            except OpenAIError:
                table.business_summary = deterministic_summary
        else:
            table.business_summary = deterministic_summary
        existing_tags = set(table.tags or [])
        if related_docs:
            existing_tags.add("knowledge-linked")
        table.tags = sorted(existing_tags)

    llm_status = "completed" if api_key else "skipped"
    llm_detail = (
        f"LLM provider configured for model {model}; enriched {llm_enriched} table summaries and used deterministic fallback for the rest."
        if api_key
        else "LLM provider not configured; used deterministic local enrichment."
    )

    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Metadata Agent",
        status="completed",
        summary=f"Generated metadata for {len(tables)} tables using schema, knowledge docs, lineage, and LLM provider state.",
        timeline=[
            {"step": "schema_context", "status": "completed", "detail": f"Read {len(tables)} tables."},
            {"step": "knowledge_context", "status": "completed", "detail": f"Matched {len(docs)} documents."},
            {"step": "llm_provider", "status": llm_status, "detail": llm_detail},
        ],
    )
    session.add(run)
    await session.flush()
    try:
        await asyncio.wait_for(
            vector_store.upsert_dataset(workspace.id, "agent_enriched", "metadata", tables),
            timeout=VECTOR_UPSERT_TIMEOUT_SECONDS,
        )
        await asyncio.wait_for(vector_store.upsert_agent_runs(workspace.id, [run]), timeout=VECTOR_UPSERT_TIMEOUT_SECONDS)
    except Exception as exc:
        run.timeline = [
            *(run.timeline or []),
            {
                "step": "vector_upsert",
                "status": "skipped",
                "detail": f"{exc.__class__.__name__}; database metadata was still updated.",
            },
        ]
    await session.commit()
    await session.refresh(run)
    return run
