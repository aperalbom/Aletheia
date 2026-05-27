# Aletheia · IMSMI — Aletheia (Dash)

## Instalación

```bash
pip install dash plotly pandas numpy scipy reportlab svglib
pip install scikit-learn openpyxl python-docx
```

> `svglib` es necesario para exportar las gráficas en el informe PDF.
> Si no está instalado, el PDF se generará sin gráficas (solo tablas y texto).
>
> `scikit-learn`, `openpyxl` y `python-docx` son obligatorios para el módulo
> **Análisis estadístico** (`/stats`): sklearn para PCA/PLS-DA y ROC, openpyxl
> para leer la plantilla IMIBIC (.xlsx), python-docx para generar el informe.

## Arranque

```bash
cd sol_analyzer_dash
python app.py
```

Se abre automáticamente en `http://localhost:8050`.

## Estructura

```
sol_analyzer_dash/
  app.py              ← punto de entrada + menú lateral
  pages/
    home.py           ← pantalla de inicio con los módulos disponibles
    sol_analyzer.py   ← Aletheia completo
  core/
    analysis.py       ← toda la lógica de análisis (independiente de la UI)
  assets/
    style.css         ← estilos globales
```

## Añadir un módulo nuevo

1. Crear `pages/mi_modulo.py` con `dash.register_page(__name__, path="/mi-modulo", name="Mi módulo")`
2. Importarlo en `app.py`: `import pages.mi_modulo`
3. Añadir la entrada en `NAV_ITEMS` en `app.py`
4. Si el módulo necesita lógica de análisis, añadirla en `core/analysis.py`

## Archivos de entrada soportados

- `SOL*_CompleteExperiment.csv`
- `SOL*_Negative.csv`
- Cualquier CSV con cabeceras `SOLxxxx_MUESTRA_...` o `SOLxxxx-MUESTRA_...`

## Archivos de salida

| Archivo | Contenido |
|---------|-----------|
| `experiment_filtered.csv` | Metabolitos que pasan linealidad |
| `good_coor.csv` | Aceptados con R², estrategia y nº de puntos |
| `bad_coor.csv` | Rechazados con motivo |
| `qcr_report.csv` | Estado de cada réplica (válida/sospechosa/fallo) |
| `experiment_aggregated.csv` | Una columna por muestra — listo para MetaboAnalyst |
| `cv_per_sample.csv` | %CV por muestra y metabolito |
| `combined_results.csv` | R², CV, ICC y pass_both por metabolito |
| `pass_all_criteria.csv` | Pasan linealidad Y CV |

## Requisitos

- Python 3.8+
- Core: `pip install dash plotly pandas numpy scipy reportlab svglib`
- Stats module (`/stats`): `pip install scikit-learn openpyxl python-docx`
