"""DuckDB — the platform monitoring its own warehouse (self-usage).

DuckDB is the embedded storage engine (no external API, no cost). This source
reports the warehouse's own resource usage by querying it directly: total fact
rows, table count, and the on-disk file size. Real, programmatic, no manual data —
it just points the collector at itself.

Env:  DUCKDB_PATH (shared with the rest of the platform)

Maps to unified schema: platform="duckdb", resource="warehouse",
      quantity=rows / tables / MB, unit accordingly, cost=null (local & free).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .base import IngestionSource, run_standalone
from . import config


class DuckdbUsage(IngestionSource):
    platform = "duckdb"

    def fetch(self) -> list[dict[str, Any]]:
        path = Path(config.settings.duckdb_path)
        today = date.today().isoformat()
        rows: list[dict[str, Any]] = []

        size_mb = round(path.stat().st_size / (1024 * 1024), 4) if path.exists() else 0.0
        rows.append({"date": today, "resource": "warehouse", "service": "storage",
                     "quantity": size_mb, "unit": "MB", "cost": None})

        # reuse the runner's open connection when present (avoids a second file lock);
        # only open our own if running fully standalone with no shared connection.
        con = getattr(self, "_con", None)
        own = con is None
        if con is None and path.exists():
            con = duckdb.connect(str(path), read_only=True)
        if con is not None:
            try:
                n_tables = con.execute(
                    "select count(*) from information_schema.tables where table_schema='main'"
                ).fetchone()[0]
                rows.append({"date": today, "resource": "warehouse", "service": "storage",
                             "quantity": n_tables, "unit": "tables", "cost": None})
                has_facts = con.execute(
                    "select 1 from information_schema.tables where table_name='usage_facts'"
                ).fetchone()
                if has_facts:
                    n_rows = con.execute("select count(*) from usage_facts").fetchone()[0]
                    rows.append({"date": today, "resource": "usage_facts", "service": "storage",
                                 "quantity": n_rows, "unit": "rows", "cost": None})
            finally:
                if own:
                    con.close()
        return rows

    def fetch_meta(self) -> dict[str, Any]:
        return {
            "plan": "embedded",
            "is_free": True,
            "account_created": None,
            "last_active": datetime.now(timezone.utc).isoformat(),
            "trial_end": None,          # local & free — no end date
            "status": "local",
            "extra": {"engine": f"duckdb {duckdb.__version__}", "path": config.settings.duckdb_path},
        }


if __name__ == "__main__":
    run_standalone(DuckdbUsage)
