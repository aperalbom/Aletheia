"""
pages/proteomics.py — IMSMI Clinical Proteomics Service
Generador de informes, Dashboard y DIA-PASEF Viewer.
"""

import dash
from dash import html, dcc, Input, Output, State, callback
from dash.exceptions import PreventUpdate
import io
from pathlib import Path
from datetime import date
import pandas as pd

dash.register_page(__name__, path="/proteomics", name="Generador de Informe — Proteómica")

# =============================================================================
# COLORES
# =============================================================================

TEAL  = "#4A9B8F"
DARK  = "#2C2C2A"
CREAM = "#F7F6F2"
MUTED = "#888780"
BORDER= "#E4E2DC"
AMBER = "#E8A838"
CORAL = "#C0756A"
SLATE = "#6A7FA8"

# =============================================================================
# CONSTANTES
# =============================================================================

COL_OPTIONS = [
    "Columna corta - 60 SPD (21 min)  |  PepSep 8 cm x 150 um, 1.5-um C18, 40 C",
    "Columna larga - 30 SPD (44 min)  |  PepSep 15 cm x 150 um, 1.9-um C18, 60 C",
    "WhisperZoom - 40 SPD (32 min)  |  Aurora Elite CSI C18, 15 cm x 75 um, 1.7-um, 50 C",
    "WhisperZoom - 20 SPD (72 min)  |  Aurora Elite CSI C18, 15 cm x 75 um, 1.7-um, 50 C",
]

LC_TEXT = {
    "short": [
        ("Purified tryptic digests were separated with the predefined ", False, False),
        ("60 SPD method (21-min gradient", True, False),
        (" time, 200 ng peptides) on an Evosep One LC system (Evosep) (5). "
         "A fused silica 10-\u03bcm ID emitter (Bruker Daltonics) was placed inside a "
         "nanoelectrospray source (CaptiveSpray source, Bruker Daltonics). "
         "The emitter was connected to an ", False, False),
        ("8-cm \u00d7 150-\u03bcm reverse-phase column packed with 1.5-\u03bcm C18 beads", True, False),
        (" (PepSep column, Bruker Daltonics). The column was heated to 40 \u00baC. "
         "Mobile phases: water and acetonitrile buffered with 0.1% formic acid "
         "(LC-MS grade, Fisher Scientific).", False, False),
    ],
    "long": [
        ("Purified tryptic digests were separated with the predefined ", False, False),
        ("30 SPD method (44-min gradient", True, False),
        (" time, 200 ng peptides) on an Evosep One LC system (Evosep) (4). "
         "A fused silica 10-\u03bcm ID emitter (Bruker Daltonics) was placed inside a "
         "nanoelectrospray source (CaptiveSpray source, Bruker Daltonics). "
         "The emitter was connected to a ", False, False),
        ("15-cm \u00d7 150-\u03bcm reverse-phase column packed with 1.9-\u03bcm C18 beads", True, False),
        (" (PepSep Fifteen columns, Bruker Daltonics). The column was heated to 60 \u00baC. "
         "Mobile phases: water and acetonitrile buffered with 0.1% formic acid "
         "(LC-MS grade, Fisher Scientific).", False, False),
    ],
    "wz40": [
        ("Peptides were separated using the ", False, False),
        ("40 SPD Whisper method (32-min gradient", True, False),
        (", 200 ng peptides) on an Evosep One LC system (5). "
         "Chromatographic separation was achieved using an ", False, False),
        ("Aurora Elite CSI C18 column (15 cm \u00d7 75 \u03bcm, 1.7 \u03bcm particles", True, False),
        (", Bruker Daltonics). Column temperature was maintained at 50 \u00b0C. "
         "Mobile phases included water and acetonitrile with 0.1% formic acid "
         "(Thermo Fisher Scientific).", False, False),
    ],
    "wz20": [
        ("Peptides were separated using the ", False, False),
        ("20 SPD Whisper method (72-min gradient", True, False),
        (", 200 ng peptides) on an Evosep One LC system (5). "
         "Chromatographic separation was achieved using an ", False, False),
        ("Aurora Elite CSI C18 column (15 cm \u00d7 75 \u03bcm, 1.7 \u03bcm particles", True, False),
        (", Bruker Daltonics). Column temperature was maintained at 50 \u00b0C. "
         "Mobile phases included water and acetonitrile with 0.1% formic acid "
         "(Thermo Fisher Scientific).", False, False),
    ],
}

METCL_STEPS = [
    "To 100 \u03bcl of sample, add 400 \u03bcl of MetOH and vortex for 1 minute.",
    "Add 100 \u03bcl of CHCl\u2083 and vortex again for 1 minute.",
    "Add 300 \u03bcl of LC-MS water and vortex for 3 minutes.",
    "Centrifuge 2 min at 15,000 G; carefully remove the upper aqueous layer without disturbing other phases.",
    "Add 400 \u03bcl of MetOH, vortex 1 min, centrifuge 3 min at 15,000 G to pellet protein.",
    "Remove supernatant without disturbing the pellet.",
    "Air-dry pellet 5\u201310 min.",
    "Resuspend in 40 \u03bcL RapiGest\u00ae and heat 10 min at 40 \u00baC with gentle agitation.",
    "Sonicate 30 s / rest on ice 30 s using an ultrasonic bath. Repeat 5 times.",
]
ACET_STEPS = [
    "Transfer protein lysate (120 \u03bcL) to a clean 2 mL microcentrifuge tube.",
    "Add ice-cold acetone (\u221220 \u00baC), 4\u00d7 volume (480 \u03bcL). Mix briefly.",
    "Incubate 1 h at \u221220 \u00baC.",
    "Centrifuge 15 min at 13,000 rpm, 4 \u00baC.",
    "Carefully discard supernatant without disturbing the pellet.",
    "Air-dry pellet 5\u201310 min.",
    "Resuspend in 40 \u03bcL RapiGest\u00ae and heat 10 min at 40 \u00baC with gentle agitation.",
    "Sonicate 30 s / rest on ice 30 s using an ultrasonic bath. Repeat 5 times.",
]

# -----------------------------------------------------------------------------
# HPLC methods catalogue (extensible — add a new entry to expose a new method)
# -----------------------------------------------------------------------------
# Each method carries the metadata needed by `_chromatography_paragraph` to
# render section 3.1. LC when platform == "nanoelute" (Materials & Methods
# style prose, ready to be copy-pasted into a publication).
# Add a new key (e.g. "nanoelute2_60min": {...}) to expose another gradient
# in the form dropdown (id="prot-hplc-method"); it will flow through to the
# report automatically.
HPLC_METHODS = {
    "nanoelute2_36min": {
        "label": "nanoElute 2 — Aurora Ultimate C18 25 cm × 75 µm, 1.7 µm · 47 min total · 250 nL/min · 50 °C",
        "short_label": "nanoElute 2 · 47 min · 250 nL/min",
        "system": "nanoElute 2 (Bruker)",
        "column": "Aurora Ultimate C18 column (25 cm × 75 µm, 1.7 µm particles; IonOpticks, Australia)",
        "temperature": "50 °C",
        "flow_rate": "250 nL/min",
        "mobile_phases": "A = 0.1% formic acid in water; B = 0.1% formic acid in acetonitrile",
        # Total run-time label used as the bolded span inside the Materials &
        # Methods paragraph (mirrors Evosep's "21-min gradient" / "44-min
        # gradient" tokens). The 47-min value reflects the full method
        # duration, including the wash at 95 % B.
        "gradient_label": "47-min gradient",
        "gradient_total_min": 47,
        "gradient_description": (
            "2% B → 25% B at 30 min → 37% B at 36 min → 95% B at 37 min, "
            "held at 95% until 47 min; total run time: 47 min"
        ),
    },
}
DEFAULT_HPLC_METHOD = "nanoelute2_36min"

# =============================================================================
# HELPERS PYDIAID
# =============================================================================

def _parse_csv_quoted(text):
    rows = []
    for line in text.strip().split('\n'):
        fields, field, inq = [], '', False
        for i, c in enumerate(line):
            if inq:
                if c == '"' and i+1 < len(line) and line[i+1] == '"':
                    field += '"'
                elif c == '"':
                    inq = False
                else:
                    field += c
            else:
                if c == '"':
                    inq = True
                elif c == ',':
                    fields.append(field.strip()); field = ''
                else:
                    field += c
        fields.append(field.strip()); rows.append(fields)
    return pd.DataFrame(rows[1:], columns=rows[0]) if len(rows) > 1 else pd.DataFrame()


def _parse_dia_txt(text):
    cols = ['MS Type','Cycle Id','1/K0 Begin','1/K0 End','Start Mass [m/z]','End Mass [m/z]','CE [eV]']
    rows = []
    for line in text.split('\n'):
        if line.startswith('#') or not line.strip(): continue
        p = [x.strip() for x in line.split(',')]
        if len(p) >= 7: rows.append(p[:7])
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def _pyd_loader(folder):
    """Load pyDIAid output files; returns dict with json-serialisable data."""
    r = {'csv_rows': None, 'csv_cols': None,
         'txt_rows': None, 'txt_cols': None,
         'img_paths': [], 'err': None}
    p = Path(folder)
    if not p.exists() or not p.is_dir():
        r['err'] = f"Carpeta no encontrada: {folder}"; return r

    csv_candidates = (list(p.glob("final_method/*.csv")) +
                      list(p.glob("*.csv")) +
                      list(p.rglob("parameters_to_evaluate_method.csv")) +
                      list(p.rglob("*.csv")))
    csv_candidates = sorted(set(csv_candidates),
                            key=lambda f: (0 if "parameters_to_evaluate" in f.name else 1))
    if csv_candidates:
        try:
            df = _parse_csv_quoted(csv_candidates[0].read_text(encoding='utf-8', errors='replace'))
            if not df.empty:
                r['csv_rows'] = df.head(30).values.tolist()
                r['csv_cols'] = df.columns.tolist()
        except Exception as e:
            r['err'] = f"Error CSV: {e}"

    txt_candidates = (list(p.glob("final_method/*.txt")) +
                      list(p.glob("*.txt")) +
                      list(p.rglob("diaPASEF_method.txt")) +
                      list(p.rglob("*.txt")))
    txt_candidates = list(dict.fromkeys(txt_candidates))
    if txt_candidates:
        try:
            df2 = _parse_dia_txt(txt_candidates[0].read_text(encoding='utf-8', errors='replace'))
            if not df2.empty:
                r['txt_rows'] = df2.head(40).values.tolist()
                r['txt_cols'] = df2.columns.tolist()
        except Exception as e:
            r['err'] = (r['err'] or '') + f" Error TXT: {e}"

    img_order = [
        list(p.rglob("Histogram_precursor_distribution*.png")) + list(p.rglob("*Histogram*.png")),
        list(p.glob("input_library/Kernel_density*.png")) + list(p.rglob("*Kernel_density_distribution_library*.png")),
        list(p.glob("final_method/Kernel_density*.png")) + list(p.glob("final_method/*.png")) + list(p.rglob("*final_method*.png")),
    ]
    seen = set()
    for candidates in img_order:
        for img in candidates:
            if img not in seen:
                r['img_paths'].append(str(img)); seen.add(img); break
    for ext in ['*.png','*.PNG','*.jpg','*.JPG']:
        for img in sorted(p.rglob(ext)):
            if img not in seen:
                r['img_paths'].append(str(img)); seen.add(img)
    return r

# =============================================================================
# HELPERS UI
# =============================================================================

def _lbl(text):
    return html.Div(text, style={
        "fontSize":"10px","fontWeight":"600","letterSpacing":".07em",
        "textTransform":"uppercase","color":MUTED,
        "fontFamily":"monospace","marginBottom":"4px","marginTop":"12px",
    })

def _inp():
    return {
        "width":"100%","padding":"7px 10px","border":f"1px solid {BORDER}",
        "borderRadius":"6px","fontSize":"12px","fontFamily":"monospace",
        "boxSizing":"border-box","background":"#fff",
    }

def _card(title, children, extra_style=None):
    s = {"background":"#fff","border":f"1px solid {BORDER}","borderRadius":"10px",
         "padding":"1.2rem 1.4rem","marginBottom":"1rem"}
    if extra_style:
        s.update(extra_style)
    return html.Div(style=s, children=[
        html.Div(title, style={"fontSize":"10px","fontWeight":"600","letterSpacing":".07em",
                               "textTransform":"uppercase","color":MUTED,
                               "fontFamily":"monospace","marginBottom":"1rem"}),
        *children,
    ])

def _radio_items(rid, options, value=None, inline=False):
    opts = [{"label": f" {o['label']}", "value": o["value"]} if isinstance(o, dict)
            else {"label": f" {o}", "value": o} for o in options]
    lbl_s = {"display":"flex","gap":".5rem","flexDirection":"row" if inline else "column",
             "flexWrap":"wrap","alignItems":"flex-start",
             "background":"#fff","border":f"1px solid {BORDER}","borderRadius":"6px",
             "padding":"7px 12px","margin":"2px 0","fontSize":"12px","cursor":"pointer"}
    return dcc.RadioItems(
        id=rid, options=opts, value=value or opts[0]["value"],
        style={"display":"flex","gap":"6px",
               "flexDirection":"row" if inline else "column"},
        labelStyle=lbl_s,
    )

