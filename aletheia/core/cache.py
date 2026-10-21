"""
core/cache.py
=============

Persistent server-side cache for analysis results.

Why this exists
---------------
Dash callbacks need to share large objects (DataFrames, parsed datasets,
analysis results) between requests. Serializing them through ``dcc.Store``
sends them all the way to the browser, which is both slow and breaks for
DataFrames over a few MB. Instead we keep them in a server-side dict keyed
by a short opaque token (``rkey``).

The original implementation kept everything only in RAM, which meant
**every restart of the Dash app wiped the cache and broke any previously
generated download URL** (``/dl/<rkey>/...``). This module preserves the
same public API (``save`` / ``load`` / ``clear``) but adds a transparent
write-through layer to disk so entries survive restarts.

Layout
------
- In-memory hot cache (``_CACHE``) — same shape as before.
- Disk-backed cold cache in ``$ALETHEIA_CACHE_DIR`` (defaults to
  ``~/.aletheia_cache/``). One pickle file per entry: ``<rkey>.pkl``.
- ``load()`` checks memory first, falls back to disk; corrupted pickles
  are removed silently (logged to stderr) so a bad file never poisons
  the whole UI.

Tuning
------
- ``ALETHEIA_CACHE_DIR``           — override storage location.
- ``ALETHEIA_CACHE_DISABLE_DISK``  — set to ``1`` to opt out of disk
                                     persistence (legacy in-memory mode).
- ``ALETHEIA_CACHE_TTL_DAYS``      — entries older than this are pruned
                                     opportunistically on ``save()``;
                                     defaults to 30, set to ``0`` to
                                     never expire.
"""
from __future__ import annotations

import os
import pickle
import sys
import time
import uuid
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _resolve_cache_dir() -> Path:
    env = os.environ.get("ALETHEIA_CACHE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".aletheia_cache"


def _disk_enabled() -> bool:
    return os.environ.get("ALETHEIA_CACHE_DISABLE_DISK", "").strip() not in ("1", "true", "yes")


def _ttl_seconds() -> Optional[float]:
    raw = os.environ.get("ALETHEIA_CACHE_TTL_DAYS", "30").strip()
    try:
        days = float(raw)
    except ValueError:
        days = 30.0
    return None if days <= 0 else days * 86400.0


CACHE_DIR = _resolve_cache_dir()
DISK_ENABLED = _disk_enabled()

if DISK_ENABLED:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[cache] WARNING: cannot create {CACHE_DIR}: {exc}. "
              f"Falling back to in-memory cache only.", file=sys.stderr)
        DISK_ENABLED = False


_CACHE: dict = {}


def _path_for(key: str) -> Path:
    return CACHE_DIR / f"{key}.pkl"


def _write_to_disk(key: str, data: dict) -> None:
    if not DISK_ENABLED:
        return
    path = _path_for(key)
    tmp_path = path.with_suffix(".pkl.tmp")
    try:
        with tmp_path.open("wb") as fh:
            pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(path)
    except Exception as exc:
        print(f"[cache] WARNING: could not persist {key}: {exc}", file=sys.stderr)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _read_from_disk(key: str) -> Optional[dict]:
    if not DISK_ENABLED:
        return None
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            return pickle.load(fh)
    except Exception as exc:
        print(f"[cache] WARNING: dropping corrupted cache entry {key}: {exc}",
              file=sys.stderr)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _prune_expired(now: Optional[float] = None) -> None:
    if not DISK_ENABLED:
        return
    ttl = _ttl_seconds()
    if ttl is None:
        return
    if now is None:
        now = time.time()
    try:
        for path in CACHE_DIR.glob("*.pkl"):
            try:
                age = now - path.stat().st_mtime
                if age > ttl:
                    path.unlink(missing_ok=True)
            except Exception:
                continue
    except Exception:
        return


def save(data: dict) -> str:
    """Store ``data`` in the cache and return its short ID."""
    key = str(uuid.uuid4())[:8]
    _CACHE[key] = data
    _write_to_disk(key, data)
    _prune_expired()
    return key


def load(key: str) -> Optional[dict]:
    """Retrieve a cache entry by key (memory -> disk fallback)."""
    if key in _CACHE:
        return _CACHE[key]
    data = _read_from_disk(key)
    if data is not None:
        _CACHE[key] = data
    return data


def clear(key: str) -> None:
    """Forget a cache entry both in memory and on disk."""
    _CACHE.pop(key, None)
    if DISK_ENABLED:
        try:
            _path_for(key).unlink(missing_ok=True)
        except Exception:
            pass


def keys() -> list:
    """Return all cache keys currently known (memory union disk)."""
    seen = set(_CACHE.keys())
    if DISK_ENABLED:
        try:
            for path in CACHE_DIR.glob("*.pkl"):
                seen.add(path.stem)
        except Exception:
            pass
    return sorted(seen)
