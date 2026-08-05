"""Sanity checks: monitoring agents are registered + import cleanly."""
from __future__ import annotations

import importlib


def test_monitoring_agents_registry_complete() -> None:
    common = importlib.import_module("app.services.agents.monitoring_common")
    expected = {"airflow_failure_agent", "dbt_failure_agent", "schema_drift_agent", "query_cost_agent"}
    assert set(common.MONITORING_AGENTS.keys()) == expected
    for agent in expected:
        meta = common.MONITORING_AGENTS[agent]
        assert meta.get("display_name")
        assert isinstance(meta.get("connectors"), list)


def test_each_agent_module_importable() -> None:
    for agent in ("airflow_failure_agent", "dbt_failure_agent", "schema_drift_agent", "query_cost_agent"):
        module = importlib.import_module(f"app.services.agents.{agent}")
        runner_attr = f"run_{agent}"
        assert hasattr(module, runner_attr), f"{agent} missing {runner_attr}"
        assert callable(getattr(module, runner_attr))


def test_worker_main_registers_monitoring_jobs() -> None:
    """Source-level grep avoids importing worker.main (which loads DEMO_DATABASE_URL drivers)."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "worker" / "main.py").read_text()
    assert "async def background_agents_job" in source
    assert 'id="background-agents"' in source
    assert "run_due_background_agents" in source
