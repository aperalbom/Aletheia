"""
app.py — Punto de entrada de la plataforma IMSMI
Arranca con:
    python sol_analyzer_dash/app.py              (desde la raíz del repo)
    python -m sol_analyzer_dash.app              (también desde la raíz)
    cd sol_analyzer_dash && python app.py        (modo legacy)
Abre en:      http://localhost:8050
"""

# ---------------------------------------------------------------------------
# Path bootstrap: the codebase uses bare imports (``from core.X import ...``,
# ``import pages.Y``) instead of fully-qualified ``sol_analyzer_dash.core.X``.
# To make every invocation form above resolve, we put the package directory
# on ``sys.path`` *before* any of those imports. Tests do the equivalent via
# their own ``sys.path.insert`` lines; the CLI does it too. Keep this block
# at the very top of the file.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import dash
from dash import Dash, html, dcc, Input, Output, callback
from flask import send_file
import io, tempfile, os, pandas as pd

app = Dash(
    __name__,
    use_pages=True,
    # Pass an absolute path so Dash finds the pages folder regardless of
    # whether the app was launched as a script (``python app.py``) or as a
    # module (``python -m sol_analyzer_dash.app``) from a different cwd.
    pages_folder=str(_HERE / "pages"),
    assets_folder=str(_HERE / "assets"),
    suppress_callback_exceptions=True,
    meta_tags=[{"name":"viewport","content":"width=device-width, initial-scale=1"}],
)
app.title = "Aletheia · IMSMI"


from core.cache import load as cload

# =============================================================================
# ENDPOINTS DE DESCARGA — sin automatismo, el usuario elige cuándo
# =============================================================================

def _combined_df(d):
    lin_cols = ["label","Name","ok","r2","strategy","n_valid","reason"]
    lin_cols = [c for c in lin_cols if c in d["m1"]["lin_df"].columns]
    lin = d["m1"]["lin_df"][lin_cols].copy()
    if d["m2"]:
        lin["CV_median"] = d["m2"]["cv_df"]["CV_median"].values
        lin["CV_ok"]     = d["m2"]["cv_df"]["CV_ok"].values
        lin["ICC"]       = d["m2"]["icc_vec"]
        lin["pass_both"] = lin["ok"] & lin["CV_ok"]
    return lin

def _sel(df, cols):
    """Select only columns that actually exist in df (safe fallback)."""
    return df[[c for c in cols if c in df.columns]]

DL_MAP = {
    "filtered": lambda d: (
        d["parsed"]["raw"][d["parsed"]["raw"]["Bucket label"]
            .isin(d["m1"]["good"]["label"])],
        "experiment_filtered.csv"),
    "good":     lambda d: (
        _sel(d["m1"]["good"], ["label","Name","r2","strategy","n_valid","reason"]),
        "good_coor.csv"),
    "bad":      lambda d: (
        _sel(d["m1"]["bad"], ["label","Name","r2","n_valid","reason"]),
        "bad_coor.csv"),
    "qcr":      lambda d: (d["qcr"]["qcr_df"],         "qcr_report.csv"),
    "agg":      lambda d: (d["qcr"]["agg_df"],          "experiment_aggregated.csv"),
    "cv":       lambda d: (d["m2"]["cv_df"] if d["m2"] else pd.DataFrame(), "cv_per_sample.csv"),
    "combined": lambda d: (_combined_df(d),             "combined_results.csv"),
    "pass":     lambda d: (_combined_df(d).query("ok==True and CV_ok==True") if d["m2"]
                           else _combined_df(d).query("ok==True"), "pass_all_criteria.csv"),
}

def _alt_suffix_filename(fname: str) -> str:
    """Append "_ALT" before the extension of *fname*.

    >>> _alt_suffix_filename("experiment_filtered.csv")
    'experiment_filtered_ALT.csv'
    """
    base, dot, ext = fname.rpartition(".")
    if not dot:
        return f"{fname}_ALT"
    return f"{base}_ALT.{ext}"


