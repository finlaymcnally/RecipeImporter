from __future__ import annotations

import json
import re
from pathlib import Path

from cookimport.analytics.dashboard_renderers.index_page import write_index_page
from cookimport.analytics.dashboard_renderers.templates import _CSS, _JS
from cookimport.analytics.dashboard_schema import DashboardData


def render_dashboard(out_dir: Path, data: DashboardData) -> Path:
    """Write dashboard files and return the path to ``index.html``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    data_json = data.model_dump_json(indent=2)
    asset_version = re.sub(r"[^A-Za-z0-9]+", "-", data.generated_at).strip("-")
    if not asset_version:
        asset_version = data.schema_version or "dashboard"

    data_path = assets_dir / "dashboard_data.json"
    data_path.write_text(data_json, encoding="utf-8")

    ui_state_path = assets_dir / "dashboard_ui_state.json"
    if not ui_state_path.exists():
        ui_state_path.write_text(
            json.dumps({"version": 1}, indent=2) + "\n",
            encoding="utf-8",
        )

    (assets_dir / "style.css").write_text(_CSS, encoding="utf-8")
    (assets_dir / "dashboard.js").write_text(_JS, encoding="utf-8")

    return write_index_page(out_dir=out_dir, data_json=data_json, asset_version=asset_version)
