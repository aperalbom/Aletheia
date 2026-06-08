"""
pages/randomizer.py — Lista randomizada de inyecciones para LC-MS

Genera una worklist aleatorizada para copiar y pegar directamente en el
software del equipo (Evosep One, Evosep Elute o Bruker nanoElute 2).

Entradas
────────
  · Prefijo SOL + rango numérico (ej. SOL2026002, 1 → 105)
  · Nº de réplicas por muestra (todas las réplicas llevan el mismo nombre)
  · QC cada X inyecciones (0 = ninguno) + QC inicial/final opcional
  · Equipo → formato de vial:
        Evosep      · 6 placas S1–S6, cada una 8 filas × 12 cols   (576 pos.)
        Elute       · 1 → 108
        nanoElute   · Slot1:1 → Slot2:54                           (108 pos.)
  · Posición inicial (por defecto la primera del equipo seleccionado)
  · Semilla opcional para reproducibilidad
  · Volumen de inyección (muestras y QC, independientes)

Salida
──────
  · Tabla con columnas: #, Sample Name, Vial, Inj. Vol (µL)
  · Textarea copiable (tab-separated) → Ctrl+A, Ctrl+C listo para pegar
  · Descarga .csv o .tsv
"""
from __future__ import annotations

import io
import random
import re
from typing import Iterator

import dash
from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate

dash.register_page(__name__, path="/randomizer",
                   name="Listas randomizadas")

# =============================================================================
# COLORES (idéntico a proteomics.py para coherencia visual)
# =============================================================================

TEAL   = "#4A9B8F"
DARK   = "#2C2C2A"
CREAM  = "#F7F6F2"
MUTED  = "#888780"
BORDER = "#E4E2DC"

# =============================================================================
# HELPERS DE ESTILO (clones livianos de los de proteomics.py)
# =============================================================================

def _lbl(t):
    return html.Div(t, style={
        "fontSize": "10px", "fontWeight": "600", "color": MUTED,
        "letterSpacing": ".03em", "textTransform": "uppercase",
        "fontFamily": "monospace", "marginBottom": "4px", "marginTop": "10px",
    })


def _inp_style():
    return {
        "width": "100%", "padding": "7px 10px",
        "border": f"1px solid {BORDER}", "borderRadius": "6px",
        "fontSize": "12px", "fontFamily": "monospace",
        "boxSizing": "border-box", "background": "#fff",
    }


def _card(title, children):
    return html.Div(style={
        "background": "#fff", "border": f"1px solid {BORDER}",
        "borderRadius": "10px", "padding": "1.2rem 1.4rem",
        "marginBottom": "1rem",
    }, children=[
        html.Div(title, style={
            "fontSize": "10px", "fontWeight": "600", "letterSpacing": ".07em",
            "textTransform": "uppercase", "color": MUTED,
            "fontFamily": "monospace", "marginBottom": "1rem",
        }),
        *children,
    ])


# =============================================================================
# ITERADORES DE POSICIÓN
# =============================================================================

_EVOSEP_RE   = re.compile(r"^\s*S([1-6])-([A-Ha-h])(\d{1,2})\s*$")
_NANO_RE     = re.compile(r"^\s*Slot([12]):(\d{1,2})\s*$", re.IGNORECASE)
_ELUTE_RE    = re.compile(r"^\s*(\d{1,3})\s*$")

_ROWS = "ABCDEFGH"


def _parse_evosep(pos: str) -> tuple[int, int, int]:
    m = _EVOSEP_RE.match(pos or "")
    if not m:
        return 1, 0, 1           # fallback: S1-A1
    s, row, col = int(m.group(1)), m.group(2).upper(), int(m.group(3))
    r_idx = _ROWS.index(row)
    if not (1 <= s <= 6 and 1 <= col <= 12):
        return 1, 0, 1
    return s, r_idx, col


def _parse_nanoelute(pos: str) -> tuple[int, int]:
    m = _NANO_RE.match(pos or "")
    if not m:
        return 1, 1
    slot, n = int(m.group(1)), int(m.group(2))
    if not (1 <= slot <= 2 and 1 <= n <= 54):
        return 1, 1
    return slot, n


def _parse_elute(pos: str) -> int:
    m = _ELUTE_RE.match(pos or "")
    if not m:
        return 1
    v = int(m.group(1))
    return v if 1 <= v <= 108 else 1


def iter_evosep(start: str = "S1-A1") -> Iterator[str]:
    """S1-A1 → S1-A12 → S1-B1 → … → S6-H12  (576 posiciones)."""
    s, r_idx, col = _parse_evosep(start)
    while s <= 6:
        while r_idx < 8:
            while col <= 12:
                yield f"S{s}-{_ROWS[r_idx]}{col}"
                col += 1
            col = 1
            r_idx += 1
        r_idx = 0
        s += 1


