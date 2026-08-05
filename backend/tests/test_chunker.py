from app.services.ingestion.chunker import chunk_text


def test_chunk_text_short_input_preserves_metadata() -> None:
    chunks = chunk_text("orders customers revenue", metadata={"source_type": "notion"})

    assert len(chunks) == 1
    assert chunks[0].content == "orders customers revenue"
    assert chunks[0].metadata["source_type"] == "notion"
    assert chunks[0].metadata["chunk_total"] == 1


def test_chunk_text_long_input_overlaps() -> None:
    text = " ".join(f"word{i}" for i in range(20))
    chunks = chunk_text(text, max_tokens=8, overlap_tokens=2)

    assert len(chunks) > 1
    assert chunks[0].content.split()[-1] == chunks[1].content.split()[0]
    assert all(chunk.total == len(chunks) for chunk in chunks)
