"""
core/analysis.py
Toda la lógica de análisis: parseo, linealidad, QC réplicas, CV/ICC.
Independiente de la UI — reutilizable desde scripts de línea de comandos.
"""

import re
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

META_COLS = {"Bucket label", "RT", "m/z", "Name", "Formula"}
QC_DIL_NAMES = {"QC20", "QC40", "QC60", "QC80", "QC100"}
QC_NRM_NAME  = "QC"

# =============================================================================
# PARSEO
# =============================================================================

def extract_sample(col: str) -> str:
    s = re.sub(r"^SOL\d+[-_]", "", col)
    s = re.sub(r"_\[POS\].*$", "", s)
    s = re.sub(r"\.d$", "", s)
    return s.split("_")[0]

def extract_run(col: str) -> int:
    m = re.search(r"\[POS\](\d+)\.d", col)
    if m:
        return int(m.group(1))
    nums = re.findall(r"\d+", col)
    return int(nums[-1]) if nums else 0

def parse_file(filepath_or_buffer) -> dict:
    """Lee el CSV y devuelve un dict con raw, col_df, qc_dil_df, qc_norm_df, samp_df,
    real_samples, reps_per_level, n_metabolites."""
    raw = pd.read_csv(filepath_or_buffer, encoding="latin1",
                      on_bad_lines="skip", engine="python")
    raw = raw.loc[:, ~raw.columns.str.match(r"Unnamed")]

    sample_cols = [c for c in raw.columns if c not in META_COLS]
    col_df = pd.DataFrame({
        "col":     sample_cols,
        "sample":  [extract_sample(c) for c in sample_cols],
        "run_num": [extract_run(c)    for c in sample_cols],
    })

    qc_dil_df = col_df[col_df["sample"].isin(QC_DIL_NAMES)].copy()
    qc_dil_df["dil"] = qc_dil_df["sample"].str.replace("QC", "").astype(int)
    qc_dil_df = qc_dil_df.sort_values(["dil", "run_num"]).reset_index(drop=True)

    qc_norm_df = col_df[col_df["sample"] == QC_NRM_NAME].sort_values("run_num").reset_index(drop=True)

    samp_df = col_df[~col_df["sample"].isin(QC_DIL_NAMES | {QC_NRM_NAME})].copy()
    samp_df["sample_n"] = pd.to_numeric(samp_df["sample"], errors="coerce")
    samp_df = samp_df.dropna(subset=["sample_n"])
    samp_df["sample_n"] = samp_df["sample_n"].astype(int)
    samp_df = samp_df.sort_values(["sample_n", "run_num"]).reset_index(drop=True)

    real_samples   = sorted(samp_df["sample_n"].unique())
    reps_per_level = int(qc_dil_df.groupby("dil").size().max()) if len(qc_dil_df) else 1
    n_samp = len(real_samples)
    n_rep  = len(samp_df) // n_samp if n_samp else 1

    return dict(raw=raw, col_df=col_df, qc_dil_df=qc_dil_df, qc_norm_df=qc_norm_df,
                samp_df=samp_df, real_samples=real_samples,
                reps_per_level=reps_per_level, n_metabolites=len(raw),
                n_samples=n_samp, reps_per_sample=n_rep)

# =============================================================================
# MÓDULO 1 — LINEALIDAD
# =============================================================================

def _get_val(series):
    v = pd.to_numeric(series, errors="coerce")
    return v.where(v > 0, other=np.nan)

def _aggregate_level(vals, strategy="mean"):
    v = [x for x in vals if pd.notna(x) and x > 0]
    if not v:
        return np.nan
    if strategy == "first":  return v[0]
    if strategy == "second": return v[1] if len(v) >= 2 else v[0]
    if strategy == "third":  return v[2] if len(v) >= 3 else (v[1] if len(v) >= 2 else v[0])
    return np.mean(v)

def _build_pairs(row_vals, qc_dil_df, strategy="mean", drop_lowest=False):
    pairs = []
    for dil, grp in qc_dil_df.groupby("dil"):
        vals = [row_vals.get(c, np.nan) for c in grp["col"]]
        y = _aggregate_level(vals, strategy)
        if pd.notna(y):
            pairs.append((dil, y))
    pairs.sort()
    if drop_lowest and len(pairs) > 1:
        pairs = pairs[1:]
    return pairs

def _lin_reg(pairs):
    if len(pairs) < 2:
        return None, None
    xs = np.array([p[0] for p in pairs], dtype=float)
    ys = np.array([p[1] for p in pairs], dtype=float)
    n  = len(xs)
    sx, sy = xs.sum(), ys.sum()
    sxy = (xs * ys).sum(); sx2 = (xs * xs).sum()
    den = n * sx2 - sx * sx
    if den == 0: return 0.0, None
    b = (n * sxy - sx * sy) / den
    a = (sy - b * sx) / n
    if n < 3: return b, None
    ym = sy / n
    ss = ((ys - ym) ** 2).sum()
    if ss == 0: return b, None
    return b, float(1 - ((ys - (a + b * xs)) ** 2).sum() / ss)

