FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────────
# samtools: BAM slicing via HTTP(S) range requests (requires libcurl / htslib)
# libcurl4: required by htslib for remote BAM access
# gcc / make: required to build some Aldy C extensions during pip install
RUN apt-get update && apt-get install -y --no-install-recommends \
        samtools \
        libcurl4 \
        gcc \
        make \
        && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────────────────────────
# Pin aldy to a working version; boto3 for S3 I/O inside the container.
COPY requirements_batch.txt /app/requirements_batch.txt
RUN pip install --no-cache-dir -r /app/requirements_batch.txt

# ── Pipeline code ──────────────────────────────────────────────────────────────
WORKDIR /app
COPY batch/process_sample.py /app/process_sample.py

# Default entrypoint — overridden by AWS Batch job definition command
ENTRYPOINT ["python", "/app/process_sample.py"]
