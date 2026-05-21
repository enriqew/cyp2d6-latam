#!/usr/bin/env python3
"""
submit_jobs.py
--------------
Read a sample manifest CSV and submit one AWS Batch job per row.

Manifest format (CSV, with header)
------------------------------------
sample_id,population,bam_url
NA19648,MXL,https://ftp.1000genomes.ebi.ac.uk/.../NA19648.mapped.ILLUMINA.bwa.MXL.low_coverage.20120522.bam
HG01565,PEL,https://ftp.1000genomes.ebi.ac.uk/.../HG01565.mapped.ILLUMINA.bwa.PEL.low_coverage.20120522.bam
...

Generate the manifest from the existing sample_manifest.py module:

    python ingest/sample_manifest.py > batch/manifest_all_pops.csv

Usage
-----
    # Dry-run: print jobs without submitting
    python batch/submit_jobs.py --manifest batch/manifest_all_pops.csv --dry-run

    # Submit all samples
    python batch/submit_jobs.py --manifest batch/manifest_all_pops.csv

    # Submit only MXL and PEL
    python batch/submit_jobs.py --manifest batch/manifest_all_pops.csv --populations MXL,PEL

    # Limit to first N samples (useful for smoke-testing)
    python batch/submit_jobs.py --manifest batch/manifest_all_pops.csv --limit 10

AWS requirements
----------------
- AWS_DEFAULT_REGION must be set (or boto3 default region configured).
- The IAM principal running this script needs: batch:SubmitJob.
- The job's IAM role (JOB_ROLE_ARN) needs: s3:PutObject on OUTPUT_BUCKET.
- The job definition must already be registered:
    aws batch register-job-definition --cli-input-json file://batch/job_definition.json
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import boto3

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

# ── Defaults (override via CLI args) ─────────────────────────────────────────
DEFAULT_JOB_DEFINITION = "cyp2d6-process-sample"
DEFAULT_JOB_QUEUE = "cyp2d6-batch-queue"
DEFAULT_OUTPUT_BUCKET = "1000genomes-cyp2d6-results"
DEFAULT_OUTPUT_PREFIX = "results"

# Throttle: stay well under the AWS Batch SubmitJob API limit (50 req/s).
SUBMIT_DELAY_SECONDS = 0.05   # 20 jobs/s


# ── Manifest loading ──────────────────────────────────────────────────────────

def load_manifest(
    csv_path: Path,
    populations: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, str]]:
    """
    Load and filter the sample manifest CSV.

    Parameters
    ----------
    csv_path : Path
        Path to the manifest CSV file.
    populations : list[str] | None
        If provided, only include rows matching these population codes.
    limit : int | None
        If provided, return at most this many rows.

    Returns
    -------
    list[dict]
        Each dict has keys: sample_id, population, bam_url.
    """
    rows: List[Dict[str, str]] = []

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"sample_id", "population", "bam_url"}
        if not required.issubset(set(reader.fieldnames or [])):
            log.critical(
                "Manifest is missing required columns.  Expected: %s  Got: %s",
                required, reader.fieldnames,
            )
            sys.exit(1)

        for row in reader:
            if populations and row["population"].strip() not in populations:
                continue
            rows.append({
                "sample_id": row["sample_id"].strip(),
                "population": row["population"].strip(),
                "bam_url": row["bam_url"].strip(),
            })
            if limit and len(rows) >= limit:
                break

    log.info("Loaded %d samples from manifest", len(rows))
    return rows


# ── Job submission ────────────────────────────────────────────────────────────

def build_job_name(sample_id: str) -> str:
    """
    AWS Batch job names must match [A-Za-z0-9_-] and be <= 128 chars.
    """
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in sample_id)
    return f"cyp2d6-{safe}"[:128]


def submit_job(
    client,
    sample: Dict[str, str],
    job_definition: str,
    job_queue: str,
    output_bucket: str,
    output_prefix: str,
    dry_run: bool,
) -> Optional[str]:
    """
    Submit a single AWS Batch job for one sample.

    Per-sample values (SAMPLE_ID, POPULATION, BAM_URL) are injected via
    containerOverrides.environment — they override the static env vars in the
    job definition.

    Returns
    -------
    str | None
        AWS Batch job ID, or None in dry-run mode.
    """
    job_name = build_job_name(sample["sample_id"])
    container_overrides = {
        "environment": [
            {"name": "SAMPLE_ID",      "value": sample["sample_id"]},
            {"name": "POPULATION",     "value": sample["population"]},
            {"name": "BAM_URL",        "value": sample["bam_url"]},
            {"name": "OUTPUT_BUCKET",  "value": output_bucket},
            {"name": "OUTPUT_PREFIX",  "value": output_prefix},
        ]
    }

    if dry_run:
        log.info(
            "[DRY-RUN] Would submit: job=%s  sample=%s  pop=%s",
            job_name, sample["sample_id"], sample["population"],
        )
        return None

    response = client.submit_job(
        jobName=job_name,
        jobQueue=job_queue,
        jobDefinition=job_definition,
        containerOverrides=container_overrides,
    )
    job_id = response["jobId"]
    log.info(
        "Submitted: jobId=%s  sample=%s  pop=%s",
        job_id, sample["sample_id"], sample["population"],
    )
    return job_id


def submit_all(
    samples: List[Dict[str, str]],
    job_definition: str,
    job_queue: str,
    output_bucket: str,
    output_prefix: str,
    dry_run: bool,
) -> List[str]:
    """
    Submit jobs for all samples, with throttling.

    Returns
    -------
    list[str]
        List of submitted AWS Batch job IDs (empty if dry_run=True).
    """
    client = boto3.client("batch")
    job_ids: List[str] = []
    errors: List[str] = []

    for i, sample in enumerate(samples, start=1):
        log.info("Submitting %d/%d: %s", i, len(samples), sample["sample_id"])
        try:
            job_id = submit_job(
                client, sample,
                job_definition=job_definition,
                job_queue=job_queue,
                output_bucket=output_bucket,
                output_prefix=output_prefix,
                dry_run=dry_run,
            )
            if job_id:
                job_ids.append(job_id)
        except Exception as exc:
            log.error("Failed to submit %s: %s", sample["sample_id"], exc)
            errors.append(sample["sample_id"])

        # Throttle between submits
        if not dry_run:
            time.sleep(SUBMIT_DELAY_SECONDS)

    log.info(
        "Submission complete: submitted=%d  errors=%d",
        len(job_ids) + (len(samples) if dry_run else 0),
        len(errors),
    )
    if errors:
        log.warning("Failed submissions: %s", errors)

    return job_ids


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit one AWS Batch job per sample in the CYP2D6 manifest"
    )
    parser.add_argument(
        "--manifest", required=True, type=Path,
        help="Path to the sample manifest CSV (sample_id,population,bam_url)",
    )
    parser.add_argument(
        "--job-definition", default=DEFAULT_JOB_DEFINITION,
        help=f"AWS Batch job definition name (default: {DEFAULT_JOB_DEFINITION})",
    )
    parser.add_argument(
        "--job-queue", default=DEFAULT_JOB_QUEUE,
        help=f"AWS Batch job queue name (default: {DEFAULT_JOB_QUEUE})",
    )
    parser.add_argument(
        "--output-bucket", default=DEFAULT_OUTPUT_BUCKET,
        help=f"S3 bucket for results (default: {DEFAULT_OUTPUT_BUCKET})",
    )
    parser.add_argument(
        "--output-prefix", default=DEFAULT_OUTPUT_PREFIX,
        help=f"S3 key prefix for results (default: {DEFAULT_OUTPUT_PREFIX})",
    )
    parser.add_argument(
        "--populations",
        help="Comma-separated list of populations to include, e.g. MXL,PEL,CLM,PUR",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Submit at most N jobs (useful for smoke tests)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be submitted without actually calling AWS Batch",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    populations: Optional[List[str]] = None
    if args.populations:
        populations = [p.strip() for p in args.populations.split(",") if p.strip()]

    samples = load_manifest(args.manifest, populations=populations, limit=args.limit)
    if not samples:
        log.warning("No samples to submit after filtering. Exiting.")
        sys.exit(0)

    log.info(
        "About to submit %d jobs → queue=%s  definition=%s",
        len(samples), args.job_queue, args.job_definition,
    )
    if args.dry_run:
        log.info("DRY RUN — no jobs will actually be submitted")

    job_ids = submit_all(
        samples,
        job_definition=args.job_definition,
        job_queue=args.job_queue,
        output_bucket=args.output_bucket,
        output_prefix=args.output_prefix,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        log.info("%d jobs submitted. Monitor in AWS Console → Batch → Jobs.", len(job_ids))
        log.info(
            "When all jobs are SUCCEEDED, run the aggregation step:\n"
            "  python batch/aggregate_results.py"
            " --bucket %s --prefix %s",
            args.output_bucket, args.output_prefix,
        )


if __name__ == "__main__":
    main()
