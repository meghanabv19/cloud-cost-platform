"""Unit tests for threshold/anomaly evaluation + HTML rendering (pure logic)."""
from __future__ import annotations

from analysis.anomaly_detection import Anomaly
from analysis.threshold_alerts import Alert, build_html, evaluate


def test_threshold_crossed_fires():
    spend = {"vercel": 120.0, "github": 2.0}
    thresholds = {"vercel": 100.0, "github": 10.0}
    alerts = evaluate(spend, thresholds)
    assert len(alerts) == 1
    assert alerts[0].platform == "vercel"
    assert alerts[0].kind == "threshold"
    assert alerts[0].limit == 100.0


def test_threshold_not_crossed_is_silent():
    spend = {"vercel": 50.0}
    thresholds = {"vercel": 100.0}
    assert evaluate(spend, thresholds) == []


def test_metric_only_platform_never_threshold_alerts():
    # dbt_cloud threshold is None → never a threshold alert regardless of "spend"
    spend = {"dbt_cloud": 9999.0}
    thresholds = {"dbt_cloud": None}
    assert evaluate(spend, thresholds) == []


def test_anomaly_becomes_alert():
    spend = {"vercel": 1.0}
    thresholds = {"vercel": 100.0}
    anomalies = [Anomaly(platform="vercel", date="2026-08-08", value=300.0, method="zscore", score=7.1, baseline=5.0)]
    alerts = evaluate(spend, thresholds, anomalies)
    assert len(alerts) == 1
    assert alerts[0].kind == "anomaly"
    assert "300" in alerts[0].detail


def test_threshold_and_anomaly_combine():
    spend = {"vercel": 150.0}
    thresholds = {"vercel": 100.0}
    anomalies = [Anomaly(platform="vercel", date="2026-08-08", value=150.0, method="iqr", score=3.2, baseline=10.0)]
    alerts = evaluate(spend, thresholds, anomalies)
    kinds = sorted(a.kind for a in alerts)
    assert kinds == ["anomaly", "threshold"]


def test_html_highlights_offenders_red_and_is_valid():
    alerts = [Alert(platform="vercel", kind="threshold", detail="over budget", value=150.0, limit=100.0)]
    html = build_html(alerts, {"vercel": 150.0}, {"vercel": 100.0})
    assert "vercel" in html
    assert "#fdecec" in html or "b00020" in html  # red highlight present
    assert html.strip().startswith("<html")


def test_html_all_clear_when_no_alerts():
    html = build_html([], {"github": 0.0}, {"github": 10.0})
    assert "No thresholds crossed" in html
