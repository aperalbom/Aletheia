"""
core/stats_biomarker.py
=======================

Biomarker screening helpers for the stats module.

* :func:`roc_auc_single`       — ROC curve + AUC for a single feature
* :func:`bootstrap_auc_ci`     — bootstrap 95 % CI for AUC
* :func:`biomarker_table`      — AUC + CI + p for every feature, sorted by |AUC-0.5|
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

try:
    from sklearn.metrics import roc_curve, roc_auc_score
except ImportError:  # pragma: no cover
    roc_curve = None
    roc_auc_score = None


# =============================================================================
# Single-feature ROC
# =============================================================================

@dataclass
class ROCResult:
    feature: str
    fpr: np.ndarray
    tpr: np.ndarray
    thresholds: np.ndarray
    auc: float
    positive: str
    negative: str


def _binary_labels(groups: pd.Series,
                     group_a: str, group_b: str,
                     samples: list[str]) -> np.ndarray:
    labels = np.empty(len(samples), dtype=int)
    for i, s in enumerate(samples):
        g = groups[s]
        if g == group_a:
            labels[i] = 1
        elif g == group_b:
            labels[i] = 0
        else:
            labels[i] = -1
    return labels


def roc_auc_single(data: pd.DataFrame,
                    groups: pd.Series,
                    feature: str,
                    group_a: str,
                    group_b: str) -> ROCResult:
    """Compute ROC curve + AUC for a single feature.

    ``group_a`` is treated as the positive class.
    """
    if roc_curve is None:
        raise RuntimeError("scikit-learn no está instalado.")

    samples = [s for s in data.columns if s in groups.index
                and groups[s] in (group_a, group_b)]
    y = _binary_labels(groups, group_a, group_b, samples)
    sl = data.loc[feature, samples]
    if hasattr(sl, "ndim") and sl.ndim == 2:
        sl = sl.iloc[0]
    x = np.asarray(sl, dtype=float).ravel()
    mask = (y >= 0) & np.isfinite(x)
    y, x = y[mask], x[mask]

    if len(y) < 4 or len(np.unique(y)) < 2:
        return ROCResult(feature, np.array([]), np.array([]), np.array([]),
                          np.nan, group_a, group_b)

    # Use max-directional AUC: if AUC < 0.5 flip the score direction
    fpr, tpr, thr = roc_curve(y, x)
    auc = roc_auc_score(y, x)
    if auc < 0.5:
        fpr, tpr, thr = roc_curve(y, -x)
        auc = 1 - auc

    return ROCResult(feature, fpr, tpr, thr, auc, group_a, group_b)


# =============================================================================
# Bootstrap CI
# =============================================================================

def bootstrap_auc_ci(data: pd.DataFrame,
                      groups: pd.Series,
                      feature: str,
                      group_a: str,
                      group_b: str,
                      n_boot: int = 1000,
                      alpha: float = 0.05,
                      random_state: int | None = None) -> dict:
    """Bootstrap a (1 - alpha) CI for the AUC of a single feature."""
    if roc_auc_score is None:
        raise RuntimeError("scikit-learn no está instalado.")

    rng = np.random.default_rng(random_state)
    samples = [s for s in data.columns if s in groups.index
                and groups[s] in (group_a, group_b)]
    y = _binary_labels(groups, group_a, group_b, samples)
    # Defensive: ``data.loc[feature, samples]`` returns a 2-D DataFrame
    # if the feature label is duplicated in the index. Take the first row.
    sl = data.loc[feature, samples]
    if hasattr(sl, "ndim") and sl.ndim == 2:
        sl = sl.iloc[0]
    x = np.asarray(sl, dtype=float).ravel()
    mask = (y >= 0) & np.isfinite(x)
    y, x = y[mask], x[mask]

    if len(y) < 4 or len(np.unique(y)) < 2:
        return {"auc": np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan}

    try:
        obs = roc_auc_score(y, x)
    except ValueError:
        obs = np.nan

    boot = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        yy, xx = y[idx], x[idx]
        if len(np.unique(yy)) < 2:
            boot[b] = np.nan; continue
        try:
            boot[b] = roc_auc_score(yy, xx)
        except ValueError:
            boot[b] = np.nan

    lo = np.nanpercentile(boot, 100 * alpha / 2)
    hi = np.nanpercentile(boot, 100 * (1 - alpha / 2))

    # DeLong-style quick p vs AUC = 0.5 using Mann-Whitney U
    try:
        u, p_mw = stats.mannwhitneyu(x[y == 1], x[y == 0], alternative="two-sided")
    except ValueError:
        p_mw = np.nan

    return {"auc": obs, "lo": lo, "hi": hi, "p": p_mw}


# =============================================================================
# All-features table
# =============================================================================

def _fast_auc_p(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """AUC + Mann-Whitney p-value derived from ranks — no sklearn loops.

    Equivalent to ``roc_auc_score(y, x)`` for binary y, computed via
    the U statistic. Roughly 100× faster than calling sklearn per feature.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=int).ravel()
    if x.shape != y.shape:
        return np.nan, np.nan
    mask = np.isfinite(x) & (y >= 0)
    x, y = x[mask], y[mask]
    if len(y) < 4 or len(np.unique(y)) < 2:
        return np.nan, np.nan
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return np.nan, np.nan
    ranks = pd.Series(x).rank(method="average").values
    sum_pos = ranks[y == 1].sum()
    U = sum_pos - n_pos * (n_pos + 1) / 2.0
    auc = U / (n_pos * n_neg)
    # Two-sided MWU p via normal approximation (with tie correction)
    try:
        _, p = stats.mannwhitneyu(x[y == 1], x[y == 0], alternative="two-sided")
    except ValueError:
        p = np.nan
    return float(auc), float(p)


