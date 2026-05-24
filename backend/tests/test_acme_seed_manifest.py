from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_acme_seed_manifest_preserves_unselected_sections() -> None:
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
        import json
        import tempfile
        from pathlib import Path

        from tests.integration.acme.seed import seed_acme

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "acme_ids.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "company": "Acme Co",
                        "generated_at": "old",
                        "containers": {"postgres": {"tables": ["customers"]}},
                        "saas": {"notion": {"churn_page_id": "notion-page"}},
                    }
                )
            )
            seed_acme.ACME_IDS_PATH = manifest_path
            seed_acme.seed_containers = lambda: {"postgres": {"tables": ["orders"]}}
            seed_acme.seed_saas = lambda: {"notion": {"churn_page_id": "new-page"}}

            containers_only = seed_acme.build_manifest(include_containers=True, include_saas=False)
            assert containers_only["containers"] == {"postgres": {"tables": ["orders"]}}
            assert containers_only["saas"] == {"notion": {"churn_page_id": "notion-page"}}

            saas_only = seed_acme.build_manifest(include_containers=False, include_saas=True)
            assert saas_only["containers"] == {"postgres": {"tables": ["customers"]}}
            assert saas_only["saas"] == {"notion": {"churn_page_id": "new-page"}}
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_seed_manifest_merges_focused_container_seed() -> None:
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
        import json
        import tempfile
        from pathlib import Path

        from tests.integration.acme.seed import seed_acme

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "acme_ids.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "company": "Acme Co",
                        "generated_at": "old",
                        "containers": {
                            "mysql": {"tables": ["invoices"]},
                            "postgres": {"tables": ["old"]},
                        },
                        "saas": {"notion": {"churn_page_id": "notion-page"}},
                    }
                )
            )
            seed_acme.ACME_IDS_PATH = manifest_path
            seed_acme.seed_containers = lambda selected: {"postgres": {"tables": sorted(selected)}}

            manifest = seed_acme.build_manifest(
                include_containers=True,
                include_saas=False,
                selected_container_connectors={"postgres"},
            )
            assert manifest["containers"] == {
                "mysql": {"tables": ["invoices"]},
                "postgres": {"tables": ["postgres"]},
            }
            assert manifest["saas"] == {"notion": {"churn_page_id": "notion-page"}}
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_redshift_helpers_share_seed_database_default() -> None:
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

        from tests.integration.acme.coverage.test_mcp_tool_coverage import _credentials_for_slug
        from tests.integration.acme.e2e.helpers import credentials_for
        from tests.integration.acme.seed.saas.seed_redshift import _parse_host_port_database

        os.environ.pop("REDSHIFT_DATABASE", None)
        os.environ["REDSHIFT_CLUSTER_ENDPOINT"] = "example-redshift:5439/dev"
        os.environ["REDSHIFT_USER"] = "dataclaw"
        os.environ["REDSHIFT_PASSWORD"] = "password"

        assert _parse_host_port_database(os.environ["REDSHIFT_CLUSTER_ENDPOINT"]) == ("example-redshift", 5439, "dev")
        assert _credentials_for_slug("redshift")["database"] == "dev"
        assert credentials_for("redshift")["database"] == "dev"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_redshift_fixtures_target_seeded_audit_log() -> None:
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
        import yaml
        from pathlib import Path

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        redshift = fixtures["redshift"]

        assert redshift["read_get_schema"]["args"] == {"schema": "acme", "table": "audit_log"}
        assert redshift["read_get_row_count"]["args"] == {"schema": "acme", "table": "audit_log"}
        assert "acme.audit_log" in redshift["read_query_select"]["args"]["sql"]
        assert redshift["read_search_columns"]["args"] == {"pattern": "event"}
        assert redshift["write_insert_rows"]["args"]["table"] == "acme_coverage_write_probe"
        assert redshift["write_create_index"]["args"]["table"] == "audit_log"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_postgres_fixtures_target_seeded_raw_tables() -> None:
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
        import yaml
        from pathlib import Path

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        postgres = fixtures["postgres"]

        assert postgres["read_get_schema"]["args"] == {"schema": "raw", "table": "customers"}
        assert postgres["read_get_row_count"]["args"] == {"schema": "raw", "table": "customers"}
        assert postgres["read_get_table_freshness"]["args"] == {"schema": "raw", "table": "customers"}
        assert "raw.churn_events" in postgres["read_query_select"]["args"]["sql"]
        assert postgres["read_search_columns"]["args"] == {"pattern": "customer"}
        assert postgres["read_list_grants"]["args"] == {"schema": "raw", "table": "customers"}
        assert postgres["write_create_table"]["args"]["schema"] == "raw"
        assert postgres["write_insert_rows"]["args"]["table"] == "acme_coverage_write_probe"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_mysql_fixtures_target_seeded_billing_table() -> None:
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
        import inspect
        from pathlib import Path

        import yaml

        from tests.integration.acme.seed import seed_acme

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        mysql = fixtures["mysql"]

        assert "grant all privileges on acme_billing.*" in inspect.getsource(seed_acme._seed_acme_mysql).lower()
        assert mysql["read_get_schema"]["args"] == {"schema": "acme_billing", "table": "invoices"}
        assert mysql["read_get_row_count"]["args"] == {"schema": "acme_billing", "table": "invoices"}
        assert mysql["read_get_table_freshness"]["args"] == {"schema": "acme_billing", "table": "invoices"}
        assert "acme_billing.invoices" in mysql["read_query_select"]["args"]["sql"]
        assert mysql["read_search_columns"]["args"] == {"pattern": "invoice"}
        assert mysql["read_list_tables"]["args"] == {"schema": "acme_billing"}
        assert mysql["write_create_table"]["args"]["schema"] == "acme_billing"
        assert mysql["write_insert_rows"]["args"]["table"] == "acme_coverage_write_probe"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_sql_server_fixtures_target_seeded_legacy_table() -> None:
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
        import yaml
        from pathlib import Path

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        sql_server = fixtures["sql_server"]

        assert sql_server["read_get_schema"]["args"] == {"schema": "dbo", "table": "legacy_orders"}
        assert sql_server["read_get_row_count"]["args"] == {"schema": "dbo", "table": "legacy_orders"}
        assert sql_server["read_get_table_freshness"]["args"] == {"schema": "dbo", "table": "legacy_orders"}
        assert "dbo.legacy_orders" in sql_server["read_query_select"]["args"]["sql"]
        assert "dbo.legacy_orders" in sql_server["read_explain_query"]["args"]["sql"]
        assert sql_server["read_search_columns"]["args"] == {"pattern": "legacy"}
        assert sql_server["read_list_grants"]["args"] == {"schema": "dbo", "table": "legacy_orders"}
        assert sql_server["write_create_table"]["args"]["schema"] == "dbo"
        assert sql_server["write_insert_rows"]["args"]["table"] == "acme_coverage_write_probe"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_trino_fixtures_target_seeded_memory_table() -> None:
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
        import inspect
        from pathlib import Path

        import yaml

        from tests.integration.acme.seed.containers import seed_trino

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        trino = fixtures["trino"]

        assert "default.acme_orders" in inspect.getsource(seed_trino.seed_trino)
        assert trino["read_get_schema"]["args"] == {"schema": "default", "table": "acme_orders"}
        assert trino["read_get_row_count"]["args"] == {"schema": "default", "table": "acme_orders"}
        assert trino["read_get_table_freshness"]["args"] == {"schema": "default", "table": "acme_orders"}
        assert "memory.default.acme_orders" in trino["read_query_select"]["args"]["sql"]
        assert "memory.default.acme_orders" in trino["read_explain_query"]["args"]["sql"]
        assert trino["read_search_columns"]["args"] == {"pattern": "order"}
        assert trino["write_create_table"]["args"]["schema"] == "default"
        assert trino["write_insert_rows"]["args"]["table"] == "acme_coverage_write_probe"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_airflow_fixtures_target_seeded_dags_and_run() -> None:
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
        import inspect
        from pathlib import Path

        import yaml

        from tests.integration.acme.seed import seed_acme

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        airflow = fixtures["airflow"]
        seeded = inspect.getsource(seed_acme._write_acme_airflow_dags)

        assert "acme_etl_daily" in seeded
        assert "acme_churn_calc" in seeded
        assert airflow["read_get_run"]["args"] == {"dag_id": "acme_churn_calc", "run_id": "manual__acme_coverage"}
        assert airflow["read_list_dag_runs"]["args"] == {"dag_id": "acme_churn_calc"}
        assert airflow["read_get_variable"]["args"] == {"key": "acme_coverage_marker"}
        assert airflow["read_get_task_logs"]["args"]["dag_id"] == "acme_etl_daily"
        assert airflow["read_get_task_logs"]["args"]["run_id"] == "manual__acme_coverage"
        assert airflow["read_get_task_logs"]["args"]["task_id"] == "extract"
        assert airflow["write_trigger_dag"]["args"]["dag_id"] == "acme_etl_daily"
        assert airflow["write_set_variable"]["args"]["key"].startswith("acme_coverage_marker_")
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_prefect_fixtures_use_seeded_prefect_ids() -> None:
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
        import inspect
        from pathlib import Path

        import yaml

        from tests.integration.acme.seed.containers import seed_prefect

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        prefect = fixtures["prefect"]
        # Check the whole module — seed_prefect was refactored to delegate to
        # _seed_prefect_live and a fixture-fallback helper.
        seeded = inspect.getsource(seed_prefect)

        assert "acme_revenue_recalc" in seeded
        assert "idempotency_key" in seeded
        assert prefect["read_get_deployment"]["args"] == {"deployment_id": "$ACME_PREFECT_DEPLOYMENT_ID"}
        assert prefect["read_get_run"]["args"] == {"run_id": "$ACME_PREFECT_RUN_ID"}
        assert prefect["read_get_run_logs"]["args"] == {"run_id": "$ACME_PREFECT_RUN_ID"}
        assert prefect["read_get_task_run"]["args"] == {"task_run_id": "$ACME_PREFECT_TASK_RUN_ID"}
        assert prefect["read_get_task_logs"]["args"] == {
            "flow_run_id": "$ACME_PREFECT_RUN_ID",
            "task_run_id": "$ACME_PREFECT_TASK_RUN_ID",
        }
        assert prefect["read_list_flow_runs"]["args"] == {"flow_id": "$ACME_PREFECT_FLOW_ID"}
        assert prefect["write_trigger_flow_run"]["args"] == {"deployment_id": "$ACME_PREFECT_DEPLOYMENT_ID"}
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_snowflake_helpers_normalize_login_url() -> None:
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

        from tests.integration.acme.coverage.test_mcp_tool_coverage import _credentials_for_slug
        from tests.integration.acme.e2e.helpers import credentials_for
        from tests.integration.acme.seed.saas.common import normalize_snowflake_account

        os.environ["SNOWFLAKE_ACCOUNT"] = "https://wadmyyq-mdb74768.snowflakecomputing.com/"
        os.environ["SNOWFLAKE_USER"] = "dataclaw"

        assert normalize_snowflake_account(os.environ["SNOWFLAKE_ACCOUNT"]) == "wadmyyq-mdb74768"
        assert _credentials_for_slug("snowflake")["account"] == "wadmyyq-mdb74768"
        assert credentials_for("snowflake")["account"] == "wadmyyq-mdb74768"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_snowflake_live_checks_require_password_or_private_key() -> None:
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

        from tests.integration.acme.coverage.test_mcp_tool_coverage import _has_creds
        from tests.integration.acme.seed.saas.common import SAAS_ENV, missing_env

        for name in ("SNOWFLAKE_PASSWORD", "SNOWFLAKE_PRIVATE_KEY"):
            os.environ.pop(name, None)
        os.environ["SNOWFLAKE_ACCOUNT"] = "acme-test"
        os.environ["SNOWFLAKE_USER"] = "dataclaw"

        assert missing_env(SAAS_ENV["snowflake"]) == ["SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY"]
        ready, reason = _has_creds("snowflake")
        assert ready is False
        assert "SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY" in reason

        os.environ["SNOWFLAKE_PRIVATE_KEY"] = "test-key"
        assert missing_env(SAAS_ENV["snowflake"]) == []
        ready, _reason = _has_creds("snowflake")
        assert ready is True
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_snowflake_fixtures_target_seeded_marts() -> None:
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
        import yaml
        from pathlib import Path

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        snowflake = fixtures["snowflake"]

        assert snowflake["read_get_schema"]["args"] == {"schema": "MARTS", "table": "CHURN_EVENTS"}
        assert snowflake["read_get_row_count"]["args"] == {"schema": "MARTS", "table": "CHURN_EVENTS"}
        assert snowflake["read_get_table_freshness"]["args"] == {"schema": "MARTS", "table": "REVENUE_DAILY"}
        assert "MARTS.CHURN_EVENTS" in snowflake["read_query_select"]["args"]["sql"]
        assert snowflake["read_search_columns"]["args"] == {"pattern": "event", "schema": "MARTS"}
        assert snowflake["write_create_pipe"]["args"]["stage"] == "ACME_COVERAGE_STAGE"
        assert snowflake["write_create_task"]["args"]["sql"] == "select count(*) from MARTS.REVENUE_DAILY"
        assert snowflake["write_insert_rows"]["args"]["table"] == "ACME_COVERAGE_WRITE_PROBE"
        assert "executed" in snowflake["write_create_pipe"]["expect_shape"]["status"]
        assert "executed" in snowflake["write_create_task"]["expect_shape"]["status"]
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_fivetran_placeholder_accepts_public_secret_names() -> None:
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

        from tests.integration.acme.coverage.test_mcp_tool_coverage import _substitute_placeholders

        os.environ.pop("ACME_FIVETRAN_CONNECTOR_ID", None)
        os.environ.pop("ACME_FIVETRAN_DESTINATION_ID", None)
        os.environ["FIVETRAN_CONNECTOR_ID"] = "connector-from-secret"
        os.environ["FIVETRAN_DESTINATION_ID"] = "destination-from-secret"

        assert _substitute_placeholders("$ACME_FIVETRAN_CONNECTOR_ID") == "connector-from-secret"
        assert _substitute_placeholders("$ACME_FIVETRAN_DESTINATION_ID") == "destination-from-secret"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_redshift_cluster_identifier_comes_from_endpoint() -> None:
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

        from tests.integration.acme.coverage.test_mcp_tool_coverage import _substitute_placeholders
        from tests.integration.acme.seed.saas.common import redshift_cluster_identifier

        endpoint = "default-workgroup.203358432634.us-east-1.redshift-serverless.amazonaws.com:5439/dev"
        os.environ.pop("REDSHIFT_CLUSTER_IDENTIFIER", None)
        os.environ["REDSHIFT_CLUSTER_ENDPOINT"] = endpoint

        assert redshift_cluster_identifier(endpoint) == "default-workgroup"
        assert _substitute_placeholders("$REDSHIFT_CLUSTER_IDENTIFIER") == "default-workgroup"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_placeholder_detector_catches_embedded_values() -> None:
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
        from tests.integration.acme.coverage.test_mcp_tool_coverage import _unresolved_placeholders

        unresolved = _unresolved_placeholders({
            "name": "coverage-$MISSING_ONE",
            "nested": ["prefix-$MISSING_TWO-suffix", "$MISSING_THREE"],
        })

        assert unresolved == ["$MISSING_ONE", "$MISSING_THREE", "$MISSING_TWO"]
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_databricks_seed_hostname_normalization() -> None:
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
        from tests.integration.acme.seed.saas.seed_databricks import _databricks_hostname

        assert _databricks_hostname("dbc-acme.cloud.databricks.com") == "dbc-acme.cloud.databricks.com"
        assert _databricks_hostname("https://dbc-acme.cloud.databricks.com/api/2.0") == "dbc-acme.cloud.databricks.com"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_databricks_seed_discovers_workspace_cluster_defaults() -> None:
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
        from tests.integration.acme.seed.saas.seed_databricks import (
            _default_node_type,
            _default_spark_version,
        )

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Client:
            def get(self, path):
                if path.endswith("spark-versions"):
                    return Response({
                        "versions": [
                            {"key": "15.4.x-gpu-ml-scala2.12", "name": "15.4 LTS ML GPU", "long_term_support": True},
                            {"key": "14.3.x-scala2.12", "name": "14.3 LTS", "long_term_support": True},
                            {"key": "13.3.x-scala2.12", "name": "13.3 LTS", "long_term_support": True},
                        ]
                    })
                if path.endswith("list-node-types"):
                    return Response({
                        "node_types": [
                            {"node_type_id": "g4dn.xlarge", "description": "GPU", "num_cores": 4, "memory_mb": 16384},
                            {"node_type_id": "m5d.large", "description": "General purpose", "num_cores": 2, "memory_mb": 8192},
                            {"node_type_id": "m5d.xlarge", "description": "General purpose", "num_cores": 4, "memory_mb": 16384},
                        ]
                    })
                raise AssertionError(path)

        client = Client()
        assert _default_spark_version(client) == "14.3.x-scala2.12"
        assert _default_node_type(client) == "m5d.large"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_databricks_fixture_matches_seed_story() -> None:
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
        from tests.integration.services import orchestration_api

        assert orchestration_api.DATABRICKS_JOB["settings"]["name"] == "acme_events_refresh"
        assert orchestration_api.DATABRICKS_JOB_RUNS[0]["run_id"] == 5000
        assert orchestration_api.DATABRICKS_JOB_RUNS[0]["job_id"] == orchestration_api.DATABRICKS_JOB["job_id"]
        assert "acme.silver.events" in orchestration_api.DATABRICKS_JOB_RUNS[0]["logs"]
        assert orchestration_api.DATABRICKS_CLUSTER["cluster_id"] == "cluster-acme-analytics"
        assert orchestration_api.DATABRICKS_WAREHOUSE["id"] == "warehouse-acme-sql"
        assert orchestration_api.DATABRICKS_NOTEBOOK["path"] == "/Shared/dataclaw/acme/events_refresh"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_notion_seed_requires_explicit_parent_page_id() -> None:
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

        from tests.integration.acme.seed.saas.common import SAAS_ENV, missing_env

        os.environ.pop("NOTION_TEST_PARENT_PAGE_ID", None)
        os.environ["NOTION_INTEGRATION_TOKEN"] = "test-token"

        assert missing_env(SAAS_ENV["notion"]) == ["NOTION_TEST_PARENT_PAGE_ID"]

        os.environ["NOTION_TEST_PARENT_PAGE_ID"] = "explicit-page"
        assert missing_env(SAAS_ENV["notion"]) == []
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_notion_existing_page_body_is_replaced() -> None:
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
        from tests.integration.acme.seed.saas.seed_notion import _replace_page_body

        class FakeChildren:
            def __init__(self):
                self.list_calls = []
                self.append_calls = []

            def list(self, **kwargs):
                self.list_calls.append(kwargs)
                if "start_cursor" not in kwargs:
                    return {
                        "results": [{"id": "old-block-1"}, {"id": "old-block-2"}],
                        "has_more": True,
                        "next_cursor": "cursor-2",
                    }
                return {"results": [{"id": "old-block-3"}], "has_more": False}

            def append(self, **kwargs):
                self.append_calls.append(kwargs)

        class FakeBlocks:
            def __init__(self):
                self.children = FakeChildren()
                self.deleted = []

            def delete(self, **kwargs):
                self.deleted.append(kwargs["block_id"])

        class FakeNotion:
            def __init__(self):
                self.blocks = FakeBlocks()

        notion = FakeNotion()
        _replace_page_body(notion, "page-1", "Canonical Acme body")

        assert notion.blocks.children.list_calls == [
            {"block_id": "page-1", "page_size": 100},
            {"block_id": "page-1", "page_size": 100, "start_cursor": "cursor-2"},
        ]
        assert notion.blocks.deleted == ["old-block-1", "old-block-2", "old-block-3"]
        assert notion.blocks.children.append_calls == [
            {
                "block_id": "page-1",
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": "Canonical Acme body"}}
                            ]
                        },
                    }
                ],
            }
        ]
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_github_repo_defaults_from_owner_and_repo_name() -> None:
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

        from tests.integration.acme.seed.saas.common import github_test_repo

        os.environ.pop("GITHUB_TEST_REPO", None)
        os.environ.pop("GH_TEST_REPO", None)
        os.environ["GITHUB_REPOSITORY_OWNER"] = "acme-owner"
        os.environ["ACME_GITHUB_REPO_NAME"] = "dataclaw-acme-dbt"

        assert github_test_repo() == "acme-owner/dataclaw-acme-dbt"

        os.environ["GH_TEST_REPO"] = "gh-secret/repo"
        assert github_test_repo() == "gh-secret/repo"

        os.environ["GITHUB_TEST_REPO"] = "explicit/repo"
        assert github_test_repo() == "explicit/repo"
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_prefect_seed_matches_fixture_story() -> None:
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
        import inspect

        from tests.integration.acme.seed.containers import seed_prefect

        # Inspect the module — the seeder was refactored to split orchestration
        # (seed_prefect / _seed_prefect_live) and helpers, so the module-level
        # source is the right contract to pin.
        source = inspect.getsource(seed_prefect)

        assert "acme_revenue_recalc" in source
        assert "/flows/" in source
        assert "/deployments/" in source
        assert "/flow_runs/" in source
        assert "/task_runs/" in source
        assert "/logs/" in source
        assert "idempotency_key" in source
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_dbt_seed_matches_fixture_story() -> None:
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
        from tests.integration.acme.seed.containers.seed_dbt import seed_dbt
        from tests.integration.services.orchestration_api import dbt_manifest_fixture

        seed = seed_dbt()
        manifest = dbt_manifest_fixture()
        nodes = manifest["nodes"]

        assert seed["project"] == "dataclaw-acme-dbt"
        assert set(seed["models"].split(",")) == {"stg_customers", "dim_customers", "fct_orders"}
        assert nodes["model.dataclaw.stg_customers"]["name"] == "stg_customers"
        assert nodes["model.dataclaw.dim_customers"]["columns"]["cust_id"]["name"] == "cust_id"
        assert nodes["model.dataclaw.fct_orders"]["name"] == "fct_orders"
        assert "source.dataclaw.raw.orders" in nodes["model.dataclaw.fct_orders"]["depends_on"]["nodes"]
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_airflow_fixture_matches_seed_story() -> None:
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
        from tests.integration.services import orchestration_api

        assert {"acme_etl_daily", "acme_churn_calc"}.issubset(orchestration_api.AIRFLOW_DAGS)
        assert orchestration_api.AIRFLOW_RUNS["acme_churn_calc"][0]["dag_run_id"] == "manual__acme_coverage"
        assert orchestration_api.AIRFLOW_RUNS["acme_churn_calc"][0]["state"] == "failed"
        assert any(
            task["task_id"] == "extract" and "load_bq" in task["downstream_task_ids"]
            for task in orchestration_api.AIRFLOW_DAGS["acme_etl_daily"]["tasks"]
        )
        assert orchestration_api.AIRFLOW_VARIABLES["acme_coverage_marker"]["value"] == "seeded"
        assert "default_pool" in orchestration_api.AIRFLOW_POOLS
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_airbyte_fixture_matches_seed_story() -> None:
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
        from tests.integration.acme.seed.containers.seed_airbyte import seed_airbyte
        from tests.integration.services import orchestration_api

        seed = seed_airbyte()
        connection = orchestration_api.AIRBYTE_CONNECTIONS[seed["connection_id"]]

        assert seed["workspace_id"] == orchestration_api.AIRBYTE_WORKSPACE["workspaceId"]
        assert connection["name"] == "raw_postgres -> bq_raw"
        assert connection["sourceId"] == seed["source_id"]
        assert connection["destinationId"] == seed["destination_id"]
        assert seed["source_id"] in orchestration_api.AIRBYTE_SOURCES
        assert seed["destination_id"] in orchestration_api.AIRBYTE_DESTINATIONS
        assert any(str(job["id"]) == seed["job_id"] and job["status"] == "succeeded" for job in orchestration_api.AIRBYTE_JOBS)
        assert "orders" in str(connection["syncCatalog"]).lower()
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)


