from __future__ import annotations

from app.cli import cmd_verify_mcp_catalog
from app.services.mcp_verify import verify_mcp_catalog


class Args:
    pass


def test_verify_mcp_catalog_passes_for_current_catalog() -> None:
    assert verify_mcp_catalog() == []


def test_orchestration_catalog_exposes_log_fetching_tools() -> None:
    from app.services.mcp_catalog import tools_for_slug

    expected = {
        "airflow": "read_get_task_logs",
        "airbyte": "read_get_job_logs",
        "prefect": "read_get_run_logs",
        "dagster": "read_get_run_logs",
        "fivetran": "read_get_connector_logs",
        "dbt": "read_get_run_logs",
    }
    for slug, tool_name in expected.items():
        read_tools, _ = tools_for_slug(slug)
        assert tool_name in read_tools


def test_airflow_catalog_exposes_operational_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("airflow")
    assert {
        "read_list_task_instances",
        "read_list_dag_runs",
        "read_get_xcom",
        "read_list_pools",
        "read_get_pool",
        "read_list_variables",
        "read_get_variable",
        "read_get_dag_dependencies",
        "read_get_import_errors",
    }.issubset(read_tools)
    assert {
        "write_unpause_dag",
        "write_clear_task_instance",
        "write_mark_task_success",
        "write_mark_task_failed",
        "write_set_variable",
        "write_set_pool",
        "write_delete_dag",
    }.issubset(write_tools)


def test_prefect_catalog_exposes_operational_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("prefect")
    assert {
        "read_list_flow_runs",
        "read_list_deployments",
        "read_get_deployment",
        "read_get_task_run",
        "read_list_work_pools",
        "read_list_artifacts",
    }.issubset(read_tools)
    assert {
        "write_pause_deployment",
        "write_resume_deployment",
        "write_cancel_flow_run",
        "write_delete_deployment",
    }.issubset(write_tools)


def test_dagster_catalog_exposes_operational_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("dagster")
    assert {
        "read_get_event_logs",
        "read_get_asset_materializations",
        "read_list_jobs",
        "read_list_partitions",
        "read_get_run_steps",
        "read_get_asset_checks",
        "read_get_sensor_state",
        "read_list_sensors",
        "read_list_schedules",
        "read_get_schedule_state",
    }.issubset(read_tools)
    assert {
        "write_terminate_run",
        "write_launch_sensor",
        "write_start_schedule",
        "write_stop_schedule",
    }.issubset(write_tools)


def test_airbyte_catalog_exposes_operational_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("airbyte")
    assert {
        "read_list_jobs",
        "read_get_connection_state",
        "read_list_sources",
        "read_get_source",
        "read_list_destinations",
        "read_get_destination",
        "read_get_workspace",
        "read_get_connection_schema",
    }.issubset(read_tools)
    assert {
        "write_reset_connection",
        "write_cancel_job",
        "write_disable_connection",
        "write_enable_connection",
    }.issubset(write_tools)


def test_fivetran_catalog_exposes_operational_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("fivetran")
    assert {
        "read_get_connector_status",
        "read_get_connector_schema",
        "read_list_destinations",
        "read_get_destination",
        "read_get_sync_history",
    }.issubset(read_tools)
    assert {"write_resume_connector", "write_delete_connector"}.issubset(write_tools)


def test_dbt_catalog_exposes_operational_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("dbt")
    assert {
        "read_list_runs",
        "read_get_run_artifacts",
        "read_get_manifest",
        "read_list_tests",
        "read_get_test_results",
        "read_get_source_freshness",
        "read_get_model_source",
        "read_list_exposures",
        "read_get_model_docs",
    }.issubset(read_tools)
    assert {"write_cancel_run", "write_trigger_snapshot", "write_trigger_seed"}.issubset(write_tools)


def test_notion_catalog_exposes_knowledge_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("notion")
    assert {
        "read_get_database",
        "read_query_database",
        "read_get_block_children",
        "read_get_comments",
        "read_list_users",
    }.issubset(read_tools)
    assert {
        "write_update_page_properties",
        "write_archive_page",
        "write_create_comment",
        "write_create_database",
        "write_update_block",
    }.issubset(write_tools)


def test_github_catalog_exposes_knowledge_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("github")
    assert {
        "read_list_issues",
        "read_get_issue",
        "read_get_pr",
        "read_get_pr_diff",
        "read_list_branches",
        "read_search_code",
        "read_get_commit",
        "read_list_workflows",
        "read_get_workflow_run_logs",
        "read_get_repo_metadata",
        "read_list_releases",
    }.issubset(read_tools)
    assert {
        "write_create_issue",
        "write_comment_on_pr",
        "write_comment_on_issue",
        "write_merge_pr",
        "write_create_branch",
        "write_delete_branch",
        "write_close_pr",
        "write_close_issue",
        "write_request_review",
    }.issubset(write_tools)


