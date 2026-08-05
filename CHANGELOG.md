# Changelog

All notable changes to DataClaw are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.1.0 - initial release

The first public DataClaw release. A single `pipx install dataclaw-platform && dataclaw init && dataclaw start` brings up the full product runtime: API, bundled UI, in-process worker, embedded persistent Chroma, and a seeded SQLite app DB. Docker Compose remains the path for multi-container deployments.

### Highlights

- **Pipx is the headline path.** Wheel ships the bundled frontend, alembic migrations, and the full connector catalog. No source tree or Node required on the host.
- **Single root Dockerfile.** Builds the React frontend then a Python runtime with `dataclaw` on `$PATH`. Compose uses the same image for API + worker; embedded mode is just the same code with `DATACLAW_EMBEDDED_WORKER=true` and `CHROMA_URL` unset.
- **Embedded Chroma.** Persistent client at `~/.dataclaw/chroma/` by default. Compose still runs a dedicated `chroma` service when `CHROMA_URL` is set.
- **Auth-disabled by default for local installs.** Hosted deployments flip `DATACLAW_AUTH_DISABLED=false` and configure `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
- **Idempotent seed.** Workspace, admin user, 21-connector catalog, 11 built-in agents, and the OpenAI provider (when `OPENAI_API_KEY` is set) are ensured on every startup.

### Connectors (21 total)

- **🟢 Stable (15)**: `postgres`, `mysql`, `sql_server`, `trino`, `bigquery`, `snowflake`, `databricks`, `sqlite`, `notion`, `confluence`, `github`, `dbt`, `prefect`, `dagster`, `airbyte`
- **🔵 Stable (read-only, 1)**: `fivetran`
- **🟡 Beta (1)**: `airflow` (sandbox infrastructure flakiness)
- **🔴 Known issue (1)**: `redshift` (psycopg3 driver bug - opt in with `EXPERIMENTAL_ENABLE_redshift=true`)
- **🚫 Unsupported (2)**: `quip` (vendor discontinued), `google_docs` (OAuth flow not wired)

All stable tiers are backed by live MCP tool coverage runs against real backends (or vendor sandboxes for SaaS). See `docs/CONNECTOR_MATRIX.md` for the per-connector tool table.

### Under the hood

- Per-slug MCP catalogs with grant-gated tool execution under `/mcp/{slug}`.
- Write SQL safety classification, destructive-write approval alerts, `agent_write_audit` history.
- Chroma-backed retrieval, OpenAI MCP tool-calling, Vega-Lite chart specs, DB-persisted structured logs.
- Knowledge graph compile from frontmatter + `[[wiki-links]]`; tier-1 markdown wiki pages mirrored in `wiki_pages`.
- Ollama support alongside OpenAI via OpenAI-compatible `base_url` plumbing.
- 19 alembic migrations packaged inside the wheel via `importlib.resources`.
- Release pipeline: docs/catalog parity check, wheel build, pipx smoke install (with `dataclaw init` + `/health` boot check), PyPI publish, GHCR image publish, GitHub release.

### Known limitations

- SQLite is the only supported app database for v0.1. Local single-node only.
- APScheduler runs a single worker; running more than one duplicates scheduled syncs.
- Chat agent exhibits tool-routing variability in multi-connector scenarios - direct MCP tool access via `/mcp/{slug}/tools/{tool}` is the reliable path. Chat improvements tracked for a follow-up release.
