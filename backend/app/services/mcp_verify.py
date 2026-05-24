from __future__ import annotations

from dataclasses import dataclass

from app.services.connectors.catalog import CATALOG_BY_SLUG
from app.services.mcp_catalog import tools_for_slug
from app.services.mcp_executor import implemented_mcp_tools_for_slug


@dataclass(frozen=True)
class McpCatalogIssue:
    connector_slug: str
    tool_name: str
    reason: str


def verify_mcp_catalog() -> list[McpCatalogIssue]:
    issues: list[McpCatalogIssue] = []
    for slug in CATALOG_BY_SLUG:
        catalog_read, catalog_write = tools_for_slug(slug)
        catalog_tools = {*catalog_read, *catalog_write}
        implemented = implemented_mcp_tools_for_slug(slug)
        if not implemented:
            issues.append(McpCatalogIssue(slug, "*", "connector has no executor handler"))
            continue
        for tool_name in sorted(catalog_tools - implemented):
            issues.append(McpCatalogIssue(slug, tool_name, "catalog tool has no executor backing"))
        for tool_name in sorted(implemented - catalog_tools):
            issues.append(McpCatalogIssue(slug, tool_name, "executor tool is not listed in catalog"))
    return issues
