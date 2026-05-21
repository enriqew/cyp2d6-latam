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

_CPIC_MAP = {
    "normal": "Normal Metabolizer",
    "poor": "Poor Metabolizer",
    "intermediate": "Intermediate Metabolizer",
    "ultrarapid": "Ultrarapid Metabolizer",
    "rapid": "Rapid Metabolizer",
    "indeterminate": "Indeterminate",
}


def _parse_one_tsv(tsv_path: Path) -> Dict[str, Any]:
    """
    Parse a single Aldy v4 TSV and return a flat dict.

    Aldy v4 format: genotype is in column "Major" (index 3) of data rows;
    activity score and CPIC phenotype come from the #Solution comment line.
    """
    sample_id = tsv_path.stem.replace("_aldy", "")
    try:
        with open(tsv_path, encoding="utf-8") as fh:
            lines = [ln.rstrip() for ln in fh if ln.strip()]
    except OSError as exc:
        log.error("Cannot read %s: %s", tsv_path, exc)
        return {"sample_id": sample_id, "status": "error", "error_msg": str(exc)}

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
        return {"sample_id": sample_id, "status": "error", "error_msg": "empty or unparseable TSV"}

    alleles = genotype.split("/") if "/" in genotype else [genotype, "unknown"]
    allele_1 = alleles[0].strip()
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