def iter_evosep_balanced(total: int, start_plate: int = 1) -> Iterator[str]:
    """Yield `total` Evosep positions distributed evenly across an **even**
    number of plates (for centrifuge balance), filling each plate with
    `ceil(total / n_plates)` tips sequentially row-major (A1..A12 → B1..
    → H12) before jumping to the next plate.

    Number of plates:
        · total ≤ 192  → 2 plates
        · total ≤ 384  → 4 plates
        · total ≤ 576  → 6 plates

    Each plate receives `per_plate = ceil(total / n_plates)` tips, so the
    two halves end up balanced (equal or differing by 1 if odd total).
    The last plate may have fewer tips. Tips start at position A1 of
    each plate (loading always begins row-major from the top).

    `start_plate` (default 1) lets a caller offset the first plate used.
    """
    if total <= 0:
        return
    # Even number of plates for centrifuge balance
    if total <= 192:
        n_plates = 2
    elif total <= 384:
        n_plates = 4
    else:
        n_plates = 6
    # Cap by what's physically available
    plates_available = max(1, 6 - start_plate + 1)
    n_plates = min(n_plates, plates_available)
    per_plate = -(-total // n_plates)  # ceil
    # Clamp per_plate to plate capacity
    per_plate = min(per_plate, 96)

    for i in range(total):
        plate_offset = i // per_plate
        local_idx = i % per_plate
        plate = start_plate + plate_offset
        if plate > 6:
            yield "—"
            continue
        r = local_idx // 12
        c = local_idx % 12 + 1
        yield f"S{plate}-{_ROWS[r]}{c}"


def iter_elute(start: int | str = 1) -> Iterator[str]:
    if isinstance(start, str):
        start = _parse_elute(start)
    v = max(1, min(108, int(start)))
    while v <= 108:
        yield str(v)
        v += 1


def iter_nanoelute(start: str = "Slot1:1") -> Iterator[str]:
    slot, n = _parse_nanoelute(start)
    while slot <= 2:
        while n <= 54:
            yield f"Slot{slot}:{n}"
            n += 1
        n = 1
        slot += 1


def _positions_for(instrument: str, start: str) -> Iterator[str]:
    if instrument == "evosep":
        return iter_evosep(start or "S1-A1")
    if instrument == "elute":
        return iter_elute(start or "1")
    return iter_nanoelute(start or "Slot1:1")


# =============================================================================
# BUILD WORKLIST
# =============================================================================

def build_worklist(
    *,
    sol_prefix:     str,
    n_start:        int,
    n_end:          int,
    replicates:     int,
    qc_name:        str,
    qc_every:       int,
    qc_at_start:    bool,
    qc_at_end:      bool,
    instrument:     str,
    init_pos:       str,
    qc_vial:        str = "",
    hela_count:     int = 0,
    hela_vial:      str = "",
    hela_name:      str = "HeLa",
    hela_vol:       float | None = None,
    # QC dilution-series block (untargeted metabolomics / lipidomics):
    # inserted between the equilibration tips and the main sample sequence.
    # Sandwiched by one pool-QC injection on each side so the block sits
    # between known stability anchors. See Aletheia paper §2.6 for the
    # design rationale.
    #
    # Two operational modes:
    #   · "vials"  — 5 separately pre-diluted vials (one per QC level).
    #                Each level gets its own physical vial (sequential
    #                from `dil_vial_start`). Injection volume is constant
    #                (`dil_vol`). This is the classic dilution-series setup.
    #   · "volume" — single concentrated QC pool vial reused for all
    #                dilutions; the dilution factor is achieved by varying
    #                the *injection volume*. Effective volume per level is
    #                `dil_base_vol × level / 100` (e.g. level 20 → 1 µL when
    #                `dil_base_vol = 5`). All injections reuse `qc_vial`,
    #                so `dil_vial_start` is ignored in this mode.
    dil_enabled:    bool = False,
    dil_mode:       str  = "vials",            # "vials" | "volume"
    dil_levels:     list[int] | None = None,   # e.g. [20, 40, 60, 80, 100]
    dil_replicates: int = 1,
    dil_name_prefix: str = "QC",                # → QC20, QC40, …
    dil_vial_start: str = "",
    dil_vol:        float | None = None,
    dil_base_vol:   float | None = None,        # only used when dil_mode="volume"
    duplicate_every: int = 0,
    seed:           int | None = None,
    sample_vol:     float = 2,
    qc_vol:         float = 2,
) -> list[dict]:
    """Return a list of dicts {'name', 'vial', 'vol', 'is_qc'} in final
    injection order.

    Vial-assignment rules (depend on instrument):

      · **Evosep One** — Evotips are loaded by centrifugation **in
        physical order**, then injected in random order. Each Evotip is
        single-use, so every injection consumes a fresh tip. The loading
        layout is:
            – QCs are loaded consecutively starting from `qc_vial`
              (e.g. `S2-A1`, `S2-A2`, …). The number of QC tips loaded
              equals `qc_at_start + qc_at_end + ⌊N_samples / qc_every⌋`.
            – Samples are loaded consecutively starting from `init_pos`
              (e.g. `S3-A1`, `S3-A2`, …) in **ascending** sample order
              with replicates contiguous:
                 SOL-1 rep-1, SOL-1 rep-2, SOL-1 rep-3, SOL-2 rep-1, …
        Each tip is labelled when loaded; the INJECTION order is then
        randomised, but every injection keeps its pre-loaded tip.
        If `qc_vial` is empty, samples and QCs share the same iterator
        starting at `init_pos`.

      · **Evosep Elute / Bruker nanoElute 2** — one vial per sample;
        replicates of the same sample share that vial. Sample *k* is
        placed at position `init_pos + (k - n_start)` in the iterator,
        so sample 1 → vial 1, sample 2 → vial 2, … when `init_pos` = 1
        (or the equivalent for Slot1:1 on nanoElute). All QC injections
        go to a single fixed position given by `qc_vial`; if empty,
        the first position *after* the last sample vial is used.

    Other rules:
      · Replicates keep the same sample name (no -R1/-R2 suffix).
      · QC is inserted every `qc_every` sample-injections inside the
        shuffled block (not counting the leading QC). `qc_every=0`
        disables it. `qc_at_start` / `qc_at_end` add one extra QC at
        each boundary.
    """
    n_start = max(1, int(n_start))
    n_end   = max(n_start, int(n_end))
    replicates = max(1, int(replicates))
    qc_every   = max(0, int(qc_every))
    hela_count = max(0, int(hela_count or 0))
    hela_name  = (hela_name or "HeLa").strip() or "HeLa"
    duplicate_every = max(0, int(duplicate_every or 0))
    if hela_vol in ("", None):
        hela_vol = qc_vol

    # ── QC dilution-series parameters ────────────────────────────────────
    dil_enabled    = bool(dil_enabled)
    dil_replicates = max(0, int(dil_replicates or 0))
    dil_name_prefix = (dil_name_prefix or "QC").strip() or "QC"
    dil_mode = (dil_mode or "vials").strip().lower()
    if dil_mode not in ("vials", "volume"):
        dil_mode = "vials"
    # Default levels: standard QC dilution-series used by Aletheia (20/40/60/80/100 %)
    if dil_levels is None:
        dil_levels_clean: list[int] = [20, 40, 60, 80, 100]
    else:
        try:
            dil_levels_clean = sorted(
                int(x) for x in dil_levels if str(x).strip() != ""
            )
        except (TypeError, ValueError):
            dil_levels_clean = []
    if dil_vol in ("", None):
        dil_vol = qc_vol
    # Base volume for "volume" mode: max injection volume (= QC100). Defaults
    # to the user-set dil_vol or qc_vol if neither was specified.
    if dil_base_vol in ("", None):
        dil_base_vol = dil_vol if dil_vol not in ("", None) else qc_vol
    # Only actually build the block if all preconditions are met
    do_dilution = (dil_enabled and dil_replicates > 0 and len(dil_levels_clean) > 0)

    rng = random.Random(seed if seed not in ("", None) else None)

    def _count_qc(n_samples: int) -> tuple[int, int]:
        """(n_intercalated, n_total) for given sample-injection count."""
        n_inter = (n_samples // qc_every) if qc_every > 0 else 0
        # Drop the final intercalated QC if it lands right before the
        # end-block (mirrors the interleave loop).
        if (qc_every > 0 and n_inter > 0 and n_samples % qc_every == 0):
            n_inter -= 1
        n_tot = (1 if qc_at_start else 0) + n_inter + (1 if qc_at_end else 0)
        return n_inter, n_tot

    if instrument == "evosep":
        # ─── Evosep — balanced contiguous loading, random injection ───
        #
        # Physical loading layout:
        #   HeLa  (hela_count)    → injected FIRST in loading order
        #   QCs   (n_qc_total)    → injected at start/every qc_every/end
        #   Samples (unique)      → one tip per unique sample, in order,
        #                           with each random duplicate inserted
        #                           IMMEDIATELY AFTER its original so the
        #                           two tips live in physically adjacent
        #                           wells (e.g. sample 4 at S1-C4 →
        #                           duplicate at S1-C5).
        #
        # The whole thing is a single contiguous sequence of tips. Tips
        # are distributed evenly across an EVEN number of plates (2, 4 or
        # 6) so the Evotip centrifuge stays balanced. The total tip count
        # is also forced to be even by adding one extra random duplicate
        # if needed.
        qcname = qc_name or "QC"

        # 1. Unique sample names
        unique_samples: list[str] = []
        for i in range(n_start, n_end + 1):
            base = f"{sol_prefix}-{i}" if sol_prefix else str(i)
            unique_samples.append(base)
        n_unique = len(unique_samples)

        # 2. Build the sample load-order list with adjacent duplicates.
        #    Start from the ordered unique list; pick N random samples to
        #    duplicate and insert each duplicate right after its original
        #    (so the two tips end up in consecutive physical positions).
        sample_load_order: list[str] = list(unique_samples)

        def _insert_duplicate_after(name: str) -> None:
            """Insert one duplicate of `name` right after its last
            occurrence in `sample_load_order` — keeps copies physically
            adjacent on the plate."""
            for i in range(len(sample_load_order) - 1, -1, -1):
                if sample_load_order[i] == name:
                    sample_load_order.insert(i + 1, name)
                    return

        if duplicate_every > 0 and n_unique > 0:
            n_dupes = n_unique // duplicate_every
            chosen = rng.sample(unique_samples, min(n_dupes, n_unique))
            for nm in chosen:
                _insert_duplicate_after(nm)

        duplicate_samples = [nm for nm in sample_load_order
                              if sample_load_order.count(nm) > 1][:]
        # (rebuilt later — keep for stats/tests that inspect it)

        n_samples_total = len(sample_load_order)

        # 3. Count QCs based on current sample count
        n_intercalated, n_qc_total = _count_qc(n_samples_total)

        # 4. Enforce EVEN total-tip count for centrifuge balance. Each
        #    parity-fix adds one duplicate glued to its original. Loop
        #    until even (at most 2 iterations in realistic cases).
        total_tips = hela_count + n_qc_total + n_samples_total
        guard = 0
        while total_tips % 2 == 1 and n_unique > 0 and guard < 3:
            extra = rng.choice(unique_samples)
            _insert_duplicate_after(extra)
            n_samples_total = len(sample_load_order)
            n_intercalated, n_qc_total = _count_qc(n_samples_total)
            total_tips = hela_count + n_qc_total + n_samples_total
            guard += 1

        # 5. Allocate tip positions. Single contiguous balanced sequence
        #    starting at `init_pos` (default S1-A1). The loading order on
        #    plate is: HeLa → QCs → samples (with adjacent duplicates).
        start_plate = _parse_evosep(init_pos or "S1-A1")[0]
        tip_positions = list(
            iter_evosep_balanced(total_tips, start_plate=start_plate)
        )
        idx_p = 0
        hela_tips    = tip_positions[idx_p:idx_p + hela_count]
        idx_p += hela_count
        qc_tips      = tip_positions[idx_p:idx_p + n_qc_total]
        idx_p += n_qc_total
        sample_tips  = tip_positions[idx_p:idx_p + n_samples_total]

        # 6. Build sample-injection pool (sample_load_order already has
        #    duplicates in the right *physical* spots), then shuffle for
        #    the injection list. Physical adjacency survives the shuffle
        #    because each copy carries its own vial.
        sample_injections: list[dict] = [
            {"name": nm, "vial": tip, "is_qc": False, "is_hela": False,
             "vol": sample_vol}
            for nm, tip in zip(sample_load_order, sample_tips)
        ]
        rng.shuffle(sample_injections)

        # 7. HeLa block: injected FIRST in loading order (not shuffled)
        hela_rows_ev: list[dict] = [
            {"name": hela_name, "vial": tip, "is_qc": False, "is_hela": True,
             "vol": hela_vol}
            for tip in hela_tips
        ]

        # 8. Weave QCs (start / every-X / end) in injection order
        qc_iter2 = iter(qc_tips)
        rows: list[dict] = list(hela_rows_ev)
        if qc_at_start:
            rows.append({"name": qcname, "vial": next(qc_iter2, "—"),
                         "is_qc": True, "is_hela": False, "vol": qc_vol})
        for idx, inj in enumerate(sample_injections):
            rows.append(inj)
            placed = idx + 1
            last = (idx == len(sample_injections) - 1)
            if qc_every > 0 and placed % qc_every == 0 and not last:
                rows.append({"name": qcname, "vial": next(qc_iter2, "—"),
                             "is_qc": True, "is_hela": False, "vol": qc_vol})
        if qc_at_end:
            rows.append({"name": qcname, "vial": next(qc_iter2, "—"),
                         "is_qc": True, "is_hela": False, "vol": qc_vol})
        return rows

    # ── HeLa equilibration block for Elute/nanoElute (shared vial) ─────
    hela_rows: list[dict] = []
    if hela_count > 0:
        default_h = "108" if instrument == "elute" else "Slot2:54"
        h_vial = (hela_vial or "").strip() or default_h
        for _ in range(hela_count):
            hela_rows.append({"name": hela_name, "vial": h_vial,
                              "is_qc": False, "is_hela": True,
                              "vol": hela_vol})

    # ── QC dilution-series block (Elute/nanoElute, optional) ───────────
    # Inserted between the equilibration block and the main sample
    # sequence, sandwiched by one pool-QC injection on each side so the
    # series is flanked by stability anchors. Order is ascending
    # (QC20 → QC100) by convention — randomisation of the dilution
    # levels is left to the downstream analyst if needed.
    qcname = qc_name or "QC"
    dilution_rows: list[dict] = []
    if do_dilution:
        # ── Mode A · "vials" — 5 pre-diluted vials, constant volume ────
        # Each dilution level lives in its own physical vial. Vials are
        # assigned sequentially from `dil_vial_start` (per-instrument
        # iterator); placeholder labels are used if no start was given.
        #
        # ── Mode B · "volume" — single concentrated vial, variable volume ─
        # All dilution rows share the main QC vial (`qc_vial_resolved`).
        # The dilution factor is achieved by varying the *injection volume*:
        # vol(level) = dil_base_vol × level / 100. So level 20 with
        # base 5 µL → 1 µL, level 40 → 2 µL, …, level 100 → 5 µL.
        if dil_mode == "vials":
            dvs = (dil_vial_start or "").strip()
            if dvs:
                try:
                    dil_positions = _positions_for(instrument, dvs)
                    level_vials = {
                        lvl: next(dil_positions, "—") for lvl in dil_levels_clean
                    }
                except Exception:
                    level_vials = {
                        lvl: f"[{dil_name_prefix}{lvl}]" for lvl in dil_levels_clean
                    }
            else:
                level_vials = {
                    lvl: f"[{dil_name_prefix}{lvl}]" for lvl in dil_levels_clean
                }
            level_vols = {lvl: dil_vol for lvl in dil_levels_clean}
        else:  # dil_mode == "volume"
            # Vials are resolved later (will match qc_vial_resolved); use a
            # sentinel for now so the row dicts have a stable shape.
            level_vials = {lvl: None for lvl in dil_levels_clean}
            level_vols  = {lvl: round(float(dil_base_vol) * lvl / 100.0, 3)
                           for lvl in dil_levels_clean}
        # Pool QC at the start of the block (vial resolved with the main QC)
        dilution_rows.append({"name": qcname, "vol": qc_vol,
                              "is_qc": True, "is_hela": False, "is_dil": False})
        # Each dilution level × replicates, ascending order
        for lvl in dil_levels_clean:
            dname = f"{dil_name_prefix}{lvl}"
            for _ in range(dil_replicates):
                dilution_rows.append({
                    "name":     dname,
                    "vial":     level_vials[lvl],   # may be None in "volume" mode
                    "vol":      level_vols[lvl],
                    "is_qc":    True,
                    "is_hela":  False,
                    "is_dil":   True,
                })
        # Pool QC at the end of the block
        dilution_rows.append({"name": qcname, "vol": qc_vol,
                              "is_qc": True, "is_hela": False, "is_dil": False})

    # ─── Elute / nanoElute: one vial per sample, shared by replicates ───
    # 1. Injection pool
    samples: list[str] = []
    for i in range(n_start, n_end + 1):
        base = f"{sol_prefix}-{i}" if sol_prefix else str(i)
        samples.extend([base] * replicates)

    # 2. Randomise injection order
    rng.shuffle(samples)

    # 3. Assemble the injection list with QC interleaving
    rows2: list[dict] = []
    # qcname already defined above for the dilution block; keep this assignment
    # for clarity / future-proofing (no-op if dilution block was skipped).
    qcname = qc_name or "QC"
    if qc_at_start:
        rows2.append({"name": qcname, "vol": qc_vol, "is_qc": True})
    for idx, s in enumerate(samples):
        rows2.append({"name": s, "vol": sample_vol, "is_qc": False})
        placed = idx + 1
        last = (idx == len(samples) - 1)
        if qc_every > 0 and placed % qc_every == 0 and not last:
            rows2.append({"name": qcname, "vol": qc_vol, "is_qc": True})
    if qc_at_end:
        rows2.append({"name": qcname, "vol": qc_vol, "is_qc": True})

    # 4. Assign vials: one vial per distinct sample, QCs share one fixed vial
    positions = _positions_for(instrument, init_pos)
    sample_to_vial: dict[str, str] = {}
    for i in range(n_start, n_end + 1):
        base = f"{sol_prefix}-{i}" if sol_prefix else str(i)
        try:
            sample_to_vial[base] = next(positions)
        except StopIteration:
            sample_to_vial[base] = "—"

    try:
        default_qc = next(positions)
    except StopIteration:
        default_qc = "—"
    qc_vial_resolved = (qc_vial or "").strip() or default_qc

    for r in rows2:
        if r["is_qc"]:
            r["vial"] = qc_vial_resolved
        else:
            r["vial"] = sample_to_vial.get(r["name"], "—")
        r.setdefault("is_hela", False)
        r.setdefault("is_dil", False)

    # Resolve vials for the dilution block:
    #   · Bookend pool-QCs always share the main QC vial.
    #   · "vials" mode: dilution-level rows already carry their own vials.
    #   · "volume" mode: dilution-level rows also use the main QC vial
    #     (single concentrated pool with variable injection volume).
    for r in dilution_rows:
        if not r.get("is_dil"):
            r["vial"] = qc_vial_resolved              # bookend pool-QC
        elif r.get("vial") is None:                   # "volume" mode marker
            r["vial"] = qc_vial_resolved
        r.setdefault("is_hela", False)
        r.setdefault("is_dil", False)

    # Final order: equilibration → QC-dilution block → main sequence
    return hela_rows + dilution_rows + rows2


# =============================================================================
# LAYOUT
# =============================================================================

_INSTRUMENT_OPTS = [
    {"label": " Evosep One  (6 placas · S1-A1 … S6-H12 · 576 pos.)", "value": "evosep"},
    {"label": " ELUTE  (1 … 108)",                                   "value": "elute"},
    {"label": " Bruker nanoElute 2  (Slot1:1 … Slot2:54 · 108 pos.)", "value": "nanoelute"},
]

_DEFAULT_INITPOS = {
    "evosep":    "S1-A1",
    "elute":     "1",
    "nanoelute": "Slot1:1",
}


def layout():
    form_col = html.Div(style={"flex": "0 0 48%", "minWidth": "340px"}, children=[

        _card("① Serie de muestras", [
            _lbl("Prefijo / código SOL"),
            dcc.Input(id="rnd-prefix", type="text", value="SOL2026002",
                      placeholder="SOL2026002", style=_inp_style()),
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr 1fr",
                            "gap": "10px"}, children=[
                html.Div([_lbl("Desde"),
                          dcc.Input(id="rnd-start", type="number", value=1,
                                    min=1, step=1, style=_inp_style())]),
                html.Div([_lbl("Hasta"),
                          dcc.Input(id="rnd-end", type="number", value=105,
                                    min=1, step=1, style=_inp_style())]),
                html.Div(id="rnd-replicates-wrap",
                         children=[_lbl("Réplicas (Elute/nanoElute)"),
                                   dcc.Input(id="rnd-replicates", type="number",
                                             value=3, min=1, max=20, step=1,
                                             style=_inp_style())]),
            ]),
            # Evosep-only: random duplicates via cadence (ignores "Réplicas")
            html.Div(id="rnd-dupe-wrap", style={"marginTop": "6px"}, children=[
                _lbl("Duplicados aleatorios cada X muestras "
                     "(solo Evosep · 0 = ninguno)"),
                dcc.Input(id="rnd-dupe-every", type="number", value=10,
                          min=0, step=1, style=_inp_style()),
                html.Div("En Evosep, las réplicas se sustituyen por "
                         "duplicados aleatorios: se elige 1 muestra por cada "
                         "X y se inyecta dos veces (mismo nombre, vial "
                         "distinto). El total de puntas se fuerza a par "
                         "para equilibrar la centrífuga.",
                         style={"fontSize": "10px", "color": MUTED,
                                "fontFamily": "monospace", "marginTop": "4px"}),
            ]),
        ]),

        _card("② QCs", [
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr",
                            "gap": "10px"}, children=[
                html.Div([_lbl("Nombre del QC"),
                          dcc.Input(id="rnd-qc-name", type="text", value="QC",
                                    style=_inp_style())]),
                html.Div([_lbl("Cada X inyecciones (0 = ninguno)"),
                          dcc.Input(id="rnd-qc-every", type="number", value=8,
                                    min=0, step=1, style=_inp_style())]),
            ]),
            html.Div(style={"marginTop": "10px"}, children=[
                dcc.Checklist(id="rnd-qc-endpoints",
                              options=[{"label": " QC al inicio", "value": "start"},
                                       {"label": " QC al final",  "value": "end"}],
                              value=["start", "end"],
                              inline=True,
                              labelStyle={"marginRight": "18px", "fontSize": "12px"}),
            ]),
        ]),

        _card("③ Equilibración al inicio (HeLa / estabilizadores)", [
            # Analysis-type selector — pre-fills the equilibration name with
            # HeLa (proteomics) or Stab_Metab / Stab_lipids (metab/lipid).
            # The text field remains editable so any custom label is allowed.
            _lbl("Tipo de análisis"),
            dcc.RadioItems(
                id="rnd-analysis-type",
                options=[
                    {"label": " Proteomics  (HeLa)",        "value": "proteomics"},
                    {"label": " Metabolomics  (Stab_Metab)", "value": "metabolomics"},
                    {"label": " Lipidomics  (Stab_lipids)",  "value": "lipidomics"},
                    {"label": " Custom",                      "value": "custom"},
                ],
                value="proteomics",
                inline=True,
                labelStyle={"marginRight": "14px", "fontSize": "12px"},
                style={"marginBottom": "8px"},
            ),
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr 1fr",
                            "gap": "10px"}, children=[
                html.Div([_lbl("Nº inyecciones (0 = ninguna)"),
                          dcc.Input(id="rnd-hela-count", type="number", value=10,
                                    min=0, step=1, style=_inp_style())]),
                html.Div([_lbl("Nombre del bloque"),
                          dcc.Input(id="rnd-hela-name", type="text", value="HeLa",
                                    placeholder="HeLa / Stab_Metab / Stab_lipids",
                                    style=_inp_style())]),
                html.Div(id="rnd-hela-vol-wrap",
                         children=[_lbl("Vol. inyección (µL)"),
                                   dcc.Input(id="rnd-hela-vol", type="number", value=2,
                                             min=0.1, step=0.1, style=_inp_style())]),
            ]),
            html.Div(id="rnd-hela-vial-label",
                     children="Vial del estabilizador / HeLa (reutilizado en cada inyección)",
                     style={"fontSize": "10px", "fontWeight": "600",
                            "color": MUTED, "letterSpacing": ".03em",
                            "textTransform": "uppercase",
                            "fontFamily": "monospace",
                            "marginBottom": "4px", "marginTop": "10px"}),
            dcc.Input(id="rnd-hela-vial", type="text", value="",
                      placeholder="vacío → S1-A1 (Evosep) · 108 (Elute) · "
                                  "Slot2:54 (nanoElute)",
                      style=_inp_style()),
            html.Div(id="rnd-hela-hint",
                     style={"fontSize": "10px", "color": MUTED,
                            "fontFamily": "monospace", "marginTop": "4px"}),
        ]),

        # ── ③.5 QC dilution-series block (untargeted metab/lipid only) ──
        _card("③.5 Serie de dilución QC (metabolómica / lipidómica)", [
            dcc.Checklist(
                id="rnd-dil-enable",
                options=[{"label": " Incluir bloque QC diluido (QC20–QC100)",
                          "value": "on"}],
                value=[],
                inline=True,
                labelStyle={"fontSize": "12px"},
                style={"marginBottom": "8px"},
            ),
            html.Div(id="rnd-dil-controls", children=[
                # Mode selector — choose between pre-diluted vials or
                # variable-volume injection of a single concentrated vial.
                _lbl("Modo de dilución"),
                dcc.RadioItems(
                    id="rnd-dil-mode",
                    options=[
                        {"label": " 5 viales pre-diluidos (vol. constante)",
                         "value": "vials"},
                        {"label": " 1 vial pool, volumen variable "
                                  "(QC20=20% × vol base, etc.)",
                         "value": "volume"},
                    ],
                    value="vials",
                    labelStyle={"display": "block", "fontSize": "12px",
                                "padding": "3px 0"},
                    style={"marginBottom": "10px"},
                ),
                html.Div(style={"display": "grid",
                                "gridTemplateColumns": "2fr 1fr 1fr",
                                "gap": "10px"}, children=[
                    html.Div([_lbl("Niveles de dilución (% pool, coma-separados)"),
                              dcc.Input(id="rnd-dil-levels", type="text",
                                        value="20, 40, 60, 80, 100",
                                        placeholder="ej. 20, 40, 60, 80, 100",
                                        style=_inp_style())]),
                    html.Div([_lbl("Réplicas por nivel"),
                              dcc.Input(id="rnd-dil-reps", type="number",
                                        value=1, min=0, max=10, step=1,
                                        style=_inp_style())]),
                    # In "vials" mode this is the constant injection volume
                    # for every dilution level. In "volume" mode this field
                    # is hidden — `rnd-dil-base-vol` is used instead.
                    html.Div(id="rnd-dil-vol-wrap",
                             children=[_lbl("Vol. inyección (µL)"),
                                       dcc.Input(id="rnd-dil-vol", type="number",
                                                 value=2, min=0.1, step=0.1,
                                                 style=_inp_style())]),
                ]),
                # Variable-volume mode controls (only visible in "volume" mode)
                html.Div(id="rnd-dil-base-vol-wrap",
                         style={"marginTop": "8px", "display": "none"},
                         children=[
                             _lbl("Volumen base = QC100 (µL); resto se escala "
                                  "proporcional (QC20 = 20%, QC40 = 40%, …)"),
                             dcc.Input(id="rnd-dil-base-vol", type="number",
                                       value=5, min=0.1, step=0.1,
                                       style=_inp_style()),
                         ]),
                html.Div([_lbl("Prefijo de nombre"),
                          dcc.Input(id="rnd-dil-prefix", type="text",
                                    value="QC",
                                    placeholder="QC → QC20, QC40, …",
                                    style=_inp_style())],
                         style={"marginTop": "8px"}),
                # Vial start only relevant in "vials" mode
                html.Div(id="rnd-dil-vial-wrap",
                         style={"marginTop": "8px"},
                         children=[
                             _lbl("Vial inicial de la serie de dilución"),
                             dcc.Input(id="rnd-dil-vial-start", type="text",
                                       value="",
                                       placeholder="vacío → placeholders [QC20] · "
                                                   "ej. 11 (Elute) o Slot1:50 (nanoElute)",
                                       style=_inp_style()),
                         ]),
                html.Div(id="rnd-dil-hint",
                         style={"fontSize": "10px", "color": MUTED,
                                "fontFamily": "monospace", "marginTop": "8px",
                                "lineHeight": "1.5"}),
            ]),
        ]),

        _card("④ Equipo y posición", [
            _lbl("Equipo"),
            dcc.RadioItems(id="rnd-instrument",
                           options=_INSTRUMENT_OPTS, value="nanoelute",
                           labelStyle={"display": "block", "fontSize": "12px",
                                       "padding": "5px 0"}),
            _lbl("Posición inicial de la primera muestra"),
            dcc.Input(id="rnd-initpos", type="text", value="Slot1:1",
                      style=_inp_style()),
            html.Div(id="rnd-initpos-hint",
                     style={"fontSize": "10px", "color": MUTED,
                            "fontFamily": "monospace", "marginTop": "4px"}),
            # QC vial / QC loading start position
            #  · Evosep      → primera punta donde cargar los QCs (e.g. S2-A1),
            #                  después se irán ocupando consecutivamente
            #  · Elute/nano  → vial único reutilizado por todos los QCs
            html.Div(id="rnd-qcvial-wrap", style={"marginTop": "6px"}, children=[
                html.Div(id="rnd-qcvial-label",
                         children="Vial del QC (reutilizado en cada inyección)",
                         style={"fontSize": "10px", "fontWeight": "600",
                                "color": MUTED, "letterSpacing": ".03em",
                                "textTransform": "uppercase",
                                "fontFamily": "monospace",
                                "marginBottom": "4px", "marginTop": "10px"}),
                dcc.Input(id="rnd-qcvial", type="text", value="",
                          placeholder="vacío → se usa la siguiente "
                                      "posición tras la última muestra",
                          style=_inp_style()),
            ]),
        ]),

        _card("⑤ Aleatorización · Volúmenes", [
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "1fr 1fr 1fr",
                            "gap": "10px"}, children=[
                html.Div([_lbl("Semilla (opcional)"),
                          dcc.Input(id="rnd-seed", type="number", value=42,
                                    step=1, style=_inp_style())]),
                html.Div(id="rnd-vol-samp-wrap",
                         children=[_lbl("Vol. muestra (µL)"),
                                   dcc.Input(id="rnd-vol-samp", type="number", value=2,
                                             min=0.1, step=0.1, style=_inp_style())]),
                html.Div(id="rnd-vol-qc-wrap",
                         children=[_lbl("Vol. QC (µL)"),
                                   dcc.Input(id="rnd-vol-qc", type="number", value=2,
                                             min=0.1, step=0.1, style=_inp_style())]),
            ]),
            html.Div(id="rnd-evosep-vol-note",
                     style={"display": "none",
                            "marginTop": "8px", "padding": "8px 12px",
                            "background": "#F2EFE6",
                            "border": f"1px dashed {BORDER}",
                            "borderRadius": "6px",
                            "fontSize": "11px", "color": MUTED,
                            "fontFamily": "monospace"},
                     children="Evosep: volumen fijo de 20 µL por inyección "
                              "(volumen cargado en cada Evotip). "
                              "No es configurable."),
            html.Div(style={"marginTop": "14px", "display": "flex", "gap": "10px"},
                     children=[
                html.Button("🎲  Generar lista", id="rnd-go", n_clicks=0,
                            style={"background": TEAL, "color": "#fff",
                                   "border": "none", "padding": "9px 18px",
                                   "borderRadius": "6px", "fontSize": "13px",
                                   "fontWeight": "600", "cursor": "pointer"}),
                html.Button("📥  CSV", id="rnd-dl-csv", n_clicks=0,
                            style={"background": "#fff", "color": DARK,
                                   "border": f"1px solid {BORDER}",
                                   "padding": "9px 14px", "borderRadius": "6px",
                                   "fontSize": "12px", "cursor": "pointer"}),
                html.Button("📥  TSV", id="rnd-dl-tsv", n_clicks=0,
                            style={"background": "#fff", "color": DARK,
                                   "border": f"1px solid {BORDER}",
                                   "padding": "9px 14px", "borderRadius": "6px",
                                   "fontSize": "12px", "cursor": "pointer"}),
                html.Button("📗  XLSX (WORKLOAD + WORKLIST)",
                            id="rnd-dl-xlsx", n_clicks=0,
                            style={"background": "#fff", "color": DARK,
                                   "border": f"1px solid {BORDER}",
                                   "padding": "9px 14px", "borderRadius": "6px",
                                   "fontSize": "12px", "cursor": "pointer"}),
            ]),
            dcc.Download(id="rnd-download"),
        ]),
    ])

    out_col = html.Div(style={"flex": "1", "minWidth": "340px"}, children=[
        _card("📋 Lista generada", [
            html.Div(id="rnd-summary",
                     style={"fontSize": "11px", "color": MUTED,
                            "fontFamily": "monospace", "marginBottom": "10px"}),
            _lbl("Copiar y pegar en el equipo (tab-separated)"),
            dcc.Textarea(id="rnd-textarea", value="", readOnly=True,
                         style={"width": "100%", "height": "140px",
                                "fontFamily": "monospace", "fontSize": "11px",
                                "border": f"1px solid {BORDER}",
                                "borderRadius": "6px", "padding": "8px",
                                "background": CREAM, "resize": "vertical"}),
            html.Div(style={"fontSize": "10px", "color": MUTED,
                            "fontFamily": "monospace", "marginTop": "4px"},
                     children="Selecciona todo con Ctrl+A y copia con Ctrl+C."),
            html.Div(id="rnd-table-wrap", style={"marginTop": "14px"}),
        ]),
    ])

    return html.Div(style={"padding": "1.5rem 2rem", "background": CREAM,
                           "minHeight": "100vh"}, children=[
        html.Div(style={"marginBottom": "1.5rem"}, children=[
            html.H1("Listas randomizadas",
                    style={"fontSize": "22px", "fontWeight": "600",
                           "color": DARK, "margin": "0 0 4px"}),
            html.Div("Genera una worklist aleatorizada con QCs intercalados, "
                     "lista para pegar en el software del equipo.",
                     style={"fontSize": "12px", "color": MUTED,
                            "fontFamily": "monospace"}),
        ]),
        html.Div(style={"display": "flex", "gap": "1.2rem",
                        "flexWrap": "wrap"},
                 children=[form_col, out_col]),
        dcc.Store(id="rnd-rows-store"),
    ])


