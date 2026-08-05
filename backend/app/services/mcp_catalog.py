from __future__ import annotations

from app.services.connectors.catalog import CATALOG_BY_SLUG, ConnectorCategory

DATA_READ = ["read_list_tables", "read_get_schema", "read_query_select", "read_get_row_count"]
SQL_DISCOVERY_READ = [
    "read_sample_rows",
    "read_search_columns",
    "read_get_column_stats",
    "read_get_table_freshness",
    "read_get_storage_size",
]
SQL_ADMIN_READ = ["read_explain_query", "read_list_users", "read_list_grants", "read_get_query_history"]
SQLITE_EXTRA_READ = ["read_explain_query"]
DATA_WRITE = ["write_execute_sql", "write_create_table", "write_create_view", "write_insert_rows"]
SQL_MUTATION_WRITE = ["write_update_rows", "write_delete_rows", "write_create_index"]
SQL_ADMIN_WRITE = ["write_grant_permission"]
ORCH_READ = {
    "airflow": [
        "read_list_dags",
        "read_get_run",
        "read_get_dag_source",
        "read_get_task_logs",
        "read_list_task_instances",
        "read_list_dag_runs",
        "read_get_xcom",
        "read_list_pools",
        "read_get_pool",
        "read_list_variables",
        "read_get_variable",
        "read_get_dag_dependencies",
        "read_get_import_errors",
    ],
    "prefect": [
        "read_list_flows",
        "read_get_run",
        "read_get_run_logs",
        "read_get_task_logs",
        "read_list_flow_runs",
        "read_list_deployments",
        "read_get_deployment",
        "read_get_task_run",
        "read_list_work_pools",
        "read_get_block",
        "read_get_concurrency_limit",
        "read_list_artifacts",
    ],
    "dagster": [
        "read_list_assets",
        "read_get_run",
        "read_get_run_logs",
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
    ],
    "airbyte": [
        "read_list_connections",
        "read_get_job_logs",
        "read_list_jobs",
        "read_get_connection_state",
        "read_list_sources",
        "read_get_source",
        "read_list_destinations",
        "read_get_destination",
        "read_get_workspace",
        "read_get_connection_schema",
    ],
    "fivetran": [
        "read_list_connectors",
        "read_get_connector_logs",
        "read_get_connector_status",
        "read_get_connector_schema",
        "read_list_destinations",
        "read_get_destination",
        "read_get_metadata",
        "read_get_data_volume",
        "read_get_sync_history",
    ],
    "dbt": [
        "read_list_models",
        "read_get_lineage",
        "read_get_run_logs",
        "read_list_runs",
        "read_get_run_artifacts",
        "read_get_manifest",
        "read_list_tests",
        "read_get_test_results",
        "read_get_source_freshness",
        "read_get_model_source",
        "read_list_exposures",
        "read_get_model_docs",
    ],
}
ORCH_WRITE = {
    "airflow": [
        "write_trigger_dag",
        "write_create_dag",
        "write_pause_dag",
        "write_unpause_dag",
        "write_clear_task_instance",
        "write_mark_task_success",
        "write_mark_task_failed",
        "write_set_variable",
        "write_set_pool",
        "write_delete_dag",
    ],
    "prefect": [
        "write_trigger_flow_run",
        "write_create_deployment",
        "write_pause_deployment",
        "write_resume_deployment",
        "write_cancel_flow_run",
        "write_set_block",
        "write_set_concurrency_limit",
        "write_delete_deployment",
    ],
    "dagster": [
        "write_materialize_asset",
        "write_trigger_job",
        "write_backfill_partitions",
        "write_terminate_run",
        "write_launch_sensor",
        "write_start_schedule",
        "write_stop_schedule",
    ],
    "airbyte": [
        "write_trigger_sync",
        "write_reset_connection",
        "write_cancel_job",
        "write_create_connection",
        "write_update_connection",
        "write_disable_connection",
        "write_enable_connection",
    ],
    "fivetran": [
        "write_trigger_sync",
        "write_pause_connector",
        "write_resume_connector",
        "write_resync_table",
        "write_modify_connector_schema",
        "write_delete_connector",
    ],
    "dbt": [
        "write_trigger_run",
        "write_trigger_test",
        "write_cancel_run",
        "write_create_model",
        "write_update_model",
        "write_trigger_snapshot",
        "write_trigger_seed",
    ],
}
KB_READ = {
    "notion": [
        "read_search_pages",
        "read_get_page",
        "read_get_database",
        "read_query_database",
        "read_get_block_children",
        "read_get_comments",
        "read_list_users",
    ],
    "github": [
        "read_list_repos",
        "read_get_file",
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
    ],
    "google_docs": [
        "read_list_docs",
        "read_get_doc",
        "read_search_docs",
        "read_get_doc_comments",
        "read_get_doc_revisions",
        "read_list_folder_contents",
        "read_list_shared_with_me",
        "read_get_doc_metadata",
    ],
    "quip": [
        "read_search",
        "read_get_thread",
        "read_get_thread_history",
        "read_list_folders",
        "read_get_folder",
        "read_get_messages",
    ],
    "confluence": [
        "read_search_pages",
        "read_get_page",
        "read_get_page_children",
        "read_get_space",
        "read_get_page_history",
        "read_search_attachments",
        "read_get_comments",
        "read_list_spaces",
        "read_get_labels",
    ],
}
KB_WRITE = {
    "notion": [
        "write_create_page",
        "write_append_to_page",
        "write_update_page_properties",
        "write_archive_page",
        "write_create_comment",
        "write_create_database",
        "write_update_block",
    ],
    "github": [
        "write_commit_file",
        "write_create_pr",
        "write_create_issue",
        "write_comment_on_pr",
        "write_comment_on_issue",
        "write_merge_pr",
        "write_create_branch",
        "write_delete_branch",
        "write_close_pr",
        "write_close_issue",
        "write_request_review",
    ],
    "google_docs": [
        "write_create_doc",
        "write_append_to_doc",
        "write_replace_text",
        "write_create_comment",
        "write_share_doc",
        "write_move_doc",
        "write_rename_doc",
    ],
    "quip": [
        "write_create_thread",
        "write_edit_thread",
        "write_send_message",
        "write_share_thread",
        "write_create_folder",
    ],
    "confluence": [
        "write_create_page",
        "write_append_to_page",
        "write_update_page",
        "write_add_label",
        "write_create_comment",
        "write_create_attachment",
        "write_move_page",
        "write_delete_page",
    ],
}


