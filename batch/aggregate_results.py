#!/usr/bin/env python3
"""
aggregate_results.py
--------------------
Reducer step for the AWS Batch scale-up pipeline.

After all per-sample Batch jobs have completed, this script:
1. Lists all aldy_output.json files under s3://{BUCKET}/{PREFIX}/
2. Downloads and parses each one.
3. Runs the same Silver + Gold transformations as the local pipeline
   (silver_diplotypes.py → gold_aggregates.py → build_artifacts.py).
4. Writes the four Gold JSON artifacts to data/exports/ — ready to be
   copied into the portfolio repo's src/data/cyp2d6/.

The script is designed to be run locally (not inside a container) after
the Batch jobs complete. It needs boto3 + pandas + duckdb (the main
pipeline requirements, not the minimal batch requirements).

Usage
-----
    python batch/aggregate_results.py \\
        --bucket 1000genomes-cyp2d6-results \\
        --prefix results \\
        [--populations MXL,PEL,CLM,PUR,CEU] \\
        [--out-dir data/exports_all_pops]

Output
------
    data/exports/allele_frequencies.json
    data/exports/phenotype_distribution.json
    data/exports/drug_impact_summary.json
    data/exports/metadata.json

Then copy to the portfolio repo:
    cp data/exports/*.json ../data-dive-design-hub/src/data/cyp2d6/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import pandas as pd

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

REPO_ROOT = Path(__file__).parents[1]


# ── S3 collection ─────────────────────────────────────────────────────────────

def list_result_keys(
    bucket: str,
    prefix: str,
    populations: Optional[List[str]] = None,
) -> List[str]:
    """
    List all aldy_output.json keys under s3://bucket/prefix/.

    Key layout written by process_sample.py:
        {prefix}/{population}/{sample_id}/aldy_output.json

    Parameters
    ----------
    populations : list[str] | None
        If provided, only include keys whose population path component matches.
    """
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    search_prefix = prefix.strip("/") + "/" if prefix else ""
    keys: List[str] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=search_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("/aldy_output.json"):
                continue
            if populations:
                # key = results/{population}/{sample_id}/aldy_output.json
                parts = key.split("/")
                # population is the first path component after the prefix
                prefix_depth = len(search_prefix.strip("/").split("/")) if search_prefix else 0
                if len(parts) > prefix_depth:
                    pop_component = parts[prefix_depth]
                    if pop_component not in populations:
                        continue
            keys.append(key)

    log.info("Found %d aldy_output.json files in s3://%s/%s", len(keys), bucket, search_prefix)
    return keys


def download_results(bucket: str, keys: List[str]) -> List[Dict[str, Any]]:
    """
    Download and parse all result JSONs from S3.

    Returns
    -------
    list[dict]
        One dict per sample (includes both ok and error results).
    """
    s3 = boto3.client("s3")
    results: List[Dict[str, Any]] = []
    errors = 0

    for i, key in enumerate(keys, start=1):
        if i % 100 == 0:
            log.info("Downloaded %d / %d ...", i, len(keys))
        try:
            response = s3.get_object(Bucket=bucket, Key=key)
            data = json.loads(response["Body"].read().decode("utf-8"))
            results.append(data)
        except Exception as exc:
            log.error("Failed to download %s: %s", key, exc)
            errors += 1

    ok = sum(1 for r in results if r.get("status") == "ok")
    err_results = sum(1 for r in results if r.get("status") != "ok")
    log.info(
        "Downloaded %d results: ok=%d  error=%d  download_failures=%d",
        len(results), ok, err_results, errors,
    )
    return results


# ── Bronze → Silver ───────────────────────────────────────────────────────────

def results_to_dataframe(results: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Convert the list of per-sample result dicts to a raw DataFrame.

    Only 'ok' results are included in the Silver transformation.
    Error results are collected separately for logging.
    """
    ok_rows = [r for r in results if r.get("status") == "ok"]
    err_rows = [r for r in results if r.get("status") != "ok"]

    if err_rows:
        log.warning("%d samples with errors (excluded from analysis):", len(err_rows))
        for r in err_rows[:20]:
            log.warning("  %s (%s): %s", r.get("sample_id"), r.get("population"), r.get("error_msg"))
        if len(err_rows) > 20:
            log.warning("  ... and %d more", len(err_rows) - 20)

    if not ok_rows:
        log.error("No successful results found — cannot build Gold artifacts")
        sys.exit(1)

    df = pd.DataFrame(ok_rows)
    log.info("Raw DataFrame: %d rows, populations: %s",
             len(df), sorted(df["population"].unique()))
    return df


