"""
pages/informe.py  —  Generador de Informe de entrega IMSMI
"""

import dash
from dash import html, dcc, Input, Output, State, callback, ALL, clientside_callback
from dash.exceptions import PreventUpdate
import datetime
import io

from sol_analyzer_dash.core import sample_history as _sh

dash.register_page(__name__, path="/informe", name="Generador de Informe")


# =============================================================================
# CLIENTSIDE CALLBACKS — clipboard buttons
# =============================================================================
# The "Copiar correo" and "Copiar M&M" buttons are rendered inside the result
# UI returned by `generar` (so they only exist after the user clicks "Generar
# informe"). Earlier versions tried to wire the click handler with a literal
# `<script>` tag injected via html.Script(), but Dash uses React under the
# hood and React does NOT evaluate script tags rendered through the virtual
# DOM — the handler was never attached.
#
# Clientside callbacks are the supported way to run JavaScript in Dash. They
# are registered once at module load and re-evaluate every time their inputs
# fire, even for components that are added to the layout dynamically (which
# requires suppress_callback_exceptions=True at the app level, already set
# in app.py).
#
# We don't care about the callback's Output — we just want the JS to run on
# every click — so we use the button's own `title` prop as a harmless target
# and always return dash_clientside.no_update.

_COPY_JS = """
function(n_clicks, text) {
    if (!n_clicks || !text) {
        return window.dash_clientside.no_update;
    }
    if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            var btn = document.getElementById('%BTN_ID%');
            if (!btn) { return; }
            var orig = btn.innerText;
            btn.innerText = '\\u2713 Copiado';
            setTimeout(function() { btn.innerText = orig; }, 2000);
        }).catch(function() {
            // Fallback: use a hidden textarea + execCommand for older browsers
            // or pages served over plain http where the Clipboard API is gated.
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'absolute';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); } catch (_) {}
            document.body.removeChild(ta);
            var btn = document.getElementById('%BTN_ID%');
            if (btn) {
                var orig = btn.innerText;
                btn.innerText = '\\u2713 Copiado';
                setTimeout(function() { btn.innerText = orig; }, 2000);
            }
        });
    }
    return window.dash_clientside.no_update;
}
"""

clientside_callback(
    _COPY_JS.replace("%BTN_ID%", "inf-copy-correo"),
    Output("inf-copy-correo", "title"),
    Input("inf-copy-correo", "n_clicks"),
    State("inf-correo-text", "children"),
    prevent_initial_call=True,
)

clientside_callback(
    _COPY_JS.replace("%BTN_ID%", "inf-copy-mm"),
    Output("inf-copy-mm", "title"),
    Input("inf-copy-mm", "n_clicks"),
    State("inf-mm-text", "children"),
    prevent_initial_call=True,
)

# =============================================================================
# CONSTANTES
# =============================================================================

PROTOCOLOS_META = {
    "meoh_1_3":          "Precipitación de proteínas con MeOH frío (1:3 v/v · 50 µL muestra + 150 µL MeOH)",
    "meoh_1_6":          "Precipitación de proteínas con MeOH frío (1:6 v/v · 50 µL muestra + 300 µL MeOH)",
    "meoh_chcl3_polar":  "Precipitación bifásica MeOH:CHCl₃ — fase polar (compatible con extracción combinada metabolómica + lipidómica + proteómica)",
}
PROTOCOLOS_LIPO = {
    "ipa_1_6":            "Precipitación de proteínas con IPA a temperatura ambiente (1:6 v/v · 50 µL muestra + 300 µL IPA)",
    "mtbe":               "Extracción con MTBE (evaporación y reconstitución en IPA:MeOH)",
    "meoh_chcl3_apolar":  "Precipitación bifásica MeOH:CHCl₃ — fase apolar (compatible con extracción combinada metabolómica + lipidómica + proteómica)",
}

ARCHIVOS_BASE = [
    ("raw",       "Datos crudos (.d)",
     "Carpeta con los archivos de adquisición originales del TIMS-TOF Pro (formato .d de Bruker). "
     "Contiene los datos brutos de espectrometría de masas tal como salen del equipo."),
    ("complete",  "{codigo}_CompleteExperiment.csv (sin filtrar)",
     "Tabla de features exportada directamente de MetaboScape, sin aplicar ningún filtro de calidad. "
     "Contiene todos los features detectados en todas las muestras, incluyendo los que no superan "
     "los criterios de calidad. Útil para revisar entidades excluidas o aplicar criterios alternativos."),
    ("filtered",  "experiment_filtered.csv",
     "Tabla principal recomendada. Contiene únicamente los metabolitos/lípidos que han superado "
     "el filtro de linealidad (R² ≥ {r2}) con pendiente positiva. "
     "Es el punto de partida para el análisis estadístico posterior."),
    ("aggregated","experiment_aggregated.csv",
     "Tabla agregada para análisis estadístico: una columna por muestra, obtenida como la media "
     "de las réplicas de inyección válidas tras excluir outliers individuales por metabolito (|Z|>2). "
     "Formato listo para importar directamente en MetaboAnalyst u otros programas de análisis multivariante."),
    ("good_coor", "good_coor.csv",
     "Listado de metabolitos aceptados por el filtro de linealidad, con R², estrategia de "
     "cálculo y número de puntos válidos en la curva de dilución. Útil para auditar el filtrado."),
    ("bad_coor",  "bad_coor.csv",
     "Listado de metabolitos excluidos por el filtro de linealidad, con el motivo de exclusión "
     "(pendiente negativa, R² insuficiente, datos insuficientes, etc.)."),
    ("qcr",       "qcr_report.csv",
     "Informe del diagnóstico de réplicas de inyección: estado de cada réplica (válida/sospechosa/"
     "fallo confirmado), suma e intensidad mediana, y recomendación de acción."),
    ("cv",        "cv_per_sample.csv",
     "Tabla de %CV (coeficiente de variación) calculado para cada metabolito sobre las réplicas "
     "de inyección de cada muestra, con CV mediana y máximo global."),
    ("combined",  "combined_results.csv",
     "Tabla resumen que integra los criterios de linealidad (R²), CV mediana entre réplicas, "
     "ICC y resultado del filtro dual para todos los metabolitos detectados."),
    ("pass_all",  "pass_all_criteria.csv",
     "Subconjunto de metabolitos que superan simultáneamente el criterio de linealidad "
     "(R² ≥ umbral, pendiente positiva) y el de repetibilidad (%CV ≤ umbral). "
     "Lista final recomendada para análisis estadístico cuando se aplica el modo combinado."),
    ("pdf",       "informe_resultados.pdf",
     "Informe PDF con todas las gráficas del análisis: resumen de linealidad, diagnóstico "
     "de réplicas de inyección, distribución de CV/ICC y análisis conjunto (diagrama de Venn)."),
]

# Archivos adicionales cuando se aplica análisis alternativo (exclusión de
# réplicas fallidas/sospechosas). Se añaden al final de la lista de archivos
# entregados y se auto-seleccionan cuando el usuario activa la opción.
ARCHIVOS_ALT = [
    ("alt_filtered",   "experiment_filtered_ALT.csv",
     "Tabla filtrada del análisis alternativo: mismos criterios de linealidad y CV que "
     "experiment_filtered.csv, pero recalculados tras excluir las réplicas de inyección "
     "problemáticas. Útil para verificar que las conclusiones del estudio no dependen de las "
     "réplicas que dispararon las alertas de control de calidad."),
    ("alt_aggregated", "experiment_aggregated_ALT.csv",
     "Tabla agregada del análisis alternativo (una columna por muestra, media de réplicas "
     "válidas). El n efectivo por muestra puede variar si alguna muestra tenía réplicas "
     "excluidas; este valor se recoge en el PDF del análisis alternativo."),
    ("alt_good_coor",  "good_coor_ALT.csv",
     "Listado de metabolitos aceptados por el filtro de linealidad en el análisis alternativo."),
    ("alt_bad_coor",   "bad_coor_ALT.csv",
     "Listado de metabolitos excluidos por el filtro de linealidad en el análisis alternativo."),
    ("alt_combined",   "combined_results_ALT.csv",
     "Tabla resumen del análisis alternativo (R², CV mediana, ICC, filtro dual) tras la "
     "exclusión de las réplicas problemáticas."),
    ("alt_pass_all",   "pass_all_criteria_ALT.csv",
     "Subconjunto del análisis alternativo que supera simultáneamente los criterios de "
     "linealidad y repetibilidad. Comparable con pass_all_criteria.csv del análisis principal."),
    ("alt_excluded",   "excluded_replicas_ALT.csv",
     "Listado detallado de las réplicas excluidas en el análisis alternativo, con su estado "
     "(fallo confirmado / sospechosa / manual) y el nombre CSV original completo "
     "({codigo}_[NOMBRE]_[VIAL]_[INYECCIÓN]_[RUN]) para trazabilidad."),
    ("alt_pdf",        "informe_sol_analyzer_ALT.pdf",
     "Informe PDF del análisis alternativo, con la misma estructura que el principal más "
     "una sección inicial que documenta las réplicas excluidas y el n efectivo por muestra."),
]

_ALT_MODE_LABEL = {
    "fail":         "réplicas con fallo confirmado de inyección",
    "fail_suspect": "réplicas con fallo confirmado de inyección y las clasificadas como sospechosas",
    "manual":       "réplicas seleccionadas manualmente por el operador",
}

_ALT_MODE_LABEL_EN = {
    "fail":         "injection replicates flagged as confirmed failures",
    "fail_suspect": "injection replicates flagged as confirmed failures or suspect",
    "manual":       "injection replicates manually flagged by the operator",
}

# =============================================================================
# SAMPLE TYPE TRANSLATION  EN → ES
# =============================================================================

_SAMPLE_ES: dict[str, str] = {
    "serum":               "suero",
    "plasma":              "plasma",
    "urine":               "orina",
    "tissue":              "tejido",
    "liver":               "hígado",
    "kidney":              "riñón",
    "brain":               "cerebro",
    "heart":               "corazón",
    "lung":                "pulmón",
    "muscle":              "músculo",
    "spleen":              "bazo",
    "adipose tissue":      "tejido adiposo",
    "adipose":             "tejido adiposo",
    "feces":               "heces",
    "stool":               "heces",
    "saliva":              "saliva",
    "csf":                 "líquido cefalorraquídeo",
    "cerebrospinal fluid": "líquido cefalorraquídeo",
    "blood":               "sangre",
    "cell culture":        "cultivo celular",
    "cells":               "células",
    "bile":                "bilis",
    "sweat":               "sudor",
    "skin":                "piel",
    "tumor":               "tumor",
    "tumor tissue":        "tejido tumoral",
    "cortex":              "corteza",
    "hippocampus":         "hipocampo",
    "hypothalamus":        "hipotálamo",
    "pituitary":           "hipófisis",
    "thyroid":             "tiroides",
    "pancreas":            "páncreas",
    "colon":               "colon",
    "intestine":           "intestino",
    "small intestine":     "intestino delgado",
    "large intestine":     "intestino grueso",
    "ovary":               "ovario",
    "testis":              "testículo",
    "bone marrow":         "médula ósea",
}

