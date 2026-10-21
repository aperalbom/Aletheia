"""
app.py — Aletheia web interface (entry point)
Arranca con:
    python aletheia/app.py              (from the repository root)
    python -m aletheia.app              (also from the repository root)
    cd aletheia && python app.py        (legacy mode)
Opens at:     http://localhost:8050
"""

# ---------------------------------------------------------------------------
# Path bootstrap: the codebase uses bare imports (``from core.X import ...``,
# ``import pages.Y``) instead of fully-qualified ``aletheia.core.X``.
# To make every invocation form above resolve, we put the package directory
# on ``sys.path`` *before* any of those imports. Tests do the equivalent via
# their own ``sys.path.insert`` lines; the CLI does it too. Keep this block
# at the very top of the file.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
# Add the package directory so bare imports (``from core.X import …``) resolve.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# Also add the parent so fully-qualified imports (``from aletheia.core …``)
# work regardless of the working directory the user launches from.
_PARENT = _HERE.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import dash
from dash import Dash, html, dcc, Input, Output, callback
from flask import send_file
import io, tempfile, os, pandas as pd

app = Dash(
    __name__,
    use_pages=True,
    # Pass an absolute path so Dash finds the pages folder regardless of
    # whether the app was launched as a script (``python app.py``) or as a
    # module (``python -m aletheia.app``) from a different cwd.
    pages_folder=str(_HERE / "pages"),
    assets_folder=str(_HERE / "assets"),
    suppress_callback_exceptions=True,
    meta_tags=[{"name":"viewport","content":"width=device-width, initial-scale=1"}],
)
app.title = "Aletheia"


from core.cache import load as cload
from core.analysis import combined_table
from core.i18n import t, get_lang, COOKIE as LANG_COOKIE
from aletheia import __version__

# =============================================================================
# DOWNLOAD ENDPOINTS — nothing is downloaded automatically, the user chooses when
# =============================================================================

def _combined_df(d):
    return combined_table(d["m1"]["lin_df"], d["m2"])

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
        return "Not found", 404
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
        return "Not found", 404
    is_alt = _is_alt_entry(d) or (request.args.get("alt") == "1")
    pdf_name = "aletheia_report_ALT.pdf" if is_alt else "aletheia_report.pdf"
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
    except Exception:
        # reportlab/svglib missing, or Kaleido cannot find Chrome/Chromium:
        # fall through to the printable HTML report below.
        pass

    # Fallback: printable HTML with interactive Plotly charts (no extra deps)
    try:
        from core.pdf_report import build_print_html
        html_str = build_print_html(d)
        return html_str, 200, {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Security-Policy": "script-src 'self' 'unsafe-inline' 'unsafe-eval';",
        }
    except Exception as e:
        return f"Error generating report: {e}", 500


@app.server.route("/sol-analyzer")
def _legacy_path():
    """Backward-compatible alias of the v1.0.0 page path."""
    from flask import redirect
    return redirect("/", code=302)


@app.server.route("/plotly.js")
def serve_plotlyjs():
    """Serve Plotly.js from the local installation — no CDN needed."""
    try:
        import plotly
        import os
        # Look for plotly.min.js in the installation
        plotly_dir = os.path.dirname(plotly.__file__)
        candidates = [
            os.path.join(plotly_dir, "package_data", "plotly.min.js"),
            os.path.join(plotly_dir, "static", "plotly.min.js"),
        ]
        # Search recursively if it is not in the usual locations
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

        # Last resort: extract the JS from a Plotly export
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
# SIDEBAR NAVIGATION
# =============================================================================

NAV_ITEMS = [
    {"section": "Aletheia"},
    {"label": "QC dilution filtering", "href": "/", "icon": "◈"},   # translated in build_sidebar
]


