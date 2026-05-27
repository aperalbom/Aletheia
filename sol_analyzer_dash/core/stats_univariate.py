"""
core/stats_univariate.py
========================

Univariate statistical tests for the stats module.

All functions operate on the preprocessed **wide-format** matrix
(rows = features, columns = samples), paired with a **groups Series**
(index = sample column names, values = group label).

Public API
----------

* :func:`two_group_test`    — Welch's t-test or Mann-Whitney U (+ effect size)
* :func:`multi_group_test`  — One-way ANOVA or Kruskal-Wallis (+ omega²)
* :func:`fold_change`       — log2 FC computed on *raw* (un-log-transformed) data
* :func:`bh_fdr`            — Benjamini-Hochberg adjustment
* :func:`volcano_data`      — ready-to-plot DataFrame with FC + p + sig flags
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


# =============================================================================
# Effect sizes
# =============================================================================

def cohens_d(x: np.ndarray, y: np.ndarray) -> float:
    """Cohen's d with pooled SD."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x = x[~np.isnan(x)]; y = y[~np.isnan(y)]
    if len(x) < 2 or len(y) < 2:
        return np.nan
    sd = np.sqrt(((len(x) - 1) * np.var(x, ddof=1) +
                  (len(y) - 1) * np.var(y, ddof=1)) /
                 (len(x) + len(y) - 2))
    if sd == 0:
        return np.nan
    return (np.mean(x) - np.mean(y)) / sd


def hedges_g(x: np.ndarray, y: np.ndarray) -> float:
    """Hedges' g — bias-corrected Cohen's d."""
    d = cohens_d(x, y)
    n = len(x) + len(y)
    if n < 4:
        return np.nan
    j = 1.0 - 3.0 / (4 * n - 9)
    return d * j


# =============================================================================
# Benjamini-Hochberg
# =============================================================================

