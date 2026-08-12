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


def raw_rows(platform: str, limit: int = 500) -> pd.DataFrame:
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
    df = _q("select distinct platform from usage_facts order by 1")
    return df["platform"].tolist() if not df.empty else []


def warehouse_exists() -> bool:
    if not Path(DB_PATH).exists():
        return False
    con = _con()
    try:
        return _has_table(con, "usage_facts")
    finally:
        con.close()
