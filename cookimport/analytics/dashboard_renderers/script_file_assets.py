from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=None)
def load_dashboard_script_asset(asset_name: str) -> str:
    return (_ASSETS_DIR / asset_name).read_text(encoding="utf-8")
