"""
benchmark_aletheia.py — Reproducible computational benchmark for the Aletheia paper.

Place this script at the root of the Aletheia_Dash repo. It runs
`aletheia run` on the Sigma synthetic plasma CSV (or any CSV you pass),
capturing wall-clock time and peak resident set size (RAM) for each run.

Usage
-----
From a PowerShell terminal inside C:\\Users\\Angela\\Desktop\\Proyectos\\Aletheia_Dash:

    # Install psutil if needed
    py -m pip install psutil

    # Run benchmark — mapping is OPTIONAL (auto-detection of roles otherwise)
    py benchmark_aletheia.py --csv "C:\\full\\path\\to\\Aletheia.csv"

    # With explicit mapping JSON
    py benchmark_aletheia.py --csv "C:\\full\\path\\to\\Aletheia.csv" --mapping "C:\\full\\path\\to\\sample_mapping.json"

    # If you do NOT remember where Aletheia.csv is on disk, you can also drag
    # the CSV from File Explorer into the PowerShell window — it pastes the path.

Output
------
    benchmark_aletheia_run/
        benchmark_results.json    machine-readable
        benchmark_results.txt     human-readable, ready to paste into the manuscript

Each dataset is run 3 times by default to capture variance. The numbers
reported in the manuscript should be the median across runs together with
the min–max range.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _import_psutil():
    try:
        import psutil  # type: ignore
        return psutil
    except ImportError:
        print("psutil is required. Install with:  py -m pip install psutil",
              file=sys.stderr)
        sys.exit(1)


def _peak_rss_mb(proc, psutil) -> float:
    """Best-effort peak RSS sampling while the child runs."""
    peak = 0
    while True:
        try:
            if not proc.is_running():
                break
            mem = proc.memory_info().rss
            for child in proc.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except psutil.NoSuchProcess:
                    continue
            if mem > peak:
                peak = mem
            time.sleep(0.05)
        except psutil.NoSuchProcess:
            break
    return peak / (1024 * 1024)


def time_one_run(cmd, cwd, psutil) -> dict:
    print(f"     starting: {' '.join(cmd[:4])} ...")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd, cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ps = psutil.Process(proc.pid)
        peak_mb = _peak_rss_mb(ps, psutil)
    except psutil.NoSuchProcess:
        peak_mb = 0.0
    stdout, stderr = proc.communicate()
    t1 = time.perf_counter()
    return {
        "wall_seconds": round(t1 - t0, 2),
        "peak_rss_mb":  round(peak_mb, 1),
        "return_code":  proc.returncode,
        "stderr_tail":  stderr[-500:] if stderr else "",
        "stdout_tail":  stdout[-300:] if stdout else "",
    }


def benchmark_dataset(name, cmd, cwd, repeats, psutil) -> dict:
    print(f"\n=== {name} ===")
    print("  cmd: " + " ".join(cmd))
    runs = []
    for i in range(repeats):
        print(f"  run {i + 1}/{repeats} ...", flush=True)
        r = time_one_run(cmd, cwd, psutil)
        print(f"     {r['wall_seconds']:.2f} s  /  {r['peak_rss_mb']:.1f} MB peak  /  rc={r['return_code']}")
        if r["return_code"] != 0:
            print(f"     ! non-zero return code")
            if r["stderr_tail"]:
                print("     ! stderr tail:")
                for line in r["stderr_tail"].splitlines():
                    print("       " + line)
        runs.append(r)
    walls = [r["wall_seconds"] for r in runs]
    peaks = [r["peak_rss_mb"]   for r in runs]
    return {
        "name":               name,
        "runs":               runs,
        "wall_median_s":      round(statistics.median(walls), 2),
        "wall_min_s":         round(min(walls), 2),
        "wall_max_s":         round(max(walls), 2),
        "peak_rss_median_mb": round(statistics.median(peaks), 1),
        "peak_rss_max_mb":    round(max(peaks), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True,
                    help="Path to the Sigma synthetic plasma CSV "
                         "(use absolute path or drag-and-drop into PowerShell)")
    ap.add_argument("--mapping", default=None,
                    help="Optional sample-mapping JSON sidecar")
    ap.add_argument("--out", default="benchmark_aletheia_run",
                    help="Output directory (created if absent)")
    ap.add_argument("--repeats", type=int, default=3,
                    help="Number of repetitions (default 3)")
    ap.add_argument("--r2", type=float, default=0.65)
    ap.add_argument("--format", default="auto")
    args = ap.parse_args()

    psutil = _import_psutil()

    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    cwd = Path(__file__).resolve().parent
    out_dir = (cwd / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sys_info = {
        "platform":            platform.platform(),
        "python":              platform.python_version(),
        "machine":             platform.machine(),
        "processor":           platform.processor(),
        "cpu_count_logical":   psutil.cpu_count(logical=True),
        "cpu_count_physical":  psutil.cpu_count(logical=False),
        "total_ram_gb":        round(psutil.virtual_memory().total / 1024**3, 1),
        "timestamp":           datetime.now().isoformat(timespec="seconds"),
        "csv":                 str(csv_path),
        "csv_size_mb":         round(csv_path.stat().st_size / 1024**2, 2),
        "mapping":             args.mapping,
    }
    print("System:")
    print(json.dumps(sys_info, indent=2))

    aletheia_cmd = [
        sys.executable, "-m", "aletheia.cli", "run",
        str(csv_path),
        "--out",     str(out_dir / "aletheia_output"),
        "--format",  args.format,
        "--r2",      str(args.r2),
        "--flag-non-monotonic",
    ]
    if args.mapping:
        mapping_path = Path(args.mapping).expanduser().resolve()
        if not mapping_path.exists():
            print(f"ERROR: mapping not found: {mapping_path}", file=sys.stderr)
            sys.exit(1)
        aletheia_cmd.extend(["--mapping", str(mapping_path)])

    sigma_results = benchmark_dataset(
        "Sigma synthetic plasma", aletheia_cmd, cwd, args.repeats, psutil,
    )

    summary = {
        "system":  sys_info,
        "results": {"sigma": sigma_results},
    }
    json_path = out_dir / "benchmark_results.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    txt = [
        "Aletheia computational benchmark",
        "================================",
        f"Date:                      {sys_info['timestamp']}",
        f"Platform:                  {sys_info['platform']}",
        f"Processor:                 {sys_info['processor']}",
        f"Python:                    {sys_info['python']}",
        f"CPU (physical / logical):  {sys_info['cpu_count_physical']} / {sys_info['cpu_count_logical']}",
        f"Total RAM:                 {sys_info['total_ram_gb']} GB",
        f"Input CSV:                 {sys_info['csv']}",
        f"Input CSV size:            {sys_info['csv_size_mb']} MB",
        f"Mapping:                   {sys_info['mapping']}",
        f"Repeats:                   {args.repeats}",
        "",
        "Sigma synthetic plasma (11,694 features, 62 injections)",
        f"  Wall time (median):        {sigma_results['wall_median_s']:.2f} s "
        f"(range {sigma_results['wall_min_s']:.2f}–{sigma_results['wall_max_s']:.2f} s across "
        f"{args.repeats} repetitions)",
        f"  Peak RSS (median):         {sigma_results['peak_rss_median_mb']:.1f} MB "
        f"(max across runs: {sigma_results['peak_rss_max_mb']:.1f} MB)",
        "",
        "Sentence to paste into Section 4 (Discussion) of the manuscript:",
        f"  Aletheia processed the 11,694-feature Sigma synthetic plasma dataset in "
        f"{sigma_results['wall_median_s']:.1f} s (median, n={args.repeats}; range "
        f"{sigma_results['wall_min_s']:.1f}–{sigma_results['wall_max_s']:.1f} s) with a "
        f"peak RSS of {sigma_results['peak_rss_median_mb']:.0f} MB on a "
        f"{sys_info['cpu_count_physical']}-core / {sys_info['cpu_count_logical']}-thread "
        f"workstation running {sys_info['platform']}.",
    ]
    txt_path = out_dir / "benchmark_results.txt"
    txt_path.write_text("\n".join(txt), encoding="utf-8")

    print("\n" + "\n".join(txt))
    print(f"\nResults written to:\n  {txt_path}\n  {json_path}")


if __name__ == "__main__":
    main()
