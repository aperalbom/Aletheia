"""tests/test_cli.py — Aletheia CLI smoke tests."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import cli                                              # noqa: E402


def _capture(fn, *args, **kw):
    """Run *fn* capturing stdout / stderr and returning (code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = fn(*args, **kw)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    return code, out.getvalue(), err.getvalue()


def test_version_prints_string():
    code, out, _ = _capture(cli.main, ["version"])
    assert code == 0
    assert "aletheia" in out.lower()


def test_sniff_detects_metaboscape():
    import test_loaders_metaboscape as M
    fixture = M._make_synthetic_metaboscape_csv()
    code, out, _ = _capture(cli.main, ["sniff", fixture])
    assert code == 0
    assert out.strip() == "metaboscape"


def test_sniff_unknown_returns_1():
    # CSV with no recognised columns.
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("foo,bar\n1,2\n")
        path = f.name
    try:
        code, _, err = _capture(cli.main, ["sniff", path])
        assert code == 1
        assert "unknown" in err.lower()
    finally:
        os.unlink(path)


def test_run_happy_path_on_metaboscape():
    import test_loaders_metaboscape as M
    fixture = M._make_synthetic_metaboscape_csv()
    with tempfile.TemporaryDirectory() as outdir:
        code, _, _err = _capture(cli.main,
                                  ["run", fixture, "--out", outdir, "--r2", "0.6"])
        assert code == 0, _err
        # JSON summary must exist and have the canonical fields.
        summary_path = Path(outdir) / "aletheia_summary.json"
        assert summary_path.exists(), f"summary missing in {outdir}"
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        for must in ("tool", "n_features_in", "n_features_passed",
                      "pct_passed", "runtime_s", "aletheia_version",
                      "format"):
            assert must in s, f"missing field {must!r} in summary"
        assert s["tool"] == "aletheia"
        assert s["format"] == "metaboscape"
        # CSVs are produced.
        assert (Path(outdir) / "linearity.csv").exists()
        assert (Path(outdir) / "good_coor.csv").exists()
        assert (Path(outdir) / "bad_coor.csv").exists()


def test_run_with_explicit_format():
    """Forcing --format works even when sniff already would have picked it."""
    import test_loaders_metaboscape as M
    fixture = M._make_synthetic_metaboscape_csv()
    with tempfile.TemporaryDirectory() as outdir:
        code, _, err = _capture(cli.main,
                                  ["run", fixture, "--out", outdir,
                                   "--format", "metaboscape"])
        assert code == 0, err


def test_run_unknown_format_errors_clearly():
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("foo,bar\n1,2\n")
        path = f.name
    try:
        with tempfile.TemporaryDirectory() as outdir:
            code, _, err = _capture(cli.main, ["run", path, "--out", outdir])
            assert code == 1
            assert "auto-detect" in err.lower()
    finally:
        os.unlink(path)


def test_run_missing_input_errors():
    with tempfile.TemporaryDirectory() as outdir:
        code, _, err = _capture(cli.main,
                                  ["run", "/no/such/file.csv", "--out", outdir])
        assert code == 1
        assert "not found" in err.lower()