# =============================================================================
# CALLBACKS
# =============================================================================

@callback(
    Output("rnd-initpos",         "value"),
    Output("rnd-initpos-hint",    "children"),
    Output("rnd-qcvial-label",    "children"),
    Output("rnd-qcvial",          "placeholder"),
    Output("rnd-hela-vial-label", "children"),
    Output("rnd-hela-hint",       "children"),
    Output("rnd-dupe-wrap",       "style"),
    Output("rnd-replicates-wrap", "style"),
    Output("rnd-qcvial-wrap",     "style"),
    Output("rnd-hela-vial",       "style"),
    Output("rnd-vol-samp-wrap",   "style"),
    Output("rnd-vol-qc-wrap",     "style"),
    Output("rnd-hela-vol-wrap",   "style"),
    Output("rnd-evosep-vol-note", "style"),
    Input("rnd-instrument",       "value"),
    State("rnd-initpos",          "value"),
    prevent_initial_call=False,
)
def _reset_initpos(instrument, current):
    """Reset the starting position + update labels/hints for the chosen
    instrument."""
    hint = {
        "evosep":    ("Posición inicial de carga de MUESTRAS. Formato: "
                      "S{1-6}-{A-H}{1-12} (Ej. S3-A1). Las muestras se "
                      "cargan en orden ascendente con réplicas contiguas; "
                      "la inyección se randomiza después."),
        "elute":     "Entero 1–108. Las réplicas comparten vial.",
        "nanoelute": ("Formato: Slot{1-2}:{1-54}. Ej. Slot1:1, Slot1:32, "
                      "Slot2:14. Las réplicas comparten vial."),
    }[instrument]
    qc_label = {
        "evosep":    "Posición inicial de carga de QCs (p. ej. S2-A1; "
                     "se ocupan consecutivamente)",
        "elute":     "Vial del QC (reutilizado en cada inyección)",
        "nanoelute": "Vial del QC (reutilizado en cada inyección)",
    }[instrument]
    qc_placeholder = {
        "evosep":    "ej. S2-A1 · vacío → continúa tras la última muestra",
        "elute":     "vacío → usa la posición tras la última muestra",
        "nanoelute": "vacío → usa la posición tras la última muestra",
    }[instrument]
    hela_label = {
        "evosep":    "Posición inicial de carga del bloque de equilibración "
                     "(HeLa / estabilizador) — p. ej. S1-A1; "
                     "cada inyección ocupa una punta consecutiva",
        "elute":     "Vial del estabilizador / HeLa (reutilizado en cada inyección)",
        "nanoelute": "Vial del estabilizador / HeLa (reutilizado en cada inyección)",
    }[instrument]
    hela_hint = {
        "evosep":    ("Cada inyección del bloque de equilibración consume una "
                      "punta distinta, cargadas desde la posición indicada "
                      "(por defecto S1-A1)."),
        "elute":     "Todas las inyecciones del bloque de equilibración "
                     "comparten el mismo vial (por defecto 108).",
        "nanoelute": "Todas las inyecciones del bloque de equilibración "
                     "comparten el mismo vial (por defecto Slot2:54).",
    }[instrument]
    matches = {
        "evosep":    _EVOSEP_RE,
        "elute":     _ELUTE_RE,
        "nanoelute": _NANO_RE,
    }[instrument]
    # Visibility: on Evosep the duplicate-cadence field is used (and the
    # per-sample "Réplicas" field + QC vial + HeLa vial fields become
    # irrelevant — everything is auto-loaded in a single balanced block).
    # On Elute/nanoElute the opposite: "Réplicas" + shared QC/HeLa vials.
    is_evo = (instrument == "evosep")
    show   = {"display": "block"}
    hide   = {"display": "none"}
    base_inp = _inp_style()
    hidden_inp = {**base_inp, "display": "none"}
    dupe_style    = show if is_evo else hide
    reps_style    = hide if is_evo else show
    qcvial_style  = hide if is_evo else show
    helavial_inp  = hidden_inp if is_evo else base_inp
    # On Evosep every tip carries a fixed 20 µL (loaded into the Evotip);
    # hide the three volume inputs and show a short note instead.
    vol_samp_style = hide if is_evo else show
    vol_qc_style   = hide if is_evo else show
    vol_hela_style = hide if is_evo else show
    note_style     = {
        "display": "block" if is_evo else "none",
        "marginTop": "8px", "padding": "8px 12px",
        "background": "#F2EFE6",
        "border": f"1px dashed {BORDER}",
        "borderRadius": "6px",
        "fontSize": "11px", "color": MUTED,
        "fontFamily": "monospace",
    }

    if current and matches.match(current):
        return (dash.no_update, hint, qc_label, qc_placeholder,
                hela_label, hela_hint,
                dupe_style, reps_style, qcvial_style, helavial_inp,
                vol_samp_style, vol_qc_style, vol_hela_style, note_style)
    return (_DEFAULT_INITPOS[instrument], hint, qc_label, qc_placeholder,
            hela_label, hela_hint,
            dupe_style, reps_style, qcvial_style, helavial_inp,
            vol_samp_style, vol_qc_style, vol_hela_style, note_style)


