"""
core/loaders/generic_csv.py

Escape-hatch loader for any tabular feature table that does not match the
specialised loaders (MetaboScape, MZmine, XCMS, MS-DIAL).

The user must supply, at minimum:

* ``feature_id_col``  — column that uniquely identifies each feature
* ``mz_col``          — column with the m/z value
* ``rt_col``          — column with the retention time
* ``sample_cols``     — list of column names containing intensities
                        (everything else is treated as feature metadata)

Optional:

* ``sample_roles``    — dict ``{column_name: role}`` to pre-assign roles
                        (``"sample"``, ``"qc_pool"``, ``"qc_dil"``,
                        ``"blank"``, ``"exclude"``). Columns not listed
                        default to ``"sample"`` and the user can refine
                        via the Sample-Mapping UI.
* ``dilution_levels`` — dict ``{column_name: int}`` for dilution percentages
                        of ``qc_dil`` columns.
* ``sep``             — CSV separator (``","`` default; pass ``"\t"`` for TSV).

This loader never auto-classifies; it only honours what the caller passes.
That avoids silent misclassification when the column-name conventions are
unknown.
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from ..schema import (
    ParsedDataset, SampleRecord,
    ROLE_SAMPLE, VALID_ROLES,
)
from ._base import Loader


class GenericCSVLoader(Loader):
    """Loader for arbitrary CSV/TSV tables with caller-supplied mapping."""

    FORMAT_NAME:  ClassVar[str] = "generic"
    FORMAT_LABEL: ClassVar[str] = "Generic CSV / TSV (manual mapping)"

    @classmethod
    def _can_read(cls, head_df: pd.DataFrame) -> bool:
        # GenericCSVLoader is never selected by sniff() — it must be invoked
        # explicitly via load(path, fmt="generic", ...).
        return False

    def _read(
        self,
        path: str,
        *,
        feature_id_col: str | None = None,
        mz_col: str | None = None,
        rt_col: str | None = None,
        sample_cols: list[str] | None = None,
        sample_roles: dict[str, str] | None = None,
        dilution_levels: dict[str, int] | None = None,
        sep: str = ",",
        **kwargs,
    ) -> ParsedDataset:
        if feature_id_col is None or mz_col is None or rt_col is None:
            raise ValueError(
                "GenericCSVLoader requires feature_id_col, mz_col and rt_col."
            )
        if sample_cols is None:
            raise ValueError(
                "GenericCSVLoader requires the list of sample_cols."
            )

        raw = pd.read_csv(path, sep=sep, encoding="latin1",
                          on_bad_lines="skip", engine="python")
        raw = raw.loc[:, ~raw.columns.str.match(r"Unnamed")]

        missing = [c for c in [feature_id_col, mz_col, rt_col, *sample_cols]
                   if c not in raw.columns]
        if missing:
            raise ValueError(
                f"GenericCSVLoader: columns not found in file: {missing!r}"
            )

        meta_cols = [c for c in raw.columns if c not in sample_cols]
        features  = raw[meta_cols].copy()
        features["feature_id"] = features[feature_id_col].astype(str)
        features["mz"] = features[mz_col]
        features["rt"] = features[rt_col]

        intens = raw[sample_cols].copy()
        intens.index = features["feature_id"].values
        intens.index.name = None

        roles = sample_roles or {}
        dils  = dilution_levels or {}
        for col, role in roles.items():
            if role not in VALID_ROLES:
                raise ValueError(
                    f"Unknown role {role!r} for column {col!r}. "
                    f"Valid: {sorted(VALID_ROLES)}"
                )

        records: list[SampleRecord] = []
        for col in sample_cols:
            role = roles.get(col, ROLE_SAMPLE)
            dil  = dils.get(col)
            records.append(SampleRecord(
                column_name=col,
                sample_id=col,           # user can refine via Sample-Mapping UI
                replicate_num=1,
                role=role,
                dilution_level=dil,
            ))

        return ParsedDataset(
            features=features,
            intensities=intens,
            samples=records,
            source_format=self.FORMAT_NAME,
            extra={"path": path,
                   "feature_id_col": feature_id_col,
                   "mz_col": mz_col, "rt_col": rt_col,
                   "n_sample_cols": len(sample_cols),
                   "separator": sep},
        )
