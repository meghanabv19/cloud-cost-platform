# sample-data/

Holds the **frozen, real** AWS CUR capture used by `aws_cur_reader.py` when
`AWS_SOURCE=sample` (the default).

### `aws_cur_sample.parquet`
This file is **not fabricated** — it is a short, real Cost & Usage Report captured
by running CUR live against a small S3 bucket for a brief window, then committed
here so the daily pipeline keeps working after the AWS side is torn down.

To (re)create it:
1. Set `AWS_SOURCE=live` plus the `AWS_*` env vars and run `python -m ingestion.aws_cur_reader`
   against your CUR S3 bucket to capture real rows.
2. Export that capture to `sample-data/aws_cur_sample.parquet` and commit it.
3. Delete the CUR report + S3 bucket in AWS, set `AWS_SOURCE=sample` — done.

See the README "Architecture" section for the full rationale (why CUR + why freeze).
