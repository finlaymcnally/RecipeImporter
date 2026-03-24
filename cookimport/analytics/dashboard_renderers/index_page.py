from __future__ import annotations

from pathlib import Path

from cookimport.analytics.dashboard_renderers.templates import _HTML


def write_index_page(*, out_dir: Path, data_json: str, asset_version: str) -> Path:
    html_path = out_dir / "index.html"
    html_data_json = data_json.replace("</", "<\/")
    html_path.write_text(
        _HTML
        .replace("__DASHBOARD_DATA_INLINE__", html_data_json)
        .replace("__ASSET_VERSION__", asset_version),
        encoding="utf-8",
    )
    return html_path
