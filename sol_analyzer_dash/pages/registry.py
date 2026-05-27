"""
pages/registry.py — Registro Interno de Solicitudes
Control interno por año: usuario, servicio, muestras, tipo de muestra.
Lee data/sample_history.json (mismo fichero que usa el histórico de informes).
"""

import dash
from dash import html, dcc, Input, Output, callback
from datetime import datetime
from pathlib import Path

dash.register_page(__name__, path="/registry", name="Registro Interno")

# ── reuse history module ──────────────────────────────────────────────────────
from sol_analyzer_dash.core import sample_history as _sh

# ── colores (idénticos al resto de la app) ────────────────────────────────────
TEAL  = "#4A9B8F"
DARK  = "#2C2C2A"
CREAM = "#F7F6F2"
MUTED = "#888780"
BORDER= "#E4E2DC"
AMBER = "#E8A838"
CORAL = "#C0756A"
SLATE = "#6A7FA8"

SERVICE_COLORS = {
    "proteomics":   TEAL,
    "metabolomics": AMBER,
    "lipidomics":   SLATE,
}
SERVICE_ICONS = {"proteomics": "🔬", "metabolomics": "🧪", "lipidomics": "💧"}


# =============================================================================
# HELPERS
# =============================================================================

def _all_entries():
    """Flatten history JSON into a list of dicts, sorted newest-first."""
    hist = _sh._read()
    rows = []
    for user_key, sol_dict in hist.items():
        for sol, e in sol_dict.items():
            rows.append({
                "user":    user_key,
                "sol":     e.get("sol", sol),
                "service": e.get("service", ""),
                "nsamp":   e.get("nsamp", ""),
                "scat":    _sh.CAT_LABELS.get(e.get("scat",""), e.get("scat","")),
                "ssub":    e.get("ssub", ""),
                "sorg":    e.get("sorg", ""),
                "date":    e.get("last_generated", "")[:10],
                "year":    e.get("last_generated", "")[:4],
            })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def _kpi(label, value, sub, color):
    return html.Div(style={
        "background":"#fff","border":f"1px solid {BORDER}","borderRadius":"8px",
        "padding":"14px 18px 10px","borderTop":f"3px solid {color}",
    }, children=[
        html.Div(label, style={"fontSize":"9px","fontWeight":"700","color":MUTED,
                               "textTransform":"uppercase","letterSpacing":".12em",
                               "marginBottom":"4px","fontFamily":"monospace"}),
        html.Div(str(value), style={"fontSize":"28px","fontWeight":"700",
                                    "color":DARK,"lineHeight":"1"}),
        html.Div(sub, style={"fontSize":"10px","color":MUTED,"marginTop":"3px"}),
    ])


def _badge(service):
    color = SERVICE_COLORS.get(service, MUTED)
    icon  = SERVICE_ICONS.get(service, "📋")
    label = service.capitalize()
    return html.Span(f"{icon} {label}", style={
        "background": color + "22",
        "color": color,
        "border": f"1px solid {color}55",
        "borderRadius": "4px",
        "padding": "2px 8px",
        "fontSize": "10px",
        "fontWeight": "600",
        "fontFamily": "monospace",
        "whiteSpace": "nowrap",
    })


# =============================================================================
# LAYOUT
# =============================================================================

def layout():
    current_year = str(datetime.now().year)

    return html.Div([
        html.Div(className="page-header", children=[
            html.H1("Registro Interno de Solicitudes", className="page-title"),
            html.P("Control interno · IMSMI · ECAI · IMIBIC",
                   className="page-sub"),
        ]),

        # ── Filtros ────────────────────────────────────────────────────
        html.Div(style={
            "display":"flex","gap":"12px","alignItems":"center",
            "flexWrap":"wrap","marginBottom":"1.2rem",
        }, children=[
            html.Div([
                html.Div("Año", style={"fontSize":"9px","fontWeight":"700","color":MUTED,
                                       "textTransform":"uppercase","fontFamily":"monospace",
                                       "marginBottom":"3px","letterSpacing":".07em"}),
                dcc.Dropdown(
                    id="reg-year",
                    options=[{"label": "Todos los años", "value": "all"}],
                    value=current_year,
                    clearable=False,
                    style={"width":"160px","fontSize":"12px","fontFamily":"monospace"},
                ),
            ]),
            html.Div([
                html.Div("Servicio", style={"fontSize":"9px","fontWeight":"700","color":MUTED,
                                            "textTransform":"uppercase","fontFamily":"monospace",
                                            "marginBottom":"3px","letterSpacing":".07em"}),
                dcc.Dropdown(
                    id="reg-service",
                    options=[
                        {"label": "Todos los servicios", "value": "all"},
                        {"label": "🔬 Proteómica",       "value": "proteomics"},
                        {"label": "🧪 Metabolómica",      "value": "metabolomics"},
                        {"label": "💧 Lipidómica",        "value": "lipidomics"},
                    ],
                    value="all",
                    clearable=False,
                    style={"width":"200px","fontSize":"12px","fontFamily":"monospace"},
                ),
            ]),
            html.Button("↻ Actualizar", id="reg-refresh",
                        style={
                            "background":"transparent","color":TEAL,
                            "border":f"1px solid {TEAL}","borderRadius":"6px",
                            "fontSize":"11px","fontWeight":"600","padding":"6px 14px",
                            "cursor":"pointer","fontFamily":"monospace",
                            "marginTop":"16px",
                        }),
        ]),

        # ── KPIs ───────────────────────────────────────────────────────
        html.Div(id="reg-kpis", style={
            "display":"grid","gridTemplateColumns":"repeat(4,1fr)",
            "gap":"1rem","marginBottom":"1.5rem",
        }),

        # ── Tabla ──────────────────────────────────────────────────────
        html.Div(id="reg-table"),
    ])


