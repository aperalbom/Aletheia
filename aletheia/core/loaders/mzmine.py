r"""
core/loaders/mzmine.py

Loader for MZmine 3 quant CSV exports (the GNPS-style _iimn_quant.csv or
the classic _feature_csv).

Recognises the canonical MZmine 3 header pattern:
    row ID, row m/z, row retention time, [row ion mobility,] [row CCS,]
    [row identity columns,] <filename>.mzML Peak area, ...

Sample columns end with ' Peak area' (with a space) and the filename
typically carries the extension ('.mzML', '.mzXML', '.raw', '.cdf').
The loader strips that suffix to obtain the logical sample identifier.

Auto-classification heuristic for the role of each sample
---------------------------------------------------------
1.  QC dilution: name matches ``(?i)QC\s*[_-]?(\d{1,3})\s*%?`` and the
    captured number is in {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}.
2.  QC pool:     contains ``QC`` (case-insensitive) without a recognised
    dilution number, or contains ``pool``.
3.  Blank:       contains ``blank`` or ``blk`` (case-insensitive).
4.  Sample:      otherwise.

The user can override every assignment via the Sample-Mapping UI; the
heuristic is only the starting point.
"""

from __future__ import annotations

import re
from typing import ClassVar

import pandas as pd

from ..schema import (
    ParsedDataset, SampleRecord,
    ROLE_BLANK, ROLE_QC_DIL, ROLE_QC_POOL, ROLE_SAMPLE,
)
from ._base import Loader


# MZmine 3 metadata columns that appear before sample columns. Any header
# that does not end in ' Peak area' is treated as metadata.
_PEAK_AREA_SUFFIX_RE = re.compile(r"\s+(Peak area|peak area)\s*$")

# Filename extensions to strip when deriving the sample id.
_EXT_RE = re.compile(r"\.(mzML|mzXML|raw|cdf|d)$", re.IGNORECASE)

# QC dilution heuristic. Captures the percentage.
_QC_DIL_RE = re.compile(r"(?i)(?<![A-Za-z])QC[ _-]?(\d{1,3})\s*%?")
# Accepted dilution percentages.
_QC_DIL_LEVELS = {10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100}

# Replicate-number heuristic: trailing _<digits> or _R<digits> or just a
# trailing integer separated by underscore.
_REP_RE = re.compile(r"[_-](?:R|Rep|rep)(\d{1,3})$", re.IGNORECASE)


def _strip_sample_suffix(col: str) -> str:
    """Remove the trailing ' Peak area' marker."""
    return _PEAK_AREA_SUFFIX_RE.sub("", col).strip()


def _logical_sample_name(col: str) -> str:
    """Derive a clean sample identifier from a MZmine sample column."""
    name = _strip_sample_suffix(col)
    name = _EXT_RE.sub("", name)
    return name.strip()


def _classify_role(name: str) -> tuple[str, int | None]:
    """Return (role, dilution_level) for a logical sample name."""
    m = _QC_DIL_RE.search(name)
    if m:
        level = int(m.group(1))
        if level in _QC_DIL_LEVELS:
            return ROLE_QC_DIL, level
    low = name.lower()
    if "qc" in low or "pool" in low:
        return ROLE_QC_POOL, None
    if "blank" in low or low.startswith("blk"):
        return ROLE_BLANK, None
    return ROLE_SAMPLE, None


def _replicate_num(name: str, by_id: dict[str, int]) -> int:
    """Heuristic replicate numbering.

    Strategy:
    * If the name ends in ``_R\\d`` / ``_rep\\d`` / ``_\\d``, take the captured
      integer as the replicate number.
    * Otherwise assign a sequential 1, 2, 3 ... within the group of identical
      sample IDs (after stripping the trailing rep tag).
    """
    m = _REP_RE.search(name)
    if m:
        return int(m.group(1))
    by_id.setdefault(name, 0)
    by_id[name] += 1
    return by_id[name]


def _sample_id(name: str) -> str:
    """Strip the trailing replicate marker so that all replicates of the
    same sample share a single ``sample_id``."""
    return _REP_RE.sub("", name).rstrip("_-")


class MZmineLoader(Loader):
    """Loader for MZmine 3 quantification CSV exports."""

    FORMAT_NAME:  ClassVar[str] = "mzmine"
    FORMAT_LABEL: ClassVar[str] = "MZmine 3 (quant CSV)"

    @classmethod
    def _can_read(cls, head_df: pd.DataFrame) -> bool:
        cols = set(head_df.columns)
        needed = {"row ID", "row m/z", "row retention time"}
        return needed.issubset(cols)

    def _read(self, path: str, **kwargs) -> ParsedDataset:
        raw = pd.read_csv(path, encoding="latin1",
                          on_bad_lines="skip", engine="python")
        raw = raw.loc[:, ~raw.columns.str.match(r"Unnamed")]

        # ---- split header into metadata vs sample columns -----------------
        sample_cols = [c for c in raw.columns
                       if _PEAK_AREA_SUFFIX_RE.search(c)]
        meta_cols   = [c for c in raw.columns if c not in sample_cols]

        if "row ID" not in meta_cols:
            raise ValueError(
                "MZmineLoader: required column 'row ID' not found."
            )

        # ---- features ------------------------------------------------------
        features = raw[meta_cols].copy()
        features["feature_id"] = features["row ID"].astype(str)
        if "row m/z" in features.columns:
            features["mz"] = features["row m/z"]
        if "row retention time" in features.columns:
            features["rt"] = features["row retention time"]
        for must in ("mz", "rt"):
            if must not in features.columns:
                features[must] = pd.NA
        # Optional canonical aliases for identification when present.
        if "row identity (main ID)" in features.columns and "Name" not in features.columns:
            features["Name"] = features["row identity (main ID)"]

        # ---- intensities + sample records ---------------------------------
        intens = raw[sample_cols].copy()
        intens.index = features["feature_id"].values
        intens.index.name = None

        rep_counter: dict[str, int] = {}
        records: list[SampleRecord] = []
        for col in sample_cols:
            full = _logical_sample_name(col)
            sid  = _sample_id(full)
            rep  = _replicate_num(full, rep_counter)
            role, dil = _classify_role(sid)
            records.append(SampleRecord(
                column_name=col,
                sample_id=sid,
                replicate_num=rep,
                role=role,
                dilution_level=dil,
            ))

        return ParsedDataset(
            features=features,
            intensities=intens,
            samples=records,
            source_format=self.FORMAT_NAME,
            extra={"path": path,
                   "n_meta_cols": len(meta_cols),
                   "n_sample_cols": len(sample_cols)},
        )
