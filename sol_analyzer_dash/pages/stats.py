"""
pages/stats.py — Análisis estadístico básico
============================================

Módulo de análisis estadístico downstream que consume:

* el **CSV agregado** generado por Aletheia (``experiment_aggregated.csv``
  o ``pass_all_criteria.csv``), una columna por muestra biológica.
* la **plantilla IMIBIC de envío de muestras** (Excel) que rellena el
  usuario, de la cual se extraen los grupos (columna ``Condition``) y la
  correspondencia ``Sample name`` ↔ ``# IMSMI``.

UI (tabs):

  ① Carga ⇒ ② Preprocesado ⇒ ③ Univariante ⇒ ④ Multivariante (PCA / PLS-DA)
  ⇒ ⑤ Heatmap ⇒ ⑥ Biomarcadores ⇒ ⑦ Informe (DOCX/PDF)

Estado en cache (servidor): un único dict con todo lo necesario para
re-renderizar las pestañas. Las descargas grandes salen por endpoints de
``app.py`` (``/dl_stats/...``) — todo persistido vía
:mod:`core.cache`.
"""
from __future__ import annotations

import base64, io, tempfile, os, time, traceback as _traceback

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import dash
from dash import dcc, html, Input, Output, State, callback, dash_table, ctx
from dash.exceptions import PreventUpdate

from sol_analyzer_dash.core.cache import save as csave, load as cload
from sol_analyzer_dash.core import stats_parser as sp
from sol_analyzer_dash.core.stats_preprocess import preprocess, PreprocessConfig
from sol_analyzer_dash.core.stats_univariate import (two_group_test, multi_group_test,
                                     volcano_data)
from sol_analyzer_dash.core.stats_multivariate import run_pca, run_plsda
from sol_analyzer_dash.core.stats_biomarker import biomarker_table

dash.register_page(__name__, path="/stats", name="Estadística")

# =============================================================================
# Style palette (matches sol_analyzer)
# =============================================================================

PAL = dict(
    teal="#4A9B8F", coral="#C0756A", amber="#E8A838", slate="#6A7FA8",
    dark="#2C2C2A", muted="#888780", border="#E4E2DC", cream="#F7F6F2",
)
SPAL = ["#4A9B8F", "#6A7FA8", "#E8A838", "#C0756A", "#B0A89A",
        "#5DCAA5", "#185FA5", "#EF9F27", "#D85A30", "#888780"]
P_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFAF8",
                 font=dict(family="Inter,sans-serif", size=11, color=PAL["dark"]),
                 margin=dict(l=44, r=16, t=36, b=40),
                 legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0))


def _hex2rgba(hex_str: str, alpha: float = 1.0) -> str:
    """Convert "#RRGGBB" → "rgba(r,g,b,a)" — Plotly does not accept 8-char hex."""
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"


def _card(*children, title=None):
    inner = ([html.Div(title, className="card-title")] if title else []) + list(children)
    return html.Div(className="card", children=inner)


def _config_label(text):
    return html.Div(text, style={
        "fontSize": "9px", "fontWeight": "700", "color": PAL["muted"],
        "textTransform": "uppercase", "fontFamily": "monospace",
        "marginBottom": "4px", "letterSpacing": ".07em",
    })


def _help(text):
    """Small greyed-out help text that sits under a control."""
    return html.Div(text, style={
        "fontSize": "10px", "color": PAL["muted"], "marginTop": "6px",
        "lineHeight": "1.35", "fontFamily": "Inter,sans-serif",
    })


def _section_help(text, kind="info"):
    """Box of recommendations / context at the top of a tab."""
    color = {"info": PAL["slate"], "warn": PAL["amber"],
             "ok":   PAL["teal"],  "note": PAL["muted"]}[kind]
    return html.Div(text, style={
        "padding": "10px 14px", "background": color + "10",
        "border": f"1px dashed {color}55", "borderRadius": "6px",
        "color": PAL["dark"], "fontSize": "11px",
        "fontFamily": "Inter,sans-serif",
        "lineHeight": "1.5", "marginBottom": "14px",
    })


def _btn(label, **kw):
    base = {
        "background": PAL["teal"], "color": "white", "border": "none",
        "borderRadius": "6px", "padding": "8px 16px", "cursor": "pointer",
        "fontFamily": "monospace", "fontSize": "11px", "fontWeight": "600",
        "letterSpacing": ".05em",
    }
    base.update(kw.pop("style", {}))
    return html.Button(label, style=base, **kw)


def _info(msg, kind="info"):
    color = {"info": PAL["slate"], "warn": PAL["amber"], "err": PAL["coral"],
             "ok": PAL["teal"]}[kind]
    return html.Div(msg, style={
        "padding": "10px 14px", "background": color + "15",
        "border": f"1px solid {color}55", "borderRadius": "6px",
        "color": color, "fontSize": "12px", "fontFamily": "monospace",
    })


def _need_form_info():
    """Shared warning shown in every downstream tab when the IMIBIC template
    (with Condition metadata) hasn't been uploaded yet."""
    return _info(
        html.Div([
            html.Strong("Falta la plantilla IMIBIC. "),
            "Este análisis necesita saber a qué grupo pertenece cada muestra. "
            "Sube el Excel de envío de muestras en la pestaña ① (tiene que "
            "incluir la columna 'Condition'). Sin ella, el módulo estadístico "
            "no puede comparar grupos ni generar informe.",
        ]), "warn")


def _err_panel(e):
    """Render any exception as a visible card (with collapsible traceback)
    so callback failures don't end up as silent 500s."""
    tb = _traceback.format_exc()
    return html.Div([
        html.Div(f"⚠ Error: {type(e).__name__}: {e}", style={
            "padding": "10px 14px", "background": PAL["coral"] + "15",
            "border": f"1px solid {PAL['coral']}55", "borderRadius": "6px",
            "color": PAL["coral"], "fontSize": "12px",
            "fontFamily": "monospace", "marginBottom": "6px",
        }),
        html.Details([
            html.Summary("Ver traceback completo", style={
                "cursor": "pointer", "fontSize": "10px",
                "fontFamily": "monospace", "color": PAL["muted"],
                "padding": "4px 0",
            }),
            html.Pre(tb, style={
                "fontSize": "10px", "fontFamily": "monospace",
                "background": "#FAFAF8", "padding": "10px",
                "border": f"1px solid {PAL['border']}",
                "borderRadius": "6px", "overflow": "auto",
                "maxHeight": "340px", "whiteSpace": "pre-wrap",
            }),
        ]),
    ])


# =============================================================================
# Layout
# =============================================================================

def layout():
    return html.Div([
        dcc.Store(id="stats-key"),
        dcc.Store(id="stats-pp-key"),
        dcc.Store(id="stats-uni-key"),
        dcc.Store(id="stats-pca-key"),
        dcc.Store(id="stats-pls-key"),
        dcc.Store(id="stats-bm-key"),

        html.Div(className="page-header", children=[
            html.H1("Análisis estadístico", className="page-title"),
            html.P("Univariante · PCA · PLS-DA · Heatmap · Biomarcadores",
                   className="page-sub"),
        ]),

        dcc.Tabs(id="stats-tabs", value="tab-load", children=[
            dcc.Tab(label="① Carga",          value="tab-load"),
            dcc.Tab(label="② Preprocesado",   value="tab-pp"),
            dcc.Tab(label="③ Univariante",    value="tab-uni"),
            dcc.Tab(label="④ Multivariante",  value="tab-mv"),
            dcc.Tab(label="⑤ Heatmap",        value="tab-hm"),
            dcc.Tab(label="⑥ Biomarcadores",  value="tab-bm"),
            dcc.Tab(label="⑦ Informe",        value="tab-rep"),
        ]),

        html.Div(id="stats-content", style={"marginTop": "1.2rem"}),
    ])


# =============================================================================
# Tab: ① Load
# =============================================================================

