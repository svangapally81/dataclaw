"""
Seed 10 realistic data-org docs under a single Notion parent page.

Idempotent-ish: re-running deletes existing child pages with matching titles before recreating.

Usage:
    set -a && . .env.integration && set +a
    python tests/integration/notion/seed_pages.py <PARENT_PAGE_ID>
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


def notion_request(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ["NOTION_INTEGRATION_TOKEN"]
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {body_text}") from None


def text(content: str, *, bold: bool = False, code: bool = False) -> dict:
    annotations = {}
    if bold:
        annotations["bold"] = True
    if code:
        annotations["code"] = True
    rich = {"type": "text", "text": {"content": content}}
    if annotations:
        rich["annotations"] = annotations
    return rich


def heading(level: int, content: str) -> dict:
    return {
        "object": "block",
        "type": f"heading_{level}",
        f"heading_{level}": {"rich_text": [text(content)]},
    }


def paragraph(content: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [text(content)]},
    }


def bullet(content: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [text(content)]},
    }


def code_block(content: str, language: str = "sql") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": [text(content)], "language": language},
    }


def callout(content: str, emoji: str = "warning") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": [text(content)], "icon": {"type": "emoji", "emoji": "⚠️"}},
    }


# =====================================================================
# Doc bodies
# =====================================================================

DOCS: list[tuple[str, list[dict]]] = []


DOCS.append(("Data Glossary", [
    paragraph("Canonical definitions for the terms data, finance, and growth use most. If a definition here disagrees with a dashboard or a query, the glossary wins — file a PR or open a ticket against the dashboard."),
    heading(2, "Active customer"),
    paragraph("A customer with at least one logged-in session in the last 30 days AND a non-canceled subscription. The exact SQL is in the metrics handbook."),
    heading(2, "Monthly Recurring Revenue (MRR)"),
    paragraph("Sum of monthly-equivalent subscription fees for all active subscriptions, in USD. Annual plans divide by 12. Discounts and proration are applied. Trials are NOT counted (they pay nothing)."),
    heading(2, "Lifetime Value (LTV)"),
    paragraph("Cumulative net revenue per customer to date. Net of refunds, gross of discounts. We do NOT model future LTV here — finance has a separate predictive model."),
    callout("Stored in derived.customer_360.total_revenue. Note: that column is in DOLLARS while core.payments.amount_cents is CENTS — easy to mis-join.", "warning"),
    heading(2, "Churn"),
    paragraph("A customer churns when their subscription enters the 'canceled' state and stays there for 30+ days. Pause is not churn. Past_due is not churn."),
    heading(2, "Trial conversion"),
    paragraph("(# trials that became paid) / (# trials that ended) measured weekly. Both numbers exclude trials still active. Target: 22%."),
]))


DOCS.append(("Metrics Handbook", [
    paragraph("KPI definitions with their canonical SQL, owner, target, and where they show up. If you write a new dashboard, copy the SQL from here verbatim — do not paraphrase."),
    heading(2, "Active customers (weekly)"),
    paragraph("Owner: Growth"),
    paragraph("Target: 5% week-over-week growth"),
    code_block("""SELECT count(DISTINCT s.user_id)
FROM events.session_starts s
JOIN core.subscriptions sub ON sub.customer_id = s.user_id
WHERE s.started_at > now() - interval '7 days'
  AND sub.status NOT IN ('canceled', 'paused');"""),
    heading(2, "Monthly Recurring Revenue"),
    paragraph("Owner: Finance"),
    paragraph("Target: $2.4M by end of FY26"),
    code_block("""SELECT sum(
  CASE plan
    WHEN 'starter' THEN 49
    WHEN 'pro' THEN 199
    WHEN 'enterprise' THEN 1999
  END
) AS mrr
FROM core.subscriptions
WHERE status IN ('active', 'past_due');"""),
    heading(2, "Activation rate"),
    paragraph("Owner: Product Analytics"),
    paragraph("Target: 35% of trial signups activate within first 7 days"),
    paragraph("Activated = ran 3+ queries in their first 7 days. Source-of-truth column: derived.activation_funnel.activated."),
    code_block("""SELECT
  count(*) FILTER (WHERE activated) * 100.0 / count(*) AS activation_pct