# =============================================================================
# CALLBACK — RENDER KPIs + TABLE
# =============================================================================

@callback(
    Output("reg-kpis",    "children"),
    Output("reg-table",   "children"),
    Output("reg-year",    "options"),
    Input("reg-year",     "value"),
    Input("reg-service",  "value"),
    Input("reg-refresh",  "n_clicks"),
)
def _render(year_filter, svc_filter, _refresh):
    rows = _all_entries()

    # Collect available years for the dropdown
    years_found = sorted({r["year"] for r in rows if r["year"]}, reverse=True)
    year_opts   = [{"label": "Todos los años", "value": "all"}] + \
                  [{"label": y, "value": y} for y in years_found]

    # Apply filters
    filtered = rows
    if year_filter and year_filter != "all":
        filtered = [r for r in filtered if r["year"] == year_filter]
    if svc_filter and svc_filter != "all":
        filtered = [r for r in filtered if r["service"] == svc_filter]

    # ── KPIs ──────────────────────────────────────────────────────────
    total_sol  = len(filtered)
    total_samp = 0
    for r in filtered:
        try:    total_samp += int(r["nsamp"])
        except: pass

    prot_n  = sum(1 for r in filtered if r["service"] == "proteomics")
    metab_n = sum(1 for r in filtered if r["service"] == "metabolomics")
    lipid_n = sum(1 for r in filtered if r["service"] == "lipidomics")
    svc_breakdown = f"🔬 {prot_n}  🧪 {metab_n}  💧 {lipid_n}"

    kpis = [
        _kpi("Solicitudes",    total_sol,   "en el período seleccionado", TEAL),
        _kpi("Muestras totales", f"{total_samp:,}".replace(",","\u202f"),
             "suma del período", SLATE),
        _kpi("Servicios activos",
             len({r["service"] for r in filtered if r["service"]}),
             svc_breakdown, AMBER),
        _kpi("Usuarios únicos",
             len({r["user"] for r in filtered}),
             "en el período", CORAL),
    ]

    # ── Table ─────────────────────────────────────────────────────────
    if not filtered:
        table = html.Div(
            "No hay registros para los filtros seleccionados. Los registros se crean automáticamente al generar un informe.",
            style={"padding":"2rem","textAlign":"center","color":MUTED,
                   "fontFamily":"monospace","fontSize":"12px",
                   "background":"#fff","border":f"1px solid {BORDER}",
                   "borderRadius":"8px"},
        )
        return kpis, table, year_opts

    COLS = [
        ("Fecha",       "date"),
        ("Solicitud",   "sol"),
        ("Usuario",     "user"),
        ("Servicio",    "service"),
        ("N.º muestras","nsamp"),
        ("Categoría",   "scat"),
        ("Sub-tipo",    "ssub"),
        ("Organismo",   "sorg"),
    ]

    th_style = {
        "padding":"8px 12px","background":DARK,"color":"#fff",
        "fontSize":"9px","fontWeight":"700","letterSpacing":".1em",
        "textTransform":"uppercase","fontFamily":"monospace",
        "whiteSpace":"nowrap","textAlign":"left",
    }
    td_style = {
        "padding":"7px 12px","fontSize":"11px","fontFamily":"monospace",
        "borderBottom":f"1px solid {BORDER}","color":DARK,"whiteSpace":"nowrap",
    }

    def _cell(col_key, value):
        if col_key == "service":
            return html.Td(_badge(value), style={**td_style, "padding":"5px 10px"})
        if col_key == "nsamp":
            return html.Td(value or "—", style={**td_style, "textAlign":"right",
                                                 "fontWeight":"600","color":TEAL})
        if col_key == "sol":
            return html.Td(value, style={**td_style, "fontWeight":"700"})
        return html.Td(value or "—", style=td_style)

    header = html.Thead(html.Tr([html.Th(label, style=th_style) for label, _ in COLS]))
    body_rows = []
    for i, r in enumerate(filtered):
        bg = "#F7F6F2" if i % 2 == 1 else "#fff"
        body_rows.append(html.Tr(
            [_cell(k, r.get(k, "")) for _, k in COLS],
            style={"background": bg},
        ))

    table = html.Div(style={"overflowX":"auto","borderRadius":"8px",
                            "border":f"1px solid {BORDER}","background":"#fff"}, children=[
        html.Table(
            [header, html.Tbody(body_rows)],
            style={"width":"100%","borderCollapse":"collapse"},
        ),
        html.Div(
            f"{len(filtered)} registro{'s' if len(filtered)!=1 else ''}",
            style={"padding":"8px 12px","fontSize":"10px","color":MUTED,
                   "fontFamily":"monospace","borderTop":f"1px solid {BORDER}"},
        ),
    ])

    return kpis, table, year_opts
