"""tests/test_loaders_xcms.py — XCMS loader regression."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders.xcms import XcmsLoader              # noqa: E402
from core.loaders import sniff, load                  # noqa: E402
from core.schema import (                              # noqa: E402
    ROLE_QC_DIL, ROLE_QC_POOL, ROLE_BLANK, ROLE_SAMPLE,
)


def _make_synthetic_xcms_csv() -> str:
    rng = np.random.default_rng(2026)
    n_features = 18
    samples = [
        "S01_R1.mzML", "S01_R2.mzML", "S01_R3.mzML",
        "S02_R1.mzML", "S02_R2.mzML", "S02_R3.mzML",
        "QC_pool_R1.mzML", "QC_pool_R2.mzML", "QC_pool_R3.mzML",
        "QC20_R1.mzML", "QC20_R2.mzML",
        "QC40_R1.mzML", "QC40_R2.mzML",
        "QC60_R1.mzML", "QC60_R2.mzML",
        "QC80_R1.mzML", "QC80_R2.mzML",
        "QC100_R1.mzML", "QC100_R2.mzML",
        "blank.mzML",
    ]
    df = pd.DataFrame({
        "Feature": [f"FT{i:04d}" for i in range(n_features)],
        "mzmed":   rng.uniform(80, 1200, n_features),
        "rtmed":   rng.uniform(30, 720, n_features),
        "npeaks":  rng.integers(1, 6, n_features),
    })
    for c in samples:
        df[c] = rng.uniform(1e3, 1e6, n_features).round(2)
    out = HERE / "fixture_xcms.csv"
    df.to_csv(out, index=False)
    return str(out)


def test_sniff_detects_xcms():
    path = _make_synthetic_xcms_csv()
    assert sniff(path) == "xcms"


def test_xcms_loader_validates_and_classifies():
    path = _make_synthetic_xcms_csv()
    ds = load(path)
    ds.validate()
    assert ds.source_format == "xcms"
    assert ds.n_features() == 18
    assert ds.n_samples_total() == 20

    by_id = {r.sample_id: r.role for r in ds.samples}
    assert by_id["S01"] == ROLE_SAMPLE
    assert by_id["QC20"] == ROLE_QC_DIL
    assert by_id["QC_pool"] == ROLE_QC_POOL
    assert by_id["blank"] == ROLE_BLANK


def test_xcms_legacy_dict_roundtrip():
    path = _make_synthetic_xcms_csv()
    ds = load(path)
    legacy = ds.to_legacy_dict()
    assert legacy["n_metabolites"] == 18
    assert legacy["reps_per_level"] == 2     # 2 reps per QC dilution level
    assert len(legacy["qc_dil_df"]) == 10    # 5 levels × 2 reps
    assert len(legacy["qc_norm_df"]) == 3    # QC_pool_01..03


def test_mz_rt_canonical_aliases_present():
    path = _make_synthetic_xcms_csv()
    ds = load(path)
    # Even though source had 'mzmed'/'rtmed', the schema requires mz/rt.
    assert "mz" in ds.features.columns
    assert "rt" in ds.features.columns
    assert ds.features["mz"].notna().all()
    assert ds.features["rt"].notna().all()


def test_xcms_does_not_confuse_with_metaboscape():
    """If we feed the XCMS fixture with a MetaboScape-style 'Bucket label'
    column added, the sniffer must still pick metaboscape (more specific)."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "Bucket label": ["X1"],
        "mz":           [100.0],
        "rt":           [1.0],
        "RT":           [1.0],
        "m/z":          [100.0],
        "S1.mzML":      [1000.0],
    })
    out = HERE / "fixture_xcms_ambiguous.csv"
    df.to_csv(out, index=False)
    assert sniff(str(out)) == "metaboscape"
