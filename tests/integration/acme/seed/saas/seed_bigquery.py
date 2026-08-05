from __future__ import annotations

import json
import os
from typing import Any

from tests.integration.acme.seed.saas.common import SAAS_ENV, missing_env, sdk_missing, skipped


def seed_bigquery() -> dict[str, Any]:
    missing = missing_env(SAAS_ENV["bigquery"])
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        return sdk_missing("google-cloud-bigquery", exc)

    project_id = os.environ["BIGQUERY_PROJECT_ID"]
    info = json.loads(os.environ["BIGQUERY_SERVICE_ACCOUNT_JSON"])
    client = bigquery.Client(
        project=project_id,
        credentials=service_account.Credentials.from_service_account_info(info),
    )
    dataset_id = "acme_analytics"
    dataset_ref = f"{project_id}.{dataset_id}"
    client.create_dataset(bigquery.Dataset(dataset_ref), exists_ok=True)
    queries = [
        f"""
        create or replace table `{dataset_ref}.dim_customers` as
        select
          n as cust_id,
          case mod(n, 3) when 0 then 'enterprise' when 1 then 'growth' else 'self_serve' end as segment,
          timestamp_sub(current_timestamp(), interval if(n <= 100, 30, mod(n, 7)) day) as last_modified
        from unnest(generate_array(1, 1000)) as n
        """,
        f"""
        create or replace table `{dataset_ref}.fct_orders` as
        select
          n as order_id,
          1 + mod(n * 13, 1000) as cust_id,
          cast(100 + mod(n * 17, 5000) as numeric) as arr_usd
        from unnest(generate_array(1, 5000)) as n
        """,
    ]
    for query in queries:
        client.query(query).result()
    return {"status": "seeded", "project": project_id, "dataset": dataset_id, "tables": ["dim_customers", "fct_orders"]}


__all__ = ["seed_bigquery"]
