"""
core/stats_parser.py
====================

Parser for the **IMIBIC Sample Submission Form** (the Excel template every
user fills in before handing samples to the ECAI).

The form looks like this (Sheet1):

    Row  3:  "Sample submission form"
    Row  4:  "IMIBIC Mass Spectrometry and Molecular Imaging Unit (IMSMI)"
    Row  6:  Date of submission:   | 23/04/2026
    Row  7:  Group:                | Laboratory of Skeletal Biomedicine
    Row  8:  Your name:            | Fabiana Csukasi
    Row  9:  Project name:         | DEPTOR regulates bone-fat imbalance...
    Row 10:  Experiment number:    | 3
    Row 11:  Organism:             | Mus musculus C57BL/6 background
    Row 12:  Sample type:          | Protein lysate from bone marrow
    Row 13:  PTM to analyze:       | Phosphorylation, ubiquitylation
    Row 14:  List of interesting proteins:  | Q570Y9 (Deptor), mTOR...
    Row 15:  Abstract:             | Increased fat content in bones...

    Row 17:  "Table with the samples:"
    Row 18:  headers  (# IMSMI | Sample labels | Sample name | Condition |
                       Replicate | Est. Volume (µl) | Buffer | Prot. conc. |
                       Comments)
    Row 19…N:  one row per sample (up to 96+)

The public API is :func:`parse_submission_form`, which returns a plain dict
with **metadata**, a tidy **samples_df**, and — if the ``Condition`` column
contains comma-separated factor labels (e.g. ``"Wild type, control diet"``)
— a **factorial** description.

The stats module (``pages/stats.py``) uses the ``samples_df`` to:

* label the columns of the Aletheia-aggregated CSV (``S1 … SN`` → pBM62…)
* build group vectors for univariate tests (``Condition`` → group)
* detect 2×2 or k×m factorial designs automatically
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


# =============================================================================
# Constants — metadata field names we recognise in column B (rows 6–15)
# =============================================================================

_META_FIELDS = {
    "Date of submission:":           "date",
    "Group:":                        "group",
    "Your name:":                    "user_name",
    "Project name:":                 "project",
    "Experiment number:":            "experiment_n",
    "Organism:":                     "organism",
    "Sample type:":                  "sample_type",
    "PTM to analyze:":               "ptm",
    "List of interesting proteins:": "interest_list",
    "Abstract:":                     "abstract",
}

# Canonical names (column C in row 18). We normalise user variations.
_CANON_HEADERS = [
    "# IMSMI", "Sample labels", "Sample name", "Condition",
    "Replicate", "Est. Volume (µl)", "Buffer",
    "Prot. conc. (mg/ml)", "Comments",
]

# Attribute name used in samples_df (mapped in order after normalising)
_SAMP_COLS = [
    "imsmi", "label_short", "sample_name", "condition",
    "replicate", "volume_ul", "buffer", "prot_conc_mgml", "comments",
]


# =============================================================================
# Low-level helpers
# =============================================================================

def _norm(s: Any) -> str:
    """Strip + collapse whitespace, tolerant of None."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _find_table_header(ws) -> int:
    """Return the row index (1-based) that contains the sample-table headers.

    The canonical row is 18 but the template has been edited a few times, so
    we search rows 10-40 for the string ``"# IMSMI"`` in column A.
    """
    for row_idx in range(10, 41):
        v = ws.cell(row=row_idx, column=1).value
        if v and "IMSMI" in str(v):
            return row_idx
    raise ValueError(
        "No se encontró la cabecera de la tabla de muestras "
        "(columna A debe contener '# IMSMI' en alguna de las filas 10-40)."
    )


def _read_metadata(ws) -> dict[str, str]:
    """Scan rows 1–17, pick up the known metadata fields (column B = key, C = value)."""
    md: dict[str, str] = {}
    for row_idx in range(1, 18):
        key = _norm(ws.cell(row=row_idx, column=2).value)
        if not key:
            continue
        slug = _META_FIELDS.get(key)
        if slug:
            md[slug] = _norm(ws.cell(row=row_idx, column=3).value)
    return md


