# DataClaw UI Test Script

Copy-paste prompts you can drop into chat to exercise every major flow. Each section: what it proves + the prompt + what "passing" looks like.

> Assumes you've completed Settings → LLM Provider (OpenAI key tested green), and configured at least Postgres (fixture), Notion (real), and one orchestrator (Airflow fixture). For full coverage configure all the items in `docs/TESTER_GUIDE.md` table.

---

## Block A - Connectors (does sync actually pull real data?)

For each configured connector, in **Connectors** tab:

1. Click **Test** - expect green badge with vendor-side response time.
2. Click **Sync** - expect "synced" with non-zero `objects_synced`.
3. Click the row to expand - expect to see tables / pages / runs by name (no "no data discovered").

**Pass:** every configured connector returns real data, not "fixture default" placeholders.
**Fail:** file as blocker per `docs/TESTER_GUIDE.md` template.

---

## Block B - Brain compile

Knowledge Base → **Brain** → click **Compile knowledge**.

Expect: progress meter, then `nodes_updated > 0` and `runtime_ms` in a few seconds.

In Brain → **Pages**, search for one of your configured connectors' slugs (`notion`, `airflow`, `postgres`). Expect at least one auto-generated wiki page per category.

**Pass:** Pages list is non-empty and references real entity names from your data.

---

## Block C - Chat (read-only RAG)

Open **Editor → Chat**, paste each prompt below. Expect: answer + at least one citation pill at the bottom.

### C1. Single-source warehouse question

```
What tables do I have in postgres? List them with row counts.
```

**Pass:** real table names from your fixture/warehouse, row counts match what `SELECT count(*) FROM <table>` would return, citations cite the schema source.

### C2. Document question

```
Summarize the most important Notion pages I've connected. What topics do they cover?
```

**Pass:** answer mentions real page titles you can find in the Notion connector's synced pages list.

### C3. ETL / orchestrator question

```
Show me the latest failed Airflow DAG run and what failed in it.
```

**Pass:** answer references `dataclaw_e2e_failure` (after `make integration-seed`), names the failed task, and includes a citation to Airflow.

### C4. Cross-source question

```
How does the customers table in postgres relate to anything documented in Notion? If you can't find a link, say so.
```

**Pass:** either (a) the agent identifies a real link between schema and docs with citations from both, or (b) the agent says it couldn't find one. Hallucinated "yes" answers without citations are a fail.

### C5. Chart

```
Show me a chart of order count by month from the postgres orders table.
```

**Pass:** chart appears below the answer; axes labels match real data.

### C6. Out-of-scope refusal

```
What's the weather in Bangalore today?
```

**Pass:** agent refuses or says it doesn't have a tool for that - does **not** hallucinate weather.

---

## Block D - Write + approval (the high-value test)

### D1. SQL write on Postgres (fixture)

```
Drop the test_summary table from postgres.
```

Expected flow:
1. Chat responds: "I've requested approval to run this; go to Observability to approve."
2. Gateway → Observability shows a critical alert with `MCP-Action: postgres.write_execute_sql`.
3. Click **Approve** in the drawer.
4. Alert flips to resolved; in chat, the run is acknowledged.
5. `psql -c '\dt'` against the fixture container confirms `test_summary` is gone.

**Pass:** all 5 steps.

### D2. Notion write (real Notion connector)

```
Append a paragraph "Sync ran at <today's ISO date>." to my Refunds runbook in Notion.
```

Expected flow:
1. Approval alert appears with `notion.write_append_to_page`, arguments include the real `page_id` (the agent must have called `notion.read_search_pages` to find it).
2. **Approve** → alert resolves → Notion page actually contains the new paragraph.

**Pass:** Notion shows the new block at the bottom of the page.

**If the agent guessed a fake page_id**, the new pre-flight validator kicks in: no alert is created, chat says something like *"I can't append - the page_id … doesn't exist in your Notion workspace. Let me search first."* Followed (on the next turn) by a real `read_search_pages` call. This is correct behavior.

### D3. Approval reject path

Repeat D1, then click **Reject** instead of Approve.

**Pass:** alert flips to `resolved` with no audit row for the write; the table is still there.

---

## Block E - Background agents

Agents → **Background**.

1. Verify all 8 system agents exist: `alerting`, `freshness`, `data_quality`, `ingestion`, `chat`, `docs`, `metadata`, `lineage`. (Last two may collapse depending on grants.)
2. For each agent: confirm it has read grants on the connectors you configured (open Configure modal).
3. Click **Run now** on `freshness`. Expect a run row to appear within ~10s in Gateway → Observability.
4. If you want to force a failure: configure a connector with a deliberately bad token and click Sync - `alerting` should generate a critical alert within its cadence.

---

## Block F - Settings / LLM provider switching

1. Settings → LLM Provider → switch to Ollama, set `base_url=http://localhost:11434/v1`, click Test.
2. If Ollama isn't running, expect a clean error (not a 500).
3. Switch back to OpenAI.
4. **Sanity:** ask C1 again with each provider - answers should remain similar (provider just changes the LLM, not the retrieval).

---

## Block G - Failure-mode UI checks

These are the small things that should NOT crash the app:

- Click **Approve** on an alert that's already resolved → expect a clear 400 message, not 500.
- Search for `;DROP TABLE` in the events filter → expect normal "no results", not a backend exception.
- Pop the connector configure modal on a connector that doesn't exist (manually navigate to `/connectors/zzz`) → 404 page, not blank.
- Press Esc inside the **New custom agent** modal → modal closes (this was broken pre-v0.1.1).

---

## Sign-off

If all blocks pass: stage 1 is green and you can move on to stage 2 (install paths) per the TESTER_GUIDE.

If anything fails, file per the template in `docs/TESTER_GUIDE.md` with severity tagged.
