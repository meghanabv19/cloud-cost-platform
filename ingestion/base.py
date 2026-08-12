"""Shared base class + runner so every ingestion script has the same shape:

- runnable standalone for local testing:  ``python -m ingestion.claude_usage``
- importable by the GitHub Actions pipeline: ``ClaudeUsage().run(con)``

A source only has to implement ``fetch()`` — return a list of loosely-shaped dicts
(any of: resource, service, sku, project, region, date, quantity, unit, cost, plus
extras). The base class normalizes and writes them idempotently via ``db``.
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from . import config, db

log = logging.getLogger("ingestion")


class IngestionSource:
    #: short platform name written into every row (e.g. "claude", "gcp")
    platform: str = "base"

    def fetch(self) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        """Pull from the API and return rows shaped like the unified schema."""
        raise NotImplementedError(f"{self.platform}: fetch() not implemented yet")

    def run(self, con: "db.duckdb.DuckDBPyConnection | None" = None) -> int:
        own_connection = con is None
        con = con or db.connect(config.settings.duckdb_path)
        try:
            raw_rows = self.fetch()
            facts = [db.normalize_row(self.platform, **row) for row in raw_rows]
            written = db.write_facts(con, facts)
            log.info("%s: ingested %d rows", self.platform, written)
            return written
        finally:
            if own_connection:
                con.close()


def run_standalone(source_cls: type[IngestionSource]) -> None:
    """Entry point for ``if __name__ == '__main__'`` in each source module."""
    parser = argparse.ArgumentParser(description=f"Ingest {source_cls.platform} usage/cost")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    count = source_cls().run()
    print(f"{source_cls.platform}: {count} rows ingested → {config.settings.duckdb_path}")
