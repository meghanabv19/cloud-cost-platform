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
    "github": "GitHub",
    "vercel": "Vercel",
    "supabase": "Supabase",
    "dbt_cloud": "dbt Cloud",
    "duckdb": "DuckDB",
}


def _fmt_usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_qty(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{v:,.0f}" if v >= 100 or v == int(v) else f"{v:,.2f}"


def _days_until(value) -> int | None:
    import pandas as pd
    if value is None or (isinstance(value, float)):
        return None
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    if ts is None or pd.isna(ts):
        return None
    return (ts.date() - pd.Timestamp.utcnow().date()).days


def _fmt_when(value) -> str:
    import pandas as pd
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    return "—" if (ts is None or pd.isna(ts)) else ts.strftime("%d %b %Y")


def _accounts_section() -> None:
    import pandas as pd
    acc = da.accounts()
    st.subheader("Accounts & free-tier status")
    if acc is None or acc.empty:
        st.caption("No account metadata yet.")
        return

    # deadline banners for any free-tier / trial ending soon
    for _, r in acc.iterrows():
        d = _days_until(r.get("trial_end"))
        if d is not None:
            plat = PLATFORM_LABEL.get(r["platform"], r["platform"])
            when = _fmt_when(r.get("trial_end"))
            if d < 0:
                st.error(f"⛔ **{plat}** free/trial period ended on {when}.")
            elif d <= 14:
                st.warning(f"⚠️ **{plat}** {r.get('plan','')} free/trial ends **{when}** — {d} day(s) left.")
            else:
                st.info(f"🗓️ **{plat}** free/trial ends {when} ({d} days).")

    show = acc.copy()
    show["Platform"] = show["platform"].map(lambda p: PLATFORM_LABEL.get(p, p))
    show["Plan"] = show["plan"]
    show["Free"] = show["is_free"].map(lambda b: "✅" if b else "—")
    show["Last active"] = show["last_active"].map(_fmt_when)
    show["Free-tier ends"] = show["trial_end"].map(lambda v: _fmt_when(v) if not pd.isna(v) else "no end date")
    show["Status"] = show["status"]
    st.dataframe(
        show[["Platform", "Plan", "Free", "Last active", "Free-tier ends", "Status"]],
        use_container_width=True, hide_index=True,
    )


def _headline_usage(usage) -> list[tuple[str, str]]:
    """Pick a few human-friendly headline usage numbers from the breakdown."""
    tiles: list[tuple[str, str]] = []
    # sum quantity per (service, unit), surface the biggest few
    grp = (
        usage.groupby(["service", "unit"], as_index=False)["quantity"].sum()
        .sort_values("quantity", ascending=False)
    )
    for _, r in grp.head(4).iterrows():
        if r["quantity"] and r["quantity"] > 0:
            tiles.append((f"{r['service']} ({r['unit']})", _fmt_qty(r["quantity"])))
    return tiles


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

    _accounts_section()

    # ---- Resource usage across platforms (the real story on a free-tier stack) ----
    st.subheader("Resource usage across platforms")
    st.caption(
        "Everything is currently within free tiers ($0 spend) — so the signal here is "
        "**what's being consumed**. Units differ per platform, so they're grouped, not summed."
    )
    usage = da.usage_across_platforms()
    if usage.empty:
        st.info("No usage rows yet.")
    else:
        # headline usage tiles for the most meaningful metrics
        tiles = _headline_usage(usage)
        if tiles:
            cols = st.columns(len(tiles))
            for col, (label, value) in zip(cols, tiles):
                col.metric(label, value)

        # one chart per unit (minutes, requests, hours, …) comparing platforms
        for unit in usage["unit"].dropna().unique():
            sub = usage[usage["unit"] == unit]
            if sub["quantity"].fillna(0).abs().sum() <= 0:
                continue
            st.markdown(f"**{unit}** by platform")
            chart_df = sub.groupby("platform", as_index=False)["quantity"].sum()
            st.bar_chart(chart_df, x="platform", y="quantity")

        with st.expander("Full usage table (platform · service · unit · quantity)"):
            u = usage.copy()
            u["cost"] = u["cost"].map(_fmt_usd)
            st.dataframe(
                u.rename(columns={
                    "platform": "Platform", "service": "Service", "unit": "Unit",
                    "quantity": "Quantity", "cost": "Cost", "line_items": "Line items",
                }),
                use_container_width=True, hide_index=True,
            )

    st.subheader("Spend over time (all platforms)")
    xdaily = da.cross_platform_daily()
    if not xdaily.empty and xdaily["total_cost"].fillna(0).abs().sum() > 0:
        st.bar_chart(xdaily, x="date", y="total_cost")
    else:
        st.caption("No paid spend yet — $0 across all platforms. See resource usage above.")

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

    # account header: plan · last active · free-tier end
    acc = da.accounts()
    if acc is not None and not acc.empty:
        row = acc[acc["platform"] == choice]
        if not row.empty:
            r = row.iloc[0]
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Plan", str(r.get("plan") or "—"))
            a2.metric("Free tier", "Yes" if r.get("is_free") else "No")
            a3.metric("Last active", _fmt_when(r.get("last_active")))
            import pandas as pd
            a4.metric("Free-tier ends", _fmt_when(r.get("trial_end")) if not pd.isna(r.get("trial_end")) else "no end date")

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

    # application-level detail (per app/resource within the platform)
    st.subheader("By application / resource")
    apps = da.application_breakdown(choice)
    if apps.empty:
        st.caption("No application-level rows.")
    else:
        a = apps.copy()
        a["cost"] = a["cost"].map(_fmt_usd)
        st.dataframe(
            a.rename(columns={
                "application": "Application", "service": "Service", "unit": "Unit",
                "quantity": "Quantity", "cost": "Cost", "line_items": "Line items",
                "last_seen": "Last seen",
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

**Free-tier by design.** DuckDB + Parquet for storage, Cloudflare R2 for cold archive,
GitHub Actions for scheduling. Sources: Claude, GitHub, Vercel, Supabase, dbt Cloud, and
DuckDB itself (self-monitoring). Each also reports plan · last-active · free-tier end date.
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
