"""Shared DuckDB helper + the unified fact schema every source writes into.

The whole platform revolves around one wide, tidy table — ``usage_facts`` — with a
small, stable set of columns. Each ingestion script normalizes its API's odd shape
into rows of this schema and calls :func:`write_facts`. Writes are idempotent:
re-running a day's ingestion updates the same rows instead of duplicating them.

Unified schema (per the project spec):
    platform, resource, date, quantity, unit, cost   ← the backbone
plus optional drill-down dimensions (service, sku, project, region) so a source
can carry per-service/per-app detail without needing its own table. ``cost`` is
nullable for sources that report metrics rather than dollars (e.g. dbt Cloud, DuckDB).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb

FACTS_TABLE = "usage_facts"

# Column order matters for inserts.
COLUMNS: tuple[str, ...] = (
    "row_key",
    "platform",
    "resource",
    "service",
    "sku",
    "project",
    "region",
    "date",
    "quantity",
    "unit",
    "cost",
    "currency",
    "meta",
    "ingested_at",
)

# The dimensions that make a fact row unique (used to build the idempotency key).
_KEY_DIMS: tuple[str, ...] = (
    "platform",
    "resource",
    "service",
    "sku",
    "project",
    "region",
    "date",
    "unit",
)

_DDL = f"""
create table if not exists {FACTS_TABLE} (
    row_key     varchar primary key,
    platform    varchar not null,
    resource    varchar,
    service     varchar,
    sku         varchar,
    project     varchar,
    region      varchar,
    date        date not null,
    quantity    double,
    unit        varchar,
    cost        double,
    currency    varchar default 'USD',
    meta        varchar,          -- JSON string of any source-specific extras
    ingested_at timestamp default now()
);
"""


META_TABLE = "platform_meta"

# Account-level state per platform (one row each): plan, whether it's free, last
# activity, and any free-tier/trial END date (null = free indefinitely).
_META_DDL = f"""
create table if not exists {META_TABLE} (
    platform        varchar primary key,
    plan            varchar,
    is_free         boolean,
    last_active     timestamp,       -- last login/activity we can observe
    trial_end       timestamp,       -- free-tier / trial expiry (null = no end date)
    account_created timestamp,
    status          varchar,
    extra           varchar,         -- JSON of platform-specific extras
    synced_at       timestamp default now()
);
"""

META_COLUMNS: tuple[str, ...] = (
    "platform", "plan", "is_free", "last_active", "trial_end",
    "account_created", "status", "extra", "synced_at",
)


def connect(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB warehouse and ensure the schema exists."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(_DDL)
    con.execute(_META_DDL)
    return con


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # accept "2026-08-07", "2026-08-07T12:00:00Z", "2026/08/07"
    text = text.replace("/", "-")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_key(row: Mapping[str, Any]) -> str:
    parts = "|".join(str(row.get(dim) or "") for dim in _KEY_DIMS)
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]


def normalize_row(platform: str, **fields: Any) -> dict[str, Any]:
    """Turn arbitrary keyword fields into one canonical ``usage_facts`` row.

    Known columns are placed directly; anything else is folded into the ``meta``
    JSON blob so no source detail is silently dropped.
    """
    row: dict[str, Any] = {
        "platform": platform,
        "resource": fields.pop("resource", None),
        "service": fields.pop("service", None),
        "sku": fields.pop("sku", None),
        "project": fields.pop("project", None),
        "region": fields.pop("region", None),
        "date": _coerce_date(fields.pop("date", None)),
        "quantity": _coerce_float(fields.pop("quantity", None)),
        "unit": fields.pop("unit", None),
        "cost": _coerce_float(fields.pop("cost", None)),
        "currency": fields.pop("currency", None) or "USD",
    }
    extra = {k: v for k, v in fields.items() if v is not None}
    row["meta"] = json.dumps(extra, default=str, sort_keys=True) if extra else None
    row["ingested_at"] = datetime.utcnow()
    row["row_key"] = _row_key(row)
    if row["date"] is None:
        raise ValueError(f"[{platform}] a fact row is missing a usable 'date': {fields!r}")
    return row


def write_facts(con: duckdb.DuckDBPyConnection, rows: Sequence[Mapping[str, Any]]) -> int:
    """Idempotently upsert normalized rows. Returns the number of rows written.

    Rows may be pre-normalized (have a ``row_key``) or raw keyword dicts already
    shaped like the schema. Existing keys are updated (quantity/cost/meta refreshed).
    """
    if not rows:
        return 0

    prepared: list[tuple] = []
    for r in rows:
        r = dict(r)
        if "row_key" not in r:  # allow callers to pass loosely-shaped dicts
            r = normalize_row(r.get("platform", "unknown"), **{k: v for k, v in r.items() if k != "platform"})
        prepared.append(tuple(r.get(col) for col in COLUMNS))

    placeholders = ", ".join(["?"] * len(COLUMNS))
    col_list = ", ".join(COLUMNS)
    update_cols = [c for c in COLUMNS if c not in ("row_key",)]
    update_set = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    sql = (
        f"insert into {FACTS_TABLE} ({col_list}) values ({placeholders}) "
        f"on conflict (row_key) do update set {update_set}"
    )
    con.executemany(sql, prepared)
    return len(prepared)


def read_facts(
    con: duckdb.DuckDBPyConnection,
    platform: str | None = None,
    since: str | date | None = None,
):
    """Return facts as a pandas DataFrame (optionally filtered)."""
    clauses, params = [], []
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if since:
        clauses.append("date >= ?")
        params.append(_coerce_date(since))
    where = f"where {' and '.join(clauses)}" if clauses else ""
    return con.execute(
        f"select * from {FACTS_TABLE} {where} order by date, platform", params
    ).fetch_df()


def platforms(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in con.execute(
        f"select distinct platform from {FACTS_TABLE} order by 1"
    ).fetchall()]


def _coerce_ts(value: Any) -> Any:
    """Accept ISO strings / unix-ms / datetime → ISO string (or None)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):  # unix milliseconds (Vercel) or seconds
        from datetime import datetime, timezone

        secs = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
    return str(value)


def write_meta(con: duckdb.DuckDBPyConnection, platform: str, **fields: Any) -> None:
    """Upsert one account-metadata row for a platform."""
    import json as _json

    extra = fields.pop("extra", None)
    row = {
        "platform": platform,
        "plan": fields.pop("plan", None),
        "is_free": fields.pop("is_free", None),
        "last_active": _coerce_ts(fields.pop("last_active", None)),
        "trial_end": _coerce_ts(fields.pop("trial_end", None)),
        "account_created": _coerce_ts(fields.pop("account_created", None)),
        "status": fields.pop("status", None),
        "extra": _json.dumps({**(extra or {}), **fields}, default=str, sort_keys=True)
        if (extra or fields) else None,
        "synced_at": datetime.utcnow(),
    }
    placeholders = ", ".join(["?"] * len(META_COLUMNS))
    cols = ", ".join(META_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in META_COLUMNS if c != "platform")
    con.execute(
        f"insert into {META_TABLE} ({cols}) values ({placeholders}) "
        f"on conflict (platform) do update set {updates}",
        tuple(row[c] for c in META_COLUMNS),
    )


def read_meta(con: duckdb.DuckDBPyConnection):
    return con.execute(f"select * from {META_TABLE} order by platform").fetch_df()