def _evaluate_lin(pairs, threshold, allow2pt, ion_sup=False):
    if not pairs:
        return dict(ok=False, r2=None, reason="no_data")
    slope, r2 = _lin_reg(pairs)
    n = len(pairs)
    if slope is None:
        return dict(ok=False, r2=None, reason="no_data")
    if slope <= 0:
        if ion_sup and n >= 3 and r2 is not None and r2 >= threshold:
            return dict(ok=True, r2=r2, reason="ion_suppression")
        if ion_sup and n == 2:
            return dict(ok=True, r2=1.0, reason="ion_suppression")
        return dict(ok=False, r2=None, reason="negative_slope")
    if n == 1: return dict(ok=False, r2=None, reason="only_1_point")
    if n == 2:
        return (dict(ok=True, r2=1.0, reason="2pt_pos_slope") if allow2pt
                else dict(ok=False, r2=None, reason="only_2_points"))
    if r2 is None: return dict(ok=False, r2=None, reason="r2_na")
    if r2 >= threshold: return dict(ok=True, r2=r2, reason="r2_ok")
    return dict(ok=False, r2=r2, reason="r2_low")

def _get_best_pairs(row_vals, qc_dil_df, reps_per_level, use_drop):
    strategies = (["mean"] if reps_per_level == 1
                  else ["first","second","mean"] if reps_per_level == 2
                  else ["first","second","third","mean"])
    drops = [False, True] if use_drop else [False]

    best_r2_pos, best_pairs_pos, best_strat_pos = -np.inf, None, "mean"
    best_r2_neg, best_pairs_neg, best_strat_neg = -np.inf, None, "mean"

    for strat in strategies:
        for drop in drops:
            ps = _build_pairs(row_vals, qc_dil_df, strat, drop)
            if len(ps) < 2: continue
            slope, r2 = _lin_reg(ps)
            if slope is None: continue
            r2val = r2 if r2 is not None else (1.0 if len(ps) == 2 else -1.0)
            key   = f"{strat}_drop_lowest" if drop else strat
            if slope > 0:
                if r2val > best_r2_pos: best_r2_pos, best_pairs_pos, best_strat_pos = r2val, ps, key
            else:
                if r2val > best_r2_neg: best_r2_neg, best_pairs_neg, best_strat_neg = r2val, ps, key

    if best_pairs_pos is not None: return best_pairs_pos, best_strat_pos
    if best_pairs_neg is not None: return best_pairs_neg, best_strat_neg
    return [], "mean"

