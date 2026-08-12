# Cloud Cost Platform

A data-engineering + analytics platform that tracks **usage and cost across cloud
platforms — using only real, programmatic APIs.** No manually-entered data anywhere.

> **Design constraint:** every component must stay **free-tier, indefinitely.** That
> single rule drives most of the architecture choices below.

## Sources (one ingestion script each)

| Platform | How it's pulled | Cost captured? |
| --- | --- | --- |
| **Claude** (Anthropic) | Admin API — Usage & Cost endpoints | ✅ $ (needs an admin key) |
| **GitHub** | REST billing/usage (Actions minutes, Codespaces, storage) | ✅ $ / metrics |
| **Vercel** | Billing/usage API (FOCUS v1.3) | ✅ $ |
| **Supabase** | Management API (project usage/analytics) | metrics (no $ on free tier) |
| **dbt Cloud** | Admin API (run history, duration, success) | metrics only |
| **DuckDB** | self-monitoring — reports its own warehouse size/rows | metrics only (local & free) |

Each source also records **account metadata** (plan, last active, and any
free-tier / trial **end date**) so the dashboard can flag deadlines.

## Architecture

<!-- PLACEHOLDER: architecture diagram goes here -->

```
GitHub Actions (daily cron)
  → ingestion/*.py   (one script per API → normalize → DuckDB `usage_facts`)
  → dbt (DuckDB)     (staging → intermediate → marts: unified per platform/resource/date)
  → analysis/*.py    (rolling z-score/IQR anomaly detection, forecast, threshold checks)
  → retention        (rows > 15 days → Parquet → Cloudflare R2, then dropped from hot store)
  → alerts           (HTML email via SMTP when a threshold is crossed or an anomaly fires)

DuckDB (hot, ≤15 days) + Parquet on R2 (cold archive)
  → Streamlit Community Cloud (public dashboard)
  → Databricks Free Edition (notebook-ready exports)
```

### Unified schema
Every source normalizes into one table, `usage_facts`:

`platform · resource · service · sku · project · region · date · quantity · unit · cost`

`cost` is **nullable** — sources like dbt Cloud report run metrics, not dollars.

### Why these tools *(placeholder — final wording later)*
<!-- PLACEHOLDER: short "why this tool" note per choice -->
- **DuckDB + Parquet** — <!-- why -->
- **Cloudflare R2 for cold storage** — <!-- why (and why not S3) -->
- **dbt Core on DuckDB** — <!-- why -->
- **GitHub Actions** — <!-- why -->
- **Streamlit + Databricks Free** — <!-- why -->

## Repo layout

```
ingestion/    db.py (DuckDB helper + unified schema + platform_meta), config.py
              (env-only config), base.py (shared pattern), one <source>_usage.py per platform
dbt/          staging → intermediate → marts models against DuckDB
analysis/     anomaly_detection.py, forecast.py, threshold_alerts.py
dashboards/   streamlit_app.py (multi-page) + published/ (committed marts) + databricks/ exports
config/       thresholds.yml (per-platform spend thresholds)
tests/        pytest for anomaly + threshold logic
.github/workflows/  daily_pipeline.yml (ingest → dbt → analyze → archive → alert)
```

## Setup (local)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
# requirements.txt = slim dashboard deps (what Streamlit Cloud installs);
# requirements-pipeline.txt = full ingestion/dbt/analysis deps.
pip install -r requirements.txt -r requirements-pipeline.txt
pip install -e .                      # makes `from ingestion.db import ...` work
cp .env.example .env.local            # fill in the sources you have credentials for

# run all sources (or one standalone):
python -m ingestion                 # every source, resilient
python -m ingestion.github_usage    # just one

# transform + test:
cd dbt && dbt build

# dashboard:
streamlit run dashboards/streamlit_app.py
```

Credentials are read **only** from environment variables (see `.env.example`). In
GitHub Actions the same names are stored as encrypted secrets.

## Status

Scaffold + shared foundation (`db.py`, `config.py`, `base.py`) complete. Ingestion
sources are built one at a time as credentials become available.
