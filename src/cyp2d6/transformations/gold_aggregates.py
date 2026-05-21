"""
gold_aggregates.py
------------------
Gold layer: population-level aggregates for allele frequencies, phenotype
distributions, and drug impact summaries.

Output schema matches the pgx-latam-atlas Gold layer for cross-gene comparisons.

Three Gold tables
-----------------
1. allele_frequencies
   allele | population | frequency | n_carriers | n_total

2. phenotype_distribution
   phenotype | population | percentage | n_samples | n_total

3. drug_impact_summary
   drug | population | pct_requiring_adjustment | n_affected | n_total | recommendation

CPIC A-level drugs for CYP2D6 (as of CPIC v1.9)
-------------------------------------------------
https://cpicpgx.org/genes-drugs/

  codeine    : PM → avoid (no conversion to morphine, risk of inefficacy)
               UM → avoid (excessive morphine conversion, respiratory depression)
  tramadol   : Same recommendations as codeine
  tamoxifen  : PM → consider alternative (reduced endoxifen formation)
               IM → standard dose with monitoring
  amitriptyline: PM → reduce dose 50% (tricyclic accumulation)
                 IM → reduce dose 25%
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

log = logging.getLogger(__name__)

# ── Drug impact rules ─────────────────────────────────────────────────────────
# Structure: {drug: {phenotype_short: recommendation}}
# Only phenotypes that require dose adjustment are listed.

DRUG_IMPACT_RULES: Dict[str, Dict[str, str]] = {
    "codeine": {
        "PM": "Avoid — no conversion to morphine; risk of inefficacy",
        "UM": "Avoid — excessive morphine; risk of respiratory depression",
    },
    "tramadol": {
        "PM": "Avoid — no conversion to active metabolite; risk of inefficacy",
        "UM": "Avoid — excessive active metabolite; risk of CNS toxicity",
    },
    "tamoxifen": {
        "PM": "Consider alternative — reduced endoxifen formation",
        "IM": "Standard dose with increased monitoring",
    },
    "amitriptyline": {
        "PM": "Reduce dose 50% — risk of tricyclic accumulation",
        "IM": "Reduce dose 25% — risk of mild accumulation",
    },
}


# ── Gold table 1: allele frequencies ─────────────────────────────────────────

def build_allele_frequencies(df_silver: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-allele frequencies for each population.

    Parameters
    ----------
    df_silver : pd.DataFrame
        Output of silver_diplotypes.apply_silver_phenotypes().
        Must have columns: sample_id, population, allele_1, allele_2.

    Returns
    -------
    pd.DataFrame
        Columns: allele, population, frequency, n_carriers, n_total
    """
    rows: List[Dict] = []

    for pop, group in df_silver.groupby("population"):
        n_total = len(group)
        # Each sample contributes 2 alleles
        all_alleles = pd.concat([group["allele_1"], group["allele_2"]], ignore_index=True)
        allele_counts = all_alleles.value_counts()
        total_alleles = len(all_alleles)  # 2 * n_samples

        for allele, count in allele_counts.items():
            # n_carriers = samples that carry at least one copy of this allele
            n_carriers = int(
                ((group["allele_1"] == allele) | (group["allele_2"] == allele)).sum()
            )
            rows.append({
                "allele": allele,
                "population": pop,
                "frequency": round(count / total_alleles, 4),
                "n_carriers": n_carriers,
                "n_total": n_total,
            })

    df = pd.DataFrame(rows).sort_values(
        ["population", "frequency"], ascending=[True, False]
    ).reset_index(drop=True)

    log.info("Gold allele_frequencies: %d rows", len(df))
    return df


# ── Gold table 2: phenotype distribution ─────────────────────────────────────

