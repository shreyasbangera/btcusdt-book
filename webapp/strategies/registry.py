"""Finds every Strategy subclass in this package."""
import importlib, pkgutil, inspect
from .base import Strategy

_CACHE = {}


def discover():
    if _CACHE:
        return _CACHE
    pkg = importlib.import_module(__package__)
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in ("base", "registry"):
            continue
        mod = importlib.import_module(f"{__package__}.{m.name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Strategy) and obj is not Strategy:
                _CACHE[obj.name] = obj
    return _CACHE


def get(name):
    d = discover()
    if name not in d:
        raise KeyError(f"unknown strategy {name!r}; have {sorted(d)}")
    return d[name]
