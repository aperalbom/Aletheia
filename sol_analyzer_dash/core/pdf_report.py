"""
core/pdf_report.py
Genera un PDF con las gráficas del análisis Aletheia.
- Con reportlab+svglib instalados: PDF nativo descargable
- Sin ellos: HTML imprimible (Ctrl+P → Guardar como PDF)
"""

import io
import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go


# ── Paleta ────────────────────────────────────────────────────────────────────
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


# ── Figuras ───────────────────────────────────────────────────────────────────

def _figs_m1(m1, N):
    good=m1["good"]; bad=m1["bad"]; nodat=m1["nodat"]; thr=m1["r2_threshold"]
    n_is  = int((good["reason"]=="ion_suppression").sum()) if "reason" in good.columns else 0
    n_pos = len(good)-n_is

    # Donut
    lbls=[" Aceptados","Rechazados","Sin datos"]; vals=[len(good),len(bad),len(nodat)]
    cols_=[PAL["good"],PAL["bad"],PAL["nodata"]]
    if n_is:
        lbls.insert(1,"Ion supp."); vals.insert(1,n_is); cols_.insert(1,PAL["amber"])
        vals[0]=n_pos
    fig_don=go.Figure(go.Pie(labels=lbls,values=vals,marker_colors=cols_,hole=.6,
                              textinfo="percent",textposition="inside",
                              insidetextorientation="radial",
                              textfont=dict(size=11,color="white"),
                              domain=dict(x=[0.0,0.60], y=[0.0,1.0])))
    fig_don.add_annotation(text=f"<b>{N}</b><br>total",x=0.30,y=0.5,
                            xref="paper",yref="paper",
                            showarrow=False,font=dict(size=12))
    fig_don.update_layout(**_pxy({"title":"M1 · Resumen linealidad","height":320,"width":520,
                                    "margin":dict(l=10,r=20,t=40,b=20),
                                    "showlegend":True,
                                    "legend":dict(orientation="v",x=0.65,y=0.5,
                                                  xanchor="left",yanchor="middle",
                                                  bgcolor="rgba(0,0,0,0)")}))

    # Histograma R²
    r2g=good["r2"].dropna().values; r2b=bad["r2"].dropna().values
    fig_his=go.Figure()
    fig_his.add_trace(go.Histogram(x=r2g,name="Aceptados",xbins=dict(size=.05),marker_color=PAL["good"],opacity=.8))
    fig_his.add_trace(go.Histogram(x=r2b,name="Rechazados",xbins=dict(size=.05),marker_color=PAL["bad"],opacity=.8))
    fig_his.add_vline(x=thr,line_dash="dash",line_color=PAL["neutral"])
    fig_his.update_layout(**P,title="M1 · Distribución R²",barmode="overlay",height=320,width=560,
                          xaxis=dict(range=[0,1],gridcolor="#EBEBEB"),yaxis=dict(gridcolor="#EBEBEB"))

    # Motivos
    RMAP={"negative_slope":"Pend. negativa","r2_low":"R² bajo","only_1_point":"1 punto",
          "no_data":"Sin señal","only_2_points":"2 puntos","r2_na":"R² N/A","ion_suppression":"Ion supp."}
    rej=m1["lin_df"][~m1["lin_df"]["ok"]]["reason"].map(RMAP).value_counts()
    fig_rej=go.Figure(go.Bar(x=rej.values,y=rej.index,orientation="h",marker_color=PAL["bad"],opacity=.85))
    fig_rej.update_layout(**_pxy({"title":"M1 · Motivos de exclusión","height":280,"width":560}))

    return [fig_don, fig_his, fig_rej]


