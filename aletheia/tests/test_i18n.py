"""Interface translation: English source strings, Spanish table, cookie switch."""
import ast
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG.parent))

from aletheia.core import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_lang():
    i18n.set_default_lang("en")
    yield
    i18n.set_default_lang("en")


def test_english_is_default_and_passthrough():
    assert i18n.t("Analyze") == "Analyze"
    assert i18n.t("{n} features", n=3) == "3 features"


def test_spanish_translation_and_fallback():
    i18n.set_default_lang("es")
    assert i18n.t("Language") == "Idioma"
    assert i18n.t("A string that has no translation") == "A string that has no translation"


def test_cookie_selects_language():
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context("/", headers={"Cookie": "aletheia_lang=es"}):
        assert i18n.get_lang() == "es"
        assert i18n.t("Language") == "Idioma"
    with app.test_request_context("/", headers={"Cookie": "aletheia_lang=xx"}):
        assert i18n.get_lang() == "en"


def test_every_translatable_string_has_a_spanish_entry():
    missing = []
    for path in PKG.rglob("*.py"):
        if "tests" in path.parts or path.name.startswith("i18n_es"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("t", "t_pdf")
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                key = node.args[0].value
                if any(c.isalpha() for c in key) and key not in i18n.ES:
                    missing.append((path.name, key[:60]))
    assert not missing, missing


def test_placeholders_match_between_languages():
    import string
    fmt = string.Formatter()
    bad = []
    for en, es in i18n.ES.items():
        a = {f for _, f, _, _ in fmt.parse(en) if f}
        b = {f for _, f, _, _ in fmt.parse(es) if f}
        if a != b:
            bad.append(en[:60])
    assert not bad, bad