# Phrase-level translations applied before falling back to the per-term map.
# Each entry is (english_phrase, spanish_phrase). The matcher tries to detect
# the phrase as a *prefix* of the user term and translates the remaining
# tail using _SAMPLE_ES (e.g. "protein lysate from bone marrow"
# → "lisado proteico de médula ósea").
_SAMPLE_ES_PHRASES: list[tuple[str, str]] = [
    ("protein lysate from", "lisado proteico de"),
    ("protein lysate of",   "lisado proteico de"),
    ("protein lysates from","lisados proteicos de"),
    ("protein extract from","extracto proteico de"),
    ("protein extract of",  "extracto proteico de"),
    ("protein extracts from","extractos proteicos de"),
    ("tissue lysate from",  "lisado tisular de"),
    ("tissue lysate of",    "lisado tisular de"),
    ("cell lysate from",    "lisado celular de"),
    ("cell lysate of",      "lisado celular de"),
    ("homogenate from",     "homogenado de"),
    ("homogenate of",       "homogenado de"),
    ("lysate from",         "lisado de"),
    ("lysate of",           "lisado de"),
    ("extract from",        "extracto de"),
    ("extract of",          "extracto de"),
]

_SCAT_OPTIONS_INF = [
    {"label": " Tejido / órgano",  "value": "tissue"},
    {"label": " Cultivo celular",  "value": "cell_culture"},
    {"label": " Plasma",           "value": "plasma"},
    {"label": " Suero",            "value": "serum"},
    {"label": " Orina",            "value": "urine"},
    {"label": " Heces",            "value": "feces"},
    {"label": " Otro / varios",    "value": "other"},
]


def _translate_sample(term: str) -> str:
    """Translate a common English sample-type term to Spanish.

    Strategy:
      1. Exact match against _SAMPLE_ES (single-word terms like "serum").
      2. Prefix match against _SAMPLE_ES_PHRASES, then translate the tail
         using _SAMPLE_ES (e.g. "protein lysate from bone marrow"
         → "lisado proteico de médula ósea").
      3. Fall back to the original string (so users typing a Spanish term
         or an unrecognised English one are left untouched).
    """
    if not term:
        return term
    raw = term.strip()
    low = raw.lower()

    # 1) direct match
    if low in _SAMPLE_ES:
        return _SAMPLE_ES[low]

    # 2) phrase prefix match
    for en_phrase, es_phrase in _SAMPLE_ES_PHRASES:
        if low.startswith(en_phrase + " "):
            tail = low[len(en_phrase):].strip()
            tail_es = _SAMPLE_ES.get(tail, tail)
            return f"{es_phrase} {tail_es}".strip()

    # 3) try to find any per-term key embedded in the string (e.g. "serum from
    # patients" → "suero from patients"). This is a weak fallback used only
    # when no phrase match was found.
    return raw


# =============================================================================
# M&M EN INGLÉS
# =============================================================================

MM_CHEMICALS_META = """Chemicals and solvents
LC–MS grade solvents and reagents used in the analytical workflow were obtained from Biosolve BV (Valkenswaard, The Netherlands): water (H₂O), methanol (MeOH) and formic acid (FA). Ammonium formate, used as a mass recalibration solution, was purchased from Merck (National Institute of Standards and Technology, USA)."""

MM_CHEMICALS_LIPO = """Chemicals and solvents
The LC-MS grade solvents and reagents used in the analytical workflow were purchased from Biosolve BV (Valkenswaard, The Netherlands): water (H₂O), acetonitrile (ACN), isopropanol (IPA), methanol (MeOH) and formic acid (FA). Ammonium formate was purchased from Merck (National Institute of Standards and Technology, USA)."""

# Chloroform (CHCl₃) is only relevant when the biphasic MeOH:CHCl₃ protocol is
# selected; we append it to the standard "Chemicals and solvents" block on the
# fly inside the generar() callback.
_CHCL3_SENTENCE = (
    "Chloroform (CHCl₃) used for biphasic extraction was also purchased from "
    "Biosolve BV (Valkenswaard, The Netherlands)."
)

# Drying / evaporation step shared across protocols. Samples are concentrated
# in a Savant SpeedVac vacuum concentrator (Thermo Scientific) instead of a
# nitrogen stream.
_EVAP_ES = (
    "se evaporó en un concentrador centrífugo a vacío Savant SpeedVac "
    "(Thermo Scientific)"
)
_EVAP_ES_PLURAL = (
    "se evaporaron en un concentrador centrífugo a vacío Savant SpeedVac "
    "(Thermo Scientific)"
)
_EVAP_EN = (
    "evaporated in a Savant SpeedVac vacuum concentrator (Thermo Scientific)"
)


# =============================================================================
# BIPHASIC MeOH:CHCl₃ HELPERS
# =============================================================================

# Reference volumes for 100 µL of starting sample (the "standard" recipe).
# All other volumes scale linearly with the sample volume.
_BIPHASIC_REF = {
    "sample": 100,   # µL of sample
    "meoh":   400,   # µL of MeOH (×4 of sample)
    "chcl3":  100,   # µL of CHCl₃ (×1 of sample)
    "water":  300,   # µL of LC-MS grade water (×3 of sample)
}


def _scale_biphasic(start_vol_ul) -> dict:
    """Return a dict of volumes (sample, meoh, chcl3, water) scaled from the
    100 µL reference recipe to the provided starting sample volume.

    Falls back to the reference recipe when no/invalid value is supplied.
    """
    try:
        v = float(start_vol_ul)
        if v <= 0:
            v = 100.0
    except (TypeError, ValueError):
        v = 100.0
    factor = v / float(_BIPHASIC_REF["sample"])

    def _fmt(x: float) -> str:
        """Format as integer when possible, otherwise with up to 1 decimal."""
        return str(int(round(x))) if abs(x - round(x)) < 0.05 else f"{x:.1f}"

    return {
        "sample": _fmt(v),
        "meoh":   _fmt(_BIPHASIC_REF["meoh"]  * factor),
        "chcl3":  _fmt(_BIPHASIC_REF["chcl3"] * factor),
        "water":  _fmt(_BIPHASIC_REF["water"] * factor),
    }


def _recon_label(solvent: str, volume) -> tuple[str, str]:
    """Return (es_text, en_text) describing reconstitution.

    Example: ("100 µL de MeOH:IPA", "100 µL of MeOH:IPA").
    Falls back to a generic sentence if no volume is supplied.
    """
    sol = (solvent or "MeOH").strip() or "MeOH"
    try:
        v = float(volume)
        if v <= 0:
            v = None
    except (TypeError, ValueError):
        v = None
    if v is None:
        return (f"{sol}", f"{sol}")
    v_str = str(int(round(v))) if abs(v - round(v)) < 0.05 else f"{v:.1f}"
    return (f"{v_str} µL de {sol}", f"{v_str} µL of {sol}")


def _build_biphasic_protocol_es(phase: str, vols: dict, recon_es: str,
                                 workflow: str) -> str:
    """Spanish description of the biphasic MeOH:CHCl₃ protocol.

    phase   : 'polar' (metabolomics) | 'apolar' (lipidomics)
    vols    : dict from _scale_biphasic()
    recon_es: e.g. "100 µL de MeOH"
    workflow: 'single' | 'combo_i' | 'combo_ii'
    """
    fase_lbl_es = (
        "fase polar (FP, fase acuosa superior)"
        if phase == "polar" else
        "fase apolar (FA, fase orgánica inferior)"
    )

    common_steps = (
        f"Brevemente, sobre {vols['sample']} µL de muestra se añadieron "
        f"{vols['meoh']} µL de MeOH y se vorteó 1 min; se añadieron "
        f"{vols['chcl3']} µL de cloroformo y se vorteó 1 min; finalmente se "
        f"añadieron {vols['water']} µL de agua MS y se vorteó 3 min. La "
        f"mezcla se centrifugó 2 min a 15.000 × g, separándose una fase "
        f"polar (capa acuosa superior), una fase apolar (capa orgánica "
        f"inferior) y una interfase con la proteína."
    )

    if workflow == "single":
        # Single workflow: just one phase is recovered, the other discarded.
        # No "this also enables combined workflow" sentence (the lab is NOT
        # actually doing the combined extraction in this case).
        if phase == "polar":
            recover_es = (
                f"La fase polar (FP) se retiró cuidadosamente sin tocar las "
                f"otras fases, {_EVAP_ES} y se resuspendió en {recon_es} "
                f"antes del análisis."
            )
        else:
            recover_es = (
                f"La fase acuosa superior se descartó sin tocar las demás "
                f"fases y la fase apolar (FA) se recuperó cuidadosamente, "
                f"{_EVAP_ES} y se resuspendió en {recon_es} antes del "
                f"análisis."
            )
        return (
            f"Precipitación bifásica MeOH:CHCl₃, recuperándose la {fase_lbl_es}. "
            f"{common_steps} {recover_es}"
        )

    # Combined workflows: FP + FA + protein pellet are all recovered.
    pellet_es = (
        "Para recuperar el pellet de proteína, tras retirar las fases "
        "deseadas se añadieron 400 µL de MeOH, se vorteó 1 min y se "
        "centrifugó 3 min a 15.000 × g; el sobrenadante se descartó sin "
        "tocar el pellet."
    )

    if workflow == "combo_i":
        target_es = (
            "metabolómica" if phase == "polar" else "lipidómica"
        )
        compat_es = (
            "Este protocolo se aplicó en un flujo combinado que permite "
            "recuperar, a partir de una sola alícuota, la fase polar (FP) "
            "para metabolómica, la fase apolar (FA) para lipidómica y el "
            "pellet de proteína para proteómica."
        )
        recover_es = (
            f"La FP y la FA se recuperaron cuidadosamente sin tocar la "
            f"interfase con la proteína. Para los análisis de {target_es}, "
            f"la {'FP' if phase=='polar' else 'FA'} {_EVAP_ES} y se "
            f"resuspendió en {recon_es} antes del análisis. {pellet_es}"
        )
        return (
            f"Precipitación bifásica MeOH:CHCl₃ (flujo combinado i). "
            f"{compat_es} {common_steps} {recover_es}"
        )

    # combo_ii — pooled phases
    target_es = "metabolómica" if phase == "polar" else "lipidómica"
    compat_es = (
        "Este protocolo se aplicó en un flujo combinado que permite "
        f"recuperar, a partir de una sola alícuota, las fases polar (FP) y "
        f"apolar (FA) combinadas para {target_es} y el pellet de proteína "
        f"para proteómica."
    )
    recover_es = (
        f"Las fases FP y FA se recuperaron y se combinaron en un mismo "
        f"tubo, {_EVAP_ES_PLURAL} y se resuspendieron en {recon_es} antes "
        f"del análisis. {pellet_es}"
    )
    return (
        f"Precipitación bifásica MeOH:CHCl₃ (flujo combinado ii). "
        f"{compat_es} {common_steps} {recover_es}"
    )


