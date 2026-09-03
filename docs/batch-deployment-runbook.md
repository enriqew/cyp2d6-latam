# CYP2D6 AWS Batch Full Run — Deployment Runbook

Scale the CYP2D6 pipeline from 452 LATAM samples to all ~2,500 individuals across 26 populations in 1000 Genomes, using AWS Batch for parallel processing.

---

## What this does

The local pipeline already works for 452 LATAM samples (MXL, PEL, CLM, PUR + CEU reference).
This runbook scales it to every population in 1000 Genomes Phase 3 high-coverage:
- African: YRI, LWK, GWD, MSL, ESN, ASW, ACB
- Admixed American: MXL, PUR, CLM, PEL
- East Asian: CHB, JPT, CHS, CDX, KHV
- European: CEU, TSI, FIN, GBR, IBS
- South Asian: GIH, PJL, BEB, STU, ITU

**Total: ~2,504 individuals. Estimated runtime: ~1.7 hours. Estimated cost: $5–$20 on Spot EC2.**

---

## Architecture

```
manifest.csv (2,504 rows)
    │
    ▼
batch/submit_jobs.py
    │  one AWS Batch job per sample
    ▼
[AWS Batch Compute Environment — 50 Spot vCPUs]
    │
    ├── process_sample.py (per job, runs inside Docker container)
    │     1. samtools view → remote BAM slice (chr22 CYP2D6 region, ~50 MB)
    │     2. aldy genotype → star allele call
    │     3. Upload result JSON → s3://{OUTPUT_BUCKET}/{population}/{sample_id}/aldy_output.json
    │
    ▼
batch/aggregate_results.py (runs locally after all jobs complete)
    │  downloads all JSONs from S3, runs Silver + Gold pipeline
    ▼
data/exports/*.json  →  copy to portfolio src/data/cyp2d6/
```

---

## Prerequisites

### AWS account
- Account ID: `<AWS_ACCOUNT_ID>` (your existing account)
- Recommended region: `us-east-1` (same region as 1000 Genomes S3 data — avoids data transfer costs)

### IAM user with permissions
Create an IAM user (or use an existing one) with these policies:
- `AWSBatchFullAccess`
- `AmazonEC2ContainerRegistryFullAccess`
- `AWSCloudFormationFullAccess`
- `AmazonS3FullAccess` (or scoped to your output bucket)
- `IAMFullAccess` (needed to create the job role via CloudFormation)

### Local tools
```bash
# Check all required tools are installed
aws --version        # AWS CLI v2
docker --version     # Docker Desktop or Docker Engine
jq --version         # jq for JSON processing
envsubst --version   # gettext-base package
```

Install on Ubuntu/WSL2 if missing:
```bash
sudo apt-get install -y awscli jq gettext-base
# Docker: follow https://docs.docker.com/engine/install/ubuntu/
```

### AWS CLI configured
```bash
aws configure
# AWS Access Key ID: <your IAM user key>
# AWS Secret Access Key: <your IAM user secret>
# Default region name: us-east-1
# Default output format: json

# Verify
aws sts get-caller-identity
```

---

## Step 0 — Budget protection (do this FIRST)

Before spending a dollar, set up a cost alert in AWS Console:
1. Go to **Billing → Budgets → Create Budget**
2. Type: Cost budget
3. Amount: $25
4. Alert threshold: 80% ($20) → email `<your-email>`
5. Also enable **AWS Cost Anomaly Detection** (free) for automated alerts

---

## Step 1 — Set environment variables

```bash
export AWS_ACCOUNT_ID=<AWS_ACCOUNT_ID>
export AWS_REGION=us-east-1
export VPC_ID=vpc-xxxxxxxx           # your default VPC — find with: aws ec2 describe-vpcs --filters Name=isDefault,Values=true
export SUBNET_IDS=subnet-xxx,subnet-yyy  # subnets in your VPC — find with: aws ec2 describe-subnets
export OUTPUT_BUCKET=cyp2d6-latam-results

# Create the S3 output bucket (if it doesn't exist)
aws s3 mb s3://$OUTPUT_BUCKET --region $AWS_REGION
```

