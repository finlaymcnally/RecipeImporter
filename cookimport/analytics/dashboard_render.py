"""Render the static analytics dashboard."""

from __future__ import annotations

import json
from pathlib import Path
import re

from cookimport.analytics.dashboard_renderers.html_shell import _HTML
from cookimport.analytics.dashboard_renderers.script_bootstrap import _JS_BOOTSTRAP
from cookimport.analytics.dashboard_renderers.script_compare_control import _JS_COMPARE_CONTROL
from cookimport.analytics.dashboard_renderers.style_asset import _CSS
from cookimport.analytics.dashboard_schema import DashboardData

_ASSET_JS_DIR = Path(__file__).resolve().parent / "dashboard_renderers" / "assets"


def _read_asset_js(asset_name: str) -> str:
    return (_ASSET_JS_DIR / asset_name).read_text(encoding="utf-8")


def render_dashboard(out_dir: Path, data: DashboardData) -> Path:
    """Write dashboard files and return the path to ``index.html``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    data_json = data.model_dump_json(indent=2)
    asset_version = re.sub(r"[^A-Za-z0-9]+", "-", data.generated_at).strip("-")
    if not asset_version:
        asset_version = data.schema_version or "dashboard"

    (assets_dir / "dashboard_data.json").write_text(data_json, encoding="utf-8")
    ui_state_path = assets_dir / "dashboard_ui_state.json"
    if not ui_state_path.exists():
        ui_state_path.write_text(
            json.dumps({"version": 1}, indent=2) + "\n",
            encoding="utf-8",
        )

    dashboard_js = "".join(
        (
            _JS_BOOTSTRAP,
            _read_asset_js("script_filters.js"),
            _JS_COMPARE_CONTROL,
            _read_asset_js("script_tables.js"),
        )
    )
    (assets_dir / "style.css").write_text(_CSS, encoding="utf-8")
    (assets_dir / "dashboard.js").write_text(dashboard_js, encoding="utf-8")

    html_path = out_dir / "index.html"
    html_path.write_text(
        _HTML
        .replace("__DASHBOARD_DATA_INLINE__", data_json.replace("</", "<\\/"))
        .replace("__ASSET_VERSION__", asset_version),
        encoding="utf-8",
    )
    return html_path


__all__ = ["render_dashboard"]
