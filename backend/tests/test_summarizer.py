import pytest

from app.services.ingestion.summarizer import content_hash, summarize_artifact


@pytest.mark.asyncio
async def test_summarizer_extracts_entities_and_skips_openai_without_key() -> None:
    content = {
        "title": "Data Glossary",
        "body": "The [[orders]] table joins [[customers]] and calculates lifetime_value.",
        "owner": "analytics",
    }
    draft = await summarize_artifact(
        workspace_id="ws1",
        source_type="notion",
        source_id="page-1",
        content=content,
        existing_page="# Prior human edit",
    )

    assert draft.path == "wiki/notion/data-glossary.md"
    assert {"orders", "customers", "lifetime_value"}.issubset(set(draft.entities))
    assert draft.frontmatter["owner"] == "analytics"
    assert draft.frontmatter["last_content_hash"] == content_hash(
        '{\n  "body": "The [[orders]] table joins [[customers]] and calculates lifetime_value.",\n'
        '  "owner": "analytics",\n  "title": "Data Glossary"\n}'
    )
    assert "orders" in draft.body


@pytest.mark.asyncio
async def test_summarizer_idempotent_for_same_content_hash() -> None:
    kwargs = {
        "workspace_id": "ws1",
        "source_type": "github",
        "source_id": "repo/README.md",
        "content": "README for [[orders]] and [[customers]].",
    }
    first = await summarize_artifact(**kwargs)
    second = await summarize_artifact(**kwargs, existing_page="User-added note")

    assert second.content_hash == first.content_hash
    assert second.frontmatter["last_content_hash"] == first.frontmatter["last_content_hash"]
    assert second.path == first.path
