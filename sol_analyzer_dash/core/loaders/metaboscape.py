"""
core/loaders/metaboscape.py

Loader for Bruker MetaboScape CompleteExperiment exports.

Recognises the canonical Bruker convention:
    * Metadata columns:  Bucket label, RT, m/z, Name, Formula
    * Sample columns:    typically <prefix><sample><suffix>.d, where
                         <sample> identifies the injection (biological
                         sample number, "QC" pool marker, "QC20…QC100"
                         dilution marker, or any of those prefixed with
                         a project tag such as "Plasma").

Role classification is done by a *trailing-* and *leading-pattern*
heuristic so that projects using project-specific decorations around the
``QC`` token — either a trailing tag (e.g. `PlasmaQC20` instead of plain
`QC20`) or a leading tag (e.g. `QCSB20`, the "QC Sangre/Batch" convention
used by some SOL studies) — are recognised automatically:

    * sample_id ends in ``QC<NN>`` (trailing, e.g. ``PlasmaQC20``) or
      starts with ``QC<letters><NN>`` (leading, e.g. ``QCSB20``), with
      NN ∈ {10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100}
                                                            → ``qc_dil`` (level=NN)
    * sample_id is exactly ``QC``, ends in a non-numeric ``QC``
      (e.g. ``PlasmaQC``, ``MtxQC``), or starts with ``QC`` followed only
      by letters (e.g. ``QCSB``, ``QCPool``)                → ``qc_pool``
    * exact match against the caller-supplied ``qc_dil_names`` or
      ``qc_pool_name`` (legacy behaviour)                  → as configured
    * otherwise                                            → ``sample``
"""

from __future__ import annotations

import re
from typing import ClassVar

import pandas as pd

from ..schema import (
    ParsedDataset, SampleRecord,
    ROLE_QC_DIL, ROLE_QC_POOL, ROLE_SAMPLE,
)
from ._base import Loader


META_COLS_DEFAULT     = {"Bucket label", "RT", "m/z", "Name", "Formula"}
QC_DIL_NAMES_DEFAULT  = {"QC20", "QC40", "QC60", "QC80", "QC100"}
QC_NRM_NAME_DEFAULT   = "QC"

# Trailing-pattern recognisers (case-insensitive) — e.g. "PlasmaQC20".
_QC_DIL_TAIL_RE  = re.compile(r"QC(\d{1,3})$", re.IGNORECASE)
_QC_POOL_TAIL_RE = re.compile(r"(?:^|[^A-Za-z0-9])QC$", re.IGNORECASE)

# Leading-pattern recognisers (case-insensitive) — e.g. "QCSB20" / "QCSB"
# (the "QC Sangre/Batch" convention some SOL studies use, where the QC
# token comes *first* instead of being appended to the sample prefix).
_QC_DIL_HEAD_RE  = re.compile(r"^QC[A-Za-z]*(\d{1,3})$", re.IGNORECASE)
_QC_POOL_HEAD_RE = re.compile(r"^QC[A-Za-z]*$", re.IGNORECASE)

# Accepted dilution percentages (anything else is treated as a "sample"
# even if it ends in QC<digits>, to avoid false positives like "myQC1024").
_QC_DIL_LEVELS = {10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100}

_SOL_PREFIX_RE = re.compile(r"^SOL\d+[-_]")
_POS_TAIL_RE   = re.compile(r"_\[POS\].*$")
_NEG_TAIL_RE   = re.compile(r"_\[NEG\].*$")
_DOT_D_TAIL_RE = re.compile(r"\.d$")
_RUN_NUM_POS_RE = re.compile(r"\[POS\](\d+)\.d")
_RUN_NUM_NEG_RE = re.compile(r"\[NEG\](\d+)\.d")


def _extract_sample(col: str) -> str:
    """Strip vendor decoration to obtain the logical sample identifier.

    The Bruker / MetaboScape convention typically appends one or more
    *numeric* tokens to the end of the column name encoding plate /
    position / run / acquisition order. Examples handled by the
    algorithm below:

        ``PlasmaQC_108_1_165_[POS]04.d``      → ``PlasmaQC``
        ``PI_Carmen-21_26_1_16579.d``          → ``PI_Carmen-21``
        ``QC100_5_1_16577.d``                  → ``QC100``
        ``S1_pos_001.d``                       → ``S1_pos``

    Algorithm: remove ``.d``, ``[POS]…`` and ``[NEG]…`` tails, then drop
    *trailing* underscore-separated tokens that are pure non-negative
    integers (plate / position / run metadata). What remains is the
    logical sample identifier. This preserves multi-token sample names
    (e.g. ``PI_Carmen-21``) which the previous ``split("_")[0]`` policy
    collapsed to a single project prefix.
    """
    s = _SOL_PREFIX_RE.sub("", col)
    s = _POS_TAIL_RE.sub("", s)
    s = _NEG_TAIL_RE.sub("", s)
    s = _DOT_D_TAIL_RE.sub("", s)
    parts = s.split("_")
    # Drop trailing pure-numeric tokens (plate/position/run metadata).
    while len(parts) > 1 and parts[-1].isdigit():
        parts.pop()
    return "_".join(parts) if parts else s


