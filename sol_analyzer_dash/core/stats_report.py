"""
core/stats_report.py
====================

PDF / DOCX report generation for the stats module.

Two entry points:

* :func:`build_pdf`   — uses ``reportlab`` if available, otherwise raises.
* :func:`build_docx`  — uses ``python-docx``.

Both consume the same ``data`` dict produced by ``pages/stats.py`` (mirrors
the structure used by ``core/pdf_report.py``):

    {
        "metadata":   {... from submission form ...},
        "pp_summary": "missing=halfmin · norm=pqn · …",
        "groups":     {"factor": "Condition", "values": ["WT","KO",…]},
        "univariate": {"comparisons": [{"a": …, "b": …, "table": DF, "n_sig": int}]},
        "pca":        {"explained": [.31, .12, .08], "scores": DF, "ellipses": {…}},
        "plsda":      {"accuracy_cv": .94, "p_value": .02, "vip_top": DF},
        "biomarkers": [{"comparison": (a,b), "top": DF}],
    }
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd


# =============================================================================
# DOCX
# =============================================================================

def build_docx(data: dict[str, Any], filename: str | None = None) -> bytes:
    """Build a Word report and return the raw bytes."""
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # ── Cover ────────────────────────────────────────────────────────────
    h = doc.add_heading("Statistical analysis report", level=0)
    md = data.get("metadata", {}) or {}
    if md.get("project"):
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(md["project"]); r.italic = True; r.font.size = Pt(13)
    if md.get("user_name"):
        p = doc.add_paragraph(f"Submitted by: {md['user_name']}"
                                + (f"  ({md['group']})" if md.get("group") else ""))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if data.get("date"):
        p = doc.add_paragraph(f"Generated: {data['date']}")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph("")

    # ── 1. Experimental design ───────────────────────────────────────────
    doc.add_heading("1. Experimental design", level=1)
    p = doc.add_paragraph()
    p.add_run(f"Number of biological samples: ").bold = True
    p.add_run(f"{data.get('n_samples', '—')}")
    p = doc.add_paragraph()
    p.add_run("Conditions: ").bold = True
    conds = data.get("groups", {}).get("values", [])
    p.add_run(", ".join(conds) if conds else "—")
    fact = data.get("factorial", {})
    if fact and fact.get("is_factorial"):
        p = doc.add_paragraph()
        p.add_run("Factorial design detected: ").bold = True
        n_f = fact.get("n_factors", "—")
        factors = fact.get("factors") or []
        try:
            desc = " × ".join(", ".join(f["levels"]) for f in factors)
        except Exception:
            desc = "—"
        p.add_run(f"{n_f} factors" + (f" — {desc}" if desc else ""))

    # ── 2. Preprocessing ─────────────────────────────────────────────────
    doc.add_heading("2. Preprocessing", level=1)
    p = doc.add_paragraph(
        "The data table from Aletheia (one column per biological sample, "
        "one row per feature) was preprocessed using the following pipeline: "
    )
    r = p.add_run(data.get("pp_summary", "—")); r.bold = True
    doc.add_paragraph(
        "Missing values were handled per feature, samples were normalised to "
        "compensate for dilution effects, and feature-wise transform + scaling "
        "were applied so each variable contributes comparably to downstream "
        "multivariate analyses."
    )

    # ── 3. Univariate analysis ───────────────────────────────────────────
    if data.get("univariate") and data["univariate"].get("comparisons"):
        doc.add_heading("3. Univariate analysis", level=1)
        for cmp_ in data["univariate"]["comparisons"]:
            doc.add_heading(f"3.{cmp_.get('idx', '')} {cmp_['a']} vs {cmp_['b']}",
                              level=2)
            p = doc.add_paragraph()
            p.add_run("Test: ").bold = True
            p.add_run(cmp_.get("test", "—"))
            p = doc.add_paragraph()
            p.add_run("Significant features (q ≤ 0.05): ").bold = True
            p.add_run(str(cmp_.get("n_sig", 0)))

            top = cmp_.get("table_top")
            if top is not None and len(top):
                _df_table(doc, top.head(20),
                          ["feature", "log2FC", "p", "q", "cohens_d"])

    # ── 4. PCA ───────────────────────────────────────────────────────────
    if data.get("pca"):
        doc.add_heading("4. Principal Component Analysis", level=1)
        ev = data["pca"].get("explained", [])
        if ev is not None and len(ev):
            txt = "Variance explained: " + " · ".join(
                f"PC{i+1} = {v*100:.1f}%" for i, v in enumerate(ev[:5])
            )
            doc.add_paragraph(txt)

    # ── 5. PLS-DA ────────────────────────────────────────────────────────
    if data.get("plsda"):
        doc.add_heading("5. PLS-DA", level=1)
        pls = data["plsda"]
        p = doc.add_paragraph()
        p.add_run("LOO cross-validation accuracy: ").bold = True
        p.add_run(f"{pls.get('accuracy_cv', float('nan')):.3f}")
        if pls.get("p_value") is not None:
            p = doc.add_paragraph()
            p.add_run(f"Permutation test (n = {pls.get('n_permutations', 1000)}): ").bold = True
            p.add_run(f"p = {pls['p_value']:.4f}")
        vip = pls.get("vip_top")
        if vip is not None and len(vip):
            doc.add_heading("Top VIPs (≥ 1.0)", level=2)
            _df_table(doc, vip.head(20), list(vip.columns))

    # ── 6. Biomarkers ────────────────────────────────────────────────────
    if data.get("biomarkers"):
        doc.add_heading("6. Biomarker candidates", level=1)
        for bm in data["biomarkers"]:
            doc.add_heading(f"{bm['comparison'][0]} vs {bm['comparison'][1]}",
                              level=2)
            top = bm.get("top")
            if top is not None and len(top):
                _df_table(doc, top.head(15),
                          ["feature", "AUC", "CI_lo", "CI_hi", "p_mwu"])

    # ── 7. References ────────────────────────────────────────────────────
    doc.add_heading("References", level=1)
    for ref in [
        "Dieterich F. et al. (2006). Probabilistic Quotient Normalization. "
        "Anal. Chem. 78, 4281–4290.",
        "van den Berg R.A. et al. (2006). Centering, scaling, and "
        "transformations: improving the biological information content of "
        "metabolomics data. BMC Genomics 7, 142.",
        "Chong I.G. & Jun C.H. (2005). Performance of some variable selection "
        "methods when multicollinearity is present. Chemom. Intell. Lab. Syst. "
        "78, 103–112.",
        "Benjamini Y. & Hochberg Y. (1995). Controlling the false discovery rate. "
        "J. R. Stat. Soc. B 57, 289–300.",
    ]:
        doc.add_paragraph(ref, style="Intense Quote")

    # Serialise
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _df_table(doc, df: pd.DataFrame, cols: list[str]) -> None:
    """Append a small DataFrame slice to the document as a Word table."""
    from docx.shared import Pt
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return
    tbl = doc.add_table(rows=1, cols=len(cols))
    tbl.style = "Light Grid Accent 1"
    hdr = tbl.rows[0].cells
    for i, c in enumerate(cols):
        hdr[i].text = c
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.bold = True; r.font.size = Pt(9)

    for _, row in df.iterrows():
        cells = tbl.add_row().cells
        for i, c in enumerate(cols):
            v = row[c]
            if isinstance(v, float):
                if abs(v) < 1e-3 and v != 0:
                    txt = f"{v:.2e}"
                else:
                    txt = f"{v:.4g}"
            else:
                txt = str(v)
            cells[i].text = txt
            for p in cells[i].paragraphs:
                for r in p.runs:
                    r.font.size = Pt(8.5)


# =============================================================================
# PDF
# =============================================================================

def build_pdf(data: dict[str, Any], filename: str | None = None) -> bytes:
    """Build a PDF report. Falls back to converting the docx via LibreOffice
    if reportlab is not installed.
    """
    try:
        return _build_pdf_reportlab(data)
    except (ImportError, ModuleNotFoundError):
        pass

    # Fallback — generate docx, then convert with LibreOffice
    docx_bytes = build_docx(data, filename)
    return _docx_to_pdf(docx_bytes)


def _build_pdf_reportlab(data: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                      Table, TableStyle, PageBreak)
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=2*cm, rightMargin=2*cm,
                              topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H0", parent=styles["Title"], fontSize=22,
                               textColor=colors.HexColor("#2C2C2A"),
                               spaceAfter=14))
    styles.add(ParagraphStyle(name="H1b", parent=styles["Heading1"], fontSize=15,
                               textColor=colors.HexColor("#4A9B8F"),
                               spaceBefore=12, spaceAfter=8))
    styles.add(ParagraphStyle(name="Body", parent=styles["BodyText"],
                               fontSize=10, leading=14))

    story = []
    md = data.get("metadata", {}) or {}
    story.append(Paragraph("Statistical analysis report", styles["H0"]))
    if md.get("project"):
        story.append(Paragraph(f"<i>{md['project']}</i>", styles["Body"]))
    if md.get("user_name"):
        story.append(Paragraph(
            f"Submitted by: <b>{md['user_name']}</b>"
            + (f"  ({md['group']})" if md.get("group") else ""),
            styles["Body"]))
    story.append(Spacer(1, 14))

    # Design
    story.append(Paragraph("1. Experimental design", styles["H1b"]))
    story.append(Paragraph(
        f"Number of biological samples: <b>{data.get('n_samples','—')}</b>",
        styles["Body"]))
    conds = data.get("groups", {}).get("values", [])
    story.append(Paragraph(
        "Conditions: " + (", ".join(conds) if conds else "—"), styles["Body"]))
    fact = data.get("factorial", {})
    if fact and fact.get("is_factorial"):
        story.append(Paragraph(
            f"Factorial design: <b>{fact['n_factors']} factors</b> — "
            + " × ".join(", ".join(f["levels"]) for f in fact["factors"]),
            styles["Body"]))

    # Preprocessing
    story.append(Paragraph("2. Preprocessing", styles["H1b"]))
    story.append(Paragraph(
        f"Pipeline: <b>{data.get('pp_summary', '—')}</b>", styles["Body"]))

    # Univariate
    if data.get("univariate") and data["univariate"].get("comparisons"):
        story.append(Paragraph("3. Univariate analysis", styles["H1b"]))
        for cmp_ in data["univariate"]["comparisons"]:
            story.append(Paragraph(
                f"<b>{cmp_['a']} vs {cmp_['b']}</b> · {cmp_.get('test','')}"
                f" · sig (q ≤ 0.05): <b>{cmp_.get('n_sig',0)}</b>",
                styles["Body"]))
            top = cmp_.get("table_top")
            if top is not None and len(top):
                story.append(_pdf_table(top.head(15),
                                         ["feature", "log2FC", "p", "q", "cohens_d"]))

    # PCA
    if data.get("pca"):
        story.append(Paragraph("4. Principal Component Analysis", styles["H1b"]))
        ev = data["pca"].get("explained", [])
        if ev is not None and len(ev):
            story.append(Paragraph(
                "Variance explained: " + " · ".join(
                    f"PC{i+1} = {v*100:.1f}%" for i, v in enumerate(ev[:5])
                ), styles["Body"]))

    # PLS-DA
    if data.get("plsda"):
        pls = data["plsda"]
        story.append(Paragraph("5. PLS-DA", styles["H1b"]))
        story.append(Paragraph(
            f"LOO accuracy: <b>{pls.get('accuracy_cv', float('nan')):.3f}</b>",
            styles["Body"]))
        if pls.get("p_value") is not None:
            story.append(Paragraph(
                f"Permutation test (n = {pls.get('n_permutations',1000)}): "
                f"<b>p = {pls['p_value']:.4f}</b>", styles["Body"]))

    # Biomarkers
    if data.get("biomarkers"):
        story.append(Paragraph("6. Biomarker candidates", styles["H1b"]))
        for bm in data["biomarkers"]:
            story.append(Paragraph(
                f"<b>{bm['comparison'][0]} vs {bm['comparison'][1]}</b>",
                styles["Body"]))
            top = bm.get("top")
            if top is not None and len(top):
                story.append(_pdf_table(top.head(10),
                                         ["feature", "AUC", "CI_lo", "CI_hi", "p_mwu"]))

    doc.build(story)
    return buf.getvalue()


def _pdf_table(df: pd.DataFrame, cols: list[str]):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return
    rows = [cols]
    for _, r in df.iterrows():
        row = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                row.append(f"{v:.2e}" if (abs(v) < 1e-3 and v != 0) else f"{v:.4g}")
            else:
                row.append(str(v))
        rows.append(row)
    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C2C2A")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("GRID",       (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _find_soffice() -> str | None:
    """Locate the LibreOffice headless binary across platforms.

    Looks first on PATH (``soffice``/``soffice.exe``) and then in the
    canonical install locations on Windows / macOS / Linux. Returns
    ``None`` if not found.
    """
    import shutil, os
    # 1. PATH
    for name in ("soffice", "soffice.exe"):
        p = shutil.which(name)
        if p:
            return p
    # 2. Common install paths
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/snap/bin/libreoffice",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _docx_to_pdf(docx_bytes: bytes) -> bytes:
    """Convert .docx → .pdf via LibreOffice headless.

    Raises ``RuntimeError`` with a clear message if LibreOffice is not
    installed on the host machine.
    """
    import subprocess, tempfile, os
    soffice = _find_soffice()
    if soffice is None:
        raise RuntimeError(
            "LibreOffice no está instalado. La generación de PDF "
            "requiere LibreOffice (soffice). Instálalo desde "
            "https://www.libreoffice.org/download — o, mientras tanto, "
            "usa la descarga DOCX y conviértelo manualmente. (Si está "
            "instalado pero no se encuentra, asegúrate de que la carpeta "
            "que contiene soffice.exe está en el PATH del sistema.)"
        )
    with tempfile.TemporaryDirectory() as td:
        dpath = os.path.join(td, "report.docx")
        with open(dpath, "wb") as f:
            f.write(docx_bytes)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", td, dpath],
            check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ppath = os.path.join(td, "report.pdf")
        with open(ppath, "rb") as f:
            return f.read()
