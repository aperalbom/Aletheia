"""Spanish strings of the PDF/HTML run report (key = English source string).

The keys must match, character for character, the first argument of the
``t("...")`` calls in ``core/pdf_report.py``.  Placeholders are identical in
both languages.
"""

ES_REPORT: dict[str, str] = {
    # ── Cover / generic ──────────────────────────────────────────────────────
    "Aletheia — Results report": "Aletheia — Informe de resultados",
    "Alternative analysis": "Análisis alternativo",
    "ECAI Mass Spectrometry and Molecular Imaging · IMIBIC · Córdoba":
        "ECAI Espectrometría de Masas e Imagen Molecular · IMIBIC · Córdoba",
    "Generated on {date}": "Generado el {date}",
    "Aletheia report — {now}": "Informe Aletheia — {now}",
    "Generated with Aletheia · ECAI IMSMI · IMIBIC · {now}":
        "Generado con Aletheia · ECAI IMSMI · IMIBIC · {now}",
    "To save as PDF: Ctrl+P → Save as PDF → Landscape · No margins":
        "Para guardar como PDF: Ctrl+P → Guardar como PDF → Orientación horizontal · Sin márgenes",
    "🖨️ Save as PDF (Ctrl+P → A4 landscape · no margins)":
        "🖨️ Guardar como PDF (Ctrl+P → A4 horizontal · sin márgenes)",
    "[Figure not available]": "[Gráfica no disponible]",
    "[Figure not available — install svglib: pip install svglib]":
        "[Gráfica no disponible — instala svglib: pip install svglib]",

    # ── Cover summary table ──────────────────────────────────────────────────
    "Parameter": "Parámetro",
    "Value": "Valor",
    "Total features": "Total metabolitos",
    "Linearity accepted": "Aceptados linealidad",
    "Rejected": "Rechazados",
    "Accepted": "Aceptados",
    "No data": "Sin datos",
    "Non-monotonic": "No monotónico",
    "Valid / total replicates": "Réplicas válidas",
    "Valid replicates": "Válidas",
    "Injection failures": "Fallos de inyección",
    "Pass both criteria": "Pasan ambos criterios",

    # ── Status / recommendation / mode / reason labels ───────────────────────
    "Valid": "Válida",
    "Suspect": "Sospechosa",
    "Failed": "Fallo",
    "Exclude replicate": "Excluir réplica",
    "Review manually": "Revisar manualmente",
    "No issues": "Sin incidencias",
    "High outliers": "Outliers elevados",
    "None": "Ninguna",
    "Failed only": "Solo fallidas",
    "Failed + suspect": "Fallidas + sospechosas",
    "Manual selection": "Selección manual",
    "Negative slope": "Pend. negativa",
    "Low R²": "R² bajo",
    "1 point": "1 punto",
    "No signal": "Sin señal",
    "2 points": "2 puntos",

    # ── Alternative analysis ─────────────────────────────────────────────────
    "<b>Exclusion mode applied:</b> {mode} ·  <b>{n}</b> replicate(s) discarded":
        "<b>Modo de exclusión aplicado:</b> {mode} ·  <b>{n}</b> réplica(s) descartadas",
    "Alternative analysis — replicate exclusion":
        "Análisis alternativo — exclusión de réplicas",
    "This report corresponds to an <b>alternative</b> analysis in which injection replicates considered problematic by the QCR module have been discarded. The full pipeline is re-run (linearity + CV/ICC + MetaboAnalyst aggregation) using only the valid replicates.":
        "Este informe corresponde a un análisis <b>alternativo</b> en el que se han descartado réplicas de inyección consideradas problemáticas por el módulo QCR. Se re-ejecuta el pipeline completo (linealidad + CV/ICC + agregación MetaboAnalyst) utilizando únicamente las réplicas válidas.",
    "Methodological justification": "Justificación metodológica",
    "When a technical replicate shows an injection failure (sum or median of intensities &lt; 70% of the median of the replicates of the same sample), standard practice in quantitative metabolomics and lipidomics (<i>mQACC</i>, <i>MSI</i>, <i>Lipidomics Standards Initiative</i>) recommends excluding it from the calculation of intra-sample precision. <b>No imputation with the mean of the remaining replicates is performed</b>: replacing a failed replicate by the mean of the rest artificially reduces the standard deviation and the coefficient of variation (factor ≈ √(2/3) ≈ 0.82 for the SD and ~18% lower CV) without any physical basis. Instead, each sample keeps its real <i>effective n</i> after the exclusion, and the intra-sample CV is computed only when ≥2 valid replicates remain.":
        "Cuando una réplica técnica presenta fallo de inyección (suma o mediana de intensidades &lt; 70% de la mediana de las réplicas de la misma muestra), la práctica estándar en metabolómica y lipidómica cuantitativa (<i>mQACC</i>, <i>MSI</i>, <i>Lipidomics Standards Initiative</i>) recomienda excluirla del cálculo de precisión intra-muestra. <b>No se realiza imputación con la media de las réplicas restantes</b>: sustituir una réplica fallida por la media del resto reduce artificialmente la desviación estándar y el coeficiente de variación (factor ≈ √(2/3) ≈ 0.82 para la SD y ~18% menos de CV) sin que exista una base física para ello. En su lugar, cada muestra conserva su <i>n efectivo</i> real tras la exclusión, y el CV intra-muestra se calcula únicamente cuando quedan ≥2 réplicas válidas.",
    "<b>Exclusion mode applied:</b> {mode}": "<b>Modo de exclusión aplicado:</b> {mode}",
    "<b>Total replicates discarded:</b> {n}": "<b>Total de réplicas descartadas:</b> {n}",
    "Excluded replicates (full column name):": "Réplicas excluidas (nombre completo de columna):",
    "Excluded replicates (full column name)": "Réplicas excluidas (nombre completo de columna)",
    "Sample": "Muestra",
    "Replicate": "Réplica",
    "Status": "Estado",
    "Original column name": "Nombre de columna original",
    "⚠ <b>Samples without valid replicates after exclusion:</b> {dropped}. These samples are excluded from the calculation of CV and from the aggregation for statistical analysis.":
        "⚠ <b>Muestras sin réplicas válidas tras la exclusión:</b> {dropped}. Estas muestras quedan excluidas del cálculo de CV y de la agregación para análisis estadístico.",
    "⚠ <b>Samples without valid replicates after exclusion:</b> {dropped}. These samples are excluded from the calculation of CV and from the aggregation.":
        "⚠ <b>Muestras sin réplicas válidas tras la exclusión:</b> {dropped}. Estas muestras quedan excluidas del cálculo de CV y de la agregación.",
    "Effective n per sample after exclusion": "n efectivo por muestra tras la exclusión",
    "n valid replicates": "n réplicas válidas",

    # ── Module 1 ─────────────────────────────────────────────────────────────
    "Module 1 · QC dilution linearity": "Módulo 1 · Linealidad de diluciones QC",
    "R² threshold = {thr}. 4 replicate-aggregation strategies are evaluated for each dilution level, choosing the one with the highest R² and a positive slope.":
        "Umbral R² = {thr}. Se evalúan 4 estrategias de agregación de réplicas por nivel de dilución, eligiendo la de mayor R² con pendiente positiva.",
    "Distribution of features by linearity filter result.":
        "Distribución de metabolitos por resultado del filtro de linealidad.",
    "Distribution of the R² coefficient for accepted and rejected features. Dashed line: R² threshold = {thr}.":
        "Distribución del coeficiente R² para metabolitos aceptados y rechazados. Línea discontinua: umbral R² = {thr}.",
    "Frequency of each exclusion reason.": "Frecuencia de cada motivo de exclusión.",
    "M1 · Linearity summary": "M1 · Resumen linealidad",
    "M1 · R² distribution": "M1 · Distribución R²",
    "M1 · Exclusion reasons": "M1 · Motivos de exclusión",
    "Linearity filter summary": "Resumen filtrado por linealidad",
    "R² distribution": "Distribución R²",
    "Reasons for exclusion": "Motivos de exclusión",
    "Summary": "Resumen",
    "n features": "n metabolitos",
    "total": "total",

    # ── QCR ──────────────────────────────────────────────────────────────────
    "QCR · Injection replicate diagnostics": "QCR · Diagnóstico de réplicas de inyección",
    "Level 1: global diagnosis by sum of intensities and median of intensities (threshold: 70% of the median of the replicates). Level 2: per-feature outlier detection (|Z| > 2) in valid replicates.":
        "Nivel 1: diagnóstico global por suma de intensidades y mediana de intensidades (umbral: 70% de la mediana de las réplicas). Nivel 2: detección de outliers por metabolito (|Z| > 2) en réplicas válidas.",
    "⚠ Replicates with confirmed failure: {names}": "⚠ Réplicas con fallo confirmado: {names}",
    "Status of each replicate per sample (valid / suspect / confirmed failure).":
        "Estado de cada réplica por muestra (válida / sospechosa / fallo confirmado).",
    "Total sum of intensities per replicate, coloured by injection status.":
        "Suma total de intensidades por réplica, coloreada por estado de inyección.",
    "Detail per replicate": "Detalle por réplica",
    "Sum int.": "Suma int.",
    "Med. int.": "Med. int.",
    "Outliers": "Outliers",
    "Recommendation": "Recomendación",
    "QCR · Replicate status per sample": "QCR · Estado de réplicas por muestra",
    "QCR · Sum of intensities per replicate": "QCR · Suma de intensidades por réplica",
    "Sum int. (×10⁶)": "Suma int. (×10⁶)",
    "Replicate status per sample": "Estado de réplicas por muestra",
    "Sum of intensities per replicate": "Suma de intensidades por réplica",
    "n replicates": "n réplicas",
    "Suspect replicates": "Sospechosas",
    "Failed replicates": "Fallos",
    "Feature outliers": "Outliers metab.",
    "1 criterion": "1 criterio",
    "both criteria": "ambos criterios",
    "in valid replicates": "réplicas válidas",
    "Status per sample": "Estado por muestra",
    "Sum of intensities": "Suma de intensidades",

    # ── Module 2 ─────────────────────────────────────────────────────────────
    "Module 2 · Repeatability and Reproducibility": "Módulo 2 · Repetibilidad y Reproducibilidad",
    "Sample %CV threshold = {cv}%. Normalisation QC %CV threshold = {qc}%. ICC computed by one-way ANOVA (consistency threshold ICC > 0.75).":
        "Umbral %CV muestras = {cv}%. Umbral %CV QC normalización = {qc}%. ICC calculado por ANOVA one-way (umbral de consistencia ICC > 0.75).",
    "Distribution of %CV per sample. Red line: threshold {cv}%.":
        "Distribución del %CV por muestra. Línea roja: umbral {cv}%.",
    "Histogram of the global median %CV.": "Histograma del %CV mediana global.",
    "CV of the normalisation QCs. Reference lines: QC threshold and sample threshold.":
        "CV de los QC de normalización. Líneas de referencia: umbral QC y umbral muestras.",
    "Distribution of ICC for all features.": "Distribución del ICC para todos los metabolitos.",
    "M2 · %CV per sample": "M2 · %CV por muestra",
    "M2 · Global median CV": "M2 · CV mediana global",
    "M2 · Normalisation QC CV": "M2 · CV QC normalización",
    "Samples:{thr}%": "Muestras:{thr}%",
    "Samples: {thr}%": "Muestras: {thr}%",
    "%CV per sample": "%CV por muestra",
    "Global median CV": "CV mediana global",
    "Median %CV": "%CV mediana",
    "Normalisation QC CV": "CV QC normalización",

    # ── Joint analysis ───────────────────────────────────────────────────────
    "Joint analysis · Linearity + CV": "Análisis conjunto · Linealidad + CV",
    "Features passing both criteria (linearity R²≥{r2} and CV≤{cv}%): {n} ({pct}%).":
        "Metabolitos que pasan ambos criterios (linealidad R²≥{r2} y CV≤{cv}%): {n} ({pct}%).",
    "Scatter of R² vs median %CV. Each point is a feature; green = passes linearity.":
        "Scatter R² vs %CV mediana. Cada punto es un metabolito; verde = pasa linealidad.",
    "Venn diagram: features passing each criterion individually and both.":
        "Diagrama de Venn: metabolitos que pasan cada criterio individualmente y ambos.",
    "Joint · R² vs median %CV": "Conjunto · R² vs %CV mediana",
    "Joint · Venn — Linearity vs CV": "Conjunto · Venn — Linealidad vs CV",
    "R² vs median %CV": "R² vs %CV mediana",
    "Venn diagram · Linearity vs CV": "Diagrama de Venn · Linealidad vs CV",
    "Venn diagram": "Diagrama de Venn",
    "Linearity<br>only": "Solo<br>linealidad",
    "CV<br>only": "Solo<br>CV",
    "Linearity only": "Solo linealidad",
    "CV only": "Solo CV",
    "Both": "Ambos",
    "Neither: {n_neither}  ·  Total: {N}": "Sin ninguno: {n_neither}  ·  Total: {N}",
    "Pass both": "Pasan ambos",
    "Pass linearity": "Pasan linealidad",
    "Pass CV≤{thr}%": "Pasan CV≤{thr}%",
}