def _tab_load(d):
    has_form = bool(d and d.get("form"))
    has_agg  = bool(d and d.get("data_agg_cols"))
    has_pass = bool(d and d.get("data_pass_labels"))
    has_data = bool(d and d.get("data_columns"))
    active   = d.get("active_dataset", "agg") if d else "agg"

    def _tag(filename, features, samples):
        return html.Div([
            html.Strong(filename, style={"color": PAL["teal"]}),
            html.Span(f" · {features} features × {samples} muestras",
                      style={"color": PAL["muted"], "marginLeft": "8px"}),
        ], style={"fontSize": "11px", "fontFamily": "monospace",
                  "padding": "6px 8px"})

    children = [
        _card(
            dcc.Upload(
                id="stats-upload-form", multiple=False,
                children=html.Div([
                    html.Div("📋", style={"fontSize": "1.6rem", "marginBottom": ".3rem"}),
                    html.Div("Plantilla IMIBIC (.xlsx)", className="upload-title"),
                    html.Div("Sample submission form — incluye grupos en col. D",
                             className="upload-sub"),
                ]), className="upload-zone",
            ),
            html.Div(id="stats-form-info",
                     children=(_tag(d["form"]["filename"], "", d["form"]["n_samples"])
                               if has_form else None)),
            title="① a · Plantilla de envío de muestras",
        ),

        _card(
            html.Div(style={"display": "grid",
                              "gridTemplateColumns": "1fr 1fr",
                              "gap": "14px"}, children=[
                # ── experiment_aggregated ─────────────────────────────────
                html.Div([
                    dcc.Upload(
                        id="stats-upload-agg", multiple=False,
                        children=html.Div([
                            html.Div("📊", style={"fontSize": "1.5rem",
                                                    "marginBottom": ".3rem"}),
                            html.Div("experiment_aggregated.csv",
                                      className="upload-title"),
                            html.Div("todas las features (sin filtro CV)",
                                      className="upload-sub"),
                        ]), className="upload-zone",
                    ),
                    html.Div(id="stats-agg-info",
                             children=(_tag(d["data_agg_fname"],
                                            d["data_agg_df"].shape[0],
                                            d["data_agg_df"].shape[1])
                                       if has_agg else None)),
                ]),
                # ── pass_all_criteria ─────────────────────────────────────
                html.Div([
                    dcc.Upload(
                        id="stats-upload-pass", multiple=False,
                        children=html.Div([
                            html.Div("✅", style={"fontSize": "1.5rem",
                                                    "marginBottom": ".3rem"}),
                            html.Div("pass_all_criteria.csv",
                                      className="upload-title"),
                            html.Div("filtradas (linealidad + CV)",
                                      className="upload-sub"),
                        ]), className="upload-zone",
                    ),
                    html.Div(id="stats-pass-info",
                             children=(html.Div([
                                        html.Strong(d["data_pass_fname"],
                                                    style={"color": PAL["teal"]}),
                                        html.Span(
                                            f" · {d.get('data_pass_count', 0)}/"
                                            f"{d.get('data_pass_total', 0)} "
                                            f"features pasan filtro",
                                            style={"color": PAL["muted"],
                                                   "marginLeft": "8px"}),
                                     ], style={"fontSize": "11px",
                                               "fontFamily": "monospace",
                                               "padding": "6px 8px"})
                                       if has_pass else None)),
                ]),
            ]),
            # ── Dataset selector ─────────────────────────────────────────
            html.Div(style={"marginTop": "14px",
                              "padding": "10px 14px",
                              "background": PAL["cream"],
                              "borderRadius": "6px"}, children=[
                _config_label("Dataset a usar en el análisis"),
                dcc.RadioItems(
                    id="stats-active-dataset", value=active,
                    options=[
                        {"label": " Todas las features (aggregated)",
                         "value": "agg",
                         "disabled": not has_agg},
                        {"label": " Solo las filtradas por pass_all_criteria",
                         "value": "pass",
                         "disabled": not (has_agg and has_pass)},
                    ],
                    style={"fontSize": "12px", "display": "flex", "gap": "18px"},
                ),
                html.Div(
                    "pass_all_criteria.csv se usa como filtro de filas sobre "
                    "experiment_aggregated: nos quedamos solo con las features "
                    "que pasan linealidad (ok=True) y CV. "
                    "Si subes solo uno de los dos, el selector queda fijado "
                    "en 'aggregated'.",
                    style={"fontSize": "10px", "color": PAL["muted"],
                             "marginTop": "6px", "fontFamily": "Inter,sans-serif"}),
            ]),
            title="① b · Datos cuantitativos",
        ),
    ]

    # ── Preview ─────────────────────────────────────────────────────────
    if has_form and has_data:
        form = d["form"]
        rename = d["rename_map"]
        unmatched = d["unmatched_data"] + [f"S{i}" for i in d["unmatched_samples"]]
        preview = pd.DataFrame({
            "Columna en datos": list(rename.keys()),
            "Sample name":      list(rename.values()),
            "Condition":        [form["sample_to_cond"].get(rename[k], "—")
                                   for k in rename],
        })

        children.append(_card(
            html.Div([
                _info(
                    f"✓ {len(rename)} columnas emparejadas · "
                    f"{len(form['conditions'])} condiciones · "
                    + ("diseño factorial detectado"
                       if form["factorial"]["is_factorial"] else "diseño simple"),
                    kind="ok"),

                html.Div(style={"marginTop": "12px"}, children=[
                    dash_table.DataTable(
                        data=preview.to_dict("records"),
                        columns=[{"name": c, "id": c} for c in preview.columns],
                        page_size=12,
                        style_cell={"fontSize": "11px", "fontFamily": "monospace",
                                      "padding": "6px 10px"},
                        style_header={"backgroundColor": PAL["dark"],
                                       "color": "white", "fontWeight": "700"},
                    ),
                ]),

                (html.Div([
                    html.Div("Sin emparejar:", style={"marginTop": "10px",
                                                          "fontSize": "11px",
                                                          "color": PAL["amber"],
                                                          "fontFamily": "monospace"}),
                    html.Div(", ".join(map(str, unmatched)),
                              style={"fontSize": "11px",
                                      "fontFamily": "monospace",
                                      "color": PAL["muted"]}),
                ]) if unmatched else None),
            ]),
            title="Emparejamiento muestras ↔ columnas",
        ))

    return html.Div(children)


# =============================================================================
# Tab: ② Preprocess
# =============================================================================

def _tab_pp(d):
    if not (d and d.get("form") and d.get("data_columns")):
        return _info("Carga primero la plantilla y el CSV de datos.", "warn")

    n = len(d["data_columns"])

    return html.Div([
        _section_help(
            html.Div([
                html.Strong("Preprocesado — pipeline estándar de metabolómica. "),
                ("Corrige missing values, equilibra diferencias de concentración "
                 "global entre muestras (normalización), comprime el rango "
                 "dinámico (transformación) y pone todas las features a una "
                 "escala comparable (escalado). El preset por defecto "),
                html.Em("Half-min · PQN · log10 · Pareto"),
                (" funciona bien para lipidómica y metabolómica LC-MS "
                 "(MetaboAnalyst usa el mismo por defecto)."),
            ]),
            kind="info"),
        _card(
            html.Div(style={"display": "grid",
                              "gridTemplateColumns": "repeat(4, 1fr)",
                              "gap": "14px"}, children=[
                html.Div([
                    _config_label("Missing values"),
                    dcc.RadioItems(id="pp-missing", value="halfmin",
                                    options=[{"label": " Half-min", "value": "halfmin"},
                                              {"label": " Drop (<50%)", "value": "drop"},
                                              {"label": " Keep NaN", "value": "keep"}],
                                    style={"fontSize": "11px"}),
                    _help("Half-min: imputa el 50 % del mínimo positivo de "
                          "cada feature — recomendado. Drop: elimina features "
                          "con < 50 % presencia. Keep: deja NaN (tests deben "
                          "tolerarlo)."),
                ]),
                html.Div([
                    _config_label("Normalisation"),
                    dcc.RadioItems(id="pp-norm", value="pqn",
                                    options=[{"label": " PQN", "value": "pqn"},
                                              {"label": " Median", "value": "median"},
                                              {"label": " Sum", "value": "sum"},
                                              {"label": " None", "value": "none"}],
                                    style={"fontSize": "11px"}),
                    _help("PQN (Dieterich 2006): standard de oro — robusto a "
                          "outliers. Median / Sum: alternativas simples. "
                          "None: solo si ya normalizaste con IS."),
                ]),
                html.Div([
                    _config_label("Transform"),
                    dcc.RadioItems(id="pp-trans", value="log10",
                                    options=[{"label": " log10", "value": "log10"},
                                              {"label": " log2",  "value": "log2"},
                                              {"label": " sqrt",  "value": "sqrt"},
                                              {"label": " None",  "value": "none"}],
                                    style={"fontSize": "11px"}),
                    _help("log10 / log2: recomendado para datos MS — convierte "
                          "distribuciones log-normales en gaussianas. sqrt: "
                          "alternativa suave. None: solo datos ya log."),
                ]),
                html.Div([
                    _config_label("Scaling"),
                    dcc.RadioItems(id="pp-scale", value="pareto",
                                    options=[{"label": " Pareto", "value": "pareto"},
                                              {"label": " Auto",   "value": "auto"},
                                              {"label": " Range",  "value": "range"},
                                              {"label": " None",   "value": "none"}],
                                    style={"fontSize": "11px"}),
                    _help("Pareto (÷√SD): default — preserva rango relativo. "
                          "Auto (÷SD = z-score): amplifica features de baja "
                          "varianza. Range: sensible a outliers. None: raro."),
                ]),
            ]),
            html.Div(style={"marginTop": "16px"}, children=[
                _btn("▶ Aplicar preprocesado", id="pp-run"),
                html.Span(id="pp-summary", style={"marginLeft": "16px",
                                                      "fontSize": "11px",
                                                      "fontFamily": "monospace",
                                                      "color": PAL["muted"]}),
            ]),
            title=f"② Preprocesado · {n} muestras · {d.get('data_filename','—')}",
        ),

        dcc.Loading(id="pp-loading", type="circle", color=PAL["teal"],
                     children=html.Div(id="pp-results"),
                     parent_style={"minHeight": "60px"}),
    ])


# =============================================================================
# Tab: ③ Univariate
# =============================================================================

def _tab_uni(d):
    if not (d and d.get("pp_done")):
        return _info("Aplica primero el preprocesado en la pestaña ②.", "warn")
    if not d.get("form"):
        return _need_form_info()

    conds = d["form"]["conditions"]
    if len(conds) < 2:
        return _info("Necesitas ≥ 2 grupos para hacer un análisis univariante.", "warn")

    # n por grupo — usado para recomendación del test
    groups = _groups_series(d)
    counts = groups.value_counts()
    n_min = int(counts.min()) if len(counts) else 0
    small_n = n_min < 5

    rec_test = ("Mann-Whitney U (no paramétrico — más seguro con n<5)"
                if small_n else
                "Welch t (asume normalidad tras log — estándar con n≥5)")

    return html.Div([
        _section_help(
            html.Div([
                html.Strong("Test univariante, feature a feature. "),
                "Compara dos grupos y ajusta por Benjamini-Hochberg (FDR) para "
                "controlar falsos positivos. El resultado ",
                html.Em("no"),
                " confirma causalidad — solo apunta a features con cambio "
                "reproducible entre condiciones. Con n mínimo por grupo = ",
                html.Strong(f"{n_min}"),
                f" la recomendación es: {rec_test}."
            ]),
            kind=("warn" if small_n else "info")),
        _card(
            html.Div(style={"display": "grid",
                              "gridTemplateColumns": "repeat(4, 1fr)",
                              "gap": "14px"}, children=[
                html.Div([
                    _config_label("Grupo A"),
                    dcc.Dropdown(id="uni-a", value=conds[0],
                                  options=[{"label": f"{c} (n={counts.get(c,0)})",
                                            "value": c} for c in conds],
                                  clearable=False),
                    _help("log2FC = log2(media_A / media_B) — A en el eje +"),
                ]),
                html.Div([
                    _config_label("Grupo B"),
                    dcc.Dropdown(id="uni-b", value=conds[1],
                                  options=[{"label": f"{c} (n={counts.get(c,0)})",
                                            "value": c} for c in conds],
                                  clearable=False),
                    _help("Usualmente control / baseline"),
                ]),
                html.Div([
                    _config_label("Test"),
                    dcc.RadioItems(id="uni-test",
                                    value=("mann_whitney" if small_n else "welch"),
                                    options=[{"label": " Welch t",   "value": "welch"},
                                              {"label": " Mann-Whitney U",
                                                "value": "mann_whitney"},
                                              {"label": " Paired t",  "value": "paired_t"},
                                              {"label": " Wilcoxon",  "value": "wilcoxon"}],
                                    style={"fontSize": "11px"}),
                    _help("Welch t: estándar, n≥5 por grupo, varianzas distintas "
                          "permitidas. Mann-Whitney: no paramétrico, usa para "
                          "n pequeño o distribuciones raras. Paired-t / "
                          "Wilcoxon: solo en diseños cross-over / matched."),
                ]),
                html.Div([
                    _config_label("FDR (q)"),
                    dcc.Slider(id="uni-q", min=0.01, max=0.20, step=0.01,
                                value=0.05,
                                marks={0.01: "0.01", 0.05: "0.05",
                                        0.10: "0.10", 0.20: "0.20"},
                                tooltip={"placement": "bottom"}),
                    _help("q < 0.05 estándar. Con n muy bajo (<5) considera "
                          "q < 0.10 como prescreening; confirma después."),
                    html.Div(style={"marginTop": "10px"}, children=[
                        _config_label("|log2 FC| umbral"),
                        dcc.Slider(id="uni-fc", min=0.0, max=3.0, step=0.25,
                                    value=1.0,
                                    marks={0: "0", 1: "1", 2: "2", 3: "3"},
                                    tooltip={"placement": "bottom"}),
                        _help("|log2FC| ≥ 1 ≡ × 2. Sube a 1.5 si buscas "
                              "cambios biológicamente fuertes."),
                    ]),
                ]),
            ]),
            html.Div(style={"marginTop": "12px"},
                      children=[_btn("▶ Ejecutar test", id="uni-run")]),
            title="③ Test univariante",
        ),
        dcc.Loading(id="uni-loading", type="circle", color=PAL["teal"],
                     children=html.Div(id="uni-results"),
                     parent_style={"minHeight": "60px"}),
    ])


