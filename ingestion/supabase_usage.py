"""Supabase — Management API (project usage / analytics).

API:  GET /v1/projects                      → project inventory
      GET /v1/organizations/{slug}          → plan
      GET /v1/projects/{ref}/analytics/endpoints/usage.api-requests-count
                                             → real API request count
Auth: Management API personal access token (sbp_...); Bearer header.
Env:  SUPABASE_ACCESS_TOKEN, SUPABASE_ORG_ID (optional)

Free tier is metric-only, so cost is null (like dbt Cloud). Only the
api-requests-count analytics metric is publicly exposed today; the source is
written so more usage.* metrics can be added to METRICS if/when available.

Maps to unified schema: platform="supabase", project=project name,
      resource=metric, quantity=count, unit, cost=null (+ region/plan/status meta).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests

from .base import IngestionSource, run_standalone
from . import config

API = "https://api.supabase.com/v1"

# metric endpoint name -> (resource label, unit)
METRICS: dict[str, tuple[str, str]] = {
    "usage.api-requests-count": ("api-requests", "requests"),
}


class SupabaseUsage(IngestionSource):
    platform = "supabase"

    def _get(self, path: str, H: dict[str, str]) -> Any:
        r = requests.get(f"{API}{path}", headers=H, timeout=30)
        return r.json() if r.ok else None

    def fetch(self) -> list[dict[str, Any]]:
        token = config.supabase_creds()["access_token"]
        H = {"Authorization": f"Bearer {token}"}
        today = date.today().isoformat()

        projects = self._get("/projects", H) or []
        # cache org plan lookups
        org_plan: dict[str, str] = {}

        rows: list[dict[str, Any]] = []
        for p in projects:
            ref = p.get("ref")
            org_id = p.get("organization_id")
            if org_id and org_id not in org_plan:
                org = self._get(f"/organizations/{org_id}", H) or {}
                org_plan[org_id] = org.get("plan", "unknown")
            plan = org_plan.get(org_id, "unknown")

            for endpoint, (label, unit) in METRICS.items():
                data = self._get(f"/projects/{ref}/analytics/endpoints/{endpoint}", H)
                if not data or not data.get("result"):
                    continue
                count = data["result"][0].get("count")
                rows.append(
                    {
                        "date": today,
                        "project": p.get("name"),
                        "resource": label,
                        "service": "supabase",
                        "region": p.get("region"),
                        "quantity": count,
                        "unit": unit,
                        "cost": None,  # free tier — metric-only
                        "plan": plan,
                        "status": p.get("status"),
                        "pg_version": (p.get("database") or {}).get("version"),
                        "project_ref": ref,
                    }
                )
        return rows


    def fetch_meta(self):
        token = config.supabase_creds()["access_token"]
        H = {"Authorization": f"Bearer {token}"}
        projects = self._get("/projects", H) or []
        if not projects:
            return None
        p = projects[0]
        org = self._get(f"/organizations/{p.get('organization_id')}", H) or {}
        plan = org.get("plan", "free")
        return {
            "plan": plan,
            "is_free": plan == "free",
            "account_created": p.get("created_at"),
            # Supabase Mgmt API doesn't expose a login time; project is the activity unit
            "last_active": None,
            "trial_end": None,   # free tier has no end date (but pauses after ~7d idle)
            "status": p.get("status"),
            "extra": {
                "region": p.get("region"),
                "pg_version": (p.get("database") or {}).get("version"),
                "note": "free projects pause after ~7 days of inactivity",
            },
        }


if __name__ == "__main__":
    run_standalone(SupabaseUsage)