# CSS injected into the preview iframe
PREVIEW_CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Calibri, sans-serif; font-size: 12px; color: {DARK}; padding: 20px 24px; background: #fff; }}
.pv-title {{ font-size: 17px; font-weight: 700; color: {DARK}; margin-bottom: 2px; }}
.pv-sub {{ font-size: 10px; color: {MUTED}; border-bottom: 2px solid {TEAL}; padding-bottom: 8px; margin-bottom: 14px; }}
.pv-h1 {{ font-size: 13px; font-weight: 700; color: {DARK}; text-transform: uppercase;
           background: #f0f9f8; border-left: 4px solid {TEAL}; padding: 6px 12px;
           margin: 18px 0 8px; letter-spacing: .02em; }}
.pv-h2 {{ font-size: 12px; font-weight: 700; color: {TEAL}; text-transform: uppercase; margin: 12px 0 5px; }}
.pv-h3 {{ font-size: 11px; font-weight: 700; color: {TEAL}; text-transform: uppercase; margin: 8px 0 4px; opacity: .85; }}
.pv-kv {{ font-size: 12px; margin: 4px 0; }}
.pv-k  {{ font-weight: 600; color: {TEAL}; }}
.pv-flow {{ display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 8px 0 12px; }}
.pv-step {{ background: {DARK}; color: #fff; font-size: 10px; font-weight: 600; padding: 4px 10px; border-radius: 4px; }}
.pv-arr {{ color: {MUTED}; font-size: 12px; }}
table.pv-tbl {{ border-collapse: collapse; width: 100%; font-size: 10px; margin: 8px 0 12px; }}
table.pv-tbl th {{ background: {TEAL}; color: #fff; padding: 5px 8px; text-align: left; font-weight: 600; }}
table.pv-tbl td {{ padding: 4px 8px; border-bottom: 1px solid {BORDER}; }}
table.pv-tbl tr:nth-child(even) td {{ background: #f2f9f8; }}
"""

# =============================================================================
# LAYOUT
# =============================================================================

TAB_STYLE = {
    "background":"transparent","border":f"1px solid {BORDER}",
    "borderRadius":"6px 6px 0 0","color":MUTED,"fontSize":"12px",
    "fontWeight":"600","padding":"7px 20px","fontFamily":"monospace",
}
STAB_STYLE = {
    "background":TEAL,"color":"#fff","border":f"1px solid {TEAL}",
    "borderRadius":"6px 6px 0 0","fontSize":"12px","fontWeight":"600",
    "padding":"7px 20px","fontFamily":"monospace",
}




def layout():
    today = date.today().isoformat()

    # ── Form column ─────────────────────────────────────────────────
    form_col = html.Div(style={"flex":"0 0 48%","minWidth":"340px"}, children=[

        # Datalists for autocomplete suggestions (populated by
        # _refresh_prot_datalists from sample_history.json).
        html.Datalist(id="dl-prot-sol",        children=[]),
        html.Datalist(id="dl-prot-user",       children=[]),
        html.Datalist(id="dl-prot-ssub",       children=[]),
        html.Datalist(id="dl-prot-sorg",       children=[]),
        html.Datalist(id="dl-prot-inst",       children=[]),
        html.Datalist(id="dl-prot-email",      children=[]),
        html.Datalist(id="dl-prot-genby",      children=[]),
        html.Datalist(id="dl-prot-cond",       children=[]),
        html.Datalist(id="dl-prot-nsamp",      children=[]),
        html.Datalist(id="dl-prot-fasta",      children=[]),
        html.Datalist(id="dl-prot-fasta-date", children=[]),
        html.Datalist(id="dl-prot-val-name",   children=[]),

        # Identificación
        _card("① Identificación de la solicitud", [
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"10px"}, children=[
                html.Div([_lbl("N.º de solicitud"),
                          dcc.Input(id="prot-sol", type="text", placeholder="SOL202XXXX",
                                    debounce=False, **{"list":"dl-prot-sol"},
                                    style=_inp())]),
                html.Div([
                    _lbl("Usuario"),
                    dcc.Input(id="prot-user", type="text", placeholder="Nombre del usuario",
                              debounce=False, **{"list":"dl-prot-user"},
                              style=_inp()),
                ]),
                html.Div([_lbl("Institución / PI"), dcc.Input(id="prot-inst", type="text", placeholder="Institución",
                          **{"list":"dl-prot-inst"}, style=_inp())]),
                html.Div([_lbl("Email"), dcc.Input(id="prot-email", type="text", placeholder="usuario@inst.es",
                          **{"list":"dl-prot-email"}, style=_inp())]),
                html.Div([_lbl("Fecha del informe"), dcc.Input(id="prot-rdate", type="date", value=today, style=_inp())]),
                html.Div([_lbl("Generado por"), dcc.Input(id="prot-genby", type="text", value="Angela Peralbo Molina, PhD.",
                          **{"list":"dl-prot-genby"}, style=_inp())]),
            ]),
            # ── Histórico de muestras por usuario ──────────────────────
            html.Div(id="prot-hist-panel", style={"display":"none","marginTop":"10px"}, children=[
                html.Div(style={
                    "background":f"linear-gradient(135deg,{TEAL}18,{SLATE}10)",
                    "border":f"1px solid {TEAL}55","borderRadius":"8px","padding":"10px 12px",
                }, children=[
                    html.Div("🕐  Sample history for this user", style={
                        "fontSize":"9px","fontWeight":"700","letterSpacing":".1em",
                        "color":TEAL,"fontFamily":"monospace","textTransform":"uppercase","marginBottom":"6px",
                    }),
                    dcc.Dropdown(id="prot-hist-select",
                        placeholder="Select a previous sample configuration…",
                        style={"fontSize":"11px","fontFamily":"monospace"},
                        clearable=True),
                    html.Div(id="prot-hist-preview",
                             style={"fontSize":"10px","color":MUTED,"fontFamily":"monospace",
                                    "marginTop":"5px","minHeight":"14px"}),
                ]),
            ]),
        ]),

        # Información del estudio
        _card("② Información de la solicitud", [
            _lbl("Descripción del estudio"),
            dcc.Textarea(id="prot-desc", placeholder="Brief study objective and description…",
                         style={"width":"100%","height":"70px","fontFamily":"monospace","fontSize":"11px",
                                "padding":"7px","border":f"1px solid {BORDER}","borderRadius":"6px",
                                "resize":"vertical","boxSizing":"border-box"}),
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"10px"}, children=[
                html.Div([_lbl("Number of samples"), dcc.Input(id="prot-nsamp", type="text", placeholder="e.g. 38",
                          **{"list":"dl-prot-nsamp"}, style=_inp())]),
                html.Div([_lbl("Comparison / conditions"), dcc.Input(id="prot-cond", type="text", placeholder="e.g. condition A vs B",
                          **{"list":"dl-prot-cond"}, style=_inp())]),
            ]),
            # ── Structured sample type ──────────────────────────────────
            _lbl("Sample type"),
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr 1fr","gap":"8px"}, children=[
                html.Div([
                    html.Div("Category", style={"fontSize":"9px","color":MUTED,"fontFamily":"monospace",
                                                "marginBottom":"3px","textTransform":"uppercase","letterSpacing":".05em"}),
                    dcc.Dropdown(id="prot-scat",
                        options=[
                            {"label":"Tissue",           "value":"tissue"},
                            {"label":"Cell culture",     "value":"cell_culture"},
                            {"label":"Plasma",           "value":"plasma"},
                            {"label":"Serum",            "value":"serum"},
                            {"label":"Urine",            "value":"urine"},
                            {"label":"PBMC",             "value":"pbmc"},
                            {"label":"CSF",              "value":"csf"},
                            {"label":"Extracellular vesicles","value":"ev"},
                            {"label":"Other",            "value":"other"},
                        ],
                        placeholder="Category…",
                        style={"fontSize":"11px","fontFamily":"monospace"},
                        clearable=True),
                ]),
                html.Div([
                    html.Div("Sub-type / tissue name", style={"fontSize":"9px","color":MUTED,"fontFamily":"monospace",
                                                               "marginBottom":"3px","textTransform":"uppercase","letterSpacing":".05em"}),
                    dcc.Input(id="prot-ssub", type="text",
                              placeholder="e.g. pituitary gland, HeLa",
                              debounce=False, **{"list":"dl-prot-ssub"},
                              style=_inp()),
                ]),
                html.Div([
                    html.Div("Organism", style={"fontSize":"9px","color":MUTED,"fontFamily":"monospace",
                                                "marginBottom":"3px","textTransform":"uppercase","letterSpacing":".05em"}),
                    dcc.Input(id="prot-sorg", type="text",
                              placeholder="e.g. Homo sapiens",
                              debounce=False, **{"list":"dl-prot-sorg"},
                              style=_inp()),
                ]),
            ]),
            # Hidden legacy field (still used by existing callbacks as combined string)
            dcc.Input(id="prot-stype", type="hidden", value=""),
        ]),

        # Recepción
        _card("③ Recepción", [
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"10px"}, children=[
                html.Div([
                    _lbl("Fecha de recepción"),
                    dcc.Input(id="prot-recdate", type="date", value=today, style=_inp()),
                    _lbl("Condición de llegada"),
                    _radio_items("prot-rec",
                        [{"label":"Hielo (4 °C)","value":"ice4"}, {"label":"Hielo seco (−65 °C)","value":"ice65"}],
                        value="ice4", inline=True),
                ]),
                html.Div([
                    _lbl("Almacenamiento IMSMI"),
                    _radio_items("prot-sto",
                        [{"label":"−20 °C","value":"-20"}, {"label":"−80 °C","value":"-80"}],
                        value="-20", inline=True),
                ]),
            ]),
        ]),

        # Preparación de muestra
        _card("④ Preparación de muestra", [
            _lbl("Estado de las muestras"),
            _radio_items("prot-prep",
                [{"label":"Muestras ya preparadas (péptidos digeridos)","value":"ready"},
                 {"label":"Hay que preparar las muestras","value":"todo"}],
                value="ready"),

            # "Ready" section
            html.Div(id="prot-prep-ready", children=[
                _lbl("µl por muestra para el QC pool"),
                dcc.Input(id="prot-qcvol", type="number", value=5, min=1, max=200, style={**_inp(),"width":"120px"}),

                # ── Limpieza ZipTip (péptidos ya digeridos) ──────────────
                # Si se marca, el M&M incluye el protocolo completo de
                # limpieza con ZipTip C18 antes del SpeedVac / reconstitución,
                # y la frase de reconstitución se ajusta a 12 µL de
                # 2% ACN / 0.2% TFA (protocolo IMSMI).
                html.Div(style={"marginTop":"10px"}, children=[
                    dcc.Checklist(
                        id="prot-ziptip",
                        options=[{
                            "label": (" Limpieza con ZipTip C₁₈ antes de LC-MS "
                                      "(muestras ya digeridas, protocolo IMSMI)"),
                            "value": "on",
                        }],
                        value=[],
                        style={"fontSize":"12px","fontFamily":"monospace",
                               "margin":"4px 0 0"},
                        inputStyle={"marginRight":"6px"},
                    ),
                    html.Small(
                        "Tres lavados con ACN 70% + TFA 0.1%, equilibrado en "
                        "ACN 2% + TFA 0.1%, 20 ciclos de carga, tres lavados, "
                        "elución con ACN 70% + TFA 0.1%, secado en SpeedVac y "
                        "resuspensión en 12 µL de ACN 2% + TFA 0.2%.",
                        style={
                            "display":"block","fontSize":"11px","color":MUTED,
                            "lineHeight":"1.45","margin":"4px 0 0 22px",
                            "fontFamily":"monospace",
                        },
                    ),
                ]),

                # ── Pool de QC (opcional, marcado por defecto) ─────────────
                # Cuando se deselecciona, el M&M omite la frase del pool de
                # QC y se reporta solo el estándar HeLa como referencia
                # externa de monitorización del instrumento.
                html.Div(style={"marginTop":"10px"}, children=[
                    dcc.Checklist(
                        id="prot-qc",
                        options=[{
                            "label": " Preparar pool de QC a partir de las muestras",
                            "value": "on",
                        }],
                        value=["on"],
                        style={"fontSize":"12px","fontFamily":"monospace",
                               "margin":"4px 0 0"},
                        inputStyle={"marginRight":"6px"},
                    ),
                ]),

                # ── Cuantificación previa con Qubit (opcional) ─────────────
                # Para muestras ya digeridas, permite añadir un paso de
                # cuantificación con Qubit antes de cargar las muestras en
                # los Evotips (o en los viales del autosampler de nanoElute).
                html.Div(style={"marginTop":"6px"}, children=[
                    dcc.Checklist(
                        id="prot-qubit-ready",
                        options=[{
                            "label": (" Cuantificar péptidos con Qubit antes de "
                                      "cargar (Evotips / autosampler)"),
                            "value": "on",
                        }],
                        value=[],
                        style={"fontSize":"12px","fontFamily":"monospace",
                               "margin":"4px 0 0"},
                        inputStyle={"marginRight":"6px"},
                    ),
                    html.Small(
                        "Útil tras ZipTip u otras limpiezas para confirmar "
                        "recuperación y normalizar la cantidad inyectada.",
                        style={
                            "display":"block","fontSize":"11px","color":MUTED,
                            "lineHeight":"1.45","margin":"4px 0 0 22px",
                            "fontFamily":"monospace",
                        },
                    ),
                ]),

                # ── Reconstitución (solo nanoElute) ─────────────────────
                # Evosep usa SIEMPRE 10 ng/µL · 20 µL/Evotip (fijo en el
                # informe). Para nanoElute, hay 2 opciones: el preset
                # estándar (100 ng/µL, 2 µL por muestra) o personalizado
                # (volumen de reconstitución + volumen de inyección libres).
                # Visibilidad: _toggle_recon_wrap (platform==nanoelute).
                html.Div(
                    id="prot-recon-wrap",
                    style={"display":"none", "marginTop":"10px"},
                    children=[
                        _lbl("Reconstitución (nanoElute)"),
                        _radio_items(
                            "prot-recon",
                            [{"label":"Reconstituir a 100 ng/µL, inyectar 2 µL por muestra",
                              "value":"std100"},
                             {"label":"Personalizado",
                              "value":"custom"}],
                            value="std100",
                        ),
                        html.Div(
                            id="prot-recon-custom-wrap",
                            style={"display":"none", "margin":"4px 0 0 18px"},
                            children=[
                                html.Div(style={"display":"flex","gap":"12px","flexWrap":"wrap"}, children=[
                                    html.Div([
                                        _lbl("Volumen reconstitución (µL)"),
                                        dcc.Input(id="prot-recon-vol", type="number",
                                                  value=30, min=1, max=500,
                                                  style={**_inp(),"width":"120px"}),
                                    ]),
                                    html.Div([
                                        _lbl("Volumen inyección (µL)"),
                                        dcc.Input(id="prot-recon-inj", type="number",
                                                  value=1, min=0.1, max=20, step=0.1,
                                                  style={**_inp(),"width":"120px"}),
                                    ]),
                                ]),
                                html.Small(
                                    "Se usarán literalmente en el informe: "
                                    "«reconstituted in X µL …, such that a Y µL "
                                    "injection yields 200 ng per sample».",
                                    style={
                                        "display":"block","fontSize":"11px","color":MUTED,
                                        "lineHeight":"1.45","margin":"4px 0 0",
                                        "fontFamily":"monospace",
                                    },
                                ),
                            ],
                        ),
                    ],
                ),
            ]),

            # "Todo" section
            html.Div(id="prot-prep-todo", style={"display":"none"}, children=[
                _lbl("Tipo de muestra"),
                _radio_items("prot-st",
                    [{"label":"Muestra líquida","value":"liquid"}, {"label":"Tejido","value":"tissue"}],
                    value="liquid", inline=True),
                html.Div(id="prot-tissue-callout", style={"display":"none"}, children=[
                    html.Div(style={
                        "background":"#FFF8EC","border":f"1px solid #F0D080","borderRadius":"6px",
                        "padding":"10px 14px","fontSize":"12px","color":"#7A5200",
                        "margin":"8px 0 10px","lineHeight":"1.5",
                    }, children=[
                        html.Strong("Tejido:", style={"color":"#C8861E"}),
                        " Se añadirá paso con Beatbox (PreOmics). La precipitación de proteínas es ",
                        html.Strong("obligatoria.", style={"color":"#C8861E"}),
                    ]),
                ]),
                _lbl("Precipitación de proteínas"),
                _radio_items("prot-precip",
                    [{"label":"MeOH : CHCl₃ (protocolo IMSMI)","value":"meoh"},
                     {"label":"Acetona fría (−20 °C)","value":"acet"},
                     {"label":"Sin precipitación","value":"none"}],
                    value="meoh"),
                html.Div(id="prot-precip-warning", style={"display":"none"}, children=[
                    html.Div("⚠ Sin precipitación no disponible para tejido.", style={
                        "background":"#fef9ec","border":f"1px solid {AMBER}","borderLeft":f"4px solid {AMBER}",
                        "borderRadius":"6px","padding":"8px 12px","fontSize":"12px",
                        "color":"#854F0B","fontFamily":"monospace","margin":"6px 0",
                    }),
                ]),
                _lbl("µl por muestra para el QC pool"),
                dcc.Input(id="prot-qcvol2", type="number", value=5, min=1, max=200, style={**_inp(),"width":"120px"}),
            ]),
        ]),

        # Adquisición LC-MS
        _card("⑤ Adquisición LC-MS", [
            _lbl("Plataforma LC-MS principal"),
            _radio_items("prot-platform",
                [{"label":"EvosepOne · timsTOF Flex","value":"evosep"},
                 {"label":"nanoElute2 · timsTOF Pro","value":"nanoelute"}],
                value="evosep", inline=True),
            # ── Combinación con la otra plataforma LC-MS ──────────────────
            # Cuando se marca, el M&M incluye un párrafo adicional indicando
            # que las mismas muestras se analizaron también en la otra
            # plataforma (Evosep ↔ nanoElute) para evaluar comparativamente
            # la cobertura del proteoma.
            dcc.Checklist(
                id="prot-also-on",
                options=[{
                    "label": (" Las mismas muestras se han analizado también en la "
                              "otra plataforma LC-MS (comparación de cobertura proteómica)"),
                    "value": "on",
                }],
                value=[],
                style={"fontSize":"12px","fontFamily":"monospace",
                       "margin":"4px 0 12px"},
                inputStyle={"marginRight":"6px"},
            ),
            _lbl("Modo de adquisición"),
            dcc.Checklist(id="prot-acq",
                options=[{"label":" DDA-PASEF","value":"dda"}, {"label":" DIA-PASEF","value":"dia"}],
                value=[], style={"display":"flex","gap":"1.5rem","fontSize":"13px","margin":"4px 0 10px"}),
            # ── Columna / gradiente (EvosepOne · timsTOF Flex) ─────────────
            # Visible only when plat = "evosep". Toggled by _toggle_lc_platform.
            html.Div(
                id="prot-evosep-wrap",
                children=[
                    _lbl("Columna / gradiente"),
                    _radio_items("prot-col", COL_OPTIONS, value=COL_OPTIONS[0]),
                ],
            ),

            # ── Método cromatográfico (nanoElute 2 · timsTOF Pro) ──────────
            # Extensible via HPLC_METHODS (add entries to expose new gradients).
            # Visible only when plat = "nanoelute". Toggled by _toggle_lc_platform.
            html.Div(
                id="prot-nanoelute-wrap",
                children=[
                    _lbl("Método cromatográfico (HPLC)"),
                    dcc.Dropdown(
                        id="prot-hplc-method",
                        options=[
                            {"label": meta["label"], "value": mid}
                            for mid, meta in HPLC_METHODS.items()
                        ],
                        value=DEFAULT_HPLC_METHOD,
                        clearable=False,
                        style={
                            "fontFamily":"monospace","fontSize":"12px",
                            "margin":"2px 0 4px",
                        },
                    ),

                    _lbl("Opciones del método"),
                    # Note: the app stack is pure dcc + html (no
                    # dash-bootstrap-components), so we use dcc.Checklist —
                    # it plays the same role as dbc.Checklist(switch=True).
                    dcc.Checklist(
                        id="prot-hplc-options",
                        options=[
                            {"label": " Extended Wash (recomendado para plasma; +10 min)",
                             "value": "extended_wash"},
                            {"label": " MS calibrant injection (vial 2 = IPA/H₂O 50:50 o ACN 100 %)",
                             "value": "ms_calibrant_injection"},
                        ],
                        value=[],  # ambos desactivados por defecto
                        style={
                            "display":"flex","flexDirection":"column","gap":"4px",
                            "fontSize":"12px","fontFamily":"monospace","margin":"4px 0 2px",
                        },
                        inputStyle={"marginRight":"6px"},
                    ),
                    html.Small(
                        "Para plasma se recomienda Extended Wash (minimiza carry-over "
                        "en la vía de inyección). MS calibrant injection previene la "
                        "obstrucción del capilar inyección–trap limpiándolo con "
                        "solvente orgánico al final de cada gradiente.",
                        style={
                            "display":"block","fontSize":"11px","color":MUTED,
                            "lineHeight":"1.45","margin":"2px 0 10px",
                            "fontFamily":"monospace",
                        },
                    ),
                ],
            ),

            _lbl("Software de análisis"),
            dcc.Checklist(id="prot-sw",
                options=[
                    {"label":" Spectronaut 20","value":"spec"},
                    {"label":" MSFragger / FragPipe","value":"frag"},
                    {"label":" MaxQuant","value":"maxq"},
                    {"label":" DIA-NN","value":"diann"},
                ],
                value=[], style={"display":"flex","gap":"1rem","flexWrap":"wrap","fontSize":"13px","margin":"4px 0"}),
            html.Div(id="prot-fasta-section", style={"display":"none"}, children=[
                html.Div(style={"display":"grid","gridTemplateColumns":"2fr 1fr","gap":"8px"}, children=[
                    html.Div([
                        _lbl("FASTA database / UniProt reference proteome"),
                        dcc.Input(id="prot-fasta", type="text",
                                  placeholder="e.g. UniProt Homo sapiens (20,421 entries)",
                                  **{"list":"dl-prot-fasta"},
                                  style=_inp()),
                    ]),
                    html.Div([
                        _lbl("FASTA version (month·year)"),
                        dcc.Input(id="prot-fasta-date", type="text",
                                  placeholder="e.g. April 2024",
                                  **{"list":"dl-prot-fasta-date"},
                                  style=_inp()),
                    ]),
                ]),
            ]),
        ]),

        # pyDIAid
        html.Div(id="prot-pyd-section", style={"display":"none"}, children=[
            _card("⑥ pyDIAid Data", [
                _lbl("pyDIAid output folder path"),
                dcc.Input(id="prot-pyd-path", type="text",
                          placeholder=r"C:\Users\Angela\...\py_diAID",
                          style=_inp()),
                html.Div(id="prot-pyd-status", style={"marginTop":"8px","fontSize":"12px"}),
            ]),
        ]),

        # Validación del informe
        _card("✔ Report Validation", [
            html.Div(style={"display":"flex","alignItems":"center","gap":"12px","flexWrap":"wrap"}, children=[
                dcc.Checklist(
                    id="prot-validated",
                    options=[{"label": " Validated and approved for delivery by:", "value": "yes"}],
                    value=[],
                    style={"fontSize":"12px","fontFamily":"monospace"},
                ),
                dcc.Input(id="prot-val-name", type="text",
                          placeholder="Reviewer name",
                          value="Eduardo Chicano-Gálvez, PhD.",
                          **{"list":"dl-prot-val-name"},
                          style={**_inp(), "width":"240px", "marginTop":"0"}),
                dcc.Input(id="prot-val-date", type="date",
                          style={**_inp(), "width":"150px", "marginTop":"0"}),
            ]),
        ], extra_style={"borderTop": f"3px solid {AMBER}"}),

        # Botón descarga
        html.Button("⬇ Generate and download report (.docx)", id="prot-btn-docx",
                    style={
                        "background":TEAL,"color":"#fff","border":"none",
                        "borderRadius":"8px","fontSize":"13px","fontWeight":"700",
                        "padding":"12px 24px","width":"100%","cursor":"pointer",
                        "marginTop":"0.5rem","fontFamily":"monospace","letterSpacing":".04em",
                    }),
        html.Div(id="prot-docx-msg", style={"marginTop":"8px","fontSize":"12px"}),
        dcc.Store(id="prot-pyd-store",  data={}),
        dcc.Store(id="prot-hist-store", data={}),
        dcc.Download(id="prot-download-docx"),
    ])

    # ── Preview column ───────────────────────────────────────────────
    preview_col = html.Div(style={"flex":"0 0 48%","minWidth":"300px","position":"sticky","top":"1.5rem"}, children=[
        html.Div(style={
            "background":"#fff","border":f"1px solid {BORDER}","borderRadius":"10px",
            "padding":"12px","overflow":"hidden",
        }, children=[
            html.Div("Vista previa en tiempo real", style={
                "fontSize":"10px","fontWeight":"600","letterSpacing":".07em",
                "textTransform":"uppercase","color":MUTED,"fontFamily":"monospace","marginBottom":"8px",
            }),
            html.Iframe(id="prot-preview-iframe", srcDoc="<p style='color:#aaa;font-family:sans-serif;padding:20px'>Rellena el formulario para ver la vista previa.</p>",
                        style={"width":"100%","height":"680px","border":"none","borderRadius":"6px"}),
        ]),
    ])

    return html.Div([
        html.Div(className="page-header", children=[
            html.H1("Generador de Informe — Proteómica", className="page-title"),
            html.P("IMSMI · Clinical Proteomics Service · EvosepOne · timsTOF Flex",
                   className="page-sub"),
        ]),

        html.Div(style={
            "display":"flex","gap":"2rem","alignItems":"flex-start",
            "flexWrap":"wrap","paddingTop":"1rem",
        }, children=[form_col, preview_col]),
    ])


# =============================================================================
# CALLBACKS — MOSTRAR/OCULTAR SECCIONES CONDICIONALES
# =============================================================================

@callback(
    Output("prot-prep-ready", "style"),
    Output("prot-prep-todo",  "style"),
    Input("prot-prep", "value"),
)
def _toggle_prep(prep):
    show = {"display":"block"}
    hide = {"display":"none"}
    is_ready = prep == "ready"
    return (show, hide) if is_ready else (hide, show)


@callback(
    Output("prot-tissue-callout",   "style"),
    Output("prot-precip-warning",   "style"),
    Input("prot-st",     "value"),
    Input("prot-precip", "value"),
)
def _toggle_tissue(st, precip):
    callout_show = {"display":"block"} if st == "tissue" else {"display":"none"}
    warning_show = ({"display":"block"}
                    if st == "tissue" and precip == "none"
                    else {"display":"none"})
    return callout_show, warning_show


@callback(
    Output("prot-pyd-section", "style"),
    Input("prot-acq", "value"),
    Input("prot-col", "value"),
)
def _toggle_pyd(acq, col):
    acq = acq or []
    is_wz = col and ("40 SPD" in col or "20 SPD" in col) and "WhisperZoom" in col
    has_dia = "dia" in acq or is_wz
    return {"display":"block"} if has_dia else {"display":"none"}


# =============================================================================
# CALLBACK — CARGAR PYDIAID
# =============================================================================

@callback(
    Output("prot-pyd-store",  "data"),
    Output("prot-pyd-status", "children"),
    Input("prot-pyd-path", "value"),
)
def _load_pyd(path):
    if not path or not path.strip():
        return {}, ""
    r = _load_pyd_safe(path.strip())
    if r.get('err'):
        msg = html.Div(f"⚠ {r['err']}",
                       style={"color":CORAL,"fontFamily":"monospace","fontSize":"11px"})
        return r, msg

    csv_ok = r.get('csv_rows') is not None
    txt_ok = r.get('txt_rows') is not None
    n_imgs = len(r.get('img_paths', []))
    msg = html.Div(
        f"✓  {'CSV OK' if csv_ok else 'sin CSV'}  |  "
        f"{'TXT OK' if txt_ok else 'sin TXT'}  |  "
        f"{n_imgs} imagen(es)",
        style={"color":TEAL,"fontFamily":"monospace","fontSize":"11px","fontWeight":"600"},
    )
    return r, msg


def _load_pyd_safe(path):
    try:
        return _pyd_loader(path)
    except Exception as e:
        return {"err": str(e), "csv_rows":None, "csv_cols":None,
                "txt_rows":None, "txt_cols":None, "img_paths":[]}


# =============================================================================
# CALLBACKS — USER SAMPLE HISTORY  (shared across all services)
# =============================================================================

from sol_analyzer_dash.core import sample_history as _sh   # shared history module


# =============================================================================
# CALLBACK — LC-MS PLATFORM → show/hide column vs. HPLC-method blocks
# =============================================================================
# EvosepOne · timsTOF Flex  →  show the 4-option column radio (prot-col).
# nanoElute2 · timsTOF Pro  →  show the HPLC-method dropdown + options block.
# Only one of the two blocks is visible at a time; the other is display:none.
# =============================================================================

@callback(
    Output("prot-evosep-wrap",    "style"),
    Output("prot-nanoelute-wrap", "style"),
    Input("prot-platform",        "value"),
)
def _toggle_lc_platform(plat):
    show = {"display": "block"}
    hide = {"display": "none"}
    if plat == "nanoelute":
        return hide, show
    # Default → evosep (or any unexpected value)
    return show, hide


# =============================================================================
# CALLBACKS — Reconstitución (pre-digested samples)
# =============================================================================
# prot-recon-wrap : visible solo si platform == "nanoelute". Evosep usa un
#                   preset fijo (10 ng/µL · 20 µL/Evotip), por lo que no
#                   necesita UI adicional — el párrafo se emite tal cual.
# prot-recon-custom-wrap : visible solo si prot-recon == "custom".
# =============================================================================

@callback(
    Output("prot-recon-wrap", "style"),
    Input("prot-platform",    "value"),
)
def _toggle_recon_wrap(plat):
    if plat == "nanoelute":
        return {"display": "block", "marginTop": "10px"}
    return {"display": "none", "marginTop": "10px"}


@callback(
    Output("prot-recon-custom-wrap", "style"),
    Input("prot-recon",              "value"),
)
def _toggle_recon_custom(recon):
    if recon == "custom":
        return {"display": "block", "margin": "4px 0 0 18px"}
    return {"display": "none", "margin": "4px 0 0 18px"}


@callback(
    Output("prot-hist-panel",  "style"),
    Output("prot-hist-select", "options"),
    Input("prot-user", "value"),
    Input("prot-btn-docx", "n_clicks"),   # refresh after each export
)
def _load_history(user, _n):
    """Rebuild history dropdown whenever user changes or a report is exported."""
    hide = {"display": "none", "marginTop": "10px"}
    show = {"display": "block", "marginTop": "10px"}
    opts = _sh.build_dropdown_options(user or "")
    return (show, opts) if opts else (hide, [])


@callback(
    Output("prot-scat",         "value"),
    Output("prot-ssub",         "value"),
    Output("prot-sorg",         "value"),
    Output("prot-nsamp",        "value"),
    Output("prot-hplc-method",  "value"),
    Output("prot-hplc-options", "value"),
    Output("prot-inst",         "value"),
    Output("prot-email",        "value"),
    Output("prot-genby",        "value"),
    Output("prot-cond",         "value"),
    Output("prot-fasta",        "value"),
    Output("prot-fasta-date",   "value"),
    Output("prot-val-name",     "value"),
    Output("prot-platform",     "value"),
    Output("prot-recon",        "value"),
    Output("prot-recon-vol",    "value"),
    Output("prot-recon-inj",    "value"),
    Output("prot-hist-preview", "children"),
    Input("prot-hist-select", "value"),
    State("prot-user", "value"),
    State("prot-inst",     "value"),
    State("prot-email",    "value"),
    State("prot-genby",    "value"),
    State("prot-cond",     "value"),
    State("prot-fasta",    "value"),
    State("prot-fasta-date","value"),
    State("prot-val-name", "value"),
    State("prot-platform", "value"),
    State("prot-recon",    "value"),
    State("prot-recon-vol","value"),
    State("prot-recon-inj","value"),
)
def _apply_history(sol_key, user,
                   cur_inst, cur_email, cur_genby, cur_cond,
                   cur_fasta, cur_fasta_date, cur_val_name,
                   cur_platform, cur_recon, cur_recon_vol, cur_recon_inj):
    """When a history entry is selected: populate scat/ssub/sorg/nsamp, restore
    the HPLC method + options, identification/validation fields, and the
    reconstitution preset used last time. Fields not stored in the entry keep
    their current UI value (via the State() fallbacks)."""
    if sol_key is None or not user:
        raise PreventUpdate
    entries = _sh.get_user_entries(user)       # dict  {SOL: entry}
    entry   = entries.get(sol_key)
    if not entry:
        raise PreventUpdate
    svc     = entry.get("service", "").capitalize()
    cat_lbl = _sh.CAT_LABELS.get(entry.get("scat", ""), entry.get("scat", ""))
    date_lbl = entry.get("last_generated", "")[:10]
    preview = (
        f"[{svc} · {date_lbl}]  "
        f"Category: {cat_lbl} · "
        f"Sub-type: {entry.get('ssub', '')} · "
        f"Organism: {entry.get('sorg', '')} · "
        f"Samples: {entry.get('nsamp', '')}"
    )
    # Restore the chromatography selections if they were stored with the
    # entry; otherwise fall back to the default method + empty options.
    hplc_method  = entry.get("hplc_method")  or DEFAULT_HPLC_METHOD
    hplc_options = list(entry.get("hplc_options") or [])

    # Helper: use stored value if non-empty, otherwise keep whatever is in
    # the form (fall-through so we don't clobber a user's in-progress typing
    # with a stale "" from an old history entry that lacked the field).
    def _or_keep(stored, current):
        return stored if (stored not in (None, "")) else current

    inst       = _or_keep(entry.get("inst"),       cur_inst)
    email      = _or_keep(entry.get("email"),      cur_email)
    genby      = _or_keep(entry.get("genby"),      cur_genby)
    cond       = _or_keep(entry.get("cond"),       cur_cond)
    fasta      = _or_keep(entry.get("fasta"),      cur_fasta)
    fasta_date = _or_keep(entry.get("fasta_date"), cur_fasta_date)
    val_name   = _or_keep(entry.get("val_name"),   cur_val_name)
    platform   = _or_keep(entry.get("platform"),   cur_platform)
    recon_mode = _or_keep(entry.get("recon_mode"), cur_recon)
    # Recon numeric values: parse back to int/float when possible.
    def _num(v, default):
        if v in (None, ""):
            return default
        try:
            x = float(v)
            return int(x) if x.is_integer() else x
        except (TypeError, ValueError):
            return default
    recon_vol = _num(entry.get("recon_vol"), cur_recon_vol)
    recon_inj = _num(entry.get("recon_inj"), cur_recon_inj)

    return (
        entry.get("scat") or None,
        entry.get("ssub", ""),
        entry.get("sorg", ""),
        entry.get("nsamp", ""),
        hplc_method,
        hplc_options,
        inst, email, genby, cond, fasta, fasta_date, val_name,
        platform, recon_mode, recon_vol, recon_inj,
        preview,
    )


# =============================================================================
# CALLBACK — REFRESH SUGGESTION DROPDOWNS
# =============================================================================

@callback(
    Output("dl-prot-sol",        "children"),
    Output("dl-prot-user",       "children"),
    Output("dl-prot-ssub",       "children"),
    Output("dl-prot-sorg",       "children"),
    Output("dl-prot-inst",       "children"),
    Output("dl-prot-email",      "children"),
    Output("dl-prot-genby",      "children"),
    Output("dl-prot-cond",       "children"),
    Output("dl-prot-nsamp",      "children"),
    Output("dl-prot-fasta",      "children"),
    Output("dl-prot-fasta-date", "children"),
    Output("dl-prot-val-name",   "children"),
    Input("prot-btn-docx", "n_clicks"),
    prevent_initial_call=False,
)
def _refresh_prot_datalists(_n):
    """Populate datalist suggestions from history (fires on load + after each export).

    Every text-input with a `list=` binding pulls its suggestions from here.
    `get_unique_values(field)` aggregates across all users and services; for
    proteomics-specific fields we scope with `service="proteomics"`.
    """
    def _opts(vals): return [html.Option(value=v) for v in vals]
    return (
        _opts(_sh.get_unique_values("sol")),
        _opts(_sh.get_all_users()),
        _opts(_sh.get_unique_values("ssub", service="proteomics")),
        _opts(_sh.get_unique_values("sorg")),
        _opts(_sh.get_unique_values("inst")),
        _opts(_sh.get_unique_values("email")),
        _opts(_sh.get_unique_values("genby")),
        _opts(_sh.get_unique_values("cond", service="proteomics")),
        _opts(_sh.get_unique_values("nsamp")),
        _opts(_sh.get_unique_values("fasta",      service="proteomics")),
        _opts(_sh.get_unique_values("fasta_date", service="proteomics")),
        _opts(_sh.get_unique_values("val_name")),
    )


# =============================================================================
# CALLBACK — LIVE PREVIEW
# =============================================================================

@callback(
    Output("prot-fasta-section", "style"),
    Input("prot-sw", "value"),
)
def _toggle_fasta(sw):
    sw = sw or []
    return {"display":"block"} if "spec" in sw else {"display":"none"}


@callback(
    Output("prot-preview-iframe", "srcDoc"),
    Input("prot-sol",      "value"),
    Input("prot-user",     "value"),
    Input("prot-inst",     "value"),
    Input("prot-email",    "value"),
    Input("prot-rdate",    "value"),
    Input("prot-genby",    "value"),
    Input("prot-desc",     "value"),
    Input("prot-nsamp",    "value"),
    Input("prot-cond",     "value"),
    Input("prot-stype",    "value"),
    Input("prot-recdate",  "value"),
    Input("prot-rec",      "value"),
    Input("prot-sto",      "value"),
    Input("prot-prep",     "value"),
    Input("prot-qcvol",    "value"),
    Input("prot-qcvol2",   "value"),
    Input("prot-st",       "value"),
    Input("prot-precip",   "value"),
    Input("prot-acq",      "value"),
    Input("prot-col",      "value"),
    Input("prot-sw",       "value"),
    Input("prot-platform",   "value"),
    Input("prot-fasta",      "value"),
    Input("prot-fasta-date", "value"),
    Input("prot-validated",  "value"),
    Input("prot-val-name",   "value"),
    Input("prot-val-date",   "value"),
    Input("prot-pyd-store",  "data"),
    Input("prot-scat",       "value"),
    Input("prot-ssub",       "value"),
    Input("prot-sorg",       "value"),
)
def _update_preview(sol, user, inst, email, rdate, genby,
                    desc, nsamp, cond, stype,
                    recdate, rec, sto, prep, qcvol, qcvol2,
                    st, precip, acq, col, sw, platform, fasta,
                    fasta_date, validated, val_name, val_date, pyd,
                    scat, ssub, sorg):

    acq = acq or []
    sw  = sw  or []
    col = col or COL_OPTIONS[0]
    rec = rec or "ice4"
    sto = sto or "-20"
    prep = prep or "ready"
    is_ready = prep == "ready"
    is_wz = "WhisperZoom" in col
    col_key = ("short" if "60 SPD" in col else
               "long"  if "30 SPD" in col else
               "wz40"  if "40 SPD" in col else "wz20")
    has_dia = "dia" in acq or is_wz

    rec_label = "Ice (4 °C)" if rec == "ice4" else "Dry ice (−65 °C)"
    sto_label = f"{sto} °C"

    # Fix: avoid "DIA-PASEF/DIA-PASEF WhisperZoom" duplication
    acq_list = ["DDA-PASEF"] if "dda" in acq else []
    if is_wz:
        acq_list.append(f"DIA-PASEF WhisperZoom {'40' if col_key=='wz40' else '20'} SPD")
    elif "dia" in acq:
        acq_list.append("DIA-PASEF")
    acq_str = ", ".join(acq_list) or "—"

    sw_list = ([("Spectronaut 20" if "spec" in sw else "")] +
               [("MSFragger / FragPipe" if "frag" in sw else "")] +
               [("MaxQuant" if "maxq" in sw else "")] +
               [("DIA-NN" if "diann" in sw else "")])
    sw_str = ", ".join(s for s in sw_list if s) or "—"

    platform = platform or "evosep"
    platform_label = "EvosepOne · timsTOF Flex" if platform == "evosep" else "nanoElute2 · timsTOF Pro"

    col_label = col.split("|")[0].strip() if "|" in col else col.split("  ")[0].strip()

    # FASTA combined label
    fasta_full = fasta or ""
    if fasta_date and fasta_date.strip():
        fasta_full = f"{fasta_full} · {fasta_date.strip()}" if fasta_full else fasta_date.strip()

    # Validation
    is_validated = validated and "yes" in validated
    val_stamp = (f"✔ {val_name or 'Reviewer'} · {val_date or '—'}"
                 if is_validated else "⏳ Pending validation")

    qcvol_use = qcvol if is_ready else qcvol2
    # Last loading step in the flow diagram depends on the LC platform:
    #   evosep    → Evotips (200 ng) — disposable stage-tips
    #   nanoelute → LC vial → 200 ng injected directly from autosampler
    load_step = "Evotips (200\u202fng)" if platform == "evosep" \
                else "LC vial \u2192 inj. 200\u202fng"
    if is_ready:
        steps = ["Pre-digested peptides received", "SpeedVac / Reconstitute",
                 f"QC pool ({qcvol_use}\u202f\u03bcL/sample)", load_step]
    else:
        steps = []
        if st == "tissue": steps.append("Beatbox (PreOmics, 10\u202fmin)")
        if precip == "meoh": steps.append("Ppt. MeOH\u2013CHCl\u2083")
        elif precip == "acet": steps.append("Ppt. Acetone \u221220\u202f\u00baC")
        steps += ["Qubit", "iST kit (PreOmics)", f"QC pool ({qcvol_use}\u202f\u03bcL/sample)", load_step]

    def kv(k, v):
        if not v or not str(v).strip(): return ""
        return f'<p class="pv-kv"><span class="pv-k">{k}:</span> {v}</p>'

    def flow(ss):
        parts = []
        for i, s in enumerate(ss):
            parts.append(f'<span class="pv-step">{s}</span>')
            if i < len(ss)-1: parts.append('<span class="pv-arr">&#8594;</span>')
        return '<div class="pv-flow">' + ''.join(parts) + '</div>'

    pyd_html = ""
    if has_dia and pyd:
        inner = ""
        if pyd.get('csv_rows'):
            cols = pyd.get('csv_cols', [])
            inner += (f'<div class="pv-h3">A) pyDIAid Parameters</div>'
                      f'<table class="pv-tbl"><thead><tr>' +
                      ''.join(f'<th>{c}</th>' for c in cols) + '</tr></thead><tbody>' +
                      ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>'
                              for row in (pyd['csv_rows'] or [])[:10]) +
                      '</tbody></table>')
        if pyd.get('txt_rows'):
            cols2 = pyd.get('txt_cols', [])
            inner += (f'<div class="pv-h3">B) Optimized method</div>'
                      f'<table class="pv-tbl"><thead><tr>' +
                      ''.join(f'<th>{c}</th>' for c in cols2) + '</tr></thead><tbody>' +
                      ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>'
                              for row in (pyd['txt_rows'] or [])[:10]) +
                      '</tbody></table>')
        n_imgs = len(pyd.get('img_paths', []))
        if n_imgs:
            inner += f'<p style="font-size:11px;color:{MUTED}">{n_imgs} imagen(es) cargada(s)</p>'
        if not inner:
            inner = f'<p style="font-size:11px;color:{MUTED};font-style:italic">Enter the pyDIAid output folder path to load data.</p>'
        pyd_html = f'<div class="pv-h2">3.2 DIA-PASEF Method Optimization</div>{inner}'

    sec4 = "4. RELATIVE QUANTIFICATION — SPECTRONAUT 20" if "spec" in sw else "4. RESULTS"

    body = f"""
    <p class="pv-title">CLINICAL PROTEOMICS SERVICE — ANALYTICAL REPORT</p>
    <p class="pv-sub">IMSMI · ECAI · IMIBIC · Córdoba | {platform_label}</p>

    <div class="pv-h1">1. OVERVIEW</div>
    {kv("Request No.", sol)}
    {kv("User", user)}
    {kv("Institution / PI", inst)}
    {kv("Email", email)}
    {kv("Report date", rdate)}
    {kv("Generated by", genby)}

    <div class="pv-h1">2. STUDY INFORMATION</div>
    {kv("Description", desc)}
    {kv("Samples", nsamp)}
    {kv("Sample category", scat)}
    {kv("Sample sub-type", ssub)}
    {kv("Organism", sorg)}
    {kv("Comparison", cond)}

    <div class="pv-h1">3. SAMPLE RECEPTION &amp; PREPARATION</div>
    <div class="pv-h2">3.1 Reception</div>
    {kv("Reception date", recdate)}
    {kv("Arrival condition", rec_label)}
    {kv("Storage", sto_label)}
    <div class="pv-h2">3.2 Sample Processing</div>
    {flow(steps)}

    <div class="pv-h1">4. MS ANALYSIS</div>
    <div class="pv-h2">4.1 Data Acquisition</div>
    {kv("Platform", platform_label)}
    {kv("Acquisition mode", acq_str)}
    {kv("Column / gradient", col_label)}
    {kv("Organism", sorg)}
    {kv("Software", sw_str)}
    {kv("FASTA / database", fasta_full)}
    {pyd_html}

    <div class="pv-h1">{sec4}</div>
    <p style="font-size:11px;color:{MUTED};font-style:italic">
      Pending analysis results.
    </p>

    <div style="margin-top:18px;padding:10px 14px;border-radius:8px;
         background:{'#f0fdf4' if is_validated else '#fffbeb'};
         border:1px solid {'#86efac' if is_validated else '#fde68a'};">
      <span style="font-size:10px;font-weight:700;letter-spacing:.08em;
            color:{'#166534' if is_validated else '#92400e'};">
        VALIDATION STATUS</span><br>
      <span style="font-size:12px;font-family:monospace;
            color:{'#166534' if is_validated else '#b45309'};">{val_stamp}</span>
    </div>
    """

    return f"""<!DOCTYPE html><html><head>
    <meta charset="utf-8">
    <style>{PREVIEW_CSS}</style>
    </head><body>{body}</body></html>"""


# =============================================================================
# CALLBACK — EXPORTAR DOCX
# =============================================================================

@callback(
    Output("prot-download-docx", "data"),
    Output("prot-docx-msg",      "children"),
    Input("prot-btn-docx", "n_clicks"),
    State("prot-sol",      "value"),
    State("prot-user",     "value"),
    State("prot-inst",     "value"),
    State("prot-email",    "value"),
    State("prot-rdate",    "value"),
    State("prot-genby",    "value"),
    State("prot-desc",     "value"),
    State("prot-nsamp",    "value"),
    State("prot-cond",     "value"),
    State("prot-stype",    "value"),
    State("prot-recdate",  "value"),
    State("prot-rec",      "value"),
    State("prot-sto",      "value"),
    State("prot-prep",     "value"),
    State("prot-qcvol",    "value"),
    State("prot-qcvol2",   "value"),
    State("prot-st",       "value"),
    State("prot-precip",   "value"),
    State("prot-acq",      "value"),
    State("prot-col",      "value"),
    State("prot-sw",       "value"),
    State("prot-platform",   "value"),
    State("prot-fasta",      "value"),
    State("prot-fasta-date", "value"),
    State("prot-validated",  "value"),
    State("prot-val-name",   "value"),
    State("prot-val-date",   "value"),
    State("prot-pyd-store",  "data"),
    State("prot-scat",       "value"),
    State("prot-ssub",       "value"),
    State("prot-sorg",       "value"),
    State("prot-hplc-method",  "value"),
    State("prot-hplc-options", "value"),
    State("prot-recon",        "value"),
    State("prot-recon-vol",    "value"),
    State("prot-recon-inj",    "value"),
    State("prot-ziptip",       "value"),
    State("prot-also-on",      "value"),
    State("prot-qc",           "value"),
    State("prot-qubit-ready",  "value"),
    prevent_initial_call=True,
)
def _export_docx(n, sol, user, inst, email, rdate, genby,
                 desc, nsamp, cond, stype,
                 recdate, rec, sto, prep, qcvol, qcvol2,
                 st, precip, acq, col, sw, platform, fasta,
                 fasta_date, validated, val_name, val_date, pyd,
                 scat, ssub, sorg,
                 hplc_method, hplc_options,
                 recon_mode, recon_vol, recon_inj,
                 ziptip, also_on,
                 qc, qubit_ready):
    if not n:
        raise PreventUpdate

    if not sol or not sol.strip():
        return None, html.Div("⚠ Please enter at least the request number.",
                              style={"color":CORAL,"fontFamily":"monospace","fontSize":"12px"})

    try:
        from docx import Document as DocxDoc
        from docx.shared import Pt, RGBColor, Cm
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return None, html.Div("⚠ python-docx no instalado. Ejecuta pip install python-docx.",
                              style={"color":CORAL,"fontFamily":"monospace","fontSize":"12px"})

    acq = acq or []
    sw  = sw  or []
    col = col or COL_OPTIONS[0]
    rec = rec or "ice4"
    sto = sto or "-20"
    prep = prep or "ready"
    is_ready = prep == "ready"
    is_wz = "WhisperZoom" in col
    col_key = ("short" if "60 SPD" in col else
               "long"  if "30 SPD" in col else
               "wz40"  if "40 SPD" in col else "wz20")
    has_dia = "dia" in acq or is_wz

    acq_arr = ["DDA-PASEF"] if "dda" in acq else []
    if is_wz:
        acq_arr.append(f"DIA-PASEF WhisperZoom {'40' if col_key=='wz40' else '20'} SPD")
    elif "dia" in acq:
        acq_arr.append("DIA-PASEF")
    acq_lbl = "/".join(acq_arr) if acq_arr else "DDA-PASEF/DIA-PASEF"

    rec_txt = ("on ice (4 \u00baC)" if rec == "ice4" else "at -65\u00baC (dry ice)")
    sto_txt = sto

    recdate_str = recdate or date.today().isoformat()
    rdate_str   = rdate   or date.today().isoformat()

    qcvol_use = qcvol if is_ready else qcvol2
    qcvol_str = str(int(qcvol_use)) if qcvol_use else "5"

    platform = platform or "evosep"
    platform_label = "EvosepOne \u00b7 timsTOF Flex" if platform == "evosep" else "nanoElute2 \u00b7 timsTOF Pro"
    platform_short  = "EvosepOne\u2013timsTOF Flex"  if platform == "evosep" else "nanoElute2\u2013timsTOF Pro"

    # \u2500\u2500 ZipTip cleanup + multi-platform comparison flags \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ziptip_on  = bool(ziptip)  and "on" in (ziptip  or [])
    also_on_on = bool(also_on) and "on" in (also_on or [])
    # QC pool flag \u2014 checked by default; user can opt out. The "ready" branch
    # also supports an optional Qubit quantification step before loading.
    qc_on       = "on" in (qc or [])
    qubit_ready = "on" in (qubit_ready or [])
    # "Other" LC-MS platform label, used in the multi-platform comparison
    # paragraph when also_on_on is True.
    other_platform        = "nanoelute" if platform == "evosep" else "evosep"
    other_platform_label  = ("nanoElute2 \u00b7 timsTOF Pro" if other_platform == "nanoelute"
                             else "EvosepOne \u00b7 timsTOF Flex")
    other_platform_short  = ("nanoElute2\u2013timsTOF Pro" if other_platform == "nanoelute"
                             else "EvosepOne\u2013timsTOF Flex")

    # ── HPLC method (extensible via HPLC_METHODS) ──────────────────────
    hplc_method  = hplc_method or DEFAULT_HPLC_METHOD
    hplc_options = list(hplc_options or [])

    # FASTA with version date
    fasta_full = fasta or ""
    if fasta_date and fasta_date.strip():
        fasta_full = f"{fasta_full} ({fasta_date.strip()})" if fasta_full else fasta_date.strip()

    # Validation
    is_validated = validated and "yes" in validated
    val_name_str = val_name or "Eduardo Chicano-Gálvez, PhD."
    val_date_str = val_date or "—"

    # ── python-docx helpers ──────────────────────────────────────────

    Tc = RGBColor(0x4A,0x9B,0x8F)
    Dc = RGBColor(0x2C,0x2C,0x2A)
    Mc = RGBColor(0x88,0x87,0x80)
    Wc = RGBColor(0xFF,0xFF,0xFF)
    Gc = RGBColor(0xAE,0xAC,0xA6)
    T2 = RGBColor(0x3D,0x85,0x78)

    def sf(r, sz=11, bold=False, italic=False, col_=None, nm="Calibri Light"):
        r.font.name = nm; r.font.size = Pt(sz)
        r.font.bold = bold; r.font.italic = italic
        if col_: r.font.color.rgb = col_

    def no_border_xml():
        nb = OxmlElement('w:tcBorders')
        for side in ['top','left','bottom','right']:
            e = OxmlElement(f'w:{side}')
            e.set(qn('w:val'),'none'); e.set(qn('w:sz'),'0')
            e.set(qn('w:space'),'0'); e.set(qn('w:color'),'auto')
            nb.append(e)
        return nb

    def set_cell_bg(cell, hex_color):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'),'clear'); shd.set(qn('w:color'),'auto')
        shd.set(qn('w:fill'), hex_color); tcPr.append(shd)

    def H1(doc, text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(16); p.paragraph_format.space_after = Pt(6)
        r = p.add_run(text.upper()); sf(r, 14, bold=True, col_=Dc)
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        lft = OxmlElement('w:left')
        lft.set(qn('w:val'),'thick'); lft.set(qn('w:sz'),'28')
        lft.set(qn('w:space'),'8'); lft.set(qn('w:color'),'4A9B8F')
        pBdr.append(lft); pPr.append(pBdr)
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'),'clear'); shd.set(qn('w:color'),'auto')
        shd.set(qn('w:fill'),'EAF4F2'); pPr.append(shd)

    def H2(doc, text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12); p.paragraph_format.space_after = Pt(4)
        r = p.add_run(('\u203a ' + text).upper()); sf(r, 14, bold=True, col_=T2)

    def H3(doc, text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(3)
        r = p.add_run(('\u203a ' + text).upper()); sf(r, 12, bold=True, col_=T2)

    def P(doc, runs_or_str, before=4, after=12):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after  = Pt(after)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if isinstance(runs_or_str, str):
            r = p.add_run(runs_or_str); sf(r, 11)
        else:
            for txt_, bold_, italic_ in runs_or_str:
                r = p.add_run(txt_); sf(r, 11, bold=bold_, italic=italic_)

    def ITEM(doc, text):
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_before = Pt(2); p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.left_indent = Pt(18)
        r = p.add_run(text); sf(r, 11)

    # ── Chromatographic conditions helper (nanoElute) ────────────────
    def _chromatography_paragraph(method_value, options):
        """Return a list of (text, bold, italic) tuples — a Materials &
        Methods paragraph describing the chosen HPLC method, with optional
        addenda for Extended Wash / MS calibrant injection when they are
        present in *options*.

        The shape is compatible with the `P(doc, runs_or_str)` helper so
        this can be dropped into section 3.1. LC just like LC_TEXT[col_key]
        is used for Evosep. Bolded tokens follow the same pattern as
        LC_TEXT (method/column/gradient spans in bold)."""
        m = HPLC_METHODS.get(method_value) or HPLC_METHODS[DEFAULT_HPLC_METHOD]
        runs = [
            ("Peptides were separated on a ", False, False),
            (m["system"], True, False),
            (" nanoflow UPLC system coupled to a CaptiveSpray nano-electrospray "
             "ion source (Bruker Daltonics). Chromatographic separation was "
             "carried out on an ", False, False),
            (m["column"], True, False),
            (f", maintained at a column temperature of {m['temperature']}. "
             f"Mobile phases consisted of {m['mobile_phases']} "
             f"(LC-MS grade, Fisher Scientific). Peptides (200 ng) were "
             f"loaded onto the column and separated at a constant flow rate "
             f"of {m['flow_rate']} using a ", False, False),
            (m["gradient_label"], True, False),
            (f" ({m['gradient_description']}).", False, False),
        ]
        opts = list(options or [])
        if "extended_wash" in opts:
            runs.extend([
                (" An ", False, False),
                ("Extended Wash", True, False),
                (" step was applied after each injection to minimize inter-run "
                 "carry-over in the injection system (+10 min per sample); "
                 "recommended for plasma samples.", False, False),
            ])
        if "ms_calibrant_injection" in opts:
            runs.extend([
                (" An ", False, False),
                ("MS calibrant injection", True, False),
                (" was included using vial 2 loaded with IPA/H\u2082O 50:50 "
                 "(or ACN 100%) to prevent clogging of the injection\u2013trap "
                 "capillary at the end of each gradient.", False, False),
            ])
        return runs

    def table_from_df_rows(doc, rows, cols, caption=None):
        if not rows: return
        if caption:
            pc = doc.add_paragraph()
            pc.paragraph_format.space_before = Pt(10)
            pc.paragraph_format.space_after  = Pt(3)
            r = pc.add_run(caption); sf(r, 11, bold=True)
        tbl = doc.add_table(rows=1+len(rows), cols=len(cols))
        tbl.style = 'Table Grid'
        for j, cn in enumerate(cols):
            cell = tbl.cell(0,j); cell.text = ''
            r = cell.paragraphs[0].add_run(str(cn).upper()); sf(r, 9, bold=True, col_=Wc)
            set_cell_bg(cell, '2C2C2A')
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                cell = tbl.cell(i+1,j); cell.text = ''
                r = cell.paragraphs[0].add_run(str(val) if val is not None else ''); sf(r, 9)
                if i % 2 == 1: set_cell_bg(cell, 'F2F9F8')
        doc.add_paragraph()

    # ── Build document ───────────────────────────────────────────────
    doc = DocxDoc()
    for sec_obj in doc.sections:
        sec_obj.top_margin    = Cm(2.0); sec_obj.bottom_margin = Cm(2.0)
        sec_obj.left_margin   = Cm(2.5); sec_obj.right_margin  = Cm(2.5)

    pt = doc.add_paragraph()
    pt.paragraph_format.space_after = Pt(4)
    r = pt.add_run("CLINICAL PROTEOMICS SERVICE REPORT"); sf(r, 10, col_=Gc)

    ps = doc.add_paragraph()
    ps.paragraph_format.space_after = Pt(0)
    r = ps.add_run(f"IMSMI \u00b7 {sol or 'SOL202XXXX'}"); sf(r, 22, bold=True, col_=Tc)
    pPr = ps._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot = OxmlElement('w:bottom')
    bot.set(qn('w:val'),'thick'); bot.set(qn('w:sz'),'12')
    bot.set(qn('w:space'),'4'); bot.set(qn('w:color'),'4A9B8F')
    pBdr.append(bot); pPr.append(pBdr)

    pu = doc.add_paragraph()
    pu.paragraph_format.space_after = Pt(2)
    r1 = pu.add_run(user or 'User'); sf(r1, 13, bold=True, col_=Dc)
    r2 = pu.add_run(f"  \u00b7  {inst or 'Institution'}"); sf(r2, 12, col_=Mc)

    pe = doc.add_paragraph()
    pe.paragraph_format.space_after = Pt(16)
    r = pe.add_run(f"{platform_label} \u00b7 ECAI \u00b7 IMIBIC \u00b7 C\u00f3rdoba")
    sf(r, 9, col_=Gc)

    meta_rows = [
        [("REQUEST NO.", sol or "—"),  ("USER",          user or "—")],
        [("INSTITUTION", inst or "—"), ("EMAIL",         email or "—")],
        [("REPORT DATE", rdate_str),   ("GENERATED BY",  genby or "—")],
    ]
    mt = doc.add_table(rows=3, cols=2)
    mt.alignment = WD_TABLE_ALIGNMENT.LEFT
    for ri, row_data in enumerate(meta_rows):
        for ci, (lbl_, val_) in enumerate(row_data):
            cell = mt.cell(ri, ci); cell.text = ''
            tcPr = cell._tc.get_or_add_tcPr(); tcPr.append(no_border_xml())
            if ci == 0: set_cell_bg(cell, 'F7F6F2')
            pl = cell.paragraphs[0]
            rl = pl.add_run(lbl_); sf(rl, 8, col_=Gc)
            p2c = cell.add_paragraph()
            r2c = p2c.add_run(val_); sf(r2c, 11, bold=True, col_=Dc)

    # Validation row — amber if pending, teal if validated
    pv = doc.add_paragraph()
    pv.paragraph_format.space_before = Pt(6)
    pv.paragraph_format.space_after  = Pt(16)
    pPr2 = pv._p.get_or_add_pPr()
    shd2 = OxmlElement('w:shd')
    shd2.set(qn('w:val'),'clear'); shd2.set(qn('w:color'),'auto')
    shd2.set(qn('w:fill'), 'EAF4F2' if is_validated else 'FFF8EC')
    pPr2.append(shd2)
    Vc = Tc if is_validated else RGBColor(0xC8,0x86,0x1E)
    rv1 = pv.add_run("\u2714 VALIDATED  " if is_validated else "\u29d0 PENDING VALIDATION  ")
    sf(rv1, 9, bold=True, col_=Vc)
    if is_validated:
        rv2 = pv.add_run(f"{val_name_str}  \u00b7  {val_date_str}")
        sf(rv2, 9, col_=Vc)

    # 1. Overview
    H1(doc, "1. OVERVIEW \u2014 General Description")
    nsamp_v = nsamp or 'XXX'

    # Build a rich sample description from structured fields
    # e.g. "38 human pituitary gland tissue samples"
    _scat_labels = {
        "tissue": "tissue", "cell_culture": "cell culture",
        "plasma": "plasma", "serum": "serum", "urine": "urine",
        "pbmc": "PBMC", "csf": "CSF", "ev": "extracellular vesicles", "other": "samples",
    }
    _cat_str  = _scat_labels.get(scat or "", "") if scat else ""
    _sub_str  = (ssub or "").strip()
    _org_str  = (sorg or "").strip()

    # Organism adjective: "Homo sapiens" → "human" (simple lookup for common organisms)
    _org_adj_map = {
        "homo sapiens": "human", "mus musculus": "mouse", "rattus norvegicus": "rat",
        "danio rerio": "zebrafish", "drosophila melanogaster": "Drosophila",
        "caenorhabditis elegans": "C. elegans", "saccharomyces cerevisiae": "yeast",
        "arabidopsis thaliana": "Arabidopsis",
    }
    _org_adj = _org_adj_map.get(_org_str.lower(), _org_str) if _org_str else ""

    # Compose the sample description string
    samp_desc_parts = []
    if _org_adj:  samp_desc_parts.append(_org_adj)
    if _sub_str:  samp_desc_parts.append(_sub_str)
    if _cat_str:  samp_desc_parts.append(_cat_str)
    samp_desc = " ".join(samp_desc_parts) if samp_desc_parts else "samples"
    # fallback to old stype if no structured data at all
    if not any([scat, ssub, sorg]) and stype and stype.strip():
        samp_desc = stype.strip()

    ov_runs = [("This report presents a comprehensive analysis of ", False, False),
               (f"{nsamp_v} {samp_desc}", True, False),
               (" from ", False, False), (inst or 'XXX', True, False),
               (f". The study employs the ", False, False), (acq_lbl, True, False),
               (" approach to identify and quantify protein levels", False, False)]
    if cond and cond.strip():
        ov_runs += [(", comparing ", False, False), (cond, True, False)]
    ov_runs.append((".", False, False))
    if desc and desc.strip():
        ov_runs.append((" " + desc, False, False))
    P(doc, ov_runs)

    # 2. Sample preparation
    H1(doc, "2. SAMPLE PREPARATION")
    H2(doc, "2.1. Sample Reception")
    P(doc, [("Sample reception date: ", False, False), (recdate_str, True, False)])
    P(doc, [
        ("Samples were received ", False, False), (rec_txt, True, False),
        (" and stored at ", False, False), (sto_txt + "\u202f\u00baC", True, False),
        (" until further processing. Upon arrival, each sample was assigned a unique "
         "identification code and allocated to its corresponding experimental group based on "
         "the information provided in the sample submission form.", False, False),
    ])

    H2(doc, "2.2. Sample Processing")
    if is_ready:
        # ── ZipTip C18 cleanup (optional, only when ziptip_on) ─────────
        # IMSMI protocol for desalting/cleaning up pre-digested peptide
        # samples prior to LC-MS. When this branch is taken, the
        # SpeedVac/reconstitution step is described as part of the ZipTip
        # workflow and the subsequent paragraph only addresses platform-
        # specific loading (Evotip vs. autosampler vial).
        if ziptip_on:
            P(doc, [
                ("Samples were received as pre-digested peptide mixtures and "
                 "subjected to ", False, False),
                ("solid-phase extraction (SPE) clean-up using C₁₈ "
                 "ZipTip® pipette tips (Millipore Sigma)", True, False),
                (" prior to LC-MS analysis. Briefly, the tips were conditioned with "
                 "three sequential aspirations of 10 μL of ", False, False),
                ("70% (v/v) acetonitrile (ACN) containing 0.1% (v/v) "
                 "trifluoroacetic acid (TFA)", True, False),
                (", followed by three equilibration washes with 10 μL of ",
                 False, False),
                ("2% (v/v) ACN / 0.1% (v/v) TFA", True, False),
                (". Peptides were bound to the C₁₈ sorbent by 20 "
                 "consecutive aspirate-and-dispense cycles of 10 μL "
                 "of sample, after which the residual sample was discarded. "
                 "Bound peptides were desalted by three additional washes with "
                 "10 μL of 2% (v/v) ACN / 0.1% (v/v) TFA and eluted "
                 "into a clean low-binding tube pre-charged with 20 μL "
                 "of 70% (v/v) ACN / 0.1% (v/v) TFA by two sequential "
                 "aspirations of 10 μL of the same elution buffer "
                 "(40 μL total eluate). Eluates were dried to "
                 "completeness under vacuum using a ", False, False),
                ("SpeedVac concentrator (Thermo Fisher Scientific)", True, False),
                (" and reconstituted in ", False, False),
                ("12 μL of 2% (v/v) ACN / 0.2% (v/v) TFA", True, False),
                (" by gentle pipetting. Reconstituted peptides were transferred "
                 "to HPLC-MS autosampler vials for analysis.", False, False),
            ])
        # ── Pre-digested peptides ─────────────────────────────────────
        # Loading mechanism differs by platform:
        #   evosep    → samples loaded onto disposable Evotip stage-tips;
        #               first paragraph closes with the Evotip injection clause.
        #   nanoelute → samples kept in autosampler vials; no loading clause in
        #               the first paragraph (injection volume is implicit from
        #               the 10 ng/µL stock). The QC-pool paragraph does NOT
        #               restate the loading step either — only the HeLa
        #               reference is kept, using the verb "used".
        # When ziptip_on is True the SpeedVac/reconstitute step is already
        # described in the preceding ZipTip paragraph, so we omit the
        # standard reconstitution paragraph but still emit the QC-pool /
        # platform-specific loading paragraph.
        if platform == "evosep":
            if not ziptip_on:
                P(doc, [
                    ("Samples were provided as pre-digested peptide mixtures. Prior to analysis, "
                     "peptide solutions were dried under vacuum using a SpeedVac concentrator "
                     "(Thermo Fisher Scientific) and reconstituted in LC-MS grade water containing ",
                     False, False),
                    ("0.1% (v/v) formic acid", True, False),
                    (" to a final concentration of ", False, False),
                    ("10\u202fng/\u03bcL", True, False),
                    (", such that a 20\u202f\u03bcL injection per Evotip yields ", False, False),
                    ("200\u202fng", True, False),
                    (" of peptide material per sample.", False, False),
                ])
            # \u2500\u2500 Optional Qubit quantification (pre-digested branch) \u2500\u2500\u2500\u2500
            # When the user marks "Qubit on pre-digested samples" the
            # paragraph below is inserted before the Evotip loading step
            # to document quantification (e.g. recovery check after
            # ZipTip clean-up) and normalization of the injected amount.
            if qubit_ready:
                P(doc, [
                    ("Peptide concentration was determined using the ", False, False),
                    ("Qubit Protein Assay Kit (Thermo Fisher Scientific)", True, False),
                    (" following the manufacturer\u2019s instructions (1) to verify "
                     "recovery and to normalize the input peptide amount per sample "
                     "prior to instrument loading.", False, False),
                ])
            # \u2500\u2500 QC pool + Evotip loading + HeLa (paragraph variants) \u2500\u2500\u2500
            # qc_on  True  \u2192 standard variant with the QC-pool sentence.
            # qc_on  False \u2192 simplified variant: loading + HeLa only.
            if qc_on:
                P(doc, [
                    ("A quality control (QC) pool was prepared by combining ",
                     False, False),
                    (f"{qcvol_str}\u202f\u03bcL from each sample", True, False),
                    (". Individual samples and the QC pool were loaded onto "
                     "Evotips (Evosep Biosystems) targeting ", False, False),
                    ("200\u202fng of peptides per injection", True, False),
                    (", according to the manufacturer\u2019s instructions (4). "
                     "Pierce\u2122 HeLa Tryptic Digest Standard (Thermo Scientific) "
                     "was additionally loaded for system suitability monitoring "
                     "and instrument equilibration.", False, False),
                ])
            else:
                P(doc, [
                    ("Individual samples were loaded onto Evotips (Evosep Biosystems) "
                     "targeting ", False, False),
                    ("200\u202fng of peptides per injection", True, False),
                    (", according to the manufacturer\u2019s instructions (4). "
                     "Pierce\u2122 HeLa Tryptic Digest Standard (Thermo Scientific) "
                     "was additionally loaded as an external reference for system "
                     "suitability monitoring and instrument equilibration.",
                     False, False),
                ])
        else:  # nanoelute
            # ── Reconstitution mode (nanoElute only) ──────────────────
            # std100  → classic preset (100 ng/µL · 2 µL injection)
            # custom  → user-supplied volumes (e.g. dry-down + resuspend
            #           in 30 µL, inject 1 µL → 200 ng)
            _rmode = recon_mode or "std100"
            def _fmt_vol(v, default):
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    x = default
                return (f"{int(x)}" if float(x).is_integer() else f"{x:g}")
            # SpeedVac/reconstitution is already described in the ZipTip
            # paragraph (if selected); skip the standard nanoelute reconstitute
            # paragraph in that case.
            if ziptip_on:
                pass
            elif _rmode == "custom":
                _v = _fmt_vol(recon_vol, 30)
                _i = _fmt_vol(recon_inj, 1)
                P(doc, [
                    ("Samples were provided as pre-digested peptide mixtures. Prior to "
                     "analysis, peptide solutions were dried under vacuum using a "
                     "SpeedVac concentrator (Thermo Fisher Scientific) and reconstituted "
                     f"in {_v}\u202f\u03bcL of LC-MS grade water containing ", False, False),
                    ("0.1% (v/v) formic acid", True, False),
                    (f", such that a {_i}\u202f\u03bcL injection yields ", False, False),
                    ("200\u202fng", True, False),
                    (" of peptide material per sample.", False, False),
                ])
            else:  # std100 default
                P(doc, [
                    ("Samples were provided as pre-digested peptide mixtures. Prior to "
                     "analysis, peptide solutions were dried under vacuum using a "
                     "SpeedVac concentrator (Thermo Fisher Scientific) and reconstituted "
                     "in LC-MS grade water containing ", False, False),
                    ("0.1% (v/v) formic acid", True, False),
                    (" to a final concentration of ", False, False),
                    ("100\u202fng/\u03bcL", True, False),
                    (", such that a 2\u202f\u03bcL injection yields ", False, False),
                    ("200\u202fng", True, False),
                    (" of peptide material per sample.", False, False),
                ])
            # \u2500\u2500 Optional Qubit quantification (pre-digested branch) \u2500\u2500\u2500\u2500
            # nanoElute2 keeps samples in autosampler vials; quantification
            # is still useful (e.g. after ZipTip clean-up) to verify peptide
            # recovery and normalize the injected amount per sample.
            if qubit_ready:
                P(doc, [
                    ("Peptide concentration was determined using the ", False, False),
                    ("Qubit Protein Assay Kit (Thermo Fisher Scientific)", True, False),
                    (" following the manufacturer\u2019s instructions (1) to verify "
                     "recovery and to normalize the input peptide amount per sample "
                     "prior to instrument loading.", False, False),
                ])
            # \u2500\u2500 QC pool + HeLa (paragraph variants) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
            # qc_on  True  \u2192 standard variant including the QC-pool sentence.
            # qc_on  False \u2192 simplified variant: HeLa reference only.
            if qc_on:
                P(doc, [
                    ("A quality control (QC) pool was prepared by combining ", False, False),
                    (f"{qcvol_str}\u202f\u03bcL from each sample", True, False),
                    (". Pierce\u2122 HeLa Tryptic Digest Standard "
                     "(Thermo Scientific) was additionally used for system "
                     "suitability monitoring and instrument equilibration.",
                     False, False),
                ])
            else:
                P(doc, [
                    ("Pierce\u2122 HeLa Tryptic Digest Standard "
                     "(Thermo Scientific) was used as an external reference for "
                     "system suitability monitoring and instrument equilibration.",
                     False, False),
                ])
    else:
        # ── Tissue homogenisation (optional) ─────────────────────────
        if st == "tissue":
            P(doc, [
                ("Tissue samples were homogenized in ", False, False),
                ("125\u202f\u03bcL of Lysis Buffer (PreOmics, Germany)", True, False),
                (" and mechanically disrupted using a ", False, False),
                ("PreOmics Beatbox", True, False),
                (" homogenizer for 10\u202fminutes, following the manufacturer\u2019s "
                 "instructions. The homogenate was subsequently centrifuged at "
                 "16,000\u202f\u00d7\u202fg for 10\u202fminutes at 4\u202f\u00baC. "
                 "The clarified supernatant, containing the solubilized proteome, was "
                 "carefully transferred to a fresh microcentrifuge tube for downstream "
                 "protein precipitation.", False, False),
            ])

        # ── Protein precipitation ─────────────────────────────────────
        if precip == "meoh":
            P(doc, [
                ("Protein precipitation was performed following the ", False, False),
                ("IMSMI methanol\u2013chloroform protocol", True, False),
                (". Briefly, 400\u202f\u03bcL of methanol was added to 100\u202f\u03bcL of "
                 "sample and the mixture was vortexed for 1\u202fmin, followed by addition "
                 "of 100\u202f\u03bcL of chloroform and a further 1\u202fmin vortex step. "
                 "Subsequently, 300\u202f\u03bcL of LC-MS grade water was added, the "
                 "mixture was vortexed for 3\u202fmin and centrifuged at 15,000\u202f\u00d7"
                 "\u202fg for 2\u202fmin. The upper aqueous phase was carefully removed "
                 "without disturbing the protein-containing interphase. The pellet was "
                 "washed with 400\u202f\u03bcL of methanol, vortexed for 1\u202fmin, and "
                 "re-pelleted by centrifugation at 15,000\u202f\u00d7\u202fg for 3\u202fmin. "
                 "The supernatant was discarded and the pellet was air-dried for "
                 "5\u201310\u202fmin. Proteins were solubilized in 40\u202f\u03bcL of "
                 "RapiGest\u00ae SF (Waters) by heating at 40\u202f\u00baC for "
                 "10\u202fmin with gentle agitation, followed by five cycles of "
                 "30\u202fs probe sonication and 30\u202fs rest on ice.", False, False),
            ])
        elif precip == "acet":
            P(doc, [
                ("Protein precipitation was carried out using ", False, False),
                ("ice-cold acetone (\u221220\u202f\u00baC)", True, False),
                (". Briefly, 480\u202f\u03bcL of pre-chilled acetone (4\u202f\u00d7 volume) "
                 "was added to 120\u202f\u03bcL of protein lysate, mixed briefly, and "
                 "incubated for 1\u202fh at \u221220\u202f\u00baC. The precipitate was "
                 "collected by centrifugation at 13,000\u202frpm for 15\u202fmin at "
                 "4\u202f\u00baC and the supernatant was carefully discarded. The pellet "
                 "was air-dried for 5\u201310\u202fmin, then solubilized in "
                 "40\u202f\u03bcL of RapiGest\u00ae SF (Waters) by heating at "
                 "40\u202f\u00baC for 10\u202fmin with gentle agitation, followed by "
                 "five cycles of 30\u202fs probe sonication and 30\u202fs rest on ice.",
                 False, False),
            ])
        elif precip == "none":
            P(doc, ("No protein precipitation step was applied; samples were processed "
                    "directly for protein quantification and digestion."))

        # ── Quantification, digestion, QC loading ────────────────────
        # Sample-loading sentence branches by platform.
        #   evosep    → explicit Evotip loading step + HeLa as external ref.
        #   nanoelute → no explicit loading sentence (samples stay in vials);
        #               only the HeLa reference is kept, with the verb "used".
        if platform == "evosep":
            _loading_runs = [
                (" and processing it identically. Individual samples and the QC pool "
                 "were loaded onto Evotips (Evosep Biosystems) targeting ", False, False),
                ("200\u202fng of peptides per injection", True, False),
                (", following the manufacturer\u2019s guidelines (4). Pierce\u2122 HeLa "
                 "Tryptic Digest Standard (Thermo Scientific) was included as an external "
                 "reference for instrument performance monitoring and system "
                 "equilibration.", False, False),
            ]
        else:  # nanoelute
            _loading_runs = [
                (" and processing it identically. Pierce\u2122 HeLa Tryptic Digest Standard "
                 "(Thermo Scientific) was used as an external reference for instrument "
                 "performance monitoring and system equilibration.", False, False),
            ]
        P(doc, [
            ("Protein concentration was determined using the ", False, False),
            ("Qubit Protein Assay Kit", True, False),
            (" (Thermo Fisher Scientific) following the manufacturer\u2019s "
             "instructions (1). Tryptic digestion was performed using the ", False, False),
            ("iST kit (PreOmics, Germany)", True, False),
            (" according to the manufacturer\u2019s protocol (2,3). The resulting "
             "peptides were resuspended in LC-MS grade water containing "
             "0.1\u202f% (v/v) formic acid to a final concentration of ", False, False),
            ("10\u202fng/\u03bcL", True, False),
            (". A quality control (QC) pool was prepared by combining ", False, False),
            (f"{qcvol_str}\u202f\u03bcL from each sample", True, False),
            *_loading_runs,
        ])

    # ── pyDIAid optimisation (DIA only) ──────────────────────────────
    if has_dia:
        P(doc, [
            ("Prior to the complete experiment acquisition, five replicate injections "
             "of the QC pool were analyzed in ", False, False),
            ("DIA-PASEF mode", True, False),
            (" using the standard broadband method. The resulting spectral data were "
             "processed with ", False, False),
            ("pyDIAid", True, False),
            (" (https://github.com/MannLabs/pydiaid) to compute optimized variable "
             "DIA-PASEF acquisition windows tailored to the precursor distribution of "
             "the sample set. The optimized method was subsequently applied to all "
             "samples in the experiment.", False, False),
        ])

    # ── Final acquisition summary ─────────────────────────────────────
    P(doc, [
        ("All samples were analyzed by nano-liquid chromatography coupled to tandem "
         "mass spectrometry (nLC-MS/MS) using the ", False, False),
        (acq_lbl, True, False),
        (f" acquisition mode on the {platform_short} Clinical Proteomics Platform "
         "at IMSMI (ECAI\u2013IMIBIC, C\u00f3rdoba). Samples were injected in "
         "randomized order to minimize potential carry-over and batch effects. "
         "Instrument performance and spectral data quality were continuously "
         "monitored throughout the acquisition using Bruker ProteoScape\u2122 "
         "software (BPS).", False, False),
    ])

    # 3. LC-MS
    H1(doc, "3. LC-MS ANALYSIS")
    H2(doc, "3.1. LC")
    # Platform-aware LC prose (single source of truth; the text has to match
    # what the user picked in the form so it can be copy-pasted as Materials
    # & Methods):
    #   evosep    → LC_TEXT[col_key]                (per selected column)
    #   nanoelute → _chromatography_paragraph(…)    (per selected HPLC method
    #                                                + options addenda)
    if platform == "nanoelute":
        P(doc, _chromatography_paragraph(hplc_method, hplc_options))
    else:
        P(doc, LC_TEXT.get(col_key, [("(No column selected)", False, False)]))

    # ── Multi-platform comparison (optional) ──────────────────────────
    # When also_on_on is True the same sample set was additionally analysed
    # on the alternative LC-MS platform to evaluate the differential
    # proteome coverage achievable by each system.
    if also_on_on:
        if other_platform == "nanoelute":
            other_lc = ("on a nanoElute2 (Bruker Daltonics) UHPLC system "
                        "coupled to a timsTOF Pro mass spectrometer, using the "
                        "laboratory's reference long-gradient method on an "
                        "Aurora Ultimate TS analytical column "
                        "(IonOpticks, 25 cm × 75 μm, 1.7 μm, C18)")
        else:
            other_lc = ("on an EvosepOne (Evosep Biosystems) LC system coupled "
                        "to a timsTOF Flex mass spectrometer, using the "
                        "manufacturer's pre-defined gradient on the corresponding "
                        "EV1106 analytical column")
        P(doc, [
            ("In addition to the primary acquisition on the ", False, False),
            (platform_short, True, False),
            (" platform, the same sample set was analysed in parallel ",
             False, False),
            (other_lc, True, False),
            (". This dual-platform strategy was implemented to enable a "
             "side-by-side assessment of proteome coverage and qualitative "
             "performance achieved by each LC-MS system on the same biological "
             "material, taking advantage of the complementary throughput and "
             "depth profiles of the two configurations.", False, False),
        ])

    H2(doc, "3.2. MS Analysis")
    # Instrument name follows the selected platform (evosep → timsTOF Flex,
    # nanoelute → timsTOF Pro).
    ms_instrument = "timsTOF Flex" if platform == "evosep" else "timsTOF Pro"
    P(doc, [
        (f"LC was coupled online to a TIMS Q-TOF instrument ({ms_instrument}, "
         "Bruker Daltonics) via a CaptiveSpray nano-electrospray ion source using ",
         False, False),
        (acq_lbl, True, False),
        (" (6,7). Ion mobility was calibrated with three Agilent ESI-L Tuning Mix ions (m/z, 1/K\u2080: "
         "622.0289 Th, 0.9848 Vs cm\u207b\u00b2; 922.0097 Th, 1.1895 Vs cm\u207b\u00b2; "
         "1221.9906 Th, 1.3820 Vs cm\u207b\u00b2). Collision energy decreased linearly from "
         "59 eV (1/K\u2080 = 1.6 Vs cm\u207b\u00b2) to 20 eV (1/K\u2080 = 0.6 Vs cm\u207b\u00b2).",
         False, False),
    ])
    # Gradient-length flag for §3.2 method descriptions. For Evosep this
    # follows the selected column (60/wz40 → short; 30/wz20 → long). For
    # nanoElute the report always describes a long gradient, regardless of
    # the selected HPLC method.
    if platform == "nanoelute":
        sh, lg = False, True
    else:
        sh = col_key in ("short","wz40"); lg = col_key in ("long","wz20")
    if "dda" in acq and sh:
        P(doc, [("For the ",False,False),("DDA-PASEF short gradient method",True,False),
                (": top-N cycles of ten PASEF MS/MS scans, accumulation/ramp 100 ms. "
                 "Singly charged precursors excluded by polygon filter. Target 20,000 → "
                 "excluded 0.4 min. Q window 2 m/z (<700 Th) / 3 m/z (>800 Th).",False,False)])
    if "dia" in acq and sh and not is_wz:
        P(doc, [("For the ",False,False),("DIA-PASEF short gradient method",True,False),
                (": m/z 475\u20131000.0 Th, 1/K\u2080 0.85\u20131.27 Vs cm\u207b\u00b2, "
                 "16 \u00d7 25 Th variable diaPASEF windows.",False,False)])
    if "dda" in acq and lg:
        P(doc, [("For the ",False,False),("DDA-PASEF long gradient method",True,False),
                (": top-N cycles of ten PASEF MS/MS scans, accumulation/ramp 100 ms, "
                 "CE 59\u219220 eV (1/K\u2080 1.60\u21920.60 Vs cm\u207b\u00b2). "
                 "Q window 2 m/z (<700 Th) / 3 m/z (>800 Th).",False,False)])
    if "dia" in acq and lg and not is_wz:
        P(doc, [("For the ",False,False),("DIA-PASEF long gradient method",True,False),
                (": m/z 400\u20131201.0 Th, 1/K\u2080 0.6\u20131.6 Vs cm\u207b\u00b2, "
                 "16 \u00d7 25 Th variable diaPASEF acquisition windows previously "
                 "optimized in pyDIAid and used as the standard scheme for this gradient.",
                 False,False)])
    if is_wz:
        P(doc, [("For the ",False,False),("DIA-PASEF Method Optimization",True,False),
                (": five QC pool injections were first analyzed using the long gradient method "
                 "(m/z 400\u20131201.0 Th, 1/K\u2080 0.6\u20131.6 Vs cm\u207b\u00b2, "
                 "16 \u00d7 25 Th variable diaPASEF windows). The resulting spectral data were "
                 "processed in Spectronaut and subsequently used in pyDIAid to optimize the "
                 "variable DIA-PASEF acquisition windows. The full sample set was then analyzed "
                 "using this optimized method.", False, False)])

    if has_dia and pyd and not pyd.get('err') and pyd.get('img_paths'):
        from docx.shared import Cm as DxCm
        img_paths = pyd.get('img_paths', [])[:3]
        pc2 = doc.add_paragraph()
        pc2.paragraph_format.space_before = Pt(10); pc2.paragraph_format.space_after = Pt(4)
        r = pc2.add_run("Figure 1."); sf(r, 11, bold=True)
        r2 = pc2.add_run(
            " DIA-PASEF Method Optimization. A) Histogram of precursor distribution across "
            "m/z range using pool samples acquired in DIA-PASEF mode. B) Kernel density "
            "distribution of precursors\u2019 ion mobility. C) Adjusted DIA-PASEF method "
            "using variable acquisition windows."); sf(r2, 11)
        if img_paths:
            # ── Helper: normalize figure for docx ──────────────────────
            # Strategy: auto-crop all white borders, then set SAME HEIGHT
            # for every panel so they align perfectly in the table row.
            def _normalize_fig(img_path_str):
                """
                1. Auto-crop white margins (tight bbox).
                2. Return (BytesIO_buf, width_emu, height_emu) maintaining
                   aspect ratio at TARGET_H_CM height, or (None,…) on failure.
                """
                TARGET_H_CM = 4.2
                try:
                    from PIL import Image as _PI, ImageChops as _IC
                    import io as _io
                    im = _PI.open(img_path_str).convert("RGB")

                    # 1. Tight auto-crop: diff against white background
                    bg   = _PI.new("RGB", im.size, (255, 255, 255))
                    diff = _IC.difference(im, bg)
                    bbox = diff.getbbox()          # (left, top, right, bottom)
                    if bbox:
                        pad = 8                    # pixel padding around content
                        x0 = max(0, bbox[0] - pad)
                        y0 = max(0, bbox[1] - pad)
                        x1 = min(im.width,  bbox[2] + pad)
                        y1 = min(im.height, bbox[3] + pad)
                        im = im.crop((x0, y0, x1, y1))

                    # 2. Serialize cropped image
                    buf = _io.BytesIO()
                    im.save(buf, format="PNG")
                    buf.seek(0)

                    # 3. Compute EMU dimensions (same height, proportional width)
                    aspect    = im.width / im.height if im.height else 1.0
                    target_h  = DxCm(TARGET_H_CM)
                    target_w  = int(target_h * aspect)
                    return buf, target_w, target_h
                except Exception:
                    return None, None, None

            fig_tbl = doc.add_table(rows=2, cols=len(img_paths))
            for ci, img_path_str in enumerate(img_paths):
                cell = fig_tbl.cell(0, ci); cell.text = ''
                tcPr = cell._tc.get_or_add_tcPr(); tcPr.append(no_border_xml())
                # Center the image in the cell
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                try:
                    rp = cell.paragraphs[0].add_run()
                    buf, tw, th = _normalize_fig(img_path_str)
                    if buf:
                        rp.add_picture(buf, width=tw, height=th)
                    else:
                        rp.add_picture(img_path_str, width=DxCm(5.0))
                except Exception:
                    rp = cell.paragraphs[0].add_run(f"[{Path(img_path_str).name}]")
                    sf(rp, 9, col_=Mc)
                lbl_cell = fig_tbl.cell(1, ci); lbl_cell.text = ''
                tcPr2 = lbl_cell._tc.get_or_add_tcPr(); tcPr2.append(no_border_xml())
                rl = lbl_cell.paragraphs[0].add_run("ABCDE"[ci]); sf(rl, 10, bold=True, col_=Tc)
                lbl_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.add_paragraph()

    if pyd and pyd.get('csv_rows'):
        table_from_df_rows(doc, pyd['csv_rows'], pyd.get('csv_cols',[]),
            caption="Table 1. Evaluated parameters to adjust DIA-PASEF method.")
    if pyd and pyd.get('txt_rows'):
        _raw_cols = pyd.get('txt_cols', [])
        _ce_idx   = _raw_cols.index('CE [eV]') if 'CE [eV]' in _raw_cols else None
        _t_cols   = [c for c in _raw_cols if c != 'CE [eV]']
        if _ce_idx is not None:
            _t_r