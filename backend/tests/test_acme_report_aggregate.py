from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_acme_report_aggregate_rejects_malformed_live_rows() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(repo_root),
                str(repo_root / "backend"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    script = textwrap.dedent(
        """
        from app.services.mcp_catalog import tools_for_slug
        from tests.integration.acme.report.aggregate import _live_coverage_row, _live_tool_set_row

        assert _live_coverage_row(
            {"connector": "postgres", "tool": "read_list_tables", "status": "ok"}
        )[2] == "green"
        assert _live_coverage_row(
            {"connector": "snowflake", "tool": "write_create_task", "status": "executed"}
        )[2] == "green"
        assert _live_coverage_row(
            {"connector": "redshift", "tool": "write_pause_cluster", "status": "paused"}
        )[2] == "green"
        assert _live_coverage_row(
            {"connector": "github", "tool": "write_delete_branch", "status": "deleted"}
        )[2] == "green"
        assert _live_coverage_row(
            {"connector": "dagster", "tool": "write_terminate_run", "status": "terminated"}
        )[2] == "green"
        assert _live_coverage_row(
            {"connector": "postgres", "tool": "read_list_tables", "status": "stubbed"}
        )[2] == "red"
        assert _live_coverage_row(
            {"connector": "postgres", "tool": "read_fake_tool", "status": "ok"}
        )[2] == "red"

        postgres_tools = set().union(*tools_for_slug("postgres"))
        assert _live_tool_set_row("postgres", set(postgres_tools), len(postgres_tools)) is None
        missing_one = set(postgres_tools)
        missing_one.remove("read_list_tables")
        row = _live_tool_set_row("postgres", missing_one, len(postgres_tools))
        assert row is not None
        assert row[0] == "postgres.live_tool_set"
        assert row[2] == "red"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_report_aggregate_respects_output_dir_override() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(repo_root),
                str(repo_root / "backend"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
        "ACME_REPORT_DOCS_DIR": "artifacts/acme-report-test",
    }
    script = textwrap.dedent(
        """
        from tests.integration.acme.report import aggregate

        assert aggregate.DOCS_DIR == aggregate.REPO_ROOT / "artifacts/acme-report-test"
        assert aggregate.MCP_REPORT == aggregate.DOCS_DIR / "MCP_COVERAGE.md"
        assert aggregate.E2E_REPORT == aggregate.DOCS_DIR / "E2E_REPORT.md"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)
