"""
Seed the GitHub repo with realistic data-engineering-codebase contents.

Idempotent: if a file already exists with the same SHA, skipped. If different, updated.

Usage:
    set -a && . .env.integration && set +a
    python tests/integration/github/seed_repo.py <owner/repo>
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://api.github.com"


def github_request(method: str, path: str, body: dict | None = None) -> dict | None:
    token = os.environ["GITHUB_TOKEN"]
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {body_text}") from None


# =====================================================================
# File contents
# =====================================================================

FILES: dict[str, str] = {}

FILES["README.md"] = """# dataclaw-docs

Analytics models, runbooks, and pipeline specs for the DataClaw data warehouse.

## Repo layout

| Path | Purpose |
|------|---------|
| `sql/models/` | Analytics SQL — derived tables built nightly by Airflow |
| `sql/staging/` | Source-system staging views |
| `runbooks/` | On-call runbooks for production pipelines |
| `data_quality/` | Great Expectations suites for tier:gold and tier:platinum tables |
| `.github/CODEOWNERS` | Per-path owner mapping (consumed by GitHub for PR routing) |

## Conventions

- All SQL targets PostgreSQL 16. We use `JSONB`, `generate_series`, and lateral joins.
- Models materialize as tables in the `derived` schema. Source data lives in `core`, `marketing`, and `events` schemas.
- Each model has a header comment specifying owner, schedule, upstream tables, downstream consumers.
- We do NOT use dbt (yet — it's on the Q4 roadmap). Models are run by Airflow DAGs.

## Where things live

| Concept | Location |
|---------|----------|
| Pipeline source code | This repo: `sql/models/` |
| Pipeline orchestration | Airflow at https://airflow.dataclaw.com |
| Pipeline ownership | Notion: "Pipeline Ownership" |
| KPI definitions | Notion: "Metrics Handbook" (canonical) |
| Customer segmentation | Notion: "Customer Segmentation" |

## Caveats

- `derived.customer_360.total_revenue` is in **dollars**; `core.payments.amount_cents` is in **cents**. Easy mistake when joining.
- `events.product_events.event_type` contains both `signed_up` and `signup` (typo from a legacy SDK). Always coalesce.
- `marketing.touchpoint_attribution_legacy` is empty and deprecated. Use `derived.attribution_touchpoints`.
"""


FILES["sql/models/customer_360.sql"] = """-- customer_360.sql
-- Owner: analytics-eng@dataclaw.com
-- Built by: weekly_customer_360 Airflow DAG (Mon 02:00 UTC)
-- Materialized as: derived.customer_360 (truncate-and-load)
--
-- Upstream: core.customers, core.orders, marketing.email_sends, events.product_events
-- Downstream: every customer-level dashboard in Looker; Salesforce sync; ML feature store
--
-- WARNING: total_revenue is in DOLLARS. core.payments.amount_cents is in CENTS.
-- Do not join customer_360.total_revenue against payments.amount_cents without a /100 conversion.

WITH order_agg AS (
  SELECT
    customer_id,
    sum(total_cents)::NUMERIC / 100.0 AS total_revenue_dollars,
    count(*)                          AS order_count,
    max(placed_at)                    AS last_order_at
  FROM core.orders
  WHERE status NOT IN ('canceled', 'stuck_in_3ds')
  GROUP BY customer_id
),
email_agg AS (
  SELECT
    customer_id,
    count(*) FILTER (WHERE event_type = 'open')    AS email_opens_total,
    count(*) FILTER (WHERE event_type = 'click')   AS email_clicks_total,
    count(*) FILTER (WHERE event_type = 'bounce')  AS email_bounces_total
  FROM marketing.email_sends
  WHERE customer_id IS NOT NULL
  GROUP BY customer_id
),
event_agg AS (
  SELECT
    user_id AS customer_id,
    count(*) AS lifetime_event_count,
    max(created_at) AS last_event_at
  FROM events.product_events
  WHERE user_id IS NOT NULL
  GROUP BY user_id
)
INSERT INTO derived.customer_360 (
  customer_id, total_revenue, order_count, last_order_at, days_since_signup,
  segment, rfm_score, snapshot_built_at
)
SELECT
  c.id,
  COALESCE(o.total_revenue_dollars, 0),
  COALESCE(o.order_count, 0),
  o.last_order_at,
  EXTRACT(DAY FROM now() - c.created_at)::INTEGER,
  CASE
    WHEN o.total_revenue_dollars > 5000 THEN 'whale'
    WHEN o.total_revenue_dollars > 1000 THEN 'core'
    WHEN o.total_revenue_dollars > 0    THEN 'casual'
    ELSE                                     'dormant'
  END,
  -- RFM placeholder; the real scorer lives in analytics-models/python/rfm.py
  'R' || (1 + (c.id % 5))::TEXT
    || 'F' || (1 + (c.id % 5))::TEXT
    || 'M' || (1 + (c.id % 5))::TEXT,
  now()
FROM core.customers c
LEFT JOIN order_agg o  ON o.customer_id = c.id
LEFT JOIN email_agg e  ON e.customer_id = c.id
LEFT JOIN event_agg ev ON ev.customer_id = c.id
WHERE c.deleted_at IS NULL
ON CONFLICT (customer_id) DO UPDATE SET
  total_revenue = EXCLUDED.total_revenue,
  order_count = EXCLUDED.order_count,
  last_order_at = EXCLUDED.last_order_at,
  days_since_signup = EXCLUDED.days_since_signup,
  segment = EXCLUDED.segment,
  rfm_score = EXCLUDED.rfm_score,
  snapshot_built_at = EXCLUDED.snapshot_built_at;
"""


FILES["sql/models/orders_daily_summary.sql"] = """-- orders_daily_summary.sql
-- Owner: core-data@dataclaw.com
-- Built by: ad-hoc; not currently scheduled (planned for Q3 — see roadmap doc)
-- Materialized as: NOT YET (this is a draft for the Q3 'finance_revenue_daily' mart)
--
-- Upstream: core.orders, core.payments, core.refunds
-- Downstream: nothing yet — this is the proposed source for the daily revenue email

SELECT
  date_trunc('day', o.placed_at)::DATE  AS day,
  o.currency,
  count(*)                              AS order_count,
  count(*) FILTER (WHERE o.status = 'fulfilled')  AS fulfilled_count,
  count(*) FILTER (WHERE o.status = 'refunded')   AS refunded_count,
  sum(o.total_cents) / 100.0            AS gross_revenue,
  sum(p.amount_cents) FILTER (WHERE p.status = 'succeeded') / 100.0 AS captured_revenue,
  sum(r.amount_cents) / 100.0           AS refunded_amount,
  (sum(p.amount_cents) FILTER (WHERE p.status = 'succeeded') - COALESCE(sum(r.amount_cents), 0)) / 100.0
                                        AS net_revenue
FROM core.orders o
LEFT JOIN core.payments p ON p.order_id = o.id
LEFT JOIN core.refunds  r ON r.payment_id = p.id
WHERE o.placed_at > now() - interval '90 days'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
"""


FILES["sql/models/cohort_retention.sql"] = """-- cohort_retention.sql
-- Owner: product-analytics@dataclaw.com
-- Built by: cohort_analysis Airflow DAG (Sun 23:00 UTC)
-- Materialized as: derived.cohort_retention
--
-- Upstream: core.customers, events.product_events
-- Definition of 'active': any meaningful event (checkout_started, dashboard_viewed, report_generated)
-- in the week. Changed 2025-Q1 from 'any login event'. See the metrics handbook for migration notes.

WITH cohorts AS (
  SELECT
    id AS customer_id,
    date_trunc('month', created_at)::DATE AS cohort_month
  FROM core.customers
  WHERE deleted_at IS NULL
),
weekly_activity AS (
  SELECT
    user_id,
    date_trunc('week', created_at)::DATE AS week_start
  FROM events.product_events
  WHERE event_type IN ('checkout_started', 'dashboard_viewed', 'report_generated')
  GROUP BY user_id, date_trunc('week', created_at)
),
joined AS (
  SELECT
    c.cohort_month,
    EXTRACT(WEEK FROM age(w.week_start, c.cohort_month))::INTEGER AS weeks_since_signup,
    count(DISTINCT w.user_id) AS active_customers
  FROM cohorts c
  JOIN weekly_activity w ON w.user_id = c.customer_id AND w.week_start >= c.cohort_month
  GROUP BY c.cohort_month, weeks_since_signup
),
cohort_size AS (
  SELECT cohort_month, count(*) AS cohort_size
  FROM cohorts
  GROUP BY cohort_month
)
INSERT INTO derived.cohort_retention (cohort_month, weeks_since_signup, active_customers, retention_pct)
SELECT
  j.cohort_month,
  j.weeks_since_signup,
  j.active_customers,
  (j.active_customers * 100.0 / NULLIF(cs.cohort_size, 0))::NUMERIC(5,2)
FROM joined j
JOIN cohort_size cs USING (cohort_month)
ON CONFLICT (cohort_month, weeks_since_signup) DO UPDATE SET
  active_customers = EXCLUDED.active_customers,
  retention_pct = EXCLUDED.retention_pct;
"""


FILES["sql/models/activation_funnel.sql"] = """-- activation_funnel.sql
-- Owner: product-analytics@dataclaw.com
-- Built by: signup_to_activation_funnel Airflow DAG (daily 05:00 UTC)
-- Materialized as: derived.activation_funnel
--
-- Activated = (queries_in_first_7d >= 3). North Star metric for Growth.
-- If you change the activation definition you MUST update:
--   1. The metrics handbook in Notion
--   2. The Looker dashboard "Growth — Activation Funnel"
--   3. The is_activated() helper in this file

WITH milestones AS (
  SELECT
    user_id,
    min(created_at) FILTER (WHERE event_type IN ('signed_up', 'signup'))           AS signed_up_at,
    min(created_at) FILTER (WHERE event_type = 'verified_email')                   AS verified_email_at,
    min(created_at) FILTER (WHERE event_type = 'created_first_workspace')          AS created_first_workspace_at,
    min(created_at) FILTER (WHERE event_type = 'imported_first_dataset')           AS imported_first_dataset_at,
    min(created_at) FILTER (WHERE event_type = 'ran_first_query')                  AS ran_first_query_at
  FROM events.product_events
  WHERE user_id IS NOT NULL
  GROUP BY user_id
),
queries_first_7d AS (
  SELECT
    user_id,
    count(*) FILTER (
      WHERE event_type = 'ran_first_query'
        AND created_at < (SELECT signed_up_at FROM milestones m WHERE m.user_id = pe.user_id) + interval '7 days'
    ) AS queries_in_first_7d
  FROM events.product_events pe
  GROUP BY user_id
)
INSERT INTO derived.activation_funnel (
  customer_id, signed_up_at, verified_email_at, created_first_workspace_at,
  imported_first_dataset_at, ran_first_query_at, queries_in_first_7d, activated
)
SELECT
  c.id,
  m.signed_up_at,
  m.verified_email_at,
  m.created_first_workspace_at,
  m.imported_first_dataset_at,
  m.ran_first_query_at,
  COALESCE(q.queries_in_first_7d, 0),
  COALESCE(q.queries_in_first_7d, 0) >= 3
FROM core.customers c
LEFT JOIN milestones m       ON m.user_id = c.id
LEFT JOIN queries_first_7d q ON q.user_id = c.id
ON CONFLICT (customer_id) DO UPDATE SET
  signed_up_at = EXCLUDED.signed_up_at,
  verified_email_at = EXCLUDED.verified_email_at,
  created_first_workspace_at = EXCLUDED.created_first_workspace_at,
  imported_first_dataset_at = EXCLUDED.imported_first_dataset_at,
  ran_first_query_at = EXCLUDED.ran_first_query_at,
  queries_in_first_7d = EXCLUDED.queries_in_first_7d,
  activated = EXCLUDED.activated;
"""


FILES["sql/staging/stg_postgres_orders.sql"] = """-- DEPRECATED naming convention. Should have been renamed to stg_postgres__orders
-- in PR #1689 but the rollout stalled. Do not add new single-underscore models.
-- (See dbt Style Guide in Notion.)

CREATE OR REPLACE VIEW staging.stg_postgres_orders AS
SELECT
  id            AS order_id,
  customer_id,
  status,
  total_cents,
  currency,
  discount_id,
  placed_at,
  fulfilled_at,
  refunded_at,
  CASE
    WHEN status = 'fulfilled' THEN 'completed'
    WHEN status = 'refunded'  THEN 'reversed'
    WHEN status = 'canceled'  THEN 'aborted'
    WHEN status = 'pending'   THEN 'in_flight'
    ELSE 'unknown'  -- catches the undocumented 'stuck_in_3ds'
  END AS lifecycle_state
FROM core.orders;
"""


FILES["runbooks/payments_reconciliation.md"] = """# payments_reconciliation runbook

## What it does
Daily reconciliation of `core.payments` against Stripe's `balance_transactions` and `core.refunds`. Writes to `derived.payments_reconciled`.

## Schedule
06:00 UTC daily. Must complete before 08:00 UTC for the daily revenue email.

## Threshold
Hard-fails the DAG if `(unmatched_payments / total_payments) > 0.005` (0.5%).

This is intentional — the daily revenue number is used by finance for cash forecasting and CFO reporting. **Changing this threshold requires CFO sign-off.**

## Common failures

### 1. Stripe API rate limit (HTTP 429)
The pull_stripe step makes ~600 calls (each balance_transaction page is 100 records). Stripe's rate limit is 100 req/sec. Retry with exponential backoff is built in; if it still fails, check Stripe status page.

### 2. Unmatched threshold breach
If the DAG fails on the threshold check, do NOT just unblock. Investigate. Common causes:
- Webhook delivery failure (Stripe retried but our handler dropped events)
- Currency-mismatch in non-USD payments (Stripe reports in original currency, we store USD)
- Manual `core.payments` insert that bypassed the webhook (don't do this — see Stripe webhook docs)

### 3. Refund correlation mismatch
If `refund_offset_cents` is significantly different from sum of `core.refunds` for that payment, check that `core.refunds.payment_id` references the right payment (we had a bug in 2024 where partial-refund webhooks stored the original payment_id instead of the partial-refund payment_id).

## Manual rerun
```bash
airflow dags trigger payments_reconciliation
```

## Escalation
- 1 hour past SLA: page finance-eng oncall
- 2 hours past SLA: page CTO
"""


FILES["runbooks/refund_alerts.md"] = """# refund_alerts runbook

## What it does
Every 15 minutes, checks if the count of refunds in the last 15-min window exceeds 3x the rolling 7-day average for the same window-of-day. Pages PagerDuty if so.

## History
Created after the 2024 fraud incident — a fraud ring opened ~200 trial accounts and refund-charged-back ~$45k before our fraud team noticed. Detection window went from "next morning" to "within 30 min".

## False-positive backpressure
After PG-2025-0117 (Stripe webhook outage causing replay storm), we added a backpressure window: if the previous run paged within the last 15 min, this run only pages if the spike is >5x baseline (instead of 3x).

## Tuning
**Do not lower the threshold without finance + security signoff.**

Current values are in `airflow/dags/refund_alerts.py`. The 7-day baseline is computed inline in the DAG. If you want to recalibrate, run:
```sql
SELECT
  date_trunc('hour', created_at) + (extract(minute from created_at)::INT / 15) * interval '15 minutes' AS bucket,
  count(*) AS refund_count
FROM core.refunds
WHERE created_at > now() - interval '7 days'
GROUP BY 1
ORDER BY 1;
```

## What to do when paged
1. Open `core.refunds` for the last 30 min and look for clustered customers (same email domain, same IP, sequential card BINs)
2. If clustered → fraud. Notify security@dataclaw.com via Slack #security-incidents.
3. If spread across many real customers → escalate to product (likely a bug in checkout)
4. If spread across one campaign → marketing issue (campaign promised something we can't deliver)
"""


FILES[".github/CODEOWNERS"] = """# Per-path owner mapping

# Default owners (any file not matched below)
*                          @dataclaw/data-platform

# Models per domain
/sql/models/customer_360.sql           @dataclaw/analytics-eng
/sql/models/cohort_retention.sql       @dataclaw/product-analytics
/sql/models/activation_funnel.sql      @dataclaw/product-analytics
/sql/models/orders_daily_summary.sql   @dataclaw/finance-eng

# Staging
/sql/staging/                          @dataclaw/data-platform

# Runbooks
/runbooks/payments_reconciliation.md   @dataclaw/finance-eng
/runbooks/refund_alerts.md             @dataclaw/finance-eng @dataclaw/security
"""


FILES["data_quality/expectations/core_orders.json"] = """{
  "$schema": "https://docs.greatexpectations.io/...",
  "expectation_suite_name": "core_orders_checkpoint",
  "tier": "gold",
  "expectations": [
    {"expectation": "expect_column_to_exist",                "kwargs": {"column": "id"}},
    {"expectation": "expect_column_values_to_not_be_null",   "kwargs": {"column": "customer_id"}},
    {"expectation": "expect_column_values_to_be_in_set",     "kwargs": {"column": "status", "value_set": ["pending","paid","fulfilled","refunded","canceled"]}},
    {"expectation": "expect_column_values_to_be_between",    "kwargs": {"column": "total_cents", "min_value": 0, "max_value": 100000000}}
  ],
  "_note": "status value_set is missing 'stuck_in_3ds' — that's why this suite warns weekly. Either add it to the set or fix the upstream that produces it."
}
"""


# =====================================================================
# Main
# =====================================================================

def get_existing_sha(repo: str, path: str) -> str | None:
    resp = github_request("GET", f"/repos/{repo}/contents/{path}")
    if resp is None:
        return None
    return resp.get("sha")


def put_file(repo: str, path: str, content: str, sha: str | None) -> None:
    body = {
        "message": f"Add {path}" if sha is None else f"Update {path}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    github_request("PUT", f"/repos/{repo}/contents/{path}", body)


def main(repo: str) -> None:
    print(f"Seeding repo: {repo}")
    print(f"Files: {len(FILES)}")
    for path, content in FILES.items():
        sha = get_existing_sha(repo, path)
        action = "updating" if sha else "creating"
        print(f"  {action}: {path}")
        put_file(repo, path, content, sha)
        time.sleep(0.5)
    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python seed_repo.py <owner/repo>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