# =============================================================================
# Factorial-design detection
# =============================================================================

def _split_condition(cond: str) -> list[str]:
    """Split ``"Wild type, control diet"`` into ``["Wild type", "control diet"]``.

    Accepts commas, semicolons, and " / " as separators. Trims whitespace.
    """
    if not cond:
        return []
    parts = re.split(r"[,/;]", cond)
    return [_norm(p) for p in parts if _norm(p)]


def detect_factorial(conditions: list[str]) -> dict[str, Any]:
    """Inspect the list of Condition labels and report whether a factorial
    design seems to be present.

    A factorial design is detected when every Condition label splits into the
    same number of tokens (≥ 2), and the cartesian product of the token-sets
    covers the observed conditions.

    Returns a dict with keys:

    * ``is_factorial``  : bool
    * ``n_factors``     : int
    * ``factors``       : list of ``{"levels": [...], "name": "Factor_i"}``
    * ``condition_map`` : dict condition -> tuple of factor levels (len = n_factors)
    """
    split = [(c, _split_condition(c)) for c in conditions]

    # No condition or wildly inconsistent token counts → not a factorial
    token_counts = {len(s) for _, s in split if s}
    if not token_counts or len(token_counts) != 1:
        return {"is_factorial": False, "n_factors": 1, "factors": [],
                "condition_map": {c: (c,) for c in conditions}}
    n = token_counts.pop()
    if n < 2:
        return {"is_factorial": False, "n_factors": 1, "factors": [],
                "condition_map": {c: (c,) for c in conditions}}

    # Collect levels per factor position
    factors: list[list[str]] = [[] for _ in range(n)]
    seen = [set() for _ in range(n)]
    for _, toks in split:
        for i, tk in enumerate(toks):
            if tk not in seen[i]:
                seen[i].add(tk)
                factors[i].append(tk)

    # A valid factorial must have ≥ 2 levels in every factor
    if any(len(f) < 2 for f in factors):
        return {"is_factorial": False, "n_factors": 1, "factors": [],
                "condition_map": {c: (c,) for c in conditions}}

    cond_map = {c: tuple(toks) for c, toks in split}
    return {
        "is_factorial": True,
        "n_factors":    n,
        "factors":      [{"name": f"Factor_{i+1}", "levels": lv}
                         for i, lv in enumerate(factors)],
        "condition_map": cond_map,
    }


# =============================================================================
# Public API
# =============================================================================

