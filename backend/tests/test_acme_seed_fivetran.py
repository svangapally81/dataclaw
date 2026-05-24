from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_acme_fivetran_seeder_extracts_sync_history() -> None:
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
        from tests.integration.acme.seed.saas.seed_fivetran import _choose_connector, _connector_status_events

        events = _connector_status_events(
            {
                "id": "acme_connector",
                "succeeded_at": "2026-05-19T00:00:00Z",
                "status": {
                    "sync_state": "scheduled",
                    "tasks": ["validate source"],
                    "warnings": ["schema drift warning"],
                },
            }
        )

        assert {"type": "succeeded_at", "detail": "2026-05-19T00:00:00Z"} in events
        assert {"type": "sync_state", "detail": "scheduled"} in events
        assert {"type": "task", "detail": "validate source"} in events
        assert {"type": "warning", "detail": "schema drift warning"} in events

        fallback = _choose_connector(
            [
                {"id": "unused", "schema": "other"},
                {"id": "active", "schema": "warehouse_sync", "succeeded_at": "2026-05-19T00:00:00Z"},
            ]
        )
        assert fallback["id"] == "active"

        preferred = _choose_connector(
            [
                {"id": "active", "schema": "warehouse_sync", "succeeded_at": "2026-05-19T00:00:00Z"},
                {"id": "story", "schema": "postgres_to_bq"},
            ]
        )
        assert preferred["id"] == "story"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)
