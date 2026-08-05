from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)


def _mark_tool(scope: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        func.mcp_scope = scope  # type: ignore[attr-defined]
        return func

    return decorator


read_tool = _mark_tool("read")
write_tool = _mark_tool("write")
