"""
run_aldy.py
-----------
Wrapper around Aldy for CYP2D6 star allele calling.

Aldy performs integrated SNP + CNV genotyping, which is required for CYP2D6
because standard VCF-based callers cannot detect:
  - *5 (complete gene deletion — poor metabolizer)
  - xN duplications (ultrarapid metabolizer, e.g. *1x2, *1x3)

Requirements
------------
    pip install aldy>=3.3
    # Reference genome: GRCh38/hg38 (Aldy downloads it automatically on first run,
    # or point ALDY_DB to a local copy)

Aldy output format (TSV)
------------------------
Columns: #Sample  Gene  Genotype  ActivityScore  Phenotype  Solutions
Example:
    NA19648  CYP2D6  *1/*4  1.00  Intermediate Metabolizer  1

Usage
-----
    python src/cyp2d6/calling/run_aldy.py --sample NA19648
    python src/cyp2d6/calling/run_aldy.py  # processes all sliced BAMs
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

BAM_DIR = Path(__file__).parents[3] / "data" / "bam_slices"
RAW_DIR = Path(__file__).parents[3] / "data" / "raw"

ALDY_GENE = "cyp2d6"
ALDY_PROFILE = "illumina"   # 1000G low-coverage WGS
ALDY_GENOME = "hg19"        # 1000G Phase 3 BAMs aligned to GRCh37/NCBI37


# ── Aldy invocation ───────────────────────────────────────────────────────────

def run_aldy_for_sample(sample_id: str) -> Dict[str, Any]:
    """
    Run Aldy on the pre-sliced BAM for `sample_id`.

    Returns
    -------
    dict with keys:
        sample_id, genotype, activity_score, phenotype, solutions, raw_tsv_path, status
    """
    bam_path = BAM_DIR / f"{sample_id}.bam"
    out_tsv = RAW_DIR / f"{sample_id}_aldy.tsv"

    if not bam_path.exists():
        log.error("[%s] BAM not found: %s — run slice_bams.py first", sample_id, bam_path)
        return _error_result(sample_id, f"BAM not found: {bam_path}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        "aldy", "genotype",
        "-g", ALDY_GENE,
        "-p", ALDY_PROFILE,
        "--genome", ALDY_GENOME,
        str(bam_path),
        "-o", str(out_tsv),
    ]

    log.info("[%s] Running Aldy ...", sample_id)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min per sample
        )
    except FileNotFoundError:
        log.critical("aldy not found — install with: pip install aldy>=3.3")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return _error_result(sample_id, "Aldy timeout after 1800s")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        log.error("[%s] Aldy failed (rc=%d): %s", sample_id, result.returncode, stderr)
        return _error_result(sample_id, stderr)

    # ── Parse TSV output ──────────────────────────────────────────────────────
    if not out_tsv.exists():
        return _error_result(sample_id, "Aldy produced no output TSV")

    parsed = _parse_aldy_tsv(out_tsv, sample_id)
    if parsed["status"] == "ok":
        log.info(
            "[%s] Genotype=%s  ActivityScore=%.2f  Phenotype=%s",
            sample_id,
            parsed.get("genotype", "?"),
            parsed.get("activity_score") or 0.0,
            parsed.get("phenotype", "?"),
        )
    return parsed


def _parse_aldy_tsv(tsv_path: Path, sample_id: str) -> Dict[str, Any]:
    """
    Parse Aldy v4 TSV output into a structured dict.

    Aldy v4 format (tab-separated, verified against v4.8.3):
      Header row:  #Sample Gene SolutionID Major Minor Copy Allele Location ...
      Comment rows: #Solution N: *X/*Y; cpic=<phenotype>; cpic_score=<float>
      Data rows:   one row per variant per copy

    Key fields:
      - Genotype: column "Major" (index 3) from the first data row
      - ActivityScore + Phenotype: parsed from the #Solution 1 comment line
    """
    _CPIC_MAP = {
        "normal": "Normal Metabolizer",
        "poor": "Poor Metabolizer",
        "intermediate": "Intermediate Metabolizer",
        "ultrarapid": "Ultrarapid Metabolizer",
        "rapid": "Rapid Metabolizer",
        "indeterminate": "Indeterminate",
    }

    try:
        with open(tsv_path, encoding="utf-8") as fh:
            lines = [ln.rstrip() for ln in fh if ln.strip()]
    except OSError as exc:
        return _error_result(sample_id, str(exc))

    genotype: str | None = None
    activity_score: float | None = None
    phenotype: str | None = None
    solutions = 0

    for line in lines:
        if line.startswith("#Solution"):
            solutions += 1
            if solutions == 1:
                m = re.search(r'cpic_score=([\d.]+)', line)
                if m:
                    activity_score = float(m.group(1))
                m = re.search(r'cpic=(\w+)', line)
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

    return {
        "sample_id": sample_id,
        "genotype": genotype,
        "activity_score": activity_score,
        "phenotype": phenotype,
        "solutions": solutions,
        "raw_tsv_path": str(tsv_path),
        "status": "ok",
    }


def _error_result(sample_id: str, msg: str) -> Dict[str, Any]:
    return {
        "sample_id": sample_id,
        "genotype": None,
        "activity_score": None,
        "phenotype": None,
        "solutions": None,
        "raw_tsv_path": None,
        "status": "error",
        "error_msg": msg,
    }


# ── Batch mode ────────────────────────────────────────────────────────────────

def run_all_samples() -> List[Dict[str, Any]]:
    """Run Aldy on all BAM slices found in BAM_DIR."""
    bam_files = sorted(BAM_DIR.glob("*.bam"))
    if not bam_files:
        log.warning("No BAM files found in %s", BAM_DIR)
        return []

    log.info("Found %d BAM files to process", len(bam_files))
    results = []
    for bam in bam_files:
        sample_id = bam.stem
        res = run_aldy_for_sample(sample_id)
        results.append(res)

    ok = sum(1 for r in results if r["status"] == "ok")
    errors = sum(1 for r in results if r["status"] == "error")
    log.info("Aldy calling complete: ok=%d  errors=%d", ok, errors)
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Aldy CYP2D6 star allele calling")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", metavar="SAMPLE_ID", help="Process a single sample")
    group.add_argument("--all", action="store_true", default=True,
                       help="Process all BAM slices in data/bam_slices/ (default)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.sample:
        result = run_aldy_for_sample(args.sample)
        import json
        print(json.dumps(result, indent=2))
    else:
        run_all_samples()
