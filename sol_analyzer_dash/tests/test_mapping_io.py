"""tests/test_mapping_io.py — sidecar JSON persistence round-trip."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.loaders import load                                      # noqa: E402
from core.loaders.mapping_io import (                              # noqa: E402
    save_mapping_json, load_mapping_json, apply_mapping,
    default_sidecar_path,
)
from core.schema import (                                          # noqa: E402
    SampleRecord, ROLE_QC_POOL, ROLE_SAMPLE, ROLE_QC_DIL,
)

NOTAME_MERGED_CSV  = Path("/sessions/nice-jolly-babbage/mnt/outputs/notame_data/merged_sample.csv")
NOTAME_MERGED_PHENO = Path("/sessions/nice-jolly-babbage/mnt/outputs/notame_data/merged_sample_pheno.csv")


def test_default_sidecar_path():
    p = default_sidecar_path("/tmp/foo.csv")
    assert p.endswith("foo_aletheia_mapping.json")


def test_roundtrip_synthetic_mzmine():
    import test_loaders_mzmine as M
    path = M._make_synthetic_mzmine_csv()
    ds = load(path)
    # Save sidecar
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        sidecar = f.name
    try:
        save_mapping_json(ds, sidecar)
        records = load_mapping_json(sidecar)
        assert len(records) == len(ds.samples)
        # Re-apply and verify it's idempotent
        apply_mapping(ds, records)
        assert {r.role for r in ds.samples} == {r.role for r in records}
    finally:
        os.unlink(sidecar)


def test_user_overrides_roles_via_sidecar():
    """User loads CSV → auto-classifies → edits roles → saves sidecar
    → reloads → applies sidecar → roles match user intent."""
    if not NOTAME_MERGED_CSV.exists():
        return
    ds = load(str(NOTAME_MERGED_CSV))
    # Initially all 218 are ROLE_SAMPLE (notame data has no QC hints in headers).
    counts_before = {}
    for r in ds.samples:
        counts_before[r.role] = counts_before.get(r.role, 0) + 1
    assert counts_before.get(ROLE_SAMPLE, 0) == 218

    # User refines via pheno_data — same approach as test_notame_real_data_with_pheno_overlay
    pheno = pd.read_csv(NOTAME_MERGED_PHENO)
    qc_map = {row["Sample_ID"]: row["QC"] for _, row in pheno.iterrows()}
    refined = []
    for r in ds.samples:
        target = qc_map.get(r.sample_id, "Sample")
        new_role = ROLE_QC_POOL if target == "QC" else ROLE_SAMPLE
        refined.append(SampleRecord(
            column_name=r.column_name,
            sample_id=r.sample_id,
            replicate_num=r.replicate_num,
            role=new_role,
            dilution_level=None,
        ))
    apply_mapping(ds, refined)

    counts_after = {}
    for r in ds.samples:
        counts_after[r.role] = counts_after.get(r.role, 0) + 1
    assert counts_after.get(ROLE_QC_POOL, 0) == 18

    # Save & reload sidecar; mapping survives the round-trip
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        sidecar = f.name
    try:
        save_mapping_json(ds, sidecar)
        new_records = load_mapping_json(sidecar)
        # Roles preserved
        roles_orig = [r.role for r in ds.samples]
        roles_new  = [r.role for r in new_records]
        assert roles_orig == roles_new
        # Reapply on a fresh load gives the same result
        ds2 = load(str(NOTAME_MERGED_CSV))
        apply_mapping(ds2, new_records)
        qc_count2 = sum(1 for r in ds2.samples if r.role == ROLE_QC_POOL)
        assert qc_count2 == 18
    finally:
        os.unlink(sidecar)


def test_apply_mapping_rejects_missing_columns():
    """If the sidecar lacks a column present in the CSV, apply_mapping errors."""
    import test_loaders_mzmine as M
    path = M._make_synthetic_mzmine_csv()
    ds = load(path)
    truncated = ds.samples[:-1]  # drop one record
    try:
        apply_mapping(ds, truncated)
    except ValueError as e:
        assert "without a matching SampleRecord" in str(e)
    else:
        raise AssertionError("expected ValueError on missing column")