def _language_selector():
    """EN | ES switch. The choice is stored in a cookie (read server-side by
    core.i18n.t) and the page is reloaded so every component is re-rendered."""
    cur = get_lang()
    def btn(code, label):
        on = cur == code
        return html.Button(label, id=f"lang-{code}", n_clicks=0, title=t("Interface language"),
                           style={"background": "rgba(255,255,255,0.14)" if on else "transparent",
                                  "color": "#FFFFFF" if on else "rgba(255,255,255,0.55)",
                                  "border": "1px solid rgba(255,255,255,0.25)",
                                  "borderRadius": "4px", "padding": "3px 10px",
                                  "fontFamily": "monospace", "fontSize": "11px",
                                  "cursor": "pointer", "marginRight": "6px"})
    return html.Div(style={"padding": "1rem 1.2rem"}, children=[
        html.Div(t("Language"), style={"fontSize": "9px", "letterSpacing": ".08em",
                                       "textTransform": "uppercase", "marginBottom": "6px",
                                       "color": "rgba(255,255,255,0.35)",
                                       "fontFamily": "monospace"}),
        btn("en", "EN"), btn("es", "ES"),
    ])


def build_sidebar(current_path):
    items = []
    for item in NAV_ITEMS:
        if "section" in item:
            items.append(html.Div(t(item["section"]), className="sidebar-section"))
        elif item.get("disabled"):
            items.append(html.Div(
                [html.Span(item["icon"], className="nav-icon"), t(item["label"])],
                className="nav-link",
                style={"opacity":".35","cursor":"default"},
            ))
        else:
            active = current_path == item["href"]
            items.append(dcc.Link(
                [html.Span(item["icon"], className="nav-icon"), t(item["label"])],
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
        _language_selector(),
        html.Div(style={"padding":"1rem 1.2rem","position":"absolute","bottom":0,
                        "left":0,"right":0,"borderTop":"1px solid rgba(255,255,255,0.08)"},
                 children=[
            html.Div(f"v{__version__} · 2026",
                     style={"fontSize":"9px","color":"rgba(255,255,255,0.2)",
                            "fontFamily":"monospace","letterSpacing":".05em"}),
        ]),
    ])



# =============================================================================
# MAIN LAYOUT
# =============================================================================

app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="lang-sink"),
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


app.clientside_callback(
    """
    function(n_en, n_es) {
        var id = (window.dash_clientside.callback_context.triggered || [{}])[0].prop_id || "";
        var lang = null;
        if (id.indexOf("lang-es") === 0 && n_es > 0) { lang = "es"; }
        if (id.indexOf("lang-en") === 0 && n_en > 0) { lang = "en"; }
        // Ignore the call made when the buttons are (re)rendered with n_clicks = 0.
        if (!lang) { return window.dash_clientside.no_update; }
        document.cookie = "%s=" + lang + "; path=/; max-age=31536000; SameSite=Lax";
        window.location.reload();
        return lang;
    }
    """ % LANG_COOKIE,
    Output("lang-sink", "data"),
    Input("lang-en", "n_clicks"),
    Input("lang-es", "n_clicks"),
    prevent_initial_call=True,
)


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    import webbrowser, threading, time, subprocess, shutil

    port = 8050
    url  = f"http://localhost:{port}"

    def _find_chrome():
        """Locate a Chrome executable on Windows without relying on the OS
        default-browser association (which may be set to Edge)."""
        program_dirs = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LocalAppData"),
        ]
        for base in program_dirs:
            if not base:
                continue
            candidate = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.isfile(candidate):
                return candidate
        return shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chrome.exe")

    def open_browser():
        time.sleep(2.0)
        try:
            if sys.platform == "win32":
                chrome_exe = _find_chrome()
                if chrome_exe:
                    subprocess.Popen([chrome_exe, url])
                else:
                    # Chrome not found: fall back to whatever the OS has set as default.
                    os.startfile(url)
            else:
                webbrowser.open(url)
        except Exception:
            pass

    print(f"\n{'='*50}")
    print(f"  Aletheia v{__version__} starting...")
    print(f"  Open in your browser: {url}")
    print(f"{'='*50}\n", flush=True)

    threading.Thread(target=open_browser, daemon=True).start()
    # Dash 3.x and 4.x both support .run(); fall back to .run_server() for older 2.x.
    run_method = getattr(app, "run", None) or getattr(app, "run_server", None)
    if run_method is None:
        raise RuntimeError("Cannot find app.run or app.run_server method on this Dash version")
    run_method(debug=False, port=port, host="0.0.0.0")
