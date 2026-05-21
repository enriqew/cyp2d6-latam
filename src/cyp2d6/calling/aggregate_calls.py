"""
aggregate_calls.py
------------------
Consolidates per-sample Aldy TSV outputs into a single DataFrame.

The aggregate table is the primary input for the Silver transformation layer.

Output schema
-------------
sample_id         : str   — 1000G sample identifier
population        : str   — MXL | PEL | CLM | PUR | CEU
genotype          : str   — Aldy diplotype (e.g. *1/*4, *5/*41)
allele_1          : str   — first star allele (e.g. *1)
allele_2          : str   — second star allele (e.g. *4)
activity_score    : float — sum of allele activity scores
phenotype         : str   — Aldy-reported phenotype (may differ from CPIC mapping)
solutions         : int   — number of equally-scoring Aldy solutions
status            : str   — ok | error
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd

from sample_manifest import POPULATION_SAMPLES

log = logging.getLogger(__name__)
RAW_DIR = Path(__file__).parents[3] / "data" / "raw"


# ── Sample → population lookup ────────────────────────────────────────────────

_SAMPLE_TO_POP: Dict[str, str] = {
    sample: pop
    for pop, samples in POPULATION_SAMPLES.items()
    for sample in samples
}


def _infer_population(sample_id: str) -> str:
    """Return population code for a sample ID, or 'UNKNOWN'."""
    return _SAMPLE_TO_POP.get(sample_id, "UNKNOWN")


# ── TSV parsing ───────────────────────────────────────────────────────────────

def _parse_one_tsv(tsv_path: Path) -> Dict[str, Any]:
    """Parse a single Aldy TSV and return a flat dict."""
    sample_id = tsv_path.stem.replace("_aldy", "")
    try:
        with open(tsv_path, encoding="utf-8") as fh:
            data_lines = [
                ln.strip()
                for ln in fh
                if ln.strip() and not ln.startswith("#")
            ]
    except OSError as exc:
        log.error("Cannot read %s: %s", tsv_path, exc)
        return {"sample_id": sample_id, "status": "error", "error_msg": str(exc)}

    if not data_lines:
        return {"sample_id": sample_id, "status": "error", "error_msg": "empty TSV"}

    parts = data_lines[0].split("\t")
    if len(parts) < 5:
        parts = data_lines[0].split()

    try:
        genotype = parts[2] if len(parts) > 2 else "unknown"
        activity_score = float(parts[3]) if len(parts) > 3 else 0.0
        phenotype = parts[4] if len(parts) > 4 else "unknown"
        solutions = int(parts[5]) if len(parts) > 5 else 1
    except (ValueError, IndexError) as exc:
        return {"sample_id": sample_id, "status": "error", "error_msg": str(exc)}

    # Split diplotype into individual alleles
    alleles = genotype.split("/") if "/" in genotype else [genotype, "unknown"]
    allele_1 = alleles[0].strip() if len(alleles) > 0 else "unknown"
    allele_2 = alleles[1].strip() if len(alleles) > 1 else "unknown"

    return {
        "sample_id": sample_id,
        "population": _infer_population(sample_id),
        "genotype": genotype,
        "allele_1": allele_1,
        "allele_2": allele_2,
        "activity_score": activity_score,
        "phenotype": phenotype,
        "solutions": solutions,
        "status": "ok",
    }


# ── Aggregate ─────────────────────────────────────────────────────────────────

def aggregate_aldy_calls(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """
    Read all *_aldy.tsv files in raw_dir and return a consolidated DataFrame.

    Parameters
    ----------
    raw_dir:
        Directory containing per-sample Aldy TSV outputs.

    Returns
    -------
    pd.DataFrame
        One row per sample with the schema described in the module docstring.
    """
    tsv_files = sorted(raw_dir.glob("*_aldy.tsv"))
    if not tsv_files:
        log.warning("No *_aldy.tsv files found in %s", raw_dir)
        return pd.DataFrame()

    log.info("Aggregating %d Aldy TSV files ...", len(tsv_files))
    rows = [_parse_one_tsv(f) for f in tsv_files]
    df = pd.DataFrame(rows)

    ok_count = (df["status"] == "ok").sum()
    err_count = (df["status"] == "error").sum()
    log.info("Aggregation complete: ok=%d  errors=%d", ok_count, err_count)

    if err_count > 0:
        log.warning("Samples with errors: %s",
                    df.loc[df["status"] == "error", "sample_id"].tolist())

    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    df = aggregate_aldy_calls()
    if df.empty:
        print("No data — run run_aldy.py first.")
    else:
        print(df.info())
        print(df.groupby(["population", "phenotype"]).size().rename("n").to_string())
