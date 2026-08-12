"""Threshold + anomaly alerting → HTML email via SMTP.

Fires when a platform's month-to-date spend crosses its configured threshold
(config/thresholds.yml) OR when the anomaly detector flags a point. Offending rows
are highlighted red in an HTML email sent over SMTP (Gmail app password).

Design: the *evaluation* is pure (`evaluate`) and unit-tested; *sending* is a thin
side-effecting wrapper. If SMTP isn't configured, the email is written to disk as a
dry-run artifact instead of failing the pipeline.
"""
from __future__ import annotations

import smtplib
import sys
from dataclasses import dataclass
from datetime import date
from email.mime.text import MIMEText
from pathlib import Path
from typing import Mapping, Sequence

from ingestion import config
from analysis.anomaly_detection import Anomaly, detect_facts


@dataclass
class Alert:
    platform: str
    kind: str            # "threshold" | "anomaly"
    detail: str
    value: float
    limit: float | None  # threshold value (None for anomaly)


# ---- pure evaluation (unit-tested) ---------------------------------------------
def evaluate(
    spend_by_platform: Mapping[str, float],
    thresholds: Mapping[str, float | None],
    anomalies: Sequence[Anomaly] = (),
) -> list[Alert]:
    """Return the list of alerts. Pure — no I/O."""
    alerts: list[Alert] = []

    for platform, spend in spend_by_platform.items():
        limit = thresholds.get(platform)
        if limit is not None and spend is not None and spend > limit:
            alerts.append(
                Alert(
                    platform=platform,
                    kind="threshold",
                    detail=f"month-to-date spend ${spend:,.2f} exceeded threshold ${limit:,.2f}",
                    value=round(float(spend), 4),
                    limit=float(limit),
                )
            )

    for a in anomalies:
        alerts.append(
            Alert(
                platform=a.platform,
                kind="anomaly",
                detail=f"{a.date}: value {a.value:,.4f} vs baseline {a.baseline:,.4f} ({a.method}, score {a.score})",
                value=a.value,
                limit=None,
            )
        )
    return alerts


# ---- HTML rendering ------------------------------------------------------------
def build_html(alerts: Sequence[Alert], spend: Mapping[str, float], thresholds: Mapping[str, float | None]) -> str:
    def row(a: Alert) -> str:
        return (
            "<tr style='background:#fdecec'>"
            f"<td style='padding:6px 10px;color:#b00020;font-weight:600'>{a.platform}</td>"
            f"<td style='padding:6px 10px'>{a.kind}</td>"
            f"<td style='padding:6px 10px'>{a.detail}</td>"
            "</tr>"
        )

    alert_rows = "".join(row(a) for a in alerts) or (
        "<tr><td colspan='3' style='padding:8px 10px;color:#2e7d32'>No thresholds crossed and no anomalies detected. ✅</td></tr>"
    )

    spend_rows = "".join(
        f"<tr><td style='padding:4px 10px'>{p}</td>"
        f"<td style='padding:4px 10px;text-align:right'>${(s or 0):,.2f}</td>"
        f"<td style='padding:4px 10px;text-align:right'>"
        f"{('$'+format(thresholds.get(p),',.2f')) if thresholds.get(p) is not None else '—'}</td></tr>"
        for p, s in sorted(spend.items())
    )

    return f"""\
<html><body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1c1c22">
  <h2 style="margin:0 0 4px">Cloud Cost Platform — daily alert</h2>
  <div style="color:#667;font-size:13px">{date.today().isoformat()}</div>

  <h3 style="margin:18px 0 6px">Alerts ({len(alerts)})</h3>
  <table style="border-collapse:collapse;font-size:13px;min-width:520px">
    <tr style="background:#f2f4f3"><th style="padding:6px 10px;text-align:left">Platform</th>
      <th style="padding:6px 10px;text-align:left">Type</th>
      <th style="padding:6px 10px;text-align:left">Detail</th></tr>
    {alert_rows}
  </table>

  <h3 style="margin:18px 0 6px">Month-to-date spend</h3>
  <table style="border-collapse:collapse;font-size:13px">
    <tr style="background:#f2f4f3"><th style="padding:4px 10px;text-align:left">Platform</th>
      <th style="padding:4px 10px;text-align:right">MTD spend</th>
      <th style="padding:4px 10px;text-align:right">Threshold</th></tr>
    {spend_rows}
  </table>
  <p style="color:#889;font-size:11px;margin-top:16px">Data from each platform's own API · free-tier stack</p>
</body></html>"""


# ---- warehouse + sending -------------------------------------------------------
def _mtd_spend(db_path: str) -> dict[str, float]:
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.execute(
            """
            select platform, coalesce(sum(cost), 0) as spend
            from usage_facts
            where date_trunc('month', cast(date as date)) = date_trunc('month', current_date)
            group by platform
            """
        ).fetch_df()
    finally:
        con.close()
    return dict(zip(df["platform"], df["spend"]))


def send_email(html: str, subject: str) -> bool:
    """Send via SMTP. Returns True if sent, False if dry-run (no SMTP configured)."""
    s = config.settings
    if not (s.smtp_user and s.smtp_password and s.alert_email_to):
        out = s.root / "data" / "last_alert.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print(f"[alerts] SMTP not configured — dry-run written to {out}")
        return False

    msg = MIMEText(html, "html")
    msg["Subject"] = subject
    msg["From"] = s.alert_email_from or s.smtp_user
    msg["To"] = s.alert_email_to
    with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:
        server.starttls()
        server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
    print(f"[alerts] email sent to {s.alert_email_to}")
    return True


def main() -> int:
    s = config.settings
    spend = _mtd_spend(s.duckdb_path)
    thresholds = config.load_thresholds()
    anomalies = detect_facts(s.duckdb_path)
    alerts = evaluate(spend, thresholds, anomalies)

    html = build_html(alerts, spend, thresholds)
    subject = (
        f"[Cloud Cost] {len(alerts)} alert(s) — {date.today().isoformat()}"
        if alerts else f"[Cloud Cost] all clear — {date.today().isoformat()}"
    )
    # Only email when there's something to say (avoid daily noise); always keep an artifact.
    if alerts:
        send_email(html, subject)
    else:
        (s.root / "data").mkdir(exist_ok=True)
        (s.root / "data" / "last_alert.html").write_text(html)
        print("[alerts] no alerts — nothing emailed")
    print(f"[alerts] {len(alerts)} alert(s); {len(anomalies)} anomaly point(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
