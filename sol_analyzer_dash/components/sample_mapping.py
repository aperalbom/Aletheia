"""
components/sample_mapping.py

Sample-Mapping editor: a Dash component that lets the user refine the
auto-classification produced by any loader before launching the QC pipeline.

Public API
----------
* :func:`layout(ds)` — return the Dash layout for the editable table.
* :func:`extract_records(table_rows)` — convert the table's ``data`` back
  into a list of :class:`SampleRecord` instances ready for
  :func:`core.loaders.mapping_io.apply_mapping`.

Integration (in pages/sol_analyzer.py)
--------------------------------------
1. After ``load(path)`` returns a ``ParsedDataset``, store it in a
   ``dcc.Store(id='sm-store')``.
2. Render ``sample_mapping.layout(ds)`` inside the page.
3. On click "Save mapping", call ``extract_records(...)`` and persist via
   :func:`core.loaders.mapping_io.save_mapping_json`.
4. On click "Continue", call :func:`core.loaders.mapping_io.apply_mapping`
   and proceed with ``ds.to_legacy_dict()`` → ``run_m1``.

Styling matches the IMSMI palette (good=#4A9B8F, slate=#6A7FA8,
amber=#E8A838, bad=#C0756A, dim=#888780).
"""

from __future__ import annotations

from typing import Any

from dash import dash_table, dcc, html

from sol_analyzer_dash.core.schema import (
    ParsedDataset, SampleRecord,
    ROLE_SAMPLE, ROLE_QC_POOL, ROLE_QC_DIL, ROLE_BLANK, ROLE_EXCLUDE,
    VALID_ROLES,
)


_ROLE_OPTIONS = [
    {"label": "Sample",       "value": ROLE_SAMPLE},
    {"label": "QC pool",      "value": ROLE_QC_POOL},
    {"label": "QC dilution",  "value": ROLE_QC_DIL},
    {"label": "Blank",        "value": ROLE_BLANK},
    {"label": "Exclude",      "value": ROLE_EXCLUDE},
]


def _record_to_row(r: SampleRecord) -> dict[str, Any]:
    return {
        "column_name":    r.column_name,
        "sample_id":      r.sample_id,
        "replicate_num":  int(r.replicate_num),
        "role":           r.role,
        "dilution_level": (int(r.dilution_level)
                            if r.dilution_level is not None else None),
    }


def _row_to_record(row: dict[str, Any]) -> SampleRecord:
    role = row.get("role") or ROLE_SAMPLE
    if role not in VALID_ROLES:
        role = ROLE_SAMPLE
    dil = row.get("dilution_level")
    try:
        dil = int(dil) if dil not in (None, "") else None
    except (TypeError, ValueError):
        dil = None
    if role != ROLE_QC_DIL:
        dil = None
    # qc_dil requires a dilution_level by SampleRecord.__post_init__.
    if role == ROLE_QC_DIL and dil is None:
        dil = 100   # safe default; user can override
    try:
        rep = int(row.get("replicate_num", 1))
    except (TypeError, ValueError):
        rep = 1
    return SampleRecord(
        column_name=str(row["column_name"]),
        sample_id=str(row.get("sample_id", row["column_name"])).strip() or str(row["column_name"]),
        replicate_num=rep,
        role=role,
        dilution_level=dil,
    )


def extract_records(table_rows: list[dict[str, Any]]) -> list[SampleRecord]:
    """Convert the editable table's ``data`` payload into SampleRecord list."""
    return [_row_to_record(r) for r in table_rows]


# ----------------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------------

PAL = dict(good="#4A9B8F", slate="#6A7FA8", amber="#E8A838",
           bad="#C0756A", dim="#888780", neutral="#2C2C2A",
           bg="#F7F6F2", border="#E4E2DC")


def _card(title: str, *children) -> html.Div:
    return html.Div(
        style={"background": "#FFFFFF", "border": f"1px solid {PAL['border']}",
               "borderRadius": "10px", "padding": "1.2rem",
               "marginBottom": "1rem"},
        children=[
            html.Div(title, style={"fontSize": "12px", "fontWeight": "600",
                                    "letterSpacing": ".08em",
                                    "textTransform": "uppercase",
                                    "color": PAL["dim"],
                                    "marginBottom": ".8rem",
                                    "fontFamily": "monospace"}),
            *children,
        ],
    )


