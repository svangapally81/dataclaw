#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DATACLAW_GITHUB_SECRETS_FILE:-$ROOT/secrets/github-actions.env}"
REPO="${DATACLAW_GITHUB_REPO:-}"
CHECK_ONLY=0

usage() {
  cat <<'EOF'
Usage:
  scripts/set_github_secrets.sh --init-template
  scripts/set_github_secrets.sh --check [--repo owner/name]
  scripts/set_github_secrets.sh [--repo owner/name]

Loads GitHub Actions secrets from an ignored local env file and uploads them
with `gh secret set`. The template intentionally contains placeholders only.
Use --check to verify that required Acme live-run secret names exist in GitHub;
it never reads or prints secret values. If NOTION_TEST_PARENT_PAGE_ID is unset,
the Notion seeder discovers a shared page titled NOTION_TEST_PARENT_PAGE_TITLE
(default: Private). GITHUB_TEST_REPO, CONFLUENCE_SPACE_KEY, and
SNOWFLAKE_WAREHOUSE are optional; the rig defaults to creating/using
dataclaw-acme-dbt, ACME, and COMPUTE_WH.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--init-template" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  if [[ -e "$ENV_FILE" ]]; then
    echo "$ENV_FILE already exists; refusing to overwrite it."
    exit 1
  fi
  cat >"$ENV_FILE" <<'EOF'
# GitHub Actions secrets for the DataClaw Acme release gate.
# This file is gitignored. Paste rotated, test-only values here.

OPENAI_API_KEY=

NOTION_INTEGRATION_TOKEN=
NOTION_TEST_PARENT_PAGE_ID=
NOTION_TEST_PARENT_PAGE_TITLE=Private
NOTION_TEST_DATABASE_IDS=

GH_TEST_TOKEN=
GITHUB_TEST_TOKEN=
GITHUB_TEST_REPO=
ACME_GITHUB_REPO_NAME=dataclaw-acme-dbt

CONFLUENCE_SITE_URL=
CONFLUENCE_EMAIL=
CONFLUENCE_API_TOKEN=
CONFLUENCE_API_BASIC_AUTH_TOKEN=
CONFLUENCE_API_OAUTH_TOKEN=
CONFLUENCE_SPACE_KEY=ACME

FIVETRAN_API_KEY=
FIVETRAN_API_SECRET=
FIVETRAN_CONNECTOR_ID=

BIGQUERY_SERVICE_ACCOUNT_JSON=
BIGQUERY_PROJECT_ID=

DATABRICKS_WORKSPACE_URL=
DATABRICKS_HOST=
DATABRICKS_HTTP_PATH=
DATABRICKS_TOKEN=

SNOWFLAKE_ACCOUNT=
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=ACME
SNOWFLAKE_SCHEMA=MARTS
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_PRIVATE_KEY=
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=

REDSHIFT_CLUSTER_ENDPOINT=
REDSHIFT_ENDPOINT=
REDSHIFT_DATABASE=
REDSHIFT_USER=
REDSHIFT_PASSWORD=
EOF
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE"
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ONLY=1
      shift
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required. Install GitHub CLI and run gh auth login." >&2
  exit 1
fi

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi
if [[ -z "$REPO" ]]; then
  echo "Could not detect GitHub repo. Pass --repo owner/name." >&2
  exit 1
fi

check_secrets() {
  local existing
  existing="$(gh secret list --app actions --repo "$REPO" | awk '{print $1}' | sort -u)"

  local missing=()
  require_secret() {
    local name="$1"
    if ! grep -qx "$name" <<<"$existing"; then
      missing+=("$name")
    fi
  }
  require_one_of() {
    local label="$1"
    shift
    local name
    for name in "$@"; do
      if grep -qx "$name" <<<"$existing"; then
        return 0
      fi
    done
    missing+=("$label")
  }

  require_secret OPENAI_API_KEY
  require_secret NOTION_INTEGRATION_TOKEN
  require_secret BIGQUERY_SERVICE_ACCOUNT_JSON
  require_secret BIGQUERY_PROJECT_ID
  require_secret SNOWFLAKE_ACCOUNT
  require_secret SNOWFLAKE_USER
  require_one_of "SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY" SNOWFLAKE_PASSWORD SNOWFLAKE_PRIVATE_KEY
  require_one_of "DATABRICKS_WORKSPACE_URL or DATABRICKS_HOST" DATABRICKS_WORKSPACE_URL DATABRICKS_HOST
  require_secret DATABRICKS_HTTP_PATH
  require_secret DATABRICKS_TOKEN
  require_one_of "REDSHIFT_CLUSTER_ENDPOINT or REDSHIFT_ENDPOINT" REDSHIFT_CLUSTER_ENDPOINT REDSHIFT_ENDPOINT
  require_secret REDSHIFT_USER
  require_secret REDSHIFT_PASSWORD
  require_secret FIVETRAN_API_KEY
  require_secret FIVETRAN_API_SECRET
  require_one_of "GITHUB_TEST_TOKEN or GH_TEST_TOKEN" GITHUB_TEST_TOKEN GH_TEST_TOKEN
  require_secret CONFLUENCE_SITE_URL
  require_secret CONFLUENCE_EMAIL
  require_one_of "CONFLUENCE_API_TOKEN or CONFLUENCE_API_BASIC_AUTH_TOKEN or CONFLUENCE_API_OAUTH_TOKEN" \
    CONFLUENCE_API_TOKEN CONFLUENCE_API_BASIC_AUTH_TOKEN CONFLUENCE_API_OAUTH_TOKEN

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "Missing required GitHub Actions secrets for $REPO:"
    printf -- '- %s\n' "${missing[@]}"
    return 1
  fi
  echo "Required Acme secret names exist for $REPO."
}

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  check_secrets
  exit $?
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  echo "Run: scripts/set_github_secrets.sh --init-template"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

set_secret() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    echo "skip $name (empty)"
    return 0
  fi
  printf '%s' "$value" | gh secret set "$name" --repo "$REPO"
}

