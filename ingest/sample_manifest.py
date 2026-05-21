"""
sample_manifest.py
------------------
Generates 1000 Genomes Phase 3 BAM URLs for LATAM + CEU populations.

Full sample lists are available at:
  https://www.internationalgenome.org/data-portal/population

The BASE_URL pattern follows the 1000G EBI FTP structure:
  https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/phase3/data/{sample}/alignment/
  {sample}.mapped.ILLUMINA.bwa.{pop}.low_coverage.20130415.bam
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict

BASE_URL = (
    "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/phase3/data"
    "/{sample}/alignment"
    "/{sample}.mapped.ILLUMINA.bwa.{pop}.low_coverage.20130415.bam"
)

# ── Sample IDs per population ────────────────────────────────────────────────
# Only the first 5 IDs are listed here as examples.
# The full lists (MXL=64, PEL=85, CLM=94, PUR=104, CEU=99) are in
# the 1000G data portal: https://www.internationalgenome.org/data-portal/population

POPULATION_SAMPLES: Dict[str, List[str]] = {
    "MXL": [  # Mexican Ancestry in Los Angeles, CA, USA  (n=64 total)
        "NA19648", "NA19649", "NA19651", "NA19652", "NA19654",
        # ... full list: see 1000G portal, population MXL
    ],
    "PEL": [  # Peruvians in Lima, Peru  (n=85 total)
        "HG01565", "HG01566", "HG01571", "HG01572", "HG01577",
        # ... full list: see 1000G portal, population PEL
    ],
    "CLM": [  # Colombians in Medellin, Colombia  (n=94 total)
        "HG01241", "HG01242", "HG01247", "HG01248", "HG01251",
        # ... full list: see 1000G portal, population CLM
    ],
    "PUR": [  # Puerto Ricans in Puerto Rico  (n=104 total)
        "HG00551", "HG00553", "HG00554", "HG00557", "HG00559",
        # ... full list: see 1000G portal, population PUR
    ],
    "CEU": [  # Utah residents (CEPH) with European ancestry  (n=99 total)
        "NA06984", "NA06985", "NA06986", "NA06989", "NA06994",
        # ... full list: see 1000G portal, population CEU
    ],
}


@dataclass
class SampleEntry:
    sample_id: str
    population: str
    bam_url: str
    bai_url: str


def build_manifest(populations: List[str] | None = None) -> List[SampleEntry]:
    """
    Build the list of SampleEntry objects for the given populations.

    Parameters
    ----------
    populations:
        Subset of populations to include. Defaults to all defined populations.

    Returns
    -------
    List[SampleEntry]
        One entry per sample with BAM + BAI URLs.
    """
    if populations is None:
        populations = list(POPULATION_SAMPLES.keys())

    entries: List[SampleEntry] = []
    for pop in populations:
        if pop not in POPULATION_SAMPLES:
            raise ValueError(f"Unknown population '{pop}'. Valid: {list(POPULATION_SAMPLES)}")
        for sample in POPULATION_SAMPLES[pop]:
            bam_url = BASE_URL.format(sample=sample, pop=pop.lower())
            bai_url = bam_url + ".bai"
            entries.append(SampleEntry(
                sample_id=sample,
                population=pop,
                bam_url=bam_url,
                bai_url=bai_url,
            ))
    return entries


def manifest_to_df(entries: List[SampleEntry]):
    """Convert manifest to a pandas DataFrame."""
    import pandas as pd
    return pd.DataFrame([
        {
            "sample_id": e.sample_id,
            "population": e.population,
            "bam_url": e.bam_url,
            "bai_url": e.bai_url,
        }
        for e in entries
    ])


if __name__ == "__main__":
    import pandas as pd

    manifest = build_manifest()
    df = manifest_to_df(manifest)
    print(f"Total samples in manifest: {len(df)}")
    print(df.groupby("population").size().rename("n_samples").to_string())
    print("\nSample rows:")
    print(df.head(10).to_string(index=False))
