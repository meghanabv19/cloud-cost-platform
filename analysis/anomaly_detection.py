"""Anomaly detection over daily usage/cost series.

Two complementary, dependency-light detectors:
  • rolling z-score — flags a point whose deviation from a trailing window mean
    exceeds `z` standard deviations (good for gradual drift + sudden spikes).
  • IQR — flags a point outside Q1/Q3 ± k·IQR (robust to non-normal data, no window).

A point is reported as an anomaly if EITHER detector fires. Pure functions operate
on plain sequences so they're trivially unit-testable; :func:`detect_facts` wires them
to the warehouse's per-platform daily cost series.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd


@dataclass
class Anomaly:
    platform: str
    date: str
    value: float
    method: str        # "zscore" | "iqr" | "zscore+iqr"
    score: float       # z-score (or IQR distance in IQR units)
    baseline: float    # expected/median value


# ---- pure detectors ------------------------------------------------------------
def rolling_zscore(values: Sequence[float], window: int = 7, z: float = 3.0) -> list[tuple[bool, float, float]]:
    """Return per-point (is_anomaly, zscore, trailing_mean).

    Uses the trailing `window` points (excluding the current) as the baseline.
    Points without enough history are never flagged.
    """
    s = pd.Series([float(v) if v is not None else float("nan") for v in values], dtype="float64")
    out: list[tuple[bool, float, float]] = []
    for i in range(len(s)):
        lo = max(0, i - window)
        base = s.iloc[lo:i].dropna()
        if len(base) < max(3, window // 2):   # not enough history yet
            out.append((False, 0.0, float(base.mean()) if len(base) else 0.0))
            continue
        mean, std = base.mean(), base.std(ddof=0)
        cur = s.iloc[i]
        if pd.isna(cur):
            out.append((False, 0.0, float(mean)))
            continue
        if std == 0:
            # flat baseline: any deviation is an (effectively infinite) anomaly
            is_hit = cur != mean
            out.append((bool(is_hit), float("inf") if is_hit else 0.0, float(mean)))
            continue
        score = (cur - mean) / std
        out.append((bool(abs(score) >= z), float(score), float(mean)))
    return out


def iqr_flags(values: Sequence[float], k: float = 1.5) -> list[tuple[bool, float, float]]:
    """Return per-point (is_anomaly, distance_in_iqr_units, median) using a global IQR."""
    s = pd.Series([float(v) if v is not None else float("nan") for v in values], dtype="float64").dropna()
    if len(s) < 4:
        return [(False, 0.0, float(s.median()) if len(s) else 0.0) for _ in values]
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    med = s.median()
    lo, hi = q1 - k * iqr, q3 + k * iqr
    out: list[tuple[bool, float, float]] = []
    for v in values:
        if v is None or pd.isna(v):
            out.append((False, 0.0, float(med)))
            continue
        if iqr == 0:
            # degenerate spread: flag any value differing from the median
            is_hit = v != med
            out.append((bool(is_hit), float("inf") if is_hit else 0.0, float(med)))
            continue
        if v > hi:
            out.append((True, float((v - q3) / iqr), float(med)))
        elif v < lo:
            out.append((True, float((v - q1) / iqr), float(med)))
        else:
            out.append((False, float((v - med) / iqr), float(med)))
    return out


def detect_series(
    dates: Sequence[str],
    values: Sequence[float],
    platform: str = "",
    window: int = 7,
    z: float = 3.0,
    k: float = 1.5,
) -> list[Anomaly]:
    """Combine both detectors over one ordered series → list of Anomaly."""
    zs = rolling_zscore(values, window=window, z=z)
    iq = iqr_flags(values, k=k)
    anomalies: list[Anomaly] = []
    for date, val, (z_hit, z_score, z_base), (i_hit, i_dist, i_med) in zip(dates, values, zs, iq):
        if not (z_hit or i_hit):
            continue
        method = "+".join(m for m, hit in (("zscore", z_hit), ("iqr", i_hit)) if hit)
        anomalies.append(
            Anomaly(
                platform=platform,
                date=str(date),
                value=float(val) if val is not None else 0.0,
                method=method,
                score=round(z_score if z_hit else i_dist, 3),
                baseline=round(z_base if z_hit else i_med, 4),
            )
        )
    return anomalies


# ---- warehouse wiring ----------------------------------------------------------
def detect_facts(db_path: str | None = None, value: str = "cost") -> list[Anomaly]:
    """Run detection on each platform's daily `cost` (or `quantity`) series."""
    import duckdb
    from ingestion import config

    path = db_path or config.settings.duckdb_path
    con = duckdb.connect(path, read_only=True)
    try:
        col = "cost" if value == "cost" else "quantity"
        df = con.execute(
            f"""
            select platform, cast(date as date) as date, sum({col}) as v
            from usage_facts
            group by platform, date
            order by platform, date
            """
        ).fetch_df()
    finally:
        con.close()

    found: list[Anomaly] = []
    for platform, grp in df.groupby("platform"):
        grp = grp.sort_values("date")
        found.extend(
            detect_series(
                grp["date"].astype(str).tolist(),
                grp["v"].tolist(),
                platform=platform,
            )
        )
    return found


if __name__ == "__main__":
    for a in detect_facts():
        print(f"{a.platform:10s} {a.date}  value={a.value:.4f}  {a.method}  score={a.score}  base={a.baseline}")
    else:
        print("(anomaly scan complete)")