def _build_biphasic_protocol_en(phase: str, vols: dict, recon_en: str,
                                 workflow: str) -> str:
    """English description of the biphasic MeOH:CHCl₃ protocol.

    phase   : 'polar' (metabolomics) | 'apolar' (lipidomics)
    workflow: 'single' | 'combo_i' | 'combo_ii'
    """
    target_full = "Metabolite" if phase == "polar" else "Lipid"

    common_steps = (
        f"Briefly, to {vols['sample']} µL of sample, {vols['meoh']} µL of "
        f"MeOH was added and the mixture was vortexed for 1 min; "
        f"{vols['chcl3']} µL of CHCl₃ was then added and vortexed for 1 "
        f"min; finally, {vols['water']} µL of LC-MS grade water was added "
        f"and the mixture vortexed for 3 min and centrifuged for 2 min at "
        f"15,000 × g, yielding a polar (upper aqueous) phase, an apolar "
        f"(lower organic) phase and a protein interphase."
    )

    if workflow == "single":
        # Single workflow: only one phase is collected — no mention of a
        # combined workflow with proteomics (the lab is NOT doing it).
        if phase == "polar":
            compat_en = (
                "Metabolite extraction was performed using a biphasic "
                "MeOH:CHCl₃ precipitation."
            )
            recover_en = (
                f"The polar phase (PP) was carefully collected without "
                f"disturbing the other phases, {_EVAP_EN} and reconstituted "
                f"in {recon_en} prior to analysis."
            )
        else:
            compat_en = (
                "Lipid extraction was performed using a biphasic "
                "MeOH:CHCl₃ precipitation."
            )
            recover_en = (
                f"The upper aqueous phase was discarded without disturbing "
                f"the remaining phases, and the apolar (lower organic) "
                f"phase (AP) was carefully collected, {_EVAP_EN} and "
                f"reconstituted in {recon_en} prior to analysis."
            )
        return f"{compat_en} {common_steps} {recover_en}"

    pellet_en = (
        "To recover the protein pellet, after collecting the desired "
        "phases, 400 µL of MeOH is added, the mixture is vortexed for 1 "
        "min and centrifuged for 3 min at 15,000 × g; the supernatant is "
        "then discarded without disturbing the pellet."
    )

    if workflow == "combo_i":
        target_en = "metabolomics" if phase == "polar" else "lipidomics"
        phase_lbl = "PP" if phase == "polar" else "AP"
        compat_en = (
            f"{target_full} extraction was performed using a biphasic "
            f"MeOH:CHCl₃ precipitation in a combined workflow that recovers, "
            f"from a single sample aliquot, the polar phase (PP) for "
            f"metabolomics, the apolar phase (AP) for lipidomics and the "
            f"protein pellet for proteomics."
        )
        recover_en = (
            f"Both PP and AP were carefully collected without disturbing "
            f"the protein interphase. For {target_en}, the {phase_lbl} was "
            f"{_EVAP_EN} and reconstituted in {recon_en} prior to analysis. "
            f"{pellet_en}"
        )
        return f"{compat_en} {common_steps} {recover_en}"

    # combo_ii — pooled phases
    target_en = "metabolomics" if phase == "polar" else "lipidomics"
    compat_en = (
        f"{target_full} extraction was performed using a biphasic "
        f"MeOH:CHCl₃ precipitation in a combined workflow that recovers, "
        f"from a single sample aliquot, the polar (PP) and apolar (AP) "
        f"phases pooled for {target_en} and the protein pellet for "
        f"proteomics."
    )
    recover_en = (
        f"The PP and AP phases were collected and pooled in a single "
        f"tube, {_EVAP_EN} and reconstituted in {recon_en} prior to "
        f"analysis. {pellet_en}"
    )
    return f"{compat_en} {common_steps} {recover_en}"

MM_LC_META = """Liquid chromatography
LC separation was performed using an Elute UHPLC system (Bruker Daltonics, Germany) with mobile phase A (water) and mobile phase B (acetonitrile, ACN), both containing 0.1% FA. The LC gradient consisted of a 30-minute runtime, including column washing, as follows: T0–T2: 99% A/1% B; T2–T17: 1% A/99% B; T17–T20: 99% B/1% A; T20–T20.10: flow increased to 0.35 mL/min, transitioning to 1% B/99% A; T20.10–T28.30: 1% B/99% A; T28.30–T30: flow returned to 0.25 mL/min. The autosampler was maintained at 4 °C. Samples were injected using the µL pickup mode with a 5 µL injection volume. Separation was performed on a T-ReX Elute M-column Kit (Bruker Daltonics, Germany), comprising an Intensity Solo HPLC Column C18 (100 × 2 mm, 2 µm) coupled to a VanGuard pre-column, thermostated at 35 °C."""

MM_LC_LIPO = """Liquid chromatography
LC separation was performed using an Elute UHPLC system (Bruker Daltonics, Germany) with mobile phase A (ACN:H₂O 60:40) and mobile phase B (IPA:ACN:H₂O 85:10:5), both containing 0.1% FA and 10 mM ammonium formate. The LC gradient consisted of a 20-minute runtime: T0: 60% A/40% B; T0–T2: 57% A/43% B; T2–T2.10: 50% A/50% B; T2.10–T12: 46% A/54% B; T12–T12.10: 30% A/70% B; T12.10–T15: 1% A/99% B; T15–T18.10: 60% A/40% B; T18.10–T20: 60% A/40% B. The autosampler was maintained at 4 °C. Samples were injected using the µL pickup mode with a 5 µL injection volume. Separation was performed on an Acquity PRM BEH C18 1.7 µm, 2.1 × 100 mm column coupled to an AQTY PRM BEH C18 1.7 µm, 2.1 × 5 mm pre-column (Waters Cromatografía, S.A., Barcelona, Spain), thermostated at 55 °C."""

MM_MS_META = """MS acquisition: 4D PASEF
4D PASEF experiments were conducted using a TIMS-TOF Pro instrument (Bruker Daltonics, Germany) in {polarity_ion} ion mode. Instrument parameters were as follows: end plate offset 500 V; capillary voltage 3,500 V; dry gas (N₂) flow 8 L/min at 240 °C; nebulizer gas 2.5 bar; peak detection threshold 100 counts; PASEF scan mode, mass range 20–1,300 Da for MS and MS²; acquisition cycle 0.1 s, mobility range 0.45–1.45 Vs/cm² (positive mode) and 0.45–1.30 Vs/cm² (negative mode); collision energy 10 eV. TIMS and mass calibration were performed weekly using the Agilent ESI LC-MS tuning mix. Online recalibration was performed immediately after each sample using a mixture of Agilent ESI LC-MS tune mix and 10 mM sodium formate (1:1), injected via a syringe pump."""

MM_MS_LIPO = """MS acquisition: 4D PASEF
4D PASEF experiments were conducted using a TIMS-TOF Pro instrument coupled to a VIP-HESI source (Bruker Daltonics, Germany) in {polarity_ion} ion mode. Instrument parameters were as follows: end plate offset 500 V; capillary voltage 4,500 V; dry gas (N₂) at 8 L/min at 230 °C; nebulizer gas 2 bar; peak detection threshold 100 counts; PASEF scan mode, mass range 100–1,350 Da for MS and MS²; acquisition cycle 0.1 s, mobility range 0.55–1.90 Vs/cm²; collision energy 10 eV. TIMS and mass calibration were performed weekly using the Agilent ESI LC-MS tuning mix. Online recalibration was performed immediately after each sample using a mixture of Agilent ESI LC-MS tune mix and 1 mM sodium formate (1:1), injected directly into the ESI source via a syringe pump."""

def _mm_processing_en(tipo, polaridad, r2, modo_filtrado, dil_levels,
                       allow2pt, use_drop, ion_sup, usar_cv, cv_thr, qc_name):
    """Genera la sección Data Processing en inglés, con descripción fiel del Aletheia."""
    sw = "Bruker Compass MetaboScape 2026 v16.0.6" if tipo == "meta" else "Bruker Compass MetaboScape 2026 v16.0.6"
    pol = polaridad.lower()
    dil_str = dil_levels.strip() if dil_levels else "20%, 40%, 60%, 80%, and 100%"

    # Descripción de la lógica de filtrado de linealidad
    strategies = ("For each feature, all possible aggregation strategies for replicate injections "
                  "per dilution level were evaluated (first, second, third injection, and mean), "
                  "with and without excluding the lowest dilution point (drop-lowest strategy). ")
    drop_txt = ("The combination yielding the highest coefficient of determination (R²) "
                "among those with a positive slope was selected. ") if use_drop else (
                "The combination yielding the highest R² with a positive slope was selected. ")
    two_pt = ("For features with exactly two valid dilution points, a simplified criterion was applied: "
              "acceptance was granted if the slope was positive, without requiring a minimum R², "
              "since with two points the fit is perfect by definition. ") if allow2pt else ""
    is_txt = ("Features with a negative slope but R² ≥ threshold were flagged as potential "
              "ion suppression candidates and retained with an 'ion_suppression' label. ") if ion_sup else ""

    cv_section = ""
    if usar_cv:
        cv_section = (
            f" Additionally, a repeatability filter was applied: only features with a "
            f"coefficient of variation (%CV) across injection replicates ≤ {cv_thr}% were retained. "
            f"Injection replicates were first screened for global failure (both total intensity sum "
            f"and median intensity below 70% of the replicate median), and metabolite-level outliers "
            f"(|Z-score| > 2) were excluded before averaging. The aggregated table "
            f"(experiment_aggregated.csv) represents the mean of valid replicates per sample, "
            f"ready for downstream multivariate analysis."
        )

    return f"""Data processing and statistical evaluation
Initial data evaluation was carried out using DataAnalysis 6.1 (Bruker Daltonics). Untargeted data processing was performed in {sw} (Bruker Daltonics) using the T-ReX algorithm for mass calibration, peak picking, time alignment, and within-batch correction. All samples were analysed in triplicate with randomised injection order. Pooled quality control ({qc_name}) samples, prepared as an equimolar pool of all study samples, were injected every 10 samples to enable signal normalisation and drift correction. Missing values were addressed using the T-ReX automatic region complete extraction algorithm, which re-extracts features below the detection threshold in a targeted manner. Only features detected in all {qc_name} samples were retained for further analysis.

Serial dilutions of the {qc_name} sample ({dil_str} of the original concentration) were used to evaluate the linearity of the instrument response for each detected feature, using a custom quality-control pipeline (Aletheia, ECAI IMSMI, IMIBIC). {strategies}{drop_txt}Only features with a positive slope and R² ≥ {r2} in {pol} mode were retained, ensuring that only analytically reliable signals were considered for downstream analysis. {two_pt}{is_txt}{cv_section}"""

