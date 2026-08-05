# E-commerce Analytics Integration Scenario

The integration scenario models an analytics stack with customer, order, and event data. DataClaw syncs connector metadata, embeds it into the knowledge base, and exercises chat flows for schema discovery, SQL, charts, and destructive-write approval.

## Flow

1. Configure SQLite, Postgres, MySQL, Chroma, orchestration, and knowledge-base connectors.
2. Sync schemas and operational metadata into SQL plus Chroma.
3. Ask chat to list indexed tables across data stores and answer last-week order volume.
4. Ask chat to create `test_summary`, generate a revenue chart, trigger Airflow/dbt work, create Notion documentation, and commit a GitHub README.
5. Attempt a destructive `DROP TABLE`, verify it waits for approval, approve it, and confirm audit/log records.
6. Create a custom read-only analyst and verify write tools return 403.

Postgres carries orders/customers/products/pipeline_runs. MySQL carries a lightweight customer mirror for cross-store coverage. The dbt project under `tests/integration/dbt` defines the expected staging and mart model names; the default fixture service returns dbt-compatible API payloads so the E2E path can run without external dbt Cloud credentials.
