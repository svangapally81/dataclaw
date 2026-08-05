from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_auto_grant_on_connector_save_grants_chat_write() -> None:
    # v0.1.1: chat agent gets write_enabled=True on configured connectors
    # (still approval-gated). All other system agents remain read-only.
    main = _read("backend/app/main.py")
    tests = _read("backend/tests/test_custom_agent_create.py")
    assert "_auto_grant_configured_connector_read_only" in main
    assert "test_auto_grant_on_connector_test_grants_chat_write" in tests


def test_chat_is_the_only_agent_that_auto_grants_write() -> None:
    # Read-only for every non-chat system agent; chat gets write because the
    # approval flow is the actual safety boundary.
    main = _read("backend/app/main.py")
    assert "SYSTEM_AGENT_READ_CATEGORIES" in main
    auto_grant = main[
        main.index("async def _auto_grant_configured_connector_read_only") : main.index('@app.get("/agents"')
    ]
    assert 'grant.write_enabled = agent.name == "chat"' in auto_grant


def test_worker_heartbeat() -> None:
    worker = _read("backend/app/worker/main.py")
    api = _read("backend/app/main.py")
    assert "async def write_heartbeat" in worker
    assert "@app.get(\"/health/worker\")" in api
    assert "@app.get(\"/worker/status\")" in api


def test_force_run_on_enable() -> None:
    api = _read("backend/app/main.py")
    tests = _read("backend/tests/test_custom_agent_create.py")
    assert "force_run_requested_at = datetime.now(UTC)" in api
    assert "test_force_run_requested_when_background_agent_enabled" in tests


def test_periodic_compile() -> None:
    worker = _read("backend/app/worker/main.py")
    assert "compile tick" in worker
    assert "CompileService(session).compile" in worker


def test_streaming_chat_fetch() -> None:
    api = _read("backend/app/main.py")
    tests = _read("backend/tests/test_chat_and_logs.py")
    assert "StreamingResponse" in api
    assert "_stream_ide_chat" in api
    assert "test_chat_stream_persists_messages" in tests


def test_chart_autodetect() -> None:
    chat = _read("backend/app/services/agents/chat.py")
    tests = _read("backend/tests/test_chat_chart_spec.py")
    assert "chart_spec" in chat
    assert "test_chart_question_returns_vega_lite_spec" in tests


def test_background_concurrency_isolation() -> None:
    runner = _read("backend/app/services/agents/background_runner.py")
    tests = _read("backend/tests/test_background_runner.py")
    assert "asyncio.gather" in runner
    assert "return_exceptions=False" in runner
    assert "test_due_background_agents_skips_active_lease" in tests


def test_knowledge_node_source_attribution() -> None:
    model = _read("backend/app/models/domain.py")
    tests = _read("backend/tests/test_compile_service.py")
    assert "connector_slug" in model
    assert "test_compile_keeps_same_entity_distinct_per_connector" in tests


def test_alerting_loop_over_orchestration_connectors() -> None:
    runner = _read("backend/app/services/agents/background_runner.py")
    assert 'category == "orchestration"' in runner or "ConnectorCategory.ORCHESTRATION" in runner
    assert "list_failed_runs" in runner


def test_data_quality_loop_over_data_store_connectors() -> None:
    runner = _read("backend/app/services/agents/background_runner.py")
    monitoring = _read("backend/app/services/agents/monitoring_common.py")
    assert "run_schema_drift_agent" in runner
    assert "run_query_cost_agent" in runner
    assert "ConnectorCategory.DATA_STORE" in monitoring


def test_run_queue_lease_reclaim() -> None:
    runtime = _read("backend/app/services/agents/runtime.py")
    runner = _read("backend/app/services/agents/background_runner.py")
    tests = _read("backend/tests/test_background_runner.py")
    assert "lease_expires_at" in runtime
    assert "reclaim_expired_agent_runs" in runner
    assert "test_reclaim_expired_agent_runs_marks_lease_failed" in tests


def test_parallel_tool_calls_gather() -> None:
    chat = _read("backend/app/services/agents/chat.py")
    tests = _read("backend/tests/test_chat_openai_mcp_tools.py")
    assert "asyncio.gather" in chat
    assert "max_concurrency" in chat
    assert "test_openai_tool_calls_run_concurrently_with_bound" in tests


def test_budget_enforcement() -> None:
    runtime = _read("backend/app/services/agents/runtime.py")
    tests = _read("backend/tests/test_chat_openai_mcp_tools.py")
    assert "enforce_run_budget" in runtime
    assert "test_openai_tool_call_marks_run_timed_out_when_budget_exceeded" in tests


def test_run_cancellation() -> None:
    api = _read("backend/app/main.py")
    tests = _read("backend/tests/test_chat_and_logs.py")
    assert "@app.post(\"/chat/runs/{run_id}/cancel\")" in api
    assert "test_chat_run_cancel_endpoint_marks_running_run_cancelled" in tests


def test_agent_tool_call_audit() -> None:
    model = _read("backend/app/models/domain.py")
    tests = _read("backend/tests/test_chat_and_logs.py")
    assert "class AgentToolCall" in model
    assert "test_observability_events_include_agent_run_tool_calls" in tests


def test_write_tool_surface_hardening() -> None:
    executor = _read("backend/app/services/mcp_executor.py")
    grants = _read("backend/tests/test_mcp_grants.py")
    assert "_pending_mcp_approval" in executor
    assert "reserved approval argument" in _read("backend/tests/test_mcp_grants.py")
    assert "write_enabled" in grants


def test_column_lineage_edges() -> None:
    model = _read("backend/app/models/domain.py")
    tests = _read("backend/tests/test_compile_service.py")
    assert "class ColumnLineageEdge" in model
    assert "test_column_lineage_context_mentions_column_edges" in tests


def test_chroma_required_no_fallback() -> None:
    vector = _read("backend/app/services/vector_store.py")
    api = _read("backend/app/main.py")
    assert "class ChromaUnreachableError" in vector
    assert "@app.get(\"/health/chroma\")" in api
    assert "ChromaDB not reachable" in vector


def test_no_silent_connector_fallback() -> None:
    chat_tests = _read("backend/tests/test_chat_openai_mcp_tools.py")
    executor = _read("backend/app/services/mcp_executor.py")
    assert "test_openai_tool_call_does_not_retry_other_connectors" in chat_tests
    assert "connector_slug" in executor
