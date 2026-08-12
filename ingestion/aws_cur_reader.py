"""AWS — Cost & Usage Report (CUR) reader. Dual-mode.

We deliberately avoid the Cost Explorer API (it charges $0.01/request). CUR delivers
detailed line items as Parquet/CSV to an S3 bucket. Because S3 is CUR's only delivery
target and isn't free forever, this source is "demo-then-freeze":

  AWS_SOURCE=live   → read the latest CUR parquet from the configured S3 bucket
  AWS_SOURCE=sample → read a committed real capture at sample-data/aws_cur_sample.parquet
                      (DEFAULT — keeps the daily pipeline working after AWS is torn down)

Env:  AWS_SOURCE, AWS_CUR_SAMPLE_PATH,
      (live only) AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
                  AWS_CUR_S3_BUCKET, AWS_CUR_S3_PREFIX

STATUS: stub — the dual-mode read + CUR→unified normalization lands when we build AWS.
"""
from __future__ import annotations

from typing import Any

from .base import IngestionSource, run_standalone
from . import config


class AwsCurReader(IngestionSource):
    platform = "aws"

    def fetch(self) -> list[dict[str, Any]]:
        creds = config.aws_creds()
        if creds["source"] == "live":
            raise NotImplementedError("aws_cur_reader: live S3 CUR read — TODO")
        raise NotImplementedError(
            "aws_cur_reader: sample parquet read — TODO "
            f"(will read {creds['sample_path']})"
        )


if __name__ == "__main__":
    run_standalone(AwsCurReader)
