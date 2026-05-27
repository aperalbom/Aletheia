"""
pages/sol_analyzer.py  —  Aletheia completo con cache en servidor
"""
import io, base64, time
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html, Input, Output, State, callback, dash_table, ctx
from dash.exceptions import PreventUpdate
import dash
from flask import send_file
import tempfile, os

from sol_analyzer_dash.core.analysis import (parse_file, run_m1, run_qcr, run_m2,
                            run_alternative_analysis)
from sol_analyzer_dash.core.cache    import save as csave, load as cload
from sol_analyzer_dash.core.loaders  import load as load_dataset, sniff as sniff_format

dash.register_page(__name__, path="/sol-analyzer", name="Aletheia")

PAL  = dict(good="#4A9B8F", bad="#C0756A", amber="#E8A838",
            slate="#6A7FA8", nodata="#B0A89A", neutral="#2C2C2A", muted="#888780")
SPAL = ["#4A9B8F","#6A7FA8","#E8A838","#C0756A","#B0A89A","#5DCAA5",
        "#185FA5","#EF9F27","#D85A30","#888780","#1D9E75","#378ADD"]
P    = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFAF8",
            font=dict(family="Inter,sans-serif", size=11, color="#2C2C2A"),
            margin=dict(l=44,r=16,t=36,b=40),
            legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0))

# ── helpers ───────────────────────────────────────────────────────────────────
def stat(n, label, sub, cls):
    return html.Div(className=f"stat-card {cls}", children=[
        html.Div(str(n), className="stat-n"),
        html.Div(label,  className="stat-label"),
        html.Div(sub,    className="stat-sub") if sub else None,
    ])

def card(*children, title=None):
    inner = ([html.Div(title, className="card-title")] if title else []) + list(children)
    return html.Div(className="card", children=inner)

def graph(fig):
    return dcc.Graph(figure=fig, config={"displayModeBar":False})

def pxy(d):
    """Layout Plotly sin conflictos de xaxis/yaxis."""
    return dict(**P, xaxis=dict(gridcolor="#EBEBEB"), yaxis=dict(gridcolor="#EBEBEB"), **d)

def dl_btn(label, href):
    """Botón de descarga como link al endpoint del servidor — no automático."""
    return html.A(label, href=href, target="_blank",
                  className="btn-download",
                  style={"textDecoration":"none","display":"inline-flex",
                         "flexDirection":"column","gap":"2px","padding":"10px 16px",
                         "border":"1.5px solid #E4E2DC","borderRadius":"8px",
                         "background":"#F7F6F2","cursor":"pointer",
                         "fontFamily":"monospace","fontSize":"12px","color":"#2C2C2A",
                         "transition":"all .15s"})

# ── layout ────────────────────────────────────────────────────────────────────
def layout():
    return html.Div([
        dcc.Store(id="sol-file-key"),
        dcc.Store(id="sol-res-key"),

        html.Div(className="page-header", children=[
            html.H1("Aletheia", className="page-title"),
            html.P("Linealidad QC · QC réplicas · CV/ICC · Análisis conjunto",
                   className="page-sub"),
        ]),

        card(
            dcc.Upload(id="sol-upload", multiple=False,
                children=html.Div([
                    html.Div("⊞", style={"fontSize":"2rem","marginBottom":".4rem"}),
                    html.Div("Arrastra el CSV o haz clic", className="upload-title"),
                    html.Div("SOL*_CompleteExperiment.csv", className="upload-sub"),
                ]), className="upload-zone"),
            html.Div(id="sol-upload-info"),
            title="① Archivo",
        ),

        card(
            html.Div(className="config-panel", children=[
                html.Div(className="config-item", children=[
                    html.Div("R² linealidad", className="config-label"),
                    dcc.Slider(id="sl-r2", min=0.3, max=0.95, step=0.05, value=0.60,
                               marks={v:f"{v:.2f}" for v in [0.3,0.5,0.6,0.7,0.8,0.95]},
                               tooltip={"placement":"bottom"}),
                ], style={"width":"200px"}),
                html.Div(className="config-item", children=[
                    html.Div("%CV muestras", className="config-label"),
                    dcc.Slider(id="sl-cv", min=5, max=50, step=5, value=20,
                               marks={v:f"{v}%" for v in [5,10,20,30,50]},
                               tooltip={"placement":"bottom"}),
                ], style={"width":"180px"}),
                html.Div(className="config-item", children=[
                    html.Div("%CV QC norm.", className="config-label"),
                    dcc.Slider(id="sl-qccv", min=5, max=30, step=5, value=15,
                               marks={v:f"{v}%" for v in [5,10,15,20,30]},
                               tooltip={"placement":"bottom"}),
                ], style={"width":"180px"}),
                html.Div(className="config-item", children=[
                    html.Div("Umbral inyección", className="config-label"),
                    dcc.Slider(id="sl-inj", min=40, max=90, step=5, value=70,
                               marks={v:f"{v}%" for v in [40,55,70,85]},
                               tooltip={"placement":"bottom"}),
                ], style={"width":"180px"}),
                html.Div(className="config-item", children=[
                    html.Div("Opciones", className="config-label"),
                    dcc.Checklist(id="sol-opts",
                        options=[{"label":" Drop lowest","value":"drop"},
                                 {"label":" 2pt → aceptar","value":"a2p"},
                                 {"label":" Ion suppression","value":"ionsup"}],
                        value=["drop","a2p"],
                        style={"fontSize":"12px","display":"flex",
                               "flexDirection":"column","gap":"4px"}),
                ]),
                html.Div(className="config-item", children=[
                    html.Div("Modo", className="config-label"),
                    dcc.RadioItems(id="sol-modo",
                        options=[{"label":" Linealidad + CV","value":"combinado"},
                                 {"label":" Solo linealidad","value":"linealidad"}],
                        value="combinado",
                        style={"fontSize":"12px","display":"flex",
                               "flexDirection":"column","gap":"4px"}),
                ]),
                html.Button("▶ Analizar", id="sol-run", className="btn-primary",
                            disabled=True, style={"alignSelf":"flex-end"}),
            ]),
            title="② Configuración",
        ),

        dcc.Loading(type="circle", color=PAL["good"], children=[
            html.Div(id="sol-results"),
        ]),
    ])

