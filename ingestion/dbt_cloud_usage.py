"""dbt Cloud — Admin API / Discovery API (job run history & metrics).

API:  https://{host}/api/v2/accounts/{account_id}/runs/  (run history: status,
      duration, started/finished) and the Discovery API for model-level metadata.
Auth: a service token / PAT; header ``Authorization: Token ...`` (v2) or Bearer.
Env:  DBT_CLOUD_API_TOKEN, DBT_CLOUD_ACCOUNT_ID, DBT_CLOUD_API_HOST (default cloud.getdbt.com)

Maps to unified schema: platform="dbt_cloud", resource=job name, quantity=duration
      seconds or run count, unit="seconds"/"runs", cost=NULL (metric-only source).

STATUS: stub.
"""
from __future__ import annotations

from typing import Any

from .base import IngestionSource, run_standalone
from . import config


class DbtCloudUsage(IngestionSource):
    platform = "dbt_cloud"

    def fetch(self) -> list[dict[str, Any]]:
        creds = config.dbt_cloud_creds()  # noqa: F841
        raise NotImplementedError("dbt_cloud_usage.fetch(): TODO once dbt Cloud token is provided")


if __name__ == "__main__":
    run_standalone(DbtCloudUsage)
