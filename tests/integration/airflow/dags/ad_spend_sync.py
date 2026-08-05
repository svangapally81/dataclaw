"""
ad_spend_sync — daily pull of ad-platform spend into marketing.ad_spend_daily.

Owner: marketing-eng@dataclaw.com
SLA: daily 03:00 UTC, completed by 04:00 UTC (must finish before attribution_backfill)
Platforms: Google Ads, Meta Marketing API, LinkedIn Ads, TikTok Ads
Output: marketing.ad_spend_daily (one row per (date, platform, campaign_id))

CAUTION: Meta and LinkedIn restate spend up to 7 days after a click (impression
attribution windows). This DAG does a 7-day rolling backfill; if you change that
window you'll create gaps in attribution_backfill (which assumes 7-day stability).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="ad_spend_sync",
    description="Daily 7-day rolling pull of ad-platform spend",
    start_date=datetime(2025, 1, 1),
    schedule="0 3 * * *",
    catchup=False,
    tags=[
        "owner:marketing-eng",
        "sla:60min",
        "tier:gold",
        "produces:marketing.ad_spend_daily",
        "external:google_ads",
        "external:meta_ads",
        "external:linkedin_ads",
        "external:tiktok_ads",
    ],
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
) as dag:
    google = BashOperator(
        task_id="pull_google_ads",
        bash_command="echo 'gcloud auth ... && curl https://googleads.googleapis.com/v17/...'",
    )
    meta = BashOperator(
        task_id="pull_meta_ads",
        bash_command="echo 'curl https://graph.facebook.com/v18.0/act_${ACCOUNT_ID}/insights?...'",
    )
    linkedin = BashOperator(
        task_id="pull_linkedin_ads",
        bash_command="echo 'curl https://api.linkedin.com/rest/adAnalytics?...'",
    )
    tiktok = BashOperator(
        task_id="pull_tiktok_ads",
        bash_command="echo 'curl https://business-api.tiktok.com/open_api/v1.3/report/...'",
    )
    merge = BashOperator(
        task_id="merge_into_ad_spend_daily",
        bash_command="echo 'INSERT INTO marketing.ad_spend_daily (...) ON CONFLICT (date, platform, campaign_id) DO UPDATE SET spend = EXCLUDED.spend'",
    )
    [google, meta, linkedin, tiktok] >> merge
