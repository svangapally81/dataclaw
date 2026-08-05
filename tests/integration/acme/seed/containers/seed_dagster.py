from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def _dagster_base_url() -> str:
    return os.getenv("ACME_DAGSTER_BASE_URL", "http://127.0.0.1:18083").rstrip("/")


def _graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{_dagster_base_url()}/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    if payload.get("errors"):
        raise RuntimeError(f"Dagster GraphQL error: {payload['errors']}")
    return payload


def _repository_context() -> tuple[str, str]:
    payload = _graphql(
        "{ repositoriesOrError { __typename ... on RepositoryConnection { nodes { name location { name } } } } }"
    )
    repositories = payload.get("data", {}).get("repositoriesOrError", {}).get("nodes", [])
    if not repositories:
        raise RuntimeError("Dagster returned no repositories.")
    repository = repositories[0]
    return str(repository["name"]), str(repository["location"]["name"])


def _existing_run_id(job_name: str) -> str | None:
    payload = _graphql(
        "query Runs($limit: Int) { runsOrError(limit: $limit) { __typename ... on Runs { results { runId pipelineName status } } } }",
        {"limit": 25},
    )
    runs = payload.get("data", {}).get("runsOrError", {}).get("results", [])
    for run in runs:
        if run.get("pipelineName") == job_name:
            return str(run["runId"])
    return None


def _launch_run(repository_name: str, location_name: str, job_name: str, partition: str) -> str:
    existing = _existing_run_id(job_name)
    if existing:
        return existing
    payload = _graphql(
        """
        mutation Launch($executionParams: ExecutionParams!) {
          launchPipelineExecution(executionParams: $executionParams) {
            __typename
            ... on LaunchRunSuccess { run { runId status } }
          }
        }
        """,
        {
            "executionParams": {
                "selector": {
                    "repositoryName": repository_name,
                    "repositoryLocationName": location_name,
                    "pipelineName": job_name,
                },
                "runConfigData": {},
                "mode": "default",
                "executionMetadata": {"tags": [{"key": "dagster/partition", "value": partition}]},
            }
        },
    )
    launch = payload.get("data", {}).get("launchPipelineExecution", {})
    run = launch.get("run") if isinstance(launch, dict) else None
    if not isinstance(run, dict) or not run.get("runId"):
        raise RuntimeError(f"Dagster did not launch {job_name}: {launch}")
    return str(run["runId"])


def seed_dagster() -> dict[str, object]:
    job_name = "acme_assets"
    partition = "2026-05-20"
    repository_name, location_name = _repository_context()
    run_id = _launch_run(repository_name, location_name, job_name, partition)
    return {
        "api_url": "http://127.0.0.1:18083",
        "assets": ["customers", "orders"],
        "job_name": job_name,
        "run_id": run_id,
        "sensor": "acme_asset_sensor",
        "schedule": "acme_assets_daily",
        "partition": partition,
        "repository_name": repository_name,
        "repository_location_name": location_name,
    }


__all__ = ["seed_dagster"]