def test_google_docs_catalog_exposes_knowledge_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("google_docs")
    assert {
        "read_search_docs",
        "read_get_doc_comments",
        "read_get_doc_revisions",
        "read_list_folder_contents",
        "read_list_shared_with_me",
        "read_get_doc_metadata",
    }.issubset(read_tools)
    assert {
        "write_append_to_doc",
        "write_replace_text",
        "write_create_comment",
        "write_share_doc",
        "write_move_doc",
        "write_rename_doc",
    }.issubset(write_tools)


def test_quip_catalog_exposes_knowledge_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("quip")
    assert {
        "read_get_thread_history",
        "read_list_folders",
        "read_get_folder",
        "read_get_messages",
    }.issubset(read_tools)
    assert {
        "write_edit_thread",
        "write_send_message",
        "write_share_thread",
        "write_create_folder",
    }.issubset(write_tools)


def test_confluence_catalog_exposes_knowledge_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("confluence")
    assert {
        "read_get_page_children",
        "read_get_space",
        "read_get_page_history",
        "read_search_attachments",
        "read_get_comments",
        "read_list_spaces",
        "read_get_labels",
    }.issubset(read_tools)
    assert {
        "write_update_page",
        "write_add_label",
        "write_create_comment",
        "write_create_attachment",
        "write_move_page",
        "write_delete_page",
    }.issubset(write_tools)


def test_sql_datastore_catalog_exposes_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    sqlite_read, sqlite_write = tools_for_slug("sqlite")
    assert {"read_explain_query"}.issubset(sqlite_read)
    assert {"write_update_rows", "write_delete_rows", "write_create_index"}.issubset(sqlite_write)

    for slug in ("postgres", "mysql", "redshift", "sql_server"):
        read_tools, write_tools = tools_for_slug(slug)
        assert {
            "read_explain_query",
            "read_list_users",
            "read_list_grants",
            "read_get_query_history",
        }.issubset(read_tools)
        assert {
            "write_update_rows",
            "write_delete_rows",
            "write_grant_permission",
            "write_create_index",
        }.issubset(write_tools)
    trino_read, trino_write = tools_for_slug("trino")
    assert {
        "read_sample_rows",
        "read_search_columns",
        "read_get_column_stats",
        "read_explain_query",
        "read_get_query_history",
    }.issubset(trino_read)
    assert {"write_execute_sql", "write_create_table", "write_create_view", "write_insert_rows"}.issubset(trino_write)
    assert "write_create_index" not in trino_write
    redshift_read, redshift_write = tools_for_slug("redshift")
    assert {"read_get_workload_management", "read_list_clusters", "read_get_disk_usage"}.issubset(redshift_read)
    assert {"write_pause_cluster", "write_resume_cluster"}.issubset(redshift_write)

    snowflake_read, snowflake_write = tools_for_slug("snowflake")
    assert {
        "read_explain_query",
        "read_list_users",
        "read_list_grants",
        "read_get_query_history",
    }.issubset(snowflake_read)
    assert {"write_update_rows", "write_delete_rows", "write_create_index"}.issubset(snowflake_write)
    assert "write_grant_permission" not in snowflake_write
    assert {
        "read_list_warehouses",
        "read_query_history",
        "read_get_credit_usage",
        "read_list_pipes",
        "read_list_streams",
        "read_list_tasks",
    }.issubset(snowflake_read)
    assert {
        "write_resume_warehouse",
        "write_suspend_warehouse",
        "write_create_pipe",
        "write_create_task",
    }.issubset(snowflake_write)


def test_bigquery_catalog_exposes_data_store_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("bigquery")
    assert {
        "read_list_datasets",
        "read_get_query_history",
        "read_explain_query",
        "read_get_slot_usage",
    }.issubset(read_tools)
    assert {
        "write_load_from_gcs",
        "write_export_to_gcs",
        "write_create_view",
        "write_create_dataset",
    }.issubset(write_tools)


def test_databricks_catalog_exposes_data_store_matrix_slice() -> None:
    from app.services.mcp_catalog import tools_for_slug

    read_tools, write_tools = tools_for_slug("databricks")
    assert {
        "read_list_clusters",
        "read_list_warehouses",
        "read_get_notebook",
        "read_get_run_logs",
        "read_get_lineage",
        "read_get_query_history",
    }.issubset(read_tools)
    assert {
        "write_run_notebook",
        "write_start_cluster",
        "write_stop_cluster",
        "write_create_view",
        "write_update_unity_grants",
    }.issubset(write_tools)


def test_verify_mcp_catalog_cli_returns_success(capsys) -> None:
    assert cmd_verify_mcp_catalog(Args()) == 0
    assert "MCP catalog verification passed" in capsys.readouterr().out
