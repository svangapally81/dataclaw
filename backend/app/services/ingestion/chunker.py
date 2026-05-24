from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    content: str
    index: int
    total: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _token_budget_to_words(tokens: int) -> int:
    return max(1, int(tokens * 0.75))


def chunk_text(
    text: str,
    max_tokens: int = 2000,
    overlap_tokens: int = 200,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    words = text.split()
    if not words:
        return []
    max_words = _token_budget_to_words(max_tokens)
    overlap_words = min(_token_budget_to_words(overlap_tokens), max_words - 1)
    step = max_words - overlap_words
    windows: list[list[str]] = []
    start = 0
    while start < len(words):
        windows.append(words[start : start + max_words])
        if start + max_words >= len(words):
            break
        start += step
    total = len(windows)
    base_metadata = dict(metadata or {})
    return [
        Chunk(
            content=" ".join(window),
            index=index,
            total=total,
            metadata={**base_metadata, "chunk_index": index, "chunk_total": total},
        )
        for index, window in enumerate(windows)
    ]
