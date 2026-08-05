from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.domain import WikiPage


@dataclass(frozen=True)
class NodeCandidate:
    name: str
    type: str
    aliases: tuple[str, ...]
    page_id: str
    connector_slug: str
    source_type: str


@dataclass(frozen=True)
class EdgeCandidate:
    src: str
    dst: str
    relationship: str
    evidence: str
    confidence: int
    source: str
    src_type: str = "doc"
    dst_type: str = "table"
    src_connector_slug: str = "unknown"
    dst_connector_slug: str = "unknown"


@dataclass(frozen=True)
class ColumnLineageCandidate:
    source_connector_slug: str
    source_table: str
    source_column: str
    target_connector_slug: str
    target_table: str
    target_column: str
    relationship: str
    evidence: str
    page_id: str


def normalize_name(value: str) -> str:
    clean = value.strip().lower().replace("`", "").replace("-", "_")
    clean = clean.removeprefix("model.")
    if clean.startswith("dataclaw."):
        clean = clean.removeprefix("dataclaw.")
    if "/" in clean:
        _connector, clean = clean.split("/", 1)
    return clean


def _page_node_type(page: WikiPage) -> str:
    source_type = (page.source_type or "").lower()
    if source_type == "airflow":
        return "dag"
    if source_type in {"postgres", "mysql", "snowflake", "bigquery", "redshift", "trino", "sql_server", "sqlite", "databricks"}:
        return "table"
    if source_type == "github":
        path = (page.path or "").lower()
        if "/models/" in path and path.endswith(".sql"):
            return "dbt_model"
        return "doc"
    if source_type == "dbt":
        return "dbt_model"
    return "doc"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _as_raw_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_column_ref(value: Any, default_connector_slug: str) -> tuple[str, str, str] | None:
    raw = str(value or "").strip().replace("`", "")
    if not raw or "." not in raw:
        return None
    connector_slug = default_connector_slug
    if "/" in raw:
        connector_slug, raw = raw.split("/", 1)
        connector_slug = connector_slug.strip() or default_connector_slug
    table, column = raw.rsplit(".", 1)
    table = normalize_name(table)
    column = normalize_name(column)
    if not table or not column:
        return None
    return connector_slug, table, column


def extract_candidates(pages: list[WikiPage]) -> tuple[list[NodeCandidate], list[EdgeCandidate]]:
    nodes: dict[tuple[str, str, str], NodeCandidate] = {}
    edges: list[EdgeCandidate] = []
    for page in pages:
        doc_name = normalize_name(page.path.removesuffix(".md").split("/")[-1])
        page_type = _page_node_type(page)
        connector_slug = page.source_type or "unknown"
        source_type = page.source_type or "unknown"
        nodes[(page_type, doc_name, connector_slug)] = NodeCandidate(
            doc_name,
            page_type,
            (page.path,),
            page.id,
            connector_slug,
            source_type,
        )
        frontmatter = page.frontmatter or {}
        for entity in [*page.entities, *_as_list(frontmatter.get("entities"))]:
            name = normalize_name(entity)
            if not name:
                continue
            node_type = "metric" if any(term in name for term in ("ltv", "mrr", "arr", "revenue")) else "table"
            nodes.setdefault(
                (node_type, name, connector_slug),
                NodeCandidate(name, node_type, (entity,), page.id, connector_slug, source_type),
            )
            edges.append(
                EdgeCandidate(
                    doc_name,
                    name,
                    "describes",
                    page.path,
                    95,
                    "frontmatter",
                    page_type,
                    node_type,
                    connector_slug,
                    connector_slug,
                )
            )
        for key, relationship in {
            "produces": "produces",
            "consumes": "consumes",
            "depends_on": "depends_on",
            "owner": "owns",
            "owners": "owns",
        }.items():
            for target in _as_list(frontmatter.get(key)):
                target_name = normalize_name(target)
                if not target_name:
                    continue
                target_type = "owner" if relationship == "owns" else "table"
                nodes.setdefault(
                    (target_type, target_name, connector_slug),
                    NodeCandidate(target_name, target_type, (target,), page.id, connector_slug, source_type),
                )
                edges.append(
                    EdgeCandidate(
                        doc_name,
                        target_name,
                        relationship,
                        f"{page.path} frontmatter:{key}",
                        100,
                        "frontmatter",
                        page_type,
                        target_type,
                        connector_slug,
                        connector_slug,
                    )
                )
        for link in re.findall(r"\[\[([^\]]+)\]\]", page.body or ""):
            target_name = normalize_name(link)
            if not target_name:
                continue
            nodes.setdefault(
                ("table", target_name, connector_slug),
                NodeCandidate(target_name, "table", (link,), page.id, connector_slug, source_type),
            )
            edges.append(
                EdgeCandidate(
                    doc_name,
                    target_name,
                    "describes",
                    f"{page.path} wiki-link",
                    90,
                    "wiki_link",
                    page_type,
                    "table",
                    connector_slug,
                    connector_slug,
                )
            )
        body_lower = (page.body or "").lower()
        for match in re.findall(r"(\w+_id)\s+(?:references|refers to|fk to)\s+(\w+)", body_lower):
            src = doc_name
            dst = normalize_name(match[1])
            nodes.setdefault(
                ("table", dst, connector_slug),
                NodeCandidate(dst, "table", (dst,), page.id, connector_slug, source_type),
            )
            edges.append(
                EdgeCandidate(
                    src,
                    dst,
                    "references_fk",
                    f"{match[0]} references {dst}",
                    80,
                    "fk_match",
                    page_type,
                    "table",
                    connector_slug,
                    connector_slug,
                )
            )
    return list(nodes.values()), edges


