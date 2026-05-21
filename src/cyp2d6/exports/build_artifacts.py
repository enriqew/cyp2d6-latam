"""
build_artifacts.py
------------------
Generates JSON artifacts for the portfolio from Gold Parquet tables.

These JSON files are committed into the portfolio repo under src/data/cyp2d6/
and imported directly by the React visualisation component — no runtime API.

Output files
------------
  allele_frequencies.json        — per-allele frequency by population
  phenotype_distribution.json    — UM/NM/IM/PM % by population
  drug_impact_summary.json       — dose adjustment % by drug + population
  metadata.json                  — run date, sample counts, pipeline version

Usage
-----
    python src/cyp2d6/exports/build_artifacts.py
    # then copy data/exports/*.json to the portfolio repo's src/data/cyp2d6/
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pandas as pd

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

REPO_ROOT = Path(__file__).parents[3]
DATA_DIR = REPO_ROOT / "data"
EXPORTS_DIR = DATA_DIR / "exports"
PARQUET_FILES = {
    "allele_frequencies": DATA_DIR / "gold_allele_frequencies.parquet",
    "phenotype_distribution": DATA_DIR / "gold_phenotype_distribution.parquet",
    "drug_impact_summary": DATA_DIR / "gold_drug_impact_summary.parquet",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_parquet(key: str) -> pd.DataFrame:
    path = PARQUET_FILES[key]
    if not path.exists():
        log.error("Parquet not found: %s — run gold_aggregates.py first", path)
        sys.exit(1)
    return pd.read_parquet(path)


def _write_json(data: Any, filename: str) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORTS_DIR / filename
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    log.info("Written: %s  (%d bytes)", out, out.stat().st_size)
    return out


# ── Artifact builders ─────────────────────────────────────────────────────────

def build_allele_frequencies_json() -> Dict:
    df = _load_parquet("allele_frequencies")
    return df.to_dict(orient="records")


def build_phenotype_distribution_json() -> Dict:
    df = _load_parquet("phenotype_distribution")
    return df.to_dict(orient="records")


def build_drug_impact_summary_json() -> Dict:
    df = _load_parquet("drug_impact_summary")
    return df.to_dict(orient="records")


def build_metadata_json(
    df_allele: pd.DataFrame,
    df_pheno: pd.DataFrame,
    df_drug: pd.DataFrame,
) -> Dict:
    """Build a metadata summary for the portfolio."""
    # Infer sample counts from phenotype_distribution (n_total per population)
    pop_counts = (
        df_pheno[df_pheno["phenotype"] == "NM"][["population", "n_total"]]
        .set_index("population")["n_total"]
        .to_dict()
    )

    return {
        "gene": "CYP2D6",
        "pipeline_version": "1.0.0",
        "run_date": date.today().isoformat(),
        "reference_genome": "GRCh37/hg19",
        "caller": "Aldy v4.8.3",
        "source": "1000 Genomes Phase 3 — low-coverage WGS BAM slices",
        "region_sliced": "22:42,400,000–42,650,000",
        "populations": {
            "MXL": {"label": "Mexican Ancestry (Los Angeles)", "n": pop_counts.get("MXL", 0)},
            "PEL": {"label": "Peruvians (Lima)", "n": pop_counts.get("PEL", 0)},
            "CLM": {"label": "Colombians (Medellin)", "n": pop_counts.get("CLM", 0)},
            "PUR": {"label": "Puerto Ricans", "n": pop_counts.get("PUR", 0)},
            "CEU": {"label": "European Reference (CEPH/Utah)", "n": pop_counts.get("CEU", 0)},
        },
        "n_alleles_reported": int(df_allele["allele"].nunique()),
        "drugs_covered": list(df_drug["drug"].unique()),
        "phenotype_categories": ["UM", "NM", "IM", "PM"],
        "limitations": [
            "Low-coverage WGS (~4x) — Aldy CNV detection less reliable below 10x",
            "16/452 samples excluded: average coverage below Aldy threshold",
            "Ultrarapid duplication counts depend on read depth at gene boundaries",
            "Indeterminate calls reflect novel/complex alleles not yet in CPIC — common in admixed LATAM populations",
        ],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Building portfolio JSON artifacts from Gold tables ...")

    df_allele = _load_parquet("allele_frequencies")
    df_pheno = _load_parquet("phenotype_distribution")
    df_drug = _load_parquet("drug_impact_summary")

    _write_json(build_allele_frequencies_json(), "allele_frequencies.json")
    _write_json(build_phenotype_distribution_json(), "phenotype_distribution.json")
    _write_json(build_drug_impact_summary_json(), "drug_impact_summary.json")
    _write_json(build_metadata_json(df_allele, df_pheno, df_drug), "metadata.json")

    log.info("All artifacts written to %s", EXPORTS_DIR)
    log.info(
        "Next step: copy %s/*.json to "
        "<portfolio-repo>/src/data/cyp2d6/",
        EXPORTS_DIR,
    )


if __name__ == "__main__":
    main()