# =============================================================================
# Tab: ④ Multivariate (PCA + PLS-DA)
# =============================================================================

def _tab_mv(d):
    if not (d and d.get("pp_done")):
        return _info("Aplica primero el preprocesado en la pestaña ②.", "warn")
    if not d.get("form"):
        return _need_form_info()

    conds = d["form"]["conditions"]
    groups = _groups_series(d)
    n_total = int(groups.dropna().shape[0])
    n_min = int(groups.value_counts().min()) if len(groups.value_counts()) else 0
    plsda_viable = (n_min >= 3 and len(conds) >= 2)

    return html.Div([
        _section_help(
            html.Div([
                html.Strong("PCA + PLS-DA. "),
                "PCA es exploratorio (no-supervisado): detecta agrupaciones "
                "naturales, outliers y efectos batch. Las elipses 95 % de "
                "Hotelling ayudan a ver si los grupos se separan realmente. ",
                html.Strong("PLS-DA"),
                " es supervisado: maximiza la separación entre las clases "
                "elegidas y da VIPs (importancia de cada feature). "
                "Requiere ≥ 3 muestras por grupo. Siempre comprueba la "
                "permutación — si p ≥ 0.05, el modelo puede estar "
                "sobreajustando.",
                html.Br(),
                html.Small(f"Detectadas {n_total} muestras con grupo · "
                           f"n mínimo por grupo = {n_min}. "
                           + ("PLS-DA viable." if plsda_viable
                              else "⚠ PLS-DA probablemente inestable "
                                   "— limita el análisis a PCA o añade muestras."),
                           style={"color": PAL["muted"]}),
            ]),
            kind=("info" if plsda_viable else "warn")),
        _card(
            html.Div(style={"display": "grid",
                              "gridTemplateColumns": "repeat(4, 1fr)",
                              "gap": "14px"}, children=[
                html.Div([
                    _config_label("Componentes"),
                    dcc.Slider(id="mv-ncomp", min=2, max=5, step=1, value=2,
                                marks={i: str(i) for i in range(2, 6)},
                                tooltip={"placement": "bottom"}),
                    _help("Número de componentes principales / latentes. "
                          "2-3 suele ser suficiente; solo sube si el scree "
                          "muestra varianza relevante más allá."),
                ]),
                html.Div([
                    _config_label("PLS-DA permutaciones"),
                    dcc.Slider(id="mv-perm", min=0, max=1000, step=100,
                                value=200,
                                marks={0: "0", 200: "200",
                                        500: "500", 1000: "1000"},
                                tooltip={"placement": "bottom"}),
                    _help("Test de permutación: mezcla etiquetas N veces y "
                          "mide cuántas veces el modelo aleatorio supera al "
                          "real. 200 es suficiente para screening; 1000 para "
                          "publicar. 0 desactiva."),
                ]),
                html.Div([
                    _config_label("PLS-DA: grupos a separar"),
                    dcc.Dropdown(id="mv-groups", multi=True,
                                  value=conds[:2] if len(conds) >= 2 else conds,
                                  options=[{"label": f"{c} (n={int((groups==c).sum())})",
                                            "value": c} for c in conds]),
                    _help("Elige 2-3 grupos. Para PLS-DA clásico usa 2 (caso/"
                          "control). Más grupos = multiclase (posible pero "
                          "interpretación más compleja)."),
                ], style={"gridColumn": "span 2"}),
            ]),
            html.Div(style={"marginTop": "12px"},
                      children=[_btn("▶ Ejecutar PCA + PLS-DA", id="mv-run")]),
            title="④ Análisis multivariante",
        ),
        dcc.Loading(id="mv-loading", type="circle", color=PAL["teal"],
                     children=html.Div(id="mv-results"),
                     parent_style={"minHeight": "60px"}),
    ])


# =============================================================================
# Tab: ⑤ Heatmap
# =============================================================================

def _tab_hm(d):
    if not (d and d.get("pp_done")):
        return _info("Aplica primero el preprocesado en la pestaña ②.", "warn")
    if not d.get("form"):
        return _need_form_info()

    conds = d["form"]["conditions"]

    return html.Div([
        _card(
            html.Div(style={"display": "grid",
                              "gridTemplateColumns": "repeat(4, 1fr)",
                              "gap": "12px"}, children=[
                html.Div([
                    _config_label("Top features (por varianza)"),
                    dcc.Slider(id="hm-top", min=10, max=200, step=10, value=50,
                                marks={10: "10", 50: "50",
                                        100: "100", 200: "200"},
                                tooltip={"placement": "bottom"}),
                    _help("Se eligen las N features más variables a través de "
                          "todas las muestras — las que discriminan más "
                          "grupos suelen estar aquí. Empieza con 30-50; "
                          "sube si sospechas señal distribuida."),
                ]),
                html.Div([
                    _config_label("Cluster muestras"),
                    dcc.RadioItems(id="hm-clus-s", value="no",
                                    options=[{"label": " sí", "value": "yes"},
                                              {"label": " no", "value": "no"}],
                                    style={"fontSize": "11px",
                                            "display": "flex", "gap": "10px"}),
                    _help("Sí: reordena por similitud (dendrograma implícito). "
                          "No: ordena por grupo — más legible para comparar "
                          "condiciones."),
                ]),
                html.Div([
                    _config_label("Cluster features"),
                    dcc.RadioItems(id="hm-clus-f", value="yes",
                                    options=[{"label": " sí", "value": "yes"},
                                              {"label": " no", "value": "no"}],
                                    style={"fontSize": "11px",
                                            "display": "flex", "gap": "10px"}),
                    _help("Agrupa features con patrón similar — aparecen "
                          "bloques rojo/azul que identifican vías."),
                ]),
                html.Div([
                    _config_label("Orden de grupos (si no se clusteriza)"),
                    dcc.Dropdown(id="hm-group-order", multi=True,
                                  value=conds,
                                  options=[{"label": c, "value": c}
                                            for c in conds],
                                  placeholder="arrastra para reordenar"),
                    _help("Arrastra para fijar el orden de las columnas en "
                          "el heatmap cuando el clustering de muestras "
                          "está en 'no'."),
                ]),
            ]),
            html.Div(style={"marginTop": "12px"},
                      children=[_btn("▶ Generar heatmap", id="hm-run")]),
            title="⑤ Heatmap jerárquico",
        ),
        dcc.Loading(id="hm-loading", type="circle", color=PAL["teal"],
                     children=html.Div(id="hm-results"),
                     parent_style={"minHeight": "60px"}),
    ])


# =============================================================================
# Tab: ⑥ Biomarkers
# =============================================================================

def _tab_bm(d):
    if not (d and d.get("pp_done")):
        return _info("Aplica primero el preprocesado en la pestaña ②.", "warn")
    if not d.get("form"):
        return _need_form_info()

    conds = d["form"]["conditions"]
    if len(conds) < 2:
        return _info("Necesitas ≥ 2 grupos.", "warn")

    groups = _groups_series(d)
    counts = groups.value_counts()

    return html.Div([
        _section_help(
            html.Div([
                html.Strong("ROC / AUC con CI por bootstrap. "),
                "Para cada feature se calcula AUC (área bajo la curva ROC) "
                "tratando el grupo A como 'positivo'. AUC = 0.5 → sin "
                "discriminación; AUC = 1.0 → perfecta. El CI se obtiene "
                "remuestreando N veces. Una feature solo es un buen "
                "candidato a biomarcador si AUC ≥ 0.75 ",
                html.Em("y"),
                " el CI 95 % no cruza 0.5. Con n<10 por grupo los CIs son "
                "anchos — interpreta con cautela."
            ]),
            kind="info"),
        _card(
            html.Div(style={"display": "grid",
                              "gridTemplateColumns": "repeat(4, 1fr)",
                              "gap": "14px"}, children=[
                html.Div([
                    _config_label("Grupo A (positivo)"),
                    dcc.Dropdown(id="bm-a", value=conds[0],
                                  options=[{"label": f"{c} (n={counts.get(c,0)})",
                                            "value": c} for c in conds],
                                  clearable=False),
                    _help("Clase que debería dar valores altos. Ej.: "
                          "'enfermedad' si esperas que los biomarcadores "
                          "estén elevados."),
                ]),
                html.Div([
                    _config_label("Grupo B"),
                    dcc.Dropdown(id="bm-b", value=conds[1],
                                  options=[{"label": f"{c} (n={counts.get(c,0)})",
                                            "value": c} for c in conds],
                                  clearable=False),
                    _help("Control / referencia."),
                ]),
                html.Div([
                    _config_label("Bootstrap iters"),
                    dcc.Slider(id="bm-boot", min=100, max=2000, step=100,
                                value=200,
                                marks={100: "100", 200: "200", 500: "500",
                                        1000: "1k", 2000: "2k"},
                                tooltip={"placement": "bottom"}),
                    _help("Remuestreos con reemplazo para estimar el CI "
                          "del AUC. El CI solo se calcula para las top "
                          "candidatas (≈ top_n × 3, mínimo 50); el resto "
                          "del listado solo lleva AUC + p para evitar "
                          "esperas eternas. 200 es suficiente para "
                          "screening; sube a 1000-2000 para el informe "
                          "final."),
                ]),
                html.Div([
                    _config_label("Top N"),
                    dcc.Slider(id="bm-topn", min=5, max=50, step=5, value=15,
                                marks={5: "5", 15: "15", 30: "30", 50: "50"},
                                tooltip={"placement": "bottom"}),
                    _help("Cuántas features mostrar en la tabla final, "
                          "ordenadas por |AUC − 0.5| descendente."),
                ]),
            ]),
            html.Div(style={"marginTop": "12px"},
                      children=[_btn("▶ Calcular biomarcadores", id="bm-run")]),
            title="⑥ ROC / AUC con bootstrap CI",
        ),
        dcc.Loading(id="bm-loading", type="circle", color=PAL["teal"],
                     children=html.Div(id="bm-results"),
                     parent_style={"minHeight": "60px"}),
    ])


