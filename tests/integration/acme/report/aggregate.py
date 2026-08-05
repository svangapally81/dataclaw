from __future__ import annotations

# ruff: noqa: E402,I001

import json
import os
import sys
from pathlib import Path
from typing import Any

ACME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ACME_ROOT.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.mcp_catalog import tools_for_slug  # noqa: E402
from tests.integration.acme.common import ACME_EXCLUDED_CONNECTORS, EXPECTED_ACME_CONNECTORS  # noqa: E402

_docs_dir = Path(os.getenv("ACME_REPORT_DOCS_DIR", str(REPO_ROOT / "docs")))
DOCS_DIR = _docs_dir if _docs_dir.is_absolute() else REPO_ROOT / _docs_dir
MCP_REPORT = DOCS_DIR / "MCP_COVERAGE.md"
E2E_REPORT = DOCS_DIR / "E2E_REPORT.md"
EXPECTED_E2E_REPORTS = [
    "compile-retrieval.json",
    "chat-1_docs.json",
    "chat-2_bq.json",
    "chat-3_prefect.json",
    "chat-4_messy.json",
    "chat-5_write.json",
    "agents.json",
]
LIVE_COVERAGE_OK_STATUSES = {
    "ok",
    "pending_approval",
    "created",
    "triggered",
    "updated",
    "cancelled",
    "executed",
    "deleted",
    "paused",
    "resumed",
    "terminated",
    "fixture",
}


def _json_reports() -> list[Path]:
    roots = [REPO_ROOT, ACME_ROOT, REPO_ROOT / "artifacts"]
    found: list[Path] = []
    for root in roots:
        if root.exists():
            found.extend(root.rglob("*.json"))
    return sorted({path.resolve() for path in found if path.name.startswith(("coverage-", "chat-", "agents", "compile-"))})


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"path": str(path), "error": "invalid json"}


def _summarize_pytest(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("error"):
        return {"total": 1, "passed": 0, "failed": 0, "skipped": 0, "errors": 1}
    summary = report.get("summary", {})
    if not summary:
        return {"total": 1, "passed": 0, "failed": 0, "skipped": 0, "errors": 1}
    return {
        "total": summary.get("total", 0),
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "errors": summary.get("errors", 0),
    }


def _status(summary: dict[str, Any]) -> str:
    if summary.get("failed") or summary.get("errors") or summary.get("skipped"):
        return "red"
    return "green"


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    reports = [(path, _load(path)) for path in _json_reports()]
    seen = {path.name for path, _ in reports}
    coverage_rows = []
    e2e_rows = []
    live_tools: dict[str, set[str]] = {}
    live_row_counts: dict[str, int] = {}
    for path, payload in reports:
        if path.name.startswith("coverage-live-") and isinstance(payload, list):
            connector = path.name.removeprefix("coverage-live-").removesuffix(".json")
            if not payload:
                coverage_rows.append((path.name, _pending_summary(), "pending"))
                continue
            live_row_counts[connector] = len(payload)
            observed_tools: set[str] = set()
            for item in payload:
                tool = str(item.get("tool") or "unknown")
                if item.get("connector") == connector and _is_catalog_tool(connector, tool):
                    observed_tools.add(tool)
                coverage_rows.append(_live_coverage_row(item))
            live_tools[connector] = observed_tools
            continue
        summary = _summarize_pytest(payload)
        row = (path.name, summary, _status(summary))
        if path.name.startswith("coverage-"):
            coverage_rows.append(row)
        else:
            e2e_rows.append(row)

    for connector in EXPECTED_ACME_CONNECTORS:
        for name in (f"coverage-{connector}.json", f"coverage-live-{connector}.json"):
            if name not in seen:
                coverage_rows.append((name, _pending_summary(), "pending"))
        if f"coverage-live-{connector}.json" in seen:
            observed_tools = live_tools.get(connector, set())
            tool_set_row = _live_tool_set_row(connector, observed_tools, live_row_counts.get(connector, 0))
            if tool_set_row is not None:
                coverage_rows.append(tool_set_row)
    for name in EXPECTED_E2E_REPORTS:
        if name not in seen:
            e2e_rows.append((name, _pending_summary(), "pending"))

    coverage_notes = [
        f"Acme live gate covers {len(EXPECTED_ACME_CONNECTORS)} supported/story connectors.",
        *[
            f"`{slug}` is excluded: {reason}"
            for slug, reason in sorted(ACME_EXCLUDED_CONNECTORS.items())
        ],
    ]
    MCP_REPORT.write_text(_render("MCP Coverage", coverage_rows, notes=coverage_notes), encoding="utf-8")
    E2E_REPORT.write_text(_render("E2E Report", e2e_rows), encoding="utf-8")
    print(f"Wrote {MCP_REPORT.resolve().relative_to(REPO_ROOT)}")
    print(f"Wrote {E2E_REPORT.resolve().relative_to(REPO_ROOT)}")
    return 0


def _pending_summary() -> dict[str, Any]:
    return {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}


def _expected_tools(connector: str) -> set[str]:
    read_tools, write_tools = tools_for_slug(connector)
    return {*read_tools, *write_tools}


def _live_tool_set_row(
    connector: str, observed_tools: set[str], live_row_count: int
) -> tuple[str, dict[str, Any], str] | None:
    expected_tools = _expected_tools(connector)
    duplicate_or_invalid_rows = max(live_row_count - len(observed_tools), 0)
    if observed_tools == expected_tools and not duplicate_or_invalid_rows:
        return None
    return (
        f"{connector}.live_tool_set",
        {
            "total": len(expected_tools),
            "passed": len(expected_tools & observed_tools),
            "failed": max(len(expected_tools - observed_tools) + duplicate_or_invalid_rows, 1),
            "skipped": 0,
            "errors": 0,
        },
        "red",
    )


def _live_coverage_row(item: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    connector = str(item.get("connector") or "unknown")
    tool = str(item.get("tool") or "unknown")
    status = str(item.get("status") or "unknown")
    valid = status in LIVE_COVERAGE_OK_STATUSES and _is_catalog_tool(connector, tool)
    row_status = "fixture" if valid and status == "fixture" else "green" if valid else "red"
    return (
        f"{connector}.{tool}",
        {"total": 1, "passed": 1 if valid else 0, "failed": 0 if valid else 1, "skipped": 0, "errors": 0},
        row_status,
    )


def _is_catalog_tool(connector: str, tool: str) -> bool:
    try:
        read_tools, write_tools = tools_for_slug(connector)
    except KeyError:
        return False
    return tool in {*read_tools, *write_tools}


def _render(title: str, rows: list[tuple[str, dict[str, Any], str]], *, notes: list[str] | None = None) -> str:
    lines = [
        f"# {title}",
        "",
        "Generated from Acme rig pytest JSON reports.",
        "",
    ]
    for note in notes or []:
        lines.append(f"- {note}")
    if notes:
        lines.append("")
    lines.extend(
        [
            "| Report | Status | Passed | Failed | Skipped | Errors | Total |",
            "|--------|--------|--------|--------|---------|--------|-------|",
        ]
    )
    if not rows:
        lines.append("| _No reports found_ | pending | 0 | 0 | 0 | 0 | 0 |")
    for name, summary, status in rows:
        lines.append(
            "| "
            f"`{name}` | {status} | {summary['passed']} | {summary['failed']} | "
            f"{summary['skipped']} | {summary['errors']} | {summary['total']} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