def run_m1(parsed: dict, r2_threshold=0.6, allow2pt=True, use_drop=True, ion_sup=False) -> dict:
    raw          = parsed["raw"]
    qc_dil_df    = parsed["qc_dil_df"]
    reps_per_lvl = parsed["reps_per_level"]
    N            = len(raw)

    # Construir matrices por estrategia de una vez
    dil_levels = sorted(qc_dil_df["dil"].unique())
    n_dil      = len(dil_levels)

    # strategies a probar
    if reps_per_lvl == 1:
        strategies = ["mean"]
    elif reps_per_lvl == 2:
        strategies = ["first","second","mean"]
    else:
        strategies = ["first","second","third","mean"]

    drops = [False, True] if use_drop else [False]

    # Preconstruir matrices (N, n_dil) para cada estrategia
    strat_matrices = {}
    for strat in strategies:
        mat = np.full((N, n_dil), np.nan)
        for j, dil in enumerate(dil_levels):
            cols = qc_dil_df[qc_dil_df["dil"]==dil]["col"].tolist()
            m    = raw[cols].apply(pd.to_numeric, errors="coerce").replace(0, np.nan).values
            if strat == "first":
                mat[:, j] = m[:, 0]
            elif strat == "second":
                mat[:, j] = m[:, 1] if m.shape[1] >= 2 else m[:, 0]
            elif strat == "third":
                mat[:, j] = m[:, 2] if m.shape[1] >= 3 else (m[:, 1] if m.shape[1] >= 2 else m[:, 0])
            else:  # mean
                with np.errstate(invalid="ignore"):
                    mat[:, j] = np.nanmean(m, axis=1)
        strat_matrices[strat] = mat

    xs = np.array(dil_levels, dtype=float)

    def lin_reg_batch(mat):
        """Regresión lineal vectorizada para N metabolitos a la vez.
        mat: (N, n_dil), puede tener NaN.
        Devuelve slopes (N,), r2s (N,)."""
        valid = ~np.isnan(mat)
        n_v   = valid.sum(axis=1).astype(float)

        # Sustitur NaN por 0 para sumas (con máscara)
        mat0 = np.where(valid, mat, 0.0)
        xs_exp = np.tile(xs, (N,1))
        xs_m   = np.where(valid, xs_exp, 0.0)

        sx  = xs_m.sum(axis=1)
        sy  = mat0.sum(axis=1)
        sxy = (xs_m * mat0).sum(axis=1)
        sx2 = (xs_m * xs_m).sum(axis=1)

        den  = n_v * sx2 - sx * sx
        safe = den != 0
        b    = np.where(safe, (n_v*sxy - sx*sy) / np.where(safe,den,1), 0.0)
        a    = np.where(n_v>0, (sy - b*sx) / np.where(n_v>0,n_v,1), np.nan)

        # R² solo con ≥3 puntos válidos
        r2 = np.full(N, np.nan)
        mask3 = n_v >= 3
        if mask3.any():
            ym  = np.where(mask3, sy/np.where(n_v>0,n_v,1), np.nan)
            ss  = np.where(valid, (mat - ym[:,None])**2, 0.0).sum(axis=1)
            res = np.where(valid, (mat - (a[:,None] + b[:,None]*xs_exp))**2, 0.0).sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                r2 = np.where(mask3 & (ss>0), 1 - res/ss, np.nan)

        return b, r2, n_v.astype(int)

    # Para cada combinación strat×drop: calcular slope, r2, n_valid
    # Guardar la mejor (pendiente positiva, mayor R²)
    best_r2_pos  = np.full(N, -np.inf)
    best_r2_neg  = np.full(N, -np.inf)
    best_slope   = np.zeros(N)
    best_r2      = np.full(N, np.nan)   # R² de la mejor pendiente positiva
    best_r2_neg_val = np.full(N, np.nan)  # R² de la mejor pendiente negativa
    best_n       = np.zeros(N, dtype=int)
    best_strat   = np.full(N, "", dtype=object)

    for strat in strategies:
        mat_full = strat_matrices[strat]
        for drop in drops:
            mat = mat_full[:, 1:] if drop else mat_full
            xs_use = xs[1:] if drop else xs
            n_dil_use = len(xs_use)

            if n_dil_use < 2:
                continue

            # Recalcular con xs_use
            valid = ~np.isnan(mat)
            n_v   = valid.sum(axis=1).astype(float)
            mat0  = np.where(valid, mat, 0.0)
            xs_exp = np.tile(xs_use, (N,1))
            xs_m   = np.where(valid, xs_exp, 0.0)

            sx  = xs_m.sum(axis=1); sy = mat0.sum(axis=1)
            sxy = (xs_m*mat0).sum(axis=1); sx2 = (xs_m*xs_m).sum(axis=1)
            den = n_v*sx2 - sx*sx
            safe = den != 0
            b   = np.where(safe, (n_v*sxy - sx*sy)/np.where(safe,den,1), 0.0)
            a   = np.where(n_v>0, (sy - b*sx)/np.where(n_v>0,n_v,1), np.nan)

            r2 = np.full(N, np.nan)
            mask3 = n_v >= 3
            if mask3.any():
                ym  = np.where(mask3, sy/np.where(n_v>0,n_v,1), np.nan)
                ss  = np.where(valid,(mat-ym[:,None])**2,0.0).sum(axis=1)
                res = np.where(valid,(mat-(a[:,None]+b[:,None]*xs_exp))**2,0.0).sum(axis=1)
                with np.errstate(invalid="ignore",divide="ignore"):
                    r2 = np.where(mask3&(ss>0), 1-res/ss, np.nan)

            n_valid = n_v.astype(int)
            r2val   = np.where(~np.isnan(r2), r2, np.where(n_valid==2, 1.0, -1.0))
            skey    = f"{strat}_drop_lowest" if drop else strat

            pos_mask = b > 0
            neg_mask = ~pos_mask

            upd_pos = pos_mask & (r2val > best_r2_pos)
            best_r2_pos  = np.where(upd_pos, r2val,   best_r2_pos)
            best_r2      = np.where(upd_pos, r2,      best_r2)
            best_slope   = np.where(upd_pos, b,       best_slope)
            best_n       = np.where(upd_pos, n_valid, best_n)
            best_strat   = np.where(upd_pos, skey,    best_strat)

            upd_neg = neg_mask & (r2val > best_r2_neg) & (best_r2_pos == -np.inf)
            best_r2_neg     = np.where(upd_neg, r2val,          best_r2_neg)
            best_r2_neg_val = np.where(upd_neg, np.where(~np.isnan(r2), r2, np.nan),
                                       best_r2_neg_val)

    # Evaluar resultado
    has_pos = best_r2_pos > -np.inf
    slope   = best_slope
    r2v     = best_r2
    nv      = best_n

    # Determinar ok y reason vectorizado
    ok     = np.zeros(N, dtype=bool)
    reason = np.full(N, "no_data", dtype=object)

    # Sin datos válidos
    no_data_mask = ~has_pos & (best_r2_neg == -np.inf)
    reason = np.where(no_data_mask, "no_data", reason)

    # Pendiente negativa
    neg_mask = ~has_pos & ~no_data_mask
    if ion_sup:
        # Usar el R² real de la mejor pendiente negativa
        r2_neg = best_r2_neg_val
        ion_mask = neg_mask & ~np.isnan(r2_neg) & (r2_neg >= r2_threshold)
        ok     = np.where(ion_mask, True, ok)
        reason = np.where(ion_mask, "ion_suppression", reason)
        # Para ion suppression, usar su R² real en el dataframe
        r2v    = np.where(ion_mask, r2_neg, r2v)
        neg_only = neg_mask & ~ion_mask
    else:
        neg_only = neg_mask
    reason = np.where(neg_only, "negative_slope", reason)

    # Con pendiente positiva
    pos_mask = has_pos
    only1 = pos_mask & (nv <= 1)
    reason = np.where(only1, "only_1_point", reason)

    two_pts = pos_mask & (nv == 2) & ~only1
    if allow2pt:
        ok     = np.where(two_pts, True, ok)
        reason = np.where(two_pts, "2pt_pos_slope", reason)
        r2v    = np.where(two_pts, 1.0, r2v)
    else:
        reason = np.where(two_pts, "only_2_points", reason)

    three_plus = pos_mask & (nv >= 3)
    r2_na_mask = three_plus & np.isnan(r2v)
    reason = np.where(r2_na_mask, "r2_na", reason)

    r2_ok_mask = three_plus & ~np.isnan(r2v) & (r2v >= r2_threshold)
    ok     = np.where(r2_ok_mask, True, ok)
    reason = np.where(r2_ok_mask, "r2_ok", reason)

    r2_low_mask = three_plus & ~np.isnan(r2v) & (r2v < r2_threshold)
    reason = np.where(r2_low_mask, "r2_low", reason)

    lin_df = pd.DataFrame({
        "label":    raw["Bucket label"].values,
        "Name":     raw["Name"].values if "Name" in raw.columns else "",
        "ok":       ok,
        "r2":       np.where(ok | r2_low_mask, r2v, np.nan),
        "strategy": np.where(ok, best_strat, None),
        "n_valid":  nv,
        "reason":   reason,
        "r2_full":  r2v,
        "r2_drop":  np.nan,  # simplificado — drop ya considerado en best
    })

    good_lin = lin_df[lin_df["ok"]].copy()
    bad_lin  = lin_df[~lin_df["ok"] & ~lin_df["reason"].isin(["no_data","only_1_point"])].copy()
    nodat    = lin_df[lin_df["reason"].isin(["no_data","only_1_point"])].copy()

    return dict(lin_df=lin_df, good=good_lin, bad=bad_lin, nodat=nodat,
                n=N, r2_threshold=r2_threshold)

