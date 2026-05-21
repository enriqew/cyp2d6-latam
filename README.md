# cyp2d6-latam

CYP2D6 star allele calling pipeline for Latin American populations using Aldy.

Covers MXL (n=64), PEL (n=85), CLM (n=94), PUR (n=104) + CEU European reference
from 1000 Genomes Phase 3. Outputs population-level allele frequencies, phenotype
distributions, and drug impact summaries compatible with the pgx-latam-atlas schema.

## Why CYP2D6 requires Aldy

CYP2D6 is pharmacogenomically unique: patients can carry **zero copies** of the gene
(*5, complete deletion → poor metabolizer) or **three or more copies** (ultrarapid
metabolizer). Standard VCF-based pipelines are blind to these copy number variants.
A *5/*5 patient appears to have no variants in the VCF — indistinguishable from a
normal *1/*1 metabolizer — leading to potential clinical misclassification.

[Aldy](https://github.com/inumanag/aldy) integrates SNP + CNV calling on BAM files,
producing diplotype calls (e.g. `*1/*4`, `*5/*41`, `*1x2/*1`) with activity scores.

## Remote BAM slicing vs full download

| Approach | Data volume | Feasibility |
|---|---|---|
| Download full 1000G BAMs | ~5 TB | Impractical without dedicated storage |
| Remote BAM slicing (this pipeline) | ~17 GB (347 × ~50 MB) | Laptop or small cloud instance |

`samtools view` can stream only the bytes covering a genomic region by fetching
relevant BGZF blocks from the remote file, guided by the remote `.bai` index.
We extract only `chr22:42,000,000–42,200,000` (~200 kb) per sample.

## Pipeline

```
ingest/slice_bams.py          Remote BAM slicing via samtools HTTP
    ↓
src/cyp2d6/calling/run_aldy.py       Aldy star allele + CNV calling
    ↓
src/cyp2d6/calling/aggregate_calls.py   Consolidate per-sample TSVs
    ↓
src/cyp2d6/transformations/silver_diplotypes.py  CPIC phenotype mapping
    ↓
src/cyp2d6/transformations/gold_aggregates.py    Population-level tables
    ↓
src/cyp2d6/exports/build_artifacts.py    JSON artifacts for portfolio
```

Or run all steps:

```bash
make pipeline
```

## Quick start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install samtools (system dependency)
# Ubuntu: apt install samtools
# macOS:  brew install samtools

# 3. Slice CYP2D6 region from remote BAMs (starts with 5 samples per pop)
make slice

# 4. Run Aldy on sliced BAMs
make call

# 5. Silver + Gold transformations
make silver gold

# 6. Export JSON artifacts for portfolio
make export

# Tests
make test
```

## CPIC phenotype thresholds

| Phenotype | Activity score | Clinical implication |
|---|---|---|
| Ultrarapid Metabolizer (UM) | > 2.0 | Gene duplication; excessive drug metabolism |
| Normal Metabolizer (NM) | 1.25 – 2.0 | Standard dosing |
| Intermediate Metabolizer (IM) | 0.25 – 1.25 | Reduced metabolism; consider dose adjustment |
| Poor Metabolizer (PM) | 0.0 | No activity; significant dose adjustment or alternative needed |

## Drugs covered (CPIC A-level)

| Drug | Affected phenotypes | Recommendation |
|---|---|---|
| Codeine | PM, UM | Avoid — risk of inefficacy (PM) or respiratory depression (UM) |
| Tramadol | PM, UM | Same as codeine |
| Tamoxifen | PM, IM | Alternative (PM); standard + monitoring (IM) |
| Amitriptyline | PM, IM | Reduce dose 50% (PM); reduce 25% (IM) |

## Repository structure

```
ingest/                  BAM slicing and sample manifest
src/cyp2d6/
  calling/               Aldy wrapper and result aggregation
  transformations/       Silver (phenotypes) and Gold (aggregates) layers
  exports/               JSON artifact generator for portfolio
dbt_project/             Optional dbt models for the Gold layer
tests/                   Unit tests (pytest)
schemas/                 JSON Schema definitions for output artifacts
data/                    .gitignored — raw BAMs, slices, exports
```

## Limitations

- Low-coverage WGS (~4x): Aldy CNV detection is less reliable below 10×. Activity
  scores for structural alleles (*5, xN duplications) should be interpreted with caution.
- Small sample sizes (n=64–104 per population): frequency estimates have wide confidence
  intervals. Use for exploratory analysis only, not clinical reference.
- Only 5 sample IDs per population are included in the manifest by default.
  Full lists are available at the [1000G data portal](https://www.internationalgenome.org/data-portal/population).
- This pipeline is for research purposes only. Do not use for clinical decisions.
