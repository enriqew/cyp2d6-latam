"""
sample_manifest.py
------------------
Generates 1000 Genomes Phase 3 BAM URLs for LATAM + CEU populations.

Complete sample lists sourced from:
  https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/
    integrated_call_samples_v3.20200731.ALL.ped
Retrieved 2026-05-21.

Note: not every sample in the PED file has a Phase 3 BAM on the EBI FTP.
build_manifest() skips samples that return HTTP 404 and logs a warning.
"""

from __future__ import annotations

import logging
import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

FTP_BASE = "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/phase3/data"

# -- Sample IDs per population ------------------------------------------------
# Counts: MXL=107, PEL=130, CLM=148, PUR=150, CEU=184  (total=719)
# Some IDs are PED-only (parents not sequenced in Phase 3) and will be skipped
# automatically by build_manifest when their FTP directory returns 404.

POPULATION_SAMPLES: Dict[str, List[str]] = {
    "MXL": [  # Mexican Ancestry in Los Angeles, CA, USA
        "NA19648", "NA19649", "NA19650", "NA19651", "NA19652", "NA19653", "NA19654",
        "NA19655", "NA19656", "NA19657", "NA19658", "NA19659", "NA19660", "NA19661",
        "NA19662", "NA19663", "NA19664", "NA19665", "NA19669", "NA19670", "NA19671",
        "NA19672", "NA19674", "NA19675", "NA19676", "NA19677", "NA19678", "NA19679",
        "NA19680", "NA19681", "NA19682", "NA19683", "NA19684", "NA19685", "NA19686",
        "NA19716", "NA19717", "NA19718", "NA19719", "NA19720", "NA19721", "NA19722",
        "NA19723", "NA19724", "NA19725", "NA19726", "NA19727", "NA19728", "NA19729",
        "NA19730", "NA19731", "NA19732", "NA19733", "NA19734", "NA19735", "NA19737",
        "NA19738", "NA19740", "NA19741", "NA19742", "NA19746", "NA19747", "NA19748",
        "NA19749", "NA19750", "NA19751", "NA19752", "NA19753", "NA19754", "NA19755",
        "NA19756", "NA19757", "NA19758", "NA19759", "NA19760", "NA19761", "NA19762",
        "NA19763", "NA19764", "NA19766", "NA19770", "NA19771", "NA19772", "NA19773",
        "NA19774", "NA19775", "NA19776", "NA19777", "NA19778", "NA19779", "NA19780",
        "NA19781", "NA19782", "NA19783", "NA19784", "NA19785", "NA19786", "NA19787",
        "NA19788", "NA19789", "NA19790", "NA19792", "NA19794", "NA19795", "NA19796",
        "NA19797", "NA19798",
    ],
    "PEL": [  # Peruvians in Lima, Peru
        "HG01565", "HG01566", "HG01567", "HG01571", "HG01572", "HG01573", "HG01577",
        "HG01578", "HG01579", "HG01892", "HG01893", "HG01898", "HG01917", "HG01918",
        "HG01919", "HG01920", "HG01921", "HG01922", "HG01923", "HG01924", "HG01925",
        "HG01926", "HG01927", "HG01928", "HG01932", "HG01933", "HG01934", "HG01935",
        "HG01936", "HG01937", "HG01938", "HG01939", "HG01940", "HG01941", "HG01942",
        "HG01943", "HG01944", "HG01945", "HG01946", "HG01947", "HG01948", "HG01949",
        "HG01950", "HG01951", "HG01952", "HG01953", "HG01954", "HG01955", "HG01961",
        "HG01965", "HG01967", "HG01968", "HG01969", "HG01970", "HG01971", "HG01972",
        "HG01973", "HG01974", "HG01975", "HG01976", "HG01977", "HG01978", "HG01979",
        "HG01980", "HG01981", "HG01982", "HG01983", "HG01984", "HG01991", "HG01992",
        "HG01993", "HG01995", "HG01997", "HG01998", "HG02002", "HG02003", "HG02004",
        "HG02006", "HG02008", "HG02089", "HG02090", "HG02091", "HG02102", "HG02104",
        "HG02105", "HG02106", "HG02146", "HG02147", "HG02148", "HG02150", "HG02252",
        "HG02253", "HG02254", "HG02259", "HG02260", "HG02261", "HG02262", "HG02265",
        "HG02266", "HG02267", "HG02271", "HG02272", "HG02273", "HG02274", "HG02275",
        "HG02276", "HG02277", "HG02278", "HG02279", "HG02285", "HG02286", "HG02287",
        "HG02288", "HG02291", "HG02292", "HG02293", "HG02298", "HG02299", "HG02300",
        "HG02301", "HG02302", "HG02303", "HG02304", "HG02312", "HG02344", "HG02345",
        "HG02347", "HG02348", "HG02415", "HG02425",
    ],
    "CLM": [  # Colombians in Medellin, Colombia
        "HG01112", "HG01113", "HG01114", "HG01119", "HG01121", "HG01122", "HG01123",
        "HG01124", "HG01125", "HG01126", "HG01130", "HG01131", "HG01133", "HG01134",
        "HG01135", "HG01136", "HG01137", "HG01138", "HG01139", "HG01140", "HG01141",
        "HG01142", "HG01148", "HG01149", "HG01150", "HG01250", "HG01251", "HG01252",
        "HG01253", "HG01254", "HG01255", "HG01256", "HG01257", "HG01258", "HG01259",
        "HG01260", "HG01261", "HG01269", "HG01271", "HG01272", "HG01273", "HG01274",
        "HG01275", "HG01276", "HG01277", "HG01278", "HG01279", "HG01280", "HG01281",
        "HG01284", "HG01341", "HG01342", "HG01343", "HG01344", "HG01345", "HG01346",
        "HG01347", "HG01348", "HG01349", "HG01350", "HG01351", "HG01352", "HG01353",
        "HG01354", "HG01355", "HG01356", "HG01357", "HG01358", "HG01359", "HG01360",
        "HG01361", "HG01362", "HG01363", "HG01364", "HG01365", "HG01366", "HG01367",
        "HG01369", "HG01372", "HG01374", "HG01375", "HG01376", "HG01377", "HG01378",
        "HG01379", "HG01383", "HG01384", "HG01385", "HG01389", "HG01390", "HG01391",
        "HG01431", "HG01432", "HG01433", "HG01435", "HG01437", "HG01438", "HG01439",
        "HG01440", "HG01441", "HG01442", "HG01443", "HG01444", "HG01445", "HG01447",
        "HG01452", "HG01453", "HG01454", "HG01455", "HG01456", "HG01457", "HG01459",
        "HG01461", "HG01462", "HG01463", "HG01464", "HG01465", "HG01466", "HG01468",
        "HG01471", "HG01473", "HG01474", "HG01477", "HG01479", "HG01480", "HG01481",
        "HG01482", "HG01483", "HG01484", "HG01485", "HG01486", "HG01487", "HG01488",
        "HG01489", "HG01490", "HG01491", "HG01492", "HG01493", "HG01494", "HG01495",
        "HG01496", "HG01497", "HG01498", "HG01499", "HG01550", "HG01551", "HG01552",
        "HG01556",
    ],
    "PUR": [  # Puerto Ricans in Puerto Rico
        "HG00551", "HG00552", "HG00553", "HG00554", "HG00555", "HG00637", "HG00638",
        "HG00639", "HG00640", "HG00641", "HG00642", "HG00731", "HG00732", "HG00733",
        "HG00734", "HG00735", "HG00736", "HG00737", "HG00738", "HG00739", "HG00740",
        "HG00741", "HG00742", "HG00743", "HG01047", "HG01048", "HG01049", "HG01050",
        "HG01051", "HG01052", "HG01053", "HG01054", "HG01055", "HG01056", "HG01058",
        "HG01060", "HG01061", "HG01062", "HG01063", "HG01064", "HG01066", "HG01067",
        "HG01068", "HG01069", "HG01070", "HG01071", "HG01072", "HG01073", "HG01074",
        "HG01075", "HG01077", "HG01079", "HG01080", "HG01081", "HG01082", "HG01083",
        "HG01084", "HG01085", "HG01086", "HG01087", "HG01088", "HG01089", "HG01090",
        "HG01092", "HG01094", "HG01095", "HG01096", "HG01097", "HG01098", "HG01099",
        "HG01100", "HG01101", "HG01102", "HG01103", "HG01104", "HG01105", "HG01106",
        "HG01107", "HG01108", "HG01109", "HG01110", "HG01111", "HG01161", "HG01162",
        "HG01164", "HG01167", "HG01168", "HG01169", "HG01170", "HG01171", "HG01172",
        "HG01173", "HG01174", "HG01175", "HG01176", "HG01177", "HG01178", "HG01182",
        "HG01183", "HG01184", "HG01187", "HG01188", "HG01189", "HG01190", "HG01191",
        "HG01192", "HG01195", "HG01197", "HG01198", "HG01199", "HG01200", "HG01204",
        "HG01205", "HG01206", "HG01241", "HG01242", "HG01243", "HG01247", "HG01248",
        "HG01249", "HG01286", "HG01301", "HG01302", "HG01303", "HG01305", "HG01308",
        "HG01311", "HG01312", "HG01322", "HG01323", "HG01324", "HG01325", "HG01326",
        "HG01327", "HG01392", "HG01393", "HG01394", "HG01395", "HG01396", "HG01397",
        "HG01398", "HG01402", "HG01403", "HG01404", "HG01405", "HG01411", "HG01412",
        "HG01413", "HG01414", "HG01415",
    ],
    "CEU": [  # Utah residents (CEPH) with European ancestry
        "NA06984", "NA06985", "NA06986", "NA06989", "NA06991", "NA06993", "NA06994",
        "NA06995", "NA06997", "NA07000", "NA07014", "NA07019", "NA07022", "NA07029",
        "NA07031", "NA07034", "NA07037", "NA07045", "NA07048", "NA07051", "NA07055",
        "NA07056", "NA07340", "NA07345", "NA07346", "NA07347", "NA07348", "NA07349",
        "NA07357", "NA07435", "NA10830", "NA10831", "NA10835", "NA10836", "NA10837",
        "NA10838", "NA10839", "NA10840", "NA10842", "NA10843", "NA10845", "NA10846",
        "NA10847", "NA10850", "NA10851", "NA10852", "NA10853", "NA10854", "NA10855",
        "NA10856", "NA10857", "NA10859", "NA10860", "NA10861", "NA10863", "NA10864",
        "NA10865", "NA11829", "NA11830", "NA11831", "NA11832", "NA11839", "NA11840",
        "NA11843", "NA11881", "NA11882", "NA11891", "NA11892", "NA11893", "NA11894",
        "NA11917", "NA11918", "NA11919", "NA11920", "NA11930", "NA11931", "NA11932",
        "NA11933", "NA11992", "NA11993", "NA11994", "NA11995", "NA12003", "NA12004",
        "NA12005", "NA12006", "NA12043", "NA12044", "NA12045", "NA12046", "NA12056",
        "NA12057", "NA12058", "NA12144", "NA12145", "NA12146", "NA12154", "NA12155",
        "NA12156", "NA12234", "NA12236", "NA12239", "NA12248", "NA12249", "NA12264",
        "NA12272", "NA12273", "NA12274", "NA12275", "NA12282", "NA12283", "NA12286",
        "NA12287", "NA12329", "NA12335", "NA12336", "NA12340", "NA12341", "NA12342",
        "NA12343", "NA12344", "NA12347", "NA12348", "NA12375", "NA12376", "NA12383",
        "NA12386", "NA12399", "NA12400", "NA12413", "NA12414", "NA12485", "NA12489",
        "NA12546", "NA12707", "NA12708", "NA12716", "NA12717", "NA12718", "NA12739",
        "NA12740", "NA12748", "NA12749", "NA12750", "NA12751", "NA12752", "NA12753",
        "NA12760", "NA12761", "NA12762", "NA12763", "NA12766", "NA12767", "NA12775",
        "NA12776", "NA12777", "NA12778", "NA12801", "NA12802", "NA12812", "NA12813",
        "NA12814", "NA12815", "NA12817", "NA12818", "NA12827", "NA12828", "NA12829",
        "NA12830", "NA12832", "NA12842", "NA12843", "NA12864", "NA12865", "NA12872",
        "NA12873", "NA12874", "NA12875", "NA12877", "NA12878", "NA12889", "NA12890",
        "NA12891", "NA12892",
    ],
}


