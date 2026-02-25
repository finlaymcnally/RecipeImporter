from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from cookimport.parsing.block_roles import assign_block_roles
from cookimport.parsing.extraction_quality import score_blocks
from cookimport.plugins import registry


@dataclass(frozen=True)
class AutoExtractorResolution:
    effective_extractor: str
    artifact: dict[str, Any]


def select_epub_extractor_auto(
    path: Path,
    *,
    candidate_extractors: Sequence[str] = ("unstructured", "markdown", "beautifulsoup"),
) -> AutoExtractorResolution:
    importer = registry.get_importer("epub")
    if importer is None:
        raise RuntimeError("No EPUB importer registered; cannot resolve --epub-extractor auto.")

    if not hasattr(importer, "inspect") or not hasattr(importer, "_extract_docpack"):
        raise RuntimeError("EPUB importer does not expose required auto-selection hooks.")

    inspection = importer.inspect(path)
    spine_count = _resolve_spine_count(inspection)
    sample_indices = _choose_sample_indices(spine_count)

    candidate_rows: list[dict[str, Any]] = []
    successful: list[dict[str, Any]] = []

    for order_index, backend in enumerate(candidate_extractors):
        backend = str(backend).strip().lower()
        sample_rows: list[dict[str, Any]] = []
        error_message: str | None = None

        for sample_index in sample_indices:
            try:
                blocks = importer._extract_docpack(  # noqa: SLF001
                    path,
                    start_spine=sample_index,
                    end_spine=sample_index + 1,
                    extractor=backend,
                )
                assign_block_roles(blocks)
                score = score_blocks(blocks)
                sample_rows.append(
                    {
                        "spine_index": sample_index,
                        "score": score.score,
                        "reasons": score.reasons,
                        "stats": score.stats,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc)
                break

        if error_message is not None:
            candidate_rows.append(
                {
                    "backend": backend,
                    "status": "failed",
                    "order_index": order_index,
                    "error": error_message,
                    "samples": sample_rows,
                }
            )
            continue

        average_score = mean(row["score"] for row in sample_rows) if sample_rows else 0.0
        row = {
            "backend": backend,
            "status": "ok",
            "order_index": order_index,
            "average_score": average_score,
            "samples": sample_rows,
        }
        candidate_rows.append(row)
        successful.append(row)

    if not successful:
        artifact = {
            "requested_extractor": "auto",
            "effective_extractor": None,
            "candidate_extractors": [str(value) for value in candidate_extractors],
            "sample_indices": sample_indices,
            "candidates": candidate_rows,
            "selected_reason": "all_backends_failed",
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        raise RuntimeError(
            "Auto extractor selection failed because all candidate backends errored."
            f" Details: {json.dumps(artifact, ensure_ascii=True)}"
        )

    best = max(
        successful,
        key=lambda row: (float(row.get("average_score", 0.0)), -int(row["order_index"])),
    )
    selected_backend = str(best["backend"])

    artifact = {
        "requested_extractor": "auto",
        "effective_extractor": selected_backend,
        "candidate_extractors": [str(value) for value in candidate_extractors],
        "sample_indices": sample_indices,
        "candidates": candidate_rows,
        "selected_reason": "highest_average_score_then_candidate_order",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    return AutoExtractorResolution(
        effective_extractor=selected_backend,
        artifact=artifact,
    )


def write_auto_extractor_artifact(
    *,
    run_root: Path,
    source_hash: str,
    artifact: dict[str, Any],
) -> Path:
    target = run_root / "raw" / "epub" / source_hash / "epub_extractor_auto.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    return target


def selected_auto_score(artifact: Mapping[str, Any] | None) -> float | None:
    """Return the selected candidate score from an auto-selection artifact."""
    if not isinstance(artifact, Mapping):
        return None

    selected_backend = str(artifact.get("effective_extractor") or "").strip().lower()
    if not selected_backend:
        return None

    raw_candidates = artifact.get("candidates")
    if not isinstance(raw_candidates, Sequence):
        return None

    for candidate in raw_candidates:
        if not isinstance(candidate, Mapping):
            continue
        backend = str(candidate.get("backend") or "").strip().lower()
        if backend != selected_backend:
            continue
        if str(candidate.get("status") or "").strip().lower() != "ok":
            continue
        try:
            return float(candidate.get("average_score"))
        except (TypeError, ValueError):
            return None
    return None


def _resolve_spine_count(inspection: Any) -> int:
    sheets = getattr(inspection, "sheets", None)
    if not sheets:
        return 1
    raw_spine_count = getattr(sheets[0], "spine_count", None)
    if raw_spine_count is None:
        return 1
    try:
        parsed = int(raw_spine_count)
    except (TypeError, ValueError):
        return 1
    return max(parsed, 1)


def _choose_sample_indices(spine_count: int) -> list[int]:
    if spine_count <= 0:
        return [0]

    last_index = max(0, spine_count - 1)
    candidates = [0, 1, spine_count // 2, max(0, last_index - 1), last_index]
    indices: list[int] = []
    seen: set[int] = set()
    for value in candidates:
        bounded = min(max(int(value), 0), last_index)
        if bounded in seen:
            continue
        seen.add(bounded)
        indices.append(bounded)
    return indices or [0]
