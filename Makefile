.PHONY: slice call silver gold export pipeline test clean \
        batch-deploy batch-manifest batch-dryrun batch-submit batch-aggregate \
        batch-status batch-logs

# ── Pipeline steps ────────────────────────────────────────────────────────────

slice:
	python ingest/slice_bams.py

call:
	python src/cyp2d6/calling/run_aldy.py

silver:
	python src/cyp2d6/transformations/silver_diplotypes.py

gold:
	python src/cyp2d6/transformations/gold_aggregates.py

export:
	python src/cyp2d6/exports/build_artifacts.py

## Run the full pipeline end-to-end
pipeline: slice call silver gold export

# ── Quality ───────────────────────────────────────────────────────────────────

test:
	python -m pytest tests/ -v

lint:
	python -m flake8 src/ ingest/ tests/ --max-line-length=100

# ── Utilities ─────────────────────────────────────────────────────────────────

manifest:
	python ingest/sample_manifest.py

## Remove generated data (not committed)
clean:
	rm -rf data/raw/ data/bam_slices/ data/exports/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete

# ── AWS Batch scale-up ────────────────────────────────────────────────────────

## Deploy CloudFormation stack, build+push Docker image, register job definition
## Requires: AWS_ACCOUNT_ID, AWS_REGION, VPC_ID, SUBNET_IDS env vars
batch-deploy:
	bash batch/deploy.sh

## Generate full 1000G manifest (queries EBI FTP — takes a few minutes)
batch-manifest:
	python ingest/sample_manifest.py > batch/manifest_all_pops.csv

## Dry-run: print jobs that would be submitted without calling AWS Batch
batch-dryrun:
	python batch/submit_jobs.py --manifest batch/manifest_all_pops.csv --dry-run

## Submit all samples to AWS Batch (requires batch/manifest_all_pops.csv)
batch-submit:
	python batch/submit_jobs.py --manifest batch/manifest_all_pops.csv

## Aggregate per-sample S3 results into Gold artifacts (run after all jobs complete)
batch-aggregate:
	python batch/aggregate_results.py --bucket 1000genomes-cyp2d6-results --prefix results

## List recent jobs in the Batch queue (all statuses)
batch-status:
	@echo "=== RUNNING ===" && \
	aws batch list-jobs --job-queue cyp2d6-latam-queue --job-status RUNNING \
	    --query 'jobSummaryList[*].{Name:jobName,Id:jobId,Status:status}' \
	    --output table 2>/dev/null || true
	@echo "=== PENDING ===" && \
	aws batch list-jobs --job-queue cyp2d6-latam-queue --job-status PENDING \
	    --query 'jobSummaryList[*].{Name:jobName,Id:jobId,Status:status}' \
	    --output table 2>/dev/null || true
	@echo "=== FAILED (last 20) ===" && \
	aws batch list-jobs --job-queue cyp2d6-latam-queue --job-status FAILED \
	    --query 'jobSummaryList[:20].{Name:jobName,Id:jobId,Status:status}' \
	    --output table 2>/dev/null || true

## Download CloudWatch logs for the most recent Batch job
## Usage: make batch-logs  (picks latest log stream automatically)
batch-logs:
	@STREAM=$$(aws logs describe-log-streams \
	    --log-group-name /aws/batch/cyp2d6-latam \
	    --order-by LastEventTime --descending \
	    --query 'logStreams[0].logStreamName' \
	    --output text 2>/dev/null) && \
	if [ -z "$$STREAM" ] || [ "$$STREAM" = "None" ]; then \
	    echo "No log streams found in /aws/batch/cyp2d6-latam"; \
	    exit 1; \
	fi && \
	echo "Fetching log stream: $$STREAM" && \
	aws logs get-log-events \
	    --log-group-name /aws/batch/cyp2d6-latam \
	    --log-stream-name "$$STREAM" \
	    --start-from-head \
	    --query 'events[*].message' \
	    --output text