# =============================================================================
# Tab: ⑦ Report
# =============================================================================

def _tab_rep(d, key=None):
    ok = bool(d and d.get("pp_done"))
    qs = f"?key={key}" if key else ""

    # Summary of what the report will include
    bits = []
    if ok:
        bits.append(f"✓ preprocesado ({d.get('pp_summary', '—')})")
        if d.get("uni_res"):
            u = d["uni_res"]
            bits.append(f"✓ univariante {u['a']} vs {u['b']} · {u['n_sig']} sig.")
        if d.get("pca_res"):
            bits.append(f"✓ PCA · {len(d['pca_res']['explained'])} componentes")
        if d.get("pls_res"):
            p = d["pls_res"]
            bits.append(f"✓ PLS-DA · accuracy {p['accuracy_cv']:.2f}"
                        + (f" · p_perm={p['permutation']['p_value']:.3f}"
                           if p.get('permutation') else ""))
        if d.get("hm_res"):
            bits.append(f"✓ heatmap · top {d['hm_res']['top']}")
        if d.get("bm_res"):
            b = d["bm_res"]
            bits.append(f"✓ biomarcadores · {b['a']} vs {b['b']}")

    return html.Div([
        _section_help(
            html.Div([
                html.Strong("Informe descargable. "),
                "Incluye portada (proyecto + metadata), descripción del diseño "
                "experimental, pipeline de preprocesado, y los análisis que "
                "hayas ejecutado en las pestañas ③ – ⑥. Todo lo que no hayas "
                "corrido en esta sesión no aparecerá en el informe — ejecuta "
                "primero cada pestaña que quieras incluir."
            ]),
            kind="info"),
        _card(
            html.Div(style={"display": "flex", "gap": "16px",
                              "flexWrap": "wrap"}, children=[
                html.A("📥 Descargar DOCX",
                        id="rep-docx-link",
                        href=f"/dl_stats/docx{qs}" if ok else "#",
                        target="_blank",
                        style={"padding": "10px 18px", "background": PAL["teal"],
                                "color": "white", "borderRadius": "6px",
                                "textDecoration": "none", "fontFamily": "monospace",
                                "fontSize": "12px", "fontWeight": "600",
                                "opacity": "1" if ok else ".4",
                                "pointerEvents": "auto" if ok else "none"}),
                html.A("📥 Descargar PDF",
                        id="rep-pdf-link",
                        href=f"/dl_stats/pdf{qs}" if ok else "#",
                        target="_blank",
                        style={"padding": "10px 18px", "background": PAL["slate"],
                                "color": "white", "borderRadius": "6px",
                                "textDecoration": "none", "fontFamily": "monospace",
                                "fontSize": "12px", "fontWeight": "600",
                                "opacity": "1" if ok else ".4",
                                "pointerEvents": "auto" if ok else "none"}),
            ]),
            html.Div(style={"marginTop": "14px"}, children=[
                html.Div("Contenido del informe:",
                         style={"fontSize": "11px", "fontWeight": "700",
                                "color": PAL["muted"], "marginBottom": "6px",
                                "fontFamily": "monospace"}),
                html.Ul([html.Li(b, style={"fontSize": "11px",
                                           "fontFamily": "monospace",
                                           "color": PAL["dark"]})
                         for b in bits] or [
                    html.Li("—", style={"fontSize": "11px", "color": PAL["muted"]})],
                         style={"margin": "0", "paddingLeft": "18px"}),
            ]) if ok else html.Div(
                "Genera primero los análisis en las pestañas anteriores.",
                style={"marginTop": "12px", "fontSize": "11px",
                       "color": PAL["muted"], "fontFamily": "monospace"}),
            title="⑦ Informe descargable",
        )
    ])


# =============================================================================
# Tab dispatcher
# =============================================================================

@callback(
    Output("stats-content", "children"),
    Input("stats-tabs", "value"),
    Input("stats-key", "data"),
)
def _route_tab(which, key):
    d = cload(key) if key else None
    if which == "tab-load":
        return _tab_load(d)
    if which == "tab-pp":
        return _tab_pp(d)
    if which == "tab-uni":
        return _tab_uni(d)
    if which == "tab-mv":
        return _tab_mv(d)
    if which == "tab-hm":
        return _tab_hm(d)
    if which == "tab-bm":
        return _tab_bm(d)
    if which == "tab-rep":
        return _tab_rep(d, key=key)
    return _info("Pestaña no reconocida.", "err")


# =============================================================================
# Upload handlers
# =============================================================================

def _decode_b64(contents):
    _, b64 = contents.split(",", 1)
    return base64.b64decode(b64)


@callback(
    Output("stats-form-info", "children"),
    Output("stats-key", "data"),
    Input("stats-upload-form", "contents"),
    State("stats-upload-form", "filename"),
    State("stats-key", "data"),
    prevent_initial_call=True,
)
def _upload_form(contents, fname, current_key):
    if not contents:
        raise PreventUpdate
    try:
        raw = _decode_b64(contents)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            tf.write(raw); path = tf.name
        parsed = sp.parse_submission_form(path)
        os.unlink(path)
    except Exception as e:
        return _info(f"Error parseando '{fname}': {e}", "err"), dash.no_update

    sample_to_cond = dict(zip(parsed["samples_df"]["sample_name"],
                                parsed["samples_df"]["condition"]))

    d = cload(current_key) if current_key else {}
    if not d:
        d = {}
    d["form"] = {
        "filename":       fname,
        "metadata":       parsed["metadata"],
        "samples_df":     parsed["samples_df"],
        "conditions":     parsed["conditions"],
        "factorial":      parsed["factorial"],
        "sample_to_cond": sample_to_cond,
        "n_samples":      parsed["n_samples"],
    }

    # Re-emparejar si ya hay datos cargados
    if d.get("data_columns"):
        mm = sp.match_aggregated_columns(parsed["samples_df"], d["data_columns"])
        d["rename_map"]        = mm["rename_map"]
        d["unmatched_data"]    = mm["unmatched_data"]
        d["unmatched_samples"] = mm["unmatched_samples"]
        d["pp_done"]           = False  # invalidate cached preprocessing

    msg = _info(f"✓ {fname} · {parsed['n_samples']} muestras · "
                  f"{len(parsed['conditions'])} condiciones"
                  + (" · factorial detectado"
                      if parsed["factorial"]["is_factorial"] else ""),
                  kind="ok")
    return msg, csave(d)


def _parse_aletheia_csv(contents, fname):
    """Parse experiment_aggregated.csv (wide format: features × samples).

    Returns (data_df, sample_cols) or raises ValueError if the CSV doesn't
    look like an aggregated intensity table (no S1..SN columns)."""
    raw = _decode_b64(contents)
    df = None
    for sep in (";", ","):
        try:
            tmp = pd.read_csv(io.BytesIO(raw), sep=sep, encoding="utf-8")
            if tmp.shape[1] > 2:
                df = tmp
                break
        except Exception:
            continue
    if df is None:
        df = pd.read_csv(io.BytesIO(raw), sep=";", encoding="latin1")

    meta_candidates = ["Bucket label", "label", "feature", "Name", "Formula",
                        "RT", "m/z"]
    id_col = next((c for c in meta_candidates if c in df.columns), df.columns[0])
    sample_cols = [c for c in df.columns if sp._SAMPLE_COL_RE.match(str(c))]
    if not sample_cols:
        raise ValueError(
            f"No encontré columnas tipo 'S1, S2, …' en '{fname}'. "
            f"Columnas detectadas: {list(df.columns)[:8]}…. "
            f"¿Este archivo es pass_all_criteria? Súbelo a la derecha — "
            f"se usa como filtro sobre experiment_aggregated.")

    # Capture the Name column (compound identifier) if present — it's
    # useful for display even though we don't use it as the index.
    name_series = None
    if "Name" in df.columns and id_col != "Name":
        name_series = df["Name"].astype(str).str.strip()

    # Deduplicate the bucket labels: Aletheia sometimes outputs the same
    # m/z + RT bucket label for several rows (different putative compounds
    # collapsed to the same coordinate). Without this, ``data.loc[lab]``
    # returns a 2-D DataFrame and downstream stats explode with
    # "too many indices for array". We append a numeric suffix to the
    # 2nd, 3rd, … occurrence so the index is unique while keeping the
    # original label in ``orig_label`` for display.
    raw_labels = df[id_col].astype(str).tolist()
    seen: dict[str, int] = {}
    unique_labels: list[str] = []
    for lab in raw_labels:
        c = seen.get(lab, 0)
        unique_labels.append(lab if c == 0 else f"{lab} #{c+1}")
        seen[lab] = c + 1

    data_df = df[sample_cols].apply(pd.to_numeric, errors="coerce")
    data_df.index = pd.Index(unique_labels, name=id_col)

    # Build display map: deduped label → original bucket label and (if
    # present) compound name. Stored on the cache so the biomarker /
    # univariate tabs can show a friendly "Name" column.
    label_meta = {
        "orig_label": dict(zip(unique_labels, raw_labels)),
        "name":       dict(zip(unique_labels,
                                 name_series.tolist() if name_series is not None
                                 else [""] * len(unique_labels))),
    }
    return data_df, sample_cols, label_meta


def _parse_pass_criteria(contents, fname):
    """Parse pass_all_criteria.csv as a *whitelist of feature labels*.

    Aletheia's pass_all_criteria.csv has diagnostic columns only
    (label, Name, ok, r2, strategy, n_valid, reason, CV_median) — not
    sample intensities. We use it to filter experiment_aggregated.csv
    rows.

    Returns (passed_labels: set[str], n_total: int, n_passed: int).
    - If a boolean ``ok`` / ``pass_both`` column exists, we filter to
      rows where it's True; else we assume the whole file is already
      pre-filtered.
    """
    raw = _decode_b64(contents)
    df = None
    for sep in (";", ","):
        try:
            tmp = pd.read_csv(io.BytesIO(raw), sep=sep, encoding="utf-8")
            if tmp.shape[1] > 1:
                df = tmp
                break
        except Exception:
            continue
    if df is None:
        df = pd.read_csv(io.BytesIO(raw), sep=";", encoding="latin1")

    label_candidates = ["label", "Bucket label", "feature", "Name"]
    lab_col = next((c for c in label_candidates if c in df.columns), None)
    if lab_col is None:
        raise ValueError(
            f"'{fname}' no contiene una columna identificadora de feature "
            f"('label' / 'Bucket label' / 'Name'). "
            f"Columnas detectadas: {list(df.columns)[:8]}…")

    n_total = len(df)
    mask = pd.Series([True] * n_total, index=df.index)
    for flag_col in ("pass_both", "ok"):
        if flag_col in df.columns:
            flag = df[flag_col]
            if flag.dtype == bool or set(str(v).lower() for v in flag.unique()) <= {
                "true", "false", "1", "0", "nan", ""}:
                mask &= flag.astype(str).str.lower().isin(["true", "1"])
            break

    passed = df.loc[mask, lab_col].dropna().astype(str).tolist()
    return set(passed), n_total, len(passed)


