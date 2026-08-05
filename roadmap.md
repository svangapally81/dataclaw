# DataClaw Roadmap

This is the public roadmap. Ordered by priority, not by date.

## v0.1 - first OSS release (shipping now)

- `pipx install dataclaw` brings up the full product runtime: API, bundled UI, in-process APScheduler worker, embedded persistent Chroma, SQLite app DB.
- Docker Compose for multi-container deployments. Same image for API + worker; dedicated Chroma service.
- 21 connectors: stable for postgres, mysql, sql_server, trino, bigquery, sqlite, snowflake, databricks; stable-read-only for fivetran; beta for notion, confluence, github, airflow, dbt, prefect, dagster, airbyte.
- Per-slug MCP catalogs, grant-gated tool execution, destructive-write approval flow, `agent_write_audit` history.
- 11 built-in agents (chat, docs, compile, alerting, data-quality, freshness, ingestion, reconciliation, metadata, lineage) plus custom agents.
- Knowledge graph compile from wiki frontmatter + `[[wiki-links]]`. Chroma-backed retrieval. OpenAI MCP tool-calling. Vega-Lite chart specs.
- OpenAI and Ollama LLM providers.

---

## Theme 1 - Connector expansion

More sources in the graph, deeper coverage on the ones already there. The graph is only as good as what feeds it.

- Graduate the 11 beta connectors to stable via live integration tests against vendor sandboxes (notion, confluence, github, airflow, dbt, prefect, dagster, airbyte first).
- **BI tools as connectors** - Tableau, Looker, Quicksight, Metabase, Power BI. Pull dashboards, published metrics, view definitions, and usage stats into the knowledge graph so chat can answer "which dashboard uses this table?" and "what's the definition of MRR in Looker?".
- New data-source connectors: ClickHouse, DuckDB, MotherDuck, Athena, MongoDB, Iceberg.
- New orchestration connectors: GitHub Actions runs, Mage, Hightouch, Census.
- New knowledge connectors: Linear, Jira, Slack channels, Confluence spaces, Google Drive folders, internal markdown repos.
- Per-tool risk labels surfaced in the UI: read-only, write, destructive, external-API, cost-sensitive.

---

## Theme 2 - Semantics and golden queries

Let users curate what makes their data theirs. Today the graph learns from schemas and wiki pages; teams need to ground it in business meaning.

- **Definitions library** - first-class metric definitions, business glossary entries, and dimension notes. Users add them via UI or files; chat-agent retrieval pulls them before answering. "What is active user?" returns the company's definition, not a hallucination.
- **Golden queries** - mark a query as canonical for a question. The agent learns to prefer golden SQL over generating fresh SQL for the same intent. Comes with: marking flow in chat, golden-query browse page, edit / deprecate / version history.
- **Semantic linking** - bind a definition to specific tables, columns, dashboards, dbt models. The graph surfaces inconsistencies (two definitions for ARR; a metric without a backing column).
- **Workspace rules** - a single `RULES.md`-style file that conditions every agent ("always exclude internal accounts", "prefer the `analytics` schema over `raw`", "ARR is in USD").
- **Correction-to-context** - when a user corrects a chat answer, offer to save the correction as a definition, golden query, or rule.

---

## Theme 3 - Evals

You can't ship the product to a team without measuring whether it's actually answering correctly.

- **Eval suites** - define a question, the expected answer or SQL shape, and the data fixtures. Run on demand or scheduled.
- **Eval runs as first-class objects** - pass/fail, diffs vs expected, latency, token cost, tool-call trace. Searchable and exportable.
- **Regression detection** - when an eval that used to pass starts failing, surface it as an alert with the diff inline.
- **Eval-on-PR** - wire eval runs into CI so a change to prompts, retrieval, or context can't silently regress chat quality.
- **Eval dashboard** - trends for pass rate, latency p50/p95, token cost per agent / model / context version.

---

## Theme 4 - Consumption layer

Bring DataClaw to where data work happens. The product is already there in the browser; this is about everywhere else.

- **Slack app** - chat with the agent in any channel or DM. Approve destructive writes. Triage alerts. Run workflows. Threaded answers with citations.
- **MCP client recipes** - Codex, Cursor, Claude Desktop, ChatGPT. Connect once, query your warehouse from the IDE.
- **CLI chat** - `dataclaw ask "how many active users this week?"` returns the answer plus the SQL it ran.
- **Scheduled questions** - pick a question, pick a cadence, route the answer to a Slack channel, email, or webhook. "Email me churn cohort numbers every Monday at 9am." Includes failure handling and answer-diff alerts.
- **Workflows** - package recurring multi-step analyses as named runs (weekly business review, failed-pipeline investigation, table validation). Trigger by event (sync complete, schema drift, failed DAG, eval failure) or schedule.
- **Shareable threads** - share, fork, replay, and annotate chat threads so teams can review and reuse work.

---

## Theme 5 - Production hardening

What needs to be true before calling DataClaw production-ready for teams larger than one.

- **Enterprise auth** - OIDC/SSO, groups, roles, service accounts, admin policy controls.
- **Postgres as a supported app DB** alongside SQLite (with a CI migration smoke gate).
- **Multi-worker support** - replace the APScheduler singleton with a distributed queue so scheduled syncs don't duplicate.
- **Pass-through permissions** - enforce user/group connector, dataset, table, row, and column permissions instead of relying only on per-agent grants.
- **Audit export** - agent runs, tool calls, write approvals, syncs, evals, definitions, permission changes - exportable for compliance review.
- **Cost governance** - per-workspace budgets for token spend, query cost, warehouse scan size, tool-call volume, background-agent runs.
- **LLM data policy** - per-provider toggles for what may be sent (metadata only, query text, result samples, screenshots, full results).
- **Notification routing** - alerts, eval failures, approvals, workflow summaries to Slack, email, PagerDuty, webhooks.
- **Backup + restore** - first-class commands and tested DR story for SQLite + Chroma + encrypted secrets.

---

## How to influence the roadmap

Open an issue describing the problem you're trying to solve. Pull requests welcome - see `CONTRIBUTING.md`. Connector graduations are code changes first: graduate by shipping a live integration test, not by editing the catalog.
