"""
core/pdf_report.py
Generates a report with the plots of an Aletheia analysis.
- With reportlab+svglib installed: native downloadable PDF
- Without them: printable HTML (Ctrl+P -> Save as PDF)

All user-visible text is written in English and wrapped in ``t()``; the
Spanish version lives in ``i18n_es_report.py``.  The language is chosen per
request, so nothing language-dependent is evaluated at import time.
"""

import io
import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .i18n import t, get_lang


# ── Palette ───────────────────────────────────────────────────────────────────
PAL = dict(good="#4A9B8F", bad="#C0756A", amber="#E8A838",
           slate="#6A7FA8", nodata="#B0A89A", neutral="#2C2C2A", muted="#888780")
SPAL = ["#4A9B8F","#6A7FA8","#E8A838","#C0756A","#B0A89A","#5DCAA5",
        "#185FA5","#EF9F27","#D85A30","#888780","#1D9E75","#378ADD"]
P = dict(paper_bgcolor="white", plot_bgcolor="#FAFAF8",
         font=dict(family="Helvetica", size=10, color="#2C2C2A"),
         margin=dict(l=50, r=20, t=40, b=40),
         legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0))




def _pxy(extra=None):
    d = dict(**P, xaxis=dict(gridcolor="#EBEBEB"), yaxis=dict(gridcolor="#EBEBEB"))
    if extra:
        d.update(extra)
    return d


# ── Language-dependent helpers (evaluated at call time, never at import) ─────

