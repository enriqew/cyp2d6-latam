#!/usr/bin/env python3
"""
process_sample.py
-----------------
AWS Batch worker script.  One invocation = one sample.

What this script does
---------------------
1. Read job parameters from environment variables (injected by AWS Batch).
2. Slice the CYP2D6 region from the remote 1000G BAM using samtools HTTP range
   requests — no full BAM download.
3. Run Aldy star allele + CNV calling on the local slice.
4. Parse the Aldy TSV output into a structured dict.
5. Write the result JSON to S3 at:
       s3://{OUTPUT_BUCKET}/{SAMPLE_ID}/aldy_output.json

Environment variables (all required unless noted)
-------------------------------------------------
SAMPLE_ID       1000G sample identifier, e.g. NA19648
POPULATION      Population code, e.g. MXL
BAM_URL         Full HTTPS URL to the remote BAM on EBI FTP
OUTPUT_BUCKET   S3 bucket name for results, e.g. 1000genomes-cyp2d6-results
OUTPUT_PREFIX   (optional) S3 key prefix, default ""

Design notes
------------
- Runs entirely in Linux/Docker — no Windows path assumptions.
- Credentials come from the AWS Batch job's IAM role; no keys are hardcoded.
- All intermediate files live in /tmp and are cleaned up after upload.
- On error the script writes a partial result JSON with status="error" to S3
  so the aggregation step can collect failures without crashing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import boto3

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
# CYP2D6 locus on GRCh37/hg19 (1000G Phase 3 BAMs are hg19-aligned).
# The wider 250 kb window (42,400,000–42,650,000) ensures full gene + flanking
# regions needed for Aldy CNV breakpoint detection.
CYP2D6_REGION = "22:42400000-42650000"

ALDY_GENE = "cyp2d6"
ALDY_PROFILE = "illumina"   # 1000G low-coverage WGS
ALDY_GENOME = "hg19"        # 1000G Phase 3 aligned to GRCh37

# CPIC phenotype mapping (mirrors silver_diplotypes.py in the main pipeline)
_CPIC_MAP = {
    "normal": "Normal Metabolizer",
    "poor": "Poor Metabolizer",
    "intermediate": "Intermediate Metabolizer",
    "ultrarapid": "Ultrarapid Metabolizer",
    "rapid": "Rapid Metabolizer",
    "indeterminate": "Indeterminate",
}


# ── Environment ───────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        log.critical("Required environment variable '%s' is not set", name)
        sys.exit(1)
    return val


def _read_config() -> Dict[str, str]:
    return {
        "sample_id": _require_env("SAMPLE_ID"),
        "population": _require_env("POPULATION"),
        "bam_url": _require_env("BAM_URL"),
        "output_bucket": _require_env("OUTPUT_BUCKET"),
        "output_prefix": os.environ.get("OUTPUT_PREFIX", "").strip().strip("/"),
    }


# ── Step 1: BAM slicing ───────────────────────────────────────────────────────

def slice_bam(bam_url: str, sample_id: str, work_dir: Path) -> Path:
    """
    Remote-slice the CYP2D6 region from the 1000G BAM via HTTPS.

    Uses samtools view with HTTP range requests — no full file download.
    The slice is ~50 MB (vs ~30 GB for the full BAM).

    Returns
    -------
    Path
        Path to the local sliced + indexed BAM.

    Raises
    ------
    RuntimeError
        If samtools exits non-zero.
    """
    out_bam = work_dir / f"{sample_id}.bam"
    log.info("[%s] Slicing %s from %s", sample_id, CYP2D6_REGION, bam_url)

    cmd = [
        "samtools", "view",
        "-b",                    # output BAM (not SAM)
        "-o", str(out_bam),
        bam_url,
        CYP2D6_REGION,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"samtools view failed (rc={result.returncode}): {result.stderr.strip()}"
        )

    log.info("[%s] Indexing BAM slice ...", sample_id)
    idx_result = subprocess.run(
        ["samtools", "index", str(out_bam)],
        capture_output=True, text=True, timeout=120,
    )
    if idx_result.returncode != 0:
        raise RuntimeError(
            f"samtools index failed (rc={idx_result.returncode}): {idx_result.stderr.strip()}"
        )

    slice_mb = out_bam.stat().st_size / 1024 / 1024
    log.info("[%s] Slice written: %.1f MB", sample_id, slice_mb)
    return out_bam


# ── Step 2: Aldy calling ──────────────────────────────────────────────────────

def run_aldy(bam_path: Path, sample_id: str, work_dir: Path) -> Path:
    """
    Run Aldy CYP2D6 star allele calling on the sliced BAM.

    Returns
    -------
    Path
        Path to the Aldy TSV output file.

    Raises
    ------
    RuntimeError
        If Aldy exits non-zero or produces no output file.
    """
    out_tsv = work_dir / f"{sample_id}_aldy.tsv"
    log.info("[%s] Running Aldy ...", sample_id)

    cmd = [
        "aldy", "genotype",
        "-g", ALDY_GENE,
        "-p", ALDY_PROFILE,
        "--genome", ALDY_GENOME,
        str(bam_path),
        "-o", str(out_tsv),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise RuntimeError(
            "aldy not found — confirm Dockerfile installs aldy via pip"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Aldy timed out after 1800s")

    if result.returncode != 0:
        raise RuntimeError(
            f"Aldy failed (rc={result.returncode}): {result.stderr.strip()}"
        )

    if not out_tsv.exists():
        raise RuntimeError("Aldy produced no output TSV")

    log.info("[%s] Aldy complete", sample_id)
    return out_tsv


# ── Step 3: TSV parsing ───────────────────────────────────────────────────────

def parse_aldy_tsv(tsv_path: Path, sample_id: str) -> Dict[str, Any]:
    """
    Parse Aldy v4 TSV output into a structured result dict.

    Aldy v4 format:
      Comment rows: #Solution N: *X/*Y; cpic=<phenotype>; cpic_score=<float>
      Data rows:    tab-separated; column 3 (0-indexed) is "Major" (the genotype)

    Returns
    -------
    dict with keys: sample_id, genotype, allele_1, allele_2,
                    activity_score, phenotype, solutions, status
    """
    try:
        with open(tsv_path, encoding="utf-8") as fh:
            lines = [ln.rstrip() for ln in fh if ln.strip()]
    except OSError as exc:
        return _error_result(sample_id, str(exc))

    genotype: Optional[str] = None
    activity_score: Optional[float] = None
    phenotype: Optional[str] = None
    solutions = 0

    for line in lines:
        if line.startswith("#Solution"):
            solutions += 1
            if solutions == 1:
                m = re.search(r"cpic_score=([\d.]+)", line)
                if m:
                    activity_score = float(m.group(1))
                m = re.search(r"cpic=(\w+)", line)
                if m:
                    key = m.group(1).lower()
                    phenotype = _CPIC_MAP.get(key, key.title() + " Metabolizer")

    data_rows = [ln for ln in lines if not ln.startswith("#")]
    if data_rows:
        parts = data_rows[0].split("\t")
        if len(parts) > 3:
            genotype = parts[3]  # "Major" column

    if genotype is None:
        return _error_result(sample_id, "Could not parse genotype from TSV")

    alleles = genotype.split("/") if genotype and "/" in genotype else [genotype, "?"]
    allele_1 = alleles[0].strip()
    allele_2 = alleles[1].strip() if len(alleles) > 1 else "?"

    log.info(
        "[%s] Genotype=%s  ActivityScore=%s  Phenotype=%s",
        sample_id, genotype, activity_score, phenotype,
    )

    return {
        "sample_id": sample_id,
        "genotype": genotype,
        "allele_1": allele_1,
        "allele_2": allele_2,
        "activity_score": activity_score,
        "phenotype": phenotype,
        "solutions": solutions,
        "status": "ok",
    }


def _error_result(sample_id: str, msg: str) -> Dict[str, Any]:
    log.error("[%s] %s", sample_id, msg)
    return {
        "sample_id": sample_id,
        "genotype": None,
        "allele_1": None,
        "allele_2": None,
        "activity_score": None,
        "phenotype": None,
        "solutions": None,
        "status": "error",
        "error_msg": msg,
    }


# ── Step 4: S3 upload ─────────────────────────────────────────────────────────

def upload_to_s3(
    result: Dict[str, Any],
    population: str,
    bucket: str,
    prefix: str,
    sample_id: str,
) -> str:
    """
    Serialize result to JSON and upload to S3.

    Key layout:
        {prefix}/{population}/{sample_id}/aldy_output.json

    Returns
    -------
    str
        S3 URI of the uploaded object.
    """
    result["population"] = population

    parts = [p for p in [prefix, population, sample_id, "aldy_output.json"] if p]
    s3_key = "/".join(parts)

    s3_client = boto3.client("s3")
    body = json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=body,
        ContentType="application/json",
    )

    s3_uri = f"s3://{bucket}/{s3_key}"
    log.info("[%s] Uploaded result to %s", sample_id, s3_uri)
    return s3_uri


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = _read_config()
    sample_id = cfg["sample_id"]

    log.info(
        "Starting job: sample=%s  population=%s  region=%s",
        sample_id, cfg["population"], CYP2D6_REGION,
    )

    with tempfile.TemporaryDirectory(prefix=f"cyp2d6_{sample_id}_") as tmpdir:
        work_dir = Path(tmpdir)
        result: Dict[str, Any]

        try:
            bam_path = slice_bam(cfg["bam_url"], sample_id, work_dir)
            tsv_path = run_aldy(bam_path, sample_id, work_dir)
            result = parse_aldy_tsv(tsv_path, sample_id)
        except Exception as exc:
            log.exception("[%s] Job failed: %s", sample_id, exc)
            result = _error_result(sample_id, str(exc))

        # Always upload — even on error — so the aggregation step can tally failures.
        try:
            s3_uri = upload_to_s3(
                result,
                population=cfg["population"],
                bucket=cfg["output_bucket"],
                prefix=cfg["output_prefix"],
                sample_id=sample_id,
            )
            log.info("[%s] Done. Result at %s", sample_id, s3_uri)
        except Exception as upload_exc:
            log.critical(
                "[%s] S3 upload failed — result lost: %s", sample_id, upload_exc
            )
            sys.exit(1)

    if result["status"] != "ok":
        # Non-zero exit signals AWS Batch to mark the job as FAILED.
        sys.exit(1)


if __name__ == "__main__":
    main()
