from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_acme_read_tool_coverage_rejects_status_only_payloads() -> None:
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
        import pytest

        from tests.integration.acme.coverage.test_mcp_tool_coverage import (
            _assert_read_tool_has_payload,
        )

        _assert_read_tool_has_payload("read_list_models", {"status": "ok", "models": []})
        _assert_read_tool_has_payload("write_create_page", {"status": "ok"})

        with pytest.raises(AssertionError):
            _assert_read_tool_has_payload("read_list_models", {"status": "ok", "agent_id": "agent"})
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)