@dataclass
class SampleEntry:
    sample_id: str
    population: str
    bam_url: str
    bai_url: str


def find_mapped_bam_url(sample: str, pop: str) -> Tuple[str, str]:
    """
    Query the 1000G EBI FTP listing to find the actual mapped BAM URL.

    Dates in filenames vary by sample (e.g. 20120522, 20121211). Rather than
    hardcoding, we parse the directory listing at runtime and match the pattern:
        {sample}.mapped.ILLUMINA.bwa.{POP}.low_coverage.{date}.bam

    Returns (bam_url, bai_url).
    Raises FileNotFoundError if no matching BAM is found.
    Raises urllib.error.HTTPError (404) if the sample has no Phase 3 directory.
    """
    dir_url = f"{FTP_BASE}/{sample}/alignment/"
    with urllib.request.urlopen(dir_url, timeout=30) as resp:
        html = resp.read().decode()

    # Match any pop code -- some samples carry a different code on FTP than
    # their population assignment (e.g. HG01241 is CLM but BAM labelled PUR).
    match = re.search(
        rf'href="({re.escape(sample)}\.mapped\.ILLUMINA\.bwa\.\w+\.low_coverage\.\d+\.bam)"',
        html,
    )
    if not match:
        raise FileNotFoundError(
            f"No mapped BAM found for {sample}/{pop} at {dir_url}"
        )

    filename = match.group(1)
    bam_url = dir_url + filename
    bai_url = bam_url + ".bai"
    return bam_url, bai_url


