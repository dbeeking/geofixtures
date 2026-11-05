"""Rewrite catalog.lock.json after an intentional case change."""

from __future__ import annotations

import json
from pathlib import Path

from test_catalog_lock import LOCK, catalog_digests

if __name__ == "__main__":
    Path(LOCK).write_text(json.dumps(catalog_digests(), indent=2, sort_keys=True) + "\n")
