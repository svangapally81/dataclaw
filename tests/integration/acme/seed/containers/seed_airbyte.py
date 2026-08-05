from __future__ import annotations

import os


def seed_airbyte() -> dict[str, str]:
    return {
        "api_url": os.getenv("DATACLAW_AIRBYTE_API_URL", "http://127.0.0.1:18084"),
        "workspace_id": os.getenv("ACME_AIRBYTE_WORKSPACE_ID", "airbyte-workspace"),
        "connection_id": os.getenv("ACME_AIRBYTE_CONNECTION_ID", "orders-to-warehouse"),
        "source_id": os.getenv("ACME_AIRBYTE_SOURCE_ID", "acme-postgres-source"),
        "destination_id": os.getenv("ACME_AIRBYTE_DESTINATION_ID", "acme-bq-destination"),
        "job_id": os.getenv("ACME_AIRBYTE_JOB_ID", "1"),
    }


__all__ = ["seed_airbyte"]
