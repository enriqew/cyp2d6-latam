"""
test_gold_aggregates.py
-----------------------
Unit tests for the Gold aggregation layer.

Uses a small synthetic DataFrame to validate allele_frequencies,
phenotype_distribution, and drug_impact_summary outputs.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cyp2d6.transformations.gold_aggregates import (
    build_allele_frequencies,
    build_phenotype_distribution,
    build_drug_impact_summary,
    DRUG_IMPACT_RULES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_silver() -> pd.DataFrame:
    """
    4 samples across 2 populations covering all 4 phenotype categories.

    MXL:
      S1: *1/*1  → NM  (score 2.0)
      S2: *4/*4  → PM  (score 0.0)

    PEL:
      S3: *1/*4  → IM  (score 1.0)
      S4: *1x2/*1 → UM (score 3.0)
    """
    data = [
        {
            "sample_id": "S1", "population": "MXL",
            "genotype": "*1/*1", "allele_1": "*1", "allele_2": "*1",
            "cpic_activity_score": 2.0, "cpic_phenotype": "Normal Metabolizer",
            "phenotype_short": "NM", "status": "ok",
        },
        {
            "sample_id": "S2", "population": "MXL",
            "genotype": "*4/*4", "allele_1": "*4", "allele_2": "*4",
            "cpic_activity_score": 0.0, "cpic_phenotype": "Poor Metabolizer",
            "phenotype_short": "PM", "status": "ok",
        },
        {
            "sample_id": "S3", "population": "PEL",
            "genotype": "*1/*4", "allele_1": "*1", "allele_2": "*4",
            "cpic_activity_score": 1.0, "cpic_phenotype": "Intermediate Metabolizer",
            "phenotype_short": "IM", "status": "ok",
        },
        {
            "sample_id": "S4", "population": "PEL",
            "genotype": "*1x2/*1", "allele_1": "*1x2", "allele_2": "*1",
            "cpic_activity_score": 3.0, "cpic_phenotype": "Ultrarapid Metabolizer",
            "phenotype_short": "UM", "status": "ok",
        },
    ]
    return pd.DataFrame(data)


# ── allele_frequencies ────────────────────────────────────────────────────────

class TestBuildAlleleFrequencies:
    def test_returns_dataframe(self, synthetic_silver):
        df = build_allele_frequencies(synthetic_silver)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns(self, synthetic_silver):
        df = build_allele_frequencies(synthetic_silver)
        required = {"allele", "population", "frequency", "n_carriers", "n_total"}
        assert required.issubset(df.columns)

    def test_mxl_star4_frequency(self, synthetic_silver):
        """MXL has 2 samples, both alleles *4 in S2 → *4 freq = 2/4 = 0.5"""
        df = build_allele_frequencies(synthetic_silver)
        row = df[(df["population"] == "MXL") & (df["allele"] == "*4")]
        assert len(row) == 1
        assert row.iloc[0]["frequency"] == pytest.approx(0.5)

    def test_frequency_sums_to_one_per_population(self, synthetic_silver):
        """Allele frequencies must sum to 1.0 per population."""
        df = build_allele_frequencies(synthetic_silver)
        for pop, group in df.groupby("population"):
            total = group["frequency"].sum()
            assert total == pytest.approx(1.0, abs=0.01), \
                f"Population {pop}: frequencies sum to {total:.4f}, expected 1.0"

    def test_n_total_correct(self, synthetic_silver):
        """n_total should equal sample count per population."""
        df = build_allele_frequencies(synthetic_silver)
        mxl_rows = df[df["population"] == "MXL"]
        assert (mxl_rows["n_total"] == 2).all()

    def test_n_carriers_does_not_exceed_n_total(self, synthetic_silver):
        df = build_allele_frequencies(synthetic_silver)
        assert (df["n_carriers"] <= df["n_total"]).all()


# ── phenotype_distribution ────────────────────────────────────────────────────

class TestBuildPhenotypeDistribution:
    def test_returns_dataframe(self, synthetic_silver):
        df = build_phenotype_distribution(synthetic_silver)
        assert isinstance(df, pd.DataFrame)

    def test_required_columns(self, synthetic_silver):
        df = build_phenotype_distribution(synthetic_silver)
        required = {"phenotype", "population", "percentage", "n_samples", "n_total"}
        assert required.issubset(df.columns)

    def test_all_four_phenotypes_present_per_pop(self, synthetic_silver):
        df = build_phenotype_distribution(synthetic_silver)
        for pop in ["MXL", "PEL"]:
            phenos = set(df[df["population"] == pop]["phenotype"])
            assert {"UM", "NM", "IM", "PM"}.issubset(phenos)

    def test_percentages_sum_to_100(self, synthetic_silver):
        df = build_phenotype_distribution(synthetic_silver)
        for pop, group in df.groupby("population"):
            total = group["percentage"].sum()
            assert total == pytest.approx(100.0, abs=0.1), \
                f"{pop}: percentages sum to {total:.2f}, expected 100.0"

    def test_mxl_pm_50_percent(self, synthetic_silver):
        """MXL: 1 PM out of 2 → 50%"""
        df = build_phenotype_distribution(synthetic_silver)
        row = df[(df["population"] == "MXL") & (df["phenotype"] == "PM")]
        assert row.iloc[0]["percentage"] == pytest.approx(50.0)

    def test_mxl_nm_50_percent(self, synthetic_silver):
        """MXL: 1 NM out of 2 → 50%"""
        df = build_phenotype_distribution(synthetic_silver)
        row = df[(df["population"] == "MXL") & (df["phenotype"] == "NM")]
        assert row.iloc[0]["percentage"] == pytest.approx(50.0)

    def test_pel_um_50_percent(self, synthetic_silver):
        """PEL: 1 UM out of 2 → 50%"""
        df = build_phenotype_distribution(synthetic_silver)
        row = df[(df["population"] == "PEL") & (df["phenotype"] == "UM")]
        assert row.iloc[0]["percentage"] == pytest.approx(50.0)


# ── drug_impact_summary ───────────────────────────────────────────────────────

class TestBuildDrugImpactSummary:
    def test_returns_dataframe(self, synthetic_silver):
        df = build_drug_impact_summary(synthetic_silver)
        assert isinstance(df, pd.DataFrame)

    def test_required_columns(self, synthetic_silver):
        df = build_drug_impact_summary(synthetic_silver)
        required = {
            "drug", "population", "pct_requiring_adjustment",
            "n_affected", "n_total", "recommendation",
        }
        assert required.issubset(df.columns)

    def test_all_drugs_present(self, synthetic_silver):
        df = build_drug_impact_summary(synthetic_silver)
        expected_drugs = set(DRUG_IMPACT_RULES.keys())
        assert expected_drugs.issubset(set(df["drug"]))

    def test_codeine_mxl_pm_affected(self, synthetic_silver):
        """MXL has 1 PM (S2) → codeine 1 affected out of 2 = 50%"""
        df = build_drug_impact_summary(synthetic_silver)
        row = df[(df["drug"] == "codeine") & (df["population"] == "MXL")]
        assert row.iloc[0]["n_affected"] == 1
        assert row.iloc[0]["pct_requiring_adjustment"] == pytest.approx(50.0)

    def test_codeine_pel_um_affected(self, synthetic_silver):
        """PEL has 1 UM (S4) → codeine 1 affected out of 2 = 50%"""
        df = build_drug_impact_summary(synthetic_silver)
        row = df[(df["drug"] == "codeine") & (df["population"] == "PEL")]
        assert row.iloc[0]["n_affected"] == 1

    def test_tamoxifen_pel_im_affected(self, synthetic_silver):
        """PEL has 1 IM (S3) → tamoxifen 1 affected out of 2 = 50%"""
        df = build_drug_impact_summary(synthetic_silver)
        row = df[(df["drug"] == "tamoxifen") & (df["population"] == "PEL")]
        assert row.iloc[0]["n_affected"] == 1

    def test_recommendation_not_empty_when_affected(self, synthetic_silver):
        df = build_drug_impact_summary(synthetic_silver)
        affected = df[df["n_affected"] > 0]
        assert (affected["recommendation"].str.len() > 0).all()

    def test_pct_between_0_and_100(self, synthetic_silver):
        df = build_drug_impact_summary(synthetic_silver)
        assert (df["pct_requiring_adjustment"] >= 0.0).all()
        assert (df["pct_requiring_adjustment"] <= 100.0).all()
