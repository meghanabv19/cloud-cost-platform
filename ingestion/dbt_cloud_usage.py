"""dbt Cloud — Admin API v2 (job run history: duration & success).

API:  GET https://{host}/api/v2/accounts/{account_id}/runs/   (paginated)
      GET https://{host}/api/v2/accounts/{account_id}/jobs/    (id → name map)
Auth: ``Authorization: Token <token>`` (v2). NOTE: newer accounts live on a
      REGIONAL host (e.g. jn529.us1.dbt.com), NOT cloud.getdbt.com — set
      DBT_CLOUD_API_HOST to your account's Access URL host.
Env:  DBT_CLOUD_API_TOKEN, DBT_CLOUD_ACCOUNT_ID, DBT_CLOUD_API_HOST

Metric-only source (cost=null): one row per run with run duration + success.

Maps to unified schema: platform="dbt_cloud", resource=job name,
      quantity=run_duration seconds, unit="seconds", cost=null
      (status/success/run_id in meta).
"""
from __future__ import annotations

from typing import Any

import requests

from .base import IngestionSource, run_standalone
from . import config


class DbtCloudUsage(IngestionSource):
    platform = "dbt_cloud"

    def fetch(self) -> list[dict[str, Any]]:
        creds = config.dbt_cloud_creds()
        host = creds["host"]
        acct = creds["account_id"]
        H = {"Authorization": f"Token {creds['token']}", "Accept": "application/json"}
        base = f"https://{host}/api/v2/accounts/{acct}"

        # job id -> name map (best-effort)
        jobs: dict[int, str] = {}
        jr = requests.get(f"{base}/jobs/", headers=H, params={"limit": 100}, timeout=30)
        if jr.ok:
            for j in jr.json().get("data", []):
                jobs[j.get("id")] = j.get("name")

        # paginate runs
        rows: list[dict[str, Any]] = []
        offset, limit = 0, 100
        while True:
            r = requests.get(
                f"{base}/runs/",
                headers=H,
                params={"limit": limit, "offset": offset, "order_by": "-finished_at"},
                timeout=45,
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                break
            for run in data:
                dur = run.get("run_duration") or run.get("duration")  # may be "HH:MM:SS" or seconds
                seconds = _to_seconds(dur)
                day = (run.get("finished_at") or run.get("created_at") or "")[:10] or None
                rows.append(
                    {
                        "date": day,
                        "resource": jobs.get(run.get("job_id"), f"job {run.get('job_id')}"),
                        "service": "dbt_cloud_job",
                        "quantity": seconds,
                        "unit": "seconds",
                        "cost": None,  # metric-only source
                        "run_id": run.get("id"),
                        "status": run.get("status_humanized"),
                        "is_success": run.get("is_success"),
                        "is_error": run.get("is_error"),
                    }
                )
            if len(data) < limit:
                break
            offset += limit
        return rows


def _to_seconds(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip()
    if ":" in text:  # "HH:MM:SS"
        parts = [float(p) for p in text.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        h, m, s = parts[-3:]
        return h * 3600 + m * 60 + s
    try:
        return float(text)
    except ValueError:
        return None


if __name__ == "__main__":
    run_standalone(DbtCloudUsage)
