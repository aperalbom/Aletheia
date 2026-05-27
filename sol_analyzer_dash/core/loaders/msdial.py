"""
core/loaders/msdial.py

Loader for MS-DIAL alignment results tables (CSV/TSV).

The MS-DIAL alignment table exported via "Export → Alignment result" has
a distinctive set of metadata columns. We recognise it by the presence
of *Alignment ID* (or *Alignment_ID*) together with *Average Mz* and
*Average Rt(min)* (or their underscore-canonicalised variants used by
notame when it ingests MS-DIAL output).

Metadata columns we treat as feature metadata
---------------------------------------------
* Alignment ID / Alignment_ID
* Average Mz / Average_Mz
* Average Rt(min) / Average_Rt_min_
* Metabolite name / Metabolite_name
* Adduct ion name / Adduct_ion_name
* Post curation result / Post_curation_result
* Fill % / Fill__
* MS/MS included / MS_MS_included
* Formula
* Ontology
* INCHIKEY
* SMILES
* Comment
* Isotope tracking parent ID / Isotope_tracking_parent_ID
* Isotope tracking weight number / Isotope_tracking_weight_number
* Dot product / Dot_product
* Reverse dot product / Reverse_dot_product
* Fragment presence % / Fragment_presence__
* Spectrum reference file name / Spectrum_reference_file_name
* MS1 isotopic spectrum / MS1_isotopic_spectrum
* MS/MS spectrum / MS_MS_spectrum
* Flag

Everything else is treated as a sample column.
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


# Canonical MS-DIAL metadata column names + the underscore-canonical forms
# used after notame's ingestion (we saw the exact list in notame's bundled
# .rda merged_sample object).
MSDIAL_META_COLUMNS = {
    # ID / coordinates
    "Alignment ID", "Alignment_ID",
    "Average Mz", "Average_Mz",
    "Average Rt(min)", "Average Rt (min)", "Average_Rt_min_",
    # Identification
    "Metabolite name", "Metabolite_name",
    "Adduct ion name", "Adduct_ion_name",
    "Post curation result", "Post_curation_result",
    "Fill %", "Fill__",
    "MS/MS included", "MS_MS_included",
    "Formula", "Ontology", "INCHIKEY", "SMILES", "Comment",
    # Isotopes
    "Isotope tracking parent ID", "Isotope_tracking_parent_ID",
    "Isotope tracking weight number", "Isotope_tracking_weight_number",
    # Spectral quality
    "Dot product", "Dot_product",
    "Reverse dot product", "Reverse_dot_product",
    "Fragment presence %", "Fragment_presence__",
    "Spectrum reference file name", "Spectrum_reference_file_name",
    "MS1 isotopic spectrum", "MS1_isotopic_spectrum",
    "MS/MS spectrum", "MS_MS_spectrum",
    "Flag",
    # notame adds these when merging modes
    "Feature_ID", "Split", "Column", "Mode",
}

_EXT_RE = re.compile(r"\.(mzML|mzXML|raw|cdf|d|abf)$", re.IGNORECASE)

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


class MSDIALLoader(Loader):
    """Loader for MS-DIAL alignment results CSV/TSV exports."""

    FORMAT_NAME:  ClassVar[str] = "msdial"
    FORMAT_LABEL: ClassVar[str] = "MS-DIAL (alignment results)"

    @classmethod
    def _can_read(cls, head_df: pd.DataFrame) -> bool:
        cols = set(head_df.columns)
        has_alignment = "Alignment ID" in cols or "Alignment_ID" in cols
        has_avg_mz    = "Average Mz" in cols or "Average_Mz" in cols
        return has_alignment and has_avg_mz

    def _read(self, path: str, **kwargs) -> ParsedDataset:
        # MS-DIAL exports may be tab-separated; let pandas detect.
        sep = ","
        with open(path, "r", encoding="latin1") as f:
            first = f.readline()
            if first.count("\t") > first.count(","):
                sep = "\t"
        raw = pd.read_csv(path, sep=sep, encoding="latin1",
                          on_bad_lines="skip", engine="python")
        raw = raw.loc[:, ~raw.columns.str.match(r"Unnamed")]

        meta_cols   = [c for c in raw.columns if c in MSDIAL_META_COLUMNS]
        sample_cols = [c for c in raw.columns if c not in MSDIAL_META_COLUMNS]

        if not meta_cols:
            raise ValueError(
                "MSDIALLoader: no recognised MS-DIAL metadata columns."
            )

        features = raw[meta_cols].copy()

        # feature_id
        for candidate in ("Feature_ID", "Alignment_ID", "Alignment ID"):
            if candidate in features.columns:
                features["feature_id"] = features[candidate].astype(str)
                break
        else:
            features["feature_id"] = [f"F{i:05d}" for i in range(len(features))]

        # mz
        for candidate in ("Average_Mz", "Average Mz"):
            if candidate in features.columns:
                features["mz"] = features[candidate]
                break
        else:
            features["mz"] = pd.NA

        # rt
        for candidate in ("Average_Rt_min_", "Average Rt(min)", "Average Rt (min)"):
            if candidate in features.columns:
                features["rt"] = features[candidate]
                break
        else:
            features["rt"] = pd.NA

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
                   "n_sample_cols": len(sample_cols),
                   "separator": sep},
        )
