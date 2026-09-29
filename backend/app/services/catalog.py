"""Operator-maintained service destinations and project catalog."""

import json
import os
from pathlib import Path
from functools import lru_cache

from app.models.catalog import Catalog


def catalog_model() -> Catalog:
    path = Path(os.getenv("DASHBOARD_CATALOG_PATH", str(
        Path(__file__).resolve().parents[3] / "config" / "catalog.json"
    )))
    stat = path.stat()
    return validated_catalog(str(path), (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))


@lru_cache(maxsize=8)
def validated_catalog(path: str, fingerprint: tuple) -> Catalog:
    # Any edit or atomic replacement invalidates the cached validation result.
    return Catalog.model_validate(json.loads(Path(path).read_text()))


def read_catalog() -> dict:
    return catalog_model().model_dump(mode='json')
