"""
core/loaders/xcms.py

Loader for XCMS (R, Bioconductor) featureValues / peakTable exports.

XCMS does not have a single canonical CSV format; users typically export
either:

(a) Classic `xcms::peakTable()` output:
    mz, mzmin, mzmax, rt, rtmin, rtmax, into, intb, maxo, sn, ...
    <one column per sample with the raw filename as header>

(b) Modern `XCMSnExp` / `xcmsExperiment` featureValues data frame:
    Feature, mzmed, rtmed, npeaks, ms_level,
    <one column per sample with the raw filename as header>

Recognition heuristic
---------------------
* The header must contain ``mz`` (lowercase) plus ``rt`` or ``rtmed``.
* Sample columns are everything that is **not** one of the canonical
  XCMS metadata columns. Most XCMS exports use filenames as sample
  headers (``.mzML``, ``.mzXML``, ``.raw``, ``.cdf``); the suffix is
  stripped to derive the logical sample id.
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


# Columns that XCMS pipelines typically emit alongside the intensity matrix.
XCMS_META_COLUMNS = {
    "Feature", "feature",
    "mz", "mzmin", "mzmax", "mzmed",
    "rt", "rtmin", "rtmax", "rtmed",
    "npeaks", "ms_level",
    "into", "intb", "maxo", "sn",
    "sample", "isFilledColumn",
}

# Filename extensions to strip when deriving the sample id.
_EXT_RE = re.compile(r"\.(mzML|mzXML|raw|cdf|d)$", re.IGNORECASE)

# Same heuristics as MZmine for QC/blank classification.
_QC_DIL_RE = re.compile(r"(?i)(?<![A-Za-z])QC[ _-]?(\d{1,3})\s*%?")
_QC_DIL_LEVELS = {10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100}
_REP_RE = re.compile(r"[_-](?:R|Rep|rep)(\d{1,3})$", re.IGNORECASE)


def _logical_sample_name(col: str) -> str:
    return _EXT_RE.sub("", col).strip()


def _classify_role(name: str) -> tuple[str, int | None]:
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
    m = _REP_RE.search(name)
    if m:
        return int(m.group(1))
    by_id.setdefault(name, 0)
    by_id[name] += 1
    return by_id[name]


def _sample_id(name: str) -> str:
    return _REP_RE.sub("", name).rstrip("_-")


class XcmsLoader(Loader):
    """Loader for XCMS featureValues / peakTable CSV exports."""

    FORMAT_NAME:  ClassVar[str] = "xcms"
    FORMAT_LABEL: ClassVar[str] = "XCMS (featureValues / peakTable CSV)"

    @classmethod
    def _can_read(cls, head_df: pd.DataFrame) -> bool:
        cols = set(head_df.columns)
        # Need lowercase mz + (rt or rtmed). Must NOT look like MetaboScape
        # ("Bucket label") nor MZmine ("row ID").
        has_mz = "mz" in cols or "mzmed" in cols
        has_rt = "rt" in cols or "rtmed" in cols
        not_other = ("Bucket label" not in cols
                     and "row ID" not in cols
                     and "Alignment_ID" not in cols
                     and "Alignment ID" not in cols)
        return has_mz and has_rt and not_other

    def _read(self, path: str, **kwargs) -> ParsedDataset:
        raw = pd.read_csv(path, encoding="latin1",
                          on_bad_lines="skip", engine="python")
        raw = raw.loc[:, ~raw.columns.str.match(r"Unnamed")]

        meta_cols   = [c for c in raw.columns if c in XCMS_META_COLUMNS]
        sample_cols = [c for c in raw.columns if c not in XCMS_META_COLUMNS]

        if not meta_cols:
            raise ValueError(
                "XcmsLoader: no recognised XCMS metadata columns "
                "(mz/rt/mzmed/rtmed)."
            )

        # ---- features ------------------------------------------------------
        features = raw[meta_cols].copy()

        # feature_id: prefer 'Feature', else generate from index.
        if "Feature" in features.columns:
            features["feature_id"] = features["Feature"].astype(str)
        elif "feature" in features.columns:
            features["feature_id"] = features["feature"].astype(str)
        else:
            features["feature_id"] = [f"F{i:05d}" for i in range(len(features))]

        # mz canonical alias.
        if "mz" in features.columns:
            features["mz"] = features["mz"]
        elif "mzmed" in features.columns:
            features["mz"] = features["mzmed"]
        else:
            features["mz"] = pd.NA

        # rt canonical alias.
        if "rt" in features.columns:
            features["rt"] = features["rt"]
        elif "rtmed" in features.columns:
            features["rt"] = features["rtmed"]
        else:
            features["rt"] = pd.NA

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
