"""
slice_bams.py
-------------
Remote BAM slicing for the CYP2D6 locus (22:42,400,000-42,650,000, GRCh37/hg19).

Strategy
--------
1000 Genomes Phase 3 BAMs total ~5 TB. Rather than downloading full files,
samtools can stream only the region of interest over HTTP/HTTPS using the
remote index (.bai). This reduces per-sample transfer from ~15 GB to ~50 MB.

Total data volume estimate:
    452 samples x ~50 MB/sample ~= 23 GB

Requirements
------------
- samtools >= 1.16 (must be on PATH)
- curl-based HTTPS support in samtools (check with: samtools view --help)

Usage
-----
    python ingest/slice_bams.py [--workers 8] [--populations MXL PEL CLM PUR CEU]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sample_manifest import SampleEntry, build_manifest

# ── Constants ────────────────────────────────────────────────────────────────
# GRCh37/hg19 coordinates — 1000G Phase 3 BAMs use NCBI37, not GRCh38.
# Chromosomes have no "chr" prefix. CYP2D6 locus ~42.52 Mb; 200 kb window
# covers CYP2D6 + CYP2D7 pseudogene cluster needed for Aldy CNV calling.
CYP2D6_REGION = "22:42400000-42650000"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "bam_slices"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Core functions ────────────────────────────────────────────────────────────

def slice_one(entry: SampleEntry, output_dir: Path) -> dict:
    """
    Slice the CYP2D6 region from a remote BAM and index the result.

    Returns a status dict: {"sample": ..., "status": "ok"|"error", "msg": ...}
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_bam = output_dir / f"{entry.sample_id}.bam"

    if out_bam.exists():
        log.info("[%s] Already exists — skipping", entry.sample_id)
        return {"sample": entry.sample_id, "status": "skipped", "msg": "already exists"}

    # ── Step 1: slice region from remote BAM ─────────────────────────────────
    slice_cmd = [
        "samtools", "view",
        "-b",                        # output BAM
        "-o", str(out_bam),
        entry.bam_url,               # remote URL (samtools fetches via HTTPS)
        CYP2D6_REGION,
    ]
    log.info("[%s] Slicing %s ...", entry.sample_id, CYP2D6_REGION)
    try:
        result = subprocess.run(
            slice_cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max per sample
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "non-zero exit"
            log.error("[%s] slice failed: %s", entry.sample_id, msg)
            return {"sample": entry.sample_id, "status": "error", "msg": msg}
    except subprocess.TimeoutExpired:
        msg = "timeout after 600s"
        log.error("[%s] %s", entry.sample_id, msg)
        return {"sample": entry.sample_id, "status": "error", "msg": msg}
    except FileNotFoundError:
        msg = "samtools not found — install samtools and ensure it is on PATH"
        log.critical(msg)
        sys.exit(1)

    # ── Step 2: index the sliced BAM ─────────────────────────────────────────
    index_cmd = ["samtools", "index", str(out_bam)]
    log.info("[%s] Indexing ...", entry.sample_id)
    try:
        result = subprocess.run(
            index_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "index non-zero exit"
            log.error("[%s] index failed: %s", entry.sample_id, msg)
            return {"sample": entry.sample_id, "status": "error", "msg": msg}
    except subprocess.TimeoutExpired:
        msg = "index timeout after 120s"
        log.error("[%s] %s", entry.sample_id, msg)
        return {"sample": entry.sample_id, "status": "error", "msg": msg}

    log.info("[%s] Done -> %s", entry.sample_id, out_bam)
    return {"sample": entry.sample_id, "status": "ok", "msg": str(out_bam)}


def run_slicing(
    populations: list[str] | None = None,
    workers: int = 8,
    output_dir: Path = OUTPUT_DIR,
) -> list[dict]:
    """
    Slice all samples in parallel using ThreadPoolExecutor.

    Parameters
    ----------
    populations:
        Subset of populations to process. None = all.
    workers:
        Number of parallel samtools processes.
    output_dir:
        Where to write the .bam slices.

    Returns
    -------
    list[dict]
        One status dict per sample.
    """
    manifest = build_manifest(populations)
    log.info(
        "Slicing %d samples across populations: %s  (workers=%d)",
        len(manifest),
        populations or "all",
        workers,
    )

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(slice_one, entry, output_dir): entry for entry in manifest}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                res = future.result()
            except Exception as exc:
                res = {"sample": entry.sample_id, "status": "error", "msg": str(exc)}
            results.append(res)

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = sum(1 for r in results if r["status"] == "error")
    log.info("Finished: ok=%d  skipped=%d  errors=%d", ok, skipped, errors)

    if errors:
        log.warning("Failed samples:")
        for r in results:
            if r["status"] == "error":
                log.warning("  %s: %s", r["sample"], r["msg"])

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Slice CYP2D6 region from remote 1000G BAMs"
    )
    parser.add_argument(
        "--populations",
        nargs="+",
        default=None,
        metavar="POP",
        help="Populations to process (default: all). E.g. --populations MXL PEL",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel samtools processes (default: 8)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory for BAM slices (default: {OUTPUT_DIR})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_slicing(
        populations=args.populations,
        workers=args.workers,
        output_dir=args.output_dir,
    )
