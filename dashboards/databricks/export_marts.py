"""Export marts (or derived aggregates) to notebook-ready Parquet + CSV.

Produces files under ``data/exports/`` that can be uploaded straight into a
Databricks Free Edition notebook (``spark.read.parquet(...)``) or opened with pandas.
Works whether or not dbt has materialized the marts — falls back to the same
aggregations via the dashboard data layer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

# allow running as a bare script (python dashboards/databricks/export_marts.py)
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ingestion import config

# Published INTO the repo so the deployed Streamlit app (and Databricks) can read
# them without a live DuckDB warehouse. Small aggregates — safe to commit.
EXPORTS = config.settings.root / "dashboards" / "published"

# mart name -> fallback SQL over usage_facts (used if the mart table is absent)
TARGETS: dict[str, str] = {
    "platform_summary": """
        select platform, count(distinct date) active_days, min(date) first_seen,
               max(date) last_seen, sum(cost) total_cost, bool_and(cost is null) is_metric_only
        from usage_facts group by platform
    """,
    "platform_daily": """
        select platform, cast(date as date) as "date", sum(cost) as cost, count(*) as line_items
        from usage_facts group by platform, cast(date as date) order by 2
    """,
    "service_breakdown": """
        select platform, coalesce(nullif(trim(service),''),platform) as service,
               coalesce(nullif(trim(unit),''),'unit') as unit,
               sum(quantity) as quantity, sum(cost) as cost, count(*) as line_items
        from usage_facts group by 1,2,3
    """,
    "cross_platform_daily": """
        select cast(date as date) as "date", sum(cost) as total_cost,
               count(distinct platform) as platforms_reporting
        from usage_facts group by cast(date as date) order by 1
    """,
    # account-level metadata (plan, last active, free-tier/trial end)
    "platform_meta": "select * from platform_meta",
    # application-level breakdown (per platform → per resource/app)
    "application_breakdown": """
        select platform,
               coalesce(nullif(trim(resource),''),'—') as application,
               coalesce(nullif(trim(service),''),platform) as service,
               coalesce(nullif(trim(unit),''),'unit') as unit,
               sum(quantity) as quantity, sum(cost) as cost, count(*) as line_items,
               max(cast(date as date)) as last_seen
        from usage_facts group by 1,2,3,4 order by platform, cost desc nulls last, quantity desc nulls last
    """,
}


def _has_table(con, name: str) -> bool:
    return con.execute(
        "select 1 from information_schema.tables where table_name = ? limit 1", [name]
    ).fetchone() is not None


def main() -> int:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(config.settings.duckdb_path, read_only=True)
    try:
        for name, fallback_sql in TARGETS.items():
            mart = f"mart_{name}"
            source = mart if _has_table(con, mart) else f"({fallback_sql})"
            df = con.execute(f"select * from {source}").fetch_df()
            df.to_parquet(EXPORTS / f"{name}.parquet", index=False)
            df.to_csv(EXPORTS / f"{name}.csv", index=False)
            print(f"exported {name}: {len(df)} rows → {EXPORTS}/{name}.{{parquet,csv}}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