def test_acme_dagster_fixture_matches_seed_story() -> None:
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
        import inspect
        from pathlib import Path

        import yaml

        from tests.integration.acme.seed.containers import seed_dagster

        fixtures = yaml.safe_load(Path("../tests/integration/acme/coverage/fixtures.yml").read_text())
        dagster = fixtures["dagster"]
        seeded = inspect.getsource(seed_dagster.seed_dagster)
        launch = inspect.getsource(seed_dagster._launch_run)

        assert "acme_assets" in seeded
        assert "acme_asset_sensor" in seeded
        assert "acme_assets_daily" in seeded
        assert "launchPipelineExecution" in launch
        assert dagster["read_get_run"]["args"] == {"run_id": "$ACME_DAGSTER_RUN_ID"}
        assert dagster["read_get_event_logs"]["args"] == {"run_id": "$ACME_DAGSTER_RUN_ID"}
        assert dagster["read_get_run_steps"]["args"] == {"run_id": "$ACME_DAGSTER_RUN_ID"}
        assert dagster["read_get_sensor_state"]["args"] == {"name": "$ACME_DAGSTER_SENSOR"}
        assert dagster["read_get_schedule_state"]["args"] == {"name": "$ACME_DAGSTER_SCHEDULE"}
        assert dagster["write_materialize_asset"]["args"]["job_name"] == "$ACME_DAGSTER_JOB_NAME"
        assert dagster["write_backfill_partitions"]["args"]["partitions"] == ["$ACME_DAGSTER_PARTITION"]
        """
    )
    subprocess.run([sys.executable, "-c", script], cwd=repo_root / "backend", env=env, check=True)
