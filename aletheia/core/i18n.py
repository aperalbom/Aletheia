"""
core/i18n.py — minimal English/Spanish interface translation.

English is the source language: every user-facing string is written in English
in the code and wrapped in :func:`t`.  The Spanish version lives in the
``ES`` table below (key = the English string, exactly as written in the code).

The language is chosen per browser: the language selector in the sidebar
stores it in the ``aletheia_lang`` cookie, which the browser sends with every
page load, callback and download request, so :func:`t` simply reads it from the
current Flask request.  Outside a request (CLI, tests, scripts) the language is
English unless :func:`set_default_lang` is called.

Only the interface and the PDF/HTML run report are translated.  Data files
(CSV/JSON outputs, column names, reason codes) are identical in both
languages, so results are reproducible regardless of the interface language.
"""
from __future__ import annotations

COOKIE = "aletheia_lang"
LANGS = ("en", "es")
_default = "en"


def set_default_lang(lang: str) -> None:
    """Language used outside a web request (scripts, tests)."""
    global _default
    _default = lang if lang in LANGS else "en"


def get_lang() -> str:
    try:
        from flask import has_request_context, request
        if has_request_context():
            lang = request.cookies.get(COOKIE, "")
            if lang in LANGS:
                return lang
    except Exception:
        pass
    return _default


def t(msg: str, **kw) -> str:
    """Translate *msg* (English source) into the current language.

    Placeholders use ``str.format`` syntax: ``t("{n} features", n=5)``.
    A missing Spanish entry silently falls back to the English text.
    """
    out = ES.get(msg, msg) if get_lang() == "es" else msg
    return out.format(**kw) if kw else out


# ---------------------------------------------------------------------------
# Spanish translations (key = English source string)
# ---------------------------------------------------------------------------
ES: dict[str, str] = {}

# The tables are split by area so they can be maintained independently.
from . import i18n_es_ui, i18n_es_report  # noqa: E402

ES.update(i18n_es_ui.ES_UI)
ES.update(i18n_es_report.ES_REPORT)