# =============================================================================
# LAYOUT
# =============================================================================

def layout():
    return html.Div([
        html.Div(className="page-header", children=[
            html.H1("Generador de Informe — Metabolómica / Lipidómica", className="page-title"),
            html.P("Correo de entrega · Materiales y Métodos (EN) · 4D-PASEF",
                   className="page-sub"),
        ]),

        _card("① Tipo de análisis y polaridad", [
            html.Div(style={"display":"flex","gap":"2rem","flexWrap":"wrap"}, children=[
                html.Div([
                    _lbl("Tipo de análisis"),
                    dcc.RadioItems(id="inf-tipo",
                        options=[{"label":" Metabolómica","value":"meta"},
                                 {"label":" Lipidómica",  "value":"lipo"}],
                        value="meta",
                        style={"display":"flex","gap":"1.5rem","fontSize":"13px"}),
                ]),
                html.Div([
                    _lbl("Polaridad analizada"),
                    dcc.RadioItems(id="inf-polaridad",
                        options=[{"label":" Negativa","value":"negativa"},
                                 {"label":" Positiva", "value":"positiva"},
                                 {"label":" Ambas",    "value":"ambas"}],
                        value="ambas",
                        style={"display":"flex","gap":"1.5rem","fontSize":"13px"}),
                ]),
            ]),
        ]),

        # Datalists for autocomplete suggestions (populated by callback)
        html.Datalist(id="dl-inf-dest",     children=[]),
        html.Datalist(id="dl-inf-codigo",   children=[]),
        html.Datalist(id="dl-inf-sorg",     children=[]),
        html.Datalist(id="dl-inf-muestra",  children=[]),
        html.Datalist(id="dl-inf-ftp-user", children=[]),
        html.Datalist(id="dl-inf-ftp-pass", children=[]),

        _card("② Datos del experimento", [
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr 1fr","gap":"1rem"}, children=[
                html.Div([_lbl("Código de solicitud"),
                          dcc.Input(id="inf-codigo", type="text", placeholder="SOL2026XXX",
                                    debounce=False,
                                    **{"list": "dl-inf-codigo"},
                                    style=_inp())]),
                html.Div([_lbl("Destinatario"),
                          dcc.Input(id="inf-dest", type="text",
                                    placeholder="Nombre del investigador",
                                    debounce=False,
                                    **{"list": "dl-inf-dest"},
                                    style=_inp())]),
                html.Div([_lbl("Organismo"),
                          dcc.Input(id="inf-sorg", type="text",
                                    placeholder="ej. Homo sapiens, Mus musculus",
                                    debounce=False,
                                    **{"list": "dl-inf-sorg"},
                                    style=_inp())]),
                html.Div([_lbl("Categoría de muestra"),
                          dcc.Dropdown(id="inf-scat",
                              options=_SCAT_OPTIONS_INF,
                              placeholder="Seleccionar categoría…",
                              clearable=True,
                              style={"fontFamily":"monospace","fontSize":"12px"})]),
                html.Div([_lbl("Tipo / subtipo de muestra"),
                          dcc.Input(id="inf-muestra", type="text",
                                    placeholder="ej. serum, urine, liver",
                                    debounce=False,
                                    **{"list": "dl-inf-muestra"},
                                    style=_inp())]),
                html.Div([_lbl("Nº muestras"),
                          dcc.Input(id="inf-n-muestras", type="number", value=15, min=1,
                                    style=_inp())]),
                html.Div([_lbl("Nº réplicas de inyección"),
                          dcc.Input(id="inf-n-replicas", type="number", value=3, min=1,
                                    style=_inp())]),
                html.Div([_lbl("Nombre del QC pool"),
                          dcc.Input(id="inf-qc-name", type="text", value="QC",
                                    style=_inp())]),
            ]),
        ]),

        _card("③ Parámetros del Aletheia", [
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr 1fr 1fr","gap":"1rem"}, children=[
                html.Div([_lbl("Umbral R²"),
                          dcc.Input(id="inf-r2", type="number", value=0.65,
                                    min=0.1, max=1.0, step=0.01, style=_inp())]),
                html.Div([_lbl("Niveles de dilución QC"),
                          dcc.Input(id="inf-dil-levels", type="text",
                                    value="20%, 40%, 60%, 80%, 100%",
                                    style=_inp())]),
                html.Div([_lbl("Modo de filtrado"),
                          dcc.RadioItems(id="inf-modo-filtrado",
                              options=[{"label":" Linealidad + CV","value":"combinado"},
                                       {"label":" Solo linealidad","value":"linealidad"}],
                              value="combinado",
                              style={"fontSize":"12px","display":"flex","flexDirection":"column","gap":"4px"})]),
                html.Div([_lbl("Umbral %CV (si aplica)"),
                          dcc.Input(id="inf-cv-thr", type="number", value=20,
                                    min=5, max=50, style=_inp())]),
            ]),
            html.Div(style={"marginTop":"1rem","display":"flex","gap":"2rem"}, children=[
                html.Div([_lbl("Opciones aplicadas"),
                          dcc.Checklist(id="inf-opts",
                              options=[{"label":" Drop lowest","value":"drop"},
                                       {"label":" 2 puntos → aceptar","value":"a2p"},
                                       {"label":" Ion suppression","value":"ionsup"}],
                              value=["drop","a2p"],
                              style={"fontSize":"12px","display":"flex","gap":"1rem"})]),
            ]),
        ]),

        _card("④ Preparación de muestra", [
            html.Div(id="inf-proto-container"),

            # ── Parámetros específicos del protocolo bifásico MeOH:CHCl₃ ──
            # Sólo visible cuando el usuario marca meoh_chcl3_polar o
            # meoh_chcl3_apolar; se muestra/oculta vía callback.
            html.Div(id="inf-biphasic-options",
                     style={"marginTop": "1rem", "display": "none",
                            "padding": "10px 12px", "background": "#F7F6F2",
                            "borderRadius": "8px",
                            "border": "1px solid #E4E2DC"},
                     children=[
                html.Div("Parámetros del protocolo bifásico MeOH:CHCl₃",
                         style={"fontSize": "11px", "fontWeight": "600",
                                "color": "#4A9B8F", "marginBottom": "0.6rem",
                                "letterSpacing": ".05em",
                                "textTransform": "uppercase",
                                "fontFamily": "monospace"}),
                html.Div(style={"display": "grid",
                                 "gridTemplateColumns": "1fr 1fr 1fr",
                                 "gap": "1rem"}, children=[
                    html.Div([
                        _lbl("Volumen inicial muestra (µL)"),
                        dcc.Input(id="inf-biphasic-vol", type="number",
                                  value=100, min=1, step=1, style=_inp()),
                        html.Div("MeOH ×4 · CHCl₃ ×1 · H₂O ×3 (sobre el "
                                 "volumen indicado)",
                                 style={"fontSize": "10px",
                                         "color": "#888780",
                                         "marginTop": "4px",
                                         "fontFamily": "monospace"}),
                    ]),
                    html.Div([
                        _lbl("Disolvente reconstitución"),
                        dcc.Dropdown(id="inf-recon-solvent",
                            options=[{"label": "MeOH",     "value": "MeOH"},
                                     {"label": "IPA",      "value": "IPA"},
                                     {"label": "MeOH:IPA", "value": "MeOH:IPA"}],
                            value="MeOH",
                            clearable=False,
                            style={"fontFamily": "monospace",
                                    "fontSize": "12px"}),
                    ]),
                    html.Div([
                        _lbl("Volumen reconstitución (µL)"),
                        dcc.Input(id="inf-recon-vol", type="number",
                                  value=100, min=1, step=1, style=_inp()),
                    ]),
                ]),
                html.Div(style={"marginTop": "0.8rem"}, children=[
                    _lbl("Flujo combinado con proteómica"),
                    dcc.RadioItems(id="inf-workflow",
                        options=[
                            {"label": " Solo metabolómica/lipidómica "
                                       "(una sola fase recuperada)",
                             "value": "single"},
                            {"label": " Combinado i — FP → metabolómica · "
                                       "FA → lipidómica · pellet → proteómica",
                             "value": "combo_i"},
                            {"label": " Combinado ii — FP + FA juntas → "
                                       "metabolómica o lipidómica · "
                                       "pellet → proteómica",
                             "value": "combo_ii"},
                        ],
                        value="single",
                        style={"fontSize": "12px", "display": "flex",
                                "flexDirection": "column", "gap": "4px"}),
                ]),
            ]),

            html.Div(style={"marginTop":"1rem"}, children=[
                _lbl("Variaciones o detalles adicionales (opcional)"),
                dcc.Textarea(id="inf-proto-extra",
                             placeholder="Describe aquí cualquier modificación del protocolo estándar, "
                             "volúmenes específicos, tiempos de incubación, etc.",
                             style={"width":"100%","height":"70px","fontFamily":"monospace",
                                    "fontSize":"11px","padding":"8px","border":"1px solid #E4E2DC",
                                    "borderRadius":"6px","resize":"vertical","boxSizing":"border-box"}),
            ]),
        ]),

        _card("⑤ Análisis alternativo (exclusión de réplicas)", [
            html.Div(style={"display":"grid","gridTemplateColumns":"auto 1fr","gap":"1rem",
                             "alignItems":"flex-start"}, children=[
                html.Div([
                    dcc.Checklist(id="inf-alt-on",
                        options=[{"label":" Se ha aplicado análisis alternativo",
                                  "value":"on"}],
                        value=[], style={"fontSize":"13px"}),
                ]),
                html.Div(id="inf-alt-extra-wrap", style={"display":"none"}, children=[
                    html.Div(style={"display":"grid",
                                     "gridTemplateColumns":"1.4fr 1fr 1fr 1fr",
                                     "gap":"1rem","marginBottom":"0.6rem"}, children=[
                        html.Div([_lbl("Modo de exclusión aplicado"),
                                  dcc.RadioItems(id="inf-alt-mode",
                                      options=[
                                          {"label":" Solo fallos confirmados",
                                           "value":"fail"},
                                          {"label":" Fallos + sospechosas",
                                           "value":"fail_suspect"},
                                          {"label":" Manual",
                                           "value":"manual"},
                                      ],
                                      value="fail",
                                      style={"fontSize":"12px","display":"flex",
                                              "flexDirection":"column","gap":"4px"})]),
                        html.Div([_lbl("Réplicas excluidas"),
                                  dcc.Input(id="inf-alt-n-excluded", type="number",
                                            value=0, min=0, style=_inp())]),
                        html.Div([_lbl("n efectivo mín."),
                                  dcc.Input(id="inf-alt-n-min", type="number",
                                            value=2, min=1, style=_inp())]),
                        html.Div([_lbl("n efectivo máx."),
                                  dcc.Input(id="inf-alt-n-max", type="number",
                                            value=3, min=1, style=_inp())]),
                    ]),
                    html.Div([
                        _lbl("Muestras sin réplicas válidas tras exclusión (opcional)"),
                        dcc.Input(id="inf-alt-samples-dropped", type="text",
                                  placeholder="ej. S3, S7 — déjalo vacío si no hay ninguna",
                                  debounce=False, style=_inp()),
                    ]),
                ]),
            ]),
        ]),

        _card("⑥ Archivos entregados", [
            html.Div(id="inf-archivos-container"),
        ]),

        _card("⑦ Entrega y firma", [
            html.Div(style={"display":"grid","gridTemplateColumns":"1fr 1fr 1fr 1fr","gap":"1rem"}, children=[
                html.Div([_lbl("Usuario FTP"),
                          dcc.Input(id="inf-ftp-user", type="text",
                                    placeholder="usuario",
                                    debounce=False,
                                    autoComplete="off",
                                    **{"list": "dl-inf-ftp-user"},
                                    style=_inp())]),
                html.Div([_lbl("Contraseña FTP"),
                          dcc.Input(id="inf-ftp-pass", type="text",
                                    placeholder="contraseña",
                                    debounce=False,
                                    autoComplete="off",
                                    **{"list": "dl-inf-ftp-pass"},
                                    style=_inp())]),
                html.Div([_lbl("Nombre firmante"),
                          dcc.Input(id="inf-firmante", type="text",
                                    value="Ángela Peralbo Molina, PhD",
                                    style=_inp())]),
                html.Div([_lbl("Cargo firmante"),
                          dcc.Input(id="inf-cargo", type="text",
                                    value="Unidad de Espectrometría de Masas · IMIBIC",
                                    style=_inp())]),
            ]),
        ]),

        html.Div(style={"textAlign":"center","marginBottom":"1.5rem"}, children=[
            html.Button("⚡ Generar informe y M&M", id="inf-generar",
                        className="btn-primary",
                        style={"fontSize":"14px","padding":"12px 40px"}),
        ]),

        html.Div(id="inf-resultado"),

        dcc.Store(id="inf-texts-store", data={}),
        dcc.Download(id="inf-download-docx"),
    ])