def apply_silver(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the same Silver phenotype mapping as silver_diplotypes.py.

    Imports from the local pipeline to avoid duplicating the logic.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from cyp2d6.transformations.silver_diplotypes import apply_silver_phenotypes
    return apply_silver_phenotypes(df_raw)


# ── Gold aggregates ───────────────────────────────────────────────────────────

def build_gold_artifacts(df_silver: pd.DataFrame, out_dir: Path) -> None:
    """
    Build and write all four Gold JSON artifacts.

    Reuses the existing gold_aggregates.py and build_artifacts.py logic.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from cyp2d6.transformations.gold_aggregates import (
        build_allele_frequencies,
        build_phenotype_distribution,
        build_drug_impact_summary,
    )

    df_silver_clean = df_silver[df_silver["population"] != "UNKNOWN"]

    df_allele = build_allele_frequencies(df_silver_clean)
    df_pheno = build_phenotype_distribution(df_silver_clean)
    df_drug = build_drug_impact_summary(df_silver_clean)

    out_dir.mkdir(parents=True, exist_ok=True)

    # -- allele_frequencies.json
    _write_json(df_allele.to_dict(orient="records"), out_dir / "allele_frequencies.json")

    # -- phenotype_distribution.json
    _write_json(df_pheno.to_dict(orient="records"), out_dir / "phenotype_distribution.json")

    # -- drug_impact_summary.json
    _write_json(df_drug.to_dict(orient="records"), out_dir / "drug_impact_summary.json")

    # -- metadata.json
    pop_counts = (
        df_pheno[df_pheno["phenotype"] == "NM"][["population", "n_total"]]
        .set_index("population")["n_total"]
        .to_dict()
    )
    metadata = {
        "gene": "CYP2D6",
        "pipeline_version": "2.0.0-batch",
        "run_date": date.today().isoformat(),
        "reference_genome": "GRCh37/hg19",
        "caller": "Aldy v4",
        "source": "1000 Genomes Phase 3 — all populations, remote BAM slicing via AWS Batch",
        "region_sliced": "22:42,400,000–42,650,000",
        "n_total_samples": len(df_silver_clean),
        "n_alleles_reported": int(df_allele["allele"].nunique()),
        "populations": {
            pop: {"n": int(n)} for pop, n in pop_counts.items()
        },
        "drugs_covered": list(df_drug["drug"].unique()),
        "phenotype_categories": ["UM", "NM", "IM", "PM"],
    }
    _write_json(metadata, out_dir / "metadata.json")

    log.info(
        "Gold artifacts written to %s:\n"
        "  allele_frequencies.json       (%d rows)\n"
        "  phenotype_distribution.json   (%d rows)\n"
        "  drug_impact_summary.json      (%d rows)\n"
        "  metadata.json",
        out_dir,
        len(df_allele), len(df_pheno), len(df_drug),
    )


def _write_json(data: Any, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    log.info("Written: %s  (%d bytes)", path, path.stat().st_size)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate per-sample Batch results into Gold JSON artifacts"
    )
    parser.add_argument(
        "--bucket", required=True,
        help="S3 bucket containing per-sample aldy_output.json files",
    )
    parser.add_argument(
        "--prefix", default="results",
        help="S3 key prefix (default: results)",
    )
    parser.add_argument(
        "--populations",
        help="Comma-separated populations to include, e.g. MXL,PEL,CLM,PUR,CEU",
    )
    parser.add_argument(
        "--out-dir", default=None, type=Path,
        help="Local output directory for JSON artifacts (default: data/exports)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    populations: Optional[List[str]] = None
    if args.populations:
        populations = [p.strip() for p in args.populations.split(",") if p.strip()]

    out_dir = args.out_dir or (REPO_ROOT / "data" / "exports")

    keys = list_result_keys(args.bucket, args.prefix, populations=populations)
    if not keys:
        log.error(
            "No results found at s3://%s/%s — did Batch jobs complete?",
            args.bucket, args.prefix,
        )
        sys.exit(1)

    results = download_results(args.bucket, keys)
    df_raw = results_to_dataframe(results)
    df_silver = apply_silver(df_raw)
    build_gold_artifacts(df_silver, out_dir)

    log.info(
        "\nNext step: copy artifacts to the portfolio repo:\n"
        "  cp %s/*.json ../data-dive-design-hub/src/data/cyp2d6/",
        out_dir,
    )


if __name__ == "__main__":
    main()
