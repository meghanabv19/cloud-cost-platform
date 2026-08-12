"""GCP — the primary, most-detailed cost source in this project.

Two free inputs:
  1. BigQuery billing export — full per-service, per-SKU, per-project line items.
     (Standard SQL query against the exported table.)
  2. Cloud Billing API — account/project metadata (always free to call).

This source gets the deepest treatment: per-project, per-service, per-SKU rows so the
marts/dashboards can drill from "spend spiked" → "which SKU caused it".

Env:  GCP_SA_KEY or GOOGLE_APPLICATION_CREDENTIALS,
      GCP_BILLING_BQ_PROJECT, GCP_BILLING_BQ_DATASET, GCP_BILLING_BQ_TABLE,
      GCP_BILLING_ACCOUNT_ID (optional, for metadata)

Maps to unified schema: platform="gcp", project, service, sku, resource=sku desc,
      quantity=usage.amount, unit=usage.unit, cost=cost (+ credits in meta).

STATUS: stub — built out most thoroughly when GCP credentials are provided.
"""
from __future__ import annotations

from typing import Any

from .base import IngestionSource, run_standalone
from . import config


class GcpBilling(IngestionSource):
    platform = "gcp"

    def fetch(self) -> list[dict[str, Any]]:
        creds = config.gcp_creds()  # noqa: F841
        raise NotImplementedError(
            "gcp_billing.fetch(): TODO — BigQuery per-SKU export + Cloud Billing metadata"
        )


if __name__ == "__main__":
    run_standalone(GcpBilling)