# ─── Auto-fill equilibration name when the analysis-type radio changes ────
# This callback only runs when the radio is touched; the text field remains
# fully editable afterwards (custom labels survive radio switches because
# we don't override an already-customised value).
_ANALYSIS_TYPE_NAMES = {
    "proteomics":    "HeLa",
    "metabolomics":  "Stab_Metab",
    "lipidomics":    "Stab_lipids",
    # custom: don't override whatever the user typed
}


# ─── Show/hide dilution-mode-specific fields + update the bottom hint ───
@callback(
    Output("rnd-dil-vol-wrap",      "style"),
    Output("rnd-dil-base-vol-wrap", "style"),
    Output("rnd-dil-vial-wrap",     "style"),
    Output("rnd-dil-hint",          "children"),
    Input("rnd-dil-mode", "value"),
    prevent_initial_call=False,
)
def _toggle_dil_mode(mode):
    base_style = {"marginTop": "8px"}
    block_show = {"display": "block", "marginTop": "8px"}
    hide       = {"display": "none"}
    if mode == "volume":
        # Volume-variable mode: single QC vial, varying injection µL
        hint = ("Modo volumen: 1 vial del pool QC, inyectando volúmenes "
                "escalados (QC20 = 20% × vol. base, …, QC100 = vol. base). "
                "Todas las inyecciones diluidas comparten el mismo vial que "
                "el pool QC. Bloque: 1 pool-QC · niveles × réplicas · 1 pool-QC.")
        return ({**_inp_style(), "display": "none"},   # rnd-dil-vol-wrap hidden
                block_show,                             # rnd-dil-base-vol-wrap visible
                hide,                                   # rnd-dil-vial-wrap hidden
                hint)
    # Default: "vials" mode
    hint = ("Modo viales: 5 viales pre-diluidos (uno por nivel), volumen "
            "constante en cada inyección. Bloque: 1 pool-QC · niveles × "
            "réplicas · 1 pool-QC. Se inserta entre la equilibración y la "
            "secuencia principal. Solo Elute / nanoElute.")
    return (block_show,             # rnd-dil-vol-wrap visible
            hide,                   # rnd-dil-base-vol-wrap hidden
            block_show,             # rnd-dil-vial-wrap visible
            hint)


