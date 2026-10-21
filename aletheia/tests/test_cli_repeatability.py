"""The command line runs the repeatability module (M2) and honours --cv."""
import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aletheia.cli import main  # noqa: E402

FIXTURE = Path(__file__).parent / "fixture_metaboscape.csv"


def _run(tmp_path, *extra):
    out = tmp_path / "out"
    rc = main(["run", str(FIXTURE), "--out", str(out), *extra])
    assert rc == 0
    return out, json.loads((out / "aletheia_summary.json").read_text(encoding="utf-8"))


def test_repeatability_files_and_summary(tmp_path):
    out, s = _run(tmp_path, "--cv", "20")
    assert s["repeatability_run"] is True
    for name in ("cv_per_sample.csv", "combined_results.csv", "pass_all_criteria.csv"):
        assert (out / name).exists()
    comb = pd.read_csv(out / "combined_results.csv")
    assert {"CV_median", "CV_ok", "ICC", "pass_both"} <= set(comb.columns)
    assert s["n_features_pass_both"] == int(comb["pass_both"].sum())
    assert s["parameters"]["cv_threshold"] == 20.0


def test_cv_threshold_is_applied(tmp_path):
    _, loose = _run(tmp_path / "a", "--cv", "1000")
    _, strict = _run(tmp_path / "b", "--cv", "0.0001")
    assert strict["n_cv_ok"] <= loose["n_cv_ok"]
    assert strict["n_features_pass_both"] <= loose["n_features_pass_both"]
    assert strict["n_cv_ok"] == 0


def test_linearity_only_skips_repeatability(tmp_path):
    out, s = _run(tmp_path, "--linearity-only")
    assert s["repeatability_run"] is False
    assert not (out / "pass_all_criteria.csv").exists()
