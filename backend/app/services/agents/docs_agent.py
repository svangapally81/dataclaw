"""Documentation agent — generates column-level descriptions.

Uses OpenAI when configured; otherwise falls back to a deterministic heuristic
that infers descriptions from column name patterns. Updates each TableAsset's
`columns[].description` and adds a Docs-tag to the table's tag list.
"""

from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI, OpenAIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import AgentRun, TableAsset, Workspace
from app.services.settings_store import resolve_openai
from app.services.vector_store import vector_store

logger = logging.getLogger("dataclaw.agents.docs")

HEURISTIC_PATTERNS = [
    ("_id", "Stable identifier."),
    ("_at", "Timestamp value (UTC)."),
    ("_count", "Row or event tally."),
    ("amount", "Monetary or quantitative value."),
    ("revenue", "Monetary value in source currency."),
    ("email", "User email address."),
    ("name", "Human-readable label."),
    ("status", "Lifecycle or state tag."),
]
LLM_TABLE_LIMIT = 1
LLM_TIMEOUT_SECONDS = 5.0
VECTOR_UPSERT_TIMEOUT_SECONDS = 10.0


def _heuristic_description(name: str) -> str:
    lower = name.lower()
    for needle, description in HEURISTIC_PATTERNS:
        if needle in lower:
            return description
    return ""


async def _llm_descriptions(
    client: AsyncOpenAI,
    model: str,
    table: TableAsset,
    retrieval_context: list[str],
) -> dict[str, str] | None:
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You document data warehouse columns. Reply with a strict JSON object "
                        "mapping column name to a concise (<= 18 word) business description. "
                        "Do not include extra commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "table": table.name,
                            "context": table.description or table.business_summary or "",
                            "retrieval_context": retrieval_context,
                            "columns": [
                                col.get("name") for col in table.columns or [] if isinstance(col, dict)
                            ],
                        }
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
    except OpenAIError as exc:
        logger.warning("docs_agent_openai_failed", extra={"_table": table.name, "_error": exc.__class__.__name__})
        return None
    content = completion.choices[0].message.content
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("docs_agent_invalid_json", extra={"_table": table.name, "_error": exc.__class__.__name__})
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): str(value) for key, value in parsed.items()}


async def run_docs_agent(session: AsyncSession) -> AgentRun:
    workspace = await session.scalar(select(Workspace).limit(1))
    if workspace is None:
        raise RuntimeError("Workspace has not been seeded.")
    tables = list(
        (
            await session.scalars(select(TableAsset).options(selectinload(TableAsset.dataset)))
        ).all()
    )
    api_key, model, base_url, _embedding_model = await resolve_openai(session)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=LLM_TIMEOUT_SECONDS) if api_key else None
    used_llm = 0
    used_heuristic = 0

    for table in tables:
        columns = list(table.columns or [])
        if not columns:
            continue
        descriptions: dict[str, str] = {}
        retrieval_context: list[str] = []
        if client and used_llm < LLM_TABLE_LIMIT:
            generated = await _llm_descriptions(client, model or "gpt-4.1-mini", table, retrieval_context)
            if generated:
                descriptions = generated
                used_llm += 1
        if not descriptions:
            descriptions = {
                col.get("name"): _heuristic_description(col.get("name") or "")
                for col in columns
                if isinstance(col, dict) and col.get("name")
            }
            used_heuristic += 1

        new_columns = []
        for col in columns:
            if not isinstance(col, dict):
                new_columns.append(col)
                continue
            name = col.get("name") or ""
            description = descriptions.get(name) or col.get("description") or ""
            new_columns.append({**col, "description": description})
        table.columns = new_columns
        rest = [tag for tag in (table.tags or []) if tag != "documented"]
        rest.append("documented")
        table.tags = sorted(rest)

    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Docs Agent",
        status="completed",
        summary=(
            f"Documented {len(tables)} tables — {used_llm} via LLM, {used_heuristic} via heuristic."
        ),
        timeline=[
            {"step": "load_tables", "status": "completed", "detail": f"{len(tables)} tables."},
            {
                "step": "generate_descriptions",
                "status": "completed" if used_llm or used_heuristic else "skipped",
                "detail": f"llm={used_llm} heuristic={used_heuristic}",
            },
        ],
    )
    session.add(run)
    await session.flush()
    try:
        await asyncio.wait_for(
            vector_store.upsert_dataset(workspace.id, "agent_enriched", "docs", tables),
            timeout=VECTOR_UPSERT_TIMEOUT_SECONDS,
        )
        await asyncio.wait_for(vector_store.upsert_agent_runs(workspace.id, [run]), timeout=VECTOR_UPSERT_TIMEOUT_SECONDS)
    except Exception as exc:
        run.timeline = [
            *(run.timeline or []),
            {
                "step": "vector_upsert",
                "status": "skipped",
                "detail": f"{exc.__class__.__name__}; database documentation was still updated.",
            },
        ]
    await session.commit()
    await session.refresh(run)
    return run
