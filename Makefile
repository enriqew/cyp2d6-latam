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
