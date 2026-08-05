from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import respx


@dataclass(frozen=True)
class HttpFixtureRoute:
    connector: str
    method: str
    url: str
    fixture: Path
    status_code: int = 200


def load_http_fixture_manifest(root: Path) -> list[HttpFixtureRoute]:
    payload = json.loads((root / "http_replay_manifest.json").read_text())
    routes: list[HttpFixtureRoute] = []
    for item in payload["routes"]:
        routes.append(
            HttpFixtureRoute(
                connector=item["connector"],
                method=item["method"].upper(),
                url=item["url"],
                fixture=Path(item["fixture"]),
                status_code=int(item.get("status_code", 200)),
            )
        )
    return routes


def register_http_fixtures(router: respx.MockRouter, root: Path) -> list[respx.Route]:
    registered: list[respx.Route] = []
    for route in load_http_fixture_manifest(root):
        payload: dict[str, Any] = json.loads((root / route.fixture).read_text())
        registered.append(
            router.request(route.method, route.url).mock(
                return_value=httpx.Response(route.status_code, json=payload)
            )
        )
    return registered