def _is_alt_entry(d: dict) -> bool:
    """A cached entry built by *run_alternative_analysis* carries an
    ``alt_meta`` key (see pages/sol_analyzer.py).  Use it as the canonical
    flag for "this is an alternative-analysis result"."""
    return bool(d.get("alt_meta")) if isinstance(d, dict) else False


@app.server.route("/dl/<rkey>/<dtype>")
def download_file(rkey, dtype):
    d = cload(rkey)
    if not d or dtype not in DL_MAP:
        return "No encontrado", 404
    df, fname = DL_MAP[dtype](d)
    if _is_alt_entry(d):
        fname = _alt_suffix_filename(fname)
    buf = io.StringIO()
    df.to_csv(buf, sep=";", index=False)
    buf.seek(0)
    return send_file(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=fname,
    )

@app.server.route("/dl/<rkey>/pdf")
def download_pdf(rkey):
    from flask import request
    d = cload(rkey)
    if not d:
        return "No encontrado", 404
    is_alt = _is_alt_entry(d) or (request.args.get("alt") == "1")
    pdf_name = "informe_sol_analyzer_ALT.pdf" if is_alt else "informe_sol_analyzer.pdf"
    try:
        import reportlab
        from core.pdf_report import build_pdf
        pdf_bytes = build_pdf(d, pdf_name)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=pdf_name,
        )
    except (ImportError, ModuleNotFoundError):
        pass
    except Exception as e:
        return f"Error generando PDF: {e}", 500

    # Fallback: HTML con gráficas Plotly interactivas
    try:
        from core.pdf_report import build_print_html
        html_str = build_print_html(d)
        return html_str, 200, {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Security-Policy": "script-src 'self' 'unsafe-inline' 'unsafe-eval';",
        }
    except Exception as e:
        return f"Error generando informe: {e}", 500


# =============================================================================
# Stats module — DOCX/PDF report endpoints
# =============================================================================