# ── callbacks ─────────────────────────────────────────────────────────────────

@callback(Output("sol-file-key","data"), Output("sol-upload-info","children"),
          Output("sol-run","disabled"),
          Input("sol-upload","contents"), State("sol-upload","filename"),
          prevent_initial_call=True)
def on_upload(contents, filename):
    """Multi-format ingestion via the loaders package.

    The upload payload is dumped to a temporary file, then `load_dataset`
    auto-detects the source format (MetaboScape, MZmine 3, XCMS, MS-DIAL)
    and returns a ParsedDataset. We feed the QC pipeline through the
    legacy-dict view so all downstream code (run_m1, run_qcr, run_m2)
    keeps working unchanged.
    """
    if not contents: raise PreventUpdate
    tmppath = None
    try:
        _, b64 = contents.split(",")
        # Dump bytes to a temp file (the loaders need a filesystem path).
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            tf.write(base64.b64decode(b64))
            tmppath = tf.name

        fmt = sniff_format(tmppath)
        if fmt is None:
            return (
                None,
                html.Div(
                    [html.Span("✗ ", style={"color": PAL["bad"], "fontWeight": "600"}),
                     html.Span(f"{filename}: could not auto-detect format. "
                                "Use the generic CSV loader via the CLI.",
                                style={"color": PAL["bad"], "fontSize": "12px"})],
                    style={"marginTop": ".5rem"}),
                True,
            )

        ds = load_dataset(tmppath, fmt=fmt)
        parsed = ds.to_legacy_dict()
        # Cache both the legacy dict and the ParsedDataset for the (forth-
        # coming) Sample-Mapping UI step.
        key = csave({"parsed": parsed, "fmt": fmt,
                      "mapping": ds.to_mapping_json()})
        p = parsed
        info = html.Div([
            html.Span(f"✓ {filename}",
                      style={"color": PAL["good"], "fontWeight": "600", "fontSize": "13px"}),
            html.Span(f"  ·  fmt={fmt}  ·  {p['n_metabolites']} metabolitos  ·  "
                      f"{p['n_samples']} muestras × {p['reps_per_sample']} réplicas  ·  "
                      f"{p['reps_per_level']} réplica/nivel QC",
                      style={"color": PAL["muted"], "fontSize": "11px", "fontFamily": "monospace"}),
        ], style={"marginTop": ".5rem"})
        return key, info, False
    except Exception as e:
        return None, html.Div(f"Error: {e}", style={"color": PAL["bad"]}), True
    finally:
        if tmppath and os.path.exists(tmppath):
            try:
                os.unlink(tmppath)
            except Exception:
                pass


@callback(Output("sol-res-key","data"), Output("sol-results","children"),
          Input("sol-run","n_clicks"),
          State("sol-file-key","data"), State("sl-r2","value"),
          State("sl-cv","value"),       State("sl-qccv","value"),
          State("sl-inj","value"),      State("sol-opts","value"),
          State("sol-modo","value"),
          prevent_initial_call=True)
def on_run(_, fkey, r2, cv, qccv, inj, opts, modo):
    if not fkey: raise PreventUpdate
    cached = cload(fkey)
    if not cached: raise PreventUpdate
    parsed = cached["parsed"]
    opts   = opts or []
    N      = parsed["n_metabolites"]

    print(f"\n[SOL] Analizando {N} metabolitos...", flush=True)
    t0 = time.time()

    print("[M1] Linealidad...", flush=True)
    m1 = run_m1(parsed, r2_threshold=r2, allow2pt="a2p" in opts,
                use_drop="drop" in opts, ion_sup="ionsup" in opts)
    print(f"[M1] {len(m1['good'])} aceptados en {time.time()-t0:.1f}s", flush=True)

    print("[QCR] Réplicas...", flush=True)
    t1 = time.time()
    qcr = run_qcr(parsed, inj_threshold=inj/100)
    print(f"[QCR] OK en {time.time()-t1:.1f}s", flush=True)

    m2 = None
    if modo == "combinado":
        print("[M2] CV/ICC...", flush=True)
        t2 = time.time()
        m2 = run_m2(parsed, cv_threshold=cv, qc_cv_thresh=qccv)
        print(f"[M2] OK en {time.time()-t2:.1f}s", flush=True)

    print(f"[SOL] Total: {time.time()-t0:.1f}s", flush=True)

    rkey = csave({"m1":m1,"qcr":qcr,"m2":m2,"parsed":parsed,"modo":modo,"N":N})

    tabs = [dcc.Tab(label="M1 · Linealidad", value="m1"),
            dcc.Tab(label="QCR · Réplicas",  value="qcr")]
    if modo == "combinado":
        tabs += [dcc.Tab(label="M2 · CV/ICC",      value="m2"),
                 dcc.Tab(label="Análisis conjunto", value="jt")]
    tabs += [dcc.Tab(label="⚡ Análisis alternativo", value="alt")]

    return rkey, html.Div([
        # Botón PDF global
        html.Div(style={"display":"flex","justifyContent":"flex-end","marginBottom":"1rem"}, children=[
            html.A(
                "📄 Exportar informe PDF completo",
                href=f"/dl/{rkey}/pdf",
                target="_blank",
                style={"background":"#2C2C2A","color":"#fff","padding":"10px 20px",
                       "borderRadius":"8px","textDecoration":"none","fontSize":"12px",
                       "fontFamily":"monospace","letterSpacing":".05em","fontWeight":"500"},
            ),
        ]),
        dcc.Tabs(id="sol-tabs", value="m1", children=tabs,
                 style={"marginBottom":"1.5rem"}),
        html.Div(id="sol-tab-body", children=_tab_m1(m1, N, rkey)),
    ])