def extract_column_lineage_candidates(pages: list[WikiPage]) -> list[ColumnLineageCandidate]:
    candidates: list[ColumnLineageCandidate] = []
    for page in pages:
        connector_slug = page.source_type or "unknown"
        frontmatter = page.frontmatter or {}
        for raw in [*_as_raw_list(frontmatter.get("column_lineage")), *_as_raw_list(frontmatter.get("column_lineage_edges"))]:
            if isinstance(raw, str):
                if "->" not in raw:
                    continue
                source_raw, target_raw = raw.split("->", 1)
                relationship = "derives_from"
            elif isinstance(raw, dict):
                source_raw = raw.get("source") or raw.get("from") or raw.get("upstream")
                target_raw = raw.get("target") or raw.get("to") or raw.get("downstream")
                relationship = str(raw.get("relationship") or "derives_from")
            else:
                continue
            source = _parse_column_ref(source_raw, connector_slug)
            target = _parse_column_ref(target_raw, connector_slug)
            if not source or not target:
                continue
            candidates.append(
                ColumnLineageCandidate(
                    source_connector_slug=source[0],
                    source_table=source[1],
                    source_column=source[2],
                    target_connector_slug=target[0],
                    target_table=target[1],
                    target_column=target[2],
                    relationship=relationship,
                    evidence=f"{page.path} frontmatter:column_lineage",
                    page_id=page.id,
                )
            )
        for source_raw, target_raw in re.findall(
            r"([A-Za-z0-9_/-]+\.[A-Za-z0-9_]+)\s+(?:derives from|derived from|depends on|feeds)\s+([A-Za-z0-9_/-]+\.[A-Za-z0-9_]+)",
            page.body or "",
            flags=re.IGNORECASE,
        ):
            source = _parse_column_ref(target_raw, connector_slug)
            target = _parse_column_ref(source_raw, connector_slug)
            if not source or not target:
                continue
            candidates.append(
                ColumnLineageCandidate(
                    source_connector_slug=source[0],
                    source_table=source[1],
                    source_column=source[2],
                    target_connector_slug=target[0],
                    target_table=target[1],
                    target_column=target[2],
                    relationship="derives_from",
                    evidence=f"{page.path} body",
                    page_id=page.id,
                )
            )
    return candidates
