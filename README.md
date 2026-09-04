# cyp2d6-latam

**Live demo:** [eredonda.com/projects/cyp2d6-latam](https://eredonda.com/projects/cyp2d6-latam?utm_source=github&utm_medium=referral)

CYP2D6 star allele calling pipeline for Latin American populations using Aldy.

Covers MXL (n=62), PEL (n=85), CLM (n=93), PUR (n=97) and the CEU European reference (n=97): 434 samples called out of 452 sliced
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
| Remote BAM slicing (this pipeline) | ~23 GB (452 × ~50 MB) | Laptop or small cloud instance |

`samtools view` can stream only the bytes covering a genomic region by fetching
relevant BGZF blocks from the remote file, guided by the remote `.bai` index.
We extract only `22:42,400,000-42,650,000` (~250 kb) per sample, in GRCh37/hg19 coordinates, which is what the 1000 Genomes Phase 3 BAMs are aligned to.

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

## Scale-Up: All 1000G Populations

The local pipeline runs on 452 LATAM + CEU samples sequentially on a single machine.
The `batch/` directory contains a fully parallel AWS Batch pipeline to scale to
all ~2,500 individuals across 1000 Genomes Phase 3 without downloading the ~5 TB of
full BAMs.

### Architecture

```
ingest/sample_manifest.py
        │
        │  generates manifest CSV
        ▼
batch/submit_jobs.py  ──────────────────────────────────────────────────────►  AWS Batch
        │                                                                         │
        │  one job per sample                            ┌────────────────────────┤
        │                                                │  job: cyp2d6-process-sample
        │                                                │
        │                                                │  1. samtools view (remote HTTP slice)
        │                                                │     ~50 MB / sample  (vs ~30 GB full BAM)
        │                                                │
        │                                                │  2. aldy genotype
        │                                                │
        │                                                │  3. parse TSV → dict
        │                                                │
        │                                                │  4. s3://OUTPUT_BUCKET/{pop}/{id}/aldy_output.json
        │                                                └────────────────────────┘
        │
        │  after all jobs complete
        ▼
batch/aggregate_results.py
        │
        │  list + download per-sample JSONs from S3
        │  apply Silver (CPIC phenotype normalization)
        │  build Gold (allele_frequencies, phenotype_distribution, drug_impact_summary)
        ▼
data/exports/*.json  ──►  copy to portfolio src/data/cyp2d6/
```

**Parallelism:** each Batch job is isolated — 2 vCPU / 4 GB RAM, 2 h timeout.
With a queue of 500 concurrent jobs, ~2,500 samples finish in roughly 15–30 min
total (vs ~12 h sequential on a laptop).

**Data volume per job:** ~50 MB BAM slice (samtools HTTP range request) — never
downloads the full 10–30 GB BAM.

### Deployment

#### Prerequisites

- AWS CLI v2 configured with credentials that have permissions to create IAM roles,
  Batch resources, ECR repositories, and CloudWatch Log Groups.
- Docker (for building and pushing the worker image).
- `jq` (optional but recommended — used by `deploy.sh` to strip JSON comments before
  registering the job definition).

#### One-command deployment

```bash
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1
export VPC_ID=vpc-0123456789abcdef0
export SUBNET_IDS=subnet-aaa,subnet-bbb   # comma-separated, no spaces
export OUTPUT_BUCKET=1000genomes-cyp2d6-results   # optional, this is the default

make batch-deploy
```

`make batch-deploy` runs `batch/deploy.sh`, which:

1. **CloudFormation** — creates the Compute Environment (EC2 Spot), Job Queue,
   IAM roles (service role, instance role, job role), Security Group, and
   CloudWatch Log Group `/aws/batch/cyp2d6-latam`.
2. **ECR push** — builds the Docker image from `batch/Dockerfile` and pushes it to
   `<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cyp2d6-latam-batch:latest`.
3. **Job definition** — instantiates `batch/job_definition.json.tpl` with the
   CloudFormation outputs (job role ARN) and registers it with the Batch API.
4. **Verification** — polls the Job Queue until it reaches `VALID` state.

The deploy is idempotent: running it again updates the stack if the template changed
and pushes a new image tag.

#### Step-by-step (after deployment)

```bash
# 1. Generate the full 1000G sample manifest (queries EBI FTP — a few minutes)
make batch-manifest

# 2. Smoke test: verify 10 jobs would be submitted correctly
python batch/submit_jobs.py \
  --manifest batch/manifest_all_pops.csv \
  --limit 10 --dry-run

# 3. Submit all ~2,500 jobs
make batch-submit

# 4. Monitor progress
make batch-status          # lists RUNNING / PENDING / FAILED jobs
make batch-logs            # streams CloudWatch logs from the most recent job

# 5. After all jobs reach SUCCEEDED — aggregate and export Gold artifacts
make batch-aggregate

# 6. Copy artifacts to the portfolio repo
cp data/exports/*.json ../data-dive-design-hub/src/data/cyp2d6/
```

#### Cost estimate (Spot EC2)

| Item | Value |
|---|---|
| Jobs | ~2,500 samples × ~2 min each |
| Compute (sequential wall time) | ~83 vCPU-hours |
| Concurrency (500 jobs in parallel) | wall time ~10–20 min |
| Instance type | c5.xlarge (4 vCPU / 8 GB) — 2 vCPU used per job |
| Spot price (us-east-1, c5.xlarge) | ~$0.04–0.06/vCPU-hour |
| **Estimated total** | **< $5** |

Spot interruptions are handled via `retryStrategy.attempts: 2` in the job definition.

#### Tear-down

To delete all AWS resources created by the stack:

```bash
aws cloudformation delete-stack --stack-name cyp2d6-latam-batch --region "$AWS_REGION"
aws ecr delete-repository --repository-name cyp2d6-latam-batch --force --region "$AWS_REGION"
```

### Files

| File | Purpose |
|---|---|
| `batch/cloudformation.yaml` | CloudFormation template: Compute Env, Job Queue, IAM, Log Group |
| `batch/deploy.sh` | Orchestration script: CFN deploy → ECR push → job definition register → verify |
| `batch/ecr_push.sh` | Build Docker image and push to ECR |
| `batch/job_definition.json.tpl` | `envsubst` template for the job definition (no hardcoded ARNs) |
| `batch/job_definition.json` | Static reference copy with `<PLACEHOLDER>` values (for documentation) |
| `batch/Dockerfile` | Container image: python:3.11-slim + samtools + Aldy |
| `batch/submit_jobs.py` | Read manifest CSV, submit one Batch job per sample |
| `batch/process_sample.py` | Worker: slice → Aldy → upload JSON to S3 (runs in container) |
| `batch/aggregate_results.py` | Reducer: download S3 JSONs → Silver → Gold → portfolio artifacts |
| `requirements_batch.txt` | Minimal deps for the container (aldy + boto3 only) |

---

## Limitations

- Low-coverage WGS (~4x): Aldy CNV detection is less reliable below 10×. Activity
  scores for structural alleles (*5, xN duplications) should be interpreted with caution.
- Small sample sizes (n=62-97 per population): frequency estimates have wide confidence
  intervals. Use for exploratory analysis only, not clinical reference.
- Only 5 sample IDs per population are included in the manifest by default.
  Full lists are available at the [1000G data portal](https://www.internationalgenome.org/data-portal/population).
- This pipeline is for research purposes only. Do not use for clinical decisions.

## Results

The run called **434 of 452 sliced samples** (Aldy v4.8.3, GRCh37/hg19). The
18 exclusions are samples whose average coverage over the locus fell below
Aldy's threshold, which is expected for low-coverage (~4x) WGS.

What came out of it:

- **PEL** carries the clearest poor-metabolizer signal in the cohort, including
  homozygous \*4C.
- **PUR** shows ultrarapid duplications.
- **MXL** has the highest share of indeterminate calls, driven by complex
  alleles common in admixed populations that CPIC tables do not yet cover.

The dashboard renders all of this: see the live demo linked at the top.

## Data & licenses

- **1000 Genomes Project Phase 3**: open access with no reuse restrictions.
  Cite as "1000 Genomes Project Phase 3". The BAM slices are derived from the
  public low-coverage WGS alignments.
- **CPIC**: open-access guidelines, used for the diplotype to phenotype mapping
  and the drug recommendations.
- Code: MIT, see [LICENSE](LICENSE).

The sample identifiers (NA/HG prefixes) are the public 1000 Genomes identifiers.
No personally identifiable information is ingested, stored or emitted.
