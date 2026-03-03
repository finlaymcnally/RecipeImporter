"""Quality-suite models and deterministic representative target discovery."""

from __future__ import annotations

import datetime as dt
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cookimport.bench.speed_suite import match_gold_exports_to_inputs, resolve_repo_path
from cookimport.core.slug import slugify_name
from cookimport.paths import REPO_ROOT

_QUALITY_SELECTION_ALGORITHM_VERSION = "quality_representative_v2"
_DEFAULT_CURATED_QUALITY_TARGET_IDS = (
    "saltfatacidheatcutdown",
    "thefoodlabcutdown",
    "seaandsmokecutdown",
)
_QUALITY_SELECTION_MODE_CURATED = "curated_target_ids"
_QUALITY_SELECTION_MODE_REPRESENTATIVE = "representative_strata"
_SOURCE_EXTENSION_NONE = "__none__"
_SIZE_BUCKETS = ("small", "medium", "large")
_LABEL_BUCKETS = ("sparse", "medium", "dense")


class QualityTarget(BaseModel):
    """One quality target row with descriptor metadata."""

    target_id: str
    source_file: str
    gold_spans_path: str
    source_extension: str | None = None
    source_hint: str | None = None
    canonical_text_chars: int
    gold_span_rows: int
    label_count: int
    size_bucket: str
    label_bucket: str


class QualitySuite(BaseModel):
    """A deterministic quality-suite manifest."""

    name: str
    generated_at: str
    gold_root: str
    input_root: str
    seed: int
    max_targets: int | None
    selection: dict[str, Any]
    targets: list[QualityTarget] = Field(default_factory=list)
    selected_target_ids: list[str] = Field(default_factory=list)
    unmatched: list[dict[str, Any]] = Field(default_factory=list)


def discover_quality_suite(
    gold_root: Path,
    input_root: Path,
    *,
    max_targets: int | None = None,
    seed: int = 42,
    preferred_target_ids: list[str] | tuple[str, ...] | None = (
        _DEFAULT_CURATED_QUALITY_TARGET_IDS
    ),
    formats: list[str] | tuple[str, ...] | set[str] | None = None,
) -> QualitySuite:
    if max_targets is not None and max_targets < 1:
        raise ValueError("max_targets must be >= 1 when provided")

    gold_exports = _discover_freeform_gold_exports(gold_root)
    matched_targets, unmatched_targets = match_gold_exports_to_inputs(
        gold_exports,
        input_root=input_root,
        gold_root=gold_root,
    )
    if not matched_targets and unmatched_targets:
        matched_targets, unmatched_targets = match_gold_exports_to_inputs(
            gold_exports,
            input_root=input_root,
            gold_root=gold_root,
            importable_files=_list_input_files(input_root),
        )
    normalized_formats = _normalize_formats_filter(formats)
    if normalized_formats:
        matched_targets = _filter_targets_by_formats(
            matched_targets,
            allowed_formats=set(normalized_formats),
        )
    quality_targets = _annotate_quality_targets(matched_targets)
    selected_target_ids, selection_metadata = _select_quality_target_ids(
        quality_targets,
        max_targets=max_targets,
        seed=seed,
        preferred_target_ids=preferred_target_ids,
    )
    strata_counts = _build_strata_counts(quality_targets)
    format_counts = _build_format_counts(quality_targets)
    selected_format_counts = _build_selected_format_counts(
        quality_targets,
        selected_target_ids=selected_target_ids,
    )
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    selection_payload: dict[str, Any] = {
        "algorithm_version": _QUALITY_SELECTION_ALGORITHM_VERSION,
        "seed": int(seed),
        "max_targets": max_targets,
        "matched_count": len(quality_targets),
        "strata_counts": strata_counts,
        "format_counts": format_counts,
        "selected_format_counts": selected_format_counts,
        **selection_metadata,
    }
    if normalized_formats:
        selection_payload["formats_filter"] = normalized_formats
    return QualitySuite(
        name=f"quality_{slugify_name(gold_root.name)}",
        generated_at=timestamp,
        gold_root=_path_for_manifest(gold_root),
        input_root=_path_for_manifest(input_root),
        seed=int(seed),
        max_targets=max_targets,
        selection=selection_payload,
        targets=quality_targets,
        selected_target_ids=selected_target_ids,
        unmatched=unmatched_targets,
    )


def load_quality_suite(path: Path) -> QualitySuite:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return QualitySuite(**payload)