@callback(Output("sol-tab-body","children"),
          Input("sol-tabs","value"),
          State("sol-res-key","data"),
          prevent_initial_call=True)
def on_tab(tab, rkey):
    if not rkey: raise PreventUpdate
    d = cload(rkey)
    if not d: raise PreventUpdate
    m1=d["m1"]; qcr=d["qcr"]; m2=d["m2"]; N=d["N"]
    if tab=="m1":  return _tab_m1(m1, N, rkey)
    if tab=="qcr": return _tab_qcr(qcr, N, rkey)
    if tab=="m2"  and m2: return _tab_m2(m2, N, rkey)
    if tab=="jt"  and m2: return _tab_jt(m1, m2, N, rkey)
    if tab=="alt": return _tab_alt(d, rkey)
    return html.Div("No disponible.",
                    style={"color":PAL["muted"],"padding":"2rem","fontFamily":"monospace"})

# ── tab renders ───────────────────────────────────────────────────────────────

def _tab_m1(m1, N, rkey):
    good=m1["good"]; bad=m1["bad"]; nodat=m1["nodat"]; thr=m1["r2_threshold"]
    n_is  = int((good["reason"]=="ion_suppression").sum()) if "reason" in good.columns else 0
    n_pos = len(good)-n_is

    lbls=[" Aceptados","Rechazados","Sin datos"]; vals=[len(good),len(bad),len(nodat)]
    cols=[PAL["good"],PAL["bad"],PAL["nodata"]]
    if n_is:
        lbls.insert(1,"Ion supp."); vals.insert(1,n_is); cols.insert(1,PAL["amber"])
        vals[0]=n_pos

    fig_don=go.Figure(go.Pie(labels=lbls,values=vals,marker_colors=cols,
                             hole=.62,textinfo="none"))
    fig_don.add_annotation(text=f"<b>{N}</b><br>total",x=.5,y=.5,
                           showarrow=False,font=dict(size=13))
    fig_don.update_layout(**pxy(dict(title="Resumen",height=260)))

    r2g=good["r2"].dropna().values; r2b=bad["r2"].dropna().values
    fig_his=go.Figure()
    fig_his.add_trace(go.Histogram(x=r2g,name="Aceptados",xbins=dict(size=.05),
                                   marker_color=PAL["good"],opacity=.8))
    fig_his.add_trace(go.Histogram(x=r2b,name="Rechazados",xbins=dict(size=.05),
                                   marker_color=PAL["bad"],opacity=.8))
    fig_his.add_vline(x=thr,line_dash="dash",line_color=PAL["neutral"])
    fig_his.update_layout(**P,title="Distribución R²",barmode="overlay",height=260,
                          xaxis=dict(range=[0,1],gridcolor="#EBEBEB"),
                          yaxis=dict(gridcolor="#EBEBEB"))

    RMAP={"negative_slope":"Pend. negativa","r2_low":"R² bajo","only_1_point":"1 punto",
          "no_data":"Sin señal","only_2_points":"2 puntos","r2_na":"R² N/A",
          "ion_suppression":"Ion suppression"}
    rej=m1["lin_df"][~m1["lin_df"]["ok"]]["reason"].map(RMAP).value_counts()
    fig_rej=go.Figure(go.Bar(x=rej.values,y=rej.index,orientation="h",
                             marker_color=PAL["bad"],opacity=.85))
    fig_rej.update_layout(**pxy(dict(title="Motivos exclusión",height=260)))

    sc=m1["lin_df"].dropna(subset=["r2_full"])
    fig_sct=go.Figure(go.Scatter(x=sc["r2_full"],y=sc["r2_full"],mode="markers",
        marker=dict(color=PAL["nodata"],size=3,opacity=.3)))
    fig_sct.update_layout(**P,title="R² distribución full vs drop",height=260,
                          xaxis=dict(range=[0,1],title="R² full",gridcolor="#EBEBEB"),
                          yaxis=dict(range=[0,1],title="R²",gridcolor="#EBEBEB"))

    stats=html.Div(className="stat-grid stat-4",children=[
        stat(N,        "Total",       None,                                            "stat-muted"),
        stat(n_pos,    "Aceptados",   f"{100*n_pos/N:.1f}%  ·  {n_pos}/{N}",          "stat-good"),
        stat(len(bad), "Rechazados",  f"{100*len(bad)/N:.1f}%  ·  {len(bad)}/{N}",    "stat-bad"),
        stat(len(nodat),"Sin datos",  f"{100*len(nodat)/N:.1f}%  ·  {len(nodat)}/{N}","stat-muted"),
    ]+([stat(n_is,"Ion suppression",  f"{100*n_is/N:.1f}%  ·  {n_is}/{N}",            "stat-amber")] if n_is else []))

    return html.Div([
        stats,
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"1rem"},children=[
            card(graph(fig_don)),card(graph(fig_his)),
            card(graph(fig_rej)),card(graph(fig_sct)),
        ]),
        card(html.Div(style={"display":"flex","gap":".8rem","flexWrap":"wrap"},children=[
            dl_btn("⬇ experiment_filtered.csv", f"/dl/{rkey}/filtered"),
            dl_btn("⬇ good_coor.csv",           f"/dl/{rkey}/good"),
            dl_btn("⬇ bad_coor.csv",            f"/dl/{rkey}/bad"),
        ]), title="Descargar M1"),
    ])