def _figs_qcr(qcr, N):
    df=qcr["qcr_df"]
    samples=sorted(df["Sample"].unique())

    fig_bar=go.Figure()
    for est,col,lbl in [("ok",PAL["good"],"Válida"),("suspect",PAL["amber"],"Sospechosa"),("fail",PAL["bad"],"Fallo")]:
        cnts=[len(df[(df["Sample"]==s)&(df["Estado"]==est)]) for s in samples]
        fig_bar.add_trace(go.Bar(x=[f"S{s}" for s in samples],y=cnts,name=lbl,marker_color=col,opacity=.85))
    fig_bar.update_layout(**_pxy({"barmode":"stack","title":"QCR · Estado de réplicas por muestra","height":300,"width":640}))

    fig_sum=go.Figure()
    for est,col,lbl in [("ok",PAL["good"],"Válida"),("suspect",PAL["amber"],"Sospechosa"),("fail",PAL["bad"],"Fallo")]:
        sub=df[df["Estado"]==est]
        fig_sum.add_trace(go.Scatter(
            x=[f"S{r.Sample} R{r.Replica}" for r in sub.itertuples()],
            y=sub["Suma_int"]/1e6,mode="markers",marker=dict(color=col,size=8,opacity=.85),name=lbl))
    fig_sum.update_layout(**_pxy({"title":"QCR · Suma de intensidades por réplica",
                                   "yaxis_title":"Suma int. (×10⁶)","height":300,"width":640}))
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
    fig_box.update_layout(**_pxy({"title":"M2 · %CV por muestra","height":300,"width":640}))

    cv_med=cv_df["CV_median"].dropna().values
    fig_cvh=go.Figure(go.Histogram(x=cv_med,xbins=dict(size=2),marker_color=PAL["good"],opacity=.85))
    fig_cvh.add_vline(x=thr,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"{thr}%",annotation_position="top right")
    fig_cvh.update_layout(**_pxy({"title":"M2 · CV mediana global","height":300,"width":560}))

    cv_qc_c=cv_qc[~np.isnan(cv_qc)&(cv_qc<200)]
    fig_qcc=go.Figure(go.Histogram(x=cv_qc_c,xbins=dict(size=2),marker_color=PAL["amber"],opacity=.85))
    fig_qcc.add_vline(x=thr_qc,line_dash="dash",line_color=PAL["bad"],
                      annotation_text=f"QC:{thr_qc}%",annotation_position="top right")
    fig_qcc.add_vline(x=thr,line_dash="dot",line_color=PAL["slate"],
                      annotation_text=f"Muestras:{thr}%",annotation_position="top left")
    fig_qcc.update_layout(**_pxy({"title":"M2 · CV QC normalización","height":300,"width":560}))

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
    fig_rv.update_layout(**P,title="Conjunto · R² vs %CV mediana",height=320,width=560,
                          xaxis=dict(title="R²",gridcolor="#EBEBEB"),
                          yaxis=dict(title="%CV (cap 100%)",gridcolor="#EBEBEB"))

    # Venn
    fig_venn=go.Figure()
    fig_venn.add_shape(type="circle",x0=0.10,y0=0.05,x1=0.70,y1=0.95,
                       fillcolor=PAL["good"],opacity=0.25,line=dict(color=PAL["good"],width=2))
    fig_venn.add_shape(type="circle",x0=0.35,y0=0.05,x1=0.95,y1=0.95,
                       fillcolor=PAL["slate"],opacity=0.25,line=dict(color=PAL["slate"],width=2))
    fig_venn.add_annotation(x=0.25,y=0.5,text=f"<b>{n_lin_only}</b><br>Solo<br>linealidad",
                            showarrow=False,font=dict(size=11,color=PAL["good"]))
    fig_venn.add_annotation(x=0.525,y=0.5,text=f"<b>{n_both}</b><br>Ambos",
                            showarrow=False,font=dict(size=12,color=PAL["neutral"]))
    fig_venn.add_annotation(x=0.80,y=0.5,text=f"<b>{n_cv_only}</b><br>Solo<br>CV",
                            showarrow=False,font=dict(size=11,color=PAL["slate"]))
    fig_venn.add_annotation(x=0.5,y=0.04,text=f"Sin ninguno: {n_neither}  ·  Total: {N}",
                            showarrow=False,font=dict(size=9,color=PAL["muted"]),xref="paper",yref="paper")
    fig_venn.update_layout(paper_bgcolor="white",plot_bgcolor="white",
                           title="Conjunto · Venn — Linealidad vs CV",height=300,width=480,
                           margin=dict(l=10,r=10,t=40,b=20),
                           xaxis=dict(visible=False,range=[0,1]),
                           yaxis=dict(visible=False,range=[0,1]),showlegend=False)

    return [fig_rv, fig_venn]


# ── Builder principal ─────────────────────────────────────────────────────────

