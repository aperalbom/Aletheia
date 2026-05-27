"""
core/sample_history.py
─────────────────────────────────────────────────────────────────────────────
Shared per-user sample history for all Aletheia services.
(proteomics, metabolomics, lipidomics, …)

Design rules
────────────
• One record per (user, SOL).  Re-generating the same report UPDATES the
  existing record instead of appending a new one → no accumulation of n_samples.
• Records are sorted newest-first in the dropdown.
• The dropdown label shows:  <icon> SOL — n samples · sub-type · organism [Service]

JSON schema  (data/sample_history.json)
───────────────────────────────────────
{
  "<username_lower>": {
    "SOL2026026": {
      "service":        "proteomics",
      "sol":            "SOL2026026",
      "scat":           "tissue",
      "ssub":           "pituitary gland",
      "sorg":           "Homo sapiens",
      "nsamp":          "38",
      "hplc_method":    "nanoelute2_36min",          # proteomics only
      "hplc_options":   ["extended_wash"],            # proteomics only
      "last_generated": "2026-04-14T13:14:00"
    },
    "SOL2026031": { … },
    …
  },
  …
}

Public API
──────────
  save_entry(user, sol, service, scat, ssub, sorg, nsamp="",
             hplc_method="", hplc_options=None)
  get_user_entries(user)           → dict  {sol: entry, …}  (sorted newest first)
  build_dropdown_options(user)     → list  of Dash Dropdown option dicts
  get_entry(user, sol)             → dict | None
  register_cat_labels(extra_dict)  → extend CAT_LABELS for non-proteomics pages
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
_HIST_FILE: Path = Path(__file__).parent.parent / "data" / "sample_history.json"

# Human-readable labels for sample category values
CAT_LABELS: dict[str, str] = {
    "tissue":       "Tissue",
    "cell_culture": "Cell culture",
    "plasma":       "Plasma",
    "serum":        "Serum",
    "urine":        "Urine",
    "pbmc":         "PBMC",
    "csf":          "CSF",
    "ev":           "Extracellular vesicles",
    "other":        "Samples",
}

SERVICE_ICONS: dict[str, str] = {
    "proteomics":   "🔬",
    "metabolomics": "🧪",
    "lipidomics":   "💧",
}


# ──────────────────────────────────────────────────────────────────────────────
# Low-level I/O
# ──────────────────────────────────────────────────────────────────────────────

def _read() -> dict[str, dict[str, Any]]:
    """Load full history; returns {} on any error."""
    try:
        if _HIST_FILE.exists():
            return json.loads(_HIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write(hist: dict[str, dict[str, Any]]) -> None:
    """Persist full history to disk. Silently ignores write errors."""
    try:
        _HIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HIST_FILE.write_text(
            json.dumps(hist, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def save_entry(
    user:         str,
    sol:          str,
    service:      str,
    scat:         str  = "",
    ssub:         str  = "",
    sorg:         str  = "",
    nsamp:        str  = "",
    hplc_method:  str  = "",
    hplc_options: list[str] | None = None,
    **extras:     Any,
) -> None:
    """
    Upsert a history record keyed by (user, SOL).

    Calling this multiple times for the same SOL simply updates the record —
    n_samples is stored as-is, never accumulated.  Skipped if user or sol is
    empty, or if all sample fields are empty.

    `hplc_method` / `hplc_options` are proteomics-specific and are stored so
    that re-opening a past solicitud in the UI can restore the exact
    chromatographic method + toggles the user picked last time.

    `**extras` accepts any additional per-entry fields the caller wants to
    persist — typically used for autocomplete bookkeeping (e.g. inst, email,
    genby, cond, fasta, fasta_date, val_name) and for restoring per-SOL
    preferences (e.g. recon_mode/vol/inj). Keys with empty values are stored
    as empty strings so `get_unique_values(...)` stays consistent.
    """
    user = (user or "").strip()
    sol  = (sol  or "").strip()
    if not user or not sol:
        return
    if not any([scat, ssub, sorg, nsamp]):
        return

    hist    = _read()
    u_dict  = hist.setdefault(user.lower(), {})

    # Composite key = sol|service → same SOL can exist once per service, never
    # accumulates across multiple generations of the same service+SOL pair.
    entry_key = f"{sol}|{service}" if service else sol

    entry = {
        "service":        service or "unknown",
        "sol":            sol,
        "dest":           user,          # preserve display-name capitalisation
        "scat":           scat   or "",
        "ssub":           ssub   or "",
        "sorg":           sorg   or "",
        "nsamp":          str(nsamp) if nsamp else "",
        "hplc_method":    hplc_method or "",
        "hplc_options":   list(hplc_options) if hplc_options else [],
        "last_generated": datetime.now().strftime("%Y-%m-%dT%H:%M"),
    }
    # Merge caller-supplied extras (stringifying simple scalars so they
    # feed cleanly into get_unique_values). Lists/dicts are stored as-is.
    for k, v in extras.items():
        if isinstance(v, (list, dict)):
            entry[k] = v
        elif v is None:
            entry[k] = ""
        else:
            entry[k] = str(v)

    u_dict[entry_key] = entry

    _write(hist)


def get_user_entries(user: str) -> dict[str, Any]:
    """
    Return the SOL → entry dict for *user* (case-insensitive).
    Returns an empty dict if the user has no history.
    """
    if not user or not user.strip():
        return {}
    return _read().get(user.strip().lower(), {})


def get_entry(user: str, sol: str) -> dict[str, Any] | None:
    """Return the history entry for a specific (user, SOL), or None."""
    return get_user_entries(user).get((sol or "").strip())


def build_dropdown_options(user: str) -> list[dict[str, str]]:
    """
    Return Dash Dropdown options for *user*, newest-first.

    Label format:
      🔬  SOL2026026 — 38 · pituitary gland · Homo sapiens  [Proteomics]
    """
    entries = get_user_entries(user)
    if not entries:
        return []

    # Sort by last_generated descending (newest first)
    sorted_items = sorted(
        entries.items(),
        key=lambda kv: kv[1].get("last_generated", ""),
        reverse=True,
    )

    options = []
    for entry_key, e in sorted_items:
        icon      = SERVICE_ICONS.get(e.get("service", ""), "📋")
        sol_lbl   = e.get("sol", entry_key.split("|")[0])
        nsamp_lbl = e.get("nsamp", "")
        sub_lbl   = e.get("ssub") or CAT_LABELS.get(e.get("scat", ""), e.get("scat", ""))
        org_lbl   = e.get("sorg", "")
        svc_lbl   = e.get("service", "").capitalize()

        desc_parts = [p for p in [nsamp_lbl, sub_lbl, org_lbl] if p]
        desc = " · ".join(desc_parts) if desc_parts else "—"

        label = f"{icon}  {sol_lbl} — {desc}  [{svc_lbl}]"
        # Use the full storage key as value so _apply_history can look it up directly
        options.append({"label": label, "value": entry_key})

    return options


def get_unique_values(field: str, service: str | None = None) -> list[str]:
    """Return sorted unique non-empty values for *field* across all history entries.

    If *service* is given (e.g. 'proteomics', 'metabolomics', 'lipidomics') only
    entries of that service are considered.
    """
    hist = _read()
    values: set[str] = set()
    for user_dict in hist.values():
        for entry in user_dict.values():
            if service and entry.get("service") != service:
                continue
            val = (entry.get(field) or "").strip()
            if val:
                values.add(val)
    return sorted(values, key=lambda s: s.lower())


def get_all_users() -> list[str]:
    """Return a sorted list of all user keys ever stored (original capitalisation preserved)."""
    hist = _read()
    # Keys are stored lower-cased; recover display names from the most recent entry's dest field
    names: list[str] = []
    for user_key, sol_dict in hist.items():
        # Try to get a prettier display name from a stored entry
        display = user_key
        for entry in sol_dict.values():
            candidate = (entry.get("dest") or entry.get("user") or "").strip()
            if candidate:
                display = candidate
                break
        if display:
            names.append(display)
    return sorted(set(names), key=lambda s: s.lower())


def register_cat_labels(extra: dict[str, str]) -> None:
    """Allow other pages to extend the category label map."""
    CAT_LABELS.update(extra)