def _stats_data_for_report(key: str | None = None):
    """Pull a specific stats cache entry (by key from the UI) and convert it
    into the flat dict expected by core.stats_report.build_*. Falls back to
    the most recently-saved entry with pp_done=True if no key is given."""
    from core.cache import _CACHE
    from flask import request

    if key is None:
        try:
            key = request.args.get("key")
        except Exception:
            key = None

    d = None
    if key and key in _CACHE and isinstance(_CACHE[key], dict):
        d = _CACHE[key]
        if not d.get("pp_done"):
            d = None

    if d is None:
        candidates = [(k, v) for k, v in _CACHE.items()
                        if isinstance(v, dict) and v.get("pp_done")
                           and v.get("form") is not None]
        if not candidates:
            return None
        _, d = candidates[-1]

    out = {
        "metadata":   d["form"]["metadata"],
        "n_samples":  len(d.get("rename_map", {})) or d["form"]["n_samples"],
        "groups":     {"factor": "Condition", "values": d["form"]["conditions"]},
        "factorial":  d["form"]["factorial"],
        "pp_summary": d.get("pp_summary", "—"),
        "date":       __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if d.get("uni_res"):
        u = d["uni_res"]
        out["univariate"] = {"comparisons": [{
            "idx":       1,
            "a":         u["a"], "b": u["b"],
            "test":      u["test"],
            "n_sig":     u["n_sig"],
            "table_top": u["table"].head(20),
        }]}
    if d.get("pca_res"):
        out["pca"] = {"explained": d["pca_res"]["explained"]}
    if d.get("pls_res"):
        p = d["pls_res"]
        out["plsda"] = {
            "accuracy_cv":   p["accuracy_cv"],
            "p_value":       p.get("permutation", {}).get("p_value") if p.get("permutation") else None,
            "n_permutations":p.get("n_permutations", 0),
            "vip_top":       (p["vip"].head(20)
                                  .rename_axis("feature")
                                  .reset_index()
                                  .rename(columns={0: "VIP"})),
        }
    if d.get("bm_res"):
        b = d["bm_res"]
        out["biomarkers"] = [{"comparison": (b["a"], b["b"]),
                                "top": b["top"]}]
    return out


@app.server.route("/dl_stats/docx")
def download_stats_docx():
    import traceback
    data = _stats_data_for_report()
    if not data:
        return ("<h2>No hay análisis preparados todavía.</h2>"
                "<p>Asegúrate de haber subido plantilla + CSV y haber aplicado "
                "el preprocesado antes de intentar generar el informe.</p>",
                404)
    try:
        from core.stats_report import build_docx
        buf = build_docx(data)
        return send_file(io.BytesIO(buf),
                          mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          as_attachment=True,
                          download_name="stats_report.docx")
    except Exception as e:
        tb = traceback.format_exc()
        return (f"<h2>Error generando DOCX</h2><pre>{e}\n\n{tb}</pre>", 500)


@app.server.route("/dl_stats/pdf")
def download_stats_pdf():
    import traceback
    data = _stats_data_for_report()
    if not data:
        return ("<h2>No hay análisis preparados todavía.</h2>"
                "<p>Asegúrate de haber subido plantilla + CSV y haber aplicado "
                "el preprocesado antes de intentar generar el informe.</p>",
                404)
    try:
        from core.stats_report import build_pdf
        buf = build_pdf(data)
        return send_file(io.BytesIO(buf),
                          mimetype="application/pdf",
                          as_attachment=True,
                          download_name="stats_report.pdf")
    except RuntimeError as e:
        # LibreOffice missing → friendly page (no traceback noise)
        msg = str(e)
        return (f"""<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>PDF no disponible</title>
<style>body{{font-family:Inter,system-ui,sans-serif;max-width:680px;
margin:60px auto;padding:0 20px;color:#2C2C2A}}
h2{{color:#C0756A}} a{{color:#4A9B8F;font-weight:600}}
.box{{background:#F7F6F2;border:1px solid #E4E2DC;border-radius:8px;
padding:18px;margin:18px 0;font-size:14px;line-height:1.55}}</style>
</head><body>
<h2>📄 PDF no disponible</h2>
<div class="box">{msg}</div>
<p>Mientras tanto puedes <a href="/dl_stats/docx?{__import__('flask').request.query_string.decode()}">
descargar el DOCX</a> y abrirlo en Word — o conviértelo a PDF desde Word
con <em>Archivo → Guardar como → PDF</em>.</p>
</body></html>""", 503)
    except Exception as e:
        tb = traceback.format_exc()
        return (f"<h2>Error generando PDF</h2><pre>{e}\n\n{tb}</pre>", 500)


@app.server.route("/plotly.js")
def serve_plotlyjs():
    """Sirve el JS de Plotly desde la instalación local — sin necesitar CDN."""
    try:
        import plotly
        import os
        # Buscar el archivo plotly.min.js en la instalación
        plotly_dir = os.path.dirname(plotly.__file__)
        candidates = [
            os.path.join(plotly_dir, "package_data", "plotly.min.js"),
            os.path.join(plotly_dir, "static", "plotly.min.js"),
        ]
        # Buscar recursivamente si no está en las rutas habituales
        for root, dirs, files in os.walk(plotly_dir):
            for fname in files:
                if fname in ("plotly.min.js", "plotly.js"):
                    candidates.append(os.path.join(root, fname))
            if len(candidates) > 5:
                break

        for path in candidates:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    js = f.read()
                return js, 200, {
                    "Content-Type": "application/javascript",
                    "Cache-Control": "public, max-age=86400",
                }

        # Último recurso: generar el JS desde Plotly
        import plotly.graph_objects as go
        import plotly.io as pio
        dummy = pio.to_html(go.Figure(), full_html=False, include_plotlyjs=True)
        import re
        m = re.search(r'<script[^>]*>(.*?)</script>', dummy, re.DOTALL)
        if m:
            js = m.group(1).encode("utf-8")
            return js, 200, {"Content-Type": "application/javascript"}

        return "Plotly JS no encontrado", 404
    except Exception as e:
        return f"Error: {e}", 500

# =============================================================================
# NAVEGACIÓN LATERAL
# =============================================================================

NAV_ITEMS = [
    {"section": "General"},
    {"label":"Inicio",                        "href":"/",             "icon":"⌂"},
    {"section": "Análisis"},
    {"label":"Aletheia",                      "href":"/sol-analyzer", "icon":"◈"},
    {"section": "Informes"},
    {"label":"Metab. / Lipidómica",           "href":"/informe",      "icon":"📄"},
    {"label":"Proteómica",                    "href":"/proteomics",   "icon":"🔬"},
    {"section": "Herramientas"},
    {"label":"Análisis estadístico",          "href":"/stats",        "icon":"📈"},
    {"label":"Listas randomizadas",           "href":"/randomizer",   "icon":"🎲"},
    {"section": "Control Interno"},
    {"label":"Registro de solicitudes",       "href":"/registry",     "icon":"📋"},
]


def build_sidebar(current_path):
    items = []
    for item in NAV_ITEMS:
        if "section" in item:
            items.append(html.Div(item["section"], className="sidebar-section"))
        elif item.get("disabled"):
            items.append(html.Div(
                [html.Span(item["icon"], className="nav-icon"), item["label"]],
                className="nav-link",
                style={"opacity":".35","cursor":"default"},
            ))
        else:
            active = current_path == item["href"]
            items.append(dcc.Link(
                [html.Span(item["icon"], className="nav-icon"), item["label"]],
                href=item["href"],
                className="nav-link active" if active else "nav-link",
            ))

    return html.Div(id="sidebar", children=[
        html.Div(className="sidebar-logo", children=[
            # Logo SVG inline
            html.Div(style={"marginBottom":"4px"}, children=[
                html.Img(src="/assets/logo.svg",
                         style={"width":"100%","height":"auto","display":"block","maxWidth":"244px"}),
            ]),
            html.Div("ECAI · IMIBIC · Córdoba", className="sidebar-logo-sub"),
        ]),
        *items,
        html.Div(style={"padding":"1rem 1.2rem","position":"absolute","bottom":0,
                        "left":0,"right":0,"borderTop":"1px solid rgba(255,255,255,0.08)"},
                 children=[
            html.Div("v1.0 · 2026",
                     style={"fontSize":"9px","color":"rgba(255,255,255,0.2)",
                            "fontFamily":"monospace","letterSpacing":".05em"}),
        ]),
    ])



# =============================================================================
# LAYOUT PRINCIPAL
# =============================================================================

app.layout = html.Div([
    dcc.Location(id="url"),
    html.Div(id="sidebar-container"),
    html.Div(
        dash.page_container,
        id="page-content",
    ),
])


@callback(
    Output("sidebar-container", "children"),
    Input("url", "pathname"),
)
def update_sidebar(pathname):
    return build_sidebar(pathname or "/")


# =============================================================================
# ARRANQUE
# =============================================================================

if __name__ == "__main__":
    import webbrowser, threading, time

    port = 8050
    url  = f"http://localhost:{port}"

    def open_browser():
        time.sleep(2.0)
        try:
            if sys.platform == "win32":
                os.startfile(url)
            else:
                webbrowser.open(url)
        except Exception:
            pass

    print(f"\n{'='*50}")
    print(f"  Aletheia · IMSMI arrancando...")
    print(f"  Abre en tu navegador: {url}")
    print(f"{'='*50}\n", flush=True)

    threading.Thread(target=open_browser, daemon=True).start()
    # Dash 3.x and 4.x both support .run(); fall back to .run_server() for older 2.x.
    run_method = getattr(app, "run", None) or getattr(app, "run_server", None)
    if run_method is None:
        raise RuntimeError("Cannot find app.run or app.run_server method on this Dash version")
    run_method(debug=False, port=port, host="0.0.0.0")
