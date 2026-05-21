"""
silver_diplotypes.py
--------------------
Silver layer: normalize Aldy diplotype calls to CPIC phenotype categories.

CPIC Activity Score Framework (CYP2D6)
---------------------------------------
https://cpicpgx.org/guidelines/guideline-for-codeine-and-cyp2d6/

  Ultrarapid Metabolizer (UM) : activity score > 2.0
  Normal Metabolizer (NM)     : 1.25 <= score <= 2.0
  Intermediate Metabolizer(IM): 0.25 <= score < 1.25
  Poor Metabolizer (PM)       : score == 0.0

Key star allele activity scores (CPIC/PharmVar definitions)
------------------------------------------------------------
  *1   : 1.0  — reference / normal function
  *2   : 1.0  — normal function
  *3   : 0.0  — nonfunctional (frameshift)
  *4   : 0.0  — nonfunctional; most common no-function allele in Europeans (~20%)
  *5   : 0.0  — gene deletion (no copies); cannot be detected by SNP VCF
  *6   : 0.0  — nonfunctional
  *10  : 0.25 — reduced function; elevated frequency in East Asians, present in MXL
  *17  : 0.5  — reduced function; elevated in African ancestry (relevant for PUR/CLM)
  *41  : 0.5  — reduced function; common in European populations
  *1xN : 1.0*N — ultrarapid (gene duplication x2, x3, etc.)
  *2xN : 1.0*N — ultrarapid

Notes
-----
- Activity scores are additive across the two alleles in a diplotype.
- Aldy reports the raw activity score; this module re-applies CPIC thresholds
  for consistency across callers/versions.
- *17/*17 has a combined score of 1.0 — classified as IM by CPIC thresholds,
  though some guidelines treat it as borderline NM.  Aldy may report NM for
  individual patients depending on additional haplotype evidence.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict

import pandas as pd

log = logging.getLogger(__name__)

# ── Activity score table ──────────────────────────────────────────────────────
# Maps canonical star allele string → per-allele activity score.
# For xN duplications, we use a regex at call time (see activity_score_for_allele).

ALLELE_ACTIVITY_SCORES: Dict[str, float] = {
    "*1":  1.0,
    "*2":  1.0,
    "*3":  0.0,
    "*4":  0.0,
    "*5":  0.0,   # gene deletion — zero copies, zero activity
    "*6":  0.0,
    "*7":  0.0,
    "*8":  0.0,
    "*9":  0.5,
    "*10": 0.25,
    "*11": 0.0,
    "*13": 0.0,   # nonfunctional gene conversion with CYP2D7
    "*14": 0.5,
    "*17": 0.5,
    "*29": 0.5,
    "*35": 1.0,   # uncertain/normal function (CPIC 2022)
    "*36": 0.0,   # nonfunctional
    "*39": 1.0,   # normal function (PharmVar)
    "*41": 0.5,
}

# Regex for xN duplications: *1x2, *2x3 (less common — Aldy v4 uses + notation instead)
_DUPLICATION_RE = re.compile(r"^(\*\d+)x(\d+)$", re.IGNORECASE)


def activity_score_for_allele(allele: str) -> float:
    """
    Return the CPIC activity score for a single star allele.

    Handles duplications (*1x2 → 2.0, *1x3 → 3.0) and unknown alleles
    (fallback to 1.0 with a warning).

    Parameters
    ----------
    allele : str
        Star allele string (e.g. "*4", "*1x2", "*41").

    Returns
    -------
    float
        Per-allele activity score.
    """
    allele = allele.strip()

    # Handle xN duplications (*1x2, *2x3)
    m = _DUPLICATION_RE.match(allele)
    if m:
        base_allele = m.group(1).lower()
        n_copies = int(m.group(2))
        base_score = ALLELE_ACTIVITY_SCORES.get(base_allele, 1.0)
        return base_score * n_copies

    # Handle Aldy v4 + notation: *1+*1 (tandem dup) or *4C+rs1058172 (modifier SNP)
    # Sum scores of all star-allele components; ignore rs-number suffixes.
    if "+" in allele:
        parts = [p.strip() for p in allele.split("+")]
        star_parts = [p for p in parts if p.startswith("*")]
        if star_parts:
            return sum(activity_score_for_allele(p) for p in star_parts)

    # Normalize: lowercase, strip trailing letters (e.g. *2A → *2, *4C → *4)
    normalized = re.sub(r"[a-z]+$", "", allele.lower())
    if normalized in ALLELE_ACTIVITY_SCORES:
        return ALLELE_ACTIVITY_SCORES[normalized]

    if allele in ALLELE_ACTIVITY_SCORES:
        return ALLELE_ACTIVITY_SCORES[allele]

    log.warning("Unknown allele '%s' — defaulting activity score to 1.0", allele)
    return 1.0


def diplotype_activity_score(allele_1: str, allele_2: str) -> float:
    """Sum of activity scores for both alleles in a diplotype."""
    return activity_score_for_allele(allele_1) + activity_score_for_allele(allele_2)


# ── Phenotype classification ──────────────────────────────────────────────────

def cpic_phenotype(activity_score: float) -> str:
    """
    Map a numeric activity score to the CPIC phenotype category.

    Parameters
    ----------
    activity_score : float
        Combined (diplotype) activity score.

    Returns
    -------
    str
        One of: "Ultrarapid Metabolizer", "Normal Metabolizer",
                "Intermediate Metabolizer", "Poor Metabolizer"
    """
    if activity_score > 2.0:
        return "Ultrarapid Metabolizer"
    elif activity_score >= 1.25:
        return "Normal Metabolizer"
    elif activity_score >= 0.25:
        return "Intermediate Metabolizer"
    else:
        return "Poor Metabolizer"


# ── DataFrame transformation ──────────────────────────────────────────────────

def apply_silver_phenotypes(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Add CPIC-normalized phenotype columns to the aggregated Aldy calls DataFrame.

    Input columns expected: sample_id, population, genotype, allele_1, allele_2,
                            activity_score (Aldy-reported), status

    Added columns:
        cpic_activity_score : float  — recomputed from CPIC allele table
        cpic_phenotype      : str    — CPIC phenotype category
        phenotype_short     : str    — UM | NM | IM | PM

    Parameters
    ----------
    df_raw : pd.DataFrame
        Output of aggregate_calls.aggregate_aldy_calls().

    Returns
    -------
    pd.DataFrame
        Input DataFrame with additional phenotype columns.
    """
    df = df_raw[df_raw["status"] == "ok"].copy()

    df["cpic_activity_score"] = df.apply(
        lambda row: diplotype_activity_score(row["allele_1"], row["allele_2"]),
        axis=1,
    )
    df["cpic_phenotype"] = df["cpic_activity_score"].apply(cpic_phenotype)

    short_map = {
        "Ultrarapid Metabolizer": "UM",
        "Normal Metabolizer": "NM",
        "Intermediate Metabolizer": "IM",
        "Poor Metabolizer": "PM",
    }
    df["phenotype_short"] = df["cpic_phenotype"].map(short_map)

    log.info(
        "Silver phenotypes applied to %d samples.  Distribution:\n%s",
        len(df),
        df.groupby(["population", "phenotype_short"]).size().rename("n").to_string(),
    )
    return df


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    # Import here to avoid circular dependency at module level
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from cyp2d6.calling.aggregate_calls import aggregate_aldy_calls

    df_raw = aggregate_aldy_calls()
    if df_raw.empty:
        print("No data — run run_aldy.py and aggregate_calls.py first.")
        sys.exit(0)

    df_silver = apply_silver_phenotypes(df_raw)
    silver_path = Path(__file__).parents[3] / "data" / "silver_diplotypes.parquet"
    df_silver.to_parquet(silver_path, index=False)
    print(f"Silver table saved: {silver_path}  ({len(df_silver)} rows)")
