"""
core/schema.py

Internal, format-agnostic representation of a parsed LC–MS feature table.

Every loader (MetaboScape, MZmine, XCMS, MS-DIAL, generic CSV) ingests its
specific export format and emits a :class:`ParsedDataset`. The downstream
QC pipeline (``run_m1``, ``run_qcr``, ``run_m2``) consumes the legacy dict
shape via :meth:`ParsedDataset.to_legacy_dict`, so the existing code keeps
working unchanged while we add multi-format support incrementally.

Design goals
------------
* Round-trip safe: ``MetaboScapeLoader().load(path).to_legacy_dict()`` must
  return *exactly* the same dict that the legacy ``parse_file`` produces.
* Source-aware: each :class:`SampleRecord` carries enough metadata to
  reconstruct any vendor-specific naming convention.
* JSON-serialisable: the dataset can be persisted as a sidecar so the user
  can re-run the analysis later with the exact same sample mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd


# =============================================================================
# SampleRecord
# =============================================================================

# Allowed values for SampleRecord.role.
ROLE_SAMPLE  = "sample"     # biological sample
ROLE_QC_POOL = "qc_pool"    # pooled QC (replicated across the run)
ROLE_QC_DIL  = "qc_dil"     # QC dilution series (linearity assessment)
ROLE_BLANK   = "blank"      # solvent / process blank
ROLE_EXCLUDE = "exclude"    # column to ignore (e.g. failed acquisition)

VALID_ROLES = frozenset([
    ROLE_SAMPLE, ROLE_QC_POOL, ROLE_QC_DIL, ROLE_BLANK, ROLE_EXCLUDE,
])


@dataclass(frozen=True)
class SampleRecord:
    """One LC–MS injection column.

    Parameters
    ----------
    column_name
        Verbatim column name from the input file. Used as the join key
        against the intensity matrix.
    sample_id
        Logical sample identifier shared by all replicates of the same
        sample (e.g. ``"S1"``, ``"QC"``, ``"PlasmaQC60"``).
    replicate_num
        1-indexed replicate number within ``sample_id``. Replicates with
        the same ``sample_id`` are aggregated together in the M1 / M2
        modules.
    role
        Functional role of the column. Must be one of :data:`VALID_ROLES`.
    dilution_level
        Numeric dilution percentage (e.g. 20, 40, 60, 80, 100). Only set
        when ``role == ROLE_QC_DIL``; ``None`` otherwise.
    injection_order
        Global injection order if known (1-indexed). ``None`` when the
        source format does not report it.
    """

    column_name: str
    sample_id: str
    replicate_num: int
    role: str
    dilution_level: int | None = None
    injection_order: int | None = None

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(
                f"Unknown role {self.role!r}; must be one of {sorted(VALID_ROLES)}"
            )
        if self.role == ROLE_QC_DIL and self.dilution_level is None:
            raise ValueError(
                f"SampleRecord with role=qc_dil requires dilution_level "
                f"(column={self.column_name!r})"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# ParsedDataset
# =============================================================================

@dataclass
class ParsedDataset:
    """Format-agnostic snapshot of a parsed LC–MS feature table.

    Parameters
    ----------
    features
        One row per feature. Mandatory columns: ``feature_id``, ``mz``,
        ``rt``. Recommended: ``name``, ``formula``. Source-specific
        columns are preserved verbatim.
    intensities
        Wide-form intensity matrix: rows aligned with ``features.feature_id``,
        columns are the verbatim column names of every injection. Missing
        values are NaN (the loader is responsible for converting zeros if
        the source format encodes missingness as 0).
    samples
        One :class:`SampleRecord` per intensity column, in the same order
        as ``intensities.columns``.
    source_format
        Short identifier of the source format: ``"metaboscape"``,
        ``"mzmine"``, ``"xcms"``, ``"msdial"`` or ``"generic"``.
    extra
        Free-form metadata bag (e.g. raw file path, polarity, batch
        marker present in the source file).
    """

    features:      pd.DataFrame
    intensities:   pd.DataFrame
    samples:       list[SampleRecord] = field(default_factory=list)
    source_format: str = "generic"
    extra:         dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ checks
    def validate(self) -> None:
        """Lightweight sanity checks. Raises :class:`ValueError` on mismatch."""
        if "feature_id" not in self.features.columns:
            raise ValueError("features must contain a 'feature_id' column")
        if set(self.features["feature_id"]) != set(self.intensities.index):
            raise ValueError(
                "features['feature_id'] and intensities.index do not match"
            )
        sample_cols = [s.column_name for s in self.samples]
        if list(self.intensities.columns) != sample_cols:
            raise ValueError(
                "samples must be in the same order as intensities.columns"
            )

    # ------------------------------------------------------------ legacy view
    def to_legacy_dict(self) -> dict[str, Any]:
        """Reproduce the dict shape returned by the historical ``parse_file``.

        Keys returned:

        * ``raw``             — wide-form DataFrame with feature meta + samples
        * ``col_df``          — (col, sample, run_num) for every injection
        * ``qc_dil_df``       — subset for QC dilution columns + ``dil`` int
        * ``qc_norm_df``      — subset for QC pool columns
        * ``samp_df``         — subset for biological samples + ``sample_n``
        * ``real_samples``    — sorted list of integer sample numbers
        * ``reps_per_level``  — max replicates per dilution level (>=1)
        * ``n_metabolites``   — number of features
        * ``n_samples``       — number of distinct biological samples
        * ``reps_per_sample`` — average replicates per biological sample (>=1)

        The downstream ``run_m1`` / ``run_qcr`` / ``run_m2`` functions consume
        this dict unchanged.
        """
        # ---- raw -----------------------------------------------------------
        # Reconstruct the original read_csv shape: feature metadata first
        # (using the source's *original* column names so that downstream code
        # such as run_m1 can still do ``raw["Bucket label"]``), then the
        # intensity columns appended in their original order.
        #
        # The canonical aliases (`feature_id`, `mz`, `rt`) the schema requires
        # are dropped from `raw` when the source already provides their
        # originals (``Bucket label``, ``m/z``, ``RT``), to avoid duplicates.
        feat = self.features.copy().reset_index(drop=True)
        canonical_aliases_to_drop = []
        for canonical, original in (("feature_id", "Bucket label"),
                                      ("mz", "m/z"),
                                      ("rt", "RT")):
            if canonical in feat.columns and original in feat.columns:
                canonical_aliases_to_drop.append(canonical)
        if canonical_aliases_to_drop:
            feat = feat.drop(columns=canonical_aliases_to_drop)
        raw = feat
        # ---- legacy aliases for downstream compatibility -------------------
        # ``run_m1`` / ``run_qcr`` consume ``raw["Bucket label"]`` and
        # ``raw["Name"]`` regardless of source format. When the source does
        # not provide them (MZmine, XCMS, MS-DIAL, generic), we synthesise
        # aliases so the legacy pipeline keeps working unchanged.
        if "Bucket label" not in raw.columns:
            if "feature_id" in raw.columns:
                raw["Bucket label"] = raw["feature_id"]
            else:
                raw["Bucket label"] = [f"F{i:05d}" for i in range(len(raw))]
        if "Name" not in raw.columns:
            for alt in ("Metabolite_name", "Metabolite name",
                         "row identity (main ID)"):
                if alt in raw.columns:
                    raw["Name"] = raw[alt]
                    break
            else:
                raw["Name"] = ""
        for col in self.intensities.columns:
            raw[col] = self.intensities[col].values

        # ---- col_df --------------------------------------------------------
        rows = []
        for s in self.samples:
            rows.append({
                "col":     s.column_name,
                "sample":  s.sample_id,
                "run_num": s.replicate_num,
            })
        col_df = pd.DataFrame(rows, columns=["col", "sample", "run_num"])

        # ---- subsets -------------------------------------------------------
        qc_dil_rows = []
        for s in self.samples:
            if s.role == ROLE_QC_DIL:
                qc_dil_rows.append({
                    "col":     s.column_name,
                    "sample":  s.sample_id,
                    "run_num": s.replicate_num,
                    "dil":     int(s.dilution_level) if s.dilution_level is not None else 0,
                })
        qc_dil_df = (
            pd.DataFrame(qc_dil_rows, columns=["col", "sample", "run_num", "dil"])
            .sort_values(["dil", "run_num"])
            .reset_index(drop=True)
        )

        qc_norm_df = (
            col_df[col_df["sample"].isin(
                [s.sample_id for s in self.samples if s.role == ROLE_QC_POOL]
            )]
            .copy()
            .sort_values("run_num")
            .reset_index(drop=True)
        )

        samp_df = col_df[
            col_df["col"].isin(
                [s.column_name for s in self.samples if s.role == ROLE_SAMPLE]
            )
        ].copy()
        # Derive integer ``sample_n`` from each ``sample_id``. The pipeline
        # (run_m2, run_alternative_analysis) groups biological replicates by
        # ``sample_n``, so the mapping must be integer, collision-free across
        # distinct ``sample_id`` strings, and reproducible.
        #
        # Resolution order:
        #   1. ``sample_id`` itself is a pure integer (legacy "1","2",…).
        #   2. ``sample_id`` ends in digits and they are unique across
        #      all biological sample_ids (e.g. ``"PI_Carmen-21"`` → 21).
        #   3. Otherwise, sequential integers 1..N over sorted sample_ids.
        if len(samp_df):
            unique_sids = sorted(samp_df["sample"].unique().tolist())
            if all(sid.isdigit() for sid in unique_sids):
                sid_to_n = {sid: int(sid) for sid in unique_sids}
            else:
                import re as _re
                _trail = _re.compile(r"(\d+)$")
                tentative: dict[str, int] = {}
                for sid in unique_sids:
                    m = _trail.search(sid)
                    if m:
                        tentative[sid] = int(m.group(1))
                if (len(tentative) == len(unique_sids)
                        and len(set(tentative.values())) == len(tentative)):
                    sid_to_n = tentative
                else:
                    sid_to_n = {sid: i + 1 for i, sid in enumerate(unique_sids)}
            samp_df["sample_n"] = samp_df["sample"].map(sid_to_n).astype(int)
            samp_df = samp_df.sort_values(["sample_n", "run_num"]).reset_index(drop=True)
        else:
            samp_df["sample_n"] = pd.Series([], dtype="int64")

        # ---- counters ------------------------------------------------------
        real_samples   = sorted(samp_df["sample_n"].unique().tolist()) if len(samp_df) else []
        reps_per_level = int(qc_dil_df.groupby("dil").size().max()) if len(qc_dil_df) else 1
        n_samp = len(real_samples)
        n_rep  = (len(samp_df) // n_samp) if n_samp else 1

        return dict(
            raw=raw, col_df=col_df,
            qc_dil_df=qc_dil_df, qc_norm_df=qc_norm_df,
            samp_df=samp_df, real_samples=real_samples,
            reps_per_level=reps_per_level,
            n_metabolites=len(self.features),
            n_samples=n_samp, reps_per_sample=n_rep,
        )

    # --------------------------------------------------------------- helpers
    def n_features(self) -> int:
        return len(self.features)

    def n_samples_total(self) -> int:
        return len(self.samples)

    def by_role(self, role: str) -> list[SampleRecord]:
        return [s for s in self.samples if s.role == role]

    def to_mapping_json(self) -> dict[str, Any]:
        """Serialisable form of the sample mapping, for sidecar JSON storage."""
        return {
            "source_format": self.source_format,
            "samples": [s.to_dict() for s in self.samples],
            "extra":   self.extra,
        }