def _fmt_dt(dt, short=False):
    """Format a timestamp according to the current language.

    EN: 2026-01-31 14:05            ES: 31/01/2026 a las 14:05
    short=True (ES only): 31/01/2026 14:05
    """
    if get_lang() == "es":
        return dt.strftime("%d/%m/%Y %H:%M" if short else "%d/%m/%Y a las %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


def _status_label(status):
    """User-facing label for the internal QCR status codes."""
    return {"ok": t("Valid"), "suspect": t("Suspect"),
            "fail": t("Failed")}.get(status, status)


def _status_items():
    """(status code, colour, label) triplets in display order."""
    return [("ok", PAL["good"], _status_label("ok")),
            ("suspect", PAL["amber"], _status_label("suspect")),
            ("fail", PAL["bad"], _status_label("fail"))]


def _rec_label(rec):
    """Translate the (English) values of the QCR Recommendation column."""
    return {"Exclude replicate": t("Exclude replicate"),
            "Review manually": t("Review manually"),
            "No issues": t("No issues"),
            "High outliers": t("High outliers")}.get(rec, rec)


def _mode_label(mode):
    """Label of the replicate-exclusion mode of the alternative analysis."""
    return {"none": t("None"), "fail": t("Failed only"),
            "fail_suspect": t("Failed + suspect"),
            "manual": t("Manual selection")}.get(mode, mode)


def _reason_map():
    """Labels of the M1 exclusion reason codes."""
    return {"negative_slope": t("Negative slope"), "r2_low": t("Low R²"),
            "only_1_point": t("1 point"), "no_data": t("No signal"),
            "only_2_points": t("2 points"), "r2_na": "R² N/A",
            "non_monotonic_response": t("Non-monotonic")}


def _report_title(alt_meta):
    title = t("Aletheia — Results report")
    if alt_meta:
        title += " · " + t("Alternative analysis")
    return title


# ── Figures ───────────────────────────────────────────────────────────────────

def _figs_m1(m1, N):
    good=m1["good"]; bad=m1["bad"]; nodat=m1["nodat"]; thr=m1["r2_threshold"]
    n_is  = int((good["reason"]=="non_monotonic_response").sum()) if "reason" in good.columns else 0
    n_pos = len(good)-n_is

    # Donut
    lbls=[t("Accepted"),t("Rejected"),t("No data")]; vals=[len(good),len(bad),len(nodat)]
    cols_=[PAL["good"],PAL["bad"],PAL["nodata"]]
    if n_is:
        lbls.insert(1,t("Non-monotonic")); vals.insert(1,n_is); cols_.insert(1,PAL["amber"])
        vals[0]=n_pos
    fig_don=go.Figure(go.Pie(labels=lbls,values=vals,marker_colors=cols_,hole=.6,
                              textinfo="percent",textposition="inside",
                              insidetextorientation="radial",
                              textfont=dict(size=11,color="white"),
                              domain=dict(x=[0.0,0.60], y=[0.0,1.0])))
    fig_don.add_annotation(text=f"<b>{N}</b><br>"+t("total"),x=0.30,y=0.5,
                            xref="paper",yref="paper",
                            showarrow=False,font=dict(size=12))
    fig_don.update_layout(**_pxy({"title":t("M1 · Linearity summary"),"height":320,"width":520,
                                    "margin":dict(l=10,r=20,t=40,b=20),
                                    "showlegend":True,
                                    "legend":dict(orientation="v",x=0.65,y=0.5,
                                                  xanchor="left",yanchor="middle",
                                                  bgcolor="rgba(0,0,0,0)")}))

    # R² histogram
    r2g=good["r2"].dropna().values; r2b=bad["r2"].dropna().values
    fig_his=go.Figure()
    fig_his.add_trace(go.Histogram(x=r2g,name=t("Accepted"),xbins=dict(size=.05),marker_color=PAL["good"],opacity=.8))
    fig_his.add_trace(go.Histogram(x=r2b,name=t("Rejected"),xbins=dict(size=.05),marker_color=PAL["bad"],opacity=.8))
    fig_his.add_vline(x=thr,line_dash="dash",line_color=PAL["neutral"])
    fig_his.update_layout(**P,title=t("M1 · R² distribution"),barmode="overlay",height=320,width=560,
                          xaxis=dict(range=[0,1],gridcolor="#EBEBEB"),yaxis=dict(gridcolor="#EBEBEB"))

    # Reasons
    RMAP=_reason_map()
    rej=m1["lin_df"][~m1["lin_df"]["ok"]]["reason"].map(RMAP).value_counts()
    fig_rej=go.Figure(go.Bar(x=rej.values,y=rej.index,orientation="h",marker_color=PAL["bad"],opacity=.85))
    fig_rej.update_layout(**_pxy({"title":t("M1 · Exclusion reasons"),"height":280,"width":560}))

    return [fig_don, fig_his, fig_rej]


def _figs_qcr(qcr, N):
    df=qcr["qcr_df"]
    samples=sorted(df["Sample"].unique())

    fig_bar=go.Figure()
    for est,col,lbl in _status_items():
        cnts=[len(df[(df["Sample"]==s)&(df["Status"]==est)]) for s in samples]
        fig_bar.add_trace(go.Bar(x=[f"S{s}" for s in samples],y=cnts,name=lbl,marker_color=col,opacity=.85))
    fig_bar.update_layout(**_pxy({"barmode":"stack","title":t("QCR · Replicate status per sample"),"height":300,"width":640}))

    fig_sum=go.Figure()
    for est,col,lbl in _status_items():
        sub=df[df["Status"]==est]
        fig_sum.add_trace(go.Scatter(
            x=[f"S{r.Sample} R{r.Replicate}" for r in sub.itertuples()],
            y=sub["Sum_int"]/1e6,mode="markers",marker=dict(color=col,size=8,opacity=.85),name=lbl))
    fig_sum.update_layout(**_pxy({"title":t("QCR · Sum of intensities per replicate"),
                                   "yaxis_title":t("Sum int. (×10⁶)"),"height":300,"width":640}))
    return [fig_bar, fig_sum]


def _figs_m2(m2, N):
    cv_df=m2["cv_df"]; icc=m2["icc_vec"]; cv_qc=m2["cv_qc"]
    samples=m2["real_samples"]; thr=m2["cv_threshold"]; thr_qc=m2["qc_cv_thresh"]

    fig_box=go.Figure()
    for i,s in enumerate(samples):
        v=cv_df[f"CV_S{s}"].dropna().values; v=v[v<200]
        fig_box.add_trace(go.Box(y=v,name=f"S{s}",marker_color=SPAL[i%len(SPAL)],
                                 line_color=SPAL[i%len(SPAL)],showlegend=False))
    fig_box.add_hline(y=thr,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"{thr}%",annotation_position="top right")
    fig_box.update_layout(**_pxy({"title":t("M2 · %CV per sample"),"height":300,"width":640}))

    cv_med=cv_df["CV_median"].dropna().values
    fig_cvh=go.Figure(go.Histogram(x=cv_med,xbins=dict(size=2),marker_color=PAL["good"],opacity=.85))
    fig_cvh.add_vline(x=thr,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"{thr}%",annotation_position="top right")
    fig_cvh.update_layout(**_pxy({"title":t("M2 · Global median CV"),"height":300,"width":560}))

    cv_qc_c=cv_qc[~np.isnan(cv_qc)&(cv_qc<200)]
    fig_qcc=go.Figure(go.Histogram(x=cv_qc_c,xbins=dict(size=2),marker_color=PAL["amber"],opacity=.85))
    fig_qcc.add_vline(x=thr_qc,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"QC:{thr_qc}%",annotation_position="top right")
    fig_qcc.add_vline(x=thr,line_dash="dot",line_color=PAL["slate"],
                      annotation_text=t("Samples:{thr}%",thr=thr),annotation_position="top left")
    fig_qcc.update_layout(**_pxy({"title":t("M2 · Normalisation QC CV"),"height":300,"width":560}))

    icc_c=icc[~np.isnan(icc)]
    fig_icc=go.Figure()
    fig_icc.add_trace(go.Histogram(x=icc_c[icc_c<.75],xbins=dict(size=.05),
                                   marker_color=PAL["nodata"],name="ICC<0.75",opacity=.85))
    fig_icc.add_trace(go.Histogram(x=icc_c[icc_c>=.75],xbins=dict(size=.05),
                                   marker_color=PAL["good"],name="ICC≥0.75",opacity=.85))
    fig_icc.add_vline(x=.75,line_dash="dash",line_color=PAL["neutral"])
    fig_icc.update_layout(**_pxy({"title":"M2 · ICC","barmode":"overlay","height":300,"width":560}))

    return [fig_box, fig_cvh, fig_qcc, fig_icc]


def _figs_jt(m1, m2, N):
    cv_med=m2["cv_df"]["CV_median"].values; icc=m2["icc_vec"]
    r2=m1["lin_df"]["r2"].fillna(0).values; lin_ok=m1["lin_df"]["ok"].values
    cv_ok=m2["cv_df"]["CV_ok"].values; thr_cv=m2["cv_threshold"]; thr_r2=m1["r2_threshold"]
    n_lin=int(lin_ok.sum()); n_cv=int(cv_ok.sum())
    n_both=int((lin_ok&cv_ok).sum()); n_lin_only=n_lin-n_both; n_cv_only=n_cv-n_both
    n_neither=N-n_lin-n_cv+n_both

    fig_rv=go.Figure(go.Scatter(x=r2,y=np.minimum(cv_med,100),mode="markers",
        marker=dict(color=[PAL["good"] if o else PAL["bad"] for o in lin_ok],size=3,opacity=.3),
        hovertemplate="R²=%{x:.3f}<br>CV=%{y:.1f}%<extra></extra>"))
    fig_rv.add_hline(y=thr_cv,line_dash="dash",line_color=PAL["bad"],annotation_text=f"CV {thr_cv}%")
    fig_rv.add_vline(x=thr_r2,line_dash="dash",line_color=PAL["bad"],annotation_text=f"R² {thr_r2}")
    fig_rv.update_layout(**P,title=t("Joint · R² vs median %CV"),height=320,width=560,
                          xaxis=dict(title="R²",gridcolor="#EBEBEB"),
                          yaxis=dict(title="%CV (cap 100%)",gridcolor="#EBEBEB"))

    # Venn
    fig_venn=go.Figure()
    fig_venn.add_shape(type="circle",x0=0.10,y0=0.05,x1=0.70,y1=0.95,
                       fillcolor=PAL["good"],opacity=0.25,line=dict(color=PAL["good"],width=2))
    fig_venn.add_shape(type="circle",x0=0.35,y0=0.05,x1=0.95,y1=0.95,
                       fillcolor=PAL["slate"],opacity=0.25,line=dict(color=PAL["slate"],width=2))
    fig_venn.add_annotation(x=0.25,y=0.5,text=f"<b>{n_lin_only}</b><br>"+t("Linearity<br>only"),
                            showarrow=False,font=dict(size=11,color=PAL["good"]))
    fig_venn.add_annotation(x=0.525,y=0.5,text=f"<b>{n_both}</b><br>"+t("Both"),
                            showarrow=False,font=dict(size=12,color=PAL["neutral"]))
    fig_venn.add_annotation(x=0.80,y=0.5,text=f"<b>{n_cv_only}</b><br>"+t("CV<br>only"),
                            showarrow=False,font=dict(size=11,color=PAL["slate"]))
    fig_venn.add_annotation(x=0.5,y=0.04,text=t("Neither: {n_neither}  ·  Total: {N}",n_neither=n_neither,N=N),
                            showarrow=False,font=dict(size=9,color=PAL["muted"]),xref="paper",yref="paper")
    fig_venn.update_layout(paper_bgcolor="white",plot_bgcolor="white",
                           title=t("Joint · Venn — Linearity vs CV"),height=300,width=480,
                           margin=dict(l=10,r=10,t=40,b=20),
                           xaxis=dict(visible=False,range=[0,1]),
                           yaxis=dict(visible=False,range=[0,1]),showlegend=False)

    return [fig_rv, fig_venn]


# ── Main builder ──────────────────────────────────────────────────────────────

def build_pdf(data: dict, filename: str) -> bytes:
    """
    Build the PDF with reportlab. Raises ImportError if reportlab is not installed.
    data: dict with m1, qcr, m2, N, modo, parsed
    """
    # Imports inside the function — the module loads even without reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, KeepTogether, Image
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    try:
        from svglib.svglib import svg2rlg
        HAS_SVGLIB = True
    except ImportError:
        HAS_SVGLIB = False

    def _fig_to_image(fig, width_cm=17, height_cm=8):
        fig.update_layout(width=int(width_cm*37.8), height=int(height_cm*37.8))
        svg_str = fig.to_image(format="svg").decode("utf-8")
        if HAS_SVGLIB:
            drawing = svg2rlg(io.StringIO(svg_str))
            if drawing:
                scale = (width_cm * cm) / drawing.width
                drawing.width  *= scale
                drawing.height *= scale
                drawing.transform = (scale, 0, 0, scale, 0, 0)
                return drawing
        return None

    def t_pdf(*a, **k):
        # Helvetica (reportlab's built-in font) has no ⚠ glyph.
        return t(*a, **k).replace("⚠", "(!)")

    m1=data["m1"]; qcr=data["qcr"]; m2=data["m2"]; N=data["N"]; modo=data["modo"]
    alt_meta = data.get("alt_meta")  # None in the original analysis
    buf = io.BytesIO()

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2.5*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"],
                         fontSize=16, textColor=colors.HexColor("#2C2C2A"),
                         spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                         fontSize=12, textColor=colors.HexColor("#4A9B8F"),
                         spaceBefore=14, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"],
                         fontSize=10, textColor=colors.HexColor("#6A7FA8"),
                         spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("body", parent=styles["Normal"],
                           fontSize=9, textColor=colors.HexColor("#2C2C2A"),
                           leading=13)
    note = ParagraphStyle("note", parent=styles["Normal"],
                           fontSize=8, textColor=colors.HexColor("#888780"),
                           leading=11, italics=True)
    center = ParagraphStyle("center", parent=body, alignment=TA_CENTER)

    story = []
    W = 17*cm  # usable width

    # ── Cover ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*cm))
    story.append(Paragraph(_report_title(alt_meta), h1))
    story.append(Paragraph(
        t("ECAI Mass Spectrometry and Molecular Imaging · IMIBIC · Córdoba"), body))
    story.append(Paragraph(
        t("Generated on {date}", date=_fmt_dt(datetime.datetime.now())), note))
    if alt_meta:
        mode_lbl = _mode_label(alt_meta["mode"])
        story.append(Paragraph(
            t("<b>Exclusion mode applied:</b> {mode} "
              "·  <b>{n}</b> replicate(s) discarded",
              mode=mode_lbl, n=alt_meta["n_excluded"]),
            ParagraphStyle("altcover", parent=body,
                            textColor=colors.HexColor("#6A7FA8"),
                            fontSize=10, spaceAfter=4)))
    story.append(Spacer(1, 0.4*cm))

    # Cover summary table
    n_good = len(m1["good"])
    n_bad  = len(m1["bad"])
    n_is   = int((m1["good"]["reason"]=="non_monotonic_response").sum()) if "reason" in m1["good"].columns else 0
    summary_data = [
        [t("Parameter"), t("Value")],
        [t("Total features"), str(N)],
        [t("Linearity accepted"), f"{n_good} ({100*n_good/(N or 1):.1f}%)"],
        [t("Rejected"), f"{n_bad} ({100*n_bad/(N or 1):.1f}%)"],
        [t("Non-monotonic"), f"{n_is}" if n_is else "—"],
        [t("Valid / total replicates"), f"{qcr['n_ok']} / {qcr['n_ok']+qcr['n_suspect']+qcr['n_fail']}"],
        [t("Injection failures"), str(qcr["n_fail"])],
    ]
    if m2:
        n_cv_ok = int(m2["cv_df"]["CV_ok"].sum())
        n_icc   = int(np.sum(m2["icc_vec"] > .75))
        n_both  = int((m1["lin_df"]["ok"].values & m2["cv_df"]["CV_ok"].values).sum())
        summary_data += [
            [f"CV ≤ {m2['cv_threshold']}%", f"{n_cv_ok} ({100*n_cv_ok/(N or 1):.1f}%)"],
            ["ICC > 0.75", f"{n_icc} ({100*n_icc/(N or 1):.1f}%)"],
            [t("Pass both criteria"), f"{n_both} ({100*n_both/(N or 1):.1f}%)"],
        ]

    tbl = Table(summary_data, colWidths=[9*cm, 8*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#2C2C2A")),
        ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
        ("FONTSIZE",    (0,0), (-1,-1), 9),
        ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1),
         [colors.HexColor("#F7F6F2"), colors.white]),
        ("GRID",        (0,0), (-1,-1), 0.3, colors.HexColor("#E4E2DC")),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING",(0,0), (-1,-1), 8),
        ("TOPPADDING",  (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
    ]))
    story.append(tbl)
    story.append(PageBreak())

    # ── Alternative analysis (only if applicable) ───────────────────────────
    if alt_meta:
        story.append(Paragraph(t("Alternative analysis — replicate exclusion"), h2))
        mode_lbl = _mode_label(alt_meta["mode"])
        story.append(Paragraph(
            t("This report corresponds to an <b>alternative</b> analysis in "
              "which injection replicates considered problematic by the QCR "
              "module have been discarded. The full pipeline is re-run "
              "(linearity + CV/ICC + MetaboAnalyst aggregation) "
              "using only the valid replicates."), body))
        story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph(t("Methodological justification"), h3))
        story.append(Paragraph(_justification_text(), body))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph(
            t("<b>Exclusion mode applied:</b> {mode}", mode=mode_lbl), body))
        story.append(Paragraph(
            t("<b>Total replicates discarded:</b> {n}", n=alt_meta['n_excluded']),
            body))

        # Full list with the original column names
        if alt_meta["n_excluded"]:
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(t("Excluded replicates (full column name):"), h3))
            excl_data = [[t("Sample"), t("Replicate"), t("Status"), t("Original column name")]]
            # alt_meta["excluded_cols"] is only the list of column names; the
            # Sample/Replicate/Status of each one come from the rows of the
            # original analysis, which are serialised in
            # data["alt_excluded_rows"] when available. Otherwise we fall back
            # to the plain list of names.
            excl_rows = data.get("alt_excluded_rows")
            if excl_rows is not None and len(excl_rows):
                for _, r in excl_rows.iterrows():
                    excl_data.append([
                        f"S{r['Sample']}", f"R{int(r['Replicate'])}",
                        _status_label(r["Status"]), r["Column"]
                    ])
            else:
                for col_name in alt_meta["excluded_cols"]:
                    excl_data.append(["—", "—", "—", col_name])
            tbl_excl = Table(excl_data, colWidths=[1.8*cm, 1.5*cm, 2.2*cm, 11.5*cm])
            tbl_excl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2C2C2A")),
                ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
                ("FONTSIZE",   (0,0), (-1,-1), 8),
                ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),
                 [colors.HexColor("#fff0f0"), colors.HexColor("#fffbec")]),
                ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E4E2DC")),
                ("LEFTPADDING",(0,0), (-1,-1), 4),
                ("TOPPADDING", (0,0), (-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
            ]))
            story.append(tbl_excl)

        # Warning: samples left without replicates
        if alt_meta.get("samples_dropped"):
            story.append(Spacer(1, 0.3*cm))
            dropped = ", ".join(f"S{s}" for s in alt_meta["samples_dropped"])
            story.append(Paragraph(
                t_pdf("⚠ <b>Samples without valid replicates after exclusion:</b> "
                  "{dropped}. These samples are excluded from the calculation of "
                  "CV and from the aggregation for statistical analysis.",
                  dropped=dropped),
                ParagraphStyle("warn", parent=body,
                                textColor=colors.HexColor("#C0756A"))))

        # Effective n per sample
        n_eff = data.get("alt_n_eff")
        if n_eff is not None and len(n_eff):
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph(t("Effective n per sample after exclusion"), h3))
            n_data = [[t("Sample"), t("n valid replicates")]]
            for _, r in n_eff.iterrows():
                n_data.append([f"S{r['Sample']}", str(int(r['n_valid_reps']))])
            tbl_n = Table(n_data, colWidths=[4*cm, 4*cm])
            tbl_n.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2C2C2A")),
                ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
                ("FONTSIZE",   (0,0), (-1,-1), 9),
                ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
                ("ALIGN",      (0,0), (-1,-1), "CENTER"),
                ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E4E2DC")),
                ("TOPPADDING", (0,0), (-1,-1), 3),
                ("BOTTOMPADDING",(0,0),(-1,-1), 3),
            ]))
            story.append(tbl_n)

        story.append(PageBreak())

    def add_section(title, figs, descriptions):
        story.append(Paragraph(title, h2))
        for fig, desc in zip(figs, descriptions):
            if desc:
                story.append(Paragraph(desc, note))
            img = _fig_to_image(fig, width_cm=16, height_cm=7.5)
            if img:
                story.append(KeepTogether([img, Spacer(1, 0.3*cm)]))
            else:
                story.append(Paragraph(
                    t("[Figure not available — install svglib: pip install svglib]"),
                    note))
                story.append(Spacer(1, 0.3*cm))

    # ── M1 ───────────────────────────────────────────────────────────────────
    story.append(Paragraph(t("Module 1 · QC dilution linearity"), h2))
    story.append(Paragraph(
        t("R² threshold = {thr}. "
          "4 replicate-aggregation strategies are evaluated "
          "for each dilution level, choosing the one with the highest R² and a positive slope.",
          thr=m1['r2_threshold']),
        body))
    story.append(Spacer(1, 0.2*cm))

    for fig, desc in zip(_figs_m1(m1, N), [
        t("Distribution of features by linearity filter result."),
        t("Distribution of the R² coefficient for accepted and rejected features. "
          "Dashed line: R² threshold = {thr}.", thr=m1['r2_threshold']),
        t("Frequency of each exclusion reason.")
    ]):
        img = _fig_to_image(fig, width_cm=16, height_cm=7)
        story.append(Paragraph(desc, note))
        if img:
            story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
        else:
            story.append(Paragraph(t("[Figure not available]"), note))
            story.append(Spacer(1, 0.3*cm))

    story.append(PageBreak())

    # ── QCR ──────────────────────────────────────────────────────────────────
    story.append(Paragraph(t("QCR · Injection replicate diagnostics"), h2))
    story.append(Paragraph(
        t("Level 1: global diagnosis by sum of intensities and median of intensities "
          "(threshold: 70% of the median of the replicates). "
          "Level 2: per-feature outlier detection (|Z| > 2) in valid replicates."),
        body))

    qcr_df = qcr["qcr_df"]
    if qcr["n_fail"] > 0:
        failed = qcr_df[qcr_df["Status"]=="fail"]
        names = ", ".join(f"S{r.Sample}-R{r.Replicate}" for r in failed.itertuples())
        story.append(Paragraph(
            t_pdf("⚠ Replicates with confirmed failure: {names}", names=names),
            ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#C0756A"))))
    story.append(Spacer(1, 0.2*cm))

    for fig, desc in zip(_figs_qcr(qcr, N), [
        t("Status of each replicate per sample (valid / suspect / confirmed failure)."),
        t("Total sum of intensities per replicate, coloured by injection status.")
    ]):
        img = _fig_to_image(fig, width_cm=16, height_cm=7)
        story.append(Paragraph(desc, note))
        if img:
            story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
        else:
            story.append(Paragraph(t("[Figure not available]"), note))
            story.append(Spacer(1, 0.3*cm))

    # QCR table
    story.append(Paragraph(t("Detail per replicate"), h3))
    cols_qcr = ["Sample","Replicate","Sum_int","Median_int","Status","N_outliers","Recommendation"]
    tbl_data = [[t("Sample"),t("Replicate"),t("Sum int."),t("Med. int."),t("Status"),t("Outliers"),t("Recommendation")]]
    status_raw = []   # internal status codes, used for the row colours
    for _, row in qcr_df[cols_qcr].iterrows():
        status_raw.append(row["Status"])
        tbl_data.append([
            f"S{row['Sample']}", f"R{int(row['Replicate'])}",
            f"{row['Sum_int']/1e6:.2f}M", f"{row['Median_int']:.0f}",
            _status_label(row["Status"]), str(int(row["N_outliers"])),
            _rec_label(row["Recommendation"])
        ])
    tbl_qcr = Table(tbl_data, colWidths=[1.8*cm,1.5*cm,2.2*cm,2.2*cm,2.2*cm,1.8*cm,5.3*cm])
    cond_style = [
        ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#2C2C2A")),
        ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID",        (0,0), (-1,-1), 0.3, colors.HexColor("#E4E2DC")),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING",  (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
    ]
    for i, st in enumerate(status_raw, 1):
        if st == "fail":
            cond_style.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#fff0f0")))
        elif st == "suspect":
            cond_style.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#fffbec")))
        else:
            bg = colors.HexColor("#F7F6F2") if i%2==0 else colors.white
            cond_style.append(("BACKGROUND",(0,i),(-1,i),bg))
    tbl_qcr.setStyle(TableStyle(cond_style))
    story.append(tbl_qcr)

    if m2:
        story.append(PageBreak())
        # ── M2 ───────────────────────────────────────────────────────────────
        story.append(Paragraph(t("Module 2 · Repeatability and Reproducibility"), h2))
        story.append(Paragraph(
            t("Sample %CV threshold = {cv}%. "
              "Normalisation QC %CV threshold = {qc}%. "
              "ICC computed by one-way ANOVA (consistency threshold ICC > 0.75).",
              cv=m2['cv_threshold'], qc=m2['qc_cv_thresh']),
            body))
        story.append(Spacer(1, 0.2*cm))

        for fig, desc in zip(_figs_m2(m2, N), [
            t("Distribution of %CV per sample. Red line: threshold {cv}%.", cv=m2['cv_threshold']),
            t("Histogram of the global median %CV."),
            t("CV of the normalisation QCs. Reference lines: QC threshold and sample threshold."),
            t("Distribution of ICC for all features.")
        ]):
            img = _fig_to_image(fig, width_cm=16, height_cm=7)
            story.append(Paragraph(desc, note))
            if img:
                story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
            else:
                story.append(Paragraph(t("[Figure not available]"), note))
                story.append(Spacer(1, 0.3*cm))

        story.append(PageBreak())
        # ── Joint analysis ───────────────────────────────────────────────────
        story.append(Paragraph(t("Joint analysis · Linearity + CV"), h2))
        lin_ok = m1["lin_df"]["ok"].values; cv_ok = m2["cv_df"]["CV_ok"].values
        n_both_ = int((lin_ok & cv_ok).sum())
        story.append(Paragraph(
            t("Features passing both criteria (linearity R²≥{r2} "
              "and CV≤{cv}%): {n} ({pct}%).",
              r2=m1['r2_threshold'], cv=m2['cv_threshold'], n=n_both_,
              pct=f"{100*n_both_/(N or 1):.1f}"),
            body))
        story.append(Spacer(1, 0.2*cm))

        for fig, desc in zip(_figs_jt(m1, m2, N), [
            t("Scatter of R² vs median %CV. Each point is a feature; green = passes linearity."),
            t("Venn diagram: features passing each criterion individually and both.")
        ]):
            img = _fig_to_image(fig, width_cm=16, height_cm=7)
            story.append(Paragraph(desc, note))
            if img:
                story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
            else:
                story.append(Paragraph(t("[Figure not available]"), note))
                story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    return buf.getvalue()


def _justification_text():
    """Methodological justification of the replicate exclusion (rich text).

    Shared by the PDF and the HTML builders.  It cites mQACC, MSI and the
    Lipidomics Standards Initiative and explains why no mean imputation is done.
    """
    return t(
        "When a technical replicate shows an injection failure (sum or "
        "median of intensities &lt; 70% of the median of the replicates "
        "of the same sample), standard practice in quantitative metabolomics "
        "and lipidomics (<i>mQACC</i>, <i>MSI</i>, "
        "<i>Lipidomics Standards Initiative</i>) recommends excluding it from "
        "the calculation of intra-sample precision. "
        "<b>No imputation with the mean of the remaining replicates is "
        "performed</b>: replacing a failed replicate by the mean of the "
        "rest artificially reduces the standard deviation and the "
        "coefficient of variation (factor ≈ √(2/3) ≈ 0.82 for the SD and "
        "~18% lower CV) without any physical basis. "
        "Instead, each sample keeps its real <i>effective n</i> "
        "after the exclusion, and the intra-sample CV is computed only "
        "when ≥2 valid replicates remain.")


# =============================================================================
# FALLBACK: printable HTML (requires neither reportlab nor svglib)
# The browser opens it and the user uses Ctrl+P -> Save as PDF
# =============================================================================

def build_print_html(data: dict) -> str:
    """Build an HTML report with inline interactive Plotly figures.
    Requires neither kaleido nor any extra dependency.
    The user uses Ctrl+P -> Save as PDF."""
    m1=data["m1"]; qcr=data["qcr"]; m2=data["m2"]; N=data["N"]
    alt_meta = data.get("alt_meta")

    # Common visual configuration for the report
    REPORT_LAYOUT = dict(
        paper_bgcolor="white", plot_bgcolor="#FAFAF8",
        font=dict(family="Arial, sans-serif", size=11, color="#2C2C2A"),
        margin=dict(l=50, r=20, t=40, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
        height=300,
    )

    def _merge_layout(fig, base):
        """Apply `base` layout only for keys the figure hasn't already set."""
        # `margin` can have individual l/r/t/b set — merge per-side.
        overrides = dict(base)
        cur_margin = fig.layout.margin
        has_explicit_margin = any(
            getattr(cur_margin, side) is not None
            for side in ("l", "r", "t", "b")
        )
        if has_explicit_margin:
            overrides.pop("margin", None)
        fig.update_layout(**overrides)

    def fb(fig, caption=""):
        """Full-width figure — the JS comes from the <head> via /plotly.js."""
        _merge_layout(fig, REPORT_LAYOUT)
        h = fig.to_html(full_html=False, include_plotlyjs=False,
                        config={"displayModeBar": False, "responsive": True},
                        div_id=f"fig_{id(fig)}")
        cap = f'<p class="caption">{caption}</p>' if caption else ""
        return f'<div class="fig-block">{h}{cap}</div>'

    def fh(fig, caption=""):
        """Half-width figure."""
        _merge_layout(fig, {**REPORT_LAYOUT, "height": 280})
        h = fig.to_html(full_html=False, include_plotlyjs=False,
                        config={"displayModeBar": False, "responsive": True},
                        div_id=f"fig_{id(fig)}")
        cap = f'<p class="caption">{caption}</p>' if caption else ""
        return f'<div class="fig-half">{h}{cap}</div>'

    def two_cols(f1, f2):
        return f'<div class="fig-row">{f1}{f2}</div>'

    def section(title, content):
        return f'<div class="section"><h2>{title}</h2>{content}</div>'

    def stat_card(n, label, sub, cls):
        return (f'<div class="stat-card {cls}">'
                f'<span class="big">{n}</span>'
                f'<br><span class="slbl">{label}</span>'
                f'{"<br><small>"+sub+"</small>" if sub else ""}'
                f'</div>')

    def stat_row(*cards):
        return f'<div class="stat-row">{"".join(cards)}</div>'

    # Translated texts used in several places
    T_SAMPLE = t("Sample")
    T_REPLICATE = t("Replicate")
    T_N_FEATURES = t("n features")

    # ═══════════════════════════════════════════════
    # M1 — Linearity
    # ═══════════════════════════════════════════════
    good=m1["good"]; bad=m1["bad"]; nodat=m1["nodat"]; thr=m1["r2_threshold"]
    n_is  = int((good["reason"]=="non_monotonic_response").sum()) if "reason" in good.columns else 0
    n_pos = len(good) - n_is

    lbls=[t("Accepted"),t("Rejected"),t("No data")]; vals=[len(good),len(bad),len(nodat)]
    cols_=[PAL["good"],PAL["bad"],PAL["nodata"]]
    if n_is:
        lbls.insert(1,t("Non-monotonic")); vals.insert(1,n_is)
        cols_.insert(1,PAL["amber"]); vals[0]=n_pos

    fig_don = go.Figure(go.Pie(
        labels=lbls, values=vals, marker_colors=cols_,
        hole=.60, textinfo="percent",
        textposition="inside", insidetextorientation="radial",
        textfont=dict(size=11, color="white"),
        # Reserve left 60% of the plotting area for the donut,
        # leaving the right 40% for a vertical legend — this keeps
        # both parts fully visible when exporting to PDF (no clipping
        # on print, no tiny circle on narrow prints).
        domain=dict(x=[0.0, 0.60], y=[0.0, 1.0]),
        hovertemplate="%{label}: %{value}<extra></extra>"))
    fig_don.add_annotation(
        text=f"<b>{N}</b><br>"+t("total"), x=0.30, y=0.5,
        xref="paper", yref="paper",
        showarrow=False, font=dict(size=14))
    fig_don.update_layout(
        title=t("Linearity filter summary"),
        showlegend=True,
        legend=dict(orientation="v", x=0.65, y=0.5,
                    xanchor="left", yanchor="middle",
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=20, t=40, b=20))

    r2g=good["r2"].dropna().values; r2b=bad["r2"].dropna().values
    fig_his = go.Figure()
    fig_his.add_trace(go.Histogram(x=r2g, name=t("Accepted"),   xbins=dict(size=.05),
                                   marker_color=PAL["good"], opacity=.82))
    fig_his.add_trace(go.Histogram(x=r2b, name=t("Rejected"),  xbins=dict(size=.05),
                                   marker_color=PAL["bad"],  opacity=.82))
    fig_his.add_vline(x=thr, line_dash="dash", line_color="#444",
                      annotation_text=f"R² = {thr}", annotation_position="top right")
    fig_his.update_layout(title=t("R² distribution"), barmode="overlay",
                          xaxis=dict(range=[0,1], title="R²"),
                          yaxis=dict(title=T_N_FEATURES))

    RMAP=_reason_map()
    rej = m1["lin_df"][~m1["lin_df"]["ok"]]["reason"].map(RMAP).value_counts()
    fig_rej = go.Figure(go.Bar(x=rej.values, y=rej.index, orientation="h",
                               marker_color=PAL["bad"], opacity=.85,
                               hovertemplate="%{y}: %{x}<extra></extra>"))
    fig_rej.update_layout(title=t("Reasons for exclusion"), xaxis_title=T_N_FEATURES)

    m1_stats = stat_row(
        stat_card(n_pos,    t("Accepted"),   f"{100*n_pos/(N or 1):.1f}% · {n_pos}/{N}",    "green"),
        stat_card(len(bad), t("Rejected"),   f"{100*len(bad)/(N or 1):.1f}% · {len(bad)}/{N}", "red"),
        stat_card(len(nodat),t("No data"),   f"{100*len(nodat)/(N or 1):.1f}%",              "gray"),
        *([ stat_card(n_is, t("Non-monotonic"), f"{100*n_is/(N or 1):.1f}%", "amber")] if n_is else [])
    )
    m1_html = (m1_stats
               + two_cols(fh(fig_don,t("Summary")), fh(fig_his,t("R² distribution")))
               + fb(fig_rej, t("Frequency of each exclusion reason.")))

    # ═══════════════════════════════════════════════
    # QCR — Replicate diagnostics
    # ═══════════════════════════════════════════════
    df=qcr["qcr_df"]; samples=sorted(df["Sample"].unique())

    fig_bar = go.Figure()
    for est, col, lbl in _status_items():
        cnts = [len(df[(df["Sample"]==s)&(df["Status"]==est)]) for s in samples]
        fig_bar.add_trace(go.Bar(x=[f"S{s}" for s in samples], y=cnts,
                                 name=lbl, marker_color=col, opacity=.85))
    fig_bar.update_layout(title=t("Replicate status per sample"), barmode="stack",
                          xaxis_title=T_SAMPLE, yaxis_title=t("n replicates"))

    fig_sum = go.Figure()
    for est, col, lbl in _status_items():
        sub = df[df["Status"]==est]
        fig_sum.add_trace(go.Scatter(
            x=[f"S{r.Sample} R{r.Replicate}" for r in sub.itertuples()],
            y=sub["Sum_int"]/1e6, mode="markers",
            marker=dict(color=col, size=9, opacity=.85), name=lbl,
            hovertemplate="<b>%{x}</b><br>%{y:.2f}M<extra></extra>"))
    fig_sum.update_layout(title=t("Sum of intensities per replicate"),
                          yaxis_title=t("Sum int. (×10⁶)"))

    n_total_r = qcr["n_ok"]+qcr["n_suspect"]+qcr["n_fail"]
    qcr_stats = stat_row(
        stat_card(qcr["n_ok"],      t("Valid replicates"),
                  f"{100*qcr['n_ok']/(n_total_r or 1):.1f}% · {qcr['n_ok']}/{n_total_r}", "green"),
        stat_card(qcr["n_suspect"], t("Suspect replicates"), t("1 criterion"), "amber"),
        stat_card(qcr["n_fail"],    t("Failed replicates"),  t("both criteria"), "red"),
        stat_card(qcr["n_outlier_total"], t("Feature outliers"), t("in valid replicates"), "slate"),
    )
    qcr_html = (qcr_stats
                + two_cols(fh(fig_bar, t("Status per sample")),
                           fh(fig_sum, t("Sum of intensities"))))

    # ═══════════════════════════════════════════════
    # M2 — CV / ICC
    # ═══════════════════════════════════════════════
    m2_html = ""
    if m2:
        cv_df_=m2["cv_df"]; icc=m2["icc_vec"]; cv_qc=m2["cv_qc"]
        samples_=m2["real_samples"]; thr_cv=m2["cv_threshold"]; thr_qc=m2["qc_cv_thresh"]
        n_ok_cv=int(cv_df_["CV_ok"].sum()); n_ok_icc=int(np.sum(icc>.75)); n_bad_cv=N-n_ok_cv

        fig_box = go.Figure()
        for i, s in enumerate(samples_):
            v = cv_df_[f"CV_S{s}"].dropna().values; v = v[v<200]
            fig_box.add_trace(go.Box(y=v, name=f"S{s}",
                marker_color=SPAL[i%len(SPAL)], line_color=SPAL[i%len(SPAL)], showlegend=False))
        fig_box.add_hline(y=thr_cv, line_dash="dash", line_color=PAL["bad"],
                          annotation_text=f"{thr_cv}%", annotation_position="top right")
        fig_box.update_layout(title=t("%CV per sample"), yaxis_title="%CV")

        cv_med = cv_df_["CV_median"].dropna().values
        fig_cvh = go.Figure(go.Histogram(x=cv_med, xbins=dict(size=2),
                                         marker_color=PAL["good"], opacity=.85))
        fig_cvh.add_vline(x=thr_cv, line_dash="dash", line_color=PAL["bad"],
                          annotation_text=f"{thr_cv}%", annotation_position="top right")
        fig_cvh.update_layout(title=t("Global median CV"),
                               xaxis_title=t("Median %CV"), yaxis_title=T_N_FEATURES)

        cv_qc_c = cv_qc[~np.isnan(cv_qc)&(cv_qc<200)]
        fig_qcc = go.Figure(go.Histogram(x=cv_qc_c, xbins=dict(size=2),
                                         marker_color=PAL["amber"], opacity=.85))
        fig_qcc.add_vline(x=thr_qc, line_dash="dash", line_color=PAL["bad"],
                          annotation_text=f"QC: {thr_qc}%", annotation_position="top right")
        fig_qcc.add_vline(x=thr_cv, line_dash="dot", line_color=PAL["slate"],
                          annotation_text=t("Samples: {thr}%", thr=thr_cv), annotation_position="top left")
        fig_qcc.update_layout(title=t("Normalisation QC CV"),
                               xaxis_title="%CV", yaxis_title=T_N_FEATURES)

        icc_c = icc[~np.isnan(icc)]
        fig_icc = go.Figure()
        fig_icc.add_trace(go.Histogram(x=icc_c[icc_c<.75], xbins=dict(size=.05),
                                       marker_color=PAL["nodata"], name="ICC<0.75", opacity=.85))
        fig_icc.add_trace(go.Histogram(x=icc_c[icc_c>=.75], xbins=dict(size=.05),
                                       marker_color=PAL["good"], name="ICC≥0.75", opacity=.85))
        fig_icc.add_vline(x=.75, line_dash="dash", line_color="#444")
        fig_icc.update_layout(title="ICC", barmode="overlay",
                               xaxis_title="ICC", yaxis_title=T_N_FEATURES)

        m2_stats = stat_row(
            stat_card(n_ok_cv,  f"CV ≤ {thr_cv}%", f"{100*n_ok_cv/(N or 1):.1f}% · {n_ok_cv}/{N}",  "green"),
            stat_card(n_bad_cv, f"CV > {thr_cv}%",  f"{100*n_bad_cv/(N or 1):.1f}% · {n_bad_cv}/{N}", "red"),
            stat_card(n_ok_icc, "ICC > 0.75",        f"{100*n_ok_icc/(N or 1):.1f}% · {n_ok_icc}/{N}", "slate"),
        )
        m2_html = (m2_stats
                   + two_cols(fh(fig_box, t("%CV per sample")),
                               fh(fig_cvh, t("Global median CV")))
                   + two_cols(fh(fig_qcc, t("Normalisation QC CV")),
                               fh(fig_icc, "ICC")))

    # ═══════════════════════════════════════════════
    # Joint analysis
    # ═══════════════════════════════════════════════
    jt_html = ""
    if m2:
        lin_ok=m1["lin_df"]["ok"].values; cv_ok=m2["cv_df"]["CV_ok"].values
        r2v=m1["lin_df"]["r2"].fillna(0).values; cv_med_=m2["cv_df"]["CV_median"].values
        n_lin=int(lin_ok.sum()); n_cv=int(cv_ok.sum())
        n_both=int((lin_ok&cv_ok).sum()); thr_r2=m1["r2_threshold"]
        n_lin_only=n_lin-n_both; n_cv_only=n_cv-n_both; n_neither=N-n_lin-n_cv+n_both

        fig_rv = go.Figure(go.Scatter(
            x=r2v, y=np.minimum(cv_med_,100), mode="markers",
            marker=dict(color=[PAL["good"] if o else PAL["bad"] for o in lin_ok],
                        size=3, opacity=.3),
            hovertemplate="R²=%{x:.3f}<br>CV=%{y:.1f}%<extra></extra>"))
        fig_rv.add_hline(y=m2["cv_threshold"], line_dash="dash", line_color=PAL["bad"],
                         annotation_text=f"CV {m2['cv_threshold']}%")
        fig_rv.add_vline(x=thr_r2, line_dash="dash", line_color=PAL["bad"],
                         annotation_text=f"R² {thr_r2}")
        fig_rv.update_layout(title=t("R² vs median %CV"),
                              xaxis_title="R²", yaxis_title="%CV (cap 100%)")

        fig_venn = go.Figure()
        fig_venn.add_shape(type="circle", x0=0.08,y0=0.05, x1=0.68,y1=0.95,
                           fillcolor=PAL["good"], opacity=0.25,
                           line=dict(color=PAL["good"], width=2))
        fig_venn.add_shape(type="circle", x0=0.35,y0=0.05, x1=0.95,y1=0.95,
                           fillcolor=PAL["slate"], opacity=0.25,
                           line=dict(color=PAL["slate"], width=2))
        fig_venn.add_annotation(x=0.23,y=0.5, text=f"<b>{n_lin_only}</b><br>"+t("Linearity only"),
                                showarrow=False, font=dict(size=12,color=PAL["good"]))
        fig_venn.add_annotation(x=0.52,y=0.5, text=f"<b>{n_both}</b><br>"+t("Both"),
                                showarrow=False, font=dict(size=14,color="#2C2C2A"))
        fig_venn.add_annotation(x=0.80,y=0.5, text=f"<b>{n_cv_only}</b><br>"+t("CV only"),
                                showarrow=False, font=dict(size=12,color=PAL["slate"]))
        fig_venn.add_annotation(x=0.5, y=0.04,
                                text=t("Neither: {n_neither}  ·  Total: {N}", n_neither=n_neither, N=N),
                                showarrow=False, font=dict(size=9,color=PAL["muted"]),
                                xref="paper", yref="paper")
        fig_venn.update_layout(title=t("Venn diagram · Linearity vs CV"),
                               xaxis=dict(visible=False, range=[0,1]),
                               yaxis=dict(visible=False, range=[0,1]),
                               plot_bgcolor="white", showlegend=False)

        jt_stats = stat_row(
            stat_card(n_both, t("Pass both"),       f"{100*n_both/(N or 1):.1f}% · {n_both}/{N}", "green"),
            stat_card(n_lin,  t("Pass linearity"),  f"{100*n_lin/(N or 1):.1f}%",                 "slate"),
            stat_card(n_cv,   t("Pass CV≤{thr}%", thr=m2['cv_threshold']), f"{100*n_cv/(N or 1):.1f}%",   "amber"),
        )
        jt_html = (jt_stats
                   + two_cols(fh(fig_rv, t("R² vs median %CV")),
                               fh(fig_venn, t("Venn diagram"))))

    # ═══════════════════════════════════════════════
    # Alternative analysis block (only if applicable)
    # ═══════════════════════════════════════════════
    alt_html = ""
    if alt_meta:
        mode_lbl = _mode_label(alt_meta["mode"])
        excl_rows = data.get("alt_excluded_rows")
        excl_table = ""
        excl_head = (f'<th>{T_SAMPLE}</th><th>{T_REPLICATE}</th><th>{t("Status")}</th>'
                     f'<th>{t("Original column name")}</th>')
        if excl_rows is not None and len(excl_rows):
            rows_html = "".join(
                f'<tr><td>S{r["Sample"]}</td>'
                f'<td>R{int(r["Replicate"])}</td>'
                f'<td class="st-{r["Status"]}">{_status_label(r["Status"])}</td>'
                f'<td class="colname">{r["Column"]}</td></tr>'
                for _, r in excl_rows.iterrows()
            )
            excl_table = (
                '<table class="alt-tbl"><thead><tr>'
                + excl_head + '</tr></thead>'
                f'<tbody>{rows_html}</tbody></table>'
            )
        elif alt_meta["n_excluded"]:
            rows_html = "".join(
                f'<tr><td>—</td><td>—</td><td>—</td>'
                f'<td class="colname">{c}</td></tr>'
                for c in alt_meta["excluded_cols"]
            )
            excl_table = (
                '<table class="alt-tbl"><thead><tr>'
                + excl_head + '</tr></thead>'
                f'<tbody>{rows_html}</tbody></table>'
            )

        dropped_html = ""
        if alt_meta.get("samples_dropped"):
            dropped = ", ".join(f"S{s}" for s in alt_meta["samples_dropped"])
            dropped_html = (
                '<p class="alt-warn">'
                + t("⚠ <b>Samples without valid replicates after "
                    "exclusion:</b> {dropped}. These samples are excluded "
                    "from the calculation of CV and from the aggregation.",
                    dropped=dropped)
                + '</p>'
            )

        n_eff = data.get("alt_n_eff")
        n_eff_html = ""
        if n_eff is not None and len(n_eff):
            rows = "".join(
                f'<tr><td>S{r["Sample"]}</td><td>{int(r["n_valid_reps"])}</td></tr>'
                for _, r in n_eff.iterrows()
            )
            n_eff_html = (
                f'<h3 class="alt-h3">{t("Effective n per sample after exclusion")}</h3>'
                '<table class="alt-tbl alt-tbl-small"><thead><tr>'
                f'<th>{T_SAMPLE}</th><th>{t("n valid replicates")}</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
            )

        alt_intro = t("This report corresponds to an <b>alternative</b> analysis in "
                      "which injection replicates considered problematic by the QCR "
                      "module have been discarded. The full pipeline is re-run "
                      "(linearity + CV/ICC + MetaboAnalyst aggregation) "
                      "using only the valid replicates.")
        alt_justif_h = t("Methodological justification")
        alt_justif = _justification_text()
        alt_mode_line = t("<b>Exclusion mode applied:</b> {mode}", mode=mode_lbl)
        alt_total_line = t("<b>Total replicates discarded:</b> {n}", n=alt_meta['n_excluded'])
        excl_head_html = (f'<h3 class="alt-h3">{t("Excluded replicates (full column name)")}</h3>'
                          if excl_table else '')

        alt_html = f"""
        <div class="alt-box">
          <p>{alt_intro}</p>

          <h3 class="alt-h3">{alt_justif_h}</h3>
          <p>{alt_justif}</p>

          <p>{alt_mode_line}<br>
             {alt_total_line}</p>

          {excl_head_html}
          {excl_table}

          {dropped_html}

          {n_eff_html}
        </div>
        """

    # ═══════════════════════════════════════════════
    # Final HTML — Plotly JS served from the local server
    # ═══════════════════════════════════════════════
    now = _fmt_dt(datetime.datetime.now(), short=True)
    lang = get_lang()
    page_title = t("Aletheia report — {now}", now=now)
    report_title = _report_title(alt_meta)
    affiliation = t("ECAI Mass Spectrometry and Molecular Imaging · IMIBIC · Córdoba")
    print_btn = t("🖨️ Save as PDF (Ctrl+P → A4 landscape · no margins)")
    sec_alt = section(t("Alternative analysis — replicate exclusion"), alt_html) if alt_html else ""
    sec_m1 = section(t("Module 1 · QC dilution linearity"), m1_html)
    sec_qcr = section(t("QCR · Injection replicate diagnostics"), qcr_html)
    sec_m2 = section(t("Module 2 · Repeatability and Reproducibility"), m2_html) if m2_html else ""
    sec_jt = section(t("Joint analysis · Linearity + CV"), jt_html) if jt_html else ""
    footer_gen = t("Generated with Aletheia · ECAI IMSMI · IMIBIC · {now}", now=now)
    footer_hint = t("To save as PDF: Ctrl+P → Save as PDF → Landscape · No margins")

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<title>{page_title}</title>
<script src="/plotly.js"></script>
<style>
  @page {{ size: A4 landscape; margin: 1.5cm; }}
  @media print {{
    .no-print {{ display: none !important; }}
    .section {{ page-break-before: always; }}
    .section:first-of-type {{ page-break-before: avoid; }}
    .fig-half .plotly-graph-div {{ height: 250px !important; }}
    .fig-block .plotly-graph-div {{ height: 280px !important; }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; font-size: 11px; color: #2C2C2A;
         background: #f0efeb; padding: 16px; }}
  .page {{ background: white; max-width: 1100px; margin: 0 auto; padding: 28px 32px; }}
  h1 {{ font-size: 20px; color: #2C2C2A; margin-bottom: 4px; font-weight: 600; }}
  h2 {{ font-size: 13px; color: #4A9B8F; border-bottom: 2px solid #4A9B8F;
        padding-bottom: 5px; margin: 24px 0 12px; font-weight: 600;
        text-transform: uppercase; letter-spacing: .05em; }}
  .meta {{ font-size: 10px; color: #888780; margin-bottom: 16px; font-family: monospace; }}
  .stat-row {{ display: flex; gap: 10px; margin: 10px 0 16px; flex-wrap: wrap; }}
  .stat-card {{ flex: 1; min-width: 110px; background: #F7F6F2; border-radius: 8px;
                padding: 10px 12px; border-top: 3px solid #B0A89A;
                color: #888780; line-height: 1.5; }}
  .stat-card.green {{ border-top-color: #4A9B8F; }}
  .stat-card.red   {{ border-top-color: #C0756A; }}
  .stat-card.amber {{ border-top-color: #E8A838; }}
  .stat-card.slate {{ border-top-color: #6A7FA8; }}
  .stat-card.gray  {{ border-top-color: #B0A89A; }}
  .big  {{ font-size: 28px; font-weight: 600; color: #2C2C2A; font-family: monospace;
           display: block; line-height: 1.1; }}
  .slbl {{ font-size: 10px; font-weight: 600; letter-spacing: .05em;
           text-transform: uppercase; color: #888780; }}
  .fig-row  {{ display: flex; gap: 10px; margin: 8px 0; }}
  .fig-half {{ flex: 1; min-width: 0; }}
  .fig-block {{ margin: 8px 0; }}
  .caption {{ font-size: 9px; color: #888780; margin: 2px 0 6px;
              font-style: italic; text-align: center; }}
  .section {{ margin-bottom: 8px; }}
  .print-btn {{ background: #2C2C2A; color: white; border: none; padding: 10px 24px;
                border-radius: 8px; font-size: 12px; cursor: pointer; margin: 0 0 20px;
                font-family: monospace; letter-spacing: .04em; }}
  .print-btn:hover {{ background: #444; }}
  .footer {{ font-size: 9px; color: #B0A89A; margin-top: 24px; padding-top: 12px;
             border-top: 1px solid #E4E2DC; font-family: monospace; }}
  .alt-box {{ background: #F5F4EF; border-left: 3px solid #6A7FA8;
               padding: 10px 14px; margin-top: 4px; border-radius: 0 6px 6px 0;
               font-size: 11px; line-height: 1.5; }}
  .alt-box p {{ margin: 6px 0; }}
  .alt-h3 {{ font-size: 11px; color: #6A7FA8; margin-top: 10px;
              font-weight: 600; letter-spacing: .03em; text-transform: uppercase; }}
  .alt-tbl {{ width: 100%; border-collapse: collapse; margin: 6px 0 8px;
               font-size: 10px; }}
  .alt-tbl th {{ background: #2C2C2A; color: white; padding: 6px 8px;
                   text-align: left; font-weight: 600; }}
  .alt-tbl td {{ padding: 4px 8px; border: 1px solid #E4E2DC; }}
  .alt-tbl td.colname {{ font-family: monospace; font-size: 9.5px;
                          color: #2C2C2A; word-break: break-all; }}
  .alt-tbl td.st-fail    {{ background: #fff0f0; color: #C0756A; font-weight: 600; }}
  .alt-tbl td.st-suspect {{ background: #fffbec; color: #B07C00; font-weight: 600; }}
  .alt-tbl-small {{ max-width: 260px; }}
  .alt-warn {{ background: #fff0f0; color: #C0756A; padding: 8px 12px;
                border-radius: 4px; border-left: 3px solid #C0756A;
                margin: 8px 0; font-size: 11px; }}
</style>
</head>
<body>
<div class="page">
<button class="print-btn no-print" onclick="window.print()">{print_btn}</button>
<h1>{report_title}</h1>
<div class="meta">{affiliation} &nbsp;|&nbsp; {now}</div>

{sec_alt}
{sec_m1}
{sec_qcr}
{sec_m2}
{sec_jt}

<div class="footer">
  {footer_gen}<br>
  {footer_hint}
</div>
</div>
</body>
</html>"""