def biomarker_table(data: pd.DataFrame,
                     groups: pd.Series,
                     group_a: str,
                     group_b: str,
                     n_boot: int = 500,
                     random_state: int | None = None,
                     top_n: int | None = None,
                     ci_top_k: int | None = None) -> pd.DataFrame:
    """Compute AUC + CI + p for every feature, sorted by discriminative power.

    Two-pass strategy for speed:

    1. **Fast pass** — for *every* feature compute AUC + Mann-Whitney p
       analytically from ranks. No bootstrap, no sklearn loops.
    2. **Bootstrap CI** — only on the top ``ci_top_k`` features by
       discriminative power (default = ``max(top_n × 3, 50)``). The
       remaining features keep their AUC + p but ``CI_lo`` / ``CI_hi``
       are ``NaN``. This makes the table useful in seconds even on
       proteomics-scale data (5–10k features).

    Set ``ci_top_k = len(data)`` if you want bootstrap CIs everywhere.
    """
    samples = [s for s in data.columns if s in groups.index
                and groups[s] in (group_a, group_b)]
    y = _binary_labels(groups, group_a, group_b, samples)

    # Slice once, by position, to avoid the duplicate-label trap that
    # would make ``data.loc[feat, samples]`` return a 2-D DataFrame.
    sub = data.reindex(columns=samples)
    sub_vals = sub.astype(float).values   # shape (n_features, n_samples)
    feats = list(data.index)

    # ── Fast pass: AUC + p for every feature ────────────────────────────
    rows = []
    for i, feat in enumerate(feats):
        x = sub_vals[i, :]
        auc, p = _fast_auc_p(x, y)
        rows.append({"feature": feat, "AUC": auc, "CI_lo": np.nan,
                       "CI_hi": np.nan, "p_mwu": p})
    df = pd.DataFrame(rows)
    df["score"] = (df["AUC"] - 0.5).abs()
    df = df.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)

    # ── Bootstrap pass: only top-K candidates ───────────────────────────
    if ci_top_k is None:
        if top_n is not None:
            ci_top_k = max(int(top_n) * 3, 50)
        else:
            ci_top_k = min(50, len(df))
    ci_top_k = min(int(ci_top_k), len(df))

    if ci_top_k > 0 and n_boot and n_boot > 0:
        for i in range(ci_top_k):
            feat = df.at[i, "feature"]
            r = bootstrap_auc_ci(data, groups, feat, group_a, group_b,
                                  n_boot=n_boot, random_state=random_state)
            df.at[i, "CI_lo"] = r["lo"]
            df.at[i, "CI_hi"] = r["hi"]

    df = df.drop(columns="score")
    if top_n is not None:
        df = df.head(top_n).reset_index(drop=True)
    return df
