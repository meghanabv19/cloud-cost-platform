"""Lightweight spend forecasting — project month-end cost per platform.

Deliberately simple and dependency-light (no statsmodels): a least-squares linear
trend over the recent daily series, plus a run-rate projection to month end. Good
enough to answer "at this rate, what will I spend this month?" and to unit-test.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass
class Forecast:
    platform: str
    mtd_cost: float          # month-to-date actual
    run_rate_eom: float      # projected end-of-month via daily run-rate
    trend_slope: float       # $/day linear trend


def linear_trend(values: Sequence[float]) -> tuple[float, float]:
    """Ordinary least-squares slope + intercept for y over x=0..n-1."""
    ys = [float(v) for v in values if v is not None]
    n = len(ys)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return 0.0, ys[0]
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    intercept = my - slope * mx
    return slope, intercept


def project_month_end(
    daily_costs: Sequence[float],
    as_of: date | None = None,
) -> tuple[float, float]:
    """Return (mtd_cost, run_rate_projection_to_eom).

    Run-rate = mean daily spend so far × days in month.
    """
    as_of = as_of or date.today()
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    costs = [float(c) for c in daily_costs if c is not None]
    mtd = sum(costs)
    day_of_month = as_of.day
    if day_of_month == 0:
        return mtd, mtd
    daily_rate = mtd / day_of_month
    return mtd, daily_rate * days_in_month


def forecast_platform(platform: str, dates: Sequence[str], daily_costs: Sequence[float], as_of: date | None = None) -> Forecast:
    slope, _ = linear_trend(daily_costs)
    mtd, eom = project_month_end(daily_costs, as_of=as_of)
    return Forecast(platform=platform, mtd_cost=round(mtd, 4), run_rate_eom=round(eom, 4), trend_slope=round(slope, 6))


def forecast_all(db_path: str | None = None) -> list[Forecast]:
    import duckdb
    from ingestion import config

    path = db_path or config.settings.duckdb_path
    con = duckdb.connect(path, read_only=True)
    try:
        df = con.execute(
            """
            select platform, cast(date as date) as date, sum(cost) as cost
            from usage_facts
            where date_trunc('month', cast(date as date)) = date_trunc('month', current_date)
            group by platform, date
            order by platform, date
            """
        ).fetch_df()
    finally:
        con.close()

    out: list[Forecast] = []
    for platform, grp in df.groupby("platform"):
        grp = grp.sort_values("date")
        out.append(forecast_platform(platform, grp["date"].astype(str).tolist(), grp["cost"].fillna(0).tolist()))
    return out


if __name__ == "__main__":
    for f in forecast_all():
        print(f"{f.platform:10s} MTD=${f.mtd_cost:.2f}  proj EOM=${f.run_rate_eom:.2f}  trend={f.trend_slope:+.4f}/day")