To find your VPC and subnets:
```bash
aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text
aws ec2 describe-subnets --filters Name=defaultForAz,Values=true --query 'Subnets[*].SubnetId' --output text
```

---

## Step 2 — Deploy infrastructure (one-time, ~5 min)

```bash
cd <HOME>/PycharmProjects/cyp2d6-latam
make batch-deploy
```

This runs `batch/deploy.sh` which:
1. Deploys the CloudFormation stack (`cyp2d6-latam-batch`) — Spot compute environment, job queue, IAM roles, log group
2. Builds the Docker image and pushes to ECR
3. Registers the job definition

**Expected output:**
```
[deploy] Deploying CloudFormation stack...
Successfully created/updated stack - cyp2d6-latam-batch
[deploy] Pushing Docker image to ECR...
[deploy] Registering job definition...
[deploy] Job queue status: VALID
[deploy] Done.
```

If CloudFormation fails, check the Events tab in the CloudFormation console for the specific resource that failed.

---

## Step 3 — Validate with 10 samples (RECOMMENDED before full run)

```bash
# Build the manifest for all populations
make batch-manifest

# Dry run — shows what would be submitted
make batch-dryrun -- --populations PEL --limit 10

# Submit 10 PEL samples only
python batch/submit_jobs.py \
  --manifest data/batch_manifest.csv \
  --populations PEL \
  --limit 10 \
  --queue cyp2d6-latam-batch-queue \
  --job-definition cyp2d6-latam-job \
  --output-bucket $OUTPUT_BUCKET

# Monitor
make batch-status

# After jobs complete (5-10 min), check S3 output
aws s3 ls s3://$OUTPUT_BUCKET/PEL/ --recursive | head -20

# Check one output file
aws s3 cp s3://$OUTPUT_BUCKET/PEL/$(aws s3 ls s3://$OUTPUT_BUCKET/PEL/ | head -1 | awk '{print $4}') - | python3 -m json.tool | head -30
```

If the 10-sample test produces valid JSON outputs with `diplotype`, `phenotype`, and `activity_score` fields — you're good to run the full dataset.

---

## Step 4 — Full run (~1.7 hours)

```bash
# Submit all 2,504 jobs
make batch-submit

# Monitor (check every 15-20 min)
make batch-status
# Shows: PENDING / RUNNABLE / STARTING / RUNNING / SUCCEEDED / FAILED counts

# Check logs if any jobs fail
make batch-logs
```

**If jobs fail:** Check CloudWatch Logs at `/aws/batch/cyp2d6-latam`. Common failure modes:
- S3 permission denied on 1000G bucket → the bucket is public, ensure `--no-sign-request` flag is in the samtools command
- Aldy timeout → increase job timeout in `batch/job_definition.json.tpl` from 7200 to 10800 seconds
- Container OOM → increase memory from 4096 to 8192 MB in the job definition

---

## Step 5 — Aggregate results (~5 min)

```bash
# Download all S3 outputs and run Silver + Gold pipeline
make batch-aggregate

# Artifacts written to data/exports/
ls -lh data/exports/

# Copy to portfolio
cp data/exports/allele_frequencies.json \
   <HOME>/PycharmProjects/data-dive-design-hub/public/data/cyp2d6/

cp data/exports/phenotype_distribution.json \
   data/exports/drug_impact_summary.json \
   <HOME>/PycharmProjects/data-dive-design-hub/src/data/cyp2d6/

# Commit in portfolio
cd <HOME>/PycharmProjects/data-dive-design-hub
git add src/data/cyp2d6/ public/data/cyp2d6/
git commit -m "data(cyp2d6): refresh to full 1000G dataset (n=2504, 26 populations)"
```

---

## Step 6 — Teardown (optional, saves ~$0/month since Batch is serverless)

The Batch compute environment scales to 0 when idle — no ongoing cost. But if you want to clean up completely:

