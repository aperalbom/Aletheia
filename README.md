# Aletheia

> Quality-control pipeline for untargeted LC–MS metabolomics and lipidomics —
> per-feature linearity, two-tier replicate diagnostic, multi-format input.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![DOI](https://img.shields.io/badge/DOI-pending-lightgrey.svg)](#citation)
[![Status](https://img.shields.io/badge/status-pre--release-orange.svg)](#)

**Aletheia** is an open-source Python/Dash pipeline for quality-control
filtering of untargeted LC–MS metabolomics and lipidomics datasets. It sits
between vendor peak-picking (Bruker MetaboScape, MZmine 3, XCMS, MS-DIAL) and
downstream statistical analysis (MetaboAnalyst, R/Bioconductor), automating
per-feature decisions that are otherwise made by ad-hoc spreadsheets.

For every feature, Aletheia performs an exhaustive search across replicate-
aggregation strategies × drop-lowest-dilution variants, retaining the
regression that maximises **R² with positive slope** against a QC dilution
series, and flags candidate **ion-suppression** entities. A two-tier
replicate-injection diagnostic (global failure + per-feature Z-score outliers)
and **%CV / ICC** filters close the loop, emitting curated feature tables
together with a fully auditable per-feature decision log.

---

## Table of contents

- [Features](#features)
- [Supported input formats](#supported-input-formats)
- [Installation](#installation)
- [Quick start — Dash UI](#quick-start--dash-ui)
- [Quick start — CLI](#quick-start--cli)
- [Sample-Mapping editor](#sample-mapping-editor)
- [Outputs](#outputs)
- [Benchmark against notame](#benchmark-against-notame)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [Citation](#citation)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---

## Features

- **Per-feature linearity assessment** against a QC dilution series, with
  exhaustive search across:
  - replicate-aggregation strategies (first / second / third replicate / mean),
  - drop-lowest-dilution variant.
  Retains the combination that maximises R² with strictly positive slope.
- **Ion-suppression flag** for features with negative-slope but high R²
  regressions, delivered separately so they can be reviewed instead of
  silently discarded.
- **Two-tier replicate-injection diagnostic**:
  - Level 1 (global failure) — total sum and median intensity below a
    user-defined fraction of the within-sample median.
  - Level 2 (per-feature outliers) — Z-score on valid replicates.
- **%CV** across valid replicates and **ICC[2,1]** repeatability filters.
- **Alternative-analysis mode** that re-executes the full pipeline excluding
  flagged replicates, propagating the effective sample size *without* missing-
  replicate imputation — in line with mQACC and MSI recommendations.
- **Multi-format ingestion** (MetaboScape · MZmine 3 · XCMS · MS-DIAL · generic
  CSV) with auto-detection and a Sample-Mapping editor for role refinement.
- **Auditable outputs**: every per-feature decision is exported with a
  machine-readable reason code (`r2_ok`, `ion_suppression`, `only_2_points`,
  `negative_slope`, `r2_low`, `no_data`).

## Supported input formats

| Format | Auto-detect | Native columns expected |
|---|---|---|
| Bruker MetaboScape | ✓ | `Bucket label`, `RT`, `m/z`, `Name`, `Formula`, …  |
| MZmine 3 | ✓ | `row ID`, `row m/z`, `row retention time`, `<file>.mzML Peak area`, …  |
| XCMS  | ✓ | `mz`/`mzmed`, `rt`/`rtmed`, one column per sample |
| MS-DIAL | ✓ | `Alignment ID` (or `Alignment_ID`), `Average Mz`, `Average Rt(min)`, …  |
| Generic CSV | manual | user supplies `feature_id_col`, `mz_col`, `rt_col`, `sample_cols` |

## Installation

### From source

```bash
git clone https://github.com/aperalbom/Aletheia.git
cd Aletheia
pip install -e .                # editable install
```

### Requirements

- Python ≥ 3.10
- See `requirements.txt` for pinned versions of Dash, pandas, NumPy,
  Plotly, openpyxl and python-docx.

### Optional: Docker (benchmarking environment)

A reproducible benchmark image containing notame v0.3.2 and pmp
(Bioconductor) is provided under `notame_benchmark/`. Build it with:

```bash
cd notame_benchmark
make build       # ≈ 10 min on first run
make bench DATA=/data/your_export.csv
```

## Quick start — Dash UI

```bash
cd sol_analyzer_dash
python app.py
# Open http://localhost:8050 in a browser
```

Navigate to **Aletheia** in the sidebar, upload a feature table from any of
the supported pipelines, optionally refine the auto-detected sample roles in
the Sample-Mapping editor, set the R² / %CV thresholds, and press *Run*. The
linearity, replicate-diagnostic and CV/ICC panels appear together with the
download links for the curated CSV tables.

## Quick start — CLI

The same pipeline can be invoked from the command line — ideal for batch
processing, CI/CD, and the reproducibility Docker image:

```bash
# Auto-detect format and run with default thresholds
aletheia run path/to/file.csv --out results/

# Force a specific format + tune the linearity filter
aletheia run path/to/file.csv \
  --out results/ \
  --format msdial \
  --r2 0.65 --cv 20 \
  --use-drop --allow-2pt --ion-suppression

# Detect the format without running anything
aletheia sniff path/to/file.csv
# → metaboscape | mzmine | xcms | msdial
```

The CLI writes the curated CSVs into `--out` plus an `aletheia_summary.json`
file with `n_features_in`, `n_features_passed`, `pct_passed`,
`rsd_qc_before_median`, `rsd_qc_after_median`, `runtime_s` and the parameters
used.

## Sample-Mapping editor

When the source format encodes sample roles in companion metadata (e.g. the
MS-DIAL workflow as used by *notame*), the auto-classifier cannot infer roles
from column headers alone. The Sample-Mapping editor lets the user:

- assign a role to each column (`sample` / `qc_pool` / `qc_dil` / `blank` /
  `exclude`),
- set dilution percentage for QC dilution levels,
- adjust replicate numbering when necessary.

The refined mapping is persisted as a JSON sidecar (`<file>_aletheia_mapping.json`)
so subsequent runs reproduce the same curation without manual re-entry.

## Outputs

| File | Content |
|---|---|
| `linearity.csv` | Per-feature linearity decision with reason code, R², strategy used |
| `good_coor.csv` | Features passing the linearity filter |
| `bad_coor.csv` | Features failing the linearity filter, with reason |
| `qcr_report.csv` | Replicate-injection diagnostic per (sample, replicate) |
| `experiment_aggregated.csv` | Per-sample average over valid replicates (ready for MetaboAnalyst) |
| `combined_results.csv` | Linearity + repeatability joint table |
| `pass_all_criteria.csv` | Subset passing both filters |
| `informe_resultados.pdf` | Audit PDF with all panels |
| `aletheia_summary.json` | Machine-readable run summary |

## Benchmark against notame

A reproducible benchmark against notame v0.3.2 (archived 31 Oct 2025) and pmp
(Bioconductor) is provided in `notame_benchmark/`. Each tool consumes the same
feature table and emits a JSON summary; a consolidation script collates the
metrics into a single CSV.

```bash
cd notame_benchmark
make build                                         # one-off, ≈ 10 min
make bench DATA=/data/your_dataset.csv             # runs Aletheia + notame + pmp
cat outputs/your_dataset/benchmark_table.csv
```

The Docker image pins R 4.2.3, Bioconductor 3.16 and notame v0.3.2 (last
release tag before the upstream repository was archived), so the comparison
is byte-reproducible across hosts.

## Testing

```bash
cd sol_analyzer_dash
pytest tests/                # 49 tests covering all five loaders, the
                              # legacy-dict round-trip, sample mapping,
                              # generic CSV, and the CLI.
```

## Project layout

```
Aletheia_Dash/
├── README.md
├── LICENSE
├── CITATION.cff
├── notame_benchmark/                ← reproducible Docker image
│   ├── Dockerfile, docker-compose.yml, Makefile, scripts/
└── sol_analyzer_dash/
    ├── app.py                       ← Dash entry point
    ├── cli.py                       ← `aletheia run|sniff|version`
    ├── core/
    │   ├── analysis.py              ← linearity / QCR / CV / ICC
    │   ├── schema.py                ← ParsedDataset, SampleRecord
    │   └── loaders/                 ← multi-format ingestion layer
    │       ├── metaboscape.py
    │       ├── mzmine.py
    │       ├── xcms.py
    │       ├── msdial.py
    │       ├── generic_csv.py
    │       └── mapping_io.py        ← sidecar JSON persistence
    ├── components/
    │   └── sample_mapping.py        ← Dash editor for role refinement
    ├── pages/                       ← Dash pages (UI)
    └── tests/                       ← pytest suite
```

## Documentation

Full documentation, vignettes and screenshots will be published at
`https://aperalbom.github.io/Aletheia` (link pending the first release).

## Citation

If you use Aletheia in research, please cite both the software and the
accompanying paper:

> Peralbo-Molina, Á., López-Vázquez, C., Salinas-Gavilán, A. &
> Chicano-Gálvez, E. (2026). *Aletheia: an open-source quality-control
> pipeline for QC dilution-based feature filtering in untargeted LC–MS
> metabolomics and lipidomics.* Metabolomics, [INSERT: vol., pages].
> DOI: [INSERT: paper DOI].

A BibTeX entry and the GitHub-recognised `CITATION.cff` are provided in this
repository.

## Acknowledgements

Developed and maintained at the **ECAI Mass Spectrometry and Molecular Imaging (IMSMI)**,
**IMIBIC** (Instituto Maimónides de Investigación Biomédica de Córdoba),
Hospital Universitario Reina Sofía / Universidad de Córdoba, Spain.

Aletheia builds on the conceptual groundwork laid by *notame* (Klåvus et al.,
*Metabolites* 2020) and adopts the quality-control guidelines from the mQACC,
MSI and Lipidomics Standards Initiative consortia.

## License

Aletheia is released under the [MIT License](LICENSE).
