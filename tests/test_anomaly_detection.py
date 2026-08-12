"""Unit tests for the anomaly detectors (pure functions, no warehouse)."""
from __future__ import annotations

from analysis.anomaly_detection import detect_series, iqr_flags, rolling_zscore


def test_flat_series_has_no_anomalies():
    values = [10.0] * 20
    dates = [f"2026-08-{i+1:02d}" for i in range(20)]
    assert detect_series(dates, values) == []


def test_zscore_flags_obvious_spike():
    # steady ~10, then a huge spike
    values = [10, 11, 9, 10, 10, 11, 9, 10, 10, 11, 200]
    flags = rolling_zscore(values, window=7, z=3.0)
    assert flags[-1][0] is True            # spike flagged
    assert all(not f[0] for f in flags[:-1])  # nothing before it


def test_iqr_flags_low_and_high_outliers():
    values = [10, 10, 11, 9, 10, 10, 11, 9, 500, -400]
    flags = iqr_flags(values, k=1.5)
    assert flags[8][0] is True   # 500 high outlier
    assert flags[9][0] is True   # -400 low outlier


def test_detect_series_reports_platform_and_method():
    values = [5, 5, 5, 5, 5, 5, 5, 300]
    dates = [f"2026-08-{i+1:02d}" for i in range(len(values))]
    anomalies = detect_series(dates, values, platform="vercel")
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.platform == "vercel"
    assert a.date == "2026-08-08"
    assert "zscore" in a.method or "iqr" in a.method
    assert a.value == 300.0


def test_insufficient_history_not_flagged():
    # only 2 points — detectors must not fire
    assert detect_series(["2026-08-01", "2026-08-02"], [1.0, 999.0]) == []


def test_none_values_are_safe():
    values = [None, 10, 10, 10, 10, 10, 10, None, 10]
    dates = [f"2026-08-{i+1:02d}" for i in range(len(values))]
    # should not raise, and a constant-ish series yields no anomalies
    assert detect_series(dates, values) == []
