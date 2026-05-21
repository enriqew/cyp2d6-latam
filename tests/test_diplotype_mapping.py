"""
test_diplotype_mapping.py
-------------------------
Unit tests for the Silver diplotype → phenotype mapping.

Covers CPIC activity score computation and phenotype classification for
the most clinically relevant CYP2D6 allele combinations in LATAM populations.
"""

import sys
from pathlib import Path

import pytest

# Ensure src/ is on the path for imports
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from cyp2d6.transformations.silver_diplotypes import (
    activity_score_for_allele,
    diplotype_activity_score,
    cpic_phenotype,
)


# ── activity_score_for_allele ─────────────────────────────────────────────────

class TestActivityScoreForAllele:
    def test_star1_is_one(self):
        assert activity_score_for_allele("*1") == 1.0

    def test_star4_is_zero(self):
        """*4 is the most common no-function allele in Europeans."""
        assert activity_score_for_allele("*4") == 0.0

    def test_star5_is_zero(self):
        """*5 is a complete gene deletion — zero activity."""
        assert activity_score_for_allele("*5") == 0.0

    def test_star10_is_reduced(self):
        """*10 has reduced function (0.25); elevated in East Asians / MXL."""
        assert activity_score_for_allele("*10") == 0.25

    def test_star17_is_reduced(self):
        """*17 has reduced function (0.5); elevated in African ancestry (PUR/CLM)."""
        assert activity_score_for_allele("*17") == 0.5

    def test_star41_is_reduced(self):
        assert activity_score_for_allele("*41") == 0.5

    def test_ultrarapid_duplication_x2(self):
        """*1x2 = 1.0 * 2 = 2.0"""
        assert activity_score_for_allele("*1x2") == pytest.approx(2.0)

    def test_ultrarapid_duplication_x3(self):
        """*1x3 = 1.0 * 3 = 3.0"""
        assert activity_score_for_allele("*1x3") == pytest.approx(3.0)

    def test_star2_duplication(self):
        """*2x2 = 1.0 * 2 = 2.0"""
        assert activity_score_for_allele("*2x2") == pytest.approx(2.0)


# ── diplotype_activity_score ──────────────────────────────────────────────────

class TestDiplotypeActivityScore:
    def test_star1_star1_normal(self):
        """*1/*1 → score 2.0 (Normal Metabolizer)"""
        assert diplotype_activity_score("*1", "*1") == pytest.approx(2.0)

    def test_star4_star4_poor(self):
        """*4/*4 → score 0.0 (Poor Metabolizer)"""
        assert diplotype_activity_score("*4", "*4") == pytest.approx(0.0)

    def test_star5_star5_poor_gene_deletion(self):
        """*5/*5 → score 0.0; both copies deleted (homozygous deletion)."""
        assert diplotype_activity_score("*5", "*5") == pytest.approx(0.0)

    def test_star10_star10_intermediate(self):
        """*10/*10 → score 0.5 (Intermediate Metabolizer)"""
        assert diplotype_activity_score("*10", "*10") == pytest.approx(0.5)

    def test_star1_star4_intermediate(self):
        """*1/*4 → score 1.0 (Intermediate Metabolizer, borderline)"""
        assert diplotype_activity_score("*1", "*4") == pytest.approx(1.0)

    def test_star17_star17_intermediate(self):
        """*17/*17 → score 1.0 (IM by CPIC thresholds; Aldy may report NM)."""
        assert diplotype_activity_score("*17", "*17") == pytest.approx(1.0)

    def test_star41_star41_intermediate(self):
        """*41/*41 → score 1.0 (Intermediate Metabolizer)"""
        assert diplotype_activity_score("*41", "*41") == pytest.approx(1.0)

    def test_ultrarapid_xn_star1(self):
        """*1xN/*1 → score > 2.0 → Ultrarapid Metabolizer"""
        score = diplotype_activity_score("*1x2", "*1")
        assert score == pytest.approx(3.0)


# ── cpic_phenotype ────────────────────────────────────────────────────────────

class TestCpicPhenotype:
    @pytest.mark.parametrize("allele_1,allele_2,expected_phenotype", [
        # (1) *1/*1 → NM (score 2.0, exactly at boundary)
        ("*1",    "*1",    "Normal Metabolizer"),
        # (2) *4/*4 → PM (score 0.0)
        ("*4",    "*4",    "Poor Metabolizer"),
        # (3) *5/*5 → PM (gene deletion, score 0.0)
        ("*5",    "*5",    "Poor Metabolizer"),
        # (4) *10/*10 → IM (score 0.5)
        ("*10",   "*10",   "Intermediate Metabolizer"),
        # (5) *1x2/*1 → UM (score 3.0)
        ("*1x2",  "*1",    "Ultrarapid Metabolizer"),
        # (6) *1/*4 → IM (score 1.0)
        ("*1",    "*4",    "Intermediate Metabolizer"),
        # (7) *17/*17 → IM (score 1.0; borderline but below 1.25 threshold)
        ("*17",   "*17",   "Intermediate Metabolizer"),
        # (8) *41/*41 → IM (score 1.0)
        ("*41",   "*41",   "Intermediate Metabolizer"),
        # Additional edge cases
        # (9) *1/*2 → NM (score 2.0)
        ("*1",    "*2",    "Normal Metabolizer"),
        # (10) *1x3/*1 → UM (score 4.0)
        ("*1x3",  "*1",    "Ultrarapid Metabolizer"),
        # (11) *1/*41 → NM (score 1.5, within 1.25–2.0)
        ("*1",    "*41",   "Normal Metabolizer"),
        # (12) *4/*5 → PM (score 0.0; heterozygous deletion)
        ("*4",    "*5",    "Poor Metabolizer"),
    ])
    def test_phenotype_classification(self, allele_1, allele_2, expected_phenotype):
        score = diplotype_activity_score(allele_1, allele_2)
        result = cpic_phenotype(score)
        assert result == expected_phenotype, (
            f"Diplotype {allele_1}/{allele_2} (score={score:.2f}) "
            f"expected '{expected_phenotype}', got '{result}'"
        )

    def test_boundary_um_above_2(self):
        """Score 2.01 → UM"""
        assert cpic_phenotype(2.01) == "Ultrarapid Metabolizer"

    def test_boundary_nm_exactly_2(self):
        """Score 2.0 → NM (not UM)"""
        assert cpic_phenotype(2.0) == "Normal Metabolizer"

    def test_boundary_nm_1_25(self):
        """Score 1.25 → NM"""
        assert cpic_phenotype(1.25) == "Normal Metabolizer"

    def test_boundary_im_below_1_25(self):
        """Score 1.24 → IM"""
        assert cpic_phenotype(1.24) == "Intermediate Metabolizer"

    def test_boundary_im_0_25(self):
        """Score 0.25 → IM"""
        assert cpic_phenotype(0.25) == "Intermediate Metabolizer"

    def test_boundary_pm_below_0_25(self):
        """Score 0.24 → PM"""
        assert cpic_phenotype(0.24) == "Poor Metabolizer"

    def test_boundary_pm_zero(self):
        """Score 0.0 → PM"""
        assert cpic_phenotype(0.0) == "Poor Metabolizer"
