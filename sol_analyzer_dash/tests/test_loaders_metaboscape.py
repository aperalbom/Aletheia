"""
tests/test_loaders_metaboscape.py

Regression: the new MetaboScapeLoader must produce a legacy dict that is
byte-for-byte equivalent to the historical ``core.analysis.parse_file``.

If this test ever fails, the refactor has introduced a behavioural change
and we MUST not merge until it is reconciled.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make sol_analyzer_dash importable from the test file regardless of pytest cwd.
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.analysis import parse_file                            # noqa: E402
from core.loaders.metaboscape import MetaboScapeLoader          # noqa: E402
from core.loaders import sniff, load, available_formats         # noqa: E402


# =============================================================================
# Test fixtures
# =============================================================================

def _make_synthetic_metaboscape_csv() -> str:
    """Build a small CSV that mimics a Bruker MetaboScape export.

    Columns (in order):
      Bucket label, RT, m/z, Name, Formula,
      SOL999-1_[POS]1.d, SOL999-1_[POS]2.d, SOL999-1_[POS]3.d,
      SOL999-2_[POS]1.d, SOL999-2_[POS]2.d, SOL999-2_[POS]3.d,
      SOL999-QC_[POS]1.d, SOL999-QC_[POS]2.d, SOL999-QC_[POS]3.d,
      SOL999-QC20_[POS]1.d, SOL999-QC20_[POS]2.d,
      SOL999-QC40_[POS]1.d, SOL999-QC40_[POS]2.d,
      SOL999-QC60_[POS]1.d, SOL999-QC60_[POS]2.d,
      SOL999-QC80_[POS]1.d, SOL999-QC80_[POS]2.d,
      SOL999-QC100_[POS]1.d, SOL999-QC100_[POS]2.d
    """
    rng = np.random.default_rng(2026)
    n_features = 25
    sample_cols = [
        "SOL999-1_[POS]1.d", "SOL999-1_[POS]2.d", "SOL999-1_[POS]3.d",
        "SOL999-2_[POS]1.d", "SOL999-2_[POS]2.d", "SOL999-2_[POS]3.d",
        "SOL999-QC_[POS]1.d", "SOL999-QC_[POS]2.d", "SOL999-QC_[POS]3.d",
        "SOL999-QC20_[POS]1.d",  "SOL999-QC20_[POS]2.d",
        "SOL999-QC40_[POS]1.d",  "SOL999-QC40_[POS]2.d",
        "SOL999-QC60_[POS]1.d",  "SOL999-QC60_[POS]2.d",
        "SOL999-QC80_[POS]1.d",  "SOL999-QC80_[POS]2.d",
        "SOL999-QC100_[POS]1.d", "SOL999-QC100_[POS]2.d",
    ]
    raw = pd.DataFrame({
        "Bucket label": [f"F{i:03d}" for i in range(n_features)],
        "RT":           rng.uniform(0.5, 12.0, n_features),
        "m/z":          rng.uniform(80, 1200, n_features),
        "Name":         ["" for _ in range(n_features)],
        "Formula":      ["" for _ in range(n_features)],
    })
    for c in sample_cols:
        raw[c] = rng.uniform(1e3, 1e6, n_features).round(2)
    out = HERE / "fixture_metaboscape.csv"
    raw.to_csv(out, index=False)
    return str(out)


@pytest.fixture(scope="module")
def fixture_csv():
    path = _make_synthetic_metaboscape_csv()
    yield path
    # Leave the fixture on disk; it's tiny and useful for manual inspection.


# =============================================================================
# Tests
# =============================================================================

def test_available_formats_contains_metaboscape():
    assert "metaboscape" in available_formats()


def test_sniff_detects_metaboscape(fixture_csv):
    assert sniff(fixture_csv) == "metaboscape"


def test_loader_validates(fixture_csv):
    ds = load(fixture_csv)
    ds.validate()
    assert ds.source_format == "metaboscape"
    assert ds.n_features() == 25
    assert ds.n_samples_total() == 19


def test_legacy_dict_matches_parse_file(fixture_csv):
    """Core regression: every field of the dict must be equal."""
    old = parse_file(fixture_csv)
    ds  = load(fixture_csv)
    new = ds.to_legacy_dict()

    # ---- scalar fields -----------------------------------------------------
    assert old["n_metabolites"]   == new["n_metabolites"]
    assert old["n_samples"]       == new["n_samples"]
    assert old["reps_per_level"]  == new["reps_per_level"]
    assert old["reps_per_sample"] == new["reps_per_sample"]
    assert old["real_samples"]    == new["real_samples"]

    # ---- DataFrames (col_df, qc_dil_df, qc_norm_df, samp_df) --------------
    for key in ("col_df", "qc_dil_df", "qc_norm_df", "samp_df"):
        # Same columns, same content (allowing for index reset).
        a = old[key].reset_index(drop=True)
        b = new[key].reset_index(drop=True)
        assert list(a.columns) == list(b.columns), \
            f"{key}: column mismatch — old {list(a.columns)} vs new {list(b.columns)}"
        pd.testing.assert_frame_equal(a, b, check_dtype=False)

    # ---- raw ---------------------------------------------------------------
    # parse_file returns the *whole* raw csv (incl. unnamed-stripped). The
    # new loader strips the same way and re-attaches sample columns in the
    # same order; we compare on shared columns.
    common = [c for c in old["raw"].columns if c in new["raw"].columns]
    assert len(common) == old["raw"].shape[1]
    pd.testing.assert_frame_equal(
        old["raw"][common].reset_index(drop=True),
        new["raw"][common].reset_index(drop=True),
        check_dtype=False,
    )


def test_metaboscape_loader_extra_metadata(fixture_csv):
    ds = MetaboScapeLoader().load(fixture_csv)
    assert ds.extra["path"].endswith("fixture_metaboscape.csv")
    assert ds.extra["qc_pool_name"] == "QC"
    assert "QC100" in ds.extra["qc_dil_names"]


def test_run_m1_consumes_legacy_dict(fixture_csv):
    """End-to-end: feed the new loader's legacy dict into run_m1."""
    from core.analysis import run_m1
    ds = load(fixture_csv)
    parsed_new = ds.to_legacy_dict()
    parsed_old = parse_file(fixture_csv)

    out_new = run_m1(parsed_new, r2_threshold=0.6)
    out_old = run_m1(parsed_old, r2_threshold=0.6)

    # The two runs must produce identical filter outcomes.
    assert out_new["n"]            == out_old["n"]
    assert out_new["r2_threshold"] == out_old["r2_threshold"]
    pd.testing.assert_frame_equal(
        out_old["lin_df"].reset_index(drop=True),
        out_new["lin_df"].reset_index(drop=True),
        check_dtype=False,
    )