def build_pdf(data: dict, filename: str) -> bytes:
    """
    Genera PDF con reportlab. Lanza ImportError si reportlab no está instalado.
    data: dict con m1, qcr, m2, N, modo, parsed
    """
    # Imports dentro de la función — el módulo carga aunque reportlab no esté
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

    m1=data["m1"]; qcr=data["qcr"]; m2=data["m2"]; N=data["N"]; modo=data["modo"]
    alt_meta = data.get("alt_meta")  # None en análisis original
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
    W = 17*cm  # ancho útil

    # ── Portada ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*cm))
    title_txt = "Aletheia — Informe de resultados"
    if alt_meta:
        title_txt += " · Análisis alternativo"
    story.append(Paragraph(title_txt, h1))
    story.append(Paragraph(
        f"ECAI Espectrometría de Masas e Imagen Molecular · IMIBIC · Córdoba", body))
    story.append(Paragraph(
        f"Generado el {datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')}", note))
    if alt_meta:
        mode_lbl = {"none":"Ninguna","fail":"Solo fallidas",
                     "fail_suspect":"Fallidas + sospechosas",
                     "manual":"Selección manual"}.get(alt_meta["mode"], alt_meta["mode"])
        story.append(Paragraph(
            f"<b>Modo de exclusión aplicado:</b> {mode_lbl} "
            f"·  <b>{alt_meta['n_excluded']}</b> réplica(s) descartadas",
            ParagraphStyle("altcover", parent=body,
                            textColor=colors.HexColor("#6A7FA8"),
                            fontSize=10, spaceAfter=4)))
    story.append(Spacer(1, 0.4*cm))

    # Tabla resumen portada
    n_good = len(m1["good"])
    n_bad  = len(m1["bad"])
    n_is   = int((m1["good"]["reason"]=="ion_suppression").sum()) if "reason" in m1["good"].columns else 0
    summary_data = [
        ["Parámetro", "Valor"],
        ["Total metabolitos", str(N)],
        ["Aceptados linealidad", f"{n_good} ({100*n_good/N:.1f}%)"],
        ["Rechazados", f"{n_bad} ({100*n_bad/N:.1f}%)"],
        ["Ion suppression", f"{n_is}" if n_is else "—"],
        ["Réplicas válidas", f"{qcr['n_ok']} / {qcr['n_ok']+qcr['n_suspect']+qcr['n_fail']}"],
        ["Fallos de inyección", str(qcr["n_fail"])],
    ]
    if m2:
        n_cv_ok = int(m2["cv_df"]["CV_ok"].sum())
        n_icc   = int(np.sum(m2["icc_vec"] > .75))
        n_both  = int((m1["lin_df"]["ok"].values & m2["cv_df"]["CV_ok"].values).sum())
        summary_data += [
            [f"CV ≤ {m2['cv_threshold']}%", f"{n_cv_ok} ({100*n_cv_ok/N:.1f}%)"],
            ["ICC > 0.75", f"{n_icc} ({100*n_icc/N:.1f}%)"],
            ["Pasan ambos criterios", f"{n_both} ({100*n_both/N:.1f}%)"],
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

    # ── Análisis alternativo (solo si aplica) ───────────────────────────────
    if alt_meta:
        story.append(Paragraph("Análisis alternativo — exclusión de réplicas", h2))
        mode_lbl = {"none":"Ninguna","fail":"Solo fallidas",
                     "fail_suspect":"Fallidas + sospechosas",
                     "manual":"Selección manual"}.get(alt_meta["mode"], alt_meta["mode"])
        story.append(Paragraph(
            f"Este informe corresponde a un análisis <b>alternativo</b> en el "
            f"que se han descartado réplicas de inyección consideradas "
            f"problemáticas por el módulo QCR. Se re-ejecuta el pipeline "
            f"completo (linealidad + CV/ICC + agregación MetaboAnalyst) "
            f"utilizando únicamente las réplicas válidas.", body))
        story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph("Justificación metodológica", h3))
        story.append(Paragraph(
            "Cuando una réplica técnica presenta fallo de inyección (suma o "
            "mediana de intensidades &lt; 70% de la mediana de las réplicas "
            "de la misma muestra), la práctica estándar en metabolómica y "
            "lipidómica cuantitativa (<i>mQACC</i>, <i>MSI</i>, "
            "<i>Lipidomics Standards Initiative</i>) recomienda excluirla del "
            "cálculo de precisión intra-muestra. "
            "<b>No se realiza imputación con la media de las réplicas "
            "restantes</b>: sustituir una réplica fallida por la media del "
            "resto reduce artificialmente la desviación estándar y el "
            "coeficiente de variación (factor ≈ √(2/3) ≈ 0.82 para la SD y "
            "~18% menos de CV) sin que exista una base física para ello. "
            "En su lugar, cada muestra conserva su <i>n efectivo</i> real "
            "tras la exclusión, y el CV intra-muestra se calcula únicamente "
            "cuando quedan ≥2 réplicas válidas.", body))
        story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph(
            f"<b>Modo de exclusión aplicado:</b> {mode_lbl}", body))
        story.append(Paragraph(
            f"<b>Total de réplicas descartadas:</b> {alt_meta['n_excluded']}",
            body))

        # Lista completa con nombres originales
        if alt_meta["n_excluded"]:
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("Réplicas excluidas (nombre completo de columna):", h3))
            excl_data = [["Muestra", "Réplica", "Estado", "Nombre de columna original"]]
            # alt_meta["excluded_cols"] es la lista de nombres; hay que
            # cruzarla con qcr del análisis original para recuperar Sample/Replica/Estado.
            # En este PDF `qcr` es ya el del análisis alternativo (post-exclusión) —
            # así que reconstruimos desde el cache del padre.
            # Mejor: serializamos todo lo necesario en `alt_meta["excluded_rows"]`
            # cuando está disponible; si no, caemos al listado simple.
            excl_rows = data.get("alt_excluded_rows")
            if excl_rows is not None and len(excl_rows):
                for _, r in excl_rows.iterrows():
                    excl_data.append([
                        f"S{r['Sample']}", f"R{int(r['Replica'])}",
                        r["Estado"], r["Column"]
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

        # Aviso muestras sin réplicas
        if alt_meta.get("samples_dropped"):
            story.append(Spacer(1, 0.3*cm))
            dropped = ", ".join(f"S{s}" for s in alt_meta["samples_dropped"])
            story.append(Paragraph(
                f"⚠ <b>Muestras sin réplicas válidas tras la exclusión:</b> "
                f"{dropped}. Estas muestras quedan excluidas del cálculo de "
                f"CV y de la agregación para análisis estadístico.",
                ParagraphStyle("warn", parent=body,
                                textColor=colors.HexColor("#C0756A"))))

        # n efectivo por muestra
        n_eff = data.get("alt_n_eff")
        if n_eff is not None and len(n_eff):
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("n efectivo por muestra tras la exclusión", h3))
            n_data = [["Muestra", "n réplicas válidas"]]
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
                    "[Gráfica no disponible — instala svglib: pip install svglib]",
                    note))
                story.append(Spacer(1, 0.3*cm))

    # ── M1 ───────────────────────────────────────────────────────────────────
    story.append(Paragraph("Módulo 1 · Linealidad de diluciones QC", h2))
    story.append(Paragraph(
        f"Umbral R² = {m1['r2_threshold']}. "
        f"Se evalúan {len([c for c in ['first','second','third','mean'] if True])} estrategias "
        f"de agregación de réplicas por nivel de dilución, eligiendo la de mayor R² con pendiente positiva.",
        body))
    story.append(Spacer(1, 0.2*cm))

    for fig, desc in zip(_figs_m1(m1, N), [
        "Distribución de metabolitos por resultado del filtro de linealidad.",
        f"Distribución del coeficiente R² para metabolitos aceptados y rechazados. "
        f"Línea discontinua: umbral R² = {m1['r2_threshold']}.",
        "Frecuencia de cada motivo de exclusión."
    ]):
        img = _fig_to_image(fig, width_cm=16, height_cm=7)
        story.append(Paragraph(desc, note))
        if img:
            story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
        else:
            story.append(Paragraph("[Gráfica no disponible]", note))
            story.append(Spacer(1, 0.3*cm))

    story.append(PageBreak())

    # ── QCR ──────────────────────────────────────────────────────────────────
    story.append(Paragraph("QCR · Diagnóstico de réplicas de inyección", h2))
    story.append(Paragraph(
        "Nivel 1: diagnóstico global por suma de intensidades y mediana de intensidades "
        f"(umbral: 70% de la mediana de las réplicas). "
        "Nivel 2: detección de outliers por metabolito (|Z| > 2) en réplicas válidas.",
        body))

    qcr_df = qcr["qcr_df"]
    if qcr["n_fail"] > 0:
        failed = qcr_df[qcr_df["Estado"]=="fail"]
        story.append(Paragraph(
            f"⚠ Réplicas con fallo confirmado: " +
            ", ".join(f"S{r.Sample}-R{r.Replica}" for r in failed.itertuples()),
            ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#C0756A"))))
    story.append(Spacer(1, 0.2*cm))

    for fig, desc in zip(_figs_qcr(qcr, N), [
        "Estado de cada réplica por muestra (válida / sospechosa / fallo confirmado).",
        "Suma total de intensidades por réplica, coloreada por estado de inyección."
    ]):
        img = _fig_to_image(fig, width_cm=16, height_cm=7)
        story.append(Paragraph(desc, note))
        if img:
            story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
        else:
            story.append(Paragraph("[Gráfica no disponible]", note))
            story.append(Spacer(1, 0.3*cm))

    # Tabla QCR
    story.append(Paragraph("Detalle por réplica", h3))
    cols_qcr = ["Sample","Replica","Suma_int","Mediana_int","Estado","N_outliers","Recomendacion"]
    tbl_data = [["Muestra","Réplica","Suma int.","Med. int.","Estado","Outliers","Recomendación"]]
    for _, row in qcr_df[cols_qcr].iterrows():
        tbl_data.append([
            f"S{row['Sample']}", f"R{int(row['Replica'])}",
            f"{row['Suma_int']/1e6:.2f}M", f"{row['Mediana_int']:.0f}",
            row["Estado"], str(int(row["N_outliers"])), row["Recomendacion"]
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
    for i, row in enumerate(tbl_data[1:], 1):
        if row[4] == "fail":
            cond_style.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#fff0f0")))
        elif row[4] == "suspect":
            cond_style.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#fffbec")))
        else:
            bg = colors.HexColor("#F7F6F2") if i%2==0 else colors.white
            cond_style.append(("BACKGROUND",(0,i),(-1,i),bg))
    tbl_qcr.setStyle(TableStyle(cond_style))
    story.append(tbl_qcr)

    if m2:
        story.append(PageBreak())
        # ── M2 ───────────────────────────────────────────────────────────────
        story.append(Paragraph("Módulo 2 · Repetibilidad y Reproducibilidad", h2))
        story.append(Paragraph(
            f"Umbral %CV muestras = {m2['cv_threshold']}%. "
            f"Umbral %CV QC normalización = {m2['qc_cv_thresh']}%. "
            "ICC calculado por ANOVA one-way (umbral de consistencia ICC > 0.75).",
            body))
        story.append(Spacer(1, 0.2*cm))

        for fig, desc in zip(_figs_m2(m2, N), [
            f"Distribución del %CV por muestra. Línea roja: umbral {m2['cv_threshold']}%.",
            "Histograma del %CV mediana global.",
            "CV de los QC de normalización. Líneas de referencia: umbral QC y umbral muestras.",
            "Distribución del ICC para todos los metabolitos."
        ]):
            img = _fig_to_image(fig, width_cm=16, height_cm=7)
            story.append(Paragraph(desc, note))
            if img:
                story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
            else:
                story.append(Paragraph("[Gráfica no disponible]", note))
                story.append(Spacer(1, 0.3*cm))

        story.append(PageBreak())
        # ── Conjunto ─────────────────────────────────────────────────────────
        story.append(Paragraph("Análisis conjunto · Linealidad + CV", h2))
        lin_ok = m1["lin_df"]["ok"].values; cv_ok = m2["cv_df"]["CV_ok"].values
        n_both_ = int((lin_ok & cv_ok).sum())
        story.append(Paragraph(
            f"Metabolitos que pasan ambos criterios (linealidad R²≥{m1['r2_threshold']} "
            f"y CV≤{m2['cv_threshold']}%): {n_both_} ({100*n_both_/N:.1f}%).",
            body))
        story.append(Spacer(1, 0.2*cm))

        for fig, desc in zip(_figs_jt(m1, m2, N), [
            "Scatter R² vs %CV mediana. Cada punto es un metabolito; verde = pasa linealidad.",
            "Diagrama de Venn: metabolitos que pasan cada criterio individualmente y ambos."
        ]):
            img = _fig_to_image(fig, width_cm=16, height_cm=7)
            story.append(Paragraph(desc, note))
            if img:
                story.append(KeepTogether([img, Spacer(1, 0.4*cm)]))
            else:
                story.append(Paragraph("[Gráfica no disponible]", note))
                story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    return buf.getvalue()


# =============================================================================
# FALLBACK: HTML imprimible (no requiere reportlab ni svglib)
# El navegador lo abre y el usuario usa Ctrl+P → Guardar como PDF
# =============================================================================

def build_print_html(data: dict) -> str:
    """Genera un HTML con gráficas Plotly interactivas inline.
    No requiere kaleido ni ninguna dependencia extra.
    El usuario usa Ctrl+P → Guardar como PDF."""
    m1=data["m1"]; qcr=data["qcr"]; m2=data["m2"]; N=data["N"]
    alt_meta = data.get("alt_meta")

    # Configuración visual común para el informe
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
        """Figura ancho completo — JS viene del <head> via /plotly.js."""
        _merge_layout(fig, REPORT_LAYOUT)
        h = fig.to_html(full_html=False, include_plotlyjs=False,
                        config={"displayModeBar": False, "responsive": True},
                        div_id=f"fig_{id(fig)}")
        cap = f'<p class="caption">{caption}</p>' if caption else ""
        return f'<div class="fig-block">{h}{cap}</div>'

    def fh(fig, caption=""):
        """Figura media anchura."""
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

    # ═══════════════════════════════════════════════
    # M1 — Linealidad
    # ═══════════════════════════════════════════════
    good=m1["good"]; bad=m1["bad"]; nodat=m1["nodat"]; thr=m1["r2_threshold"]
    n_is  = int((good["reason"]=="ion_suppression").sum()) if "reason" in good.columns else 0
    n_pos = len(good) - n_is

    lbls=["Aceptados","Rechazados","Sin datos"]; vals=[len(good),len(bad),len(nodat)]
    cols_=[PAL["good"],PAL["bad"],PAL["nodata"]]
    if n_is:
        lbls.insert(1,"Ion supp."); vals.insert(1,n_is)
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
        text=f"<b>{N}</b><br>total", x=0.30, y=0.5,
        xref="paper", yref="paper",
        showarrow=False, font=dict(size=14))
    fig_don.update_layout(
        title="Resumen filtrado por linealidad",
        showlegend=True,
        legend=dict(orientation="v", x=0.65, y=0.5,
                    xanchor="left", yanchor="middle",
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=20, t=40, b=20))

    r2g=good["r2"].dropna().values; r2b=bad["r2"].dropna().values
    fig_his = go.Figure()
    fig_his.add_trace(go.Histogram(x=r2g, name="Aceptados",   xbins=dict(size=.05),
                                   marker_color=PAL["good"], opacity=.82))
    fig_his.add_trace(go.Histogram(x=r2b, name="Rechazados",  xbins=dict(size=.05),
                                   marker_color=PAL["bad"],  opacity=.82))
    fig_his.add_vline(x=thr, line_dash="dash", line_color="#444",
                      annotation_text=f"R² = {thr}", annotation_position="top right")
    fig_his.update_layout(title=f"Distribución R²", barmode="overlay",
                          xaxis=dict(range=[0,1], title="R²"),
                          yaxis=dict(title="n metabolitos"))

    RMAP={"negative_slope":"Pend. negativa","r2_low":"R² bajo","only_1_point":"1 punto",
          "no_data":"Sin señal","only_2_points":"2 puntos","r2_na":"R² N/A",
          "ion_suppression":"Ion supp."}
    rej = m1["lin_df"][~m1["lin_df"]["ok"]]["reason"].map(RMAP).value_counts()
    fig_rej = go.Figure(go.Bar(x=rej.values, y=rej.index, orientation="h",
                               marker_color=PAL["bad"], opacity=.85,
                               hovertemplate="%{y}: %{x}<extra></extra>"))
    fig_rej.update_layout(title="Motivos de exclusión", xaxis_title="n metabolitos")

    m1_stats = stat_row(
        stat_card(n_pos,    "Aceptados",     f"{100*n_pos/N:.1f}% · {n_pos}/{N}",    "green"),
        stat_card(len(bad), "Rechazados",    f"{100*len(bad)/N:.1f}% · {len(bad)}/{N}", "red"),
        stat_card(len(nodat),"Sin datos",    f"{100*len(nodat)/N:.1f}%",              "gray"),
        *([ stat_card(n_is, "Ion suppression", f"{100*n_is/N:.1f}%", "amber")] if n_is else [])
    )
    m1_html = (m1_stats
               + two_cols(fh(fig_don,"Resumen"), fh(fig_his,"Distribución R²"))
               + fb(fig_rej, "Frecuencia de cada motivo de exclusión"))

    # ═══════════════════════════════════════════════
    # QCR — Diagnóstico de réplicas
    # ═══════════════════════════════════════════════
    df=qcr["qcr_df"]; samples=sorted(df["Sample"].unique())

    fig_bar = go.Figure()
    for est, col, lbl in [("ok",PAL["good"],"Válida"),
                           ("suspect",PAL["amber"],"Sospechosa"),
                           ("fail",PAL["bad"],"Fallo")]:
        cnts = [len(df[(df["Sample"]==s)&(df["Estado"]==est)]) for s in samples]
        fig_bar.add_trace(go.Bar(x=[f"S{s}" for s in samples], y=cnts,
                                 name=lbl, marker_color=col, opacity=.85))
    fig_bar.update_layout(title="Estado de réplicas por muestra", barmode="stack",
                          xaxis_title="Muestra", yaxis_title="n réplicas")

    fig_sum = go.Figure()
    for est, col, lbl in [("ok",PAL["good"],"Válida"),
                           ("suspect",PAL["amber"],"Sospechosa"),
                           ("fail",PAL["bad"],"Fallo")]:
        sub = df[df["Estado"]==est]
        fig_sum.add_trace(go.Scatter(
            x=[f"S{r.Sample} R{r.Replica}" for r in sub.itertuples()],
            y=sub["Suma_int"]/1e6, mode="markers",
            marker=dict(color=col, size=9, opacity=.85), name=lbl,
            hovertemplate="<b>%{x}</b><br>%{y:.2f}M<extra></extra>"))
    fig_sum.update_layout(title="Suma de intensidades por réplica",
                          yaxis_title="Suma int. (×10⁶)")

    n_total_r = qcr["n_ok"]+qcr["n_suspect"]+qcr["n_fail"]
    qcr_stats = stat_row(
        stat_card(qcr["n_ok"],      "Válidas",
                  f"{100*qcr['n_ok']/n_total_r:.1f}% · {qcr['n_ok']}/{n_total_r}", "green"),
        stat_card(qcr["n_suspect"], "Sospechosas", "1 criterio", "amber"),
        stat_card(qcr["n_fail"],    "Fallos",      "ambos criterios", "red"),
        stat_card(qcr["n_outlier_total"], "Outliers metab.", "réplicas válidas", "slate"),
    )
    qcr_html = (qcr_stats
                + two_cols(fh(fig_bar, "Estado por muestra"),
                           fh(fig_sum, "Suma de intensidades")))

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
        fig_box.update_layout(title="%CV por muestra", yaxis_title="%CV")

        cv_med = cv_df_["CV_median"].dropna().values
        fig_cvh = go.Figure(go.Histogram(x=cv_med, xbins=dict(size=2),
                                         marker_color=PAL["good"], opacity=.85))
        fig_cvh.add_vline(x=thr_cv, line_dash="dash", line_color=PAL["bad"],
                          annotation_text=f"{thr_cv}%", annotation_position="top right")
        fig_cvh.update_layout(title="CV mediana global",
                               xaxis_title="%CV mediana", yaxis_title="n metabolitos")

        cv_qc_c = cv_qc[~np.isnan(cv_qc)&(cv_qc<200)]
        fig_qcc = go.Figure(go.Histogram(x=cv_qc_c, xbins=dict(size=2),
                                         marker_color=PAL["amber"], opacity=.85))
        fig_qcc.add_vline(x=thr_qc, line_dash="dash", line_color=PAL["bad"],
                          annotation_text=f"QC: {thr_qc}%", annotation_position="top right")
        fig_qcc.add_vline(x=thr_cv, line_dash="dot", line_color=PAL["slate"],
                          annotation_text=f"Muestras: {thr_cv}%", annotation_position="top left")
        fig_qcc.update_layout(title="CV QC normalización",
                               xaxis_title="%CV", yaxis_title="n metabolitos")

        icc_c = icc[~np.isnan(icc)]
        fig_icc = go.Figure()
        fig_icc.add_trace(go.Histogram(x=icc_c[icc_c<.75], xbins=dict(size=.05),
                                       marker_color=PAL["nodata"], name="ICC<0.75", opacity=.85))
        fig_icc.add_trace(go.Histogram(x=icc_c[icc_c>=.75], xbins=dict(size=.05),
                                       marker_color=PAL["good"], name="ICC≥0.75", opacity=.85))
        fig_icc.add_vline(x=.75, line_dash="dash", line_color="#444")
        fig_icc.update_layout(title="ICC", barmode="overlay",
                               xaxis_title="ICC", yaxis_title="n metabolitos")

        m2_stats = stat_row(
            stat_card(n_ok_cv,  f"CV ≤ {thr_cv}%", f"{100*n_ok_cv/N:.1f}% · {n_ok_cv}/{N}",  "green"),
            stat_card(n_bad_cv, f"CV > {thr_cv}%",  f"{100*n_bad_cv/N:.1f}% · {n_bad_cv}/{N}", "red"),
            stat_card(n_ok_icc, "ICC > 0.75",        f"{100*n_ok_icc/N:.1f}% · {n_ok_icc}/{N}", "slate"),
        )
        m2_html = (m2_stats
                   + two_cols(fh(fig_box, "%CV por muestra"),
                               fh(fig_cvh, "CV mediana global"))
                   + two_cols(fh(fig_qcc, "CV QC normalización"),
                               fh(fig_icc, "ICC")))

    # ═══════════════════════════════════════════════
    # Análisis conjunto
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
        fig_rv.update_layout(title="R² vs %CV mediana",
                              xaxis_title="R²", yaxis_title="%CV (cap 100%)")

        fig_venn = go.Figure()
        fig_venn.add_shape(type="circle", x0=0.08,y0=0.05, x1=0.68,y1=0.95,
                           fillcolor=PAL["good"], opacity=0.25,
                           line=dict(color=PAL["good"], width=2))
        fig_venn.add_shape(type="circle", x0=0.35,y0=0.05, x1=0.95,y1=0.95,
                           fillcolor=PAL["slate"], opacity=0.25,
                           line=dict(color=PAL["slate"], width=2))
        fig_venn.add_annotation(x=0.23,y=0.5, text=f"<b>{n_lin_only}</b><br>Solo linealidad",
                                showarrow=False, font=dict(size=12,color=PAL["good"]))
        fig_venn.add_annotation(x=0.52,y=0.5, text=f"<b>{n_both}</b><br>Ambos",
                                showarrow=False, font=dict(size=14,color="#2C2C2A"))
        fig_venn.add_annotation(x=0.80,y=0.5, text=f"<b>{n_cv_only}</b><br>Solo CV",
                                showarrow=False, font=dict(size=12,color=PAL["slate"]))
        fig_venn.add_annotation(x=0.5, y=0.04,
                                text=f"Sin ninguno: {n_neither}  ·  Total: {N}",
                                showarrow=False, font=dict(size=9,color=PAL["muted"]),
                                xref="paper", yref="paper")
        fig_venn.update_layout(title="Diagrama de Venn · Linealidad vs CV",
                               xaxis=dict(visible=False, range=[0,1]),
                               yaxis=dict(visible=False, range=[0,1]),
                               plot_bgcolor="white", showlegend=False)

        jt_stats = stat_row(
            stat_card(n_both, "Pasan ambos",       f"{100*n_both/N:.1f}% · {n_both}/{N}", "green"),
            stat_card(n_lin,  "Pasan linealidad",  f"{100*n_lin/N:.1f}%",                 "slate"),
            stat_card(n_cv,   f"Pasan CV≤{m2['cv_threshold']}%", f"{100*n_cv/N:.1f}%",   "amber"),
        )
        jt_html = (jt_stats
                   + two_cols(fh(fig_rv, "R² vs %CV mediana"),
                               fh(fig_venn, "Diagrama de Venn")))

    # ═══════════════════════════════════════════════
    # Bloque Análisis Alternativo (solo si procede)
    # ═══════════════════════════════════════════════
    alt_html = ""
    alt_title_tag = ""
    if alt_meta:
        mode_lbl = {"none":"Ninguna","fail":"Solo fallidas",
                     "fail_suspect":"Fallidas + sospechosas",
                     "manual":"Selección manual"}.get(alt_meta["mode"], alt_meta["mode"])
        alt_title_tag = " · Análisis alternativo"
        excl_rows = data.get("alt_excluded_rows")
        excl_table = ""
        if excl_rows is not None and len(excl_rows):
            rows_html = "".join(
                f'<tr><td>S{r["Sample"]}</td>'
                f'<td>R{int(r["Replica"])}</td>'
                f'<td class="st-{r["Estado"]}">{r["Estado"]}</td>'
                f'<td class="colname">{r["Column"]}</td></tr>'
                for _, r in excl_rows.iterrows()
            )
            excl_table = (
                '<table class="alt-tbl"><thead><tr>'
                '<th>Muestra</th><th>Réplica</th><th>Estado</th>'
                '<th>Nombre de columna original</th></tr></thead>'
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
                '<th>Muestra</th><th>Réplica</th><th>Estado</th>'
                '<th>Nombre de columna original</th></tr></thead>'
                f'<tbody>{rows_html}</tbody></table>'
            )

        dropped_html = ""
        if alt_meta.get("samples_dropped"):
            dropped = ", ".join(f"S{s}" for s in alt_meta["samples_dropped"])
            dropped_html = (
                f'<p class="alt-warn">⚠ <b>Muestras sin réplicas válidas tras '
                f'la exclusión:</b> {dropped}. Estas muestras quedan excluidas '
                f'del cálculo de CV y de la agregación.</p>'
            )

        n_eff = data.get("alt_n_eff")
        n_eff_html = ""
        if n_eff is not None and len(n_eff):
            rows = "".join(
                f'<tr><td>S{r["Sample"]}</td><td>{int(r["n_valid_reps"])}</td></tr>'
                for _, r in n_eff.iterrows()
            )
            n_eff_html = (
                '<h3 class="alt-h3">n efectivo por muestra tras la exclusión</h3>'
                '<table class="alt-tbl alt-tbl-small"><thead><tr>'
                '<th>Muestra</th><th>n réplicas válidas</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
            )

        alt_html = f"""
        <div class="alt-box">
          <p>Este informe corresponde a un análisis <b>alternativo</b> en el
          que se han descartado réplicas de inyección consideradas
          problemáticas por el módulo QCR. Se re-ejecuta el pipeline completo
          (linealidad + CV/ICC + agregación MetaboAnalyst) utilizando
          únicamente las réplicas válidas.</p>

          <h3 class="alt-h3">Justificación metodológica</h3>
          <p>Cuando una réplica técnica presenta fallo de inyección
          (suma o mediana de intensidades &lt; 70% de la mediana de las
          réplicas de la misma muestra), la práctica estándar en metabolómica
          y lipidómica cuantitativa (<i>mQACC</i>, <i>MSI</i>,
          <i>Lipidomics Standards Initiative</i>) recomienda excluirla del
          cálculo de precisión intra-muestra.
          <b>No se realiza imputación con la media de las réplicas
          restantes</b>: sustituir una réplica fallida por la media del resto
          reduce artificialmente la desviación estándar y el coeficiente de
          variación (factor ≈ √(2/3) ≈ 0.82 para la SD y ~18% menos de CV)
          sin que exista una base física para ello. En su lugar, cada
          muestra conserva su <i>n efectivo</i> real tras la exclusión, y el
          CV intra-muestra se calcula únicamente cuando quedan ≥2 réplicas
          válidas.</p>

          <p><b>Modo de exclusión aplicado:</b> {mode_lbl}<br>
             <b>Total de réplicas descartadas:</b> {alt_meta['n_excluded']}</p>

          {'<h3 class="alt-h3">Réplicas excluidas (nombre completo de columna)</h3>' if excl_table else ''}
          {excl_table}

          {dropped_html}

          {n_eff_html}
        </div>
        """

    # ═══════════════════════════════════════════════
    # HTML final — JS de Plotly servido desde el servidor local
    # ═══════════════════════════════════════════════
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Informe Aletheia — {now}</title>
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
<button class="print-btn no-print" onclick="window.print()">🖨️ Guardar como PDF (Ctrl+P → A4 horizontal · sin márgenes)</button>
<h1>Aletheia · Informe de resultados{alt_title_tag}</h1>
<div class="meta">ECAI Espectrometría de Masas e Imagen Molecular · IMIBIC · Córdoba &nbsp;|&nbsp; {now}</div>

{section("Análisis alternativo — exclusión de réplicas", alt_html) if alt_html else ""}
{section("Módulo 1 · Linealidad de diluciones QC", m1_html)}
{section("QCR · Diagnóstico de réplicas de inyección", qcr_html)}
{section("Módulo 2 · Repetibilidad y Reproducibilidad", m2_html) if m2_html else ""}
{section("Análisis conjunto · Linealidad + CV", jt_html) if jt_html else ""}

<div class="footer">
  Generado con Aletheia · ECAI IMSMI · IMIBIC · {now}<br>
  Para guardar como PDF: Ctrl+P → Guardar como PDF → Orientación horizontal · Sin márgenes
</div>
</div>
</body>
</html>"""