def _activate_dataset(d, which):
    """Point d['data_df'] + d['data_columns'] + d['rename_map'] at either
    the full aggregated table or the pass_all_criteria-filtered subset.

    ``which`` ∈ {'agg', 'pass'}:
      - 'agg'  → use data_agg_df as-is.
      - 'pass' → use data_agg_df filtered to rows whose index is in
                 data_pass_labels. Falls back to 'agg' if either is
                 missing.
    """
    agg_df = d.get("data_agg_df")
    if agg_df is None:
        return d

    if which == "pass":
        labels = d.get("data_pass_labels")
        if not labels:
            # No filter loaded yet — fall back to full set
            which = "agg"
            data_df = agg_df
            fname = d.get("data_agg_fname", "experiment_aggregated.csv")
        else:
            keep = [lab for lab in agg_df.index if str(lab) in labels]
            data_df = agg_df.loc[keep]
            fname = (f"{d.get('data_agg_fname', 'experiment_aggregated.csv')} "
                     f"· filtrado por {d.get('data_pass_fname', 'pass_all_criteria.csv')} "
                     f"({len(keep)}/{len(agg_df)})")
    else:
        which = "agg"
        data_df = agg_df
        fname = d.get("data_agg_fname", "experiment_aggregated.csv")

    d["data_df"]       = data_df
    d["data_columns"]  = list(data_df.columns)
    d["data_filename"] = fname
    d["active_dataset"] = which
    d["pp_done"] = False
    for k in ("uni_res", "pca_res", "pls_res", "hm_res", "bm_res"):
        d.pop(k, None)
    if d.get("form"):
        mm = sp.match_aggregated_columns(d["form"]["samples_df"], d["data_columns"])
        d["rename_map"]        = mm["rename_map"]
        d["unmatched_data"]    = mm["unmatched_data"]
        d["unmatched_samples"] = mm["unmatched_samples"]
    return d


@callback(
    Output("stats-agg-info", "children"),
    Output("stats-key", "data", allow_duplicate=True),
    Input("stats-upload-agg", "contents"),
    State("stats-upload-agg", "filename"),
    State("stats-key", "data"),
    prevent_initial_call=True,
)
def _upload_agg(contents, fname, current_key):
    if not contents:
        raise PreventUpdate
    try:
        data_df, sample_cols, label_meta = _parse_aletheia_csv(contents, fname)
    except Exception as e:
        return _info(f"Error leyendo '{fname}': {e}", "err"), dash.no_update

    d = cload(current_key) if current_key else {}
    if not d:
        d = {}
    d["data_agg_df"]    = data_df
    d["data_agg_cols"]  = sample_cols
    d["data_agg_fname"] = fname
    d["label_meta"]     = label_meta
    _activate_dataset(d, d.get("active_dataset", "agg"))

    msg = _info(f"✓ {fname} · {data_df.shape[0]} features × "
                  f"{data_df.shape[1]} muestras", kind="ok")
    return msg, csave(d)


@callback(
    Output("stats-pass-info", "children"),
    Output("stats-key", "data", allow_duplicate=True),
    Input("stats-upload-pass", "contents"),
    State("stats-upload-pass", "filename"),
    State("stats-key", "data"),
    prevent_initial_call=True,
)
def _upload_pass(contents, fname, current_key):
    if not contents:
        raise PreventUpdate
    try:
        passed_labels, n_total, n_passed = _parse_pass_criteria(contents, fname)
    except Exception as e:
        return _info(f"Error leyendo '{fname}': {e}", "err"), dash.no_update

    d = cload(current_key) if current_key else {}
    if not d:
        d = {}
    d["data_pass_labels"] = passed_labels
    d["data_pass_count"]  = n_passed
    d["data_pass_total"]  = n_total
    d["data_pass_fname"]  = fname
    # Auto-switch to 'pass' only if agg is already present (otherwise UI
    # is still waiting for agg — the selector stays disabled).
    if d.get("data_agg_df") is not None:
        _activate_dataset(d, "pass")
    else:
        _activate_dataset(d, d.get("active_dataset", "agg"))

    if d.get("data_agg_df") is not None:
        msg = _info(
            f"✓ {fname} · {n_passed}/{n_total} features pasan filtro · "
            f"aplicado sobre experiment_aggregated", kind="ok")
    else:
        msg = _info(
            f"✓ {fname} · {n_passed}/{n_total} features pasan filtro. "
            f"Sube experiment_aggregated.csv para aplicarlo.", kind="warn")
    return msg, csave(d)


@callback(
    Output("stats-key", "data", allow_duplicate=True),
    Input("stats-active-dataset", "value"),
    State("stats-key", "data"),
    prevent_initial_call=True,
)
def _switch_dataset(which, current_key):
    d = cload(current_key) if current_key else None
    if not d or not which:
        raise PreventUpdate
    _activate_dataset(d, which)
    return csave(d)


# =============================================================================
# ② Preprocess callback
# =============================================================================

@callback(
    Output("pp-summary", "children"),
    Output("pp-results", "children"),
    Output("stats-key", "data", allow_duplicate=True),
    Input("pp-run", "n_clicks"),
    State("pp-missing", "value"),
    State("pp-norm",    "value"),
    State("pp-trans",   "value"),
    State("pp-scale",   "value"),
    State("stats-key",  "data"),
    prevent_initial_call=True,
)
def _run_preprocess(_n, missing, norm, trans, scale, key):
    if not _n:
        raise PreventUpdate
    try:
        d = cload(key)
        if not d or d.get("data_df") is None:
            return "—", _info("Carga la tabla de datos primero.", "warn"), dash.no_update

        cfg = PreprocessConfig(missing=missing, normalize=norm,
                                 transform=trans, scale=scale)
        raw = d["data_df"]
        pp = preprocess(raw, cfg)

        d["pp_cfg"]     = {"missing": missing, "norm": norm,
                              "transform": trans, "scale": scale}
        d["pp_data"]    = pp["data"]
        d["pp_summary"] = pp["summary"]
        d["pp_done"]    = True
        # invalidate downstream caches
        d.pop("uni_res", None); d.pop("pca_res", None); d.pop("pls_res", None)
        d.pop("hm_res",  None); d.pop("bm_res",  None)

        # Visual sanity check: per-sample density (bell curve) + global raw/proc
        groups = _groups_series(d) if d.get("form") else None
        fig = _preprocess_density_fig(raw, pp["data"], groups=groups)

        res = html.Div([
            _card(
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                html.Div([
                    html.Span("Features: "), html.Strong(str(pp["data"].shape[0])),
                    html.Span(" · "),
                    html.Span("Muestras: "), html.Strong(str(pp["data"].shape[1])),
                    html.Span(" · ", style={"margin": "0 6px"}),
                    html.Span("Dataset: "),
                    html.Strong(d.get("data_filename", "—")),
                ], style={"fontSize": "12px", "fontFamily": "monospace",
                           "color": PAL["dark"]}),
                html.Div(
                    "Cada curva = densidad de intensidades de una muestra. "
                    "Tras PQN + log + escalado esperas campanas gaussianas "
                    "superpuestas: si una muestra está desplazada o tiene "
                    "varianza distinta, normalmente indica contaminación, "
                    "dilución incorrecta o efecto batch.",
                    style={"fontSize": "10px", "color": PAL["muted"],
                             "marginTop": "6px",
                             "fontFamily": "Inter,sans-serif"}),
                title="Resultado del preprocesado",
            ),
        ])
        # Mutate the cache entry in place via the live reference returned by cload;
        # do NOT update stats-key (would re-trigger _route_tab and wipe pp-results).
        return pp["summary"], res, dash.no_update
    except Exception as e:
        return "—", _err_panel(e), dash.no_update


# =============================================================================
# Helper: per-sample density "bell curve" plot for preprocessing sanity check
# =============================================================================

