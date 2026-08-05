from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_acme_coverage_connector_env_selects_exact_slug() -> None:
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
        import os

        import pytest

        from tests.integration.acme.coverage.conftest import coverage_connector_slugs

        os.environ.pop("ACME_COVERAGE_CONNECTOR", None)
        assert "postgres" in coverage_connector_slugs()
        assert "openai" not in coverage_connector_slugs()

        os.environ["ACME_COVERAGE_CONNECTOR"] = "postgres"
        assert coverage_connector_slugs() == ["postgres"]

        os.environ["ACME_COVERAGE_CONNECTOR"] = "openai"
        with pytest.raises(pytest.UsageError):
            coverage_connector_slugs()

        os.environ["ACME_COVERAGE_CONNECTOR"] = "not-a-connector"
        with pytest.raises(pytest.UsageError):
            coverage_connector_slugs()
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)
