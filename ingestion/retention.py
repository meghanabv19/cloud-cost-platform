"""Retention / archival: move cold rows out of the hot DuckDB store to R2.

Any row older than RETENTION_HOT_DAYS (default 15) is:
  1. written to Parquet, one file per date  (archive/date=YYYY-MM-DD.parquet)
  2. uploaded to the configured Cloudflare R2 bucket (S3-compatible, via boto3)
  3. deleted from the hot `usage_facts` table

Safety: if R2 isn't configured, archival is SKIPPED (nothing is deleted) so data is
never lost. Re-archiving a date overwrites the same object → idempotent.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import duckdb

from . import config


def _r2_client():
    s = config.settings
    if not (s.r2_access_key_id and s.r2_secret_access_key and s.r2_bucket and s.r2_endpoint_url()):
        return None
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint_url(),
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
    )


def run(db_path: str | None = None) -> dict:
    s = config.settings
    path = db_path or s.duckdb_path
    cutoff = (date.today() - timedelta(days=s.retention_hot_days)).isoformat()

    client = _r2_client()
    con = duckdb.connect(path)
    try:
        cold_dates = [
            r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0])
            for r in con.execute(
                "select distinct cast(date as date) d from usage_facts where cast(date as date) < ? order by d",
                [cutoff],
            ).fetchall()
        ]
        if not cold_dates:
            print(f"[retention] nothing older than {cutoff} — hot store unchanged")
            return {"archived_dates": 0, "deleted_rows": 0, "r2": bool(client)}

        if client is None:
            print(
                f"[retention] R2 not configured — {len(cold_dates)} cold date(s) kept in hot store "
                "(no deletion, to avoid data loss)."
            )
            return {"archived_dates": 0, "deleted_rows": 0, "r2": False, "pending": len(cold_dates)}

        deleted = 0
        with tempfile.TemporaryDirectory() as tmp:
            for d in cold_dates:
                local = Path(tmp) / f"{d}.parquet"
                con.execute(
                    "copy (select * from usage_facts where cast(date as date) = ?) "
                    f"to '{local}' (format parquet)",
                    [d],
                )
                key = f"archive/date={d}/usage_facts.parquet"
                client.upload_file(str(local), s.r2_bucket, key)
                n = con.execute(
                    "select count(*) from usage_facts where cast(date as date) = ?", [d]
                ).fetchone()[0]
                con.execute("delete from usage_facts where cast(date as date) = ?", [d])
                deleted += n
                print(f"[retention] archived {d} ({n} rows) → r2://{s.r2_bucket}/{key}")

        print(f"[retention] done — {len(cold_dates)} date(s), {deleted} rows moved to R2")
        return {"archived_dates": len(cold_dates), "deleted_rows": deleted, "r2": True}
    finally:
        con.close()


if __name__ == "__main__":
    run()
