"""
core/loaders

Format-aware ingestion layer for Aletheia.

Supported formats
-----------------
* ``metaboscape``  — Bruker MetaboScape CompleteExperiment CSV
* ``mzmine``       — MZmine 3 quant CSV
* ``xcms``         — XCMS featureValues / peakTable CSV
* ``msdial``       — MS-DIAL alignment results table
* ``generic``      — fallback (user supplies mapping)
"""

from __future__ import annotations

import os
from typing import Iterable

import pandas as pd

from ..schema import ParsedDataset
from ._base import Loader
from .metaboscape import MetaboScapeLoader
from .mzmine      import MZmineLoader
from .xcms        import XcmsLoader
from .msdial      import MSDIALLoader
from .generic_csv import GenericCSVLoader


# Loaders are tried in order, most-specific first. GenericCSVLoader is at
# the end of the list but its sniff() always returns False — it can only
# be invoked explicitly via load(path, fmt="generic", ...).
_REGISTRY: list[type[Loader]] = [
    MetaboScapeLoader,
    MZmineLoader,
    MSDIALLoader,
    XcmsLoader,
    GenericCSVLoader,
]


def available_formats() -> list[str]:
    return [L.FORMAT_NAME for L in _REGISTRY]


def _read_head(path: str | os.PathLike, n: int = 2) -> pd.DataFrame:
    return pd.read_csv(
        path, nrows=n, encoding="latin1",
        on_bad_lines="skip", engine="python",
    )


def sniff(path: str | os.PathLike) -> str | None:
    try:
        head = _read_head(path)
    except Exception:
        return None
    for L in _REGISTRY:
        try:
            if L.sniff(head):
                return L.FORMAT_NAME
        except Exception:
            continue
    return None


def load(
    path: str | os.PathLike,
    fmt: str | None = None,
    **kwargs,
) -> ParsedDataset:
    name = fmt or sniff(path)
    if name is None:
        raise ValueError(
            f"Could not auto-detect the format of {path!r}. "
            f"Pass fmt=<one of {available_formats()}> explicitly."
        )
    for L in _REGISTRY:
        if L.FORMAT_NAME == name:
            return L().load(path, **kwargs)
    raise ValueError(
        f"Unknown loader format {name!r}. Available: {available_formats()}"
    )


__all__ = [
    "Loader",
    "MetaboScapeLoader",
    "MZmineLoader",
    "XcmsLoader",
    "MSDIALLoader",
    "GenericCSVLoader",
    "ParsedDataset",
    "available_formats",
    "sniff",
    "load",
]
