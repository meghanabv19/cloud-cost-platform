"""Vercel — billing/usage API (FOCUS v1.3), with a graceful free-tier fallback.

API:  GET /v1/billing/charges?from=&to=[&teamId=]   → FOCUS-formatted cost rows
      (paid plans only; hobby returns 404 "costs_not_found").
      GET /v2/user            → plan + currency
      GET /v9/projects        → project inventory (works on hobby)
Auth: Bearer access token; optional ?teamId= for team scope.
Env:  VERCEL_TOKEN, VERCEL_TEAM_ID (optional)

Maps to unified schema:
  - paid:  platform="vercel", service=ServiceName, resource=ChargeDescription,
           quantity, unit, cost=BilledCost
  - free:  one truthful snapshot row — resource="account", service="plan:<plan>",
           quantity=<#projects>, unit="projects", cost=0 (API-derived, not manual).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests

from .base import IngestionSource, run_standalone
from . import config

API = "https://api.vercel.com"


class VercelUsage(IngestionSource):
    platform = "vercel"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.vercel_creds()['token']}"}

    def _team_param(self) -> dict[str, str]:
        creds = config.vercel_creds()
        team = creds.get("team_id")
        if not team:  # fall back to the account's default team (northstar accounts)
            u = requests.get(f"{API}/v2/user", headers=self._headers(), timeout=30)
            if u.ok:
                team = (u.json().get("user") or {}).get("defaultTeamId")
        return {"teamId": team} if team else {}

    def fetch(self) -> list[dict[str, Any]]:
        H = self._headers()
        params = self._team_param()

        # 1) Try real FOCUS billing charges (paid plans).
        frm = date.today().replace(day=1).isoformat()
        to = date.today().isoformat()
        charges = requests.get(
            f"{API}/v1/billing/charges",
            headers=H,
            params={**params, "from": frm, "to": to},
            timeout=45,
        )
        if charges.ok:
            rows: list[dict[str, Any]] = []
            data = charges.json()
            for c in data.get("charges", data if isinstance(data, list) else []):
                rows.append(
                    {
                        "date": c.get("ChargePeriodStart") or c.get("date") or to,
                        "service": c.get("ServiceName") or c.get("service"),
                        "resource": c.get("ChargeDescription") or c.get("resourceName"),
                        "sku": c.get("SkuId"),
                        "region": c.get("RegionId"),
                        "quantity": c.get("PricingQuantity") or c.get("ConsumedQuantity"),
                        "unit": c.get("PricingUnit") or c.get("ConsumedUnit"),
                        "cost": c.get("BilledCost"),
                        "currency": c.get("BillingCurrency") or "USD",
                    }
                )
            if rows:
                return rows

        # 2) Free/hobby fallback: capture a truthful, API-derived snapshot.
        user = requests.get(f"{API}/v2/user", headers=H, timeout=30).json().get("user", {})
        plan = (user.get("billing") or {}).get("plan", "unknown")
        currency = (user.get("billing") or {}).get("currency", "usd").upper()
        projects = requests.get(f"{API}/v9/projects", headers=H, params=params, timeout=30)
        n_projects = len(projects.json().get("projects", [])) if projects.ok else None
        return [
            {
                "date": to,
                "resource": "account",
                "service": f"plan:{plan}",
                "quantity": n_projects,
                "unit": "projects",
                "cost": 0.0,
                "currency": currency,
                "plan": plan,
                "note": "hobby plan — no billable charges via API",
            }
        ]


    def fetch_meta(self):
        H = self._headers()
        params = self._team_param()
        user = requests.get(f"{API}/v2/user", headers=H, timeout=30).json().get("user", {})
        billing = user.get("billing") or {}
        plan = billing.get("plan")
        trial = billing.get("trial") or {}
        # last activity ≈ most recent deployment
        deps = requests.get(
            f"{API}/v6/deployments", headers=H, params={**params, "limit": 1}, timeout=30
        )
        last_active = None
        last_name = None
        if deps.ok:
            d = deps.json().get("deployments", [])
            if d:
                last_active = d[0].get("createdAt")  # unix ms
                last_name = d[0].get("name")
        return {
            "plan": plan,
            "is_free": plan == "hobby",
            "account_created": user.get("createdAt"),   # unix ms
            "last_active": last_active,
            "trial_end": trial.get("end"),              # null on hobby (free forever)
            "status": billing.get("status"),
            "extra": {"last_deployment": last_name},
        }


if __name__ == "__main__":
    run_standalone(VercelUsage)