def parse_submission_form(xlsx_path: str,
                           sheet: str | int = 0) -> dict[str, Any]:
    """Parse an IMIBIC sample submission form.

    Parameters
    ----------
    xlsx_path : str
        Path to the ``.xlsx`` file.
    sheet : str | int, optional
        Sheet name or index. By default the first sheet.

    Returns
    -------
    dict with the following keys:

    * ``metadata``  — dict[str, str] with project info
    * ``samples_df`` — ``pandas.DataFrame`` (one row per sample)
        columns: ``imsmi``, ``label_short``, ``sample_name``, ``condition``,
                 ``replicate``, ``volume_ul``, ``buffer``, ``prot_conc_mgml``,
                 ``comments``
    * ``factorial`` — output of :func:`detect_factorial`
    * ``conditions`` — list of **unique** conditions (in order of appearance)
    * ``n_samples``  — int
    """
    if openpyxl is None:
        raise RuntimeError(
            "openpyxl no está instalado. Ejecuta `pip install openpyxl`."
        )

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if isinstance(sheet, int):
        ws = wb[wb.sheetnames[sheet]]
    else:
        ws = wb[sheet]

    metadata = _read_metadata(ws)
    header_row = _find_table_header(ws)

    # Read the sample table starting just after the headers
    rows: list[dict[str, Any]] = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        # Stop at the first fully-empty row — the template has explanatory
        # text after the sample block.
        if row is None or all(c is None or _norm(c) == "" for c in row[:9]):
            break
        # If the # IMSMI column is non-numeric (e.g. text note), stop.
        try:
            imsmi = int(row[0]) if row[0] is not None else None
        except (ValueError, TypeError):
            break
        if imsmi is None:
            break

        entry = {
            "imsmi":          imsmi,
            "label_short":    _norm(row[1]) if len(row) > 1 else "",
            "sample_name":    _norm(row[2]) if len(row) > 2 else "",
            "condition":      _norm(row[3]) if len(row) > 3 else "",
            "replicate":      row[4]        if len(row) > 4 else None,
            "volume_ul":      row[5]        if len(row) > 5 else None,
            "buffer":         _norm(row[6]) if len(row) > 6 else "",
            "prot_conc_mgml": row[7]        if len(row) > 7 else None,
            "comments":       _norm(row[8]) if len(row) > 8 else "",
        }
        rows.append(entry)

    samples_df = pd.DataFrame(rows, columns=_SAMP_COLS)

    # Sample name fallback — if column C is empty, use column B (label_short)
    samples_df["sample_name"] = samples_df.apply(
        lambda r: r["sample_name"] or r["label_short"], axis=1
    )

    # Collect unique conditions preserving first-appearance order
    uniq_conds: list[str] = []
    for c in samples_df["condition"].tolist():
        if c and c not in uniq_conds:
            uniq_conds.append(c)

    factorial = detect_factorial(uniq_conds)

    # Add factor columns to samples_df when factorial is detected
    if factorial["is_factorial"]:
        for i in range(factorial["n_factors"]):
            col = f"factor_{i+1}"
            samples_df[col] = samples_df["condition"].map(
                lambda c: factorial["condition_map"].get(c, (None,) * factorial["n_factors"])[i]
            )

    return {
        "metadata":   metadata,
        "samples_df": samples_df,
        "factorial":  factorial,
        "conditions": uniq_conds,
        "n_samples":  len(samples_df),
    }


# =============================================================================
# Column matching (submission form ↔ MetaboScape aggregated CSV)
# =============================================================================

# Aletheia's aggregated CSV uses column names like "S1", "S2", … "SN" where
# the numeric part equals the "# IMSMI" field of the submission form.
_SAMPLE_COL_RE = re.compile(r"^S(\d+)$")


def match_aggregated_columns(samples_df: pd.DataFrame,
                              data_columns: list[str]) -> dict[str, Any]:
    """Match the sample table to the columns of an aggregated CSV.

    Parameters
    ----------
    samples_df : DataFrame
        Output of :func:`parse_submission_form` (must contain ``imsmi`` + ``sample_name``).
    data_columns : list[str]
        Column names of the aggregated CSV (typically ``S1``, ``S2``, …).

    Returns
    -------
    dict with:

    * ``matched`` — list of dicts ``{"data_col": "S1", "imsmi": 1, "sample_name": "pBM62"}``
    * ``unmatched_data``   — data columns we could not place
    * ``unmatched_samples`` — samples with no matching column
    * ``rename_map``       — ``{"S1": "pBM62", ...}`` — handy for plotting
    """
    by_imsmi = {int(r["imsmi"]): r["sample_name"]
                for _, r in samples_df.iterrows() if pd.notna(r["imsmi"])}

    matched, unmatched_data = [], []
    for col in data_columns:
        m = _SAMPLE_COL_RE.match(col)
        if not m:
            continue  # skip meta columns
        n = int(m.group(1))
        if n in by_imsmi:
            matched.append({"data_col": col, "imsmi": n, "sample_name": by_imsmi[n]})
        else:
            unmatched_data.append(col)

    matched_imsmi = {m["imsmi"] for m in matched}
    unmatched_samples = [int(i) for i in by_imsmi if int(i) not in matched_imsmi]

    return {
        "matched":            matched,
        "unmatched_data":     unmatched_data,
        "unmatched_samples":  unmatched_samples,
        "rename_map":         {m["data_col"]: m["sample_name"] for m in matched},
    }
