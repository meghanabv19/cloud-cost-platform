"""Claude (Anthropic) — Admin API Usage & Cost endpoints.

API:  GET /v1/organizations/cost_report            → $ cost, grouped by day
      GET /v1/organizations/usage_report/messages   → token usage, grouped by day
Auth: an **Admin** API key (sk-ant-admin...), headers x-api-key + anthropic-version.
      A regular sk-ant-api... key is rejected (401) — these are org-admin endpoints.
Env:  ANTHROPIC_ADMIN_KEY

Reading these reports is free (no per-request charge). This source is fully
implemented but stays dormant until an admin key is available; with a regular key
it raises a clear, catchable error so the daily pipeline can skip it.

Maps to unified schema: platform="claude",
  - cost_report → cost=amount, resource=description, unit="usd"
  - usage_report → quantity=tokens, unit="tokens", resource=model, cost=null
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .base import IngestionSource, run_standalone
from . import config

BASE = "https://api.anthropic.com/v1/organizations"


class ClaudeUsage(IngestionSource):
    platform = "claude"

    def _headers(self) -> dict[str, str]:
        key = config.claude_creds()["admin_key"]
        if not key.startswith("sk-ant-admin"):
            raise RuntimeError(
                "ANTHROPIC_ADMIN_KEY is not an Admin key (needs sk-ant-admin...). "
                "The Usage/Cost API requires an org Admin key; a regular sk-ant-api key "
                "is rejected. Source will be skipped until an admin key is provided."
            )
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}

    def _paged(self, url: str, params: dict[str, Any], H: dict[str, str]) -> list[dict]:
        out: list[dict] = []
        while True:
            r = requests.get(url, headers=H, params=params, timeout=45)
            r.raise_for_status()
            body = r.json()
            out.extend(body.get("data", []))
            if body.get("has_more") and body.get("next_page"):
                params = {**params, "page": body["next_page"]}
            else:
                break
        return out

    def fetch(self) -> list[dict[str, Any]]:
        H = self._headers()
        start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
        rows: list[dict[str, Any]] = []

        # ---- Cost report ($ spend, per day, per description) ----
        for bucket in self._paged(
            f"{BASE}/cost_report",
            {"starting_at": start, "group_by[]": "description"},
            H,
        ):
            day = (bucket.get("starting_at") or start)[:10]
            for item in bucket.get("results", []):
                amount = item.get("amount")
                if amount is None and isinstance(item.get("cost"), dict):
                    amount = item["cost"].get("amount")
                rows.append(
                    {
                        "date": day,
                        "resource": item.get("description") or item.get("service_type") or "cost",
                        "service": item.get("service_type"),
                        "quantity": amount,
                        "unit": "usd",
                        "cost": amount,
                        "currency": item.get("currency", "USD"),
                    }
                )

        # ---- Usage report (tokens, per day, per model) ----
        for bucket in self._paged(
            f"{BASE}/usage_report/messages",
            {"starting_at": start, "group_by[]": "model"},
            H,
        ):
            day = (bucket.get("starting_at") or start)[:10]
            for item in bucket.get("results", []):
                tokens = (item.get("uncached_input_tokens", 0) or 0) + (item.get("output_tokens", 0) or 0)
                rows.append(
                    {
                        "date": day,
                        "resource": item.get("model") or "messages",
                        "service": "messages",
                        "quantity": tokens,
                        "unit": "tokens",
                        "cost": None,  # dollars come from the cost report
                        "input_tokens": item.get("uncached_input_tokens"),
                        "output_tokens": item.get("output_tokens"),
                    }
                )
        return rows


if __name__ == "__main__":
    run_standalone(ClaudeUsage)