```bash
# Delete the CloudFormation stack (removes compute environment, job queue, IAM roles)
aws cloudformation delete-stack --stack-name cyp2d6-latam-batch --region $AWS_REGION

# Delete ECR repository (optional)
aws ecr delete-repository --repository-name cyp2d6-latam-batch --force --region $AWS_REGION

# Delete S3 output bucket (optional — removes ~2,504 JSON files)
aws s3 rm s3://$OUTPUT_BUCKET --recursive
aws s3 rb s3://$OUTPUT_BUCKET
```

---

## Cost breakdown

| Component | Estimate | Notes |
|---|---|---|
| EC2 Spot (c5.xlarge) | ~$3.40 | 50 vCPUs × 1.7h × $0.04/vCPU-h |
| S3 storage (outputs) | ~$0.05 | 2,504 JSON files × ~50 KB each = ~120 MB |
| S3 GET requests | ~$0.01 | 2,504 reads during aggregation |
| ECR storage | ~$0.01 | Docker image ~1 GB × $0.10/GB-month |
| CloudWatch Logs | ~$0.10 | 2,504 job logs |
| Data transfer | $0 | 1000G data is in us-east-1, stays intra-region |
| **Total** | **~$3.60–$5** | Up to $20 if high retry rate |

Spot interruption risk: c5.xlarge has ~5% interruption rate. With 2 retries configured, the job completes even under moderate interruptions.

---

## Troubleshooting

**`make batch-deploy` fails at CloudFormation:**
Check the stack events:
```bash
aws cloudformation describe-stack-events \
  --stack-name cyp2d6-latam-batch \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
  --output table
```

**Docker build fails:**
```bash
cd cyp2d6-latam
docker build -t cyp2d6-test batch/
docker run --rm cyp2d6-test python -c "import aldy; import pysam; print('OK')"
```

**Jobs stuck in RUNNABLE:**
The compute environment may not be scaling up. Check:
- VPC/subnet configuration has internet access (NAT gateway or public subnet)
- EC2 service role has `AWSServiceRoleForBatch`

**Aldy fails on a sample:**
The job uploads a `status=error` JSON and exits with code 1. Batch marks it as FAILED.
After full run, check how many failed:
```bash
aws s3 ls s3://$OUTPUT_BUCKET/ --recursive | grep aldy_output.json | wc -l
# Compare to 2504 — difference is failed samples
```

---

## Blog content angles

This pipeline is a showcase for several distinct engineering topics:

### 1. Remote BAM slicing at scale
The key insight: 1000 Genomes BAMs are ~10-30 GB each but CYP2D6 is ~200 kb. `samtools view` with a region specifier against an S3 CRAM/BAM URL pulls only the relevant index bytes + the region reads. 2,504 samples × ~50 MB slice = ~125 GB transferred instead of ~5 TB. This is the fundamental technique for genomics data engineering at scale — you never download what you don't need.

### 2. Embarrassingly parallel bioinformatics
CYP2D6 genotyping is per-sample independent. AWS Batch with a job-per-sample pattern is the canonical approach: static job definition, per-sample environment variable injection via `containerOverrides`, Spot for cost, retry for resilience. The submit script throttles at 20 jobs/sec to avoid AWS API rate limits.

### 3. Medallion architecture for genomic data
Bronze (raw BAM slices) → Silver (Aldy TSV + CPIC phenotype mapping) → Gold (population aggregates). The same pattern as a data warehouse but applied to sequencing data. The Gold layer is pure pandas/DuckDB and runs locally; only Bronze→Silver needs distributed compute.

### 4. Star allele calling complexity
CYP2D6 is the hardest pharmacogene to call: pseudogene interference (CYP2D7 at 92% identity), CNVs (*5 deletion, xN duplication), hybrid alleles. Aldy solves this by using read depth + variant phasing together. The `*1+*1` tandem duplication notation bug (Aldy v4 → pipeline UM misclassification) is a good engineering war story about the gap between tool documentation and actual output format.

### 5. Population PGx at 1000G scale
Running this on all 26 populations turns the LATAM atlas into a global atlas. The clinical story shifts from "LATAM is different from European baseline" to "every major ancestry group has a distinct pharmacogenomic profile" — which is the actual scientific finding. The data supports this as a general argument for pre-prescription genotyping, not a region-specific one.
