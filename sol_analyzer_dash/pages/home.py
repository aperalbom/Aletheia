"""
pages/home.py
Pantalla de inicio de la plataforma IMSMI.
"""

import dash
from dash import html, dcc

dash.register_page(__name__, path="/", name="Inicio")

MODULES = [
    {
        "name":  "Aletheia",
        "path":  "/sol-analyzer",
        "desc":  "Linealidad de diluciones QC · Diagnóstico de réplicas · CV/ICC",
        "icon":  "◈",
        "color": "#4A9B8F",
        "ready": True,
    },
    {
        "name":  "Informe Metabolómica / Lipidómica",
        "path":  "/informe",
        "desc":  "Informe de entrega · Materiales y Métodos · 4D-PASEF Metabolómica y Lipidómica",
        "icon":  "📄",
        "color": "#6A7FA8",
        "ready": True,
    },
    {
        "name":  "Informe Proteómica",
        "path":  "/proteomics",
        "desc":  "Informe de entrega · DDA/DIA-PASEF · pyDIAid · DIA-PASEF Viewer",
        "icon":  "🔬",
        "color": "#6A7FA8",
        "ready": True,
    },
    {
        "name":  "Listas randomizadas",
        "path":  "/randomizer",
        "desc":  "Worklist aleatorizada con QCs · Evosep · Elute · nanoElute 2",
        "icon":  "🎲",
        "color": "#4A9B8F",
        "ready": True,
    },
    {
        "name":  "Análisis estadístico",
        "path":  "/stats",
        "desc":  "Univariante · PCA · PLS-DA · Heatmap · ROC/biomarcadores · Informe",
        "icon":  "📈",
        "color": "#E8A838",
        "ready": True,
    },
]


def layout():
    cards = []
    for m in MODULES:
        content = html.Div([
            html.Div(m["icon"], style={
                "fontSize": "2rem", "color": m["color"],
                "marginBottom": ".6rem",
            }),
            html.Div(m["name"], style={
                "fontSize": "15px", "fontWeight": "600",
                "color": "#2C2C2A", "marginBottom": ".3rem",
            }),
            html.Div(m["desc"], style={
                "fontSize": "12px", "color": "#888780",
                "lineHeight": "1.5",
            }),
            html.Div(
                "Abrir →" if m["ready"] else "En desarrollo",
                style={
                    "marginTop": "1rem",
                    "fontSize": "11px",
                    "fontWeight": "600",
                    "color": m["color"],
                    "letterSpacing": ".05em",
                    "fontFamily": "monospace",
                }
            ),
        ])

        style = {
            "background": "#fff",
            "border": f"1px solid {'#E4E2DC' if m['ready'] else '#EEECE6'}",
            "borderTop": f"3px solid {m['color']}",
            "borderRadius": "10px",
            "padding": "1.5rem",
            "textDecoration": "none",
            "display": "block",
            "opacity": "1" if m["ready"] else ".55",
            "transition": "box-shadow .2s, transform .15s",
            "cursor": "pointer" if m["ready"] else "default",
        }

        if m["ready"]:
            cards.append(dcc.Link(content, href=m["path"], style=style))
        else:
            cards.append(html.Div(content, style=style))

    return html.Div([
        html.Div(style={"maxWidth": "700px", "marginBottom": "2.5rem"}, children=[
            html.H1("Aletheia · IMSMI",
                    style={"fontSize":"24px","fontWeight":"600","margin":"0 0 6px",
                           "color":"#2C2C2A"}),
            html.P("ECAI Espectrometría de Masas e Imagen Molecular · IMIBIC",
                   style={"fontSize":"12px","color":"#888780","fontFamily":"monospace","margin":"0 0 4px"}),
            html.P("Selecciona un módulo para comenzar el análisis.",
                   style={"fontSize":"13px","color":"#888780","margin":"0"}),
        ]),

        html.Div(
            cards,
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fill, minmax(220px, 1fr))",
                "gap": "1.2rem",
                "maxWidth": "900px",
            }
        ),
    ])