# =============================================================================
# HELPERS
# =============================================================================

def _card(title, children):
    return html.Div(className="card", style={"marginBottom":"1.2rem"}, children=[
        html.Div(title, className="card-title"),
        *children,
    ])

def _lbl(text):
    return html.Div(text, style={"fontSize":"10px","fontWeight":"600","letterSpacing":".07em",
                                  "textTransform":"uppercase","color":"#888780",
                                  "fontFamily":"monospace","marginBottom":"4px"})

def _inp():
    return {"width":"100%","fontFamily":"monospace","fontSize":"12px","padding":"7px 10px",
            "border":"1px solid #E4E2DC","borderRadius":"6px","boxSizing":"border-box"}

def _copy_btn(btn_id, label, color="#2C2C2A"):
    return html.Button(label, id=btn_id,
                       style={"background":color,"color":"#fff","border":"none",
                              "padding":"6px 14px","borderRadius":"6px","cursor":"pointer",
                              "fontSize":"11px","fontFamily":"monospace"})

def _text_box(content, box_id):
    return html.Pre(content, id=box_id,
                    style={"fontFamily":"monospace","fontSize":"11px","whiteSpace":"pre-wrap",
                           "background":"#F7F6F2","padding":"1.2rem","borderRadius":"8px",
                           "lineHeight":"1.7","margin":"0","maxHeight":"550px","overflowY":"auto"})

# =============================================================================
# CALLBACKS
# =============================================================================

@callback(Output("inf-proto-container","children"),
          Input("inf-tipo","value"))
def update_protocols(tipo):
    protos = PROTOCOLOS_META if tipo == "meta" else PROTOCOLOS_LIPO
    return [
        html.Div(style={"display":"flex","alignItems":"flex-start","gap":"8px","marginBottom":"6px"},
                 children=[
            dcc.Checklist(id={"type":"proto-check","index":key},
                options=[{"label":"","value":key}], value=[],
                style={"marginTop":"2px"}),
            html.Div(label, style={"fontSize":"13px","color":"#2C2C2A"}),
        ])
        for key, label in protos.items()
    ]


@callback(
    Output("dl-inf-dest",     "children"),
    Output("dl-inf-codigo",   "children"),
    Output("dl-inf-sorg",     "children"),
    Output("dl-inf-muestra",  "children"),
    Output("dl-inf-ftp-user", "children"),
    Output("dl-inf-ftp-pass", "children"),
    Input("inf-generar", "n_clicks"),
    prevent_initial_call=False,
)
def _refresh_inf_datalists(_n):
    """Populate datalist suggestion options (fires on load + after each generation)."""
    def _opts(vals): return [html.Option(value=v) for v in vals]
    return (
        _opts(_sh.get_all_users()),
        _opts(_sh.get_unique_values("sol")),
        _opts(_sh.get_unique_values("sorg")),
        _opts(_sh.get_unique_values("ssub")),
        _opts(_sh.get_unique_values("ftp_user")),
        _opts(_sh.get_unique_values("ftp_pass")),
    )


@callback(Output("inf-alt-extra-wrap", "style"),
          Input("inf-alt-on", "value"))
def _toggle_alt_extra(alt_on):
    on = bool(alt_on) and "on" in (alt_on or [])
    return {"display": "block"} if on else {"display": "none"}


@callback(Output("inf-biphasic-options", "style"),
          Input({"type": "proto-check", "index": ALL}, "value"),
          State({"type": "proto-check", "index": ALL}, "id"))
def _toggle_biphasic_options(proto_vals, proto_ids):
    """Show the MeOH:CHCl₃ parameters block only when one of the two
    biphasic protocols (polar / apolar) is checked."""
    base = {"marginTop": "1rem",
            "padding": "10px 12px",
            "background": "#F7F6F2",
            "borderRadius": "8px",
            "border": "1px solid #E4E2DC"}
    show = False
    for v, pid in zip(proto_vals or [], proto_ids or []):
        if v and pid.get("index") in {"meoh_chcl3_polar", "meoh_chcl3_apolar"}:
            show = True
            break
    return {**base, "display": "block" if show else "none"}


@callback(Output("inf-recon-solvent", "value"),
          Input("inf-tipo", "value"),
          prevent_initial_call=False)
def _default_recon_solvent(tipo):
    """Default reconstitution solvent: MeOH for metabolomics, IPA for lipidomics."""
    return "MeOH" if tipo == "meta" else "IPA"


@callback(Output("inf-archivos-container","children"),
          Input("inf-tipo","value"),
          Input("inf-modo-filtrado","value"),
          Input("inf-alt-on","value"))
def update_archivos(tipo, modo, alt_on):
    default = {"raw","complete","filtered","aggregated","good_coor","bad_coor","qcr","pdf"}
    if modo == "combinado":
        default |= {"cv","combined","pass_all"}

    alt_on = bool(alt_on) and "on" in (alt_on or [])
    files = list(ARCHIVOS_BASE)
    if alt_on:
        files = files + list(ARCHIVOS_ALT)
        default |= {k for k, *_ in ARCHIVOS_ALT}

    return [
        html.Div(style={"display":"flex","alignItems":"flex-start","gap":"8px","marginBottom":"8px",
                         "padding":"8px","background":"#F7F6F2","borderRadius":"6px"}, children=[
            dcc.Checklist(id={"type":"arch-check","index":key},
                options=[{"label":"","value":key}], value=[key] if key in default else [],
                style={"marginTop":"2px","flexShrink":"0"}),
            html.Div([
                html.Div(nombre, style={"fontSize":"12px","fontWeight":"600",
                                         "color":"#2C2C2A","fontFamily":"monospace"}),
                html.Div(desc,   style={"fontSize":"11px","color":"#888780","marginTop":"2px",
                                         "lineHeight":"1.4"}),
            ]),
        ])
        for key, nombre, desc in files
    ]


@callback(Output("inf-resultado","children"),
          Output("inf-texts-store","data"),
          Input("inf-generar","n_clicks"),
          State("inf-tipo","value"),
          State("inf-polaridad","value"),
          State("inf-codigo","value"),
          State("inf-dest","value"),
          State("inf-scat","value"),
          State("inf-sorg","value"),
          State("inf-muestra","value"),
          State("inf-n-muestras","value"),
          State("inf-n-replicas","value"),
          State("inf-qc-name","value"),
          State("inf-r2","value"),
          State("inf-dil-levels","value"),
          State("inf-modo-filtrado","value"),
          State("inf-cv-thr","value"),
          State("inf-opts","value"),
          State({"type":"proto-check","index":ALL},"value"),
          State({"type":"arch-check","index":ALL},"value"),
          State({"type":"proto-check","index":ALL},"id"),
          State({"type":"arch-check","index":ALL},"id"),
          State("inf-proto-extra","value"),
          State("inf-ftp-user","value"),
          State("inf-ftp-pass","value"),
          State("inf-firmante","value"),
          State("inf-cargo","value"),
          State("inf-alt-on","value"),
          State("inf-alt-mode","value"),
          State("inf-alt-n-excluded","value"),
          State("inf-alt-n-min","value"),
          State("inf-alt-n-max","value"),
          State("inf-alt-samples-dropped","value"),
          State("inf-biphasic-vol","value"),
          State("inf-recon-solvent","value"),
          State("inf-recon-vol","value"),
          State("inf-workflow","value"),
          prevent_initial_call=True)
