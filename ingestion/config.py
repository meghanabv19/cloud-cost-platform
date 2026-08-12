"""Central configuration — read **only** from environment variables.

No secret is ever hard-coded. For local development, values are loaded from a
``.env.local`` file if present (never committed). In GitHub Actions the same names
are provided as encrypted secrets, so the code is identical in both places.

Import ``settings`` for shared config (DB path, retention, R2, SMTP, thresholds),
and call the small ``*_creds()`` helpers only inside the source that needs them —
that way a missing credential never breaks unrelated sources.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---- optional .env.local loader (local dev only) -------------------------------
try:  # python-dotenv is a convenience, not a hard dependency at import time
    from dotenv import load_dotenv

    _root = Path(__file__).resolve().parents[1]
    for _name in (".env.local", ".env"):
        _p = _root / _name
        if _p.exists():
            load_dotenv(_p, override=False)
            break
except Exception:  # pragma: no cover - dotenv absent is fine in CI
    pass


class MissingConfig(RuntimeError):
    """Raised when a required environment variable is absent."""


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise MissingConfig(f"required environment variable not set: {name}")
    return val


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


# ---- shared settings -----------------------------------------------------------
@dataclass
class Settings:
    root: Path = Path(__file__).resolve().parents[1]
    duckdb_path: str = ""
    retention_hot_days: int = 15

    # Cloudflare R2 (S3-compatible) cold archive
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_endpoint: str | None = None  # derived from account id if not given

    # SMTP email alerts (Gmail app password recommended)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    alert_email_from: str | None = None
    alert_email_to: str | None = None

    def r2_endpoint_url(self) -> str | None:
        if self.r2_endpoint:
            return self.r2_endpoint
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return None


def _load_settings() -> Settings:
    s = Settings()
    s.duckdb_path = env("DUCKDB_PATH", str(s.root / "data" / "warehouse.duckdb"))
    s.retention_hot_days = env_int("RETENTION_HOT_DAYS", 15)

    s.r2_account_id = env("R2_ACCOUNT_ID")
    s.r2_access_key_id = env("R2_ACCESS_KEY_ID")
    s.r2_secret_access_key = env("R2_SECRET_ACCESS_KEY")
    s.r2_bucket = env("R2_BUCKET")
    s.r2_endpoint = env("R2_ENDPOINT")

    s.smtp_host = env("SMTP_HOST", "smtp.gmail.com")
    s.smtp_port = env_int("SMTP_PORT", 587)
    s.smtp_user = env("SMTP_USER")
    s.smtp_password = env("SMTP_PASSWORD")
    s.alert_email_from = env("ALERT_EMAIL_FROM") or s.smtp_user
    s.alert_email_to = env("ALERT_EMAIL_TO")
    return s


settings = _load_settings()


# ---- per-source credential helpers (called lazily, only where needed) ----------
def claude_creds() -> dict[str, Any]:
    return {"admin_key": env("ANTHROPIC_ADMIN_KEY", required=True)}


def github_creds() -> dict[str, Any]:
    return {
        "token": env("GH_BILLING_TOKEN") or env("GITHUB_TOKEN", required=True),
        "org": env("GITHUB_ORG"),
        "username": env("GITHUB_USERNAME"),
    }


def supabase_creds() -> dict[str, Any]:
    return {
        "access_token": env("SUPABASE_ACCESS_TOKEN", required=True),
        "org_id": env("SUPABASE_ORG_ID"),
    }


def dbt_cloud_creds() -> dict[str, Any]:
    return {
        "token": env("DBT_CLOUD_API_TOKEN", required=True),
        "account_id": env("DBT_CLOUD_ACCOUNT_ID", required=True),
        "host": env("DBT_CLOUD_API_HOST", "cloud.getdbt.com"),
    }


def vercel_creds() -> dict[str, Any]:
    return {
        "token": env("VERCEL_TOKEN", required=True),
        "team_id": env("VERCEL_TEAM_ID"),
    }


# ---- spend thresholds (config/thresholds.yml, with env override) ---------------
def load_thresholds() -> dict[str, float | None]:
    """Per-platform spend thresholds in USD. ``None`` means metric-only (no $)."""
    path = settings.root / "config" / "thresholds.yml"
    thresholds: dict[str, float | None] = {}
    if path.exists():
        try:
            import yaml

            data = yaml.safe_load(path.read_text()) or {}
            thresholds = dict(data.get("thresholds", {}))
        except Exception:
            thresholds = {}
    # env override e.g. THRESHOLD_GCP=120
    for key, val in list(thresholds.items()):
        override = os.environ.get(f"THRESHOLD_{key.upper()}")
        if override not in (None, ""):
            thresholds[key] = float(override)
    return thresholds
