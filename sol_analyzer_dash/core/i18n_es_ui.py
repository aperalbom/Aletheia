"""Spanish strings of the web interface (key = English source string)."""

ES_UI: dict[str, str] = {}

ES_UI.update({
    # ── page header / upload / settings ──
    "QC linearity · QC replicates · CV/ICC · Joint analysis":
        "Linealidad QC · QC réplicas · CV/ICC · Análisis conjunto",
    "Drag the CSV here or click": "Arrastra el CSV o haz clic",
    "MetaboScape, MZmine 3, XCMS or MS-DIAL feature table (CSV)":
        "Tabla de features de MetaboScape, MZmine 3, XCMS o MS-DIAL (CSV)",
    "① File": "① Archivo",
    "② Settings": "② Configuración",
    "R² linearity": "R² linealidad",
    "%CV samples": "%CV muestras",
    "%CV QC norm.": "%CV QC norm.",
    "Injection threshold": "Umbral inyección",
    "Options": "Opciones",
    " 2pt → accept": " 2pt → aceptar",
    "Mode": "Modo",
    " Linearity + CV": " Linealidad + CV",
    " Linearity only": " Solo linealidad",
    "▶ Analyze": "▶ Analizar",

    # ── upload info / errors ──
    "{filename}: could not auto-detect format. Supported: MetaboScape, MZmine 3, XCMS, MS-DIAL.":
        "{filename}: no se pudo detectar el formato automáticamente. "
        "Formatos admitidos: MetaboScape, MZmine 3, XCMS, MS-DIAL.",
    "  ·  fmt={fmt}  ·  {n_feat} features  ·  {n_samp} samples × {n_reps} replicates  ·  {n_lvl} replicate/QC level":
        "  ·  fmt={fmt}  ·  {n_feat} metabolitos  ·  {n_samp} muestras × {n_reps} réplicas  ·  "
        "{n_lvl} réplica/nivel QC",

    # ── sample-mapping editor (page) ──
    "⚠ Invalid mapping: {err}": "⚠ Asignación no válida: {err}",
    "⚠ No usable QC dilution series ({n} level(s) with the «QC dilution» role). At least 2 levels are needed: without them every feature will come out as “no data” and none will be retained. Check the role assignment of the columns.":
        "⚠ No hay serie de dilución QC utilizable ({n} nivel(es) con rol «QC dilution»). "
        "Se necesitan al menos 2 niveles: sin ellos todos los metabolitos saldrán como "
        "«sin datos» y ninguno se conservará. Revisa la asignación de roles de las columnas.",
    "⚠ {n} column(s) with the «QC dilution» role have no dilution level; 100 % will be assigned by default. Fill in «Dilution %».":
        "⚠ {n} columna(s) con rol «QC dilution» no tienen nivel de dilución; "
        "se les asignará 100 % por defecto. Rellena «Dilución %».",
    "✓ QC dilution series: {n} levels ({levels} %).":
        "✓ Serie de dilución QC: {n} niveles ({levels} %).",
    "⬇ Save mapping (JSON)": "⬇ Guardar mapeo (JSON)",
    "⬆ Load mapping (JSON)": "⬆ Cargar mapeo (JSON)",
    "↺ Reset": "↺ Restablecer",
    "Changes made in this table are applied automatically when you press «Analyze».":
        "Los cambios de esta tabla se aplican automáticamente al pulsar «Analizar».",
    "① b Sample assignment": "① b Asignación de muestras",
    "Automatic assignment restored.": "Asignación automática restaurada.",
    "✗ The JSON does not match the file: {n} column(s) missing, e.g. {examples}":
        "✗ El JSON no coincide con el archivo: faltan {n} columna(s), p. ej. {examples}",
    "✓ Mapping loaded ({n} columns).": "✓ Mapeo cargado ({n} columnas).",
    "✗ Could not read the JSON: {err}": "✗ No se pudo leer el JSON: {err}",
    "Error in the sample assignment: {err}": "Error en la asignación de muestras: {err}",

    # ── tabs / generic ──
    "M1 · Linearity": "M1 · Linealidad",
    "QCR · Replicates": "QCR · Réplicas",
    "Joint analysis": "Análisis conjunto",
    "⚡ Alternative analysis": "⚡ Análisis alternativo",
    "📄 Export full PDF report": "📄 Exportar informe PDF completo",
    "Not available.": "No disponible.",
    "Total": "Total",

    # ── M1 ──
    "Accepted": "Aceptados",
    "Rejected": "Rechazados",
    "No data": "Sin datos",
    "Non-monotonic": "No monotónico",
    "Summary": "Resumen",
    "R² distribution": "Distribución R²",
    "Negative slope": "Pend. negativa",
    "Low R²": "R² bajo",
    "1 point": "1 punto",
    "No signal": "Sin señal",
    "2 points": "2 puntos",
    "Exclusion reasons": "Motivos exclusión",
    "R² distribution full vs drop": "R² distribución full vs drop",
    "Download M1": "Descargar M1",

    # ── QCR ──
    "Valid": "Válida",
    "Suspect": "Sospechosa",
    "Failed": "Fallo",
    "Exclude replicate": "Excluir réplica",
    "Review manually": "Revisar manualmente",
    "No issues": "Sin incidencias",
    "High outliers": "Outliers elevados",
    "Status per sample": "Estado por muestra",
    "Sum of intensities": "Suma de intensidades",
    "Sum int. (×10⁶)": "Suma int. (×10⁶)",
    "5% features": "5% metab.",
    "Outliers per feature": "Outliers por metabolito",
    "n features": "n metabolitos",
    "⚠ {n} replicate(s) with confirmed failure": "⚠ {n} réplica(s) con fallo confirmado",
    "⚠ {n} suspect replicate(s)": "⚠ {n} réplica(s) sospechosa(s)",
    "Valid replicates": "Válidas",
    "Suspect replicates": "Sospechosas",
    "Failures": "Fallos",
    "1 criterion  ·  {a}/{b}": "1 criterio  ·  {a}/{b}",
    "both criteria  ·  {a}/{b}": "ambos criterios  ·  {a}/{b}",
    "Feature outliers": "Outliers metab.",
    "valid replicates": "réplicas válidas",
    "Detail per replicate": "Detalle por réplica",
    "Download QCR": "Descargar QCR",

    # ── M2 ──
    "%CV per sample": "%CV por muestra",
    "Overall median CV": "CV mediana global",
    "Samples: {thr}%": "Muestras: {thr}%",
    "QC normalization CV": "CV QC normalización",
    "Biological CV": "CV biológico",
    "No biological samples": "Sin muestras biológicas",
    "Not applicable": "No aplicable",
    "  ({n} without CV)": "  ({n} sin CV)",
    "Download M2": "Descargar M2",

    # ── Joint analysis ──
    "R² vs median %CV": "R² vs %CV mediana",
    "<b>{n}</b><br>Linearity only": "<b>{n}</b><br>Solo linealidad",
    "<b>{n}</b><br>Both": "<b>{n}</b><br>Ambos",
    "<b>{n}</b><br>CV only": "<b>{n}</b><br>Solo CV",
    "None: {a}  ·  Total: {b}": "Sin ninguno: {a}  ·  Total: {b}",
    "Linearity": "Linealidad",
    "Venn · Linearity vs CV": "Venn · Linealidad vs CV",
    "Pass both": "Pasan ambos",
    "Pass linearity": "Pasan linealidad",
    "Pass CV≤{thr}%": "Pasan CV≤{thr}%",
    "Download combined": "Descargar combinado",

    # ── Alternative analysis ──
    "Re-runs the full pipeline (linearity + CV/ICC + aggregation) after discarding the selected replicates. No values are imputed: each sample keeps its real effective n. If a sample is left with ≤1 valid replicate, its within-sample CV is reported as NaN and flagged in the table.":
        "Re-ejecuta el pipeline completo (linealidad + CV/ICC + agregación) después de "
        "descartar las réplicas seleccionadas. No se imputan valores: cada muestra queda "
        "con su n efectivo real. Si una muestra se queda con ≤1 réplica válida, su CV "
        "intra-muestra se reporta como NaN y se indica en la tabla.",
    "  None (original analysis)": "  Ninguna (análisis original)",
    "  Failed only  ({n})": "  Solo fallidas  ({n})",
    "  Failed + suspect  ({n})": "  Fallidas + sospechosas  ({n})",
    "  Manual selection": "  Selección manual",
    "Exclusion mode": "Modo de exclusión",
    "Replicates to exclude:": "Réplicas a excluir:",
    "▶ Re-analyze without excluded replicates": "▶ Re-analizar sin réplicas excluidas",
    "Configure alternative analysis": "Configurar análisis alternativo",
    "⚠ Error in the alternative analysis": "⚠ Error en el análisis alternativo",
    "Mode: ": "Modo: ",
    "None": "Ninguna",
    "Failed only": "Solo fallidas",
    "Failed + suspect": "Fallidas + sospechosas",
    "Manual selection": "Selección manual",
    "{n} replicate(s) excluded": "{n} réplica(s) excluidas",
    "⚠ Samples without valid replicates: {samples}": "⚠ Muestras sin réplicas válidas: {samples}",
    "Applied settings": "Configuración aplicada",
    "Accepted (orig.)": "Aceptados (orig.)",
    "Accepted (alt.)": "Aceptados (alt.)",
    "{d:+d} features": "{d:+d} metabolitos",
    "Linearity comparison (M1)": "Comparativa linealidad (M1)",
    "CV comparison (M2)": "Comparativa CV (M2)",
    "M2 could not be recomputed: {err}": "M2 no pudo recalcularse: {err}",
    "Error in alternative M2": "Error en M2 alternativo",
    "n valid replicates": "n réplicas válidas",
    "Effective n per sample": "n efectivo por muestra",
    "📄 PDF report — alternative analysis": "📄 Informe PDF — análisis alternativo",
    "Downloads (alternative analysis)": "Descargas (análisis alternativo)",

    # ── components/sample_mapping.py ──
    "Sample": "Muestra",
    "Blank": "Blanco",
    "Exclude": "Excluir",
    "Column name": "Nombre de columna",
    "Sample ID": "ID de muestra",
    "Replicate #": "Réplica #",
    "Role": "Rol",
    "Dilution %": "Dilución %",
    "Sample mapping — source format: {fmt} · {n} columns":
        "Asignación de muestras — formato de origen: {fmt} · {n} columnas",
    "Auto-classification is a starting point only. Refine roles and dilution levels below; click Save mapping to persist the choices as a sidecar JSON.":
        "La clasificación automática es solo un punto de partida. Ajusta abajo los roles y "
        "los niveles de dilución; pulsa «Guardar mapeo» para conservar los cambios como un "
        "JSON auxiliar.",
})

ES_UI.update({
    # ── application shell (sidebar) ──
    "Aletheia": "Aletheia",
    "QC dilution filtering": "Filtrado por dilución QC",
    "Language": "Idioma",
    "Interface language": "Idioma de la interfaz",
})
