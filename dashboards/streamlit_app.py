"""Cloud Cost Platform — public dashboard (Streamlit).

Multi-page:
  • Cross-Platform Summary  — headline spend + per-platform totals
  • Per-Platform Usage & Cost — drill into one platform's services/SKUs and raw rows
  • Architecture             — how the data got here

Run locally:   streamlit run dashboards/streamlit_app.py
Deploy:        Streamlit Community Cloud (point it at this file).
Reads the DuckDB warehouse via data_access (marts if present, else usage_facts).
"""
from __future__ import annotations

import os
import sys

import streamlit as st

# Streamlit puts the script's own folder (dashboards/) on sys.path, not the project
# root — so ensure the root is importable whether run locally or on Streamlit Cloud.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dashboards import data_access as da
except ModuleNotFoundError:  # running with dashboards/ as cwd
    import data_access as da  # type: ignore

st.set_page_config(page_title="Cloud Cost Platform", page_icon="📊", layout="wide")

PLATFORM_LABEL = {
    "claude": "Claude (Anthropic)",
    "aws": "AWS",
    "gcp": "Google Cloud",
    "github": "GitHub",
    "supabase": "Supabase",
    "dbt_cloud": "dbt Cloud",
    "vercel": "Vercel",
}


def _fmt_usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def page_summary() -> None:
    st.title("📊 Cross-Platform Cost & Usage")
    st.caption("Usage and cost pulled from each platform's own API — no manually-entered data.")

    summary = da.platform_summary()
    if summary.empty:
        st.info("No data yet. Run the ingestion scripts to populate the warehouse.")
        return

    total = summary["total_cost"].fillna(0).sum()
    metric_only = int(summary["is_metric_only"].sum()) if "is_metric_only" in summary else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Tracked spend", _fmt_usd(total))
    c2.metric("Platforms reporting", len(summary))
    c3.metric("Metric-only sources", metric_only, help="Report usage but no $ (e.g. free tier / dbt Cloud)")

    st.subheader("Spend over time (all platforms)")
    xdaily = da.cross_platform_daily()
    if not xdaily.empty and xdaily["total_cost"].fillna(0).abs().sum() > 0:
        st.bar_chart(xdaily, x="date", y="total_cost")
    else:
        st.caption("Everything is currently within free tiers — $0 spend. Usage detail is on each platform page.")

    st.subheader("Per-platform")
    show = summary.copy()
    show["platform"] = show["platform"].map(lambda p: PLATFORM_LABEL.get(p, p))
    show["total_cost"] = show["total_cost"].map(_fmt_usd)
    show = show.rename(columns={
        "platform": "Platform", "active_days": "Active days",
        "first_seen": "First", "last_seen": "Last",
        "total_cost": "Total cost", "is_metric_only": "Metric-only",
    })
    st.dataframe(show, use_container_width=True, hide_index=True)


def page_platform() -> None:
    st.title("🔎 Per-Platform Usage & Cost")
    plats = da.platforms()
    if not plats:
        st.info("No data yet.")
        return
    choice = st.selectbox("Platform", plats, format_func=lambda p: PLATFORM_LABEL.get(p, p))

    daily = da.platform_daily(choice)
    breakdown = da.service_breakdown(choice)

    total_cost = daily["cost"].fillna(0).sum() if not daily.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Total cost", _fmt_usd(total_cost))
    c2.metric("Services", breakdown["service"].nunique() if not breakdown.empty else 0)
    c3.metric("Line items", int(breakdown["line_items"].sum()) if not breakdown.empty else 0)

    if not daily.empty and daily["cost"].fillna(0).abs().sum() > 0:
        st.subheader("Daily cost")
        st.bar_chart(daily, x="date", y="cost")

    st.subheader("By service / unit")
    if breakdown.empty:
        st.caption("No rows yet.")
    else:
        b = breakdown.copy()
        b["cost"] = b["cost"].map(_fmt_usd)
        st.dataframe(
            b.rename(columns={
                "service": "Service", "unit": "Unit", "quantity": "Quantity",
                "cost": "Cost", "line_items": "Line items",
                "first_seen": "First", "last_seen": "Last",
            }).drop(columns=["platform"], errors="ignore"),
            use_container_width=True, hide_index=True,
        )

    with st.expander("Raw line items"):
        st.dataframe(da.raw_rows(choice), use_container_width=True, hide_index=True)


def page_architecture() -> None:
    st.title("🏗️ Architecture")
    st.markdown(
        """
This dashboard is the read layer of a small but complete data platform. Every number
comes from a platform's **own programmatic API** — nothing is typed in by hand.

```
GitHub Actions (daily cron)
  → ingestion/*.py   one script per API → normalize → DuckDB `usage_facts`
  → dbt (DuckDB)     staging → intermediate → marts (unified schema)
  → analysis/*.py    rolling z-score / IQR anomaly detection + threshold checks
  → retention        rows > 15 days → Parquet → Cloudflare R2, dropped from hot store
  → alerts           HTML email when a threshold is crossed or an anomaly fires
DuckDB (hot) + R2 (cold)  →  this Streamlit app  +  Databricks-ready exports
```

**Unified schema** — every source normalizes into one table:
`platform · resource · service · sku · project · region · date · quantity · unit · cost`
(`cost` is nullable — some sources report usage metrics, not dollars.)

**Free-tier by design.** DuckDB + Parquet for storage, Cloudflare R2 for cold archive
(no S3), GitHub Actions for scheduling. AWS runs on a captured CUR sample by design —
see the README for the full rationale.
        """
    )


PAGES = {
    "Cross-Platform Summary": page_summary,
    "Per-Platform Usage & Cost": page_platform,
    "Architecture": page_architecture,
}


def main() -> None:
    st.sidebar.title("Cloud Cost Platform")
    if not da.warehouse_exists():
        st.sidebar.error("Warehouse not found — run ingestion first.")
    choice = st.sidebar.radio("Page", list(PAGES))
    st.sidebar.caption("Data via each platform's API · free-tier stack")
    PAGES[choice]()


if __name__ == "__main__":
    main()
else:
    main()  # Streamlit executes the module top-to-bottom
