from __future__ import annotations

SEEDED_ORG = "dataclaw-test"
SEEDED_REPOS = {
    "data-warehouse": {
        "pull_requests": ["Fix customer 360 freshness", "Document payments reconciliation"],
        "issues": ["Backfill customer segments", "Retire legacy attribution table", "Investigate 3DS status"],
    },
    "analytics": {
        "files": ["notebooks/revenue_quality.ipynb", "notebooks/customer_ltv.ipynb"],
    },
}


def main() -> int:
    print(f"Seed Gitea org {SEEDED_ORG} with repos: {', '.join(SEEDED_REPOS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
