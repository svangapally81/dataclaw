from __future__ import annotations

import json
import os

import pytest
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import WikiPage, Workspace
from app.services.knowledge_compile.service import CompileService
from app.services.retrieval import BrainRetriever
from app.services.vector_store import vector_store

pytestmark = pytest.mark.integration


EVAL_CASES = [
    ("How is customer lifetime value calculated?", "lifetime_value revenue refunds subscriptions"),
    ("What feeds daily revenue?", "daily_orders_refresh orders payments revenue"),
    ("Which source documents explain churn risk?", "churn_score support tickets subscription cancellations"),
    ("Where does paid CAC come from?", "paid_cac ad_spend campaigns signups"),
    ("How do we identify activated customers?", "activation first_project_created onboarding_completed"),
    ("What upstream job loads product events?", "event_warehouse_loader product_events"),
    ("How is gross margin calculated?", "gross_margin revenue cost_of_goods_sold"),
    ("Which table powers the executive ARR dashboard?", "arr_dashboard subscriptions accounts"),
    ("Where are refund events documented?", "refunds payments refund_alerts"),
    ("What feeds email conversion reporting?", "email_send_loader email_events campaigns"),
    ("How do we calculate expansion revenue?", "expansion_revenue subscription_changes accounts"),
    ("Which model depends on stg_orders?", "stg_orders fct_revenue_daily intermediate_orders"),
    ("What is the source for campaign attribution?", "attribution_backfill campaigns product_events"),
    ("Which workflow refreshes customer 360?", "weekly_customer_360 customers subscriptions support_tickets"),
    ("Where is invoice aging defined?", "invoice_aging invoices payments"),
    ("How is net revenue different from gross revenue?", "net_revenue gross_revenue refunds discounts"),
    ("What pipeline loads support tickets?", "support_ticket_sync support_tickets"),
    ("Which assets describe signup funnel?", "signup_to_activation_funnel signups activation"),
    ("Where is data quality for orders checked?", "data_quality_checks orders freshness uniqueness"),
    ("What feeds marketing ROI?", "marketing_roi campaigns ad_spend revenue"),
]


async def _seed_workspace(session: AsyncSession) -> str:
    workspace = Workspace(name="Retrieval Quality")
    session.add(workspace)
    await session.flush()
    pages: list[WikiPage] = []
    for index, (_question, expected_terms) in enumerate(EVAL_CASES):
        entity = expected_terms.split()[0]
        connector = ["postgres", "notion", "airflow", "dbt"][index % 4]
        pages.append(
            WikiPage(
                workspace_id=workspace.id,
                path=f"wiki/{connector}/{entity}.md",
                disk_path=f"/tmp/{entity}.md",
                tier=1,
                source_type=connector,
                source_id=entity,
                title=entity,
                body=(
                    f"{entity} is defined by these evidence terms: {expected_terms}. "
                    f"It links to [[{expected_terms.split()[-1]}]] for operational context."
                ),
                frontmatter={"entities": [entity, expected_terms.split()[-1]]},
                entities=[entity, expected_terms.split()[-1]],
                content_hash=f"retrieval-quality-{index}",
            )
        )
    session.add_all(pages)
    await session.commit()
    await vector_store.upsert_wiki_pages(workspace.id, pages)
    await CompileService(session).compile(workspace.id)
    return workspace.id


def _brain_context_text(result) -> str:
    node_text = "\n".join(f"{node.connector_slug}:{node.canonical_name}: {node.summary}" for node in result.nodes)
    chunk_text = "\n".join(chunk.document for chunk in result.chunks)
    return f"{node_text}\n{chunk_text}".strip()


async def _flat_context_text(workspace_id: str, question: str) -> str:
    results = await vector_store.search(workspace_id, question, top_k=12)
    return "\n".join(result.document for result in results)


async def _judge_score(client: AsyncOpenAI, *, question: str, expected_terms: str, context: str) -> float:
    response = await client.chat.completions.create(
        model=os.getenv("DATACLAW_RETRIEVAL_JUDGE_MODEL", "gpt-4.1-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "Score whether the retrieval context contains the evidence needed to answer the question. "
                    "Return strict JSON: {\"score\": number between 0 and 1}. Penalize missing expected terms."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question, "expected_terms": expected_terms, "context": context[:8000]}),
            },
        ],
        response_format={"type": "json_object"},
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return max(0.0, min(1.0, float(payload.get("score", 0))))


@pytest.mark.asyncio
async def test_brain_retrieval_scores_thirty_percent_above_flat_baseline(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.getenv("DATACLAW_FULL_STACK_RELEASE_GATE") != "1":
        pytest.skip("Set DATACLAW_FULL_STACK_RELEASE_GATE=1 to run the retrieval quality release gate.")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for the LLM-judged retrieval quality gate.")
    monkeypatch.delenv("DATACLAW_VECTOR_TEST_DOUBLE", raising=False)
    assert not vector_store._use_test_double()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retrieval_quality.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        workspace_id = await _seed_workspace(session)
        judge = AsyncOpenAI()
        brain_total = 0.0
        flat_total = 0.0
        for question, expected_terms in EVAL_CASES:
            brain = await BrainRetriever(session).retrieve(workspace_id, question)
            brain_total += await _judge_score(
                judge,
                question=question,
                expected_terms=expected_terms,
                context=_brain_context_text(brain),
            )
            flat_total += await _judge_score(
                judge,
                question=question,
                expected_terms=expected_terms,
                context=await _flat_context_text(workspace_id, question),
            )

    await engine.dispose()
    assert len(EVAL_CASES) == 20
    assert flat_total > 0, "flat baseline corpus produced no judge-recognized evidence"
    assert brain_total >= 14.0, f"brain retrieval absolute score too low: {brain_total:.2f}/20"
    assert brain_total >= flat_total * 1.3, f"brain={brain_total:.2f} flat={flat_total:.2f}"
