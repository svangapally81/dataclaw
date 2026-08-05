from __future__ import annotations

import sys
from pathlib import Path

import yaml

ACME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ACME_ROOT.parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.connectors.catalog import CATALOG_BY_SLUG  # noqa: E402
from app.services.mcp_catalog import tools_for_slug  # noqa: E402

TARGET = Path(__file__).resolve().parent / "fixtures.yml"

SQLITE_ARGS = {
    "read_list_tables": {},
    "read_get_schema": {"table": "customers"},
    "read_query_select": {"sql": "select customer_id, segment from customers order by customer_id", "limit": 5},
    "read_get_row_count": {"table": "customers"},
    "read_sample_rows": {"table": "orders", "limit": 2},
    "read_search_columns": {"pattern": "customer"},
    "read_get_column_stats": {"table": "customers"},
    "read_get_table_freshness": {"table": "orders"},
    "read_get_storage_size": {"table": "orders"},
    "read_explain_query": {"sql": "select * from orders where net_revenue > 1000", "limit": 5},
    "write_execute_sql": {"sql": "drop table if exists acme_coverage_disposable"},
    "write_create_table": {
        "table": "acme_coverage_disposable",
        "columns": [{"name": "id", "type": "integer"}, {"name": "note", "type": "text"}],
    },
    "write_create_view": {
        "view": "acme_coverage_orders_view",
        "select_sql": "select order_id, net_revenue from orders limit 5",
    },
    "write_insert_rows": {
        "table": "test_summary",
        "rows": [{"id": 9001, "note": "acme coverage insert"}],
    },
    "write_update_rows": {
        "table": "test_summary",
        "set": {"note": "acme coverage update"},
        "where": "id = 1",
    },
    "write_delete_rows": {"table": "test_summary", "where": "id = 9001"},
    "write_create_index": {
        "table": "orders",
        "columns": ["customer_id"],
        "index_name": "idx_acme_coverage_orders_customer",
    },
}