def layout(ds: ParsedDataset, *, table_id: str = "sm-table",
           summary_id: str = "sm-summary") -> html.Div:
    """Return a Dash layout for the sample-mapping editor.

    The caller is expected to wire callbacks on:
    * Input(table_id, 'data')    — fires on every cell edit
    * Output(summary_id, 'children') — live counts per role
    * State(table_id, 'data')    — read for save/continue actions
    """
    rows = [_record_to_row(r) for r in ds.samples]
    counts = _summarise(rows)

    columns = [
        {"name": "Column name",  "id": "column_name",   "editable": False,
         "type": "text"},
        {"name": "Sample ID",    "id": "sample_id",     "editable": True,
         "type": "text"},
        {"name": "Replicate #",  "id": "replicate_num", "editable": True,
         "type": "numeric"},
        {"name": "Role",         "id": "role",          "editable": True,
         "presentation": "dropdown"},
        {"name": "Dilution %",   "id": "dilution_level","editable": True,
         "type": "numeric"},
    ]

    return html.Div([
        _card(
            f"Sample mapping — source format: {ds.source_format} · "
            f"{len(ds.samples)} columns",
            html.Div(
                f"Auto-classification is a starting point only. Refine roles "
                f"and dilution levels below; click Save mapping to persist "
                f"the choices as a sidecar JSON.",
                style={"fontSize": "12px", "color": PAL["dim"],
                       "marginBottom": ".8rem", "lineHeight": "1.5"},
            ),
            html.Div(id=summary_id, style={"marginBottom": ".6rem"},
                     children=_render_summary(counts)),
            dash_table.DataTable(
                id=table_id,
                columns=columns,
                data=rows,
                editable=True,
                row_deletable=False,
                page_action="native",
                page_size=20,
                sort_action="native",
                filter_action="native",
                style_table={"overflowX": "auto",
                              "border": f"1px solid {PAL['border']}",
                              "borderRadius": "6px"},
                style_cell={"fontFamily": "monospace", "fontSize": "11px",
                             "padding": "6px 10px", "textAlign": "left",
                             "color": PAL["neutral"]},
                style_header={"background": PAL["bg"], "fontWeight": "600",
                               "color": PAL["neutral"],
                               "border": f"1px solid {PAL['border']}"},
                style_data_conditional=[
                    {"if": {"filter_query": '{role} = "qc_pool"'},
                     "backgroundColor": "rgba(74,155,143,0.08)"},
                    {"if": {"filter_query": '{role} = "qc_dil"'},
                     "backgroundColor": "rgba(106,127,168,0.08)"},
                    {"if": {"filter_query": '{role} = "blank"'},
                     "backgroundColor": "rgba(232,168,56,0.08)"},
                    {"if": {"filter_query": '{role} = "exclude"'},
                     "backgroundColor": "rgba(192,117,106,0.08)",
                     "color": PAL["dim"]},
                ],
                dropdown={"role": {"options": _ROLE_OPTIONS}},
            ),
        ),
    ])


def _summarise(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        role = r.get("role", ROLE_SAMPLE)
        counts[role] = counts.get(role, 0) + 1
    return counts


def _render_summary(counts: dict[str, int]) -> list:
    chips = []
    label_for = {ROLE_SAMPLE: "Sample", ROLE_QC_POOL: "QC pool",
                 ROLE_QC_DIL: "QC dil", ROLE_BLANK: "Blank",
                 ROLE_EXCLUDE: "Exclude"}
    color_for = {ROLE_SAMPLE: PAL["neutral"], ROLE_QC_POOL: PAL["good"],
                 ROLE_QC_DIL: PAL["slate"], ROLE_BLANK: PAL["amber"],
                 ROLE_EXCLUDE: PAL["bad"]}
    for role in (ROLE_SAMPLE, ROLE_QC_POOL, ROLE_QC_DIL,
                  ROLE_BLANK, ROLE_EXCLUDE):
        n = counts.get(role, 0)
        if n == 0:
            continue
        chips.append(html.Span(
            f"{label_for[role]}: {n}",
            style={"display": "inline-block", "marginRight": "8px",
                   "padding": "4px 10px",
                   "fontSize": "11px", "fontWeight": "600",
                   "fontFamily": "monospace",
                   "color": color_for[role],
                   "border": f"1px solid {color_for[role]}",
                   "borderRadius": "12px",
                   "background": "rgba(255,255,255,0.6)"}))
    return chips


def render_summary(rows: list[dict[str, Any]]) -> list:
    """Public wrapper for callbacks: counts → chip list."""
    return _render_summary(_summarise(rows))
