"""Reference ETL: SQLite source -> aggregate -> JSON sink.

Run after starting the backend or stand-alone for a quick demo.

  uv run python scripts/sample_etl.py
  uv run python scripts/sample_etl.py --source /tmp/dataclaw_demo.sqlite --sink ./out/revenue.json

The script uses the same SQLite seed the in-product connector relies on, so the
output mirrors what the workspace would render after a successful sync.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.connectors.adapters import DEMO_SQLITE_PATH, seed_sqlite_demo


REVENUE_BY_SEGMENT = """
select c.segment,
       count(distinct o.order_id) as order_count,
       round(sum(o.net_revenue), 2) as net_revenue
from orders o
join customers c on c.customer_id = o.customer_id
group by c.segment
order by net_revenue desc
"""


def extract(database_path: Path) -> list[dict]:
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(REVENUE_BY_SEGMENT)
        return [dict(row) for row in cursor.fetchall()]


def transform(rows: list[dict]) -> list[dict]:
    total = sum(row["net_revenue"] for row in rows) or 1
    return [
        {**row, "share_of_revenue": round(row["net_revenue"] / total, 4)}
        for row in rows
    ]


def load(rows: list[dict], sink: Path) -> None:
    sink.parent.mkdir(parents=True, exist_ok=True)
    sink.write_text(json.dumps(rows, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample DataClaw ETL")
    parser.add_argument("--source", type=Path, default=DEMO_SQLITE_PATH)
    parser.add_argument("--sink", type=Path, default=ROOT / "out" / "revenue_by_segment.json")
    args = parser.parse_args()

    if not args.source.exists():
        seed_sqlite_demo(args.source)

    rows = transform(extract(args.source))
    load(rows, args.sink)
    print(f"Wrote {len(rows)} rows to {args.sink}")
    for row in rows:
        print(f"  {row['segment']:<12} ${row['net_revenue']:>12,.2f}  ({row['share_of_revenue']:.0%})")


if __name__ == "__main__":
    main()