def _kde_1d(values, grid, bw=None):
    """Minimal Gaussian KDE without scipy dependency.
    values : 1-D array (drop NaNs upstream)
    grid   : 1-D array of x values to evaluate on
    bw     : Silverman's rule if None
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 3:
        return np.zeros_like(grid, dtype=float)
    sd = v.std(ddof=1)
    if sd == 0:
        return np.zeros_like(grid, dtype=float)
    if bw is None:
        bw = 1.06 * sd * n ** (-1 / 5)      # Silverman
        if bw <= 0:
            bw = 1e-3
    # vectorised kernel sum: (G, N) matrix of (x - xi)/h
    z = (grid[:, None] - v[None, :]) / bw
    k = np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)
    return k.sum(axis=1) / (n * bw)


def _preprocess_density_fig(raw, proc, groups=None):
    """MetaboAnalyst-style 2×2 sanity plot:

      ┌──────────────────────────┬────────────────────────────┐
      │ Boxplots RAW por muestra │ Density RAW (campana global)│
      ├──────────────────────────┼────────────────────────────┤
      │ Boxplots PROCESADO       │ Density PROCESADO          │
      └──────────────────────────┴────────────────────────────┘

    Tras PQN + log + escalado, los boxplots deberían alinearse (mismo
    mediana/IQR) y la densidad global debería ser aprox. una campana
    de Gauss ≈ N(0,1) si se aplicó Pareto.
    """
    from plotly.subplots import make_subplots
    fig = make_subplots(
        rows=2, cols=2, shared_yaxes=False,
        subplot_titles=("Raw · boxplots por muestra",
                        "Raw · densidad global (log10 intensidad)",
                        "Procesado · boxplots por muestra",
                        "Procesado · densidad global (≈ campana de Gauss)"),
        vertical_spacing=0.14, horizontal_spacing=0.10,
        column_widths=[0.55, 0.45],
    )

    samples = list(proc.columns)

    # ── Palette: by group if available, else by sample index ─────────────
    if groups is not None and not groups.empty:
        g_unique = list(pd.unique(groups.dropna()))
        gp = {g: SPAL[i % len(SPAL)] for i, g in enumerate(g_unique)}
        sample_color = [gp.get(groups.get(s), PAL["muted"]) for s in samples]
    else:
        sample_color = [SPAL[i % len(SPAL)] for i in range(len(samples))]

    # ── RAW (log10(x+1) para aplanar el rango dinámico) ──────────────────
    raw_aligned = raw[samples] if all(s in raw.columns for s in samples) else raw
    raw_log = np.log10(raw_aligned.clip(lower=0) + 1.0)

    # Boxplots raw (por muestra)
    for i, s in enumerate(samples):
        vals = raw_log[s].dropna().values
        fig.add_trace(go.Box(
            y=vals, name=str(s), marker_color=sample_color[i],
            line=dict(color=sample_color[i], width=1),
            boxmean=True, showlegend=False, boxpoints=False,
            hovertemplate=f"<b>{s}</b><br>log10(int)=%{{y:.2f}}<extra></extra>",
        ), row=1, col=1)

    # Density raw global (una sola curva)
    all_raw = raw_log.values.flatten()
    all_raw = all_raw[np.isfinite(all_raw)]
    if len(all_raw) >= 3:
        lo_r, hi_r = np.percentile(all_raw, [1, 99])
        grid_r = np.linspace(lo_r, hi_r, 200)
        y_r = _kde_1d(all_raw, grid_r)
        fig.add_trace(go.Scatter(
            x=grid_r, y=y_r, mode="lines", fill="tozeroy",
            line=dict(color=PAL["slate"], width=2),
            fillcolor=_hex2rgba(PAL["slate"], 0.18),
            showlegend=False, name="raw",
            hovertemplate="log10(int)=%{x:.2f}<br>densidad=%{y:.3f}<extra></extra>",
        ), row=1, col=2)

    # ── PROCESADO ────────────────────────────────────────────────────────
    for i, s in enumerate(samples):
        vals = proc[s].dropna().values
        fig.add_trace(go.Box(
            y=vals, name=str(s), marker_color=sample_color[i],
            line=dict(color=sample_color[i], width=1),
            boxmean=True, showlegend=False, boxpoints=False,
            hovertemplate=f"<b>{s}</b><br>valor=%{{y:.2f}}<extra></extra>",
        ), row=2, col=1)

    all_proc = proc.values.flatten()
    all_proc = all_proc[np.isfinite(all_proc)]
    if len(all_proc) >= 3:
        lo_p, hi_p = np.percentile(all_proc, [1, 99])
        if lo_p == hi_p:
            lo_p, hi_p = -3.0, 3.0
        grid_p = np.linspace(lo_p, hi_p, 200)
        y_p = _kde_1d(all_proc, grid_p)
        fig.add_trace(go.Scatter(
            x=grid_p, y=y_p, mode="lines", fill="tozeroy",
            line=dict(color=PAL["teal"], width=2),
            fillcolor=_hex2rgba(PAL["teal"], 0.18),
            showlegend=False, name="procesado",
            hovertemplate="valor=%{x:.2f}<br>densidad=%{y:.3f}<extra></extra>",
        ), row=2, col=2)
        # Overlay N(0,1) para comparar con la campana ideal
        mu, sd = float(np.mean(all_proc)), float(np.std(all_proc, ddof=1))
        if sd > 0 and np.isfinite(sd):
            ref = np.exp(-0.5 * ((grid_p - mu) / sd) ** 2) / (sd * np.sqrt(2 * np.pi))
            fig.add_trace(go.Scatter(
                x=grid_p, y=ref, mode="lines",
                line=dict(color=PAL["coral"], width=1.5, dash="dot"),
                showlegend=False, name="gaussiana",
                hovertemplate="Gaussian ref<extra></extra>",
            ), row=2, col=2)

    # Legend key para el color de grupo
    if groups is not None and not groups.empty:
        g_unique = list(pd.unique(groups.dropna()))
        for g in g_unique:
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers",
                marker=dict(color=gp[g], size=10, symbol="square"),
                name=str(g), legendgroup=str(g), showlegend=True,
            ), row=1, col=1)

    # Axes labels
    fig.update_xaxes(title_text="", tickangle=-45, row=1, col=1,
                      tickfont=dict(size=9))
    fig.update_xaxes(title_text="log10(intensidad + 1)", row=1, col=2)
    fig.update_xaxes(title_text="Muestra", tickangle=-45, row=2, col=1,
                      tickfont=dict(size=9))
    fig.update_xaxes(title_text="Intensidad procesada", row=2, col=2)
    fig.update_yaxes(title_text="log10(intensidad + 1)", row=1, col=1)
    fig.update_yaxes(title_text="Densidad", row=1, col=2)
    fig.update_yaxes(title_text="Valor procesado", row=2, col=1)
    fig.update_yaxes(title_text="Densidad", row=2, col=2)

    fig.update_layout(
        title=("Distribución por muestra · antes y después del preprocesado · "
               "boxplots + densidad global"),
        height=680,
        **{k: v for k, v in P_LAYOUT.items() if k not in ("margin", "legend")},
        margin=dict(l=60, r=16, t=80, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=-0.08,
                     xanchor="center", x=0.5, font=dict(size=10)),
        boxmode="group",
    )
    return fig


# =============================================================================
# Helper: build groups Series from form + processed data
# =============================================================================

def _groups_series(d):
    """Return a Series indexed by data column name, value = condition (using the
    rename_map and the sample_name → condition map from the form).
    """
    rename = d.get("rename_map", {})
    s2c = d["form"]["sample_to_cond"]
    out = {}
    for data_col, sname in rename.items():
        out[data_col] = s2c.get(sname)
    return pd.Series(out)


def _placeholder_name(s: str) -> bool:
    """True if a Name value is blank or a placeholder like 'Compound 042'."""
    if s is None:
        return True
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return True
    # Aletheia's default placeholder pattern: "Compound 000", "Compound 1234", …
    import re
    return bool(re.match(r"^compound\s*\d+$", s, re.IGNORECASE))


def _attach_display_name(df: pd.DataFrame, d: dict,
                          feature_col: str = "feature") -> pd.DataFrame:
    """Add a human-friendly ``Name`` column to a feature-level DataFrame.

    Uses ``d['label_meta']['name']`` (Aletheia ``Name`` column) when it
    contains a meaningful identifier; otherwise falls back to the
    deduped bucket label. Returns a copy with ``Name`` inserted right
    after ``feature``.
    """
    out = df.copy()
    meta = (d or {}).get("label_meta") or {}
    name_map = meta.get("name") or {}
    orig_map = meta.get("orig_label") or {}

    def _resolve(lab):
        nm = name_map.get(lab, "")
        if not _placeholder_name(nm):
            return str(nm).strip()
        # Fall back to the original bucket label (without dedup suffix)
        return str(orig_map.get(lab, lab))

    out.insert(out.columns.get_loc(feature_col) + 1,
                "Name",
                out[feature_col].map(_resolve))
    return out


# =============================================================================
# ③ Univariate callback
# =============================================================================

@callback(
    Output("uni-results", "children"),
    Output("stats-key",  "data", allow_duplicate=True),
    Input("uni-run", "n_clicks"),
    State("uni-a",    "value"),
    State("uni-b",    "value"),
    State("uni-test", "value"),
    State("uni-q",    "value"),
    State("uni-fc",   "value"),
    State("stats-key","data"),
    prevent_initial_call=True,
)
def _run_uni(_n, a, b, test, qth, fcth, key):
    if not _n:
        raise PreventUpdate
    try:
        d = cload(key)
        if not d or not d.get("pp_done"):
            return _info("Aplica preprocesado primero.", "warn"), dash.no_update
        if a == b:
            return _info("Elige dos grupos diferentes.", "warn"), dash.no_update

        groups = _groups_series(d)
        res = two_group_test(d["pp_data"], groups, a, b, test=test,
                              raw_for_fc=d["data_df"])

        vol_df = volcano_data(res, fc_threshold=fcth, q_threshold=qth)
        n_sig = int((vol_df["sig"] != "ns").sum())
        n_up   = int((vol_df["sig"] == "up").sum())
        n_down = int((vol_df["sig"] == "down").sum())

        # ── Volcano + p-value histogram side by side ───────────────────────
        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.65, 0.35],
            subplot_titles=(
                f"Volcano · {a} vs {b} · {test}",
                "Distribución de p-valores (raw)"),
            horizontal_spacing=0.12,
        )

        # Volcano
        color_map = {"up":   PAL["coral"],
                      "down": PAL["slate"],
                      "ns":   "#CCCCCC"}
        label_map = {"up":   f"↑ en {a} (n={n_up})",
                      "down": f"↑ en {b} (n={n_down})",
                      "ns":   "n.s."}
        for cat in ("ns", "down", "up"):
            sub = vol_df[vol_df["sig"] == cat]
            fig.add_trace(go.Scatter(
                x=sub["log2FC"], y=sub["neg_log10_q"],
                mode="markers", name=label_map[cat],
                marker=dict(color=color_map[cat], size=7,
                              opacity=(0.95 if cat != "ns" else 0.55),
                              line=dict(color="white", width=0.5)),
                text=sub["feature"],
                hovertemplate="<b>%{text}</b><br>"
                                "log2FC=%{x:.2f}<br>"
                                "-log10(q)=%{y:.2f}<extra></extra>",
            ), row=1, col=1)
        fig.add_hline(y=-np.log10(qth),
                      line=dict(dash="dash", color=PAL["muted"], width=1),
                      annotation_text=f"q={qth}", annotation_position="top left",
                      row=1, col=1)
        fig.add_vline(x=fcth,  line=dict(dash="dash", color=PAL["muted"], width=1),
                      row=1, col=1)
        fig.add_vline(x=-fcth, line=dict(dash="dash", color=PAL["muted"], width=1),
                      row=1, col=1)

        # Label the top N significant features directly on the plot
        top_labels = vol_df[vol_df["sig"] != "ns"].sort_values(
            "neg_log10_q", ascending=False).head(12)
        if not top_labels.empty:
            fig.add_trace(go.Scatter(
                x=top_labels["log2FC"], y=top_labels["neg_log10_q"],
                mode="text", text=top_labels["feature"],
                textposition="top center",
                textfont=dict(size=8, color=PAL["dark"]),
                showlegend=False, hoverinfo="skip",
            ), row=1, col=1)

        fig.update_xaxes(title_text="log2 FC (A / B)", row=1, col=1,
                         zeroline=True, zerolinecolor=PAL["border"])
        fig.update_yaxes(title_text="−log10(q)", row=1, col=1,
                         rangemode="tozero")

        # p-value histogram
        pvals = res.table["p"].dropna().values
        fig.add_trace(go.Histogram(
            x=pvals, nbinsx=20, marker=dict(color=PAL["teal"], opacity=0.75),
            name="p-value", showlegend=False,
            hovertemplate="p∈[%{x}] · n=%{y}<extra></extra>",
        ), row=1, col=2)
        # Expected uniform line under H0 (total / nbins)
        total = len(pvals)
        if total:
            fig.add_hline(y=total / 20,
                          line=dict(dash="dash", color=PAL["muted"], width=1),
                          annotation_text="H₀ uniforme",
                          annotation_position="top right",
                          row=1, col=2)
        fig.update_xaxes(title_text="p-valor", range=[0, 1], row=1, col=2)
        fig.update_yaxes(title_text="# features", row=1, col=2)

        fig.update_layout(
            title=(f"{a} vs {b} · {test} · n_sig = {n_sig} "
                   f"(↑{n_up}·↓{n_down})"),
            height=420,
            **{k: v for k, v in P_LAYOUT.items() if k not in ("margin", "legend")},
            margin=dict(l=50, r=16, t=72, b=50),
            legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
        )

        # Top hits table
        top = res.table.head(25).copy()
        for c in ("log2FC", "p", "q", "cohens_d", "hedges_g", "stat"):
            if c in top.columns:
                top[c] = top[c].apply(
                    lambda v: f"{v:.3e}" if (pd.notna(v) and abs(v) < 1e-3)
                                else (f"{v:.4g}" if pd.notna(v) else "—"))

        d["uni_res"] = {"a": a, "b": b, "test": test,
                          "table": res.table, "n_sig": n_sig,
                          "fc_threshold": fcth, "q_threshold": qth}

        return html.Div([
            _card(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                    title=f"Volcano plot — q ≤ {qth} · |log2FC| ≥ {fcth}"),
            _card(
                dash_table.DataTable(
                    data=top.to_dict("records"),
                    columns=[{"name": c, "id": c} for c in top.columns],
                    page_size=15, sort_action="native",
                    style_cell={"fontSize": "11px", "fontFamily": "monospace",
                                  "padding": "4px 8px", "textAlign": "left"},
                    style_header={"backgroundColor": PAL["dark"],
                                   "color": "white", "fontWeight": "700"},
                ),
                title=f"Top features · {n_sig} significativos a q ≤ {qth}",
            ),
        ]), dash.no_update
    except Exception as e:
        return _err_panel(e), dash.no_update


# =============================================================================
# ④ Multivariate callback
# =============================================================================

@callback(
    Output("mv-results", "children"),
    Output("stats-key", "data", allow_duplicate=True),
    Input("mv-run", "n_clicks"),
    State("mv-ncomp", "value"),
    State("mv-perm",  "value"),
    State("mv-groups","value"),
    State("stats-key","data"),
    prevent_initial_call=True,
)
def _run_mv(_n, ncomp, n_perm, plsda_groups, key):
    if not _n:
        raise PreventUpdate
    try:
        # ── sklearn availability check with actionable message ───────────
        try:
            import sklearn  # noqa: F401
        except ImportError:
            return _info(
                html.Div([
                    html.Strong("scikit-learn no está instalado. "),
                    "Instálalo con: ",
                    html.Code("pip install scikit-learn",
                               style={"background": PAL["cream"],
                                      "padding": "2px 6px",
                                      "borderRadius": "3px"}),
                    " y reinicia la app.",
                ]), "err"), dash.no_update

        d = cload(key)
        if not d or not d.get("pp_done"):
            return _info("Aplica preprocesado primero.", "warn"), dash.no_update

        # Restrict data to samples with group + numeric data
        pp = d["pp_data"]
        groups_all = _groups_series(d)
        cols_with_group = [c for c in pp.columns
                           if c in groups_all.index and pd.notna(groups_all.get(c))]
        if len(cols_with_group) < 3:
            return _info(
                f"Sólo {len(cols_with_group)} muestra(s) con grupo asignado — "
                "PCA requiere ≥ 3. Revisa la plantilla: todas las muestras "
                "deben tener 'Condition' rellena.", "err"), dash.no_update

        pp_clean = pp[cols_with_group].replace(
            [np.inf, -np.inf], np.nan).fillna(0)
        groups = groups_all.loc[cols_with_group]
        counts = groups.value_counts()

        # ── PCA (todas las muestras con grupo) ───────────────────────────────
        pca = run_pca(pp_clean, groups=groups, n_components=ncomp)

        pca_fig = _pca_scores_fig(pca, groups)
        scree = go.Figure()
        scree.add_trace(go.Bar(
            x=[f"PC{i+1}" for i in range(pca.n_components)],
            y=pca.explained_variance_ratio * 100,
            marker_color=PAL["teal"],
        ))
        scree.update_layout(title="Varianza explicada (%)", **P_LAYOUT,
                              yaxis_title="%")

        # ── PLS-DA (subset of selected groups) ───────────────────────────────
        pls_card = None
        pls = None
        if plsda_groups and len(plsda_groups) >= 2:
            keep = groups[groups.isin(plsda_groups)].dropna()
            sel_counts = keep.value_counts()
            min_n = int(sel_counts.min()) if len(sel_counts) else 0
            if len(keep) < 4:
                pls_card = _info(
                    f"PLS-DA: sólo {len(keep)} muestras en los grupos "
                    f"seleccionados ({', '.join(plsda_groups)}). "
                    "Se necesitan ≥ 4 en total y ≥ 2 por grupo.", "warn")
            elif min_n < 2:
                pls_card = _info(
                    f"PLS-DA: algún grupo tiene sólo {min_n} muestra — "
                    "necesitas ≥ 2 por grupo para LOO-CV.", "warn")
            else:
                try:
                    pls = run_plsda(pp_clean[keep.index], keep,
                                     n_components=min(ncomp,
                                                     len(plsda_groups) - 1, 3,
                                                     max(1, min_n - 1)),
                                     loo_cv=True,
                                     n_permutations=int(n_perm),
                                     random_state=7)
                except Exception as e:
                    pls_card = _info(
                        html.Div([
                            html.Strong(f"PLS-DA error: "),
                            html.Span(str(e)),
                            html.Div("Si el problema persiste con n pequeños, "
                                     "prueba a reducir componentes a 2 o "
                                     "limita a 2 grupos.",
                                     style={"marginTop": "4px",
                                            "fontSize": "10px"}),
                        ]), "err")

                if pls is not None:
                    pls_fig = _plsda_scores_fig(pls, keep)
                    # vip is a Series with name="VIP" and index = feature labels
                    # (whose .name may be "Bucket label" or similar). Force the
                    # output column to "feature" via rename_axis so downstream
                    # references (vip_top["feature"]) always work.
                    vip_top = (pls.vip.head(20)
                                 .rename_axis("feature")
                                 .reset_index())
                    if "VIP" not in vip_top.columns:
                        # Series may have come back unnamed → second column is 0
                        vip_top = vip_top.rename(columns={0: "VIP"})
                    vip_fig = go.Figure()
                    vip_fig.add_trace(go.Bar(
                        x=vip_top["VIP"], y=vip_top["feature"],
                        orientation="h", marker=dict(color=PAL["amber"]),
                    ))
                    vip_fig.update_layout(
                        title="Top 20 VIPs (≥ 1.0 son relevantes)",
                        yaxis=dict(autorange="reversed"),
                        **{**P_LAYOUT, "margin": dict(l=120, r=16, t=36, b=40)})

                    perm_msg = ""
                    if pls.permutation:
                        perm_msg = (f" · permutation p = "
                                      f"{pls.permutation['p_value']:.4f}")

                    pls_card = _card(
                        html.Div([
                            html.Div(f"Accuracy LOO-CV: ", style={"display": "inline"}),
                            html.Strong(f"{pls.accuracy_cv:.3f}",
                                          style={"color": PAL["teal"]}),
                            html.Span(perm_msg, style={"color": PAL["muted"],
                                                          "marginLeft": "8px"}),
                        ], style={"fontSize": "12px", "fontFamily": "monospace",
                                   "marginBottom": "10px"}),
                        dcc.Graph(figure=pls_fig, config={"displayModeBar": False}),
                        dcc.Graph(figure=vip_fig, config={"displayModeBar": False}),
                        title=f"PLS-DA · {' vs '.join(plsda_groups)}",
                    )

        d["pca_res"] = {"explained": pca.explained_variance_ratio.tolist(),
                          "scores":     pca.scores,
                          "loadings":   pca.loadings,
                          "ellipses":   pca.ellipses}
        if pls is not None:
            d["pls_res"] = {"accuracy_cv":   pls.accuracy_cv,
                              "permutation":   pls.permutation,
                              "scores":        pls.scores,
                              "vip":           pls.vip,
                              "classes":       pls.classes_,
                              "n_components":  pls.n_components,
                              "groups":        list(plsda_groups),
                              "n_permutations": int(n_perm)}

        return html.Div([
            _card(dcc.Graph(figure=pca_fig, config={"displayModeBar": False}),
                    dcc.Graph(figure=scree,   config={"displayModeBar": False}),
                    title="PCA · scores PC1–PC2 + scree"),
            pls_card or _info("Selecciona ≥ 2 grupos en el dropdown para correr PLS-DA.",
                                  "info"),
        ]), dash.no_update
    except Exception as e:
        return _err_panel(e), dash.no_update


def _pca_scores_fig(pca, groups):
    fig = go.Figure()
    g_unique = list(pd.unique(groups.dropna())) or ["—"]
    palette = {g: SPAL[i % len(SPAL)] for i, g in enumerate(g_unique)}

    for g in g_unique:
        mask = [s in pca.scores.index and groups.get(s) == g
                  for s in pca.scores.index]
        sub = pca.scores.loc[mask]
        fig.add_trace(go.Scatter(
            x=sub["PC1"], y=sub["PC2"], mode="markers+text",
            name=str(g),
            marker=dict(color=palette[g], size=10, line=dict(color="white", width=1)),
            text=sub.index, textposition="top center",
            textfont=dict(size=8, color=PAL["muted"]),
        ))
        # Ellipse
        ell = pca.ellipses.get(g)
        if ell is not None and len(ell):
            fig.add_trace(go.Scatter(
                x=ell[:, 0], y=ell[:, 1], mode="lines",
                line=dict(color=palette[g], dash="dot", width=1.5),
                name=f"95% T² {g}", showlegend=False,
                hoverinfo="skip",
            ))

    pc1_var = pca.explained_variance_ratio[0] * 100
    pc2_var = pca.explained_variance_ratio[1] * 100 if pca.n_components >= 2 else 0
    fig.update_layout(
        title="PCA · scores con elipses 95 % de Hotelling",
        xaxis_title=f"PC1 ({pc1_var:.1f}%)",
        yaxis_title=f"PC2 ({pc2_var:.1f}%)",
        **P_LAYOUT)
    return fig


def _plsda_scores_fig(pls, groups):
    fig = go.Figure()
    g_unique = list(pls.classes_)
    palette = {g: SPAL[i % len(SPAL)] for i, g in enumerate(g_unique)}

    for g in g_unique:
        mask = [s in pls.scores.index and groups.get(s) == g
                  for s in pls.scores.index]
        sub = pls.scores.loc[mask]
        if "Comp2" in sub.columns:
            fig.add_trace(go.Scatter(
                x=sub["Comp1"], y=sub["Comp2"], mode="markers+text",
                marker=dict(color=palette[g], size=11,
                              line=dict(color="white", width=1)),
                name=str(g), text=sub.index, textposition="top center",
                textfont=dict(size=8, color=PAL["muted"]),
            ))
        else:
            fig.add_trace(go.Scatter(
                x=sub["Comp1"], y=[0] * len(sub), mode="markers+text",
                marker=dict(color=palette[g], size=11),
                name=str(g), text=sub.index, textposition="top center",
            ))
    fig.update_layout(title="PLS-DA · scores",
                       xaxis_title="Comp 1", yaxis_title="Comp 2", **P_LAYOUT)
    return fig


# =============================================================================
# ⑤ Heatmap callback
# =============================================================================

@callback(
    Output("hm-results", "children"),
    Output("stats-key",  "data", allow_duplicate=True),
    Input("hm-run", "n_clicks"),
    State("hm-top",    "value"),
    State("hm-clus-s", "value"),
    State("hm-clus-f", "value"),
    State("hm-group-order", "value"),
    State("stats-key", "data"),
    prevent_initial_call=True,
)
def _run_hm(_n, top_n, clus_s, clus_f, group_order, key):
    if not _n:
        raise PreventUpdate
    try:
        d = cload(key)
        if not d or not d.get("pp_done"):
            return _info("Aplica preprocesado primero.", "warn"), dash.no_update

        data = d["pp_data"]
        var = data.var(axis=1).sort_values(ascending=False)
        top_feats = var.head(int(top_n)).index
        sub = data.loc[top_feats].copy()

        groups_raw = _groups_series(d)  # indexed by data column
        # Keep only columns that actually have a group assignment
        cols_with_group = [c for c in sub.columns if pd.notna(groups_raw.get(c))]
        if not cols_with_group:
            return _info("Ninguna muestra tiene grupo asignado — revisa la "
                           "plantilla.", "err"), dash.no_update
        sub = sub[cols_with_group]
        groups = groups_raw.loc[cols_with_group]

        cluster_samples = clus_s == "yes"
        cluster_features = clus_f == "yes"

        # Sample ordering: cluster wins if enabled; otherwise group by group
        if cluster_samples and sub.shape[1] >= 3:
            try:
                from scipy.cluster.hierarchy import linkage, leaves_list
                from scipy.spatial.distance import pdist
                order = leaves_list(linkage(pdist(sub.T.values), method="average"))
                sub = sub.iloc[:, order]
                groups = groups.loc[sub.columns]
            except Exception:
                pass
        else:
            # Sort columns by group (user order if provided, else input order)
            g_order = (group_order if group_order
                        else list(pd.unique(groups.dropna())))
            # Stable sort: first by the index of the group in g_order, then by sample
            key_fn = {c: (g_order.index(g) if g in g_order else 999)
                      for c, g in groups.items()}
            sub = sub[sorted(sub.columns, key=lambda c: (key_fn[c], c))]
            groups = groups.loc[sub.columns]

        # Feature ordering
        if cluster_features and sub.shape[0] >= 3:
            try:
                from scipy.cluster.hierarchy import linkage, leaves_list
                from scipy.spatial.distance import pdist
                order = leaves_list(linkage(pdist(sub.values), method="average"))
                sub = sub.iloc[order, :]
            except Exception:
                pass

        # Friendly sample labels (use rename_map → sample name)
        rename = d.get("rename_map", {})
        display_cols = [rename.get(c, c) for c in sub.columns]

        # Center per feature for visual contrast (robust z-score alternative)
        centered = sub.sub(sub.mean(axis=1), axis=0)

        # ── Build figure with group annotation bar + heatmap using subplots ─
        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.04, 0.96],
            vertical_spacing=0.02,
        )

        # Group → color map
        g_uniq = list(pd.unique(groups))
        gpal = {g: SPAL[i % len(SPAL)] for i, g in enumerate(g_uniq)}
        g_idx = {g: i for i, g in enumerate(g_uniq)}
        bar_z = np.array([[g_idx[groups[c]] for c in sub.columns]])
        # Discrete colorscale for the group bar
        if len(g_uniq) == 1:
            gscale = [[0, gpal[g_uniq[0]]], [1, gpal[g_uniq[0]]]]
        else:
            gscale = [[i / max(1, len(g_uniq) - 1), gpal[g]]
                      for i, g in enumerate(g_uniq)]
        fig.add_trace(go.Heatmap(
            z=bar_z, x=display_cols, y=["grupo"],
            colorscale=gscale, showscale=False,
            hovertemplate="<b>%{x}</b><br>grupo=%{text}<extra></extra>",
            text=[[groups[c] for c in sub.columns]],
            zmin=0, zmax=max(1, len(g_uniq) - 1),
        ), row=1, col=1)

        # Main heatmap
        fig.add_trace(go.Heatmap(
            z=centered.values,
            x=display_cols,
            y=list(centered.index),
            colorscale="RdBu_r",
            zmid=0,
            colorbar=dict(title="Δ vs media", len=0.75, y=0.45),
            hovertemplate="<b>%{y}</b> · %{x}<br>valor=%{z:.3f}<extra></extra>",
        ), row=2, col=1)

        # Legend-style annotations for groups (one coloured tag per group)
        annotations = []
        for i, g in enumerate(g_uniq):
            annotations.append(dict(
                xref="paper", yref="paper",
                x=0.01 + i * 0.12, y=1.04,
                text=f"<span style='color:{gpal[g]};font-weight:700;'>■</span> {g}",
                showarrow=False, font=dict(size=10, family="Inter,sans-serif"),
            ))

        fig.update_xaxes(showticklabels=False, row=1, col=1)
        fig.update_yaxes(showticklabels=True, row=1, col=1,
                         tickfont=dict(size=9, color=PAL["muted"]))
        fig.update_xaxes(tickangle=45, tickfont=dict(size=9),
                         showticklabels=True, row=2, col=1)
        fig.update_yaxes(tickfont=dict(size=9), row=2, col=1)
        fig.update_layout(
            title=(f"Heatmap · top {top_n} features · "
                   f"{'cluster muestras' if cluster_samples else 'por grupo'} × "
                   f"{'cluster features' if cluster_features else 'por varianza'}"),
            height=max(520, 14 * len(centered.index) + 140),
            **{**P_LAYOUT, "margin": dict(l=160, r=40, t=72, b=110)},
            annotations=annotations,
        )

        d["hm_res"] = {"top": top_n,
                         "clus_s": cluster_samples,
                         "clus_f": cluster_features,
                         "group_order": list(groups.unique()),
                         "matrix": centered}

        return html.Div([
            _card(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                    title="Heatmap"),
        ]), dash.no_update
    except Exception as e:
        return _err_panel(e), dash.no_update


# =============================================================================
# ⑥ Biomarkers callback
# =============================================================================

@callback(
    Output("bm-results", "children"),
    Output("stats-key",  "data", allow_duplicate=True),
    Input("bm-run", "n_clicks"),
    State("bm-a", "value"),
    State("bm-b", "value"),
    State("bm-boot", "value"),
    State("bm-topn", "value"),
    State("stats-key", "data"),
    prevent_initial_call=True,
)
def _run_bm(_n, a, b, n_boot, top_n, key):
    if not _n:
        raise PreventUpdate
    try:
        d = cload(key)
        if not d or not d.get("pp_done"):
            return _info("Aplica preprocesado primero.", "warn"), dash.no_update
        if a == b:
            return _info("Elige dos grupos diferentes.", "warn"), dash.no_update

        groups = _groups_series(d)
        try:
            bm = biomarker_table(d["pp_data"], groups, a, b,
                                  n_boot=int(n_boot), random_state=7,
                                  top_n=int(top_n))
        except Exception as e:
            return _err_panel(e), dash.no_update

        bm_disp = _attach_display_name(bm, d, feature_col="feature")
        for c in ("AUC", "CI_lo", "CI_hi", "p_mwu"):
            bm_disp[c] = bm_disp[c].apply(
                lambda v, _c=c: f"{v:.3f}" if pd.notna(v) and _c != "p_mwu"
                            else (f"{v:.3e}" if pd.notna(v) else "—"))
        # Display order: Name first (more readable), then bucket label
        bm_disp = bm_disp[["Name", "feature", "AUC", "CI_lo", "CI_hi", "p_mwu"]]

        # Top-3 ROC curves — use the friendly Name in the legend
        from core.stats_biomarker import roc_auc_single
        roc_fig = go.Figure()
        # Build a feature → display-name map once
        meta = (d or {}).get("label_meta") or {}
        nmap = meta.get("name") or {}
        omap = meta.get("orig_label") or {}
        def _disp(lab):
            nm = nmap.get(lab, "")
            return (str(nm).strip() if not _placeholder_name(nm)
                     else str(omap.get(lab, lab)))
        for i, feat in enumerate(bm["feature"].head(3)):
            roc = roc_auc_single(d["pp_data"], groups, feat, a, b)
            if len(roc.fpr):
                roc_fig.add_trace(go.Scatter(
                    x=roc.fpr, y=roc.tpr, mode="lines",
                    line=dict(color=SPAL[i], width=2),
                    name=f"{_disp(feat)} · AUC={roc.auc:.3f}",
                ))
        roc_fig.add_trace(go.Scatter(
            x=[0, 1], y=[0, 1], mode="lines",
            line=dict(color="gray", dash="dash"), showlegend=False))
        roc_fig.update_layout(
            title=f"Top 3 features · ROC curves ({a} vs {b})",
            xaxis_title="FPR", yaxis_title="TPR",
            **P_LAYOUT)

        d["bm_res"] = {"a": a, "b": b, "n_boot": int(n_boot), "top": bm}

        return html.Div([
            _card(dcc.Graph(figure=roc_fig, config={"displayModeBar": False}),
                    title=f"ROC · {a} vs {b}"),
            _card(
                dash_table.DataTable(
                    data=bm_disp.to_dict("records"),
                    columns=[{"name": c, "id": c} for c in bm_disp.columns],
                    page_size=20, sort_action="native",
                    style_cell={"fontSize": "11px", "fontFamily": "monospace",
                                  "padding": "4px 8px", "textAlign": "left"},
                    style_header={"backgroundColor": PAL["dark"],
                                   "color": "white", "fontWeight": "700"},
                ),
                title=f"Top {top_n} biomarcadores",
            ),
        ]), dash.no_update
    except Exception as e:
        return _err_panel(e), dash.no_update
