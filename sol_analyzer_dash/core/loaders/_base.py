"""
core/loaders/_base.py

Abstract base class for every Aletheia loader.

A loader is a stateless object that knows how to recognise one specific
vendor / pipeline export and convert it into a :class:`core.schema.ParsedDataset`.
"""

from __future__ import annotations

import abc
import os
from typing import ClassVar

import pandas as pd

from ..schema import ParsedDataset


class Loader(abc.ABC):
    """Abstract Loader. Subclasses must implement :meth:`_can_read` and
    :meth:`_read`.
    """

    #: Short identifier of the source format (``"metaboscape"``, ``"mzmine"``…).
    FORMAT_NAME: ClassVar[str] = "abstract"

    #: Human-friendly label shown in the Sample-Mapping UI.
    FORMAT_LABEL: ClassVar[str] = "Abstract loader"

    # ------------------------------------------------------------------ API
    @classmethod
    def sniff(cls, head_df: pd.DataFrame) -> bool:
        """Return ``True`` if the loader recognises the file from its header
        row (``head_df`` is the first ~2 rows of the CSV)."""
        return cls._can_read(head_df)

    def load(self, path: str | os.PathLike, **kwargs) -> ParsedDataset:
        """Read the file at *path* and return a populated :class:`ParsedDataset`.

        Subclasses should override :meth:`_read`, not this method, unless they
        need pre/post-processing hooks beyond the default ``validate()``.
        """
        ds = self._read(str(path), **kwargs)
        ds.validate()
        return ds

    # ----------------------------------------------------------- subclasses
    @classmethod
    @abc.abstractmethod
    def _can_read(cls, head_df: pd.DataFrame) -> bool:
        """Heuristic: does the dataframe look like our format?"""

    @abc.abstractmethod
    def _read(self, path: str, **kwargs) -> ParsedDataset:
        """Parse *path* and return a populated :class:`ParsedDataset`."""

    # ----------------------------------------------------------------- repr
    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} format={self.FORMAT_NAME!r}>"
