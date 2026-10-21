# Aletheia

> Quality-control pipeline for untargeted LC–MS metabolomics and lipidomics —
> per-feature linearity, two-tier replicate diagnostic, multi-format input.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20641569.svg)](https://doi.org/10.5281/zenodo.20641569)
[![Status](https://img.shields.io/badge/status-pre--release-orange.svg)](#)

**Aletheia** is an open-source Python/Dash pipeline for quality-control
filtering of untargeted LC–MS metabolomics and lipidomics datasets. It sits
between vendor peak-picking (Bruker MetaboScape, MZmine 3, XCMS, MS-DIAL) and
downstream statistical analysis (MetaboAnalyst, R/Bioconductor), automating
per-feature decisions that are otherwise made by ad-hoc spreadsheets.

For every feature, Aletheia performs an exhaustive search across replicate-
aggregation strategies × drop-lowest-dilution variants, retaining the
regression that maximises **R² with positive slope** against a QC dilution
series, and flags candidate **non-monotonic dilution-response** entities. A two-tier
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
- [Computational benchmark](#computational-benchmark)
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
- **%CV** across valid replicates and **ICC(1,1)** repeatability filters.
- **Alternative-analysis mode** that re-executes the full pipeline excluding
  flagged replicates, propagating the effective sample size *without* missing-
  replicate imputation — in line with mQACC and MSI recommendations.
- **Multi-format ingestion** (MetaboScape · MZmine 3 · XCMS · MS-DIAL · generic
  CSV) with auto-detection and a Sample-Mapping editor for role refinement.
- **Auditable outputs**: every per-feature decision is exported with a
  machine-readable reason code (`r2_ok`, `2pt_pos_slope`,
  `non_monotonic_response`, `negative_slope`, `r2_low`, `no_data`).

## Supported input formats

| Format | Auto-detect | Native columns expected |
|---|---|---|
| Bruker MetaboScape | ✓ | `Bucket label`, `RT`, `m/z`, `Name`, `Formula`, …  |
| MZmine 3 | ✓ | `row ID`, `row m/z`, `row retention time`, `<file>.mzML Peak area`, …  |
| XCMS  | ✓ | `mz`/`mzmed`, `rt`/`rtmed`, one column per sample |
| MS-DIAL | ✓ | `Alignment ID` (or `Alignment_ID`), `Average Mz`, `Average Rt(min)`, …  |
| Generic CSV | manual | user supplies `feature_id_col`, `mz_col`, `rt_col`, `sample_cols` |

## Installation

### One-step installers (Windows, macOS, Linux)

Install [Python 3.10 or later](https://www.python.org/downloads/) once (on
Windows, tick *Add python.exe to PATH*), download or clone this repository and:

- **Windows:** double-click `Aletheia_windows.bat`.
- **macOS / Linux:** open a terminal in the folder and run
  `bash Aletheia_mac_linux.command`.

The first run creates a private environment (`.venv`) in the folder, installs
Aletheia and its dependencies (internet connection needed) and opens the web
interface at http://localhost:8050. The following runs only start the app.

### From source (command line)

```bash
git clone https://github.com/aperalbom/Aletheia.git
cd Aletheia
python -m venv .venv
# Windows: .venv\Scripts\activate        macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .                # editable install
```

Upgrading pip first is necessary: pip older than 21.3 (for example the one that
comes with the system Python of macOS) cannot install a project that only has a
`pyproject.toml` and stops with *File "setup.py" not found*.

### Requirements

- Python ≥ 3.10
- Dash, Plotly, Flask, pandas, NumPy and SciPy (see `requirements.txt`).
- Optional, only for the PDF run report of the web UI:
  `pip install -e .[full]` (ReportLab, svglib and Kaleido; Kaleido needs a
  local Chrome/Chromium installation). The analysis, the CLI and all CSV
  exports work without them.

## Quick start — Dash UI

```bash
python aletheia/app.py
# Open http://localhost:8050 in a browser
```

Upload a feature table from MetaboScape, MZmine 3, XCMS or MS-DIAL (the generic
CSV loader is available through the Python API),
optionally refine the auto-detected sample roles in the Sample-Mapping editor,
set the R² / %CV thresholds, and press *Run*. The linearity, replicate-
diagnostic and CV/ICC panels appear together with the download links for the
curated CSV tables. If no QC dilution series is detected, the run proceeds and
the interface shows a warning instead of blocking.

The interface is in English by default; the **EN | ES** switch in the sidebar
changes the language of the web interface and of the PDF run report (the choice
is remembered in the browser). Output files and column names are identical in
both languages.

## Quick start — CLI

The same pipeline can be invoked from the command line — ideal for batch
processing, CI/CD, and the reproducibility Docker image:

```bash
# Auto-detect format and run with default thresholds
aletheia run path/to/file.csv --out results/

# Force a specific format + tune the linearity and %CV thresholds
aletheia run path/to/file.csv \
  --out results/ \
  --format msdial \
  --r2 0.65 --cv 20 \
  --use-drop --allow-2pt --flag-non-monotonic

# Linearity and replicate diagnostic only (skip %CV, ICC and the joint table)
aletheia run path/to/file.csv --out results/ --linearity-only

# Detect the format without running anything
aletheia sniff path/to/file.csv
# → metaboscape | mzmine | xcms | msdial
```

The CLI writes the curated CSVs into `--out` plus an `aletheia_summary.json`
file with `n_features_in`, `n_features_passed`, `pct_passed`,
`rsd_qc_before_median`, `runtime_s`, any warnings (for example a missing QC
dilution series) and the parameters used. Unless `--linearity-only` is given,
it also runs the repeatability module and writes `cv_per_sample.csv`,
`combined_results.csv` and `pass_all_criteria.csv` (features passing linearity
and a median %CV across the injections of each sample at or below `--cv`);
the summary then also reports `n_cv_ok`, `n_icc_gt_0_75` and
`n_features_pass_both`. ICC is reported for information and is not part of the
joint criterion.

## Sample-Mapping editor

The auto-classifier infers sample roles from column headers; whenever a header
does not encode the role, the Sample-Mapping editor lets the user:

- assign a role to each column (`sample` / `qc_pool` / `qc_dil` / `blank` /
  `exclude`),
- set the dilution percentage of the QC dilution levels,
- adjust replicate numbering and injection order when necessary.

In the web UI the editor appears as a table right after the upload. The refined
mapping can be saved as a JSON file and reloaded in later sessions, and the same
file can be passed to the CLI (`aletheia run … --mapping mapping.json`), so a
curated assignment is reproduced without manual re-entry.

## Outputs

| File | Content | CLI | Web UI |
|---|---|:-:|:-:|
| `linearity.csv` | Per-feature linearity decision with reason code, R², strategy used | ✓ | |
| `good_coor.csv` | Features passing the linearity filter | ✓ | ✓ |
| `bad_coor.csv` | Features failing the linearity filter, with reason | ✓ | ✓ |
| `qcr_report.csv` | Replicate-injection diagnostic per (sample, replicate): `Sum_int`, `Median_int`, `Fail_sum`, `Fail_median`, `Status`, `Recommendation`, `N_outliers` | ✓ | ✓ |
| `experiment_aggregated.csv` | Per-sample average over valid replicates (ready for MetaboAnalyst) | ✓ | ✓ |
| `aletheia_summary.json` | Machine-readable run summary | ✓ | |
| `experiment_filtered.csv` | Original table restricted to accepted features | | ✓ |
| `cv_per_sample.csv` | %CV per sample and feature | ✓ | ✓ |
| `combined_results.csv` | Linearity + repeatability joint table (R², CV, ICC) | ✓ | ✓ |
| `pass_all_criteria.csv` | Subset passing both filters | ✓ | ✓ |
| `aletheia_report.pdf` | PDF run report (requires the `full` extra) | | ✓ |

## Computational benchmark

`benchmark_aletheia.py` runs `aletheia run` repeatedly on a feature table and
records wall-clock time and peak memory (median and range over the runs):

```bash
pip install psutil
python benchmark_aletheia.py --csv path/to/feature_table.csv
```

## Testing

```bash
pip install -e .[dev]
pytest                        # 65 tests covering the loaders, the legacy-dict
                              # round-trip, sample mapping, the mapping editor
                              # of the web UI, the EN/ES interface texts, generic CSV and the CLI.
```

## Project layout

```
Aletheia/
├── README.md
├── LICENSE
├── CITATION.cff
├── pyproject.toml
├── requirements.txt
├── benchmark_aletheia.py
└── aletheia/
    ├── app.py                       ← Dash entry point (web UI)
    ├── cli.py                       ← `aletheia run|sniff|version`
    ├── core/
    │   ├── analysis.py              ← linearity / QCR / CV / ICC
    │   ├── schema.py                ← ParsedDataset, SampleRecord
    │   ├── cache.py                 ← server-side result cache
    │   ├── i18n.py, i18n_es_*.py    ← EN/ES interface texts
    │   ├── pdf_report.py            ← PDF run report
    │   └── loaders/                 ← multi-format ingestion layer
    │       ├── metaboscape.py
    │       ├── mzmine.py
    │       ├── xcms.py
    │       ├── msdial.py
    │       ├── generic_csv.py
    │       └── mapping_io.py        ← sidecar JSON persistence
    ├── components/
    │   └── sample_mapping.py        ← Dash editor for role refinement
    ├── pages/
    │   └── sol_analyzer.py          ← the Aletheia page
    ├── assets/                      ← stylesheet and logo
    └── tests/                       ← pytest suite
```

## Documentation

A step-by-step tutorial with a synthetic plasma example dataset is provided as
Online Resource 5 of the accompanying paper.

## Citation

If you use Aletheia in research, please cite both the software and the
accompanying paper:

> Peralbo-Molina, Á., López, C. M., Salinas-Gavilán, A. &
> Chicano-Gálvez, E. (2026). *Aletheia: an open-source pipeline for QC
> dilution-based feature filtering in untargeted LC–MS metabolomics and
> lipidomics.* Metabolomics (submitted). Software: Zenodo,
> https://doi.org/10.5281/zenodo.20641569 (all versions; each release has its
> own version DOI, listed on that page).

The GitHub-recognised `CITATION.cff` in this repository feeds the
"Cite this repository" button (APA and BibTeX).

## Acknowledgements

Developed and maintained at the **ECAI Mass Spectrometry and Molecular Imaging (IMSMI)**,
**IMIBIC** (Instituto Maimónides de Investigación Biomédica de Córdoba),
Hospital Universitario Reina Sofía / Universidad de Córdoba, Spain.

Aletheia builds on the conceptual groundwork laid by *notame* (Klåvus et al.,
*Metabolites* 2020) and adopts the quality-control guidelines from the mQACC,
MSI and Lipidomics Standards Initiative consortia.

## License

Aletheia is released under the [MIT License](LICENSE).