def generar(_, tipo, polaridad, codigo, dest,
            scat, sorg, muestra,
            n_muestras, n_replicas, qc_name,
            r2, dil_levels, modo_filtrado, cv_thr, opts,
            proto_vals, arch_vals, proto_ids, arch_ids,
            proto_extra, ftp_user, ftp_pass, firmante, cargo,
            alt_on, alt_mode, alt_n_excluded, alt_n_min, alt_n_max,
            alt_samples_dropped,
            biphasic_vol, recon_solvent, recon_vol, workflow):

    opts = opts or []
    use_drop = "drop"   in opts
    allow2pt = "a2p"    in opts
    ion_sup  = "ionsup" in opts
    usar_cv  = modo_filtrado == "combinado"
    alt_on   = bool(alt_on) and "on" in (alt_on or [])

    # Translate sample type for correo body (keep original for registry)
    muestra_es = _translate_sample(muestra or "") or muestra or ""

    # ── Protocolos seleccionados ──
    protos_all = PROTOCOLOS_META if tipo == "meta" else PROTOCOLOS_LIPO
    protos_sel = [protos_all[pid["index"]] for val, pid in zip(proto_vals, proto_ids) if val]

    # ── Archivos seleccionados ──
    arch_dict = {a[0]: a for a in (list(ARCHIVOS_BASE) + list(ARCHIVOS_ALT))}
    archivos_sel = [arch_dict[aid["index"]] for val, aid in zip(arch_vals, arch_ids)
                    if val and aid["index"] in arch_dict]

    # ── Textos de polaridad ──
    pol_map = {
        "negativa": ("negativa", "en modo negativo",  "negative", "negative",  "negative"),
        "positiva": ("positiva", "en modo positivo",  "positive", "positive",  "positive"),
        "ambas":    ("positiva y negativa", "en modos positivo y negativo",
                     "positive and negative", "positive and negative", "positive and negative"),
    }
    pol_es, pol_es_long, pol_en, pol_en_ion, pol_en_modo = pol_map[polaridad]

    tipo_str    = "metabolómica no dirigida" if tipo=="meta" else "lipidómica no dirigida"
    tipo_str_en = "untargeted metabolomics"  if tipo=="meta" else "untargeted lipidomics"
    entidad     = "metabolitos"              if tipo=="meta" else "lípidos"

    # ── Saludo según hora ──
    hora = datetime.datetime.now().hour
    saludo = "Buenos días" if hora < 14 else ("Buenas tardes" if hora < 21 else "Buenas noches")

    # ── Volúmenes y reconstitución para el protocolo bifásico MeOH:CHCl₃ ──
    # _scale_biphasic devuelve los volúmenes escalados linealmente desde la
    # receta de referencia (100 µL muestra → 400 MeOH / 100 CHCl₃ / 300 H₂O).
    _biphasic_vols = _scale_biphasic(biphasic_vol)
    _recon_es, _recon_en = _recon_label(recon_solvent, recon_vol)
    _workflow = workflow if workflow in {"single", "combo_i", "combo_ii"} else "single"

    # ── Preparación de muestra (correo, ES) ──
    proto_es_map = {
        "meoh_1_3": (
            "Precipitación de proteínas con metanol (MeOH) frío en proporción 1:3 (v/v "
            "muestra:disolvente). Las muestras se descongelaron en hielo. En un tubo "
            "correctamente etiquetado, mantenido a 4 °C, se añadieron 150 µL de MeOH a "
            "50 µL de suero. La mezcla se vorteó 30 s a 1.200 rpm y se incubó 15 min a "
            "4 °C. Se centrifugó 10 min a 6.168 × g y 10 °C, el sobrenadante se transfirió "
            "a un tubo nuevo a 4 °C, se vorteó 30 s a 1.200 rpm y se centrifugó de nuevo "
            "6 min a 6.168 × g y 10 °C antes del análisis."
        ),
        "meoh_1_6": (
            "Precipitación de proteínas con metanol (MeOH) frío en proporción 1:6 (v/v "
            "muestra:disolvente). Las muestras se descongelaron en hielo. En un tubo "
            "correctamente etiquetado, mantenido a 4 °C, se añadieron 300 µL de MeOH a "
            "50 µL de suero. La mezcla se vorteó 30 s a 1.200 rpm y se incubó 15 min a "
            "4 °C. Se centrifugó 10 min a 6.168 × g y 10 °C, el sobrenadante se transfirió "
            "a un tubo nuevo a 4 °C, se vorteó 30 s a 1.200 rpm y se centrifugó de nuevo "
            "6 min a 6.168 × g y 10 °C antes del análisis."
        ),
        "meoh_chcl3_polar":  _build_biphasic_protocol_es(
            "polar",  _biphasic_vols, _recon_es, _workflow),
        "ipa_1_6": (
            "Precipitación de proteínas con isopropanol (IPA) en proporción 1:6 (v/v "
            "muestra:disolvente). Las muestras se descongelaron en hielo. En un tubo "
            "correctamente etiquetado que contenía 50 µL de suero, se añadieron 300 µL de "
            "IPA a temperatura ambiente. La mezcla se incubó 15 min a temperatura "
            "ambiente y se centrifugó 10 min a 12.000 × g y 10 °C. El sobrenadante se "
            "transfirió a un tubo nuevo y se vorteó (centrifugando de nuevo si fue "
            "necesario) antes del análisis."
        ),
        "mtbe": (
            "Extracción basada en metil-terc-butil éter (MTBE). Tras la "
            "extracción, la fase orgánica se evaporó en un concentrador "
            "centrífugo a vacío Savant SpeedVac (Thermo Scientific) y se "
            "reconstituyó en IPA:MeOH antes de la inyección."
        ),
        "meoh_chcl3_apolar": _build_biphasic_protocol_es(
            "apolar", _biphasic_vols, _recon_es, _workflow),
    }

    _has_meoh_chcl3_es = False
    pp_lines_es = []
    for val, pid in zip(proto_vals, proto_ids):
        if val:
            key = pid["index"]
            if key in proto_es_map:
                pp_lines_es.append(proto_es_map[key])
            if key in {"meoh_chcl3_polar", "meoh_chcl3_apolar"}:
                _has_meoh_chcl3_es = True

    if pp_lines_es:
        # Numbered list of protocols (the combined-workflow text is already
        # embedded inside the biphasic helper when applicable).
        if len(pp_lines_es) == 1:
            pp_body_es = pp_lines_es[0]
        else:
            pp_body_es = "\n\n".join(
                f"• {ln}" for ln in pp_lines_es
            )
        pp_txt_es = (
            "La extracción de {} se realizó según el siguiente protocolo:\n\n{}"
            .format(entidad, pp_body_es)
        )
    else:
        pp_txt_es = ""

    if proto_extra:
        pp_txt_es += ("\n\n" if pp_txt_es else "") + proto_extra.strip()
    if not pp_txt_es:
        pp_txt_es = "(Protocolo de preparación de muestra pendiente de detallar.)"

    # ── Preparación de muestra (M&M, EN) ──
    proto_en_map = {
        "meoh_1_3": (
            "Metabolite extraction was performed by protein precipitation with cold methanol "
            "(MeOH; 1:3 v/v sample:solvent). Briefly, samples were thawed on ice. To a properly "
            "labelled tube kept at 4 °C, 150 µL of MeOH was added to 50 µL of serum. The mixture "
            "was vortexed for 30 s at 1,200 rpm and incubated for 15 min at 4 °C. Samples were "
            "centrifuged for 10 min at 6,168 × g and 10 °C. The supernatant was transferred to a "
            "new tube kept at 4 °C, vortexed for 30 s at 1,200 rpm, and centrifuged again for "
            "6 min at 6,168 × g and 10 °C prior to analysis."
        ),
        "meoh_1_6": (
            "Metabolite extraction was performed by protein precipitation with cold methanol "
            "(MeOH; 1:6 v/v sample:solvent). Briefly, samples were thawed on ice. To a properly "
            "labelled tube kept at 4 °C, 300 µL of MeOH was added to 50 µL of serum. The mixture "
            "was vortexed for 30 s at 1,200 rpm and incubated for 15 min at 4 °C. Samples were "
            "centrifuged for 10 min at 6,168 × g and 10 °C. The supernatant was transferred to a "
            "new tube kept at 4 °C, vortexed for 30 s at 1,200 rpm, and centrifuged again for "
            "6 min at 6,168 × g and 10 °C prior to analysis."
        ),
        "meoh_chcl3_polar":  _build_biphasic_protocol_en(
            "polar",  _biphasic_vols, _recon_en, _workflow),
        "ipa_1_6": (
            "Lipid extraction was performed by protein precipitation with isopropanol (IPA; 1:6 v/v "
            "sample:solvent). Briefly, samples were thawed on ice. To a properly labelled tube "
            "containing 50 µL of serum, 300 µL of IPA was added at room temperature. The mixture "
            "was incubated for 15 min at room temperature and centrifuged for 10 min at 12,000 × g "
            "and 10 °C. The supernatant was transferred to a new tube and vortexed (re-centrifuged "
            "if necessary) prior to analysis."
        ),
        "mtbe": (
            "Lipid extraction was performed using a methyl tert-butyl ether (MTBE)-based protocol. "
            "After extraction, the organic phase was evaporated in a Savant SpeedVac vacuum "
            "concentrator (Thermo Scientific) and reconstituted in IPA:MeOH prior to injection."
        ),
        "meoh_chcl3_apolar": _build_biphasic_protocol_en(
            "apolar", _biphasic_vols, _recon_en, _workflow),
    }

    pp_lines_en = []
    _meoh_chcl3_keys = {"meoh_chcl3_polar", "meoh_chcl3_apolar"}
    _has_meoh_chcl3  = False
    for val, pid in zip(proto_vals, proto_ids):
        if val:
            key = pid["index"]
            if key in proto_en_map:
                pp_lines_en.append(proto_en_map[key])
            if key in _meoh_chcl3_keys:
                _has_meoh_chcl3 = True
    pp_txt_en = " ".join(pp_lines_en)
    if proto_extra:
        pp_txt_en += " " + proto_extra.strip()
    if not pp_txt_en:
        pp_txt_en = "[Sample preparation protocol to be described here.]"

    # ── Sección polaridad correo ──
    pol_desc = ""
    if polaridad == "ambas":
        pol_desc = ("El análisis se ha realizado en polaridad positiva y negativa. "
                    "Las tablas entregadas contienen los features de ambas polaridades combinados "
                    "tras el procesado en MetaboScape.")
    else:
        pol_desc = f"El análisis se ha realizado en polaridad {pol_es}."

    # ── Descripción filtrado linealidad (correo, ES) ──
    dil_str_es = dil_levels.strip() if dil_levels else "20%, 40%, 60%, 80% y 100%"
    lin_desc = (
        f"Para garantizar que solo se reportan entidades moleculares con una respuesta instrumental "
        f"fiable, el {qc_name or 'QC'} se ha analizado en diluciones seriadas (al {dil_str_es} de "
        f"concentración). Para cada {('metabolito' if tipo=='meta' else 'lípido')}, se han evaluado "
        f"todas las combinaciones posibles de estrategia de agregación de réplicas por nivel de "
        f"dilución (primera, segunda, tercera réplica o media), "
        + ("probando también la exclusión del nivel de dilución más bajo, " if use_drop else "")
        + f"y se ha seleccionado la que maximiza el R² con pendiente positiva. "
        + f"Solo se conservan los {entidad} con R² ≥ {r2} y pendiente positiva "
        + f"en polaridad {pol_es}. "
        + (f"Para los {entidad} con exactamente dos puntos válidos en la curva de dilución, "
           f"se aplica un criterio simplificado: se aceptan si la pendiente es positiva. "
           if allow2pt else "")
        + (f"Las entidades con pendiente negativa pero R² ≥ {r2} quedan etiquetadas como "
           f"posible supresión iónica y se entregan en la tabla filtrada con esa indicación. "
           if ion_sup else "")
    )

    # ── Sección CV (correo, ES) ──
    cv_section_es = ""
    if usar_cv:
        cv_section_es = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONTROL DE REPETIBILIDAD Y REPRODUCIBILIDAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Adicionalmente, se ha evaluado la repetibilidad de las réplicas de inyección. En primer lugar, se ha realizado un diagnóstico global de cada réplica comparando su suma total e intensidad mediana con la mediana del conjunto: si ambos criterios caen por debajo del 70% de la mediana se clasifica la réplica como fallo confirmado de inyección y se excluye del cálculo. A continuación, para cada metabolito y muestra, se detectan valores atípicos entre réplicas válidas (|Z-score| > 2). La tabla experiment_aggregated.csv contiene la media de las réplicas válidas por metabolito y muestra, lista para análisis estadístico directo.

