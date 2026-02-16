from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Literal

from .run_settings import RunSettings

logger = logging.getLogger(__name__)

RunSettingsKind = Literal["import", "benchmark"]

_STORE_FILENAMES: dict[RunSettingsKind, str] = {
    "import": "last_run_settings_import.json",
    "benchmark": "last_run_settings_benchmark.json",
}


def _store_path(kind: RunSettingsKind, output_dir: Path) -> Path:
    return output_dir / ".history" / _STORE_FILENAMES[kind]


def load_last_run_settings(
    kind: RunSettingsKind,
    output_dir: Path,
) -> RunSettings | None:
    path = _store_path(kind, output_dir)
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring corrupt last-run settings file %s: %s", path, exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("Ignoring invalid last-run settings payload in %s", path)
        return None

    data = payload.get("run_settings")
    if isinstance(data, dict):
        return RunSettings.from_dict(data, warn_context=f"{kind} last-run settings")
    return RunSettings.from_dict(payload, warn_context=f"{kind} last-run settings")


def save_last_run_settings(
    kind: RunSettingsKind,
    output_dir: Path,
    settings: RunSettings,
) -> None:
    path = _store_path(kind, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": 1,
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "run_settings": settings.to_run_config_dict(),
    }
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)
