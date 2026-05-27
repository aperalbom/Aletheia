"""tests/test_loaders_generic.py — GenericCSVLoader."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders import load                                  # noqa: E402
from core.loaders.generic_csv import GenericCSVLoader         # noqa: E402
from core.schema import (                                       # noqa: E402
    ROLE_SAMPLE, ROLE_QC_POOL, ROLE_QC_DIL, ROLE_BLANK, ROLE_EXCLUDE,
)


def _make_arbitrary_csv() -> str:
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "myID":  ["A", "B", "C", "D"],
        "Mass":  [100.1, 200.2, 300.3, 400.4],
        "TR":    [1.5, 2.5, 3.5, 4.5],
        "Note":  ["", "", "", ""],
        "S1":    rng.uniform(1e3, 1e6, 4),
        "S2":    rng.uniform(1e3, 1e6, 4),
        "S3":    rng.uniform(1e3, 1e6, 4),
        "Pool1": rng.uniform(1e3, 1e6, 4),
        "Dil20": rng.uniform(1e3, 1e6, 4),
        "Dil40": rng.uniform(1e3, 1e6, 4),
    })
    out = HERE / "fixture_generic_arb.csv"
    df.to_csv(out, index=False)
    return str(out)


def test_generic_requires_explicit_format():
    """sniff() must NOT pick generic; the user has to pass fmt='generic'."""
    from core.loaders import sniff
    path = _make_arbitrary_csv()
    assert sniff(path) is None


def test_generic_requires_full_mapping():
    """Missing arguments raise ValueError."""
    path = _make_arbitrary_csv()
    try:
        load(path, fmt="generic")
    except ValueError as e:
        assert "feature_id_col" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_generic_happy_path():
    path = _make_arbitrary_csv()
    ds = load(
        path, fmt="generic",
        feature_id_col="myID", mz_col="Mass", rt_col="TR",
        sample_cols=["S1", "S2", "S3", "Pool1", "Dil20", "Dil40"],
        sample_roles={
            "S1": "sample", "S2": "sample", "S3": "sample",
            "Pool1": "qc_pool",
            "Dil20": "qc_dil", "Dil40": "qc_dil",
        },
        dilution_levels={"Dil20": 20, "Dil40": 40},
    )
    ds.validate()
    assert ds.source_format == "generic"
    assert ds.n_features() == 4
    assert ds.n_samples_total() == 6

    by_col = {r.column_name: (r.role, r.dilution_level) for r in ds.samples}
    assert by_col["S1"] == (ROLE_SAMPLE, None)
    assert by_col["Pool1"] == (ROLE_QC_POOL, None)
    assert by_col["Dil20"] == (ROLE_QC_DIL, 20)
    assert by_col["Dil40"] == (ROLE_QC_DIL, 40)


def test_generic_rejects_unknown_role():
    path = _make_arbitrary_csv()
    try:
        load(path, fmt="generic",
             feature_id_col="myID", mz_col="Mass", rt_col="TR",
             sample_cols=["S1"], sample_roles={"S1": "garbage"})
    except ValueError as e:
        assert "Unknown role" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_generic_missing_column_errors():
    path = _make_arbitrary_csv()
    try:
        load(path, fmt="generic",
             feature_id_col="DOES_NOT_EXIST", mz_col="Mass", rt_col="TR",
             sample_cols=["S1"])
    except ValueError as e:
        assert "not found" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_generic_to_legacy_dict():
    path = _make_arbitrary_csv()
    ds = load(
        path, fmt="generic",
        feature_id_col="myID", mz_col="Mass", rt_col="TR",
        sample_cols=["S1", "S2", "S3", "Pool1", "Dil20", "Dil40"],
        sample_roles={
            "S1": "sample", "S2": "sample", "S3": "sample",
            "Pool1": "qc_pool",
            "Dil20": "qc_dil", "Dil40": "qc_dil",
        },
        dilution_levels={"Dil20": 20, "Dil40": 40},
    )
    legacy = ds.to_legacy_dict()
    assert legacy["n_metabolites"] == 4
    assert len(legacy["qc_norm_df"]) == 1     # Pool1
    assert len(legacy["qc_dil_df"]) == 2      # Dil20, Dil40
