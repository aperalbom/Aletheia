"""tests/test_sol_analyzer_mapping.py — Sample-Mapping editor wired into the page.

Exercises the page helpers/callbacks directly (no browser): live dilution
check, applying edited roles before a run, JSON save/load/reset.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))

import dash                                                        # noqa: E402

# register_page needs a Dash(use_pages=True) app to exist first.
_app = dash.Dash(__name__, use_pages=True, pages_folder="",
                 suppress_callback_exceptions=True)

from aletheia.pages import sol_analyzer as sa              # noqa: E402
from aletheia.core.loaders import load                     # noqa: E402
from aletheia.core.cache import save, load as cload        # noqa: E402

FIXTURE = HERE / "fixture_metaboscape.csv"


def _setup():
    ds = load(str(FIXTURE), fmt="metaboscape")
    key = save({"parsed": ds.to_legacy_dict(), "fmt": "metaboscape", "ds": ds,
                "filename": "fixture.csv", "mapping": ds.to_mapping_json()})
    rows = [sa.smap._record_to_row(r) for r in ds.samples]
    return ds, key, rows


def _as_callback(trigger_prop):
    """Fake a Dash callback context so ``ctx.triggered_id`` works in tests."""
    from dash._callback_context import context_value
    from dash._utils import AttributeDict
    context_value.set(AttributeDict(
        triggered_inputs=[{"prop_id": trigger_prop, "value": 1}],
        inputs_list=[], states_list=[], outputs_list=[]))


def _text(node) -> str:
    return str(node)


def test_alert_ok_with_dilution_series():
    ds, _, rows = _setup()
    assert "QC dilution series" in _text(sa._mapping_alert(rows, ds))
    assert "No usable QC dilution series" not in _text(sa._mapping_alert(rows, ds))


def test_alert_warns_without_dilution_series():
    ds, _, rows = _setup()
    rows = [dict(r, role="sample" if r["role"] == "qc_dil" else r["role"],
                 dilution_level=None) for r in rows]
    assert "No usable QC dilution series" in _text(sa._mapping_alert(rows, ds))


def test_alert_flags_missing_dilution_level():
    ds, _, rows = _setup()
    i = next(i for i, r in enumerate(rows) if r["role"] == "qc_dil")
    rows[i] = dict(rows[i], dilution_level=None)
    assert "have no dilution level" in _text(sa._mapping_alert(rows, ds))


def test_records_keep_injection_order():
    ds, _, rows = _setup()
    recs = sa._records_from_rows(rows, ds)
    assert [r.injection_order for r in recs] == [r.injection_order for r in ds.samples]


def test_run_applies_edited_roles_and_keeps_cache_untouched():
    ds, key, rows = _setup()
    n_dil = sum(1 for r in ds.samples if r.role == "qc_dil")
    rows2 = [dict(r, role="sample" if r["role"] == "qc_dil" else r["role"],
                  dilution_level=None) for r in rows]
    rkey, _ = sa.on_run(1, key, 0.6, 20, 15, 70, ["drop", "a2p"], "linealidad", rows2)
    m1 = cload(rkey)["m1"]
    assert len(m1["good"]) == 0           # no series -> nothing retained
    assert sum(1 for r in cload(key)["ds"].samples if r.role == "qc_dil") == n_dil


def test_run_reports_invalid_mapping():
    _, key, rows = _setup()
    out = sa.on_run(1, key, 0.6, 20, 15, 70, [], "linealidad", rows[:3])
    assert out[0] is dash.no_update
    assert "sample assignment" in _text(out[1])


def test_save_load_reset_roundtrip():
    ds, key, rows = _setup()
    data = sa.on_mapping_save(1, rows, key)
    assert data["filename"] == "fixture_aletheia_mapping.json"
    payload = json.loads(data["content"])
    assert len(payload["samples"]) == len(ds.samples)

    contents = "data:application/json;base64," + base64.b64encode(
        data["content"].encode()).decode()
    # load: same mapping back
    _as_callback("sm-load.contents")
    new_rows, msg = sa.on_mapping_load_reset(0, contents, key)
    assert new_rows == rows and "Mapping loaded" in msg

    # load a JSON that does not match the file -> error, table untouched
    bad = "data:application/json;base64," + base64.b64encode(json.dumps(
        {"samples": payload["samples"][:3]}).encode()).decode()
    out, msg = sa.on_mapping_load_reset(0, bad, key)
    assert out is dash.no_update and "does not match" in msg

    # reset: back to the loader's auto-classification
    _as_callback("sm-reset.n_clicks")
    new_rows, msg = sa.on_mapping_load_reset(1, None, key)
    assert new_rows == rows and "restored" in msg
