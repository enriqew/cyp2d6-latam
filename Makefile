.PHONY: slice call silver gold export pipeline test clean

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
