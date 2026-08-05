from __future__ import annotations

import os
from typing import Any

from tests.integration.acme.seed.saas.common import (
    SAAS_ENV,
    env_first,
    missing_env,
    record_action,
    sdk_missing,
    skipped,
)

PAGES = {
    "Q3 OKRs": "Reduce churn by explaining the acme_churn_calc ownership chain and improving revenue freshness.",
    "Data team architecture": (
        "Postgres raw data lands in BigQuery, dbt builds marts, Snowflake serves churn and ARR reporting. "
        "On-call runbook: append deployment notes to this page when a production deployment completes."
    ),
    "Postgres to BigQuery pipeline": "Airflow acme_etl_daily copies raw.orders into BigQuery before dbt builds fct_orders.",
}


def _fixture_seed(space_key: str, reason: str) -> dict[str, Any]:
    return {
        "status": "fixture",
        "api": "fixture",
        "api_reason": reason,
        "space_key": space_key,
        "okr_page_id": "fixture-confluence-okr",
        "architecture_page_id": "fixture-confluence-architecture",
        "pipeline_page_id": "fixture-confluence-pipeline",
        "actions": [],
    }


def seed_confluence() -> dict[str, Any]:
    missing = missing_env(SAAS_ENV["confluence"])
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        from atlassian import Confluence
    except ImportError as exc:
        return sdk_missing("atlassian-python-api", exc)

    space_key = os.environ["CONFLUENCE_SPACE_KEY"]
    confluence = Confluence(
        url=os.environ["CONFLUENCE_SITE_URL"],
        username=os.environ["CONFLUENCE_EMAIL"],
        password=env_first("CONFLUENCE_API_TOKEN", "CONFLUENCE_API_BASIC_AUTH_TOKEN", "CONFLUENCE_API_OAUTH_TOKEN"),
        cloud=True,
    )
    try:
        if not confluence.get_space(space_key):
            confluence.create_space(space_key, "Acme Co Release Gate")
    except Exception as exc:
        return _fixture_seed(
            space_key,
            f"Confluence space {space_key!r} is not available and could not be created: {exc}",
        )
    actions: list[dict[str, str]] = []
    seeded: dict[str, Any] = {"status": "seeded", "space_key": space_key, "actions": actions}
    key_by_title = {
        "Q3 OKRs": "okr_page_id",
        "Data team architecture": "architecture_page_id",
        "Postgres to BigQuery pipeline": "pipeline_page_id",
    }
    for title, body in PAGES.items():
        existing = confluence.get_page_by_title(space_key, title)
        html = f"<h1>{title}</h1><p>{body}</p>"
        if existing and existing.get("id"):
            page_id = existing["id"]
            confluence.update_page(page_id, title, html, representation="storage")
            record_action(actions, "confluence", title, "exists")
        else:
            created = confluence.create_page(space_key, title, html, representation="storage")
            page_id = created["id"]
            record_action(actions, "confluence", title, "created")
        seeded[key_by_title[title]] = page_id
    return seeded


__all__ = ["seed_confluence"]
