"""
core/stats_preprocess.py
========================

Preprocessing pipeline for the statistical analysis module.

Three orthogonal stages are exposed:

1. **Missing-value handling** — drop, half-min imputation, or k-NN.
2. **Normalisation** between samples (rows are samples here!):
   * ``none``   — pass-through
   * ``sum``    — divide each sample by its total intensity
   * ``median`` — divide by the sample median
   * ``pqn``    — **Probabilistic Quotient Normalization** (Dieterich 2006)
3. **Transform & scaling** per feature:
   * ``log10`` or ``log2`` or ``none``
   * ``pareto`` (default), ``auto``, ``range``, or ``none``

The public entry point is :func:`preprocess`, which chains all stages and
returns a tidy result dict.

Input convention
----------------
A **wide-format** numeric DataFrame with:

* **rows   = features** (metabolites / lipids / proteins), indexed by the
  feature ID (``Bucket label`` in Aletheia).
* **columns = samples**  (e.g. ``S1, S2, …``  or the renamed ``pBM62, pBM71…``).

Internally we transpose once so that per-sample normalisation (PQN, median,
sum) operates row-wise on samples, and feature-wise transform/scaling
operates column-wise, which matches the usual metabolomics convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd


# =============================================================================
# Missing values
# =============================================================================

def handle_missing(df: pd.DataFrame, strategy: str = "halfmin",
                    min_present_frac: float = 0.5) -> pd.DataFrame:
    """Handle missing values.

    Parameters
    ----------
    df : DataFrame
        Wide format (rows = features, columns = samples).
    strategy : {"halfmin", "drop", "keep"}
        * ``halfmin`` — impute missing with half the feature's minimum
          positive value (standard in metabolomics).
        * ``drop``    — drop features present in fewer than ``min_present_frac``
          samples.
        * ``keep``    — leave NaNs untouched (downstream tests must handle them).
    min_present_frac : float
        Fraction of samples a feature must have non-missing to survive
        ``drop``. Default 0.5 — i.e. keep features seen in at least half
        the samples.
    """
    x = df.replace({0: np.nan}).astype(float).copy()

    if strategy == "drop":
        present = x.notna().mean(axis=1)
        x = x.loc[present >= min_present_frac]
        return x

    if strategy == "halfmin":
        # half of the minimum positive value per feature
        mins = x.where(x > 0).min(axis=1)
        for feat, m in mins.items():
            if np.isfinite(m):
                x.loc[feat] = x.loc[feat].fillna(m / 2.0)
            else:
                x.loc[feat] = x.loc[feat].fillna(0.0)
        return x

    if strategy == "keep":
        return x

    raise ValueError(f"Estrategia desconocida: {strategy!r}")


# =============================================================================
# Sample-wise normalisation
# =============================================================================

def normalize_samples(df: pd.DataFrame,
                       method: Literal["none", "sum", "median", "pqn"] = "pqn",
                       reference: str | None = None) -> pd.DataFrame:
    """Normalise between samples.

    ``df`` is wide format — rows = features, columns = samples. We operate
    per *column* (i.e. per sample).

    * ``sum``    — divide each sample by its sum then × mean-sum across samples
    * ``median`` — divide by the sample's median then × mean-median
    * ``pqn``    — Dieterich 2006: build a reference spectrum (median of
      all samples), compute quotients per sample / reference, take the
      median quotient (a dilution factor), and divide the sample by it.
    """
    if method == "none":
        return df.copy()

    x = df.astype(float).copy()

    if method == "sum":
        sums = x.sum(axis=0, skipna=True)
        mean_s = sums.mean()
        return x.divide(sums, axis=1) * mean_s

    if method == "median":
        meds = x.median(axis=0, skipna=True)
        mean_m = meds.mean()
        return x.divide(meds, axis=1) * mean_m

    if method == "pqn":
        # Reference spectrum: column-wise operation →  need per-feature ref
        if reference is not None and reference in x.columns:
            ref = x[reference]
        else:
            ref = x.median(axis=1, skipna=True)
        ref = ref.replace({0: np.nan})
        # quotients: (feature, sample) — each column divided by ref
        q = x.divide(ref, axis=0)
        factors = q.median(axis=0, skipna=True)  # per-sample dilution factor
        factors = factors.replace({0: np.nan}).fillna(1.0)
        return x.divide(factors, axis=1)

    raise ValueError(f"Método de normalización desconocido: {method!r}")


# =============================================================================
# Feature-wise transform + scaling
# =============================================================================

def transform(df: pd.DataFrame,
              method: Literal["none", "log10", "log2", "sqrt", "cube"] = "log10",
              pseudocount_frac: float = 0.5) -> pd.DataFrame:
    """Per-feature transform — applied before scaling."""
    x = df.astype(float).copy()

    if method == "none":
        return x
    if method == "sqrt":
        return np.sqrt(x.clip(lower=0))
    if method == "cube":
        return np.cbrt(x)

    # Logs: add pseudocount to avoid log(0)
    # pseudocount = pseudocount_frac × (minimum positive value across the matrix)
    pos = x.where(x > 0).stack()
    pc = (pos.min() * pseudocount_frac) if len(pos) else 1e-9
    base = {"log10": 10.0, "log2": 2.0}[method]
    return np.log(x.clip(lower=0) + pc) / np.log(base)


def scale(df: pd.DataFrame,
          method: Literal["none", "auto", "pareto", "range"] = "pareto"
          ) -> pd.DataFrame:
    """Per-feature scaling. Operates along rows (features), so each feature
    becomes comparable in magnitude.
    """
    x = df.astype(float).copy()
    mu = x.mean(axis=1)

    if method == "none":
        return x
    if method == "auto":
        sd = x.std(axis=1, ddof=1).replace({0: np.nan})
        return x.subtract(mu, axis=0).divide(sd, axis=0).fillna(0)
    if method == "pareto":
        sd = x.std(axis=1, ddof=1).replace({0: np.nan})
        return x.subtract(mu, axis=0).divide(np.sqrt(sd), axis=0).fillna(0)
    if method == "range":
        rng = (x.max(axis=1) - x.min(axis=1)).replace({0: np.nan})
        return x.subtract(mu, axis=0).divide(rng, axis=0).fillna(0)

    raise ValueError(f"Método de escalado desconocido: {method!r}")


# =============================================================================
# Single entry point
# =============================================================================

@dataclass
class PreprocessConfig:
    missing:       str = "halfmin"          # halfmin / drop / keep
    min_present:   float = 0.5              # only used when missing == 'drop'
    normalize:     str = "pqn"              # none / sum / median / pqn
    reference:     str | None = None        # only for PQN with a fixed sample
    transform:     str = "log10"            # none / log10 / log2 / sqrt / cube
    pseudocount:   float = 0.5              # fraction of min-pos for log pseudocount
    scale:         str = "pareto"           # none / auto / pareto / range

    def describe(self) -> str:
        """Human-readable summary used in the report."""
        parts = []
        parts.append(f"missing={self.missing}")
        if self.missing == "drop":
            parts.append(f"min_present={self.min_present:.0%}")
        parts.append(f"norm={self.normalize}")
        if self.normalize == "pqn" and self.reference:
            parts.append(f"ref={self.reference}")
        parts.append(f"transform={self.transform}")
        parts.append(f"scale={self.scale}")
        return " · ".join(parts)


def preprocess(df: pd.DataFrame,
                cfg: PreprocessConfig | None = None) -> dict:
    """Run the full preprocessing pipeline.

    Returns a dict with:

    * ``data``    — final DataFrame (features × samples), fully processed
    * ``stages``  — dict of intermediate stages keyed by stage name
    * ``config``  — the :class:`PreprocessConfig` used
    * ``summary`` — textual summary for the report
    """
    cfg = cfg or PreprocessConfig()

    s0 = df.copy()
    s1 = handle_missing(s0, cfg.missing, cfg.min_present)
    s2 = normalize_samples(s1, cfg.normalize, cfg.reference)
    s3 = transform(s2, cfg.transform, cfg.pseudocount)
    s4 = scale(s3, cfg.scale)

    return {
        "data":    s4,
        "stages":  {
            "raw":        s0,
            "missing":    s1,
            "normalized": s2,
            "transformed":s3,
            "scaled":     s4,
        },
        "config":  cfg,
        "summary": cfg.describe(),
    }
