#!/usr/bin/env bash
# deploy.sh — Deploy the full CYP2D6 AWS Batch stack.
#
# What this script does (in order):
#   1. Deploy CloudFormation stack (Compute Env, Job Queue, IAM roles, Log Group)
#   2. Build and push the Docker image to ECR
#   3. Register the job definition (resolved from job_definition.json.tpl)
#   4. Verify the Job Queue reaches VALID state
#
# Required environment variables:
#   AWS_ACCOUNT_ID   12-digit AWS account ID
#   AWS_REGION       e.g. us-east-1
#   VPC_ID           VPC ID for the Compute Environment
#   SUBNET_IDS       Comma-separated subnet IDs, e.g. subnet-aaa,subnet-bbb
#
# Optional environment variables:
#   OUTPUT_BUCKET    S3 bucket for results (default: 1000genomes-cyp2d6-results)
#   STACK_NAME       CloudFormation stack name (default: cyp2d6-latam-batch)
#   ECR_REPO         ECR repository name      (default: cyp2d6-latam-batch)
#   IMAGE_TAG        Docker image tag          (default: latest)
#   MAX_VCPUS        Max vCPUs for Spot fleet  (default: 200)
#
# Usage:
#   export AWS_ACCOUNT_ID=123456789012
#   export AWS_REGION=us-east-1
#   export VPC_ID=vpc-0123456789abcdef0
#   export SUBNET_IDS=subnet-aaa,subnet-bbb
#   bash batch/deploy.sh

set -euo pipefail

# ── Required variables ─────────────────────────────────────────────────────────
ACCOUNT_ID="${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"
REGION="${AWS_REGION:?AWS_REGION is required}"
VPC_ID="${VPC_ID:?VPC_ID is required}"
SUBNET_IDS="${SUBNET_IDS:?SUBNET_IDS is required (comma-separated)}"

# ── Optional variables ─────────────────────────────────────────────────────────
OUTPUT_BUCKET="${OUTPUT_BUCKET:-1000genomes-cyp2d6-results}"
STACK_NAME="${STACK_NAME:-cyp2d6-latam-batch}"
ECR_REPO="${ECR_REPO:-cyp2d6-latam-batch}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MAX_VCPUS="${MAX_VCPUS:-200}"

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CFN_TEMPLATE="${SCRIPT_DIR}/cloudformation.yaml"
JOB_DEF_TPL="${SCRIPT_DIR}/job_definition.json.tpl"

# ── Helper ─────────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Deploy CloudFormation stack
# ──────────────────────────────────────────────────────────────────────────────
log "STEP 1/4  Deploying CloudFormation stack: ${STACK_NAME}"

aws cloudformation deploy \
    --template-file "${CFN_TEMPLATE}" \
    --stack-name "${STACK_NAME}" \
    --region "${REGION}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        ProjectName=cyp2d6-latam \
        VpcId="${VPC_ID}" \
        SubnetIds="${SUBNET_IDS}" \
        OutputBucket="${OUTPUT_BUCKET}" \
        MaxvCpus="${MAX_VCPUS}" \
    --tags project=cyp2d6-latam

log "CloudFormation stack deployed."

# ── Fetch stack outputs ────────────────────────────────────────────────────────
log "Fetching stack outputs ..."

_cfn_output() {
    aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}" \
        --region "${REGION}" \
        --query "Stacks[0].Outputs[?OutputKey=='${1}'].OutputValue" \
        --output text
}

JOB_ROLE_ARN="$(_cfn_output JobRoleArn)"
JOB_QUEUE_NAME="$(_cfn_output JobQueueName)"

log "  Job Role ARN  : ${JOB_ROLE_ARN}"
log "  Job Queue     : ${JOB_QUEUE_NAME}"

# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Build and push Docker image to ECR
# ──────────────────────────────────────────────────────────────────────────────
log "STEP 2/4  Building and pushing Docker image to ECR ..."

export AWS_ACCOUNT_ID="${ACCOUNT_ID}"
export AWS_REGION="${REGION}"
export ECR_REPO="${ECR_REPO}"
export IMAGE_TAG="${IMAGE_TAG}"

bash "${SCRIPT_DIR}/ecr_push.sh"

ECR_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"
log "Image pushed: ${ECR_IMAGE}"

# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Register job definition
# ──────────────────────────────────────────────────────────────────────────────
log "STEP 3/4  Registering job definition ..."

RESOLVED_JOB_DEF="$(mktemp /tmp/job_definition_XXXXXX.json)"
trap 'rm -f "${RESOLVED_JOB_DEF}"' EXIT

# envsubst only substitutes the variables we explicitly export here
export JOB_ROLE_ARN
export OUTPUT_BUCKET
# AWS_ACCOUNT_ID and AWS_REGION already exported above

envsubst '${AWS_ACCOUNT_ID} ${AWS_REGION} ${JOB_ROLE_ARN} ${OUTPUT_BUCKET}' \
    < "${JOB_DEF_TPL}" > "${RESOLVED_JOB_DEF}"

# Remove the _comment key (not accepted by the Batch API)
if command -v jq &>/dev/null; then
    TMP_CLEAN="$(mktemp /tmp/job_definition_clean_XXXXXX.json)"
    jq 'del(._comment)' "${RESOLVED_JOB_DEF}" > "${TMP_CLEAN}"
    mv "${TMP_CLEAN}" "${RESOLVED_JOB_DEF}"
fi

JOB_DEF_ARN=$(aws batch register-job-definition \
    --cli-input-json "file://${RESOLVED_JOB_DEF}" \
    --region "${REGION}" \
    --query "jobDefinitionArn" \
    --output text)

log "  Job definition registered: ${JOB_DEF_ARN}"

# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Verify Job Queue is VALID
# ──────────────────────────────────────────────────────────────────────────────
log "STEP 4/4  Waiting for Job Queue '${JOB_QUEUE_NAME}' to reach VALID state ..."

MAX_WAIT=120   # seconds
ELAPSED=0
INTERVAL=10

while true; do
    QUEUE_STATE=$(aws batch describe-job-queues \
        --job-queues "${JOB_QUEUE_NAME}" \
        --region "${REGION}" \
        --query "jobQueues[0].status" \
        --output text 2>/dev/null || echo "UNKNOWN")

    log "  Queue status: ${QUEUE_STATE}"

    if [[ "${QUEUE_STATE}" == "VALID" ]]; then
        break
    fi

    if [[ "${ELAPSED}" -ge "${MAX_WAIT}" ]]; then
        log "ERROR: Job Queue did not reach VALID state within ${MAX_WAIT}s."
        log "       Check AWS Console → Batch → Job Queues for details."
        exit 1
    fi

    sleep "${INTERVAL}"
    ELAPSED=$((ELAPSED + INTERVAL))
done

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
log "============================================================"
log "Deployment complete."
log "  CloudFormation stack : ${STACK_NAME}"
log "  ECR image            : ${ECR_IMAGE}"
log "  Job definition       : ${JOB_DEF_ARN}"
log "  Job queue            : ${JOB_QUEUE_NAME} (VALID)"
log ""
log "Next steps:"
log "  make batch-manifest   # generate sample manifest from EBI FTP"
log "  make batch-submit     # submit all jobs to the queue"
log "  make batch-status     # monitor job progress"
log "  make batch-aggregate  # after all jobs complete"
log "============================================================"