FROM derived.activation_funnel
WHERE signed_up_at > now() - interval '90 days';"""),
    heading(2, "Refund rate (15-min)"),
    paragraph("Owner: Finance + Security"),
    paragraph("Alert threshold: 3x the rolling 7-day baseline for the same window-of-day."),
    paragraph("Pager: refund_alerts DAG runs every 15 minutes."),
]))


DOCS.append(("Customer Segmentation", [
    paragraph("How we segment customers for analytics, marketing campaigns, and customer-success outreach."),
    heading(2, "Segment definitions"),
    paragraph("All thresholds applied to derived.customer_360.total_revenue (which is in dollars — be careful)."),
    bullet("whale: > $5,000 lifetime revenue"),
    bullet("core: $1,000 – $5,000 lifetime revenue"),
    bullet("casual: $1 – $1,000 lifetime revenue"),
    bullet("dormant: zero lifetime revenue OR no activity in 90+ days"),
    heading(2, "Migration note (2025-Q1)"),
    paragraph("We bumped 'whale' from $3,000 to $5,000 because the cohort got too big to be useful for AE assignments. Dashboards built before 2025-01-15 may show inflated whale counts — the threshold change is in version control on the customer_360 dbt model, not the SQL above."),
    callout("If you query this directly, JOIN derived.customer_360 — DO NOT recompute from core.payments unless you really mean it. The customer_360 snapshot bakes in refund + discount logic that is non-trivial to reproduce.", "warning"),
    heading(2, "Owner mapping"),
    bullet("whale segment: assigned to enterprise AE pool"),
    bullet("core segment: assigned to mid-market AM pool"),
    bullet("casual segment: self-serve (no human owner)"),
    bullet("dormant: re-engagement automation only"),
]))


DOCS.append(("Orders Pipeline Runbook", [
    paragraph("On-call runbook for daily_orders_refresh. If you're paged, read this first."),
    heading(2, "What it does"),
    paragraph("Refreshes core.orders and core.order_items nightly from the OLTP replica. Runs at 00:00 UTC. SLA is 30 minutes — if not green by 00:30, page on-call."),
    heading(2, "Common failure modes"),
    heading(3, "1. OLTP replica lag"),
    paragraph("If replica lag > 10 minutes when the DAG starts, the extract task may fail because we use a transactional snapshot for consistency. Wait 15 min and retry."),
    heading(3, "2. order_items_idx_orderid corruption"),
    paragraph("This index has corrupted twice (incident PG-2024-1129 and PG-2024-1411). Symptoms: load_core_order_items hangs > 20min. Fix: REINDEX INDEX core.order_items_orderid_idx CONCURRENTLY. Do NOT run with daily_orders_refresh active."),
    heading(3, "3. Currency-conversion drift"),
    paragraph("Some non-USD orders show up with total_cents that doesn't match item-line subtotals. Currency conversion lives in transform_apply_business_rules. If diffs > 1%, escalate to billing-eng."),
    heading(2, "Manual backfill"),
    code_block("airflow dags backfill daily_orders_refresh -s 2025-04-01 -e 2025-04-15", language="bash"),
    callout("NEVER run a manual backfill while the scheduled run is also active — see PG-2024-1129. Pause the schedule first.", "warning"),
]))


DOCS.append(("Pipeline Ownership", [
    paragraph("Who owns what. If you don't know who owns a DAG, this is the source of truth."),
    heading(2, "Core data"),
    bullet("daily_orders_refresh — core-data@dataclaw.com (Slack: #core-data-oncall)"),
    bullet("event_warehouse_loader — data-platform@dataclaw.com"),
    bullet("data_quality_checks — data-platform@dataclaw.com"),
    heading(2, "Finance + billing"),
    bullet("payments_reconciliation — finance-eng@dataclaw.com"),
    bullet("subscription_lifecycle — billing-eng@dataclaw.com"),
    bullet("refund_alerts — finance-eng@dataclaw.com"),
    heading(2, "Marketing + growth"),
    bullet("email_send_loader — marketing-eng@dataclaw.com"),
    bullet("ad_spend_sync — marketing-eng@dataclaw.com"),
    bullet("attribution_backfill — marketing-eng@dataclaw.com"),
    heading(2, "Analytics"),
    bullet("weekly_customer_360 — analytics-eng@dataclaw.com"),
    bullet("cohort_analysis — product-analytics@dataclaw.com"),
    bullet("signup_to_activation_funnel — product-analytics@dataclaw.com"),
    heading(2, "Orphaned / deprecated"),
    bullet("legacy_orders_archive — DEPRECATED 2024-08. Was core-data. Do not unpause."),
    callout("Maria left the team 2025-03 — she owned ad_spend_sync. New owner is marketing-eng@dataclaw.com (whole team) until we hire a replacement.", "warning"),
]))


DOCS.append(("Data Quality Policies", [
    paragraph("How we handle data-quality issues. Owners: data-platform team."),
    heading(2, "Tiers"),
    bullet("platinum: finance-critical (core.payments, core.refunds, derived.payments_reconciled). DQ failures fail the entire downstream chain."),
    bullet("gold: product-critical (core.orders, core.customers, derived.customer_360, derived.activation_funnel). DQ failures Slack-warn but proceed."),
    bullet("silver: analytics-only (derived.cohort_retention, marketing.email_sends). DQ failures notify channel-owner only."),
    heading(2, "Suite definitions"),
    paragraph("All Great Expectations suites live in `data_quality/expectations/` in the dataclaw-models repo. The data_quality_checks DAG runs them daily at 07:00 UTC."),
    heading(2, "Escalation"),
    bullet("platinum failure: PagerDuty page → finance-eng oncall → CTO if unresolved 2hr"),
    bullet("gold failure: Slack #data-quality-alerts → table owner"),
    bullet("silver failure: Slack channel mentioned in suite metadata"),
    heading(2, "Known stale snapshots"),
    paragraph("derived.customer_360 has been documented as 'rebuilt weekly Monday 02:00 UTC' but the snapshot is currently 14 days stale because the 2025-Q1 segment-redefinition rollout broke the build. Rebuild is unblocked but not yet rerun. ETA next week."),
]))


DOCS.append(("Incident Postmortems", [
    paragraph("Recent significant incidents. Add new ones at the top."),
    heading(2, "PG-2025-0117: refund_alerts false-positive storm"),
    paragraph("Date: 2025-01-17 03:00 UTC"),
    paragraph("What happened: a Stripe webhook outage caused refund events to batch-replay over a 30-minute window. refund_alerts paged on-call 8 times in 20 minutes."),
    paragraph("Resolution: added a backpressure window to refund_alerts (ignore alerts within 15 min of the previous one)."),
    heading(2, "PG-2024-1411: order_items index corruption (recurrence)"),
    paragraph("Date: 2024-11-04"),
    paragraph("Same as PG-2024-1129 below. Concurrent backfill + scheduled run corrupted the index. Recovery took 4 hours."),
    paragraph("Action: added a hard pre-check to daily_orders_refresh that fails fast if a manual backfill is running. SHIPPED in dataclaw-models#1834."),
    heading(2, "PG-2024-1129: order_items_orderid_idx corruption"),
    paragraph("Date: 2024-10-29"),
    paragraph("What happened: a manual backfill of daily_orders_refresh was started while the scheduled run was active. Both wrote to core.order_items via different transactions, corrupting order_items_orderid_idx. order lookup queries returned partial results for ~6 hours."),
    paragraph("Detection: customer-success ticket about 'missing line items in invoice export'."),
    paragraph("Resolution: REINDEX INDEX CONCURRENTLY core.order_items_orderid_idx. ~45min."),
    paragraph("Lesson: do not run concurrent backfills. See PG-2024-1411 for follow-up."),
]))


DOCS.append(("Roadmap Q3", [
    paragraph("Q3 2025 data + analytics roadmap. Last edited 2025-04-15."),
    heading(2, "Shipping in Q3"),
    bullet("real-time event ingestion: replace event_warehouse_loader (5-min microbatch) with Materialize-based streaming sink"),
    bullet("metrics-as-code: stop hand-writing the metrics handbook in Notion; generate it from dbt model metadata"),
    bullet("attribution v3: drop position-based, switch to data-driven attribution (training on derived.attribution_touchpoints history)"),
    heading(2, "Deprecation watchlist"),
    bullet("marketing.touchpoint_attribution_legacy — deprecated 2024-08, removal target Q4 2025. Has zero rows; only 3 Looker queries still reference it."),
    bullet("Kafka product-events-v1 + v2 topics — already shut off. Do not consume."),
    bullet("legacy_orders_archive DAG — paused, awaiting deletion in Q3."),
    heading(2, "Stretch / unplanned"),
    bullet("BigQuery export for archival data older than 1 year"),
    bullet("self-serve cohort builder UI for product-analytics team"),
]))


DOCS.append(("dbt Style Guide", [
    paragraph("How we write dbt models. Read this before opening a PR against analytics-models."),
    heading(2, "Naming"),
    bullet("staging models: stg_<source>__<table> (double underscore between source and table)"),
    bullet("intermediate: int_<entity>__<verb> (e.g. int_orders__deduped)"),
    bullet("marts: <domain>_<concept> (e.g. finance_revenue_daily)"),
    heading(2, "Materialization"),
    bullet("staging: view"),
    bullet("intermediate: ephemeral if cheap, table if join-heavy"),
    bullet("marts: incremental for >1M rows, otherwise table"),
    heading(2, "Testing"),
    paragraph("Every model needs at least: not_null on the primary key, unique on the primary key, and a relationship test on every FK. Custom tests for business invariants live in tests/."),
    heading(2, "Drift with this guide"),
    callout("Models created before 2024-Q4 use single underscores (e.g. stg_postgres_orders). They were renamed in PR #1689 but the rollout stalled — there are still ~12 single-underscore models in the codebase. Don't add new ones, but don't rename existing without coordination.", "warning"),
]))


DOCS.append(("KPI Targets 2025", [
    paragraph("Quarterly KPI targets agreed with the board. Updated each quarter."),
    heading(2, "Q1 2025 (closed)"),
    bullet("MRR: $1.6M target / $1.71M actual ✓"),
    bullet("Active customers (weekly): 4,200 target / 4,051 actual ✗"),
    bullet("Activation rate: 32% target / 34.1% actual ✓"),
    heading(2, "Q2 2025 (closed)"),
    bullet("MRR: $1.85M target / $1.92M actual ✓"),
    bullet("Active customers (weekly): 4,800 target / 4,612 actual ✗"),
    bullet("Activation rate: 33% target / 35.4% actual ✓"),
    heading(2, "Q3 2025 (in flight)"),
    bullet("MRR: $2.1M target"),
    bullet("Active customers (weekly): 5,400 target"),
    bullet("Activation rate: 34% target"),
    bullet("Net revenue retention: 112% target (new metric this quarter)"),
    callout("The 'Active customers' miss in Q1 + Q2 is being investigated. Suspected cause: the metrics handbook query joins on subscriptions.status NOT IN ('canceled','paused') but the dashboard ignores 'paused'. Reconciliation pending.", "warning"),
]))


# =====================================================================
# Main
# =====================================================================

def list_existing_children(parent_id: str) -> list[dict]:
    children = []
    cursor: str | None = None
    while True:
        path = f"/blocks/{parent_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        resp = notion_request("GET", path)
        children.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return children


def archive_block(block_id: str) -> None:
    notion_request("PATCH", f"/blocks/{block_id}", {"archived": True})


def create_page(parent_id: str, title: str, children: list[dict]) -> str:
    body = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": children,
    }
    resp = notion_request("POST", "/pages", body)
    return resp["id"]


def main(parent_id: str) -> None:
    print(f"Seeding under parent page: {parent_id}")
    print("Cleaning up existing child pages with matching titles...")
    existing = list_existing_children(parent_id)
    target_titles = {title for title, _ in DOCS}
    for block in existing:
        if block.get("type") != "child_page":
            continue
        title = block.get("child_page", {}).get("title", "")
        if title in target_titles:
            print(f"  archiving stale: {title}")
            archive_block(block["id"])
            time.sleep(0.4)

    print(f"Creating {len(DOCS)} pages...")
    for title, blocks in DOCS:
        # Notion limits to 100 blocks per /pages call. Our docs are well under.
        page_id = create_page(parent_id, title, blocks)
        print(f"  ✓ {title} -> {page_id}")
        time.sleep(0.4)
    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python seed_pages.py <parent_page_id>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
