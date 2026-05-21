#!/usr/bin/env bash
# ecr_push.sh — Build the CYP2D6 Batch worker image and push it to ECR.
#
# Required environment variables:
#   AWS_ACCOUNT_ID   12-digit AWS account ID
#   AWS_REGION       e.g. us-east-1
#
# Optional:
#   ECR_REPO         ECR repository name (default: cyp2d6-latam-batch)
#   IMAGE_TAG        Docker image tag  (default: latest)
#
# Usage:
#   export AWS_ACCOUNT_ID=123456789012
#   export AWS_REGION=us-east-1
#   bash batch/ecr_push.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
ACCOUNT_ID="${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"
REGION="${AWS_REGION:?AWS_REGION is required}"
ECR_REPO="${ECR_REPO:-cyp2d6-latam-batch}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
FULL_IMAGE="${REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"

# Resolve repo root (the directory that contains batch/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> ECR repository : ${ECR_REPO}"
echo "==> Region         : ${REGION}"
echo "==> Image          : ${FULL_IMAGE}"
echo "==> Build context  : ${REPO_ROOT}"

# ── Step 1: Create ECR repository (idempotent) ────────────────────────────────
echo ""
echo "==> Ensuring ECR repository exists ..."
aws ecr create-repository \
    --repository-name "${ECR_REPO}" \
    --region "${REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --tags Key=project,Value=cyp2d6-latam \
    2>/dev/null || echo "    (repository already exists — skipping)"

# ── Step 2: Authenticate Docker to ECR ────────────────────────────────────────
echo ""
echo "==> Authenticating Docker to ECR ..."
aws ecr get-login-password --region "${REGION}" \
    | docker login --username AWS --password-stdin "${REGISTRY}"

# ── Step 3: Build the image ────────────────────────────────────────────────────
echo ""
echo "==> Building Docker image ..."
docker build \
    --file "${SCRIPT_DIR}/Dockerfile" \
    --tag "${ECR_REPO}:${IMAGE_TAG}" \
    "${REPO_ROOT}"

# ── Step 4: Tag for ECR ────────────────────────────────────────────────────────
echo ""
echo "==> Tagging image for ECR ..."
docker tag "${ECR_REPO}:${IMAGE_TAG}" "${FULL_IMAGE}"

# ── Step 5: Push to ECR ────────────────────────────────────────────────────────
echo ""
echo "==> Pushing image to ECR ..."
docker push "${FULL_IMAGE}"

echo ""
echo "==> Done. Image available at:"
echo "    ${FULL_IMAGE}"
echo ""
echo "    Next: run batch/deploy.sh to register the job definition and deploy the stack."
