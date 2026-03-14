from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

from cookimport.paths import history_root_for_output

from .run_settings import RunSettings

logger = logging.getLogger(__name__)

_QUALITYSUITE_WINNER_STORE_FILENAME = "qualitysuite_winner_run_settings.json"


def _qualitysuite_winner_store_path(output_dir: Path) -> Path:
    return history_root_for_output(output_dir) / _QUALITYSUITE_WINNER_STORE_FILENAME


def _legacy_qualitysuite_winner_store_path(output_dir: Path) -> Path:
    return output_dir / ".history" / _QUALITYSUITE_WINNER_STORE_FILENAME


def _legacy_qualitysuite_winner_store_paths(output_dir: Path) -> tuple[Path, ...]:
    return (
        _legacy_qualitysuite_winner_store_path(output_dir),
        output_dir.parent / ".history" / _QUALITYSUITE_WINNER_STORE_FILENAME,
    )


def _load_run_settings_file(path: Path, *, warn_context: str) -> RunSettings | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring corrupt %s settings file %s: %s", warn_context, path, exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("Ignoring invalid %s settings payload in %s", warn_context, path)
        return None

    data = payload.get("run_settings")
    if isinstance(data, dict):
        return RunSettings.from_dict(data, warn_context=f"{warn_context} settings")
    return RunSettings.from_dict(payload, warn_context=f"{warn_context} settings")


def _write_run_settings_file(path: Path, settings: RunSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": 1,
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "run_settings": settings.model_dump(mode="json", exclude_none=True),
        "operator_run_settings": settings.to_operator_run_config_dict(),
        "operator_run_settings_summary": settings.summary(contract="operator"),
        "product_run_settings_summary": settings.summary(contract="product"),
    }
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def load_qualitysuite_winner_run_settings(output_dir: Path) -> RunSettings | None:
    path = _qualitysuite_winner_store_path(output_dir)
    if not path.is_file():
        for legacy in _legacy_qualitysuite_winner_store_paths(output_dir):
            if legacy.is_file():
                path = legacy
                break
        else:
            return None
    return _load_run_settings_file(path, warn_context="qualitysuite winner")


def save_qualitysuite_winner_run_settings(
    output_dir: Path,
    settings: RunSettings,
) -> None:
    _write_run_settings_file(_qualitysuite_winner_store_path(output_dir), settings)