Solo se conservan en la lista final los {entidad} con %CV entre réplicas ≤ {cv_thr or 20}%."""

    sec_n = 4 if usar_cv else 3

    # ── Sección análisis alternativo (correo, ES) ──
    alt_section_es = ""
    alt_sec_num    = None
    if alt_on:
        alt_sec_num = sec_n + 1
        sec_n       = alt_sec_num              # siguiente sección = alt + 1
        mode_label  = _ALT_MODE_LABEL.get(alt_mode or "fail",
                                          _ALT_MODE_LABEL["fail"])
        n_exc       = int(alt_n_excluded or 0)
        n_min       = int(alt_n_min or 0) if alt_n_min is not None else None
        n_max       = int(alt_n_max or 0) if alt_n_max is not None else None
        if n_min and n_max and n_min != n_max:
            neff_txt = f"entre {n_min} y {n_max} réplicas válidas por muestra"
        elif n_min:
            neff_txt = f"{n_min} réplicas válidas por muestra"
        else:
            neff_txt = "el número efectivo de réplicas válidas por muestra"

        dropped_txt = ""
        if alt_samples_dropped and alt_samples_dropped.strip():
            dropped_txt = (
                f"Tras la exclusión, las siguientes muestras quedaron sin réplicas válidas y "
                f"no aparecen en los archivos del análisis alternativo: {alt_samples_dropped.strip()}. "
                f"El resto de muestras conservan al menos una réplica. "
            )

        alt_section_es = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{alt_sec_num}. ANÁLISIS ALTERNATIVO — EXCLUSIÓN DE RÉPLICAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Dado que el control de calidad ha señalado inyecciones problemáticas, adicionalmente al análisis principal se ha ejecutado un análisis alternativo excluyendo {mode_label} (en total, {n_exc} réplica{'s' if n_exc != 1 else ''}). El pipeline completo (diagnóstico de réplicas, filtrado por linealidad R² y filtrado por CV) se ha vuelto a ejecutar sobre el subconjunto de réplicas válidas, trabajando con {neff_txt}. {dropped_txt}

No se ha aplicado ningún método de imputación (p. ej. sustituir la réplica fallida por la media de las válidas), ya que esta práctica infla artificialmente la significación estadística: la desviación estándar de tres valores donde uno es la media de los otros dos es exactamente √((n-1)/n) veces la de los dos valores reales (≈ 0.82 para n = 3). En línea con las recomendaciones de los consorcios mQACC, MSI y Lipidomics Standards Initiative, se trabaja con el n efectivo por muestra y se propaga la incertidumbre correctamente.

Los archivos del análisis alternativo se entregan con el sufijo `_ALT` (p. ej. experiment_filtered_ALT.csv) y pueden utilizarse en paralelo al análisis principal: si los resultados son consistentes entre ambos, la interpretación biológica es robusta; si difieren notablemente en alguna entidad concreta, conviene revisar esa entidad con detalle antes de incluirla en las conclusiones. El listado exacto de réplicas excluidas, con el nombre CSV original completo de cada una, está en excluded_replicas_ALT.csv."""
    # ── Archivos entregados (correo) ──
    file_rows = ""
    for i, (key, nombre, desc) in enumerate(archivos_sel, 1):
        nombre_r = nombre.replace("{codigo}", codigo or "SOL2026XXX").replace("{r2}", str(r2))
        desc_r   = desc.replace("{r2}", str(r2)).replace("{codigo}", codigo or "SOL2026XXX")
        file_rows += f"\n{'─'*40}\n{i}. {nombre_r}\n{desc_r}\n"

    # ── Columnas ──
    cv_col_desc = ""
    if usar_cv:
        cv_col_desc = ("\n• CV_S[N]: coeficiente de variación (%) de cada metabolito calculado "
                       "sobre las réplicas de inyección de la muestra N.\n"
                       "• CV_median: mediana del %CV entre todas las muestras.\n"
                       "• pass_both: indica si el metabolito supera simultáneamente el filtro "
                       "de linealidad y el de repetibilidad.")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # CORREO (ES)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    correo = f"""{saludo} {dest or '[Destinatario]'},

Le comunicamos que los resultados del análisis de {tipo_str} al que se han sometido sus muestras{(' de ' + muestra_es) if muestra_es else ''} ya están disponibles en nuestro servidor. A continuación le detallamos el contenido de cada archivo y las consideraciones metodológicas relevantes para su correcta interpretación.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. PREPARACIÓN DE MUESTRA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{pp_txt_es}


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. DISEÑO EXPERIMENTAL Y CONTROL DE CALIDAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

El análisis se ha realizado por triplicado para cada muestra{(' de ' + muestra_es) if muestra_es else ''}, con el orden de inyección aleatorizado. A lo largo de la secuencia de inyección se han intercalado muestras de control de calidad ({qc_name or 'QC'}), preparadas como un pool equimolar de todas las muestras del experimento. Estas muestras cumplen una doble función: permiten normalizar los datos finales corrigiendo la deriva instrumental a lo largo de la secuencia; y sirven como base para el filtrado por linealidad descrito a continuación.

{pol_desc}


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. FILTRADO POR LINEALIDAD DE DILUCIONES (ALETHEIA)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{lin_desc}
La recomendación es trabajar con los datos filtrados (experiment_filtered.csv o experiment_aggregated.csv). No obstante, la tabla completa sin filtrar también se entrega para que, si en algún análisis posterior necesita ampliar el número de entidades disponibles, pueda hacerlo relajando estos criterios.
{cv_section_es}{alt_section_es}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sec_n + 1}. ARCHIVOS ENTREGADOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{file_rows if file_rows else '(Ningún archivo seleccionado)'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sec_n + 2}. DESCRIPCIÓN DE LAS COLUMNAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Bucket label: identificador asignado por el software a cada entidad molecular, combinando masa exacta (Da) y tiempo de retención (s).
• RT: tiempo de retención en minutos.
• m/z: relación masa/carga.
• Name: nombre del metabolito/lípido para los identificados automáticamente mediante las bases de datos del ECAI.
• Formula: fórmula molecular calculada.
• Columnas de muestra: cada columna corresponde a una muestra o control, nombrada como {codigo or 'SOLxxxx'}-[NOMBRE]_[VIAL]_[INYECCIÓN]_[RUN].{cv_col_desc}


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sec_n + 3}. ACCESO A LOS DATOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Los archivos están disponibles en nuestro servidor. Para la descarga, siga las instrucciones del documento adjunto para conectarse vía FileZilla/FTP.
• Usuario: {ftp_user or '—'}
• Contraseña: {ftp_pass or '—'}

Le rogamos que nos avise cuando haya completado la descarga para proceder a eliminar los archivos del servidor.


Le agradeceríamos que dedicase unos instantes a completar la encuesta de satisfacción que hemos preparado en el siguiente enlace: https://forms.gle/K6uwJjekgKyLTmrr9. No le llevará más de 30 segundos y nos resultará de gran ayuda a la hora de justificar nuestro trabajo.

Muchas gracias por la confianza depositada en nuestro servicio para llevar a cabo los análisis. Para cualquier duda o comentario, no dude en escribirnos.

{firmante or 'ECAI Espectrometría de Masas e Imagen Molecular'}
{cargo or 'Unidad de Espectrometría de Masas · IMIBIC'}"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # M&M (EN)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    chems = MM_CHEMICALS_META if tipo=="meta" else MM_CHEMICALS_LIPO
    # Append the chloroform sentence to the Chemicals & Solvents block when
    # the biphasic MeOH:CHCl₃ protocol is in use.
    if _has_meoh_chcl3:
        chems = chems + " " + _CHCL3_SENTENCE
    lc    = MM_LC_META        if tipo=="meta" else MM_LC_LIPO
    ms_t  = MM_MS_META        if tipo=="meta" else MM_MS_LIPO
    ms    = ms_t.format(polarity_ion=pol_en_ion)
    proc  = _mm_processing_en(tipo, pol_en_modo, r2, modo_filtrado,
                               dil_levels, allow2pt, use_drop, ion_sup,
                               usar_cv, cv_thr or 20, qc_name or "QC")

    if alt_on:
        mode_label_en = _ALT_MODE_LABEL_EN.get(alt_mode or "fail",
                                                _ALT_MODE_LABEL_EN["fail"])
        n_exc = int(alt_n_excluded or 0)
        n_min = int(alt_n_min or 0) if alt_n_min is not None else None
        n_max = int(alt_n_max or 0) if alt_n_max is not None else None
        if n_min and n_max and n_min != n_max:
            neff_en = f"between {n_min} and {n_max} valid replicates per sample"
        elif n_min:
            neff_en = f"{n_min} valid replicates per sample"
        else:
            neff_en = "the effective number of valid replicates per sample"

        alt_mm_en = (
            f"As a complementary analysis, the full quality-control pipeline (replicate "
            f"diagnostic, linearity filter and repeatability filter) was re-executed after "
            f"excluding {mode_label_en} "
            f"(n = {n_exc} replicate{'s' if n_exc != 1 else ''} in total), using {neff_en}. "
            f"No imputation strategy was applied — in particular, failed replicates were not "
            f"replaced by the mean of the remaining valid replicates, as this practice "
            f"artificially deflates the standard deviation by a factor of √((n−1)/n) "
            f"(≈ 0.82 for n = 3) and inflates downstream statistical significance. "
            f"This approach follows the recommendations from the mQACC, MSI and Lipidomics "
            f"Standards Initiative consortia, which advocate propagating the effective "
            f"sample size rather than imputing missing replicates. Outputs from this "
            f"alternative analysis are delivered alongside the main results as a parallel "
            f"set of CSV files suffixed with `_ALT` (e.g., experiment_filtered_ALT.csv)."
        )
        proc = proc + "\n\n" + alt_mm_en

    mm = f"""Sample preparation
{pp_txt_en}

{chems}

{lc}

{ms}

{proc}"""

    # ── Save to registry ────────────────────────────────────────────────────
    _sh.save_entry(
        user     = dest or "",
        sol      = codigo or "",
        service  = "metabolomics" if tipo == "meta" else "lipidomics",
        scat     = scat or "",
        ssub     = muestra or "",       # keep original EN term for registry
        sorg     = sorg or "",
        nsamp    = str(n_muestras or ""),
        # Persist FTP credentials as autocomplete suggestions for future
        # reports. Stored in the same per-user history JSON as the rest of
        # the metadata; accessed via get_unique_values('ftp_user'/'ftp_pass').
        ftp_user = (ftp_user or "").strip(),
        ftp_pass = (ftp_pass or "").strip(),
    )

    # ── Store data for Word download ─────────────────────────────────────────
    store_data = {
        "correo": correo,
        "mm":     mm,
        "codigo": codigo or "",
        "tipo":   tipo,
        "dest":   dest or "",
    }

    # ── Render ──────────────────────────────────────────────────────────────
    tipo_label = "Metabolómica" if tipo == "meta" else "Lipidómica"
    docx_fname = f"{(codigo or 'informe').upper()}_{tipo_label}.docx"

    result_ui = html.Div([
        # Correo
        html.Div(className="card", children=[
            html.Div(style={"display":"flex","justifyContent":"space-between",
                            "alignItems":"center","marginBottom":"1rem"}, children=[
                html.Div("Correo de entrega", className="card-title",
                         style={"marginBottom":"0"}),
                html.Div(style={"display":"flex","gap":"8px"}, children=[
                    _copy_btn("inf-copy-correo","📋 Copiar correo"),
                ]),
            ]),
            _text_box(correo, "inf-correo-text"),
        ]),

        # M&M
        html.Div(className="card", style={"marginTop":"1rem"}, children=[
            html.Div(style={"display":"flex","justifyContent":"space-between",
                            "alignItems":"center","marginBottom":"1rem"}, children=[
                html.Div("Materials & Methods (EN)", className="card-title",
                         style={"marginBottom":"0"}),
                html.Div(style={"display":"flex","gap":"8px"}, children=[
                    _copy_btn("inf-copy-mm","📋 Copiar M&M","#4A9B8F"),
                ]),
            ]),
            _text_box(mm, "inf-mm-text"),
        ]),

        # Botón descarga Word
        html.Div(style={"textAlign":"center","marginTop":"1.2rem","marginBottom":"0.5rem"},
                 children=[
            html.Button(
                f"⬇ Descargar informe Word ({docx_fname})",
                id="inf-btn-docx",
                style={
                    "background":"#4A9B8F","color":"#fff","border":"none",
                    "padding":"10px 28px","borderRadius":"6px","cursor":"pointer",
                    "fontSize":"12px","fontFamily":"monospace","fontWeight":"600",
                },
            ),
        ]),

        # Clipboard wiring lives in the two clientside_callbacks registered
        # at module load (see top of this file). React does NOT execute
        # <script> tags injected via html.Script(), so the previous
        # implementation never attached its click handlers.
    ])

    return result_ui, store_data


