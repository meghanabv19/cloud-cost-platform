"""Run every ingestion source in one shot: ``python -m ingestion``.

Resilient: each source runs independently; one source failing (e.g. a missing or
dormant credential like Claude's admin key) logs a warning and does NOT stop the
others. Exit code is 0 unless *every* source failed.
"""
from __future__ import annotations

import logging

from . import config, db
from .claude_usage import ClaudeUsage
from .github_usage import GithubUsage
from .supabase_usage import SupabaseUsage
from .dbt_cloud_usage import DbtCloudUsage
from .vercel_usage import VercelUsage
from .duckdb_usage import DuckdbUsage

SOURCES = [
    GithubUsage, VercelUsage, SupabaseUsage, DbtCloudUsage, DuckdbUsage, ClaudeUsage,
]

log = logging.getLogger("ingestion")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    con = db.connect(config.settings.duckdb_path)
    ok, failed = 0, 0
    try:
        for cls in SOURCES:
            src = cls()
            try:
                n = src.run(con)
                log.info("✓ %s: %d rows", src.platform, n)
                ok += 1
            except Exception as exc:  # noqa: BLE001 — isolate per-source failures
                log.warning("✗ %s skipped: %s", src.platform, exc)
                failed += 1
    finally:
        con.close()
    log.info("ingestion complete: %d ok, %d skipped", ok, failed)
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