echo "Uploading GitHub Actions secrets to $REPO from $ENV_FILE"

for name in \
  OPENAI_API_KEY \
  NOTION_INTEGRATION_TOKEN NOTION_TEST_PARENT_PAGE_ID NOTION_TEST_PARENT_PAGE_TITLE NOTION_TEST_DATABASE_IDS \
  GH_TEST_TOKEN GITHUB_TEST_TOKEN GITHUB_TEST_REPO ACME_GITHUB_REPO_NAME \
  CONFLUENCE_SITE_URL CONFLUENCE_EMAIL CONFLUENCE_API_TOKEN CONFLUENCE_API_BASIC_AUTH_TOKEN CONFLUENCE_API_OAUTH_TOKEN CONFLUENCE_SPACE_KEY \
  FIVETRAN_API_KEY FIVETRAN_API_SECRET FIVETRAN_CONNECTOR_ID \
  BIGQUERY_SERVICE_ACCOUNT_JSON BIGQUERY_PROJECT_ID \
  DATABRICKS_WORKSPACE_URL DATABRICKS_HOST DATABRICKS_HTTP_PATH DATABRICKS_TOKEN \
  SNOWFLAKE_ACCOUNT SNOWFLAKE_WAREHOUSE SNOWFLAKE_DATABASE SNOWFLAKE_SCHEMA SNOWFLAKE_USER SNOWFLAKE_PASSWORD SNOWFLAKE_PRIVATE_KEY SNOWFLAKE_PRIVATE_KEY_PASSPHRASE \
  REDSHIFT_CLUSTER_ENDPOINT REDSHIFT_ENDPOINT REDSHIFT_DATABASE REDSHIFT_USER REDSHIFT_PASSWORD
do
  set_secret "$name"
done

echo "Done."
