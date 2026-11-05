"""Load adapters by name, entry point, or module path."""

from __future__ import annotations

import importlib
from importlib import metadata
from typing import Any

from ..models import AdapterError
from ..runner.protocol import Adapter

_BUILT_IN = {
    "reference": "geofixtures.adapters.reference:ReferenceAdapter",
    "landfuse": "geofixtures.adapters.landfuse:LandFuseAdapter",
}


def _load_path(path: str) -> Any:
    module_name, _, attribute = path.partition(":")
    if not attribute:
        raise AdapterError(f"Adapter path needs module:Class, got {path!r}")
    try:
        return getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise AdapterError(f"Couldn't load adapter {path!r}: {exc}") from exc


def load_adapter(adapter: str | Adapter) -> Adapter:
    """Return an adapter from an instance, a registered name, or module:Class."""
    if not isinstance(adapter, str):
        return adapter
    if adapter in _BUILT_IN:
        return _load_path(_BUILT_IN[adapter])()  # type: ignore[no-any-return]
    for entry_point in metadata.entry_points(group="geofixtures.adapters"):
        if entry_point.name == adapter:
            return entry_point.load()()  # type: ignore[no-any-return]
    if ":" in adapter:
        return _load_path(adapter)()  # type: ignore[no-any-return]
    raise AdapterError(f"Unknown adapter: {adapter}")