# =============================================================================
# MÓDULO QCR — DIAGNÓSTICO DE RÉPLICAS
# =============================================================================

def run_qcr(parsed: dict, inj_threshold=0.70) -> dict:
    """Diagnóstico de inyección (Nivel 1) + outliers por metabolito (Nivel 2).
    Devuelve qcr_df y agg_df (tabla agregada para MetaboAnalyst)."""
    raw          = parsed["raw"]
    samp_df      = parsed["samp_df"]
    real_samples = parsed["real_samples"]
    N            = len(raw)

    qcr_rows = []
    for s in real_samples:
        cols = samp_df[samp_df["sample_n"] == s]["col"].tolist()
        rep_stats = []
        for ri, col in enumerate(cols, 1):
            vals = pd.to_numeric(raw[col], errors="coerce")
            vals = vals[(vals > 0) & vals.notna()]
            rep_stats.append({"Sample": s, "Replica": ri, "Column": col,
                               "Suma_int": float(vals.sum()),
                               "Mediana_int": float(vals.median()) if len(vals) else 0.0})

        sums = sorted(r["Suma_int"]    for r in rep_stats)
        meds = sorted(r["Mediana_int"] for r in rep_stats)
        med_sum = sums[len(sums)//2]
        med_med = meds[len(meds)//2]

        for r in rep_stats:
            fs = med_sum > 0 and r["Suma_int"]    < inj_threshold * med_sum
            fm = med_med > 0 and r["Mediana_int"] < inj_threshold * med_med
            r["Falla_suma"] = fs; r["Falla_med"] = fm
            r["Estado"]     = "fail" if (fs and fm) else "suspect" if (fs or fm) else "ok"
            r["Recomendacion"] = ("Excluir replica"     if r["Estado"] == "fail" else
                                  "Revisar manualmente" if r["Estado"] == "suspect" else
                                  "Sin incidencias")
            qcr_rows.append(r)

    qcr_df = pd.DataFrame(qcr_rows)

    # Nivel 2: outliers por metabolito en réplicas válidas — vectorizado
    outlier_counts = {}
    for s in real_samples:
        valid = qcr_df[(qcr_df["Sample"]==s) & (qcr_df["Estado"]!="fail")]
        vcols = valid["Column"].tolist()
        if len(vcols) < 2:
            continue
        # Matriz (N_metabolitos × n_replicas_validas)
        mat_v = raw[vcols].apply(pd.to_numeric, errors="coerce").replace(0, np.nan).values
        with np.errstate(invalid="ignore", divide="ignore"):
            mn  = np.nanmean(mat_v, axis=1, keepdims=True)
            sd  = np.nanstd(mat_v,  axis=1, keepdims=True, ddof=0)
            z   = np.where(sd > 0, np.abs(mat_v - mn) / sd, 0)
            out = z > 2   # (N, n_valid_reps) bool
        # Contar outliers por réplica
        for ri_idx, rep_num in enumerate(valid["Replica"].tolist()):
            cnt = int(np.nansum(out[:, ri_idx]))
            outlier_counts[(s, rep_num)] = cnt

    # Guard against the all-QC / no-biological-samples case. When samp_df was
    # empty (e.g. the experiment contains only QC injections, as in the Sigma
    # synthetic plasma case study) qcr_rows is also empty and pd.DataFrame([])
    # has zero rows AND zero columns. We rebuild a well-formed empty frame so
    # downstream code (and the legacy dict consumers) sees the expected
    # schema.
    _QCR_COLS = ["Sample", "Replica", "Column", "Suma_int", "Mediana_int",
                 "Falla_suma", "Falla_med", "Estado", "Recomendacion",
                 "N_outliers"]
    if len(qcr_df) == 0:
        qcr_df = pd.DataFrame(columns=_QCR_COLS)
    else:
        qcr_df["N_outliers"] = qcr_df.apply(
            lambda r: outlier_counts.get((r["Sample"], r["Replica"]), 0), axis=1)
        qcr_df.loc[(qcr_df["Estado"] == "ok") & (qcr_df["N_outliers"] > N * 0.05),
                   "Recomendacion"] = "Outliers elevados"

    # Tabla agregada — vectorizada
    meta_cols = [c for c in ["Bucket label","RT","m/z","Name","Formula"] if c in raw.columns]
    agg_df    = raw[meta_cols].copy()
    for s in real_samples:
        valid_cols = qcr_df[(qcr_df["Sample"]==s) & (qcr_df["Estado"]!="fail")]["Column"].tolist()
        if not valid_cols:
            agg_df[f"S{s}"] = np.nan
            continue
        mat_v = raw[valid_cols].apply(pd.to_numeric, errors="coerce").replace(0, np.nan).values
        with np.errstate(invalid="ignore", divide="ignore"):
            mn_v  = np.nanmean(mat_v, axis=1, keepdims=True)
            sd_v  = np.nanstd(mat_v,  axis=1, keepdims=True, ddof=0)
            z_v   = np.where(sd_v > 0, np.abs(mat_v - mn_v) / sd_v, 0)
            clean = np.where(z_v > 2, np.nan, mat_v)
        agg_df[f"S{s}"] = np.nanmean(clean, axis=1)

    return dict(qcr_df=qcr_df, agg_df=agg_df,
                n_fail=int((qcr_df["Estado"]=="fail").sum()),
                n_suspect=int((qcr_df["Estado"]=="suspect").sum()),
                n_ok=int((qcr_df["Estado"]=="ok").sum()),
                n_outlier_total=int(qcr_df["N_outliers"].sum()))

# =============================================================================
# MÓDULO 2 — CV / ICC
# =============================================================================

def _safe_cv(vals):
    v = pd.to_numeric(pd.Series(vals), errors="coerce")
    v = v[(v > 0) & v.notna()]
    if len(v) < 2: return np.nan
    cv = v.std() / v.mean() * 100
    return float(cv) if np.isfinite(cv) else np.nan

def run_m2(parsed: dict, cv_threshold=20, qc_cv_thresh=15, detect_alert=70) -> dict:
    raw          = parsed["raw"]
    samp_df      = parsed["samp_df"]
    qc_norm_df   = parsed["qc_norm_df"]
    real_samples = parsed["real_samples"]
    N            = len(raw)
    n_rep        = parsed["reps_per_sample"]

    # CV por muestra — vectorizado
    cv_by_samp = {}
    det_any1   = {}
    det_allr   = {}
    for s in real_samples:
        cols    = samp_df[samp_df["sample_n"]==s]["col"].tolist()
        mat_num = raw[cols].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
        # CV fila a fila vectorizado
        mn = mat_num.mean(axis=1)
        sd = mat_num.std(axis=1, ddof=1)
        cv = (sd / mn * 100).where(mn > 0)
        cv_by_samp[s] = cv.values
        det_any1[s]   = (mat_num.notna().sum(axis=1) >= 1).values
        det_allr[s]   = (mat_num.notna().sum(axis=1) == len(cols)).values

    cv_df = pd.DataFrame({f"CV_S{s}": cv_by_samp[s] for s in real_samples})
    cv_df.insert(0, "label", raw["Bucket label"].values)
    cv_df.insert(1, "Name",
                 raw["Name"].values if "Name" in raw.columns else "")
    cv_cols            = [f"CV_S{s}" for s in real_samples]
    cv_df["CV_median"] = cv_df[cv_cols].median(axis=1)
    cv_df["CV_max"]    = cv_df[cv_cols].max(axis=1)
    cv_df["CV_ok"]     = cv_df["CV_median"] <= cv_threshold

    # Detección
    det_df = pd.DataFrame({
        "Sample": real_samples,
        "n_any1": [det_any1[s].sum() for s in real_samples],
        "n_allr": [det_allr[s].sum() for s in real_samples],
    })
    det_df["pct_all"] = 100 * det_df["n_allr"] / N
    problematic = det_df[det_df["pct_all"] < detect_alert]

    # CV QC norm — vectorizado
    if len(qc_norm_df):
        qc_mat = raw[qc_norm_df["col"].tolist()].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
        mn_qc  = qc_mat.mean(axis=1)
        sd_qc  = qc_mat.std(axis=1, ddof=1)
        cv_qc  = (sd_qc / mn_qc * 100).where(mn_qc > 0).values
    else:
        cv_qc = np.array([])

    # ICC — vectorizado con matrices numpy (mucho más rápido que el bucle por metabolito)
    # Construir matriz (N_metabolitos × N_total_réplicas) con etiquetas de grupo
    all_cols   = []
    group_ids  = []
    for gi, s in enumerate(real_samples):
        cols = samp_df[samp_df["sample_n"]==s]["col"].tolist()
        all_cols.extend(cols)
        group_ids.extend([gi] * len(cols))

    mat = raw[all_cols].apply(pd.to_numeric, errors="coerce").replace(0, np.nan).values
    # mat shape: (N_metabolitos, N_total_replicas)
    # Ensure int dtype: when real_samples is empty (e.g. all-QC experiments
    # such as the Sigma synthetic plasma case study), np.array([]) defaults
    # to float64, which np.bincount rejects.
    group_ids = np.asarray(group_ids, dtype=np.int64)
    n_groups  = len(real_samples)
    n_reps    = n_rep  # réplicas por muestra (asumido uniforme)

    icc_vec = np.full(N, np.nan)

    # ── Detect uniform vs non-uniform replicate counts ────────────────────
    if n_groups == 0:
        # All-QC experiment: there are no biological samples to compute
        # ICC against. Skip the per-feature ICC step; downstream code uses
        # cv_df / cv_qc which are already computed above.
        counts_per_group = np.zeros(0, dtype=np.int64)
    else:
        counts_per_group = np.bincount(group_ids, minlength=n_groups)
    uniform_reps = (counts_per_group.size > 0
                     and counts_per_group.min() == counts_per_group.max()
                     and counts_per_group.min() > 0)

    if uniform_reps:
        # ── Fast tensor path: (N, G, R) ───────────────────────────────────
        n_rep_actual = int(counts_per_group[0])
        try:
            mat_3d = mat.reshape(N, n_groups, n_rep_actual)
        except ValueError:
            # Defensive — column ordering shouldn't break this, but if it
            # does fall through to the non-uniform path below.
            mat_3d = None

        if mat_3d is not None:
            valid = ~np.isnan(mat_3d)
            n_valid_per_group = valid.sum(axis=2)              # (N, G)
            n_groups_with_data = (n_valid_per_group > 0).sum(axis=1)
            do_calc = n_groups_with_data >= 2

            mat_safe = np.where(valid, mat_3d, 0.0)
            gm = np.where(n_valid_per_group > 0,
                          mat_safe.sum(axis=2) / np.where(n_valid_per_group > 0,
                                                            n_valid_per_group, 1),
                          np.nan)
            total_vals  = mat_safe.sum(axis=(1, 2))
            total_count = valid.sum(axis=(1, 2))
            grand = np.where(total_count > 0,
                              total_vals / np.where(total_count > 0, total_count, 1),
                              np.nan)
            ssB = np.nansum(n_valid_per_group.astype(float)
                             * (gm - grand[:, None]) ** 2, axis=1)
            gm_exp = np.broadcast_to(gm[:, :, None], mat_3d.shape)
            ssW = np.nansum(valid * (mat_3d - gm_exp) ** 2, axis=(1, 2))

            dfB = (n_groups_with_data - 1).astype(float)
            dfW = (total_count - n_groups_with_data).astype(float)

            with np.errstate(invalid="ignore", divide="ignore"):
                msB = np.where(dfB > 0, ssB / dfB, np.nan)
                msW = np.where(dfW > 0, ssW / dfW, np.nan)
                icc_raw = np.where(
                    do_calc & (msB > 0),
                    (msB - msW) / (msB + (n_reps - 1) * msW),
                    np.nan,
                )
            icc_vec = np.where(do_calc, np.maximum(0.0, icc_raw), np.nan)

    if not uniform_reps:
        # ── Vectorised non-uniform path ───────────────────────────────────
        # Loops over GROUPS (≈ n_samples) instead of metabolites (≈ N).
        # Each iteration is fully vectorised across all N metabolites,
        # so e.g. 105 groups × 4595 metabolites runs in ~1 s rather than
        # the previous ~minutes of per-metabolite Python.
        valid_full = ~np.isnan(mat)                     # (N, n_total_cols)
        n_per_group = np.zeros((N, n_groups), dtype=float)
        gm = np.full((N, n_groups), np.nan)
        for g in range(n_groups):
            cols_g = np.where(group_ids == g)[0]
            if cols_g.size == 0:
                continue
            sub  = mat[:, cols_g]                       # (N, n_reps_g)
            valg = ~np.isnan(sub)
            n_g  = valg.sum(axis=1).astype(float)
            n_per_group[:, g] = n_g
            sub_safe = np.where(valg, sub, 0.0)
            with np.errstate(invalid="ignore", divide="ignore"):
                gm[:, g] = np.where(n_g > 0,
                                     sub_safe.sum(axis=1) / np.where(n_g > 0, n_g, 1),
                                     np.nan)

        n_total_per_met = n_per_group.sum(axis=1)
        n_groups_with_data = (n_per_group > 0).sum(axis=1)
        do_calc = (n_groups_with_data >= 2) & (n_total_per_met >= 4)

        # Grand mean per metabolite, NaN-safe
        with np.errstate(invalid="ignore", divide="ignore"):
            mat_safe_full = np.where(valid_full, mat, 0.0)
            grand = np.where(n_total_per_met > 0,
                              mat_safe_full.sum(axis=1)
                              / np.where(n_total_per_met > 0, n_total_per_met, 1),
                              np.nan)

        # SS between
        ssB = np.nansum(n_per_group * (gm - grand[:, None]) ** 2, axis=1)

        # SS within: accumulate per-group, broadcasting group mean
        ssW = np.zeros(N)
        for g in range(n_groups):
            cols_g = np.where(group_ids == g)[0]
            if cols_g.size == 0:
                continue
            sub  = mat[:, cols_g]
            diff = sub - gm[:, g:g + 1]                 # NaNs propagate, OK
            ssW += np.nansum(diff ** 2, axis=1)

        # Average n per group with data — used as n0 in ICC(1,1) formula
        with np.errstate(invalid="ignore", divide="ignore"):
            avg_n = np.where(n_groups_with_data > 0,
                              n_total_per_met
                              / np.where(n_groups_with_data > 0,
                                          n_groups_with_data, 1),
                              np.nan)

        dfB = (n_groups_with_data - 1).astype(float)
        dfW = (n_total_per_met - n_groups_with_data).astype(float)

        with np.errstate(invalid="ignore", divide="ignore"):
            msB = np.where(dfB > 0, ssB / dfB, np.nan)
            msW = np.where(dfW > 0, ssW / dfW, np.nan)
            icc_raw = np.where(
                do_calc & (msB > 0) & (avg_n > 1),
                (msB - msW) / (msB + (avg_n - 1) * msW),
                np.nan,
            )
        icc_vec = np.where(do_calc, np.maximum(0.0, icc_raw), np.nan)

    return dict(cv_df=cv_df, cv_qc=cv_qc, icc_vec=icc_vec,
                det_df=det_df, problematic=problematic,
                cv_threshold=cv_threshold, qc_cv_thresh=qc_cv_thresh,
                real_samples=real_samples)


# =============================================================================
# ANÁLISIS ALTERNATIVO — exclusión de réplicas fail/suspect/manual
# =============================================================================

def _parsed_without(parsed: dict, excluded_cols: set[str]) -> dict:
    """Devuelve un `parsed` nuevo sin las columnas indicadas en
    samp_df. Las cabeceras del CSV (`raw`) se conservan intactas —
    `run_m1/m2/qcr` solo leen las columnas que samp_df les pasa, así que
    basta con filtrar samp_df para que el resto del pipeline use solo
    las réplicas válidas. No imputa nada — muestras con 0/1 réplica
    válidas quedan con ese n efectivo (el CV se deja NaN, la media
    agregada se calcula con los valores que haya)."""
    samp_df = parsed["samp_df"]
    keep    = ~samp_df["col"].isin(excluded_cols)
    samp_df_new = samp_df[keep].copy()

    # Renumerar rep dentro de cada muestra para que quede contiguo
    # (1, 2, 3, ...) — útil para que CV_S{n} siga construyéndose bien.
    # La columna 'rep' puede no existir en todas las versiones; si no,
    # no pasa nada (samp_df["sample_n"] basta para el resto del pipeline).
    if "rep" in samp_df_new.columns:
        samp_df_new["rep"] = (samp_df_new
                               .groupby("sample_n")
                               .cumcount() + 1)

    # reps_per_sample — tomar el máximo para preservar el contrato con
    # run_m2.reshape (que asume n_rep uniforme). Si ya no lo es, se
    # marca como -1 para que el consumidor sepa que es variable.
    n_per_sample = samp_df_new.groupby("sample_n").size()
    if len(n_per_sample) and n_per_sample.nunique() == 1:
        reps_per_sample = int(n_per_sample.iloc[0])
    else:
        reps_per_sample = int(n_per_sample.max()) if len(n_per_sample) else 0

    # Muestras que se han quedado sin ninguna réplica válida: se excluyen
    # del listado real_samples para que no aparezcan como columnas vacías.
    real_samples = sorted(samp_df_new["sample_n"].unique().tolist())

    out = dict(parsed)  # shallow copy — raw se comparte (solo lectura)
    out["samp_df"]         = samp_df_new
    out["real_samples"]    = real_samples
    out["n_samples"]       = len(real_samples)
    out["reps_per_sample"] = reps_per_sample
    return out


def _n_effective_per_sample(samp_df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve un DataFrame con columnas [Sample, n_valid_reps]."""
    grp = samp_df.groupby("sample_n").size().reset_index(name="n_valid_reps")
    grp = grp.rename(columns={"sample_n": "Sample"})
    return grp


def build_excluded_cols(qcr: dict, mode: str,
                        manual_cols: list[str] | None = None) -> list[str]:
    """Dado el resultado de run_qcr y un modo de exclusión, devuelve la
    lista de columnas (nombres completos del CSV) a descartar.

    mode ∈ {"none", "fail", "fail_suspect", "manual"}
    manual_cols: solo se usa cuando mode == "manual".
    """
    df = qcr["qcr_df"]
    if mode == "none":
        return []
    if mode == "fail":
        return df[df["Estado"] == "fail"]["Column"].tolist()
    if mode == "fail_suspect":
        return df[df["Estado"].isin(["fail", "suspect"])]["Column"].tolist()
    if mode == "manual":
        return list(manual_cols or [])
    raise ValueError(f"Modo de exclusión desconocido: {mode}")


def run_alternative_analysis(
    parsed: dict, qcr: dict,
    mode: str = "fail",
    manual_cols: list[str] | None = None,
    *,
    r2_threshold: float = 0.6,
    allow2pt: bool = True,
    use_drop: bool = True,
    ion_sup: bool = False,
    cv_threshold: float = 20,
    qc_cv_thresh: float = 15,
    inj_threshold: float = 0.70,
    detect_alert: float = 70,
) -> dict:
    """Re-ejecuta el pipeline completo (QCR + M1 + M2) sobre un subconjunto
    de réplicas, sin imputación. Devuelve un dict con los mismos campos
    que el análisis original + metadatos del modo aplicado:

        { "mode", "excluded_cols", "excluded_rows", "n_excluded",
          "m1_alt", "qcr_alt", "m2_alt",
          "n_eff_per_sample", "samples_dropped" }

    `excluded_rows` es un DataFrame con las filas completas del qcr_df
    original para las réplicas descartadas (útil para documentación).
    `samples_dropped` lista las muestras que se quedaron con 0 réplicas.
    """
    excluded_cols = build_excluded_cols(qcr, mode, manual_cols)
    excluded_rows = qcr["qcr_df"][qcr["qcr_df"]["Column"].isin(excluded_cols)].copy()

    parsed_alt = _parsed_without(parsed, set(excluded_cols))
    n_eff      = _n_effective_per_sample(parsed_alt["samp_df"])

    # Muestras que aparecían en el original pero se han quedado sin réplicas
    orig_samples = set(parsed["real_samples"])
    alt_samples  = set(parsed_alt["real_samples"])
    samples_dropped = sorted(orig_samples - alt_samples)

    # Volver a correr QCR + M1 + M2 con las réplicas válidas
    qcr_alt = run_qcr(parsed_alt, inj_threshold=inj_threshold)
    m1_alt  = run_m1(parsed_alt, r2_threshold=r2_threshold,
                     allow2pt=allow2pt, use_drop=use_drop, ion_sup=ion_sup)
    try:
        m2_alt = run_m2(parsed_alt, cv_threshold=cv_threshold,
                        qc_cv_thresh=qc_cv_thresh, detect_alert=detect_alert)
    except Exception as e:
        # Si algún sample queda con 1 réplica y rompe el reshape de ICC,
        # devolvemos m2=None y el consumidor puede degradar
        # elegantemente (la UI ya sabe manejar modo="linealidad").
        m2_alt = None
        m2_error = str(e)
    else:
        m2_error = None

    return dict(
        mode=mode,
        excluded_cols=excluded_cols,
        excluded_rows=excluded_rows,
        n_excluded=len(excluded_cols),
        m1_alt=m1_alt,
        qcr_alt=qcr_alt,
        m2_alt=m2_alt,
        m2_error=m2_error,
        n_eff_per_sample=n_eff,
        samples_dropped=samples_dropped,
        parsed_alt=parsed_alt,
    )