def _extract_run(col: str) -> int:
    """Extract an integer replicate / injection index from the column name."""
    m = _RUN_NUM_POS_RE.search(col)
    if m:
        return int(m.group(1))
    m = _RUN_NUM_NEG_RE.search(col)
    if m:
        return int(m.group(1))
    nums = re.findall(r"\d+", col)
    return int(nums[-1]) if nums else 0


def _classify(sid: str,
              qc_dil_names: set,
              qc_pool_name: str) -> tuple[str, int | None]:
    """Return ``(role, dilution_level)`` for the sample identifier ``sid``.

    Precedence:
      1. Exact match against caller-supplied vocabularies.
      2. Trailing- or leading-pattern: ``...QC<NN>`` / ``QC<letters><NN>``
         with NN in the accepted set → qc_dil level NN.
      3. Trailing- or leading-pattern: ``...QC`` / ``QC<letters>``
         (no accepted digits) → qc_pool.
      4. Otherwise → sample.
    """
    # 1. Exact match — legacy behaviour
    if sid in qc_dil_names:
        return ROLE_QC_DIL, int(sid.replace("QC", ""))
    if sid == qc_pool_name:
        return ROLE_QC_POOL, None

    # 2. Trailing/leading pattern: <prefix>QC<NN>  or  QC<letters><NN>
    m = _QC_DIL_TAIL_RE.search(sid) or _QC_DIL_HEAD_RE.match(sid)
    if m:
        try:
            level = int(m.group(1))
        except ValueError:
            level = None
        if level is not None and level in _QC_DIL_LEVELS:
            return ROLE_QC_DIL, level

    # 3. Trailing/leading pattern: <prefix>QC  or  QC<letters>  (no digits,
    #    or digits that did not resolve to an accepted dilution level above)
    if ((sid.lower().endswith("qc") and not _QC_DIL_TAIL_RE.search(sid))
            or (_QC_POOL_HEAD_RE.match(sid) is not None)):
        return ROLE_QC_POOL, None

    # 4. Fallback
    return ROLE_SAMPLE, None


class MetaboScapeLoader(Loader):
    FORMAT_NAME:  ClassVar[str] = "metaboscape"
    FORMAT_LABEL: ClassVar[str] = "Bruker MetaboScape (CompleteExperiment.csv)"

    @classmethod
    def _can_read(cls, head_df: pd.DataFrame) -> bool:
        cols = set(head_df.columns)
        return {"Bucket label", "m/z", "RT"}.issubset(cols)

    def _read(
        self,
        path: str,
        *,
        meta_cols: set | None = None,
        qc_dil_names: set | None = None,
        qc_pool_name: str | None = None,
    ) -> ParsedDataset:
        meta_cols    = meta_cols    or META_COLS_DEFAULT
        qc_dil_names = qc_dil_names or QC_DIL_NAMES_DEFAULT
        qc_pool_name = qc_pool_name or QC_NRM_NAME_DEFAULT

        raw = pd.read_csv(path, encoding="latin1",
                          on_bad_lines="skip", engine="python")
        raw = raw.loc[:, ~raw.columns.str.match(r"Unnamed")]

        feature_cols = [c for c in raw.columns if c in meta_cols]
        if "Bucket label" not in feature_cols:
            raise ValueError(
                "MetaboScapeLoader: required column 'Bucket label' not found."
            )

        features = raw[feature_cols].copy()
        if "Bucket label" in features.columns:
            features["feature_id"] = features["Bucket label"]
        if "m/z" in features.columns:
            features["mz"] = features["m/z"]
        if "RT" in features.columns:
            features["rt"] = features["RT"]
        for must in ("mz", "rt"):
            if must not in features.columns:
                features[must] = pd.NA

        sample_cols = [c for c in raw.columns if c not in meta_cols]
        intens = raw[sample_cols].copy()
        intens.index = features["feature_id"].values
        intens.index.name = None

        records = []
        for col in sample_cols:
            sid = _extract_sample(col)
            run = _extract_run(col)
            role, dil = _classify(sid, qc_dil_names, qc_pool_name)
            records.append(SampleRecord(
                column_name=col, sample_id=sid, replicate_num=run,
                role=role, dilution_level=dil,
            ))

        return ParsedDataset(
            features=features,
            intensities=intens,
            samples=records,
            source_format=self.FORMAT_NAME,
            extra={"path": path,
                   "meta_cols":    sorted(meta_cols),
                   "qc_dil_names": sorted(qc_dil_names),
                   "qc_pool_name": qc_pool_name},
        )