# =============================================================================
# CALLBACK — DESCARGA WORD
# =============================================================================

# Known M&M section headings (must be the first line of each paragraph block)
_MM_HEADINGS = {
    "Sample preparation",
    "Chemicals and solvents",
    "Liquid chromatography",
    "MS acquisition: 4D PASEF",
    "Data processing and statistical evaluation",
}


def _parse_correo_blocks(correo_text: str) -> list:
    """Parse the correo string into a list of (kind, text) tuples.

    Kinds:
      'section_heading' — numbered section title (was between ━━━ lines)
      'file_heading'    — numbered file entry title (after ─── line)
      'file_body'       — description for the file entry
      'body'            — regular paragraph text
    """
    result = []
    lines  = correo_text.split("\n")
    n      = len(lines)
    i      = 0

    while i < n:
        stripped = lines[i].strip()

        # ── Heavy separator (━━━): title is the next non-separator, non-empty line ──
        if stripped.startswith("━"):
            j = i + 1
            # skip any more ━ lines or empty lines
            while j < n and (not lines[j].strip() or lines[j].strip().startswith("━")):
                j += 1
            if j < n and lines[j].strip() and not lines[j].strip().startswith("━"):
                heading = lines[j].strip()
                result.append(("section_heading", heading))
                # skip past the closing ━━━ line(s)
                k = j + 1
                while k < n and lines[k].strip().startswith("━"):
                    k += 1
                i = k
                continue
            else:
                i += 1
                continue

        # ── Light separator (─────): next non-empty line is file_heading ──
        if stripped.startswith("─"):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and lines[j].strip():
                result.append(("file_heading", lines[j].strip()))
                # collect following lines as file_body (until blank line or next ─/━)
                k = j + 1
                body_lines = []
                while k < n and lines[k].strip() \
                      and not lines[k].strip().startswith("─") \
                      and not lines[k].strip().startswith("━"):
                    body_lines.append(lines[k].strip())
                    k += 1
                if body_lines:
                    result.append(("file_body", " ".join(body_lines)))
                i = k
                continue
            else:
                i += 1
                continue

        # ── Empty line → skip ──
        if not stripped:
            i += 1
            continue

        # ── Regular body text ──
        result.append(("body", stripped))
        i += 1

    return result


def _build_docx(store: dict) -> bytes:
    """Build a python-docx Word document from stored correo + mm texts."""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    TEAL  = RGBColor(0x4A, 0x9B, 0x8F)
    DARK  = RGBColor(0x2C, 0x2C, 0x2A)
    MUTED = RGBColor(0x88, 0x87, 0x80)
    SLATE = RGBColor(0x6A, 0x7F, 0xA8)
    GRAY  = RGBColor(0x55, 0x55, 0x55)
    FONT  = "Calibri"

    correo = store.get("correo", "")
    mm     = store.get("mm", "")
    codigo = store.get("codigo", "")
    tipo   = store.get("tipo", "meta")
    dest   = store.get("dest", "")

    tipo_label   = "Metabolómica"  if tipo == "meta" else "Lipidómica"
    tipo_label_u = "METABOLÓMICA"  if tipo == "meta" else "LIPIDÓMICA"
    fecha_str    = datetime.datetime.now().strftime("%d/%m/%Y")

    doc = Document()

    # ── Page margins ──
    for sec in doc.sections:
        sec.top_margin    = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin   = Cm(2.5)
        sec.right_margin  = Cm(2.5)

    # ── Default style ──
    doc.styles["Normal"].font.name      = FONT
    doc.styles["Normal"].font.size      = Pt(10.5)
    doc.styles["Normal"].font.color.rgb = DARK

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _sf(run, size, *, bold=False, color=DARK):
        run.font.name = FONT; run.font.size = Pt(size)
        run.font.bold = bold; run.font.color.rgb = color

    def _thick_rule(para, color="4A9B8F", sz="12"):
        pPr  = para._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bot  = OxmlElement("w:bottom")
        bot.set(qn("w:val"), "thick"); bot.set(qn("w:sz"), sz)
        bot.set(qn("w:space"), "4");   bot.set(qn("w:color"), color)
        pBdr.append(bot); pPr.append(pBdr)

    def _thin_rule(para, color="4A9B8F"):
        pPr  = para._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bot  = OxmlElement("w:bottom")
        bot.set(qn("w:val"), "single"); bot.set(qn("w:sz"), "4")
        bot.set(qn("w:space"), "1");    bot.set(qn("w:color"), color)
        pBdr.append(bot); pPr.append(pBdr)

    def _no_border_xml():
        tcBdr = OxmlElement("w:tcBdr")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "none"); el.set(qn("w:sz"), "0")
            el.set(qn("w:space"), "0"); el.set(qn("w:color"), "auto")
            tcBdr.append(el)
        return tcBdr

    def _para(text, *, bold=False, size=10.5, color=DARK,
               align=WD_ALIGN_PARAGRAPH.LEFT, space_before=0, space_after=6):
        p = doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after  = Pt(space_after)
        r = p.add_run(text)
        _sf(r, size, bold=bold, color=color)
        return p

    def _H1(text):
        """Teal section heading, thin rule below."""
        p = _para(text, bold=True, size=11, color=TEAL,
                  space_before=14, space_after=6)
        _thin_rule(p, color="4A9B8F")
        return p

    # ════════════════════════════════════════════════
    # DOCUMENT HEADER  (same style as proteomics)
    # ════════════════════════════════════════════════

    # Service tag
    pt = doc.add_paragraph()
    pt.paragraph_format.space_after = Pt(4)
    _sf(pt.add_run(f"INFORME DE ENTREGA · {tipo_label_u}"), 10, color=MUTED)

    # SOL + thick teal underline
    ps = doc.add_paragraph()
    ps.paragraph_format.space_after = Pt(0)
    _sf(ps.add_run(f"IMSMI · {codigo or 'SOL202XXXXX'}"), 22, bold=True, color=TEAL)
    _thick_rule(ps)

    # Destinatario line
    pu = doc.add_paragraph()
    pu.paragraph_format.space_after = Pt(2)
    _sf(pu.add_run(dest or "Destinatario"), 13, bold=True, color=DARK)
    _sf(pu.add_run("  ·  Unidad de Espectrometría de Masas · IMIBIC"), 11, color=MUTED)

    # Platform/unit line
    pe = doc.add_paragraph()
    pe.paragraph_format.space_after = Pt(14)
    _sf(pe.add_run(f"{tipo_label} no dirigida · IMSMI · IMIBIC · Córdoba"), 9, color=MUTED)

    # Metadata table: 3 rows × 2 cols  (no borders, shaded label cells)
    meta_rows = [
        [("SOLICITUD", codigo or "—"),      ("FECHA DEL INFORME", fecha_str)],
        [("DESTINATARIO", dest or "—"),      ("SERVICIO", tipo_label)],
    ]
    mt = doc.add_table(rows=len(meta_rows), cols=2)
    mt.alignment = WD_TABLE_ALIGNMENT.LEFT
    for ri, row_data in enumerate(meta_rows):
        for ci, (lbl_, val_) in enumerate(row_data):
            cell = mt.cell(ri, ci)
            cell.text = ""
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.append(_no_border_xml())
            if ci == 0:
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), "F0FAF8")
                tcPr.append(shd)
            pl = cell.paragraphs[0]
            rl = pl.add_run(lbl_); _sf(rl, 8, color=MUTED)
            p2 = cell.add_paragraph()
            r2 = p2.add_run(val_); _sf(r2, 11, bold=True, color=DARK)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)   # spacer

    # ════════════════════════════════════════════════
    # CORREO CONTENT — starts directly at section 1
    # (greeting/intro paragraphs are skipped here; they live in the app only)
    # ════════════════════════════════════════════════
    blocks = _parse_correo_blocks(correo)
    first_heading_idx = next(
        (i for i, (k, _) in enumerate(blocks) if k == "section_heading"), 0
    )
    for kind, text in blocks[first_heading_idx:]:
        if kind == "section_heading":
            _H1(text)
        elif kind == "file_heading":
            _para(text, bold=True, size=10.5, color=SLATE, space_before=8, space_after=2)
        elif kind == "file_body":
            _para(text, size=9.5, color=GRAY,
                  align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=4)
        else:
            # Fallback for any block kind not handled above — render as
            # plain body text so nothing is silently dropped.
            _para(text, size=10.5, color=DARK,
                  align=WD_ALIGN_PARAGRAPH.LEFT, space_after=4)

    # ════════════════════════════════════════════════
    # SERIALIZE the python-docx Document and return the raw bytes,
    # honouring the ``-> bytes`` annotation on _build_docx.
    # ════════════════════════════════════════════════
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
