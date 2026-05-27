"""tests/test_loaders_msdial.py — MS-DIAL loader regression."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders.msdial import MSDIALLoader          # noqa: E402
from core.loaders import sniff, load                  # noqa: E402
from core.schema import (                              # noqa: E402
    ROLE_QC_DIL, ROLE_QC_POOL, ROLE_SAMPLE,
)


NOTAME_MERGED_CSV  = Path("/sessions/nice-jolly-babbage/mnt/outputs/notame_data/merged_sample.csv")
NOTAME_MERGED_PHENO = Path("/sessions/nice-jolly-babbage/mnt/outputs/notame_data/merged_sample_pheno.csv")


def _make_synthetic_msdial_csv() -> str:
    rng = np.random.default_rng(2026)
    n_features = 12
    samples = [
        "S01_R1.mzML", "S01_R2.mzML",
        "S02_R1.mzML", "S02_R2.mzML",
        "QC_R1.mzML", "QC_R2.mzML", "QC_R3.mzML",
        "QC20_R1.mzML", "QC20_R2.mzML",
        "QC50_R1.mzML", "QC50_R2.mzML",
        "QC100_R1.mzML", "QC100_R2.mzML",
    ]
    df = pd.DataFrame({
        "Alignment_ID":   list(range(1, n_features + 1)),
        "Average_Mz":     rng.uniform(80, 1200, n_features),
        "Average_Rt_min_": rng.uniform(0.5, 12, n_features),
        "Metabolite_name": [""] * n_features,
        "Adduct_ion_name": ["[M+H]+"] * n_features,
        "Formula":        [""] * n_features,
        "Flag":           [""] * n_features,
    })
    for c in samples:
        df[c] = rng.uniform(1e3, 1e6, n_features).round(2)
    out = HERE / "fixture_msdial.csv"
    df.to_csv(out, index=False)
    return str(out)


# ============================================================================

def test_sniff_detects_msdial():
    path = _make_synthetic_msdial_csv()
    assert sniff(path) == "msdial"


def test_msdial_loader_validates():
    path = _make_synthetic_msdial_csv()
    ds = load(path)
    ds.validate()
    assert ds.source_format == "msdial"
    assert ds.n_features() == 12
    assert ds.n_samples_total() == 13

    by_id = {r.sample_id: r.role for r in ds.samples}
    assert by_id["S01"] == ROLE_SAMPLE
    assert by_id["QC"] == ROLE_QC_POOL
    assert by_id["QC20"] == ROLE_QC_DIL
    assert by_id["QC100"] == ROLE_QC_DIL


def test_msdial_legacy_dict():
    path = _make_synthetic_msdial_csv()
    ds = load(path)
    legacy = ds.to_legacy_dict()
    assert legacy["n_metabolites"] == 12
    assert legacy["reps_per_level"] == 2
    assert len(legacy["qc_dil_df"]) == 6


def test_msdial_canonical_aliases():
    path = _make_synthetic_msdial_csv()
    ds = load(path)
    assert "feature_id" in ds.features.columns
    assert "mz" in ds.features.columns
    assert "rt" in ds.features.columns
    assert ds.features["mz"].notna().all()
    assert ds.features["rt"].notna().all()


def test_notame_real_data_loads():
    """Real notame data loads, but sample roles are not inferrable from
    column names alone (notame uses pheno_data for that). Without pheno,
    the loader defaults every sample to ROLE_SAMPLE — which is the
    documented behaviour; the user fixes it via the Sample-Mapping UI."""
    if not NOTAME_MERGED_CSV.exists():
        return
    ds = load(str(NOTAME_MERGED_CSV))
    ds.validate()
    assert ds.source_format == "msdial"
    assert ds.n_features() == 83
    assert ds.n_samples_total() == 218
    # Without pheno_data, the heuristic cannot identify QCs:
    by_role = {}
    for r in ds.samples:
        by_role[r.role] = by_role.get(r.role, 0) + 1
    # Every sample default to ROLE_SAMPLE since column names lack QC tags.
    assert by_role.get(ROLE_SAMPLE, 0) == 218


def test_notame_real_data_with_pheno_overlay():
    """When a paired pheno CSV is available, the user can post-process the
    ParsedDataset to set roles from pheno_data['QC']. We verify the count."""
    if not (NOTAME_MERGED_CSV.exists() and NOTAME_MERGED_PHENO.exists()):
        return
    ds = load(str(NOTAME_MERGED_CSV))
    pheno = pd.read_csv(NOTAME_MERGED_PHENO)
    # Build a {Sample_ID → role} map (Sample_ID matches the column header).
    qc_map = {row["Sample_ID"]: row["QC"] for _, row in pheno.iterrows()}
    # Re-classify roles.
    from core.schema import SampleRecord
    new_samples = []
    for r in ds.samples:
        target = qc_map.get(r.sample_id, "Sample")
        new_role = ROLE_QC_POOL if target == "QC" else ROLE_SAMPLE
        new_samples.append(SampleRecord(
            column_name=r.column_name,
            sample_id=r.sample_id,
            replicate_num=r.replicate_num,
            role=new_role,
            dilution_level=None,
        ))
    ds.samples = new_samples

    qc_count = sum(1 for r in ds.samples if r.role == ROLE_QC_POOL)
    assert qc_count == 18  # matches our earlier characterisation
