"""tests/test_sample_mapping.py — Sample-Mapping component logic.

We don't spin up a Dash app; we exercise the row-to-record and
record-to-row converters and the summariser, which is where bugs live.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders import load                                      # noqa: E402
from core.schema  import (                                          # noqa: E402
    SampleRecord, ROLE_QC_DIL, ROLE_QC_POOL, ROLE_SAMPLE, ROLE_BLANK,
)
from components.sample_mapping import (                             # noqa: E402
    extract_records, render_summary, _record_to_row, _row_to_record,
    _summarise,
)


def test_record_row_roundtrip_keeps_role_and_dil():
    r = SampleRecord(column_name="C1", sample_id="S1",
                     replicate_num=2, role=ROLE_QC_DIL, dilution_level=40)
    row = _record_to_row(r)
    assert row["role"] == ROLE_QC_DIL
    assert row["dilution_level"] == 40
    r2 = _row_to_record(row)
    assert r2.role == ROLE_QC_DIL
    assert r2.dilution_level == 40
    assert r2.replicate_num == 2


def test_row_to_record_handles_blank_dilution():
    """If the user blanks out the dilution_level cell, treat it as None."""
    row = {"column_name": "X", "sample_id": "X", "replicate_num": 1,
           "role": ROLE_SAMPLE, "dilution_level": ""}
    r = _row_to_record(row)
    assert r.role == ROLE_SAMPLE
    assert r.dilution_level is None


def test_row_to_record_unknown_role_falls_back_to_sample():
    row = {"column_name": "X", "sample_id": "X", "replicate_num": 1,
           "role": "garbage", "dilution_level": None}
    r = _row_to_record(row)
    assert r.role == ROLE_SAMPLE


def test_qc_dil_without_level_gets_default_100():
    """SampleRecord.__post_init__ rejects qc_dil without level; the editor
    fills in a safe default so the user can correct it visually."""
    row = {"column_name": "X", "sample_id": "QC100", "replicate_num": 1,
           "role": ROLE_QC_DIL, "dilution_level": None}
    r = _row_to_record(row)
    assert r.role == ROLE_QC_DIL
    assert r.dilution_level == 100


def test_summarise_counts_roles():
    rows = [
        {"role": ROLE_SAMPLE}, {"role": ROLE_SAMPLE},
        {"role": ROLE_QC_POOL}, {"role": ROLE_QC_DIL},
        {"role": ROLE_BLANK},
    ]
    s = _summarise(rows)
    assert s[ROLE_SAMPLE] == 2
    assert s[ROLE_QC_POOL] == 1
    assert s[ROLE_QC_DIL] == 1
    assert s[ROLE_BLANK] == 1


def test_extract_records_from_synthetic_mzmine():
    import test_loaders_mzmine as M
    ds = load(M._make_synthetic_mzmine_csv())
    rows = [_record_to_row(r) for r in ds.samples]
    # Simulate the user editing the first row's role.
    rows[0]["role"] = ROLE_QC_POOL
    new_records = extract_records(rows)
    assert new_records[0].role == ROLE_QC_POOL
    # The rest are unchanged.
    for old, new in zip(ds.samples[1:], new_records[1:]):
        assert old.role == new.role


def test_render_summary_returns_chips():
    rows = [{"role": ROLE_SAMPLE}, {"role": ROLE_QC_POOL}]
    chips = render_summary(rows)
    assert len(chips) == 2