def _tab_qcr(qcr, N, rkey):
    df=qcr["qcr_df"]
    samples=sorted(df["Sample"].unique())

    fig_bar=go.Figure()
    for est,col,lbl in [("ok",PAL["good"],"Válida"),
                        ("suspect",PAL["amber"],"Sospechosa"),
                        ("fail",PAL["bad"],"Fallo")]:
        cnts=[len(df[(df["Sample"]==s)&(df["Estado"]==est)]) for s in samples]
        fig_bar.add_trace(go.Bar(x=[f"S{s}" for s in samples],y=cnts,
                                 name=lbl,marker_color=col,opacity=.85))
    fig_bar.update_layout(**pxy(dict(barmode="stack",title="Estado por muestra",height=260)))

    fig_sum=go.Figure()
    for est,col,lbl in [("ok",PAL["good"],"Válida"),
                        ("suspect",PAL["amber"],"Sospechosa"),
                        ("fail",PAL["bad"],"Fallo")]:
        sub=df[df["Estado"]==est]
        fig_sum.add_trace(go.Scatter(
            x=[f"S{r.Sample} R{r.Replica}" for r in sub.itertuples()],
            y=sub["Suma_int"]/1e6,mode="markers",
            marker=dict(color=col,size=9,opacity=.85),name=lbl))
    fig_sum.update_layout(**pxy(dict(title="Suma de intensidades",
                                     yaxis_title="Suma int. (×10⁶)",height=260)))

    valid=df[df["Estado"]!="fail"]
    thr_out=N*0.05
    fig_out=go.Figure(go.Bar(
        x=[f"S{r.Sample} R{r.Replica}" for r in valid.itertuples()],
        y=valid["N_outliers"],
        marker_color=[PAL["amber"] if n>thr_out else PAL["good"] for n in valid["N_outliers"]],
        opacity=.85))
    fig_out.add_hline(y=thr_out,line_dash="dash",line_color=PAL["bad"],
                      annotation_text="5% metab.",annotation_position="top right")
    fig_out.update_layout(**pxy(dict(title="Outliers por metabolito",
                                     yaxis_title="n metabolitos",height=260)))

    tbl_cols = ["Sample","Replica","Column","Suma_int","Mediana_int",
                "Falla_suma","Falla_med","Estado","N_outliers","Recomendacion"]
    table=dash_table.DataTable(
        data=df[tbl_cols].round({"Suma_int":0,"Mediana_int":0}).to_dict("records"),
        columns=[{"name":c,"id":c} for c in tbl_cols],
        style_table={"overflowX":"auto"},
        style_cell={"fontFamily":"monospace","fontSize":"11px","padding":"5px 9px",
                    "maxWidth":"260px","textOverflow":"ellipsis","overflow":"hidden"},
        style_cell_conditional=[
            {"if":{"column_id":"Column"},
             "fontSize":"10px","textAlign":"left","maxWidth":"340px"},
        ],
        style_header={"background":"#F7F6F2","fontWeight":"600","color":"#888780"},
        style_data_conditional=[
            {"if":{"filter_query":'{Estado} = "fail"'},    "background":"#fff5f5"},
            {"if":{"filter_query":'{Estado} = "suspect"'}, "background":"#fffbec"},
        ],
        tooltip_data=[
            {"Column": {"value": str(r["Column"]), "type": "text"}}
            for r in df[tbl_cols].to_dict("records")
        ],
        tooltip_duration=None,
        page_size=20,
    )

    warns=[]
    if qcr["n_fail"]>0:
        failed=df[df["Estado"]=="fail"]
        warns.append(html.Div(className="alert-warn",children=[
            html.Div(f"⚠ {qcr['n_fail']} réplica(s) con fallo confirmado",
                     style={"fontWeight":"600","marginBottom":"4px"}),
            html.Ul([
                html.Li(f"S{r.Sample} · R{r.Replica}  —  {r.Column}",
                        style={"fontFamily":"monospace","fontSize":"11px"})
                for r in failed.itertuples()
            ], style={"margin":"4px 0 0 18px"}),
        ]))
    if qcr["n_suspect"]>0:
        susp=df[df["Estado"]=="suspect"]
        warns.append(html.Div(className="alert-info",
            style={"background":"#fffbec","border":"1px solid #E8D68C",
                   "padding":"10px 14px","borderRadius":"8px","margin":".5rem 0"},
            children=[
                html.Div(f"⚠ {qcr['n_suspect']} réplica(s) sospechosa(s)",
                         style={"fontWeight":"600","marginBottom":"4px"}),
                html.Ul([
                    html.Li(f"S{r.Sample} · R{r.Replica}  —  {r.Column}",
                            style={"fontFamily":"monospace","fontSize":"11px"})
                    for r in susp.itertuples()
                ], style={"margin":"4px 0 0 18px"}),
            ]))

    n_total_reps = qcr["n_ok"] + qcr["n_suspect"] + qcr["n_fail"]
    stats=html.Div(className="stat-grid stat-4",children=[
        stat(qcr["n_ok"],            "Válidas",
             f"{100*qcr['n_ok']/n_total_reps:.1f}%  ·  {qcr['n_ok']}/{n_total_reps}", "stat-good"),
        stat(qcr["n_suspect"],       "Sospechosas",
             f"1 criterio  ·  {qcr['n_suspect']}/{n_total_reps}",                      "stat-amber"),
        stat(qcr["n_fail"],          "Fallos",
             f"ambos criterios  ·  {qcr['n_fail']}/{n_total_reps}",                    "stat-bad"),
        stat(qcr["n_outlier_total"], "Outliers metab.",
             "réplicas válidas",                                                         "stat-slate"),
    ])

    return html.Div([
        stats,*warns,
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"1rem"},children=[
            card(graph(fig_bar)),card(graph(fig_sum)),
            card(graph(fig_out)),
        ]),
        card(table, title="Detalle por réplica"),
        card(html.Div(style={"display":"flex","gap":".8rem","flexWrap":"wrap"},children=[
            dl_btn("⬇ qcr_report.csv",            f"/dl/{rkey}/qcr"),
            dl_btn("⬇ experiment_aggregated.csv", f"/dl/{rkey}/agg"),
        ]), title="Descargar QCR"),
    ])