def write_quality_suite(path: Path, suite: QualitySuite) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        suite.model_dump_json(indent=2),
        encoding="utf-8",
    )


def validate_quality_suite(
    suite: QualitySuite,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    errors: list[str] = []
    seen_target_ids: set[str] = set()

    if not suite.targets:
        errors.append("Suite has no targets.")
        return errors

    targets_by_id: dict[str, QualityTarget] = {}
    for target in suite.targets:
        if target.target_id in seen_target_ids:
            errors.append(f"Duplicate target_id: {target.target_id}")
        seen_target_ids.add(target.target_id)
        targets_by_id[target.target_id] = target

        source_file = resolve_repo_path(target.source_file, repo_root=repo_root)
        if not source_file.exists() or not source_file.is_file():
            errors.append(
                f"[{target.target_id}] Source file not found: {target.source_file}"
            )

        gold_spans_path = resolve_repo_path(target.gold_spans_path, repo_root=repo_root)
        if not gold_spans_path.exists() or not gold_spans_path.is_file():
            errors.append(
                f"[{target.target_id}] Gold spans file not found: {target.gold_spans_path}"
            )

    if not suite.selected_target_ids:
        errors.append("Suite has no selected_target_ids.")
    else:
        seen_selected: set[str] = set()
        for target_id in suite.selected_target_ids:
            if target_id in seen_selected:
                errors.append(f"Duplicate selected target id: {target_id}")
                continue
            seen_selected.add(target_id)
            if target_id not in targets_by_id:
                errors.append(f"Selected target id not found in targets: {target_id}")

    return errors


def _discover_freeform_gold_exports(gold_root: Path) -> list[Path]:
    if not gold_root.exists():
        return []
    exports = [
        path
        for path in gold_root.glob("**/exports/freeform_span_labels.jsonl")
        if path.is_file()
    ]
    return sorted(exports, key=str)


def _list_input_files(input_root: Path) -> list[Path]:
    if not input_root.exists():
        return []
    return sorted(
        [
            path
            for path in input_root.glob("*")
            if path.is_file() and not path.name.startswith(".")
        ],
        key=str,
    )


def _annotate_quality_targets(
    matched_targets: list[Any],
) -> list[QualityTarget]:
    if not matched_targets:
        return []

    descriptor_rows: list[dict[str, Any]] = []
    for target in matched_targets:
        gold_spans_path = resolve_repo_path(str(target.gold_spans_path), repo_root=REPO_ROOT)
        canonical_text_chars = _canonical_text_size(gold_spans_path)
        gold_span_rows, label_count = _gold_rows_and_labels(gold_spans_path)
        descriptor_rows.append(
            {
                "target_id": str(target.target_id),
                "source_file": str(target.source_file),
                "gold_spans_path": str(target.gold_spans_path),
                "source_extension": _normalize_source_extension(
                    Path(str(target.source_file)).suffix
                ),
                "source_hint": target.source_hint,
                "canonical_text_chars": canonical_text_chars,
                "gold_span_rows": gold_span_rows,
                "label_count": label_count,
            }
        )

    size_by_id = _assign_tercile_buckets(
        {
            str(row["target_id"]): int(row["canonical_text_chars"])
            for row in descriptor_rows
        },
        bucket_names=_SIZE_BUCKETS,
    )
    label_by_id = _assign_tercile_buckets(
        {
            str(row["target_id"]): int(row["label_count"])
            for row in descriptor_rows
        },
        bucket_names=_LABEL_BUCKETS,
    )

    quality_targets: list[QualityTarget] = []
    for row in sorted(descriptor_rows, key=lambda item: str(item["target_id"])):
        target_id = str(row["target_id"])
        quality_targets.append(
            QualityTarget(
                target_id=target_id,
                source_file=str(row["source_file"]),
                gold_spans_path=str(row["gold_spans_path"]),
                source_extension=_normalize_source_extension(row.get("source_extension")),
                source_hint=row.get("source_hint"),
                canonical_text_chars=int(row["canonical_text_chars"]),
                gold_span_rows=int(row["gold_span_rows"]),
                label_count=int(row["label_count"]),
                size_bucket=size_by_id[target_id],
                label_bucket=label_by_id[target_id],
            )
        )
    return quality_targets


def _select_representative_target_ids(
    targets: list[QualityTarget],
    *,
    max_targets: int | None,
    seed: int,
) -> list[str]:
    if not targets:
        return []

    sorted_target_ids = [
        target.target_id for target in sorted(targets, key=lambda row: row.target_id)
    ]
    if max_targets is None or max_targets >= len(sorted_target_ids):
        return sorted_target_ids

    by_extension: dict[str, list[QualityTarget]] = defaultdict(list)
    for target in sorted(targets, key=lambda row: row.target_id):
        by_extension[_source_extension_key(target.source_extension)].append(target)

    if len(by_extension) <= 1:
        return _select_representative_target_ids_by_strata(
            targets,
            max_targets=max_targets,
            seed=seed,
        )

    rng = random.Random(int(seed))
    selected: list[str] = []
    selected_ids: set[str] = set()

    extension_order = sorted(by_extension)
    rng.shuffle(extension_order)
    extension_coverage = extension_order[: min(max_targets, len(extension_order))]
    for extension_key in extension_coverage:
        extension_target_ids = [
            target.target_id
            for target in sorted(by_extension[extension_key], key=lambda row: row.target_id)
        ]
        rng.shuffle(extension_target_ids)
        for target_id in extension_target_ids:
            if target_id in selected_ids:
                continue
            selected.append(target_id)
            selected_ids.add(target_id)
            break

    remaining_capacity = max_targets - len(selected)
    if remaining_capacity <= 0:
        return selected[:max_targets]

    remaining_targets = [
        target for target in targets if target.target_id not in selected_ids
    ]
    selected.extend(
        _select_representative_target_ids_by_strata(
            remaining_targets,
            max_targets=remaining_capacity,
            seed=seed,
        )
    )
    return selected[:max_targets]


def _select_representative_target_ids_by_strata(
    targets: list[QualityTarget],
    *,
    max_targets: int,
    seed: int,
) -> list[str]:
    if not targets or max_targets <= 0:
        return []

    rng = random.Random(int(seed))
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for target in targets:
        key = (target.size_bucket, target.label_bucket)
        strata[key].append(target.target_id)
    for key in strata:
        target_ids = sorted(strata[key])
        rng.shuffle(target_ids)
        strata[key] = target_ids

    selected: list[str] = []
    ordered_keys = sorted(strata)
    rng.shuffle(ordered_keys)
    while len(selected) < max_targets:
        progressed = False
        for key in ordered_keys:
            bucket_ids = strata[key]
            if not bucket_ids:
                continue
            selected.append(bucket_ids.pop(0))
            progressed = True
            if len(selected) >= max_targets:
                break
        if not progressed:
            break
    return selected[:max_targets]


def _select_quality_target_ids(
    targets: list[QualityTarget],
    *,
    max_targets: int | None,
    seed: int,
    preferred_target_ids: list[str] | tuple[str, ...] | None,
) -> tuple[list[str], dict[str, Any]]:
    normalized_preferred_ids = _normalize_target_ids(preferred_target_ids)
    if normalized_preferred_ids:
        target_ids = {target.target_id for target in targets}
        selected_preferred = [
            target_id
            for target_id in normalized_preferred_ids
            if target_id in target_ids
        ]
        missing_preferred = [
            target_id
            for target_id in normalized_preferred_ids
            if target_id not in target_ids
        ]
        if selected_preferred:
            selected_target_ids = selected_preferred
            representative_fill_target_ids: list[str] = []
            if max_targets is not None:
                selected_target_ids = selected_target_ids[: max_targets]
                remaining_capacity = max(0, max_targets - len(selected_target_ids))
            else:
                remaining_capacity = 0
            if remaining_capacity > 0:
                excluded_ids = set(selected_target_ids)
                remaining_targets = [
                    target
                    for target in targets
                    if target.target_id not in excluded_ids
                ]
                representative_fill_target_ids = _select_representative_target_ids(
                    remaining_targets,
                    max_targets=remaining_capacity,
                    seed=seed,
                )
                selected_target_ids.extend(representative_fill_target_ids)
            return selected_target_ids, {
                "selection_mode": _QUALITY_SELECTION_MODE_CURATED,
                "preferred_target_ids_requested": normalized_preferred_ids,
                "preferred_target_ids_selected": selected_preferred,
                "preferred_target_ids_missing": missing_preferred,
                "representative_fill_target_ids": representative_fill_target_ids,
            }

    return _select_representative_target_ids(
        targets,
        max_targets=max_targets,
        seed=seed,
    ), {
        "selection_mode": _QUALITY_SELECTION_MODE_REPRESENTATIVE,
        "preferred_target_ids_requested": normalized_preferred_ids,
        "preferred_target_ids_selected": [],
        "preferred_target_ids_missing": normalized_preferred_ids,
    }


def _normalize_target_ids(
    preferred_target_ids: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if not preferred_target_ids:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_target_id in preferred_target_ids:
        target_id = slugify_name(str(raw_target_id))
        if not target_id or target_id == "unknown" or target_id in seen:
            continue
        seen.add(target_id)
        normalized.append(target_id)
    return normalized


def _build_strata_counts(targets: list[QualityTarget]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for target in targets:
        counts[f"{target.size_bucket}:{target.label_bucket}"] += 1
    return dict(sorted(counts.items()))


def _build_format_counts(targets: list[QualityTarget]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for target in targets:
        counts[_source_extension_key(target.source_extension)] += 1
    return dict(sorted(counts.items()))


def _build_selected_format_counts(
    targets: list[QualityTarget],
    *,
    selected_target_ids: list[str],
) -> dict[str, int]:
    if not targets or not selected_target_ids:
        return {}
    selected_set = set(selected_target_ids)
    selected_targets = [target for target in targets if target.target_id in selected_set]
    return _build_format_counts(selected_targets)


def _filter_targets_by_formats(
    matched_targets: list[Any],
    *,
    allowed_formats: set[str],
) -> list[Any]:
    if not matched_targets or not allowed_formats:
        return matched_targets
    filtered: list[Any] = []
    for target in matched_targets:
        extension = _normalize_source_extension(Path(str(target.source_file)).suffix)
        if extension and extension in allowed_formats:
            filtered.append(target)
    return filtered


def _normalize_formats_filter(
    formats: list[str] | tuple[str, ...] | set[str] | None,
) -> list[str]:
    if not formats:
        return []
    normalized: set[str] = set()
    for raw_item in formats:
        tokens = str(raw_item or "").split(",")
        for token in tokens:
            extension = _normalize_source_extension(token)
            if extension:
                normalized.add(extension)
    return sorted(normalized)


def _source_extension_key(raw_extension: str | None) -> str:
    extension = _normalize_source_extension(raw_extension)
    return extension or _SOURCE_EXTENSION_NONE


def _normalize_source_extension(raw_extension: Any) -> str | None:
    cleaned = str(raw_extension or "").strip().lower()
    if not cleaned:
        return None
    if cleaned in {"none", "null", _SOURCE_EXTENSION_NONE}:
        return None
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    return cleaned


def _assign_tercile_buckets(
    values_by_target: dict[str, int],
    *,
    bucket_names: tuple[str, str, str],
) -> dict[str, str]:
    if not values_by_target:
        return {}

    ordered_values = sorted(max(0, int(value)) for value in values_by_target.values())
    total = len(ordered_values)
    low_index = max(0, math.ceil(total / 3.0) - 1)
    high_index = max(0, math.ceil((2.0 * total) / 3.0) - 1)
    low_cut = ordered_values[low_index]
    high_cut = ordered_values[high_index]

    by_target: dict[str, str] = {}
    for target_id, raw_value in values_by_target.items():
        value = max(0, int(raw_value))
        if value <= low_cut:
            by_target[target_id] = bucket_names[0]
        elif value <= high_cut:
            by_target[target_id] = bucket_names[1]
        else:
            by_target[target_id] = bucket_names[2]
    return by_target


def _canonical_text_size(gold_spans_path: Path) -> int:
    canonical_text_path = gold_spans_path.parent / "canonical_text.txt"
    if not canonical_text_path.exists() or not canonical_text_path.is_file():
        return 0
    try:
        return max(0, int(canonical_text_path.stat().st_size))
    except OSError:
        return 0


def _gold_rows_and_labels(gold_spans_path: Path) -> tuple[int, int]:
    if not gold_spans_path.exists() or not gold_spans_path.is_file():
        return 0, 0

    row_count = 0
    labels: set[str] = set()
    try:
        with gold_spans_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                row_count += 1
                try:
                    payload = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(payload, dict):
                    continue
                _collect_labels(payload.get("label"), labels)
                _collect_labels(payload.get("labels"), labels)
    except Exception:  # noqa: BLE001
        return row_count, len(labels)
    return row_count, len(labels)


def _collect_labels(raw_value: Any, labels: set[str]) -> None:
    if raw_value is None:
        return
    if isinstance(raw_value, (list, tuple, set)):
        for item in raw_value:
            _collect_labels(item, labels)
        return
    label = str(raw_value).strip()
    if label:
        labels.add(label)


def _path_for_manifest(path: Path) -> str:
    candidate = path.expanduser()
    try:
        return str(candidate.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(candidate)