def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg step-up FDR.

    Accepts NaNs — returns NaN in those positions.
    """
    p = np.asarray(pvals, dtype=float)
    mask = ~np.isnan(p)
    q = np.full_like(p, np.nan)
    if mask.sum() == 0:
        return q

    pm = p[mask]
    order = np.argsort(pm)
    ranked = pm[order]
    n = len(pm)
    q_ranked = ranked * n / (np.arange(1, n + 1))
    # Monotonic step-up
    q_ranked = np.minimum.accumulate(q_ranked[::-1])[::-1]
    q_ranked = np.clip(q_ranked, 0, 1)

    out = np.empty(n)
    out[order] = q_ranked
    q[mask] = out
    return q


# =============================================================================
# Two-group comparison
# =============================================================================

@dataclass
class TwoGroupResult:
    test: str          # "welch" | "mann_whitney" | "paired_t" | "wilcoxon"
    group_a: str
    group_b: str
    table: pd.DataFrame  # columns: feature, mean_a, mean_b, log2FC, stat, p, q, cohens_d, hedges_g, n_a, n_b


def two_group_test(data: pd.DataFrame,
                    groups: pd.Series,
                    group_a: str,
                    group_b: str,
                    test: str = "welch",
                    raw_for_fc: pd.DataFrame | None = None,
                    ) -> TwoGroupResult:
    """Run a two-group test for every feature.

    Parameters
    ----------
    data : DataFrame
        **Pre-processed** matrix (features × samples) — tests run on these values.
    groups : Series
        index = sample column names, values = group label
    group_a, group_b : str
        Two group labels to compare.
    test : {"welch", "mann_whitney", "paired_t", "wilcoxon"}
    raw_for_fc : DataFrame, optional
        Untransformed abundances used to compute fold-change. If None, FC is
        computed on ``data`` (which may already be log-transformed — in that
        case the "log2FC" column is actually a simple mean difference, and
        is labelled as such in the output).

    Returns
    -------
    :class:`TwoGroupResult` — ``.table`` holds one row per feature.
    """
    cols_a = [c for c in groups.index if c in data.columns and groups[c] == group_a]
    cols_b = [c for c in groups.index if c in data.columns and groups[c] == group_b]
    if len(cols_a) < 2 or len(cols_b) < 2:
        raise ValueError(
            f"Se necesitan ≥2 muestras por grupo (group_a={len(cols_a)}, group_b={len(cols_b)})"
        )

    if test in ("paired_t", "wilcoxon"):
        if len(cols_a) != len(cols_b):
            raise ValueError(
                f"Los tests pareados requieren el mismo nº de muestras por grupo "
                f"(A={len(cols_a)}, B={len(cols_b)})"
            )

    rows = []
    fc_src = raw_for_fc if raw_for_fc is not None else data

    for feat in data.index:
        x = data.loc[feat, cols_a].astype(float).values
        y = data.loc[feat, cols_b].astype(float).values
        x_clean = x[~np.isnan(x)]
        y_clean = y[~np.isnan(y)]

        if len(x_clean) < 2 or len(y_clean) < 2:
            rows.append({
                "feature": feat, "mean_a": np.nanmean(x), "mean_b": np.nanmean(y),
                "log2FC": np.nan, "stat": np.nan, "p": np.nan,
                "cohens_d": np.nan, "hedges_g": np.nan,
                "n_a": len(x_clean), "n_b": len(y_clean),
            })
            continue

        try:
            if test == "welch":
                st, p = stats.ttest_ind(x_clean, y_clean, equal_var=False, nan_policy="omit")
            elif test == "mann_whitney":
                st, p = stats.mannwhitneyu(x_clean, y_clean, alternative="two-sided")
            elif test == "paired_t":
                st, p = stats.ttest_rel(x, y, nan_policy="omit")
            elif test == "wilcoxon":
                # scipy raises if all zeros/equal, catch below
                st, p = stats.wilcoxon(x, y, zero_method="wilcox")
            else:
                raise ValueError(f"Test desconocido: {test!r}")
        except Exception:
            st, p = np.nan, np.nan

        # Fold change on raw abundances when provided
        a_raw = fc_src.loc[feat, cols_a].astype(float).values
        b_raw = fc_src.loc[feat, cols_b].astype(float).values
        a_mean = np.nanmean(a_raw); b_mean = np.nanmean(b_raw)
        if raw_for_fc is not None:
            # Real fold change
            log2fc = (np.log2(a_mean) - np.log2(b_mean)) \
                if (a_mean > 0 and b_mean > 0) else np.nan
        else:
            # data may already be log-transformed — report mean difference
            # (which is a log-fold-change if transform was log2 / log10)
            log2fc = a_mean - b_mean

        rows.append({
            "feature":  feat,
            "mean_a":   np.nanmean(x), "mean_b": np.nanmean(y),
            "log2FC":   log2fc,
            "stat":     st, "p": p,
            "cohens_d": cohens_d(x_clean, y_clean),
            "hedges_g": hedges_g(x_clean, y_clean),
            "n_a":      len(x_clean), "n_b": len(y_clean),
        })

    df = pd.DataFrame(rows)
    df["q"] = bh_fdr(df["p"].values)
    df = df.sort_values("p", na_position="last").reset_index(drop=True)
    return TwoGroupResult(test=test, group_a=group_a, group_b=group_b, table=df)


# =============================================================================
# Multi-group comparison
# =============================================================================

@dataclass
class MultiGroupResult:
    test: str          # "anova" | "kruskal"
    groups: list
    table: pd.DataFrame  # columns: feature, stat, p, q, eta2, posthoc (dict)


def multi_group_test(data: pd.DataFrame,
                      groups: pd.Series,
                      test: str = "anova",
                      ) -> MultiGroupResult:
    """One-way ANOVA or Kruskal-Wallis across all groups."""
    group_labels = list(pd.unique(groups.dropna()))
    if len(group_labels) < 2:
        raise ValueError("Se necesitan ≥ 2 grupos.")

    rows = []
    for feat in data.index:
        vals = [data.loc[feat, groups[groups == g].index.intersection(data.columns)]
                  .astype(float).dropna().values
                for g in group_labels]
        if any(len(v) < 2 for v in vals):
            rows.append({"feature": feat, "stat": np.nan, "p": np.nan, "eta2": np.nan})
            continue
        try:
            if test == "anova":
                st, p = stats.f_oneway(*vals)
                # omega-squared approximation
                grand = np.concatenate(vals)
                ss_between = sum(len(v) * (np.mean(v) - np.mean(grand))**2 for v in vals)
                ss_total = np.sum((grand - np.mean(grand))**2)
                eta2 = ss_between / ss_total if ss_total > 0 else np.nan
            elif test == "kruskal":
                st, p = stats.kruskal(*vals)
                # H/(N-1) is the eta²-equivalent
                n_total = sum(len(v) for v in vals)
                eta2 = (st - len(vals) + 1) / (n_total - len(vals)) \
                       if n_total > len(vals) else np.nan
            else:
                raise ValueError(f"Test desconocido: {test!r}")
        except Exception:
            st, p, eta2 = np.nan, np.nan, np.nan

        rows.append({"feature": feat, "stat": st, "p": p, "eta2": eta2})

    df = pd.DataFrame(rows)
    df["q"] = bh_fdr(df["p"].values)
    df = df.sort_values("p", na_position="last").reset_index(drop=True)
    return MultiGroupResult(test=test, groups=group_labels, table=df)


# =============================================================================
# Fold change (standalone helper, on raw data)
# =============================================================================

def fold_change(raw: pd.DataFrame, groups: pd.Series,
                 group_a: str, group_b: str) -> pd.DataFrame:
    """Compute per-feature mean_a / mean_b and log2 fold-change on raw data."""
    cols_a = [c for c in groups.index if c in raw.columns and groups[c] == group_a]
    cols_b = [c for c in groups.index if c in raw.columns and groups[c] == group_b]
    mean_a = raw[cols_a].mean(axis=1)
    mean_b = raw[cols_b].mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        log2fc = np.log2(mean_a) - np.log2(mean_b)
    return pd.DataFrame({
        "feature": raw.index,
        "mean_a":  mean_a.values,
        "mean_b":  mean_b.values,
        "log2FC":  log2fc.values,
    })


# =============================================================================
# Volcano plot data
# =============================================================================

def volcano_data(res: TwoGroupResult,
                 fc_threshold: float = 1.0,
                 q_threshold: float = 0.05) -> pd.DataFrame:
    """Return a DataFrame ready for a volcano plot.

    Adds ``-log10(p)``, ``-log10(q)`` and a ``sig`` column:

    * ``up``   — log2FC ≥ fc_threshold AND q ≤ q_threshold
    * ``down`` — log2FC ≤ -fc_threshold AND q ≤ q_threshold
    * ``ns``   — otherwise
    """
    df = res.table.copy()
    with np.errstate(divide="ignore"):
        df["neg_log10_p"] = -np.log10(df["p"].values)
        df["neg_log10_q"] = -np.log10(df["q"].values)

    sig = []
    for fc, q in zip(df["log2FC"].values, df["q"].values):
        if np.isnan(q) or np.isnan(fc):
            sig.append("ns")
        elif q <= q_threshold and fc >= fc_threshold:
            sig.append("up")
        elif q <= q_threshold and fc <= -fc_threshold:
            sig.append("down")
        else:
            sig.append("ns")
    df["sig"] = sig
    return df