def _tab_m2(m2, N, rkey):
    cv_df=m2["cv_df"]; icc=m2["icc_vec"]; cv_qc=m2["cv_qc"]
    samples=m2["real_samples"]; thr=m2["cv_threshold"]; thr_qc=m2["qc_cv_thresh"]

    # Boxplot %CV con línea de corte
    fig_box=go.Figure()
    for i,s in enumerate(samples):
        v=cv_df[f"CV_S{s}"].dropna().values; v=v[v<200]
        fig_box.add_trace(go.Box(y=v,name=f"S{s}",
            marker_color=SPAL[i%len(SPAL)],line_color=SPAL[i%len(SPAL)],showlegend=False))
    fig_box.add_hline(y=thr,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"{thr}%",annotation_position="top right")
    fig_box.update_layout(**pxy(dict(title="%CV por muestra",height=280)))

    # Histograma CV mediana con línea de corte
    cv_med=cv_df["CV_median"].dropna().values
    fig_cvh=go.Figure(go.Histogram(x=cv_med,xbins=dict(size=2),
                                   marker_color=PAL["good"],opacity=.85))
    fig_cvh.add_vline(x=thr,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"{thr}%",annotation_position="top right")
    fig_cvh.update_layout(**pxy(dict(title="CV mediana global",height=280)))

    # CV QC con línea de corte del 20% (thr) Y la del QC (thr_qc)
    cv_qc_c=cv_qc[~np.isnan(cv_qc)&(cv_qc<200)]
    fig_qcc=go.Figure(go.Histogram(x=cv_qc_c,xbins=dict(size=2),
                                   marker_color=PAL["amber"],opacity=.85))
    fig_qcc.add_vline(x=thr_qc,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"QC: {thr_qc}%",annotation_position="top right")
    fig_qcc.add_vline(x=thr,line_dash="dot",line_color=PAL["slate"],
                      annotation_text=f"Muestras: {thr}%",annotation_position="top left")
    fig_qcc.update_layout(**pxy(dict(title="CV QC normalización",height=280)))

    icc_c=icc[~np.isnan(icc)]
    fig_icc=go.Figure()
    fig_icc.add_trace(go.Histogram(x=icc_c[icc_c<.75],xbins=dict(size=.05),
                                   marker_color=PAL["nodata"],name="ICC<0.75",opacity=.85))
    fig_icc.add_trace(go.Histogram(x=icc_c[icc_c>=.75],xbins=dict(size=.05),
                                   marker_color=PAL["good"],name="ICC≥0.75",opacity=.85))
    fig_icc.add_vline(x=.75,line_dash="dash",line_color=PAL["neutral"])
    fig_icc.update_layout(**pxy(dict(title="ICC",barmode="overlay",height=280)))

    # CV biológico: separar features computables (CV_median no-NaN) de las
    # no calculables (≤1 réplica válida por muestra, o cero muestras
    # biológicas en el experimento → CV_median = NaN). Las no calculables
    # NO se cuentan como "CV > umbral".
    cv_med_arr = cv_df["CV_median"].values
    n_na_cv  = int(np.isnan(cv_med_arr).sum())
    n_ok_cv  = int(cv_df["CV_ok"].sum())
    n_bad_cv = N - n_ok_cv - n_na_cv
    n_calc   = N - n_na_cv  # denominador "features con CV calculable"
    n_ok_icc = int(np.sum(icc > .75))

    if n_calc == 0:
        # Experimento sin muestras biológicas (e.g. validación QC-only):
        # CV inter-muestra no aplica. Mostrar aviso en vez de "100% bad".
        stats = html.Div(className="stat-grid stat-3", children=[
            stat("—", "CV biológico", "Sin muestras biológicas", "stat-slate"),
            stat("—", "CV biológico", "No aplicable", "stat-slate"),
            stat(n_ok_icc, "ICC > 0.75", "No aplicable", "stat-slate"),
        ])
    else:
        cv_caption_ok  = f"{100*n_ok_cv/n_calc:.1f}%  ·  {n_ok_cv}/{n_calc}"
        cv_caption_bad = f"{100*n_bad_cv/n_calc:.1f}%  ·  {n_bad_cv}/{n_calc}"
        if n_na_cv:
            cv_caption_ok  += f"  ({n_na_cv} sin CV)"
            cv_caption_bad += f"  ({n_na_cv} sin CV)"
        stats = html.Div(className="stat-grid stat-3", children=[
            stat(n_ok_cv,  f"CV ≤ {thr}%", cv_caption_ok,  "stat-good"),
            stat(n_bad_cv, f"CV > {thr}%", cv_caption_bad, "stat-bad"),
            stat(n_ok_icc, "ICC > 0.75",
                 f"{100*n_ok_icc/N:.1f}%  ·  {n_ok_icc}/{N}", "stat-slate"),
        ])

    return html.Div([
        stats,
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"1rem"},children=[
            card(graph(fig_box)),card(graph(fig_cvh)),
            card(graph(fig_qcc)),card(graph(fig_icc)),
        ]),
        card(dl_btn("⬇ cv_per_sample.csv", f"/dl/{rkey}/cv"), title="Descargar M2"),
    ])


