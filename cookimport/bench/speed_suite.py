"""Speed-suite models and deterministic target discovery."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from cookimport.core.slug import slugify_name
from cookimport.paths import REPO_ROOT
from cookimport.plugins import registry


class SpeedTarget(BaseModel):
    """One speed target row: source file + gold spans export."""

    target_id: str
    source_file: str
    gold_spans_path: str
    source_hint: str | None = None
    notes: str | None = None


class SpeedSuite(BaseModel):
    """A deterministic speed-suite manifest."""

    name: str
    generated_at: str
    gold_root: str
    input_root: str
    targets: list[SpeedTarget] = Field(default_factory=list)
    unmatched: list[dict[str, Any]] = Field(default_factory=list)


def load_speed_suite(path: Path) -> SpeedSuite:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SpeedSuite(**payload)


def write_speed_suite(path: Path, suite: SpeedSuite) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        suite.model_dump_json(indent=2),
        encoding="utf-8",
    )


def resolve_repo_path(path_value: str, *, repo_root: Path = REPO_ROOT) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (repo_root / candidate).resolve()


def validate_speed_suite(
    suite: SpeedSuite,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    if not suite.targets:
        errors.append("Suite has no targets.")
        return errors

    for target in suite.targets:
        if target.target_id in seen_ids:
            errors.append(f"Duplicate target_id: {target.target_id}")
        seen_ids.add(target.target_id)

        source_file = resolve_repo_path(target.source_file, repo_root=repo_root)
        if not source_file.exists() or not source_file.is_file():
            errors.append(
                f"[{target.target_id}] Source file not found: {target.source_file}"
            )

        gold_spans_path = resolve_repo_path(
            target.gold_spans_path, repo_root=repo_root
        )
        if not gold_spans_path.exists() or not gold_spans_path.is_file():
            errors.append(
                f"[{target.target_id}] Gold spans file not found: "
                f"{target.gold_spans_path}"
            )

    return errors


def discover_speed_targets(gold_root: Path, input_root: Path) -> SpeedSuite:
    discovered, unmatched = match_gold_exports_to_inputs(
        _discover_freeform_gold_exports(gold_root),
        input_root=input_root,
        gold_root=gold_root,
    )
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    return SpeedSuite(
        name=f"speed_{slugify_name(gold_root.name)}",
        generated_at=timestamp,
        gold_root=_path_for_manifest(gold_root),
        input_root=_path_for_manifest(input_root),
        targets=discovered,
        unmatched=unmatched,
    )


def match_gold_exports_to_inputs(
    gold_spans_paths: Iterable[Path],
    *,
    input_root: Path,
    gold_root: Path | None = None,
    importable_files: Iterable[Path] | None = None,
) -> tuple[list[SpeedTarget], list[dict[str, Any]]]:
    importable_paths = (
        [Path(path) for path in importable_files]
        if importable_files is not None
        else _list_importable_files(input_root)
    )
    importable_by_name = {
        path.name: path
        for path in importable_paths
    }

    matched_targets: list[SpeedTarget] = []
    unmatched_targets: list[dict[str, Any]] = []
    seen_target_ids: set[str] = set()

    for gold_spans_path in sorted((Path(path) for path in gold_spans_paths), key=str):
        gold_display = _path_for_display(gold_spans_path, gold_root=gold_root)
        gold_manifest_path = _path_for_manifest(gold_spans_path)
        if not gold_spans_path.exists() or not gold_spans_path.is_file():
            unmatched_targets.append(
                {
                    "gold_spans_path": gold_manifest_path,
                    "gold_display": gold_display,
                    "reason": "Gold spans file is missing.",
                    "source_hint": None,
                }
            )
            continue

        source_hint = _load_source_hint_from_gold_export(gold_spans_path)
        if source_hint is None:
            unmatched_targets.append(
                {
                    "gold_spans_path": gold_manifest_path,
                    "gold_display": gold_display,
                    "reason": (
                        "Missing source hint in manifest, run_manifest, "
                        "freeform_span_labels.jsonl, and freeform_segment_manifest.jsonl."
                    ),
                    "source_hint": None,
                }
            )
            continue

        source_file = importable_by_name.get(source_hint)
        if source_file is None:
            unmatched_targets.append(
                {
                    "gold_spans_path": gold_manifest_path,
                    "gold_display": gold_display,
                    "reason": (
                        f"No importable file named `{source_hint}` in "
                        f"{_path_for_manifest(input_root)}."
                    ),
                    "source_hint": source_hint,
                }
            )
            continue

        matched_targets.append(
            SpeedTarget(
                target_id=_unique_target_id(
                    base=_target_id_for_gold(gold_spans_path),
                    seen=seen_target_ids,
                ),
                source_file=_path_for_manifest(source_file),
                gold_spans_path=gold_manifest_path,
                source_hint=source_hint,
                notes=None,
            )
        )

    return matched_targets, unmatched_targets


def _discover_freeform_gold_exports(gold_root: Path) -> list[Path]:
    if not gold_root.exists():
        return []
    exports = [
        path
        for path in gold_root.glob("**/exports/freeform_span_labels.jsonl")
        if path.is_file()
    ]
    return sorted(exports, key=str)


def _target_id_for_gold(gold_spans_path: Path) -> str:
    # .../<target>/exports/freeform_span_labels.jsonl
    target_dir_name = gold_spans_path.parent.parent.name
    return slugify_name(target_dir_name)


def _unique_target_id(*, base: str, seen: set[str]) -> str:
    if base not in seen:
        seen.add(base)
        return base
    suffix = 2
    while True:
        candidate = f"{base}_{suffix}"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
        suffix += 1


def _path_for_manifest(path: Path) -> str:
    candidate = path.expanduser()
    try:
        return str(candidate.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(candidate)


def _path_for_display(path: Path, *, gold_root: Path | None = None) -> str:
    if gold_root is not None:
        try:
            return str(path.relative_to(gold_root))
        except ValueError:
            pass
    return _path_for_manifest(path)


def _list_importable_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files: list[Path] = []
    for path in folder.glob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        _, score = registry.best_importer_for_path(path)
        if score > 0:
            files.append(path)
    return sorted(files)


def _load_manifest_source_file(gold_spans_path: Path) -> str | None:
    run_root = gold_spans_path.parent.parent
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists() and manifest_path.is_file():
        source_hint = _source_hint_from_manifest_payload(manifest_path)
        if source_hint is not None:
            return source_hint

    run_manifest_path = run_root / "run_manifest.json"
    if run_manifest_path.exists() and run_manifest_path.is_file():
        source_hint = _source_hint_from_manifest_payload(run_manifest_path)
        if source_hint is not None:
            return source_hint
    return None


def _source_hint_from_manifest_payload(manifest_path: Path) -> str | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None

    source_file = str(payload.get("source_file") or "").strip()
    if source_file:
        return source_file

    source_payload = payload.get("source")
    if isinstance(source_payload, dict):
        source_path = str(source_payload.get("path") or "").strip()
        if source_path:
            return source_path
    return None


def _first_source_file_from_jsonl(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(payload, dict):
                    continue
                source_file = str(payload.get("source_file") or "").strip()
                if source_file:
                    return source_file
    except Exception:  # noqa: BLE001
        return None
    return None


def _source_name_from_hint(source_hint: str | None) -> str | None:
    if source_hint is None:
        return None
    stripped = source_hint.strip()
    if not stripped:
        return None
    source_name = Path(stripped).name.strip()
    return source_name or None


def _load_source_hint_from_gold_export(gold_spans_path: Path) -> str | None:
    source_hint = _source_name_from_hint(_load_manifest_source_file(gold_spans_path))
    if source_hint is not None:
        return source_hint

    canonical_manifest_path = gold_spans_path.parent / "canonical_manifest.json"
    source_hint = _source_name_from_hint(
        _source_hint_from_manifest_payload(canonical_manifest_path)
    )
    if source_hint is not None:
        return source_hint

    source_hint = _source_name_from_hint(_first_source_file_from_jsonl(gold_spans_path))
    if source_hint is not None:
        return source_hint

    segment_manifest_path = gold_spans_path.parent / "freeform_segment_manifest.jsonl"
    return _source_name_from_hint(_first_source_file_from_jsonl(segment_manifest_path))
