"""
tests/test_loaders_mzmine.py

Regression: MZmineLoader recognises and parses a canonical MZmine 3 quant
CSV, auto-classifies QC dilution + pool samples, and produces a valid
ParsedDataset.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders.mzmine import (              # noqa: E402
    MZmineLoader, _logical_sample_name, _classify_role, _sample_id,
)
from core.loaders import sniff, load           # noqa: E402
from core.schema import (                       # noqa: E402
    ROLE_QC_DIL, ROLE_QC_POOL, ROLE_BLANK, ROLE_SAMPLE,
)


def _make_synthetic_mzmine_csv() -> str:
    """Synthetic MZmine 3 export with realistic column names."""
    rng = np.random.default_rng(2026)
    n_features = 15

    samples = [
        "S01_R1.mzML Peak area",
        "S01_R2.mzML Peak area",
        "S01_R3.mzML Peak area",
        "S02_R1.mzML Peak area",
        "S02_R2.mzML Peak area",
        "S02_R3.mzML Peak area",
        "QC_pool_R1.mzML Peak area",
        "QC_pool_R2.mzML Peak area",
        "QC_pool_R3.mzML Peak area",
        "QC20_R1.mzML Peak area",
        "QC20_R2.mzML Peak area",
        "QC40_R1.mzML Peak area",
        "QC40_R2.mzML Peak area",
        "QC60_R1.mzML Peak area",
        "QC60_R2.mzML Peak area",
        "QC80_R1.mzML Peak area",
        "QC80_R2.mzML Peak area",
        "QC100_R1.mzML Peak area",
        "QC100_R2.mzML Peak area",
        "blank_01.mzML Peak area",
    ]
    df = pd.DataFrame({
        "row ID":               list(range(1, n_features + 1)),
        "row m/z":              rng.uniform(80, 1200, n_features),
        "row retention time":   rng.uniform(0.5, 12, n_features),
        "row identity (main ID)": [""] * n_features,
    })
    for c in samples:
        df[c] = rng.uniform(1e3, 1e6, n_features).round(2)
    out = HERE / "fixture_mzmine.csv"
    df.to_csv(out, index=False)
    return str(out)


# ============================================================================

def test_helpers_logical_name_and_classify():
    assert _logical_sample_name("S01_R1.mzML Peak area") == "S01_R1"
    assert _logical_sample_name("QC20_R1.raw Peak area") == "QC20_R1"
    assert _logical_sample_name("blank_01.mzML Peak area") == "blank_01"

    assert _sample_id("S01_R1") == "S01"
    assert _sample_id("QC20_R1") == "QC20"
    assert _sample_id("QC_pool_01") == "QC_pool_01"  # no R prefix, NOT stripped
    assert _sample_id("QC_pool_R1") == "QC_pool"     # R prefix, stripped

    role, dil = _classify_role("QC20")
    assert role == ROLE_QC_DIL and dil == 20
    role, dil = _classify_role("QC100")
    assert role == ROLE_QC_DIL and dil == 100
    role, dil = _classify_role("QC_pool")
    assert role == ROLE_QC_POOL and dil is None
    role, dil = _classify_role("S01")
    assert role == ROLE_SAMPLE and dil is None
    role, dil = _classify_role("blank_01")
    assert role == ROLE_BLANK and dil is None


def test_sniff_detects_mzmine():
    path = _make_synthetic_mzmine_csv()
    assert sniff(path) == "mzmine"


def test_mzmine_loader_load_and_validate():
    path = _make_synthetic_mzmine_csv()
    ds = load(path)
    ds.validate()
    assert ds.source_format == "mzmine"
    assert ds.n_features() == 15
    assert ds.n_samples_total() == 20

    # Spot-check roles
    by_id = {r.sample_id: r.role for r in ds.samples}
    assert by_id["S01"] == ROLE_SAMPLE
    assert by_id["S02"] == ROLE_SAMPLE
    assert by_id["QC20"] == ROLE_QC_DIL
    assert by_id["QC100"] == ROLE_QC_DIL
    assert by_id["QC_pool"] == ROLE_QC_POOL
    assert by_id["blank_01"] == ROLE_BLANK

    # Spot-check dilution levels
    dl = {r.sample_id: r.dilution_level for r in ds.samples if r.role == ROLE_QC_DIL}
    assert dl == {"QC20": 20, "QC40": 40, "QC60": 60, "QC80": 80, "QC100": 100}


def test_mzmine_legacy_dict_roundtrip():
    path = _make_synthetic_mzmine_csv()
    ds = load(path)
    legacy = ds.to_legacy_dict()
    # Same number of features
    assert legacy["n_metabolites"] == 15
    # 5 dilution levels × 2 reps each → reps_per_level = 2
    assert legacy["reps_per_level"] == 2
    # QC pool has 3 replicates (QC_pool_01/02/03)
    assert len(legacy["qc_norm_df"]) == 3
    # QC dilution has 10 entries (5 levels × 2 reps)
    assert len(legacy["qc_dil_df"]) == 10