def _tab_jt(m1, m2, N, rkey):
    cv_med  = m2["cv_df"]["CV_median"].values
    icc     = m2["icc_vec"]
    r2      = m1["lin_df"]["r2"].fillna(0).values
    lin_ok  = m1["lin_df"]["ok"].values
    cv_ok   = m2["cv_df"]["CV_ok"].values
    thr_cv  = m2["cv_threshold"]
    thr_r2  = m1["r2_threshold"]

    n_lin      = int(lin_ok.sum())
    n_cv       = int(cv_ok.sum())
    n_both     = int((lin_ok & cv_ok).sum())
    n_lin_only = n_lin - n_both
    n_cv_only  = n_cv  - n_both
    n_neither  = N - n_lin - n_cv + n_both

    # Scatter R² vs CV
    fig_rv=go.Figure(go.Scatter(
        x=r2, y=np.minimum(cv_med,100), mode="markers",
        marker=dict(color=[PAL["good"] if o else PAL["bad"] for o in lin_ok],
                    size=3,opacity=.3),
        hovertemplate="R²=%{x:.3f}<br>CV=%{y:.1f}%<extra></extra>"))
    fig_rv.add_hline(y=thr_cv,line_dash="dash",line_color=PAL["bad"],
                     annotation_text=f"CV {thr_cv}%")
    fig_rv.add_vline(x=thr_r2,line_dash="dash",line_color=PAL["bad"],
                     annotation_text=f"R² {thr_r2}")
    fig_rv.update_layout(**P,title="R² vs %CV mediana",height=320,
                          xaxis=dict(title="R²",gridcolor="#EBEBEB"),
                          yaxis=dict(title="%CV (cap 100%)",gridcolor="#EBEBEB"))

    # Diagrama de Venn aproximado con SVG como scatter Plotly
    # Usamos dos círculos con shapes y anotaciones de texto
    fig_venn=go.Figure()
    fig_venn.add_shape(type="circle",x0=0.15,y0=0.1,x1=0.75,y1=0.9,
                       fillcolor=PAL["good"],opacity=0.25,
                       line=dict(color=PAL["good"],width=2))
    fig_venn.add_shape(type="circle",x0=0.35,y0=0.1,x1=0.95,y1=0.9,
                       fillcolor=PAL["slate"],opacity=0.25,
                       line=dict(color=PAL["slate"],width=2))
    # Etiquetas
    fig_venn.add_annotation(x=0.28,y=0.5,text=f"<b>{n_lin_only}</b><br>Solo linealidad",
                            showarrow=False,font=dict(size=11,color=PAL["good"]))
    fig_venn.add_annotation(x=0.55,y=0.5,text=f"<b>{n_both}</b><br>Ambos",
                            showarrow=False,font=dict(size=12,color=PAL["neutral"]))
    fig_venn.add_annotation(x=0.82,y=0.5,text=f"<b>{n_cv_only}</b><br>Solo CV",
                            showarrow=False,font=dict(size=11,color=PAL["slate"]))
    fig_venn.add_annotation(x=0.55,y=0.05,
                            text=f"Sin ninguno: {n_neither}  ·  Total: {N}",
                            showarrow=False,font=dict(size=10,color=PAL["muted"]),
                            xref="paper",yref="paper")
    fig_venn.add_annotation(x=0.28,y=0.95,text="Linealidad",
                            showarrow=False,font=dict(size=10,color=PAL["good"]),
                            xref="paper",yref="paper")
    fig_venn.add_annotation(x=0.82,y=0.95,text=f"CV ≤ {thr_cv}%",
                            showarrow=False,font=dict(size=10,color=PAL["slate"]),
                            xref="paper",yref="paper")
    fig_venn.update_layout(paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                           title="Venn · Linealidad vs CV",height=320,
                           margin=dict(l=10,r=10,t=36,b=30),
                           xaxis=dict(visible=False,range=[0,1]),
                           yaxis=dict(visible=False,range=[0,1]),
                           showlegend=False)

    # Scatter CV vs ICC
    mask=~np.isnan(cv_med)&~np.isnan(icc)
    fig_ci=go.Figure(go.Scatter(
        x=icc[mask],y=np.minimum(cv_med[mask],100),mode="markers",
        marker=dict(color=PAL["slate"],size=3,opacity=.3)))
    fig_ci.add_hline(y=thr_cv,line_dash="dash",line_color=PAL["bad"])
    fig_ci.add_vline(x=.75,line_dash="dash",line_color=PAL["bad"])
    fig_ci.update_layout(**P,title="CV vs ICC",height=320,
                          xaxis=dict(title="ICC",gridcolor="#EBEBEB"),
                          yaxis=dict(title="%CV (cap 100%)",gridcolor="#EBEBEB"))

    stats=html.Div(className="stat-grid stat-3",children=[
        stat(n_both, "Pasan ambos",        f"{100*n_both/N:.1f}%  ·  {n_both}/{N}",  "stat-good"),
        stat(n_lin,  "Pasan linealidad",   f"{100*n_lin/N:.1f}%  ·  {n_lin}/{N}",    "stat-slate"),
        stat(n_cv,   f"Pasan CV≤{thr_cv}%",f"{100*n_cv/N:.1f}%  ·  {n_cv}/{N}",    "stat-amber"),
    ])

    return html.Div([
        stats,
        html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr","gap":"1rem"},children=[
            card(graph(fig_rv)),card(graph(fig_venn)),
            card(graph(fig_ci)),
        ]),
        card(html.Div(style={"display":"flex","gap":".8rem","flexWrap":"wrap"},children=[
            dl_btn("⬇ combined_results.csv",  f"/dl/{rkey}/combined"),
            dl_btn("⬇ pass_all_criteria.csv", f"/dl/{rkey}/pass"),
        ]), title="Descargar combinado"),
    ])


# ── ANÁLISIS ALTERNATIVO ───────────────────────────────────────────────────────

_ALT_INFO = (
    "Re-ejecuta el pipeline completo (linealidad + CV/ICC + agregación) "
    "después de descartar las réplicas seleccionadas. No se imputan valores: "
    "cada muestra queda con su n efectivo real. Si una muestra se queda con "
    "≤1 réplica válida, su CV intra-muestra se reporta como NaN y se indica "
    "en la tabla."
)

def _alt_mode_options(qcr_df):
    n_fail    = int((qcr_df["Estado"] == "fail").sum())
    n_suspect = int((qcr_df["Estado"] == "suspect").sum())
    return [
        {"label": f"  Ninguna (análisis original)", "value": "none"},
        {"label": f"  Solo fallidas  ({n_fail})",     "value": "fail"},
        {"label": f"  Fallidas + sospechosas  ({n_fail + n_suspect})",
                                                       "value": "fail_suspect"},
        {"label": f"  Selección manual",               "value": "manual"},
    ]

