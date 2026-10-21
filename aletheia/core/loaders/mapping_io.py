"""
core/loaders/mapping_io.py

Persistence helpers for the Sample-Mapping layer.

After the user refines the auto-classified sample roles in the Sample-Mapping
UI, the mapping can be saved as a JSON sidecar next to the input CSV. Loading
that JSON restores the user-curated classification on subsequent analyses
without manual re-entry.

Sidecar format
--------------
{
  "source_format": "msdial",
  "source_file":   "merged_sample.csv",
  "samples": [
    {"column_name": "Sample_1", "sample_id": "Sample_1",
     "replicate_num": 1, "role": "qc_pool", "dilution_level": null,
     "injection_order": 1},
    ...
  ],
  "extra": {...}
}
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..schema import (
    ParsedDataset, SampleRecord,
    VALID_ROLES, ROLE_QC_DIL,
)


def _serialize_sample(s: SampleRecord) -> dict[str, Any]:
    return {
        "column_name":     s.column_name,
        "sample_id":       s.sample_id,
        "replicate_num":   int(s.replicate_num),
        "role":            s.role,
        "dilution_level":  (int(s.dilution_level)
                             if s.dilution_level is not None else None),
        "injection_order": (int(s.injection_order)
                             if s.injection_order is not None else None),
    }


def _deserialize_sample(d: dict[str, Any]) -> SampleRecord:
    role = d["role"]
    if role not in VALID_ROLES:
        raise ValueError(
            f"Unknown role {role!r} for column {d.get('column_name')!r}. "
            f"Valid: {sorted(VALID_ROLES)}"
        )
    return SampleRecord(
        column_name=d["column_name"],
        sample_id=d["sample_id"],
        replicate_num=int(d["replicate_num"]),
        role=role,
        dilution_level=(int(d["dilution_level"])
                        if d.get("dilution_level") is not None else None),
        injection_order=(int(d["injection_order"])
                         if d.get("injection_order") is not None else None),
    )


def save_mapping_json(ds: ParsedDataset, path: str | os.PathLike) -> str:
    """Write the sample mapping of *ds* to a JSON file at *path*.

    Returns the canonical string path written.
    """
    payload = {
        "source_format": ds.source_format,
        "source_file":   os.path.basename(ds.extra.get("path", "")),
        "samples":       [_serialize_sample(s) for s in ds.samples],
        "extra":         {k: v for k, v in ds.extra.items()
                          if isinstance(v, (str, int, float, bool, list, dict, type(None)))},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return str(path)


def load_mapping_json(path: str | os.PathLike) -> list[SampleRecord]:
    """Read a mapping sidecar JSON and return the list of SampleRecords.

    Caller is responsible for assigning the returned list to
    ``ds.samples`` after verifying the ``source_format`` and column names
    match the freshly loaded :class:`ParsedDataset`.
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return [_deserialize_sample(d) for d in payload["samples"]]


def apply_mapping(ds: ParsedDataset, records: list[SampleRecord]) -> ParsedDataset:
    """Replace *ds.samples* with *records*, preserving the column order.

    Validates that every column in ``ds.intensities`` has a matching record.
    Raises :class:`ValueError` on mismatch.
    """
    by_col = {r.column_name: r for r in records}
    new_records: list[SampleRecord] = []
    missing: list[str] = []
    for col in ds.intensities.columns:
        if col not in by_col:
            missing.append(col)
        else:
            new_records.append(by_col[col])
    if missing:
        raise ValueError(
            f"apply_mapping: {len(missing)} intensity column(s) without "
            f"a matching SampleRecord — examples: {missing[:5]}"
        )
    ds.samples = new_records
    return ds


def default_sidecar_path(source_path: str | os.PathLike) -> str:
    """Return ``<source>_aletheia_mapping.json`` next to the source file."""
    base = os.path.splitext(str(source_path))[0]
    return f"{base}_aletheia_mapping.json"
