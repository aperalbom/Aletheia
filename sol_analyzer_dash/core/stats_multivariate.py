"""
core/stats_multivariate.py
==========================

Multivariate analysis for the stats module.

* :func:`run_pca`      — PCA with Hotelling's T² 95 % ellipses for scores plots
* :func:`run_plsda`    — PLS-DA with optional permutation test + VIP scores
* :func:`permutation_test_plsda` — separate helper when you want to reuse scores

Input convention (matches :mod:`stats_preprocess`):

* ``data`` is **wide format**: rows = features, columns = samples
* ``groups`` is a ``Series`` indexed by sample column name.

The PLS-DA implementation is a thin wrapper around
``sklearn.cross_decomposition.PLSRegression`` with Y one-hot encoded; VIPs are
computed analytically from the loadings and x-scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

try:
    from sklearn.decomposition import PCA
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.preprocessing import LabelBinarizer
    from sklearn.metrics import accuracy_score
except ImportError:  # pragma: no cover
    PCA = None
    PLSRegression = None
    LabelBinarizer = None
    accuracy_score = None


# =============================================================================
# PCA
# =============================================================================

@dataclass
class PCAResult:
    scores:   pd.DataFrame    # index = sample, columns = PC1, PC2, ...
    loadings: pd.DataFrame    # index = feature, columns = PC1, PC2, ...
    explained_variance_ratio: np.ndarray
    n_components: int
    ellipses: dict[str, np.ndarray]  # group -> (N, 2) xy pts of 95 % T² ellipse


def _hotelling_ellipse_2d(xy: np.ndarray, alpha: float = 0.95, n_pts: int = 120
                            ) -> np.ndarray:
    """Return (N, 2) xy points of the Hotelling's T² α-confidence ellipse.

    ``xy`` — (n, 2) matrix of sample scores on two PCs.
    """
    from scipy.stats import f as f_dist

    n = len(xy)
    if n < 3:
        return np.empty((0, 2))
    mean = xy.mean(axis=0)
    cov = np.cov(xy.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # T² = (n-1)*2/(n-2) · F(2, n-2; α)
    crit = f_dist.ppf(alpha, 2, n - 2) * 2 * (n - 1) / (n - 2)
    radii = np.sqrt(eigvals * crit)

    t = np.linspace(0, 2 * np.pi, n_pts)
    circle = np.stack([np.cos(t), np.sin(t)], axis=1)
    ellipse = (circle * radii) @ eigvecs.T + mean
    return ellipse


def run_pca(data: pd.DataFrame,
             groups: pd.Series | None = None,
             n_components: int = 5,
             alpha_ellipse: float = 0.95) -> PCAResult:
    """Principal Component Analysis on a features × samples matrix.

    We transpose to samples × features internally since sklearn's PCA
    centres per feature and returns one score per sample.
    """
    if PCA is None:
        raise RuntimeError("scikit-learn no está instalado.")

    X = data.T.values                    # samples × features
    samples = list(data.columns)
    features = list(data.index)

    n_components = min(n_components, X.shape[0], X.shape[1])
    pca = PCA(n_components=n_components)
    scores = pca.fit_transform(X)

    pc_cols = [f"PC{i+1}" for i in range(n_components)]
    scores_df = pd.DataFrame(scores, index=samples, columns=pc_cols)
    loadings_df = pd.DataFrame(pca.components_.T, index=features, columns=pc_cols)

    # 95 % ellipses on PC1 vs PC2 per group
    ellipses: dict[str, np.ndarray] = {}
    if groups is not None and n_components >= 2:
        for g in pd.unique(groups.dropna()):
            cols = [s for s in samples if s in groups.index and groups[s] == g]
            if len(cols) >= 3:
                xy = scores_df.loc[cols, ["PC1", "PC2"]].values
                ellipses[g] = _hotelling_ellipse_2d(xy, alpha=alpha_ellipse)

    return PCAResult(
        scores=scores_df,
        loadings=loadings_df,
        explained_variance_ratio=pca.explained_variance_ratio_,
        n_components=n_components,
        ellipses=ellipses,
    )


# =============================================================================
# PLS-DA
# =============================================================================

@dataclass
class PLSDAResult:
    scores: pd.DataFrame          # index = sample, columns = Comp1, Comp2, ...
    loadings: pd.DataFrame        # index = feature, columns = Comp1, ...
    vip: pd.Series                # index = feature → VIP
    weights: pd.DataFrame
    y_encoded: pd.DataFrame       # sample × classes one-hot
    classes_: list
    accuracy_cv: float            # leave-one-out CV accuracy
    n_components: int
    permutation: dict | None      # output of permutation_test_plsda() if run


def _vip_scores(pls: "PLSRegression") -> np.ndarray:
    """Variable Importance in Projection from a fitted PLSRegression.

    VIP_j = sqrt( p * sum_k (w_jk² · SS_k) / sum_k SS_k )

    where SS_k is the sum of squares explained by component k and p is the
    number of features. See Chong & Jun 2005.
    """
    t = pls.x_scores_           # n × k
    w = pls.x_weights_          # p × k
    q = pls.y_loadings_         # m × k

    # SS per component: ||t_k||² · ||q_k||²
    ss = np.sum(t ** 2, axis=0) * np.sum(q ** 2, axis=0)
    total = np.sum(ss)
    if total <= 0:
        return np.zeros(w.shape[0])

    # normalise weight columns
    w_norm = w / (np.linalg.norm(w, axis=0) + 1e-12)
    weighted = (w_norm ** 2) * ss
    vip = np.sqrt(weighted.sum(axis=1) * w.shape[0] / total)
    return vip


def run_plsda(data: pd.DataFrame,
               groups: pd.Series,
               n_components: int = 2,
               loo_cv: bool = True,
               n_permutations: int = 0,
               random_state: int | None = None) -> PLSDAResult:
    """Partial Least Squares Discriminant Analysis.

    Parameters
    ----------
    data : DataFrame (features × samples)
        Preprocessed matrix (typically log-Pareto).
    groups : Series
        index = sample column names, values = class label.
    n_components : int, default 2
    loo_cv : bool, default True
        Compute leave-one-out cross-validation accuracy.
    n_permutations : int, default 0
        If > 0, run a permutation test on class labels and compute empirical p.
    """
    if PLSRegression is None:
        raise RuntimeError("scikit-learn no está instalado.")

    # Keep only samples with group membership
    samples = [s for s in data.columns if s in groups.index and pd.notna(groups[s])]
    if len(samples) < 4:
        raise ValueError("Necesito ≥ 4 muestras con grupo asignado para PLS-DA.")

    X = data[samples].T.values
    y = groups.loc[samples].values
    lb = LabelBinarizer()
    Y = lb.fit_transform(y)
    classes = list(lb.classes_)
    if Y.shape[1] == 1:
        # Binary case: LabelBinarizer returns 1 col with 1 for the positive
        # class = classes_[1]. Rebuild a proper 2-col one-hot so col i == classes_[i].
        Y2 = np.zeros((len(y), 2), dtype=float)
        Y2[Y[:, 0] == 0, 0] = 1   # classes_[0]
        Y2[Y[:, 0] == 1, 1] = 1   # classes_[1]
        Y = Y2

    n_components = min(n_components, X.shape[0] - 1, X.shape[1])
    pls = PLSRegression(n_components=n_components, scale=False)
    pls.fit(X, Y)

    comp_cols = [f"Comp{i+1}" for i in range(n_components)]
    scores_df = pd.DataFrame(pls.x_scores_, index=samples, columns=comp_cols)
    loadings_df = pd.DataFrame(pls.x_loadings_, index=data.index, columns=comp_cols)
    weights_df = pd.DataFrame(pls.x_weights_, index=data.index, columns=comp_cols)
    vip = pd.Series(_vip_scores(pls), index=data.index, name="VIP")

    # Leave-one-out CV
    accuracy = np.nan
    if loo_cv:
        correct = 0
        for i in range(len(samples)):
            mask = np.ones(len(samples), dtype=bool); mask[i] = False
            p_cv = PLSRegression(n_components=n_components, scale=False)
            try:
                p_cv.fit(X[mask], Y[mask])
                pred = p_cv.predict(X[i:i+1]).ravel()
                # pred has one entry per class (columns of Y, aligned with classes_)
                pred_cls = classes[int(np.argmax(pred))]
                if pred_cls == y[i]:
                    correct += 1
            except Exception:
                pass
        accuracy = correct / len(samples)

    # Permutation test on accuracy
    perm = None
    if n_permutations and n_permutations > 0:
        perm = permutation_test_plsda(
            data, groups, n_components=n_components,
            n_permutations=n_permutations, random_state=random_state,
            observed_accuracy=accuracy if loo_cv else None,
        )

    return PLSDAResult(
        scores=scores_df,
        loadings=loadings_df,
        weights=weights_df,
        vip=vip.sort_values(ascending=False),
        y_encoded=pd.DataFrame(Y, index=samples, columns=classes),
        classes_=classes,
        accuracy_cv=accuracy,
        n_components=n_components,
        permutation=perm,
    )


def permutation_test_plsda(data: pd.DataFrame,
                            groups: pd.Series,
                            n_components: int = 2,
                            n_permutations: int = 1000,
                            random_state: int | None = None,
                            observed_accuracy: float | None = None,
                            ) -> dict[str, Any]:
    """Permutation test for PLS-DA generalisability.

    Shuffles class labels ``n_permutations`` times, refits PLS-DA, evaluates
    leave-one-out accuracy, and returns the empirical p-value.
    """
    rng = np.random.default_rng(random_state)
    samples = [s for s in data.columns if s in groups.index and pd.notna(groups[s])]
    X = data[samples].T.values
    y_true = groups.loc[samples].values
    lb = LabelBinarizer()
    lb.fit(y_true)
    classes = list(lb.classes_)

    def _encode(y_labels):
        Y = lb.transform(y_labels)
        if Y.shape[1] == 1:
            Y2 = np.zeros((len(y_labels), 2), dtype=float)
            Y2[Y[:, 0] == 0, 0] = 1
            Y2[Y[:, 0] == 1, 1] = 1
            return Y2
        return Y.astype(float)

    def _accuracy(y_labels):
        Y = _encode(y_labels)
        correct = 0
        for i in range(len(y_labels)):
            mask = np.ones(len(y_labels), dtype=bool); mask[i] = False
            pls = PLSRegression(n_components=min(n_components, mask.sum() - 1), scale=False)
            try:
                pls.fit(X[mask], Y[mask])
                pred = pls.predict(X[i:i+1]).ravel()
                pred_cls = classes[int(np.argmax(pred))]
                if pred_cls == y_labels[i]:
                    correct += 1
            except Exception:
                pass
        return correct / len(y_labels)

    if observed_accuracy is None:
        observed_accuracy = _accuracy(y_true)

    perm_accs = np.zeros(n_permutations)
    for p in range(n_permutations):
        y_perm = rng.permutation(y_true)
        perm_accs[p] = _accuracy(y_perm)

    # Empirical p: fraction of permutations with acc ≥ observed
    pval = (np.sum(perm_accs >= observed_accuracy) + 1) / (n_permutations + 1)

    return {
        "observed_accuracy": observed_accuracy,
        "perm_accuracies":   perm_accs,
        "p_value":           pval,
        "n_permutations":    n_permutations,
    }
