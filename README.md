# Cloud Cost Platform

A data-engineering + analytics platform that tracks **usage and cost across cloud
platforms — using only real, programmatic APIs.** No manually-entered data anywhere.

> **Design constraint:** every component must stay **free-tier, indefinitely.** That
> single rule drives most of the architecture choices below.

## Sources (one ingestion script each)

| Platform | How it's pulled | Cost captured? |
| --- | --- | --- |
| **Claude** (Anthropic) | Admin API — Usage & Cost endpoints | ✅ $ |
| **AWS** | Cost & Usage Report (CUR) parquet — *not* Cost Explorer | ✅ $ (frozen sample, see below) |
| **GCP** | BigQuery billing export (per-SKU) + Cloud Billing API | ✅ $ — deepest analysis |
| **GitHub** | REST billing/usage (Actions minutes, storage) | ✅ $ / metrics |
| **Supabase** | Management API (project usage/analytics) | metrics (often no $ on free tier) |
| **dbt Cloud** | Admin/Discovery API (run history, duration, success) | metrics only |
| **Vercel** | Billing/usage API (FOCUS v1.3) | ✅ $ |

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

### A deliberate tradeoff: AWS runs on a frozen sample
AWS ingestion reads a **captured sample**, not a live source — on purpose.

CUR is the *right* AWS source (Cost Explorer's API charges $0.01 per request), but
CUR's **only delivery destination is an S3 bucket**, and S3 storage is no longer free
indefinitely for new accounts. Keeping a live CUR bucket running would introduce
exactly the kind of ongoing storage cost the rest of this stack was designed to avoid.

So AWS is **demo-then-freeze**: run CUR live briefly to capture *real* line items, commit
that capture to `sample-data/aws_cur_sample.parquet`, then tear the AWS side down. The
reader (`aws_cur_reader.py`) supports `AWS_SOURCE=live` or `AWS_SOURCE=sample` (default),
so the daily pipeline keeps producing real, representative AWS data with zero standing
cost. It's a conscious cost-engineering decision, consistent with the project's premise —
not a gap.

## Repo layout

```
ingestion/    db.py (DuckDB helper + unified schema), config.py (env-only config),
              base.py (shared pattern), one <source>_usage.py per platform
dbt/          staging → intermediate → marts models against DuckDB
analysis/     anomaly_detection.py, forecast.py, threshold_alerts.py
dashboards/   streamlit_app.py (multi-page) + databricks/ export scripts
config/       thresholds.yml (per-platform spend thresholds)
sample-data/  frozen real AWS CUR capture
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

# run one source standalone (once its fetch() is implemented):
python -m ingestion.gcp_billing

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