def tools_for_slug(slug: str) -> tuple[list[str], list[str]]:
    definition = CATALOG_BY_SLUG[slug]
    if definition.category == ConnectorCategory.DATA_STORE:
        read = [*DATA_READ]
        write = [*DATA_WRITE]
        if slug in {"sqlite", "postgres", "mysql", "redshift", "sql_server", "snowflake", "trino"}:
            read.extend(SQL_DISCOVERY_READ)
        if slug == "sqlite":
            read.extend(SQLITE_EXTRA_READ)
            write.extend(SQL_MUTATION_WRITE)
        if slug in {"postgres", "mysql", "redshift", "sql_server", "snowflake"}:
            read.extend(SQL_ADMIN_READ)
            write.extend(SQL_MUTATION_WRITE)
        if slug in {"postgres", "mysql", "redshift", "sql_server"}:
            write.extend(SQL_ADMIN_WRITE)
        if slug == "trino":
            read.extend(SQL_ADMIN_READ)
        if slug == "redshift":
            read.extend(["read_get_workload_management", "read_list_clusters", "read_get_disk_usage"])
            write.extend(["write_pause_cluster", "write_resume_cluster"])
        if slug == "snowflake":
            read.extend(
                [
                    "read_list_warehouses",
                    "read_query_history",
                    "read_get_credit_usage",
                    "read_list_pipes",
                    "read_list_streams",
                    "read_list_tasks",
                ]
            )
            write.extend(["write_resume_warehouse", "write_suspend_warehouse", "write_create_pipe", "write_create_task"])
        if slug == "bigquery":
            read.extend(
                [
                    "read_list_jobs",
                    "read_list_datasets",
                    "read_get_query_history",
                    "read_search_columns",
                    "read_get_table_freshness",
                    "read_get_storage_size",
                    "read_explain_query",
                    "read_get_slot_usage",
                ]
            )
            write = [
                "write_execute_sql",
                "write_create_table",
                "write_run_query_save_to_table",
                "write_load_from_gcs",
                "write_export_to_gcs",
                "write_create_view",
                "write_create_dataset",
            ]
        if slug == "databricks":
            read.extend(
                [
                    "read_list_jobs",
                    "read_get_unity_asset",
                    "read_list_clusters",
                    "read_list_warehouses",
                    "read_get_notebook",
                    "read_get_run_logs",
                    "read_get_lineage",
                    "read_get_query_history",
                    "read_get_table_freshness",
                ]
            )
            write = [
                "write_execute_sql",
                "write_create_table",
                "write_trigger_job",
                "write_run_notebook",
                "write_start_cluster",
                "write_stop_cluster",
                "write_create_view",
                "write_update_unity_grants",
            ]
        return read, write
    if definition.category == ConnectorCategory.ORCHESTRATION:
        return ORCH_READ.get(slug, []), ORCH_WRITE.get(slug, [])
    if definition.category == ConnectorCategory.KNOWLEDGE:
        return KB_READ.get(slug, []), KB_WRITE.get(slug, [])
    if slug == "openai":
        return ["read_list_models"], []
    return [], []


def mcp_catalog() -> list[dict]:
    rows = []
    for slug, definition in CATALOG_BY_SLUG.items():
        read, write = tools_for_slug(slug)
        rows.append(
            {
                "slug": slug,
                "display_name": definition.display_name,
                "logo_key": definition.logo_key,
                "read_tools": [{"name": name, "scope": "read"} for name in read],
                "write_tools": [{"name": name, "scope": "write"} for name in write],
            }
        )
    return rows
