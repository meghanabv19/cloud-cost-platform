"""GitHub — enhanced billing usage API (Actions minutes, Codespaces, storage, ...).

API:  GET /users/{user}/settings/billing/usage   (or /organizations/{org}/... )
      Returns {"usageItems": [ {date, product, sku, quantity, unitType,
      pricePerUnit, grossAmount, discountAmount, netAmount, repositoryName}, ...]}
      (The classic /billing/actions|shared-storage endpoints are now 410 Gone.)
Auth: fine-grained PAT with "Plan" read; header Authorization: Bearer.
Env:  GH_BILLING_TOKEN (or GITHUB_TOKEN), GITHUB_USERNAME or GITHUB_ORG

Maps to unified schema: platform="github", service=product, sku=sku,
      resource=repositoryName, quantity, unit=unitType, cost=netAmount
      (gross/discount/pricePerUnit kept in meta).
"""
from __future__ import annotations

from typing import Any

import requests

from .base import IngestionSource, run_standalone
from . import config

API = "https://api.github.com"


class GithubUsage(IngestionSource):
    platform = "github"

    def fetch(self) -> list[dict[str, Any]]:
        creds = config.github_creds()
        token = creds["token"]
        if creds.get("org"):
            path = f"/organizations/{creds['org']}/settings/billing/usage"
        else:
            path = f"/users/{creds['username']}/settings/billing/usage"

        resp = requests.get(
            f"{API}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "cloud-cost-platform",
            },
            timeout=45,
        )
        resp.raise_for_status()
        items = resp.json().get("usageItems", [])

        rows: list[dict[str, Any]] = []
        for it in items:
            rows.append(
                {
                    "date": it.get("date"),
                    "service": it.get("product"),
                    "sku": it.get("sku"),
                    "resource": it.get("repositoryName") or it.get("product"),
                    "quantity": it.get("quantity"),
                    "unit": it.get("unitType"),
                    # netAmount = what you actually pay after free-tier discounts
                    "cost": it.get("netAmount"),
                    "currency": "USD",
                    # keep the full economics for drill-down / reconciliation
                    "gross_amount": it.get("grossAmount"),
                    "discount_amount": it.get("discountAmount"),
                    "price_per_unit": it.get("pricePerUnit"),
                }
            )
        return rows


    def fetch_meta(self):
        creds = config.github_creds()
        H = {
            "Authorization": f"Bearer {creds['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cloud-cost-platform",
        }
        user = requests.get(f"{API}/user", headers=H, timeout=30).json()
        plan = (user.get("plan") or {}).get("name")
        # "last active" ≈ most recent push across repos (GitHub doesn't expose login)
        repos = requests.get(
            f"{API}/user/repos?sort=pushed&per_page=1", headers=H, timeout=30
        ).json()
        last_active = repos[0]["pushed_at"] if isinstance(repos, list) and repos else user.get("updated_at")
        last_repo = repos[0]["name"] if isinstance(repos, list) and repos else None
        return {
            "plan": plan,
            "is_free": plan == "free",
            "account_created": user.get("created_at"),
            "last_active": last_active,
            "trial_end": None,          # GitHub Free has no end date
            "status": "active",
            "extra": {"last_active_repo": last_repo, "storage_bytes": (user.get("plan") or {}).get("space")},
        }


if __name__ == "__main__":
    run_standalone(GithubUsage)