def _tab_alt(d, rkey):
    qcr    = d["qcr"]
    qcr_df = qcr["qcr_df"]
    # Candidatos a excluir en modo manual: todas las réplicas (la mayoría ok)
    manual_opts = [
        {"label": f"S{r.Sample} · R{r.Replica}  —  {r.Column}  ({r.Estado})",
         "value": r.Column}
        for r in qcr_df.itertuples()
    ]
    default_manual = qcr_df[qcr_df["Estado"].isin(["fail", "suspect"])]["Column"].tolist()

    return html.Div([
        card(
            html.Div([
                html.P(_ALT_INFO, style={"color":PAL["muted"],"fontSize":"12px",
                                          "lineHeight":"1.5","marginTop":"0"}),
                html.Div(style={"display":"grid",
                                "gridTemplateColumns":"1fr 1fr","gap":"1.5rem",
                                "marginTop":".8rem"},children=[
                    html.Div([
                        html.Div("Modo de exclusión", className="config-label",
                                 style={"fontWeight":"600","marginBottom":"6px"}),
                        dcc.RadioItems(id="alt-mode",
                            options=_alt_mode_options(qcr_df),
                            value="fail_suspect",
                            style={"fontSize":"12px","display":"flex",
                                   "flexDirection":"column","gap":"5px"}),
                    ]),
                    html.Div(id="alt-manual-wrap",
                             style={"display":"none","maxHeight":"220px",
                                    "overflowY":"auto","border":"1px solid #E4E2DC",
                                    "borderRadius":"6px","padding":"8px"},
                             children=[
                        html.Div("Réplicas a excluir:", style={"fontSize":"11px",
                                                                "fontWeight":"600",
                                                                "color":PAL["muted"],
                                                                "marginBottom":"4px"}),
                        dcc.Checklist(id="alt-manual-cols",
                                      options=manual_opts, value=default_manual,
                                      style={"fontSize":"10px","fontFamily":"monospace",
                                             "display":"flex","flexDirection":"column",
                                             "gap":"2px"}),
                    ]),
                ]),
                html.Div(style={"marginTop":"1rem"},children=[
                    html.Button("▶ Re-analizar sin réplicas excluidas",
                                id="alt-run", className="btn-primary"),
                ]),
            ]),
            title="Configurar análisis alternativo"),
        dcc.Loading(type="circle", color=PAL["good"], children=[
            html.Div(id="alt-results", style={"marginTop":"1rem"}),
        ]),
    ])


@callback(Output("alt-manual-wrap","style"),
          Input("alt-mode","value"),
          prevent_initial_call=True)
def _toggle_manual(mode):
    base = {"maxHeight":"220px","overflowY":"auto","border":"1px solid #E4E2DC",
            "borderRadius":"6px","padding":"8px"}
    if mode == "manual":
        base["display"] = "block"
    else:
        base["display"] = "none"
    return base


def _alt_err_panel(exc: Exception) -> html.Div:
    """Inline error panel — surfaces a full traceback so the spinner
    doesn't keep spinning silently when something breaks."""
    import traceback
    tb = traceback.format_exc()
    return html.Div(style={"padding":"14px 16px","border":"1px solid #C0756A",
                           "background":"#FBEFEC","borderRadius":"8px",
                           "color":"#5A2E26"}, children=[
        html.Div("⚠ Error en el análisis alternativo",
                 style={"fontWeight":"700","marginBottom":"6px"}),
        html.Div(f"{type(exc).__name__}: {exc}",
                 style={"fontFamily":"monospace","fontSize":"12px",
                        "marginBottom":"8px"}),
        html.Pre(tb, style={"fontSize":"10.5px","whiteSpace":"pre-wrap",
                            "background":"#F7F1EE","padding":"8px","borderRadius":"6px",
                            "maxHeight":"260px","overflow":"auto","margin":"0"}),
    ])


@callback(Output("alt-results","children"),
          Input("alt-run","n_clicks"),
          State("alt-mode","value"),
          State("alt-manual-cols","value"),
          State("sol-res-key","data"),
          State("sl-r2","value"),   State("sl-cv","value"),
          State("sl-qccv","value"), State("sl-inj","value"),
          State("sol-opts","value"), State("sol-modo","value"),
          prevent_initial_call=True)
def _run_alt(_, mode, manual_cols, rkey, r2, cv, qccv, inj, opts, modo):
    if not rkey or not mode: raise PreventUpdate
    d = cload(rkey)
    if not d: raise PreventUpdate
    opts = opts or []

    try:
        alt = run_alternative_analysis(
            parsed=d["parsed"], qcr=d["qcr"],
            mode=mode, manual_cols=manual_cols,
            r2_threshold=r2, allow2pt="a2p" in opts,
            use_drop="drop" in opts, ion_sup="ionsup" in opts,
            cv_threshold=cv, qc_cv_thresh=qccv,
            inj_threshold=inj/100,
        )
        # Guardar el resultado bajo una clave derivada para las descargas
        alt_key = csave({"m1": alt["m1_alt"], "qcr": alt["qcr_alt"],
                         "m2": alt["m2_alt"], "parsed": alt["parsed_alt"],
                         "modo": modo, "N": d["N"],
                         "alt_meta": {
                             "mode": alt["mode"],
                             "excluded_cols": alt["excluded_cols"],
                             "n_excluded": alt["n_excluded"],
                             "samples_dropped": alt["samples_dropped"],
                             "parent_key": rkey,
                         },
                         "alt_excluded_rows": alt["excluded_rows"],
                         "alt_n_eff":         alt["n_eff_per_sample"]})
        return _render_alt(d, alt, alt_key)
    except Exception as exc:
        return _alt_err_panel(exc)


