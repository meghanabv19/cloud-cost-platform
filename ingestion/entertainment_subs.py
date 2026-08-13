"""Entertainment subscriptions — parsed from Gmail receipt emails (IMAP).

Netflix / Amazon Prime / Crunchyroll etc. have no consumer billing API, so the
data comes from their **receipt emails**: this source logs into Gmail over IMAP
(app password), finds the most recent receipt per configured merchant, and
extracts the real charge amount + date. Prices are never hand-entered — only the
sender list lives in config/subscriptions.yml.

Env:  GMAIL_USER + GMAIL_APP_PASSWORD  (falls back to SMTP_USER/SMTP_PASSWORD)

Maps to unified schema: platform="entertainment", service="subscription",
      resource=merchant, cost=amount, unit="month", currency, date=charge date.
This is the first source that contributes real recurring $ spend.
"""
from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .base import IngestionSource, run_standalone
from . import config

IMAP_HOST = "imap.gmail.com"
_CUR = {"£": "GBP", "$": "USD", "€": "EUR"}


def _load_cfg() -> dict:
    import yaml

    path = config.settings.root / "config" / "subscriptions.yml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def _body_text(msg: email.message.Message) -> str:
    """Best-effort plain-text/HTML body extraction."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore"))
                except Exception:
                    continue
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore"))
        except Exception:
            pass
    text = "\n".join(parts)
    # strip HTML tags so amount regexes hit visible text
    return re.sub(r"<[^>]+>", " ", text)


class EntertainmentSubs(IngestionSource):
    platform = "entertainment"

    def __init__(self) -> None:
        self._last_dates: list[datetime] = []

    def fetch(self) -> list[dict[str, Any]]:
        creds = config.gmail_creds()
        cfg = _load_cfg()
        merchants: dict = cfg.get("merchants", {})
        default_re = cfg.get("default_amount_regex", r"[£$€]\s?([0-9]+(?:\.[0-9]{2})?)")
        since = cfg.get("since", "01 May 2026")
        mailbox = cfg.get("mailbox", "INBOX")

        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(creds["user"], creds["app_password"])
        rows: list[dict[str, Any]] = []
        try:
            M.select(mailbox, readonly=True)
            since_imap = datetime.strptime(since, "%d %b %Y").strftime("%d-%b-%Y")
            for name, mc in merchants.items():
                row = self._latest_charge(M, name, mc, default_re, since_imap)
                if row:
                    rows.append(row)
        finally:
            try:
                M.logout()
            except Exception:
                pass
        return rows

    def _latest_charge(self, M, name, mc, default_re, since_imap) -> dict[str, Any] | None:
        criteria = [f'(FROM "{mc.get("from", "")}")', f'(SINCE "{since_imap}")']
        if mc.get("subject_contains"):
            criteria.append(f'(SUBJECT "{mc["subject_contains"]}")')
        typ, data = M.search(None, *criteria)
        if typ != "OK" or not data or not data[0]:
            return None
        ids = data[0].split()
        amount_re = re.compile(mc.get("amount_regex", default_re))
        # scan newest-first; take the first email with a parseable amount
        for eid in reversed(ids[-8:]):
            typ, msg_data = M.fetch(eid, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            body = _body_text(msg)
            m = amount_re.search(body)
            if not m:
                continue
            amount = float(m.group(1))
            symbol = next((c for c in body[max(0, m.start() - 2):m.start() + 1] if c in _CUR), "£")
            when = None
            try:
                when = parsedate_to_datetime(msg.get("Date"))
            except Exception:
                when = datetime.now(timezone.utc)
            if when:
                self._last_dates.append(when)
            return {
                "date": (when or datetime.now(timezone.utc)).date().isoformat(),
                "service": "subscription",
                "resource": name,
                "quantity": 1,
                "unit": "month",
                "cost": amount,
                "currency": _CUR.get(symbol, "GBP"),
                "billed_email_subject": _subject(msg),
            }
        return None

    def fetch_meta(self) -> dict[str, Any]:
        last = max(self._last_dates).isoformat() if self._last_dates else None
        return {
            "plan": "subscriptions",
            "is_free": False,
            "account_created": None,
            "last_active": last,
            "trial_end": None,
            "status": "active",
            "extra": {"source": "gmail receipts (IMAP)"},
        }


def _subject(msg) -> str:
    raw = msg.get("Subject", "")
    try:
        parts = decode_header(raw)
        return "".join(
            (p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else p) for p, enc in parts
        )
    except Exception:
        return raw


if __name__ == "__main__":
    run_standalone(EntertainmentSubs)