def build_phenotype_distribution(df_silver: pd.DataFrame) -> pd.DataFrame:
    """
    Compute phenotype distribution (% UM/NM/IM/PM) per population.

    Parameters
    ----------
    df_silver : pd.DataFrame
        Must have columns: population, phenotype_short.

    Returns
    -------
    pd.DataFrame
        Columns: phenotype, population, percentage, n_samples, n_total
    """
    rows: List[Dict] = []

    for pop, group in df_silver.groupby("population"):
        n_total = len(group)
        pheno_counts = group["phenotype_short"].value_counts()

        for pheno in ["UM", "NM", "IM", "PM"]:
            n = int(pheno_counts.get(pheno, 0))
            rows.append({
                "phenotype": pheno,
                "population": pop,
                "percentage": round(100.0 * n / n_total, 2) if n_total > 0 else 0.0,
                "n_samples": n,
                "n_total": n_total,
            })

    df = pd.DataFrame(rows).sort_values(["population", "phenotype"]).reset_index(drop=True)
    log.info("Gold phenotype_distribution: %d rows", len(df))
    return df


# ── Gold table 3: drug impact summary ────────────────────────────────────────

def build_drug_impact_summary(
    df_silver: pd.DataFrame,
    rules: Dict[str, Dict[str, str]] = DRUG_IMPACT_RULES,
) -> pd.DataFrame:
    """
    Compute the percentage of patients requiring dose adjustment per drug per population.

    Parameters
    ----------
    df_silver : pd.DataFrame
        Must have columns: population, phenotype_short.
    rules : dict
        DRUG_IMPACT_RULES or a custom override.

    Returns
    -------
    pd.DataFrame
        Columns: drug, population, pct_requiring_adjustment, n_affected, n_total,
                 recommendation
    """
    rows: List[Dict] = []

    for pop, group in df_silver.groupby("population"):
        n_total = len(group)

        for drug, pheno_recommendations in rules.items():
            affected_mask = group["phenotype_short"].isin(pheno_recommendations.keys())
            n_affected = int(affected_mask.sum())

            # Build a combined recommendation string for all affected phenotypes
            relevant_phenos = group.loc[affected_mask, "phenotype_short"].unique()
            rec_parts = [
                f"{p}: {pheno_recommendations[p]}"
                for p in sorted(relevant_phenos)
                if p in pheno_recommendations
            ]
            recommendation = " | ".join(rec_parts) if rec_parts else "No adjustment"

            rows.append({
                "drug": drug,
                "population": pop,
                "pct_requiring_adjustment": round(
                    100.0 * n_affected / n_total, 2
                ) if n_total > 0 else 0.0,
                "n_affected": n_affected,
                "n_total": n_total,
                "recommendation": recommendation,
            })

    df = pd.DataFrame(rows).sort_values(["drug", "population"]).reset_index(drop=True)
    log.info("Gold drug_impact_summary: %d rows", len(df))
    return df


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    sys.path.insert(0, str(Path(__file__).parents[2]))
    from cyp2d6.calling.aggregate_calls import aggregate_aldy_calls
    from cyp2d6.transformations.silver_diplotypes import apply_silver_phenotypes

    df_raw = aggregate_aldy_calls()
    if df_raw.empty:
        print("No data — run the calling pipeline first.")
        sys.exit(0)

    df_silver = apply_silver_phenotypes(df_raw)
    df_silver = df_silver[df_silver["population"] != "UNKNOWN"]

    df_allele_freq = build_allele_frequencies(df_silver)
    df_pheno_dist = build_phenotype_distribution(df_silver)
    df_drug_impact = build_drug_impact_summary(df_silver)

    data_dir = Path(__file__).parents[3] / "data"
    data_dir.mkdir(exist_ok=True)

    df_allele_freq.to_parquet(data_dir / "gold_allele_frequencies.parquet", index=False)
    df_pheno_dist.to_parquet(data_dir / "gold_phenotype_distribution.parquet", index=False)
    df_drug_impact.to_parquet(data_dir / "gold_drug_impact_summary.parquet", index=False)

    print("Gold tables saved:")
    print(f"  allele_frequencies:    {len(df_allele_freq)} rows")
    print(f"  phenotype_distribution: {len(df_pheno_dist)} rows")
    print(f"  drug_impact_summary:   {len(df_drug_impact)} rows")
