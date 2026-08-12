"""Dashboard data layer.

Prefers the dbt marts (``mart_*``) when they exist; otherwise derives the exact
same aggregations directly from ``usage_facts``. This means the Streamlit app works
immediately after ingestion (before dbt has run locally) AND uses the governed marts
in production — identical shapes either way.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

# resolve the warehouse path the same way the ingestion side does
_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("DUCKDB_PATH", str(_ROOT / "data" / "warehouse.duckdb"))

# committed mart Parquet files — the data source when there's no live warehouse
# (e.g. on Streamlit Community Cloud). Written by dashboards/databricks/export_marts.py.
PUBLISHED = Path(__file__).resolve().parent / "published"


def _live_warehouse() -> bool:
    """True when a DuckDB warehouse with usage_facts exists (local/dev)."""
    if not Path(DB_PATH).exists():
        return False
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return _has_table(con, "usage_facts")
    finally:
        con.close()


def _published(name: str) -> pd.DataFrame:
    """Read a committed mart parquet (deployed/no-warehouse path)."""
    f = PUBLISHED / f"{name}.parquet"
    if not f.exists():
        return pd.DataFrame()
    con = duckdb.connect()  # in-memory; DuckDB reads parquet natively
    try:
        return con.execute(f"select * from read_parquet('{f.as_posix()}')").fetch_df()
    finally:
        con.close()


def _con() -> duckdb.DuckDBPyConnection:
    # read-only so the dashboard can never mutate the warehouse
    return duckdb.connect(DB_PATH, read_only=True)


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    q = "select 1 from information_schema.tables where table_name = ? limit 1"
    return con.execute(q, [name]).fetchone() is not None


def _q(sql: str, params: list | None = None) -> pd.DataFrame:
    con = _con()
    try:
        return con.execute(sql, params or []).fetch_df()
    finally:
        con.close()


# ---- headline / summary --------------------------------------------------------
def platform_summary() -> pd.DataFrame:
    if not _live_warehouse():
        return _published("platform_summary")
    con = _con()
    try:
        if _has_table(con, "mart_platform_summary"):
            return con.execute("select * from mart_platform_summary").fetch_df()
        return con.execute(
            """
            select platform,
                   count(distinct date)      as active_days,
                   min(date)                 as first_seen,
                   max(date)                 as last_seen,
                   sum(cost)                 as total_cost,
                   bool_and(cost is null)    as is_metric_only,
                   max(currency)             as currency
            from usage_facts
            group by platform
            order by total_cost desc nulls last, platform
            """
        ).fetch_df()
    finally:
        con.close()


def cross_platform_daily() -> pd.DataFrame:
    if not _live_warehouse():
        return _published("cross_platform_daily")
    con = _con()
    try:
        if _has_table(con, "mart_cross_platform_daily"):
            return con.execute("select * from mart_cross_platform_daily order by date").fetch_df()
        return con.execute(
            """
            select date,
                   date_trunc('month', date) as month,
                   sum(cost)                 as total_cost,
                   count(distinct platform)  as platforms_reporting,
                   max(currency)             as currency
            from usage_facts
            group by date
            order by date
            """
        ).fetch_df()
    finally:
        con.close()


# ---- per-platform detail -------------------------------------------------------
def platform_daily(platform: str) -> pd.DataFrame:
    if not _live_warehouse():
        df = _published("platform_daily")
        return df[df["platform"] == platform] if not df.empty else df
    con = _con()
    try:
        if _has_table(con, "mart_platform_daily"):
            return con.execute(
                "select * from mart_platform_daily where platform = ? order by date", [platform]
            ).fetch_df()
        return con.execute(
            """
            select platform, date, date_trunc('month', date) as month,
                   sum(cost) as cost, count(*) as line_items, max(currency) as currency
            from usage_facts where platform = ?
            group by platform, date
            order by date
            """,
            [platform],
        ).fetch_df()
    finally:
        con.close()


def service_breakdown(platform: str) -> pd.DataFrame:
    if not _live_warehouse():
        df = _published("service_breakdown")
        return df[df["platform"] == platform] if not df.empty else df
    con = _con()
    try:
        if _has_table(con, "mart_service_breakdown"):
            return con.execute(
                "select * from mart_service_breakdown where platform = ? "
                "order by cost desc nulls last, quantity desc nulls last",
                [platform],
            ).fetch_df()
        return con.execute(
            """
            select platform,
                   coalesce(nullif(trim(service),''), platform) as service,
                   coalesce(nullif(trim(unit),''), 'unit')      as unit,
                   sum(quantity) as quantity, sum(cost) as cost, count(*) as line_items,
                   min(date) as first_seen, max(date) as last_seen
            from usage_facts where platform = ?
            group by 1,2,3
            order by cost desc nulls last, quantity desc nulls last
            """,
            [platform],
        ).fetch_df()
    finally:
        con.close()


def usage_across_platforms() -> pd.DataFrame:
    """Full per-platform/service/unit usage (all platforms) — the resource view.

    Units differ across platforms (minutes, hours, requests, GB, projects, seconds),
    so this is intentionally NOT summed into one number — it's grouped for comparison.
    """
    if not _live_warehouse():
        df = _published("service_breakdown")
        return df.sort_values(["platform", "quantity"], ascending=[True, False]) if not df.empty else df
    con = _con()
    try:
        if _has_table(con, "mart_service_breakdown"):
            return con.execute(
                "select * from mart_service_breakdown order by platform, quantity desc nulls last"
            ).fetch_df()
        return con.execute(
            """
            select platform,
                   coalesce(nullif(trim(service),''), platform) as service,
                   coalesce(nullif(trim(unit),''), 'unit')      as unit,
                   sum(quantity) as quantity, sum(cost) as cost, count(*) as line_items
            from usage_facts group by 1,2,3
            order by platform, quantity desc nulls last
            """
        ).fetch_df()
    finally:
        con.close()


def usage_by_unit() -> pd.DataFrame:
    """Totals grouped by unit across platforms (e.g. all 'Minutes', all 'requests')."""
    df = usage_across_platforms()
    if df.empty:
        return df
    g = (
        df.groupby("unit", as_index=False)
        .agg(quantity=("quantity", "sum"), platforms=("platform", "nunique"))
        .sort_values("quantity", ascending=False)
    )
    return g


def raw_rows(platform: str, limit: int = 500) -> pd.DataFrame:
    # raw line items only exist in a live warehouse; deployed mode has aggregates only
    if not _live_warehouse():
        return pd.DataFrame()
    return _q(
        """
        select date, service, sku, resource, project, region, quantity, unit, cost, currency
        from usage_facts where platform = ?
        order by date desc, cost desc nulls last
        limit ?
        """,
        [platform, limit],
    )


def platforms() -> list[str]:
    if not _live_warehouse():
        df = _published("platform_summary")
        return sorted(df["platform"].tolist()) if not df.empty else []
    df = _q("select distinct platform from usage_facts order by 1")
    return df["platform"].tolist() if not df.empty else []


def warehouse_exists() -> bool:
    if _live_warehouse():
        return True
    # deployed: consider it "exists" if we have published aggregates
    return (PUBLISHED / "platform_summary.parquet").exists()
