"""Paprastas Redis cache pagalbininkas: grąžina iš cache arba suskaičiuoja ir išsaugo."""
import json
from typing import Any, Callable

from .db import r


def cached(key: str, ttl: int, compute: Callable[[], Any]) -> Any:
    hit = r.get(key)
    if hit is not None:
        return json.loads(hit)
    value = compute()
    if value is not None:  # „nerasta“ necache'uojam – kitaip naujas įrašas būtų nematomas iki TTL pabaigos
        r.set(key, json.dumps(value, default=str), ex=ttl)
    return value


def invalidate(*keys: str) -> None:
    if keys:
        r.delete(*keys)
