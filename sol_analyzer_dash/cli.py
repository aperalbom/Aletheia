"""
Aletheia command-line interface.

Subcommands
-----------
    aletheia sniff   <file.csv>
    aletheia run     <file.csv> --out <dir> [options]
    aletheia version

The ``run`` subcommand drives the full pipeline from any supported source
format (MetaboScape / MZmine 3 / XCMS / MS-DIAL / generic CSV) and writes
the same set of outputs the Dash UI produces, plus a machine-readable
``aletheia_summary.json`` consumed by the ``notame_benchmark`` Docker
consolidator (``scripts/04_extract_metrics.R``).

Example
-------
    aletheia run /data/merged_sample.csv \\
        --out /outputs/aletheia/ \\
        --r2 0.65 --cv 20 --use-drop --allow-2pt \\
        --mapping /data/merged_sample_aletheia_mapping.json

Exit codes
----------
    0  success
    1  user error (bad CLI args, missing file, unknown format, …)
    2  runtime error inside the pipeline
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Path handling: when invoked as a script (`python -m sol_analyzer_dash.cli`)
# or via a console-script entry point, make sure sibling modules resolve.
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from core.analysis import run_m1, run_qcr, run_m2          # noqa: E402
from core.loaders  import load as load_dataset             # noqa: E402
from core.loaders  import sniff as sniff_format             # noqa: E402
from core.loaders  import available_formats                # noqa: E402
from core.loaders.mapping_io import (                       # noqa: E402
    load_mapping_json, apply_mapping,
)


try:
    # Prefer the version declared in the installed package metadata
    # (sol_analyzer_dash/__init__.py + pyproject.toml).
    from sol_analyzer_dash import __version__ as VERSION
except Exception:
    # Fallback for in-tree execution without an installed package.
    VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Subcommand: sniff
# ---------------------------------------------------------------------------

def cmd_sniff(args: argparse.Namespace) -> int:
    fmt = sniff_format(args.input)
    if fmt is None:
        print(f"unknown — formats supported: {available_formats()}", file=sys.stderr)
        return 1
    print(fmt)
    return 0


# ---------------------------------------------------------------------------
# Subcommand: version
# ---------------------------------------------------------------------------

def cmd_version(_args: argparse.Namespace) -> int:
    print(f"aletheia {VERSION} (Python {platform.python_version()})")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def _rsd_qc(parsed: dict) -> float | None:
    """Median %CV across QC pool replicates for the raw intensity matrix."""
    qc_norm = parsed.get("qc_norm_df")
    if qc_norm is None or len(qc_norm) < 2:
        return None
    raw = parsed["raw"]
    cols = qc_norm["col"].tolist()
    mat = raw[cols].apply(pd.to_numeric, errors="coerce")
    mat = mat.where(mat > 0)
    rsd = mat.std(axis=1) / mat.mean(axis=1) * 100
    rsd = rsd.replace([np.inf, -np.inf], np.nan).dropna()
    return float(rsd.median()) if len(rsd) else None


def cmd_run(args: argparse.Namespace) -> int:
    inp = Path(args.input)
    if not inp.exists():
        print(f"error: input file not found: {inp}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # ---- 1. ingest -----------------------------------------------------
    fmt = args.format
    if fmt == "auto":
        fmt = sniff_format(str(inp))
        if fmt is None:
            print(
                f"error: cannot auto-detect format of {inp}. "
                f"Pass --format <one of {available_formats()}>.",
                file=sys.stderr,
            )
            return 1

    print(f"[1/4] ingesting {inp} (format={fmt}) …", file=sys.stderr)
    try:
        ds = load_dataset(str(inp), fmt=fmt)
    except Exception as e:
        print(f"error: loader failed: {e}", file=sys.stderr)
        return 2

    if args.mapping:
        if not Path(args.mapping).exists():
            print(f"error: mapping sidecar not found: {args.mapping}", file=sys.stderr)
            return 1
        try:
            records = load_mapping_json(args.mapping)
            apply_mapping(ds, records)
            print(f"      applied mapping from {args.mapping}", file=sys.stderr)
        except Exception as e:
            print(f"error: applying mapping failed: {e}", file=sys.stderr)
            return 2

    parsed = ds.to_legacy_dict()
    n_features_in = parsed["n_metabolites"]
    n_samples_in  = parsed["n_samples"]

    rsd_before = _rsd_qc(parsed)

    # ---- 2. linearity --------------------------------------------------
    print(
        f"[2/4] linearity filter (R² ≥ {args.r2}, "
        f"drop_lowest={args.use_drop}, allow_2pt={args.allow_2pt}, "
        f"ion_suppression={args.ion_suppression}) …",
        file=sys.stderr,
    )
    try:
        lin = run_m1(
            parsed,
            r2_threshold=args.r2,
            allow2pt=args.allow_2pt,
            use_drop=args.use_drop,
            ion_sup=args.ion_suppression,
        )
    except Exception as e:
        print(f"error: run_m1 failed: {e}", file=sys.stderr)
        return 2

    lin["lin_df"].to_csv(out_dir / "linearity.csv", index=False)
    lin["good"].to_csv(out_dir / "good_coor.csv", index=False)
    lin["bad"].to_csv(out_dir / "bad_coor.csv", index=False)

    n_passed = int(lin["good"].shape[0])
    pct_passed = round(100.0 * n_passed / max(1, n_features_in), 2)

    # ---- 3. replicate diagnostic --------------------------------------
    rsd_after: float | None = None
    qcr_df = None
    if n_samples_in >= 1:
        print("[3/4] replicate diagnostic …", file=sys.stderr)
        try:
            qcr = run_qcr(parsed, inj_threshold=args.injection_threshold)
            qcr_df = qcr.get("qcr_df")
            agg_df = qcr.get("agg_df")
            if qcr_df is not None:
                qcr_df.to_csv(out_dir / "qcr_report.csv", index=False)
            if agg_df is not None:
                agg_df.to_csv(out_dir / "experiment_aggregated.csv", index=False)
        except Exception as e:
            print(f"warning: run_qcr failed: {e}", file=sys.stderr)

    # ---- 4. summary ----------------------------------------------------
    runtime = round(time.time() - t0, 2)
    summary = {
        "tool":                "aletheia",
        "input":               str(inp),
        "format":              fmt,
        "n_features_in":       int(n_features_in),
        "n_features_passed":   n_passed,
        "pct_passed":          pct_passed,
        "rsd_qc_before_median": (round(rsd_before, 2) if rsd_before is not None else None),
        "rsd_qc_after_median":  (round(rsd_after,  2) if rsd_after  is not None else None),
        "n_samples_in":        int(n_samples_in),
        "n_qc_pool":           int(len(parsed.get("qc_norm_df", []))),
        "n_qc_dil_levels":     int(parsed["qc_dil_df"]["dil"].nunique()) if len(parsed.get("qc_dil_df", [])) else 0,
        "runtime_s":           runtime,
        "aletheia_version":    VERSION,
        "python_version":      platform.python_version(),
        "parameters": {
            "r2_threshold":      args.r2,
            "cv_threshold":      args.cv,
            "use_drop":          bool(args.use_drop),
            "allow_2pt":         bool(args.allow_2pt),
            "ion_suppression":   bool(args.ion_suppression),
            "injection_threshold": args.injection_threshold,
        },
    }
    with open(out_dir / "aletheia_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(
        f"[4/4] done — {n_passed} / {n_features_in} features retained "
        f"({pct_passed} %), runtime {runtime}s",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aletheia",
        description="Quality-control pipeline for untargeted LC–MS "
                    "metabolomics and lipidomics.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # version
    p_ver = sub.add_parser("version", help="print version and exit.")
    p_ver.set_defaults(func=cmd_version)

    # sniff
    p_sniff = sub.add_parser("sniff",
        help="detect the input format and print its name.")
    p_sniff.add_argument("input", help="path to the input CSV/TSV file.")
    p_sniff.set_defaults(func=cmd_sniff)

    # run
    p_run = sub.add_parser("run",
        help="run the full QC pipeline on the input file.")
    p_run.add_argument("input", help="path to the input CSV/TSV file.")
    p_run.add_argument("--out", "-o", required=True,
                        help="directory where results will be written.")
    p_run.add_argument("--format", "-f", default="auto",
                        choices=["auto"] + available_formats(),
                        help="source format (default: auto-detect).")
    p_run.add_argument("--mapping", default=None,
                        help="optional sample-mapping JSON sidecar.")
    p_run.add_argument("--r2", type=float, default=0.65,
                        help="R² threshold for the linearity filter.")
    p_run.add_argument("--cv", type=float, default=20.0,
                        help="%%CV threshold for the repeatability filter.")
    p_run.add_argument("--injection-threshold", type=float, default=0.70,
                        help="global-failure threshold (fraction of within-sample median).")
    p_run.add_argument("--use-drop", action="store_true", default=True,
                        help="enable the drop-lowest-dilution variant search.")
    p_run.add_argument("--no-use-drop", dest="use_drop", action="store_false",
                        help="disable drop-lowest-dilution.")
    p_run.add_argument("--allow-2pt", action="store_true", default=True,
                        help="accept features with exactly two valid points.")
    p_run.add_argument("--no-allow-2pt", dest="allow_2pt", action="store_false",
                        help="reject two-point features.")
    p_run.add_argument("--ion-suppression", action="store_true", default=False,
                        help="flag candidate ion-suppression entities.")
    p_run.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