@callback(
    Output("rnd-hela-name", "value"),
    Input("rnd-analysis-type", "value"),
    State("rnd-hela-name", "value"),
    prevent_initial_call=False,
)
def _autofill_hela_name(analysis_type, current):
    default_name = _ANALYSIS_TYPE_NAMES.get(analysis_type or "proteomics")
    if default_name is None:
        # custom → preserve current value (or fall back to HeLa if blank)
        return current or "HeLa"
    # If the user is on a preset type, always show the canonical name
    # (overwrites any prior custom edit — intentional, matches "preset" UX).
    return default_name


@callback(
    Output("rnd-rows-store",  "data"),
    Output("rnd-textarea",    "value"),
    Output("rnd-summary",     "children"),
    Output("rnd-table-wrap",  "children"),
    Input("rnd-go",           "n_clicks"),
    State("rnd-prefix",       "value"),
    State("rnd-start",        "value"),
    State("rnd-end",          "value"),
    State("rnd-replicates",   "value"),
    State("rnd-qc-name",      "value"),
    State("rnd-qc-every",     "value"),
    State("rnd-qc-endpoints", "value"),
    State("rnd-instrument",   "value"),
    State("rnd-initpos",      "value"),
    State("rnd-qcvial",       "value"),
    State("rnd-hela-count",   "value"),
    State("rnd-hela-name",    "value"),
    State("rnd-hela-vial",    "value"),
    State("rnd-hela-vol",     "value"),
    State("rnd-dil-enable",     "value"),
    State("rnd-dil-mode",       "value"),
    State("rnd-dil-levels",     "value"),
    State("rnd-dil-reps",       "value"),
    State("rnd-dil-prefix",     "value"),
    State("rnd-dil-vial-start", "value"),
    State("rnd-dil-vol",        "value"),
    State("rnd-dil-base-vol",   "value"),
    State("rnd-dupe-every",   "value"),
    State("rnd-seed",         "value"),
    State("rnd-vol-samp",     "value"),
    State("rnd-vol-qc",       "value"),
    prevent_initial_call=True,
)
def _generate(n, prefix, n1, n2, reps, qcname, qcevery, qcends,
              instrument, initpos, qcvial,
              helacount, helaname, helavial, helavol,
              dil_enable, dil_mode_val, dil_levels_str, dil_reps_val,
              dil_prefix_val, dil_vial_start_val,
              dil_vol_val, dil_base_vol_val,
              dupe_every,
              seed, vsamp, vqc):
    if not n:
        raise PreventUpdate

    # On Evosep every tip is loaded with a fixed 20 µL (what the Evotip
    # carries) — override whatever the UI inputs contain.
    is_evo = (instrument or "") == "evosep"
    if is_evo:
        samp_vol_val = 20.0
        qc_vol_val   = 20.0
        hela_vol_val = 20.0
    else:
        samp_vol_val = float(vsamp or 2)
        qc_vol_val   = float(vqc or 2)
        hela_vol_val = (float(helavol)
                        if helavol not in ("", None) else None)

    # Normalise the equilibration-block name: fall back to "HeLa" if blank.
    hela_name_val = (helaname or "").strip() or "HeLa"

    # Parse dilution-series controls
    dil_on = "on" in (dil_enable or [])
    dil_levels_list: list[int] = []
    if dil_levels_str:
        for tok in str(dil_levels_str).replace(";", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                dil_levels_list.append(int(float(tok)))
            except ValueError:
                pass
    dil_vol_resolved = (float(dil_vol_val)
                        if dil_vol_val not in ("", None) else None)
    dil_base_vol_resolved = (float(dil_base_vol_val)
                             if dil_base_vol_val not in ("", None) else None)
    dil_mode_norm = (dil_mode_val or "vials").strip().lower()
    if dil_mode_norm not in ("vials", "volume"):
        dil_mode_norm = "vials"

    try:
        rows = build_worklist(
            sol_prefix=prefix or "",
            n_start=int(n1 or 1),
            n_end=int(n2 or 1),
            replicates=int(reps or 1),
            qc_name=qcname or "QC",
            qc_every=int(qcevery or 0),
            qc_at_start="start" in (qcends or []),
            qc_at_end="end" in (qcends or []),
            instrument=instrument or "nanoelute",
            init_pos=initpos or _DEFAULT_INITPOS.get(instrument, "Slot1:1"),
            qc_vial=(qcvial or "").strip(),
            hela_count=int(helacount or 0),
            hela_vial=(helavial or "").strip(),
            hela_name=hela_name_val,
            hela_vol=hela_vol_val,
            dil_enabled=dil_on,
            dil_mode=dil_mode_norm,
            dil_levels=dil_levels_list,
            dil_replicates=int(dil_reps_val or 0),
            dil_name_prefix=(dil_prefix_val or "QC").strip() or "QC",
            dil_vial_start=(dil_vial_start_val or "").strip(),
            dil_vol=dil_vol_resolved,
            dil_base_vol=dil_base_vol_resolved,
            duplicate_every=int(dupe_every or 0),
            seed=int(seed) if seed not in ("", None) else None,
            sample_vol=samp_vol_val,
            qc_vol=qc_vol_val,
        )
    except Exception as e:
        return dash.no_update, "", f"⚠ Error: {e}", html.Div()

    # Tab-separated body for copy-paste
    lines = [f"{r['vial']}\t{r['name']}\t{_fmt_vol(r['vol'])}" for r in rows]
    tsv_body = "Vial\tSample Name\tInj. Vol (uL)\n" + "\n".join(lines)

    # Summary line — count dilution-block injections separately so the
    # pool-QC count reflects only the regular intercalated/bookend QCs.
    n_samples = sum(1 for r in rows
                    if not r["is_qc"] and not r.get("is_hela"))
    n_dil     = sum(1 for r in rows if r.get("is_dil"))
    n_qc_pool = sum(1 for r in rows
                    if r["is_qc"] and not r.get("is_dil"))
    n_hela    = sum(1 for r in rows if r.get("is_hela"))
    # Use the actual equilibration-block name (HeLa / Stab_Metab / Stab_lipids / ...).
    parts = [f"{len(rows)} inyecciones",
             f"{n_samples} de muestra",
             f"{n_qc_pool} QC pool"]
    if n_dil:
        parts.append(f"{n_dil} QC diluido")
    if n_hela:
        parts.append(f"{n_hela} {hela_name_val}")
    parts.append(f"equipo: {instrument}")
    summary = "  ·  ".join(parts)

    # HTML preview table
    header = html.Tr([
        html.Th("#",            style=_th()),
        html.Th("Vial",         style=_th()),
        html.Th("Sample Name",  style=_th()),
        html.Th("Inj. Vol (µL)", style=_th()),
    ])
    body_rows = []
    for i, r in enumerate(rows, 1):
        if r.get("is_hela"):
            bg = "#fff4e4"
        elif r["is_qc"]:
            bg = "#f2f9f8"
        else:
            bg = ("#ffffff" if i % 2 else "#fafaf8")
        is_bold = r["is_qc"] or r.get("is_hela", False)
        body_rows.append(html.Tr([
            html.Td(str(i),              style=_td(bg)),
            html.Td(r["vial"],           style=_td(bg)),
            html.Td(r["name"],           style=_td(bg, bold=is_bold)),
            html.Td(_fmt_vol(r["vol"]),  style=_td(bg)),
        ]))
    table = html.Table(
        [html.Thead(header), html.Tbody(body_rows)],
        style={"width": "100%", "borderCollapse": "collapse",

               "fontSize": "11px", "fontFamily": "monospace"},
    )

    return rows, tsv_body, summary, html.Div(
        table, style={"maxHeight": "500px", "overflow": "auto",
                      "border": f"1px solid {BORDER}", "borderRadius": "6px"},
    )


def _fmt_vol(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _th():
    return {"background": TEAL, "color": "#fff", "padding": "5px 8px",
            "textAlign": "left", "fontWeight": "600", "fontSize": "10px",
            "position": "sticky", "top": "0", "zIndex": 1}


def _td(bg, bold=False):
    return {"padding": "3px 8px", "borderBottom": f"1px solid {BORDER}",
            "background": bg,
            "fontWeight": "600" if bold else "400",
            "color": TEAL if bold else DARK}


# ── Downloads ─────────────────────────────────────────────────────────────────

def _row_type(r: dict) -> str:
    if r.get("is_hela"):
        return "HeLa"
    if r.get("is_qc"):
        return "QC"
    return "Sample"


def build_xlsx(rows: list[dict], instrument: str) -> bytes:
    """Generate a two-sheet workbook (WORKLOAD + WORKLIST) matching Ángela's
    manual format.

    WORKLOAD — loading plan: one row per unique physical tip/vial, sorted
              by physical loading order.
              For Evosep each injection is a unique tip (one row per
              injection). For Elute/nanoElute rows are de-duplicated so
              there is one row per *vial* (shared across replicates).

    WORKLIST — final injection list in injection order (same data as the
              CSV/TSV export).
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(
            "El módulo 'openpyxl' no está instalado en este entorno. "
            "Instálalo desde la terminal con:\n"
            "    pip install openpyxl\n"
            "(o, si usas el launcher de Windows, 'py -m pip install "
            "openpyxl') y reinicia la app."
        ) from exc

    wb = Workbook()
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", start_color="4A9B8F")
    qc_fill     = PatternFill("solid", start_color="E9F3F1")
    hela_fill   = PatternFill("solid", start_color="FFF4E4")
    center      = Alignment(horizontal="center", vertical="center")
    left        = Alignment(horizontal="left",   vertical="center")

    def _style_header(ws, n_cols):
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

    def _fill_row(ws, row_idx, kind):
        if kind == "QC":
            fill = qc_fill
        elif kind == "HeLa":
            fill = hela_fill
        else:
            return
        for c in range(1, ws.max_column + 1):
            ws.cell(row=row_idx, column=c).fill = fill

    # ── WORKLOAD sheet ───────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "WORKLOAD"
    ws1.append(["Load #", "Position (Vial)", "Type", "Name", "Inj. Vol (µL)"])
    _style_header(ws1, 5)

    # Split injection rows by type to build a deterministic loading order
    hela_inj = [r for r in rows if r.get("is_hela")]
    sample_inj = [r for r in rows
                  if not r.get("is_hela") and not r["is_qc"]]
    qc_inj = [r for r in rows if r["is_qc"]]

    if instrument == "evosep":
        # Every injection = unique tip → one load row per injection.
        # Preserve physical loading order: HeLa → QC → Samples (ascending
        # by loading plate position, which matches the ordering assigned
        # at build_worklist time).
        def _sort_key(r: dict) -> tuple:
            s, ri, col = _parse_evosep(r["vial"])
            return (s, ri, col)
        load_rows = (
            sorted(hela_inj, key=_sort_key)
            + sorted(qc_inj, key=_sort_key)
            + sorted(sample_inj, key=_sort_key)
        )
        for i, r in enumerate(load_rows, 1):
            kind = _row_type(r)
            ws1.append([i, r["vial"], kind, r["name"], _fmt_vol(r["vol"])])
            _fill_row(ws1, ws1.max_row, kind)
    else:
        # Elute / nanoElute: de-duplicate by vial.
        seen: dict[str, dict] = {}
        # Samples first (they drive the main plate layout)
        for r in sample_inj:
            seen.setdefault(r["vial"], {"kind": "Sample",
                                        "name": r["name"], "vol": r["vol"]})
        # HeLa (single shared vial)
        if hela_inj:
            h = hela_inj[0]
            seen.setdefault(h["vial"], {"kind": "HeLa",
                                        "name": h["name"], "vol": h["vol"]})
        # QC (single shared vial)
        if qc_inj:
            q = qc_inj[0]
            seen.setdefault(q["vial"], {"kind": "QC",
                                        "name": q["name"], "vol": q["vol"]})

        def _sort_key_flat(item):
            vial = item[0]
            if instrument == "elute":
                return (_parse_elute(vial),)
            slot, n = _parse_nanoelute(vial)
            return (slot, n)

        for i, (vial, info) in enumerate(
                sorted(seen.items(), key=_sort_key_flat), 1):
            ws1.append([i, vial, info["kind"], info["name"],
                        _fmt_vol(info["vol"])])
            _fill_row(ws1, ws1.max_row, info["kind"])

    # Column widths
    widths_w1 = [8, 18, 10, 28, 14]
    for i, w in enumerate(widths_w1, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w

    # ── PLATES sheet (Evosep only) ────────────────────────────────────────
    # Visual 8×12 grid for each Evosep plate that has at least one tip.
    # Mirrors Ángela's template: one grid per plate, column numbers 1–12
    # across the top, row letters A–H down the side, well contents in the
    # centre (colour-coded: QC = teal, HeLa = amber).
    if instrument == "evosep":
        ws_p = wb.create_sheet("PLATES")
        plate_hdr_font = Font(name="Calibri", size=12, bold=True,
                              color="2F5D6A")
        axis_font      = Font(name="Calibri", size=10, bold=True,
                              color="FFFFFF")
        cell_font      = Font(name="Calibri", size=9)
        pos_to_row: dict[str, dict] = {}
        for r in rows:
            v = r.get("vial", "")
            if isinstance(v, str) and v.startswith("S") and "-" in v:
                pos_to_row.setdefault(v, r)

        used_plates = sorted({_parse_evosep(v)[0] for v in pos_to_row})
        row_cursor = 1
        for plate_num in used_plates:
            # Plate title
            title_cell = ws_p.cell(row=row_cursor, column=1,
                                    value=f"S{plate_num}")
            title_cell.font = plate_hdr_font
            # Column headers (1–12)
            for c in range(1, 13):
                cell = ws_p.cell(row=row_cursor, column=c + 1, value=c)
                cell.font = axis_font
                cell.fill = header_fill
                cell.alignment = center
            # Row letters + well contents
            for ri, letter in enumerate("ABCDEFGH"):
                row_n = row_cursor + 1 + ri
                lc = ws_p.cell(row=row_n, column=1, value=letter)
                lc.font = axis_font
                lc.fill = header_fill
                lc.alignment = center
                for ci in range(12):
                    pos = f"S{plate_num}-{letter}{ci + 1}"
                    match = pos_to_row.get(pos)
                    cell = ws_p.cell(row=row_n, column=ci + 2)
                    if match is None:
                        continue
                    cell.value = match["name"]
                    cell.font = cell_font
                    cell.alignment = center
                    kind = _row_type(match)
                    if kind == "HeLa":
                        cell.fill = hela_fill
                    elif kind == "QC":
                        cell.fill = qc_fill
            # 9 rows consumed (title + 8 wells) + 1 blank spacer
            row_cursor += 10

        # Column widths — narrow row-header col, wider wells
        ws_p.column_dimensions["A"].width = 6
        for c in range(2, 14):
            ws_p.column_dimensions[get_column_letter(c)].width = 16

    # ── WORKLIST sheet ───────────────────────────────────────────────────
    ws2 = wb.create_sheet("WORKLIST")
    ws2.append(["#", "Vial", "Sample Name", "Inj. Vol (µL)", "Type"])
    _style_header(ws2, 5)
    for i, r in enumerate(rows, 1):
        kind = _row_type(r)
        ws2.append([i, r["vial"], r["name"], _fmt_vol(r["vol"]), kind])
        _fill_row(ws2, ws2.max_row, kind)
    widths_w2 = [6, 14, 28, 14, 10]
    for i, w in enumerate(widths_w2, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    # Freeze header rows
    ws1.freeze_panes = "A2"
    ws2.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@callback(
    Output("rnd-download",  "data"),
    Input("rnd-dl-csv",     "n_clicks"),
    Input("rnd-dl-tsv",     "n_clicks"),
    Input("rnd-dl-xlsx",    "n_clicks"),
    State("rnd-rows-store", "data"),
    State("rnd-instrument", "value"),
    prevent_initial_call=True,
)
def _download(n_csv, n_tsv, n_xlsx, rows, instrument):
    # Fallback to triggered[0] if triggered_id isn't populated
    ctx = dash.callback_context
    trigger = ctx.triggered_id
    if trigger is None and ctx.triggered:
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if not rows or trigger not in (
            "rnd-dl-csv", "rnd-dl-tsv", "rnd-dl-xlsx"):
        raise PreventUpdate

    if trigger == "rnd-dl-xlsx":
        try:
            payload = build_xlsx(rows, instrument)
        except RuntimeError as exc:
            # openpyxl not installed in this environment — download a
            # plain-text explanation instead of crashing the callback.
            fname = "randomized_worklist_README.txt"
            return dict(content=str(exc), filename=fname)
        fname = f"randomized_worklist_{instrument}.xlsx"
        # dcc.send_bytes — recommended helper for binary downloads
        # (matches the pattern used in proteomics.py).
        return dcc.send_bytes(payload, fname)

    sep = "," if trigger == "rnd-dl-csv" else "\t"
    ext = "csv" if trigger == "rnd-dl-csv" else "tsv"
    buf = io.StringIO()
    buf.write(sep.join(["#", "Vial", "Sample Name", "Inj. Vol (uL)",
                        "Type"]) + "\n")
    for i, r in enumerate(rows, 1):
        buf.write(sep.join([str(i), str(r["vial"]), str(r["name"]),
                            _fmt_vol(r["vol"]), _row_type(r)]) + "\n")
    fname = f"randomized_worklist_{instrument}.{ext}"
    return dict(content=buf.getvalue(), filename=fname)
