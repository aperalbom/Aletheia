"""
core/cache.py
Cache en memoria del servidor para resultados de análisis.
Evita serializar DataFrames grandes en dcc.Store (que los manda al navegador).
"""
import uuid

_CACHE = {}

def save(data: dict) -> str:
    """Guarda data en cache y devuelve un ID corto."""
    key = str(uuid.uuid4())[:8]
    _CACHE[key] = data
    return key

def load(key: str) -> dict:
    """Recupera data del cache por ID."""
    return _CACHE.get(key)

def clear(key: str):
    _CACHE.pop(key, None)