def _render_alt(d_orig, alt, alt_key):
    N = d_orig["N"]
    # Stats comparativos
    m1_o, m1_a = d_orig["m1"], alt["m1_alt"]
    lin_o = int(m1_o["lin_df"]["ok"].sum())
    lin_a = int(m1_a["lin_df"]["ok"].sum())

    blocks = [
        # Cabecera con el modo aplicado y lista de réplicas descartadas
        card(
            html.Div([
                html.Div([
                    html.Span("Modo: ", style={"color":PAL["muted"],"fontSize":"11px"}),
                    html.Span({"none":"Ninguna","fail":"Solo fallidas",
                               "fail_suspect":"Fallidas + sospechosas",
                               "manual":"Selección manual"}[alt["mode"]],
                              style={"fontWeight":"600","color":PAL["neutral"]}),
                ]),
                html.Div(f"{alt['n_excluded']} réplica(s) excluidas",
                         style={"color":PAL["muted"],"fontSize":"11px","marginTop":"4px"}),
                html.Ul([
                    html.Li(f"S{r.Sample} · R{r.Replica}  —  {r.Column}  "
                            f"({r.Estado})",
                            style={"fontFamily":"monospace","fontSize":"10.5px",
                                   "color":"#5A5A57"})
                    for r in alt["excluded_rows"].itertuples()
                ], style={"marginTop":"6px","maxHeight":"180px","overflowY":"auto"})
                if alt["n_excluded"] else None,
                html.Div(
                    f"⚠ Muestras sin réplicas válidas: "
                    f"{', '.join(f'S{s}' for s in alt['samples_dropped'])}",
                    style={"color":PAL["bad"],"fontSize":"11px","marginTop":"8px",
                           "fontWeight":"600"})
                if alt["samples_dropped"] else None,
            ]), title="Configuración aplicada"),

        # Comparativa M1 antes/después
        card(
            html.Div(className="stat-grid stat-3", children=[
                stat(lin_o, "Aceptados (orig.)",
                     f"{100*lin_o/N:.1f}%  ·  {lin_o}/{N}", "stat-muted"),
                stat(lin_a, "Aceptados (alt.)",
                     f"{100*lin_a/N:.1f}%  ·  {lin_a}/{N}",
                     "stat-good" if lin_a >= lin_o else "stat-amber"),
                stat(lin_a - lin_o, "Δ M1",
                     f"{lin_a - lin_o:+d} metabolitos",
                     "stat-good" if lin_a >= lin_o else "stat-bad"),
            ]),
            title="Comparativa linealidad (M1)"),
    ]

    # Comparativa M2 si procede
    if d_orig["m2"] and alt["m2_alt"]:
        m2_o, m2_a = d_orig["m2"], alt["m2_alt"]
        cv_o = int(m2_o["cv_df"]["CV_ok"].sum())
        cv_a = int(m2_a["cv_df"]["CV_ok"].sum())
        thr  = m2_o["cv_threshold"]
        blocks.append(card(
            html.Div(className="stat-grid stat-3", children=[
                stat(cv_o, f"CV ≤ {thr}% (orig.)",
                     f"{100*cv_o/N:.1f}%  ·  {cv_o}/{N}", "stat-muted"),
                stat(cv_a, f"CV ≤ {thr}% (alt.)",
                     f"{100*cv_a/N:.1f}%  ·  {cv_a}/{N}",
                     "stat-good" if cv_a >= cv_o else "stat-amber"),
                stat(cv_a - cv_o, "Δ M2",
                     f"{cv_a - cv_o:+d} metabolitos",
                     "stat-good" if cv_a >= cv_o else "stat-bad"),
            ]),
            title="Comparativa CV (M2)"))
    elif d_orig["m2"] and alt["m2_error"]:
        blocks.append(card(
            html.Div(f"M2 no pudo recalcularse: {alt['m2_error']}",
                     style={"color":PAL["bad"],"fontSize":"12px"}),
            title="Error en M2 alternativo"))

    # Tabla n efectivo por muestra
    n_eff = alt["n_eff_per_sample"]
    blocks.append(card(
        dash_table.DataTable(
            data=n_eff.to_dict("records"),
            columns=[{"name":"Sample","id":"Sample"},
                     {"name":"n réplicas válidas","id":"n_valid_reps"}],
            style_cell={"fontFamily":"monospace","fontSize":"11px",
                        "padding":"4px 10px","textAlign":"center"},
            style_header={"background":"#F7F6F2","fontWeight":"600",
                          "color":"#888780"},
            style_data_conditional=[
                {"if":{"filter_query":'{n_valid_reps} < 2'},
                 "background":"#fff5f5","color":PAL["bad"],"fontWeight":"600"},
            ],
            page_size=20,
        ),
        title="n efectivo por muestra"))

    # Descargas del análisis alternativo
    blocks.append(card(
        html.Div(style={"display":"flex","gap":".8rem","flexWrap":"wrap"},children=[
            dl_btn("⬇ experiment_filtered_ALT.csv",  f"/dl/{alt_key}/filtered"),
            dl_btn("⬇ good_coor_ALT.csv",            f"/dl/{alt_key}/good"),
            dl_btn("⬇ bad_coor_ALT.csv",             f"/dl/{alt_key}/bad"),
            dl_btn("⬇ qcr_report_ALT.csv",           f"/dl/{alt_key}/qcr"),
            dl_btn("⬇ experiment_aggregated_ALT.csv",f"/dl/{alt_key}/agg"),
            dl_btn("⬇ cv_per_sample_ALT.csv",        f"/dl/{alt_key}/cv"),
            dl_btn("⬇ combined_results_ALT.csv",     f"/dl/{alt_key}/combined"),
            dl_btn("⬇ pass_all_criteria_ALT.csv",    f"/dl/{alt_key}/pass"),
            html.A("📄 Informe PDF — análisis alternativo",
                   href=f"/dl/{alt_key}/pdf?alt=1",
                   target="_blank",
                   style={"background":"#2C2C2A","color":"#fff","padding":"10px 20px",
                          "borderRadius":"8px","textDecoration":"none","fontSize":"12px",
                          "fontFamily":"monospace","letterSpacing":".05em",
                          "fontWeight":"500","marginLeft":"auto"}),
        ]), title="Descargas (análisis alternativo)"))

    return html.Div(blocks)
