from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .io import _load_json


def _timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H.%M.%S")


def _parse_run_timestamp(run_id: str) -> datetime | None:
    try:
        return datetime.strptime(run_id, "%Y-%m-%d_%H.%M.%S")
    except ValueError:
        return None


def _is_run_dir(path: Path) -> bool:
    return (path / "eval_report.json").is_file() and (path / "run_manifest.json").is_file()


def _is_ignored_dir(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if ".cache" in parts:
        return True
    for part in parts:
        if part.endswith("_cutdown") or part.endswith("_md"):
            return True
    return False


def _discover_run_dirs(input_dir: Path) -> list[Path]:
    discovered: dict[Path, None] = {}
    if _is_run_dir(input_dir):
        discovered[input_dir] = None

    for report_path in input_dir.rglob("eval_report.json"):
        run_dir = report_path.parent
        if _is_ignored_dir(run_dir):
            continue
        if _is_run_dir(run_dir):
            discovered[run_dir] = None

    return sorted(discovered.keys())


def _read_run_id_for_dir(run_dir: Path) -> str:
    manifest_path = run_dir / "run_manifest.json"
    try:
        manifest = _load_json(manifest_path)
    except Exception:
        return run_dir.name
    run_id = manifest.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    return run_dir.name


def _default_output_dir_from_runs(input_dir: Path, run_dirs: list[Path]) -> Path:
    run_ids = sorted({_read_run_id_for_dir(run_dir) for run_dir in run_dirs})
    timestamp_ids = sorted(
        run_id for run_id in run_ids if _parse_run_timestamp(run_id) is not None
    )
    if len(timestamp_ids) == 1:
        base_name = timestamp_ids[0]
    elif len(timestamp_ids) > 1:
        base_name = f"{timestamp_ids[0]}__to__{timestamp_ids[-1]}"
    else:
        base_name = input_dir.name
    return input_dir.parent / f"{base_name}_cutdown"
