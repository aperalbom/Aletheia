"""tests/test_loaders_integration.py

Integration tests across the full loader registry: verifies that sniff()
unambiguously picks the right loader for each fixture, that the registry
exposes the documented formats, and that the GenericCSVLoader honours its
manual-mapping contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders import sniff, load, available_formats   # noqa: E402
from core.schema  import ROLE_QC_DIL, ROLE_QC_POOL, ROLE_SAMPLE  # noqa: E402


def test_registry_lists_all_formats():
    fmts = available_formats()
    assert set(fmts) == {"metaboscape", "mzmine", "msdial", "xcms", "generic"}


def test_sniff_disambiguates_each_format():
    """Build a minimal fixture for each format and verify sniff picks it."""
    import test_loaders_metaboscape as M
    import test_loaders_mzmine      as Z
    import test_loaders_xcms        as X
    import test_loaders_msdial      as D

    assert sniff(M._make_synthetic_metaboscape_csv()) == "metaboscape"
    assert sniff(Z._make_synthetic_mzmine_csv())      == "mzmine"
    assert sniff(X._make_synthetic_xcms_csv())        == "xcms"
    assert sniff(D._make_synthetic_msdial_csv())      == "msdial"


def test_generic_loader_requires_explicit_mapping():
    """GenericCSVLoader is never selected by sniff and demands a manual map."""
    # Build an arbitrary CSV that none of the specialised loaders recognise.
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "my_id":  ["A", "B", "C"],
        "my_mz":  [100.0, 200.0, 300.0],
        "my_rt":  [1.0, 2.0, 3.0],
        "X1":     rng.uniform(1e3, 1e6, 3),
        "X2":     rng.uniform(1e3, 1e6, 3),
    })
    path = HERE / "fixture_generic.csv"
    df.to_csv(path, index=False)

    # sniff returns None (no specialised match, generic never claims).
    assert sniff(str(path)) is None

    # Explicit load with fmt="generic" + full mapping works.
    ds = load(str(path), fmt="generic",
              feature_id_col="my_id", mz_col="my_mz", rt_col="my_rt",
              sample_cols=["X1", "X2"],
              sample_roles={"X1": "sample", "X2": "qc_pool"})
    ds.validate()
    assert ds.n_features() == 3
    assert ds.n_samples_total() == 2
    by_id = {r.column_name: r.role for r in ds.samples}
    assert by_id["X1"] == ROLE_SAMPLE
    assert by_id["X2"] == ROLE_QC_POOL


def test_unknown_format_raises():
    """Explicit fmt= must match an existing loader."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"a": [1], "b": [2]})
    path = HERE / "fixture_unknown.csv"
    df.to_csv(path, index=False)
    import pytest_compat as _
    try:
        load(str(path))
    except ValueError as e:
        assert "auto-detect" in str(e)
    else:
        raise AssertionError("expected ValueError for un-sniffable file")