def _args_for(slug: str, tool_name: str) -> dict:
    if slug == "sqlite" and tool_name in SQLITE_ARGS:
        return SQLITE_ARGS[tool_name]
    if slug == "confluence":
        if tool_name == "read_get_space":
            return {"space_key": "$ACME_CONFLUENCE_SPACE_KEY"}
        if tool_name in {
            "read_get_page",
            "read_get_page_children",
            "read_get_page_history",
            "read_get_comments",
            "read_get_labels",
            "write_append_to_page",
            "write_update_page",
            "write_add_label",
            "write_create_comment",
            "write_create_attachment",
            "write_move_page",
            "write_delete_page",
        }:
            return {
                "page_id": "$ACME_CONFLUENCE_PIPELINE_PAGE_ID",
                "parent_id": "$ACME_CONFLUENCE_ARCHITECTURE_PAGE_ID",
                "title": "coverage-test-$TIMESTAMP",
                "body": "Acme coverage test",
                "content": "Acme coverage test",
                "label": "dataclaw-acme-coverage",
                "filename": "dataclaw-acme-coverage.txt",
                "version": 2,
            }
        if tool_name == "write_create_page":
            return {
                "space_key": "$ACME_CONFLUENCE_SPACE_KEY",
                "title": "coverage-test-$TIMESTAMP",
                "body": "Acme coverage test",
            }
    if tool_name.startswith("read_list"):
        return {}
    if "search" in tool_name:
        return {"query": "churn"}
    if "schema" in tool_name:
        return {"schema": "core"}
    if "row_count" in tool_name:
        return {"table": "customers", "schema": "core"}
    if "query" in tool_name or tool_name in {"write_execute_sql", "read_explain_query"}:
        return {"sql": "select 1 as acme_smoke"}
    if "page" in tool_name:
        return {"page_id": "$ACME_PAGE_ID", "title": "coverage-test-$TIMESTAMP", "content": "Acme coverage test"}
    if slug == "fivetran":
        if "destination" in tool_name:
            return {"destination_id": "$ACME_FIVETRAN_DESTINATION_ID"}
        if "resync_table" in tool_name:
            return {"connector_id": "$ACME_FIVETRAN_CONNECTOR_ID", "schema": "postgres_to_bq", "table": "orders"}
        if "modify_connector_schema" in tool_name:
            return {"connector_id": "$ACME_FIVETRAN_CONNECTOR_ID", "config": {"schemas": {}}}
        if "connector" in tool_name or "metadata" in tool_name or "data_volume" in tool_name or "sync_history" in tool_name:
            return {"connector_id": "$ACME_FIVETRAN_CONNECTOR_ID"}
    if slug == "airbyte":
        if tool_name == "read_get_job_logs" or tool_name == "write_cancel_job":
            return {"job_id": "$ACME_AIRBYTE_JOB_ID"}
        if tool_name == "read_get_source":
            return {"source_id": "$ACME_AIRBYTE_SOURCE_ID"}
        if tool_name == "read_get_destination":
            return {"destination_id": "$ACME_AIRBYTE_DESTINATION_ID"}
        if tool_name == "write_create_connection":
            return {"source_id": "$ACME_AIRBYTE_SOURCE_ID", "destination_id": "$ACME_AIRBYTE_DESTINATION_ID"}
        if "connection" in tool_name or "sync" in tool_name:
            return {"connection_id": "$ACME_AIRBYTE_CONNECTION_ID"}
    if slug == "dagster":
        if tool_name in {"read_get_run", "read_get_run_logs", "read_get_event_logs", "read_get_run_steps", "write_terminate_run"}:
            return {"run_id": "$ACME_DAGSTER_RUN_ID"}
        if tool_name in {"read_get_asset_materializations", "read_list_partitions", "read_get_asset_checks", "write_materialize_asset"}:
            return {"asset_key": "customers", "job_name": "$ACME_DAGSTER_JOB_NAME"}
        if tool_name in {"read_get_sensor_state", "write_launch_sensor"}:
            return {"name": "$ACME_DAGSTER_SENSOR"}
        if tool_name in {"read_get_schedule_state", "write_start_schedule", "write_stop_schedule"}:
            return {"name": "$ACME_DAGSTER_SCHEDULE"}
        if tool_name == "write_backfill_partitions":
            return {"asset_key": "customers", "partitions": ["$ACME_DAGSTER_PARTITION"]}
        if tool_name == "write_trigger_job":
            return {"job_name": "$ACME_DAGSTER_JOB_NAME"}
    if slug == "databricks":
        if tool_name in {"read_get_schema", "read_get_row_count", "read_get_table_freshness"}:
            return {"schema": "silver", "table": "events"}
        if tool_name == "read_query_select":
            return {"sql": "$ACME_DATABRICKS_EVENTS_SELECT_SQL"}
        if tool_name == "read_get_unity_asset":
            return {"full_name": "$ACME_DATABRICKS_TABLE"}
        if tool_name == "read_get_lineage":
            return {"asset": "$ACME_DATABRICKS_TABLE"}
        if tool_name in {"read_get_run_logs"}:
            return {"run_id": "$ACME_DATABRICKS_RUN_ID"}
        if tool_name == "read_get_notebook" or tool_name == "write_run_notebook":
            return {"path": "$ACME_DATABRICKS_NOTEBOOK_PATH"}
        if tool_name in {"write_start_cluster", "write_stop_cluster"}:
            return {"cluster_id": "$ACME_DATABRICKS_CLUSTER_ID"}
        if tool_name == "write_trigger_job":
            return {"job_id": "$ACME_DATABRICKS_JOB_ID"}
        if tool_name == "write_update_unity_grants":
            return {
                "full_name": "$ACME_DATABRICKS_TABLE",
                "securable_type": "table",
                "changes": [{"principal": "data-team", "add": ["SELECT"]}],
            }
        if tool_name == "write_create_view":
            return {
                "view": "$ACME_DATABRICKS_EVENTS_VIEW",
                "select_sql": "$ACME_DATABRICKS_EVENTS_VIEW_SELECT_SQL",
            }
        if tool_name == "write_create_table":
            return {"table": "acme_coverage_events", "schema": "silver", "columns": [{"name": "id", "type": "integer"}]}
        if tool_name == "write_execute_sql":
            return {"sql": "create or replace table silver.acme_coverage_smoke (id int)"}
        if tool_name == "read_get_query_history":
            return {"limit": 5}
    if slug == "redshift":
        if tool_name in {
            "read_get_schema",
            "read_get_row_count",
            "read_sample_rows",
            "read_get_column_stats",
            "read_get_table_freshness",
            "read_get_storage_size",
            "read_list_grants",
        }:
            return {"schema": "acme", "table": "audit_log"}
        if tool_name in {"read_query_select", "read_explain_query"}:
            return {"sql": "select event_id, action, actor from acme.audit_log order by event_id limit 5"}
        if tool_name == "read_search_columns":
            return {"pattern": "event"}
        if tool_name == "read_get_disk_usage":
            return {"schema": "acme"}
        if tool_name == "read_get_query_history":
            return {"limit": 5}
        if tool_name == "write_create_table":
            return {"schema": "acme", "table": "acme_coverage_write_probe", "columns": [{"name": "id", "type": "integer"}]}
        if tool_name == "write_create_view":
            return {
                "schema": "acme",
                "view": "acme_coverage_audit_view",
                "select_sql": "select event_id, action from acme.audit_log limit 10",
            }
        if tool_name == "write_execute_sql":
            return {"sql": "create table if not exists acme.acme_coverage_smoke (id integer)"}
        if tool_name == "write_insert_rows":
            return {"schema": "acme", "table": "acme_coverage_write_probe", "rows": [{"id": 1}]}
        if tool_name == "write_update_rows":
            return {"schema": "acme", "table": "acme_coverage_write_probe", "set": {"id": 2}, "where": "id = 1"}
        if tool_name == "write_delete_rows":
            return {"schema": "acme", "table": "acme_coverage_write_probe", "where": "id = 2"}
        if tool_name == "write_create_index":
            return {
                "schema": "acme",
                "table": "audit_log",
                "columns": ["event_id"],
                "index_name": "idx_acme_audit_log_event_id",
            }
        if tool_name == "write_grant_permission":
            return {"schema": "acme", "table": "audit_log", "role": "$REDSHIFT_USER", "scope": "SELECT"}
        if tool_name in {"write_pause_cluster", "write_resume_cluster"}:
            return {"cluster_identifier": "$REDSHIFT_CLUSTER_IDENTIFIER"}
    if slug == "snowflake":
        if tool_name in {
            "read_get_schema",
            "read_get_row_count",
            "read_sample_rows",
            "read_get_column_stats",
            "read_get_storage_size",
            "read_list_grants",
        }:
            return {"schema": "MARTS", "table": "CHURN_EVENTS"}
        if tool_name == "read_get_table_freshness":
            return {"schema": "MARTS", "table": "REVENUE_DAILY"}
        if tool_name in {"read_query_select", "read_explain_query"}:
            return {
                "sql": "select customer_id, event_type, event_at from MARTS.CHURN_EVENTS order by event_at desc limit 5"
            }
        if tool_name in {"read_get_query_history", "read_query_history"}:
            return {"limit": 5}
        if tool_name == "read_get_credit_usage":
            return {}
        if tool_name == "read_search_columns":
            return {"schema": "MARTS", "pattern": "event"}
        if tool_name in {"read_list_pipes", "read_list_streams", "read_list_tasks", "read_list_tables"}:
            return {"schema": "MARTS"}
        if tool_name in {"write_resume_warehouse", "write_suspend_warehouse"}:
            return {"warehouse": "$SNOWFLAKE_WAREHOUSE"}
        if tool_name == "write_create_table":
            return {"schema": "MARTS", "table": "ACME_COVERAGE_WRITE_PROBE", "columns": [{"name": "ID", "type": "INTEGER"}]}
        if tool_name == "write_create_view":
            return {
                "schema": "MARTS",
                "view": "ACME_COVERAGE_CHURN_VIEW",
                "select_sql": "select customer_id, event_type from MARTS.CHURN_EVENTS limit 10",
            }
        if tool_name == "write_execute_sql":
            return {"sql": "create table if not exists MARTS.ACME_COVERAGE_SMOKE (ID INTEGER)"}
        if tool_name == "write_insert_rows":
            return {"schema": "MARTS", "table": "ACME_COVERAGE_WRITE_PROBE", "rows": [{"ID": 1}]}
        if tool_name == "write_update_rows":
            return {"schema": "MARTS", "table": "ACME_COVERAGE_WRITE_PROBE", "set": {"ID": 2}, "where": "ID = 1"}
        if tool_name == "write_delete_rows":
            return {"schema": "MARTS", "table": "ACME_COVERAGE_WRITE_PROBE", "where": "ID = 2"}
        if tool_name == "write_create_index":
            return {
                "schema": "MARTS",
                "table": "CHURN_EVENTS",
                "columns": ["CUSTOMER_ID"],
                "index_name": "IDX_ACME_CHURN_CUSTOMER",
            }
        if tool_name == "write_create_pipe":
            return {
                "schema": "MARTS",
                "name": "ACME_COVERAGE_PIPE",
                "table": "CHURN_EVENTS",
                "stage": "ACME_COVERAGE_STAGE",
                "file_format": "CSV",
            }
        if tool_name == "write_create_task":
            return {
                "schema": "MARTS",
                "name": "ACME_COVERAGE_TASK",
                "warehouse": "$SNOWFLAKE_WAREHOUSE",
                "schedule": "USING CRON 0 * * * * UTC",
                "sql": "select count(*) from MARTS.REVENUE_DAILY",
            }
    if slug == "github":
        if tool_name == "read_get_file":
            return {"repo": "$GITHUB_TEST_REPO", "path": "models/staging/stg_customers.sql"}
        if tool_name == "read_get_commit":
            return {"repo": "$GITHUB_TEST_REPO", "sha": "$ACME_GITHUB_HEAD_SHA"}
        if tool_name in {"read_get_issue"}:
            return {"repo": "$GITHUB_TEST_REPO", "number": "$ACME_GITHUB_ISSUE_NUMBER"}
        if tool_name in {"read_get_pr", "read_get_pr_diff"}:
            return {"repo": "$GITHUB_TEST_REPO", "number": "$ACME_GITHUB_PR_NUMBER"}
        if tool_name == "read_get_workflow_run_logs":
            return {"repo": "$ACME_GITHUB_WORKFLOW_RUN_REPO", "run_id": "$ACME_GITHUB_WORKFLOW_RUN_ID"}
    if "repo" in tool_name or "pr" in tool_name or "issue" in tool_name or "branch" in tool_name:
        return {"repo": "$GITHUB_TEST_REPO", "path": "models/staging/stg_customers.sql", "title": "coverage-test-$TIMESTAMP"}
    if "dag" in tool_name or "task" in tool_name or "xcom" in tool_name:
        return {"dag_id": "acme_etl_daily", "run_id": "manual__acme_coverage", "task_id": "extract"}
    if "flow" in tool_name or "deployment" in tool_name:
        return {"flow_name": "acme_revenue_recalc", "deployment_name": "acme_revenue_recalc/default"}
    if "asset" in tool_name or "materialization" in tool_name:
        return {"asset_key": "customers", "job_name": "acme_assets"}
    if "connection" in tool_name or "job" in tool_name or "sync" in tool_name:
        return {"connection_id": "$ACME_AIRBYTE_CONNECTION_ID", "connector_id": "$ACME_FIVETRAN_CONNECTOR_ID"}
    if "model" in tool_name or "run" in tool_name or "test" in tool_name:
        return {"model": "dim_customers", "run_id": "$ACME_DBT_RUN_ID", "project_path": "$ACME_DBT_PROJECT_PATH"}
    if "warehouse" in tool_name:
        return {"warehouse": "$SNOWFLAKE_WAREHOUSE"}
    if "dataset" in tool_name:
        return {"dataset": "acme_analytics"}
    if tool_name.startswith("write_create_table"):
        return {"table": "coverage_test_$TIMESTAMP", "schema": "core", "columns": [{"name": "id", "type": "integer"}]}
    if tool_name.startswith("write_insert"):
        return {"table": "coverage_test_$TIMESTAMP", "schema": "core", "rows": [{"id": 1}]}
    return {"name": "coverage-test-$TIMESTAMP"}


def _expect_for(tool_name: str) -> dict:
    if tool_name.startswith("write_"):
        statuses = [
            "ok",
            "pending_approval",
            "created",
            "triggered",
            "updated",
            "cancelled",
            "executed",
        ]
        if "delete" in tool_name:
            statuses.append("deleted")
        if "pause" in tool_name:
            statuses.append("paused")
        if "resume" in tool_name:
            statuses.append("resumed")
        if tool_name == "write_terminate_run":
            statuses.append("terminated")
        return {"status": statuses}
    if tool_name.startswith("read_"):
        return {"status": ["ok"]}
    return {"status": ["ok"]}


def build_payload() -> dict:
    payload: dict[str, dict] = {}
    for slug in sorted(CATALOG_BY_SLUG):
        read_tools, write_tools = tools_for_slug(slug)
        payload[slug] = {}
        for tool_name in [*read_tools, *write_tools]:
            payload[slug][tool_name] = {
                "args": _args_for(slug, tool_name),
                "expect_shape": _expect_for(tool_name),
            }
    return payload


def main() -> int:
    TARGET.write_text(yaml.safe_dump(build_payload(), sort_keys=True), encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
