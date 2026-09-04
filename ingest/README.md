# ingest/

Data ingestion layer for cyp2d6-latam.

## Files

### `sample_manifest.py`
Generates the list of 1000 Genomes Phase 3 BAM URLs for LATAM + CEU populations.
Produces `SampleEntry` objects with `sample_id`, `population`, `bam_url`, and `bai_url`.

### `slice_bams.py`
Remote BAM slicing script. For each sample it:
1. Calls `samtools view -b` over HTTPS to extract only `22:42,400,000-42,650,000` (GRCh37/hg19)
2. Indexes the resulting BAM with `samtools index`
3. Parallelizes across samples using `concurrent.futures.ThreadPoolExecutor`

**Run:**
```bash
python ingest/slice_bams.py --workers 8
# or a single population:
python ingest/slice_bams.py --populations MXL --workers 4
```

## Prerequisites

- `samtools >= 1.16` on PATH with HTTPS/curl support
- Outbound HTTPS access to `ftp.1000genomes.ebi.ac.uk`

## Why remote slicing?

Full 1000G Phase 3 BAMs total ~5 TB. Downloading them is impractical on a laptop
or a small cloud instance. Instead, samtools can stream just the bytes covering
the desired genomic region by fetching only the relevant blocks from the remote BGZF
file, guided by the `.bai` index. Per-sample data transfer drops from ~15 GB to ~50 MB.

Total for 452 samples: **~23 GB** vs 5 TB.