def build_manifest(
    populations: Optional[List[str]] = None,
    skip_missing: bool = True,
) -> List[SampleEntry]:
    """
    Build the list of SampleEntry objects for the given populations.

    BAM URLs are discovered dynamically by querying the 1000G EBI FTP directory
    listing -- this handles per-sample date variations in filenames.

    Parameters
    ----------
    populations:
        Subset of populations to include. Defaults to all defined populations.
    skip_missing:
        If True (default), samples whose FTP directory returns HTTP 404 are
        silently skipped with a log.warning rather than raising an exception.
        These are typically PED-listed parents not sequenced in Phase 3.

    Returns
    -------
    List[SampleEntry]
        One entry per sample with BAM + BAI URLs.
    """
    import urllib.error

    if populations is None:
        populations = list(POPULATION_SAMPLES.keys())

    entries: List[SampleEntry] = []
    skipped: List[str] = []

    for pop in populations:
        if pop not in POPULATION_SAMPLES:
            raise ValueError(
                f"Unknown population '{pop}'. Valid: {list(POPULATION_SAMPLES)}"
            )
        for sample in POPULATION_SAMPLES[pop]:
            try:
                bam_url, bai_url = find_mapped_bam_url(sample, pop)
            except urllib.error.HTTPError as exc:
                if skip_missing and exc.code == 404:
                    log.warning(
                        "[%s/%s] No Phase 3 BAM directory (HTTP 404) -- skipping",
                        sample, pop,
                    )
                    skipped.append(sample)
                    continue
                raise
            except FileNotFoundError as exc:
                if skip_missing:
                    log.warning("[%s/%s] %s -- skipping", sample, pop, exc)
                    skipped.append(sample)
                    continue
                raise
            entries.append(SampleEntry(
                sample_id=sample,
                population=pop,
                bam_url=bam_url,
                bai_url=bai_url,
            ))

    if skipped:
        log.warning(
            "Skipped %d samples with no Phase 3 BAM: %s",
            len(skipped), skipped,
        )

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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    manifest = build_manifest()
    df = manifest_to_df(manifest)
    print(f"Total samples in manifest: {len(df)}")
    print(df.groupby("population").size().rename("n_samples").to_string())
    print("\nSample rows:")
    print(df.head(10).to_string(index=False))
