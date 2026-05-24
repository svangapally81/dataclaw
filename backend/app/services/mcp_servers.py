from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.mcp_catalog import tools_for_slug
from app.services.mcp_executor import execute_mcp_tool

_SERVERS: dict[str, FastMCP] = {}


def build_mcp_server(slug: str) -> FastMCP:
    if slug in _SERVERS:
        return _SERVERS[slug]
    server = FastMCP(
        f"dataclaw-{slug}",
        instructions=(
            "DataClaw connector MCP server. Pass agent_id with each call; "
            "DataClaw validates the agent's read/write grant before executing tools."
        ),
        stateless_http=True,
        streamable_http_path="/",
        json_response=True,
    )
    read_tools, write_tools = tools_for_slug(slug)
    for tool_name in [*read_tools, *write_tools]:
        server.add_tool(_tool_callable(slug, tool_name), name=tool_name)
    _SERVERS[slug] = server
    return server


def build_mcp_app(slug: str):
    _SERVERS.pop(slug, None)
    return build_mcp_server(slug).streamable_http_app()


def mcp_lifespan_contexts():
    return [
        server.session_manager.run()
        for server in _SERVERS.values()
        if server.session_manager is not None
    ]


def _tool_callable(slug: str, tool_name: str) -> Callable[..., Any]:
    async def run_tool(
        agent_id: str,
        arguments: dict[str, Any] | None = None,
        user_email: str = "mcp@dataclaw.local",
    ) -> dict[str, Any]:
        if arguments and "__approved" in arguments:
            raise ValueError("__approved is reserved.")
        settings = get_settings()
        engine = create_async_engine(settings.demo_database_url, pool_pre_ping=True)
        try:
            async with SessionLocal() as session:
                return await execute_mcp_tool(
                    session=session,
                    engine=engine,
                    connector_slug=slug,
                    tool_name=tool_name,
                    arguments=arguments or {},
                    agent_id=agent_id,
                    user_email=user_email,
                )
        finally:
            await engine.dispose()

    run_tool.__name__ = tool_name
    run_tool.__doc__ = (
        f"Execute {slug}.{tool_name}. Requires agent_id and validates DataClaw MCP grants."
    )
    return run_tool
