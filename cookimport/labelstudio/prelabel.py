from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol

from cookimport.labelstudio.freeform_tasks import map_span_offsets_to_blocks
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABEL_CONTROL_NAME,
    FREEFORM_LABEL_RESULT_TYPE,
    FREEFORM_TEXT_NAME,
    normalize_freeform_label,
)


class LlmProvider(Protocol):
    """Small interface for LLM completion providers."""

    def complete(self, prompt: str) -> str:
        """Return raw model output."""


class CodexCliProvider:
    """Run a local Codex-style CLI command and cache prompt/response pairs."""

    def __init__(
        self,
        *,
        cmd: str,
        timeout_s: int,
        cache_dir: Path | None = None,
    ) -> None:
        normalized_cmd = cmd.strip()
        if not normalized_cmd:
            raise ValueError("codex command cannot be empty")
        self.cmd = normalized_cmd
        self.timeout_s = max(1, int(timeout_s))
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "cookimport" / "prelabel"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def complete(self, prompt: str) -> str:
        cache_key = hashlib.sha256(
            f"{self.cmd}\n{prompt}".encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                response = cached.get("response")
                if isinstance(response, str):
                    return response
            except (json.JSONDecodeError, OSError):
                pass

        argv = shlex.split(self.cmd)
        if not argv:
            raise RuntimeError(f"Unable to parse codex command: {self.cmd!r}")

        completed = subprocess.run(
            argv,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.timeout_s,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or "unknown error"
            raise RuntimeError(
                f"Codex command failed (exit={completed.returncode}): {detail}"
            )

        response = completed.stdout.strip()
        if not response:
            raise RuntimeError("Codex command returned empty stdout")

        try:
            cache_path.write_text(
                json.dumps(
                    {
                        "cmd": self.cmd,
                        "prompt": prompt,
                        "response": response,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return response


def extract_first_json_value(raw: str) -> Any:
    """Extract the first JSON array/object embedded in model output."""
    decoder = json.JSONDecoder()
    for index, ch in enumerate(raw):
        if ch not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("No JSON object/array found in model output")


def _coerce_selection_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("selections", "labels", "items", "blocks"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def parse_block_label_output(raw: str) -> list[dict[str, Any]]:
    """Parse model output into `{block_index, label}` records."""
    payload = extract_first_json_value(raw)
    items = _coerce_selection_items(payload)
    parsed: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for item in items:
        block_index_raw = item.get("block_index")
        label_raw = item.get("label") or item.get("tag") or item.get("category")
        if block_index_raw is None or not label_raw:
            continue
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        label = normalize_freeform_label(str(label_raw))
        key = (block_index, label)
        if key in seen:
            continue
        seen.add(key)
        parsed.append({"block_index": block_index, "label": label})
    return parsed


def _extract_task_data(task: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError("task missing data object")
    segment_id = str(data.get("segment_id") or "")
    if not segment_id:
        raise ValueError("task missing data.segment_id")
    segment_text = str(data.get("segment_text") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing data.source_map")
    blocks = source_map.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("task source_map.blocks missing/empty")
    source_blocks = [item for item in blocks if isinstance(item, dict)]
    if not source_blocks:
        raise ValueError("task source_map.blocks has no valid entries")
    return segment_id, segment_text, source_blocks


def _build_block_map(task: dict[str, Any]) -> dict[int, tuple[int, int]]:
    _segment_id, segment_text, source_blocks = _extract_task_data(task)
    block_map: dict[int, tuple[int, int]] = {}
    for item in source_blocks:
        block_index_raw = item.get("block_index")
        start_raw = item.get("segment_start")
        end_raw = item.get("segment_end")
        try:
            block_index = int(block_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        block_map[block_index] = (start, end)
    return block_map


def _result_key(result_item: dict[str, Any]) -> tuple[str, int, int]:
    value = result_item.get("value")
    if not isinstance(value, dict):
        return ("", -1, -1)
    labels = value.get("labels")
    if not isinstance(labels, list) or not labels:
        return ("", -1, -1)
    label = normalize_freeform_label(str(labels[0]))
    try:
        start = int(value.get("start"))
        end = int(value.get("end"))
    except (TypeError, ValueError):
        return ("", -1, -1)
    return (label, start, end)


def merge_annotation_results(
    base_results: list[dict[str, Any]],
    new_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge base + new span results, deduping exact label/range duplicates."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in [*base_results, *new_results]:
        if not isinstance(item, dict):
            continue
        key = _result_key(item)
        if key in seen or key[1] < 0:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def select_latest_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the latest annotation attached to a Label Studio task."""
    annotations = task.get("annotations") or task.get("completions") or []
    if not isinstance(annotations, list):
        return None
    candidates = [item for item in annotations if isinstance(item, dict)]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("id") or 0)
    return candidates[-1]


def annotation_labels(annotation: dict[str, Any] | None) -> set[str]:
    """Return canonical label names used in an annotation."""
    if not isinstance(annotation, dict):
        return set()
    labels: set[str] = set()
    for item in annotation.get("result") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        for label in value.get("labels") or []:
            labels.add(normalize_freeform_label(str(label)))
    return labels


def _build_annotation_result_item(
    *,
    segment_id: str,
    segment_text: str,
    block_index: int,
    start: int,
    end: int,
    label: str,
) -> dict[str, Any]:
    text = segment_text[start:end]
    digest = hashlib.sha256(
        f"{segment_id}|{block_index}|{start}|{end}|{label}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": f"cookimport-prelabel-{digest}",
        "from_name": FREEFORM_LABEL_CONTROL_NAME,
        "to_name": FREEFORM_TEXT_NAME,
        "type": FREEFORM_LABEL_RESULT_TYPE,
        "value": {
            "start": start,
            "end": end,
            "text": text,
            "labels": [label],
        },
    }


def _annotation_to_block_labels(
    *,
    annotation: dict[str, Any] | None,
    source_map: dict[str, Any],
) -> dict[int, set[str]]:
    block_labels: dict[int, set[str]] = {}
    if not isinstance(annotation, dict):
        return block_labels
    for item in annotation.get("result") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        labels = value.get("labels")
        if not isinstance(labels, list) or not labels:
            continue
        label = normalize_freeform_label(str(labels[0]))
        try:
            start = int(value.get("start"))
            end = int(value.get("end"))
        except (TypeError, ValueError):
            continue
        for touched in map_span_offsets_to_blocks(source_map, start, end):
            if not isinstance(touched, dict):
                continue
            block_index_raw = touched.get("block_index")
            try:
                block_index = int(block_index_raw)
            except (TypeError, ValueError):
                continue
            block_labels.setdefault(block_index, set()).add(label)
    return block_labels


def _build_prompt(
    *,
    task: dict[str, Any],
    allowed_labels: set[str],
    mode: str,
    augment_only_labels: set[str] | None,
    base_annotation: dict[str, Any] | None,
) -> str:
    data = task.get("data") if isinstance(task, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("task missing data")
    segment_text = str(data.get("segment_text") or "")
    segment_id = str(data.get("segment_id") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing source_map")
    blocks = source_map.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("task source_map.blocks missing")

    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_index_raw = block.get("block_index")
        start_raw = block.get("segment_start")
        end_raw = block.get("segment_end")
        try:
            block_index = int(block_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        block_text = segment_text[start:end]
        lines.append(
            json.dumps(
                {"block_index": block_index, "text": block_text},
                ensure_ascii=False,
            )
        )

    mode_suffix = ""
    if mode == "augment":
        add_labels = sorted(augment_only_labels or [])
        mode_suffix = (
            "\nMode: augment existing annotations.\n"
            f"Only add labels from: {', '.join(add_labels) if add_labels else '(none)'}.\n"
        )
        existing = _annotation_to_block_labels(
            annotation=base_annotation,
            source_map=source_map,
        )
        if existing:
            existing_rows = "\n".join(
                f"- block_index={block_index}: {sorted(labels)}"
                for block_index, labels in sorted(existing.items())
            )
            mode_suffix += f"Existing labels per block:\n{existing_rows}\n"
        else:
            mode_suffix += "Existing labels per block: (none)\n"

    return (
        "You label cookbook text blocks.\n"
        "Return STRICT JSON only.\n"
        "Output format: "
        '[{"block_index": <int>, "label": "<LABEL>"}].\n'
        f"Allowed labels: {', '.join(sorted(allowed_labels))}.\n"
        f"Segment id: {segment_id}\n"
        f"{mode_suffix}"
        "Blocks:\n"
        + "\n".join(lines)
    )


def prelabel_freeform_task(
    task: dict[str, Any],
    *,
    provider: LlmProvider,
    allowed_labels: set[str] | None = None,
    mode: str = "full",
    augment_only_labels: set[str] | None = None,
    base_annotation: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Generate one Label Studio annotation from LLM block-label suggestions."""
    if mode not in {"full", "augment"}:
        raise ValueError("mode must be 'full' or 'augment'")

    normalized_allowed = {
        normalize_freeform_label(label)
        for label in (allowed_labels or set(FREEFORM_ALLOWED_LABELS))
    }
    normalized_allowed = {
        label for label in normalized_allowed if label in FREEFORM_ALLOWED_LABELS
    }
    if not normalized_allowed:
        raise ValueError("allowed_labels cannot be empty")

    normalized_augment_only: set[str] | None = None
    if augment_only_labels is not None:
        normalized_augment_only = {
            normalize_freeform_label(label) for label in augment_only_labels
        }
        normalized_augment_only &= normalized_allowed
        if not normalized_augment_only:
            return None

    segment_id, segment_text, _source_blocks = _extract_task_data(task)
    block_map = _build_block_map(task)
    if not block_map:
        raise ValueError("task source_map has no valid block offsets")

    prompt = _build_prompt(
        task=task,
        allowed_labels=normalized_allowed,
        mode=mode,
        augment_only_labels=normalized_augment_only,
        base_annotation=base_annotation,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    raw = provider.complete(prompt)
    selections = parse_block_label_output(raw)
    if not selections:
        return None

    existing_results = (
        list(base_annotation.get("result") or [])
        if isinstance(base_annotation, dict)
        else []
    )
    existing_keys = {_result_key(item) for item in existing_results if isinstance(item, dict)}
    generated: list[dict[str, Any]] = []
    for selection in selections:
        block_index = int(selection["block_index"])
        label = normalize_freeform_label(str(selection["label"]))
        if label not in normalized_allowed:
            continue
        if mode == "augment" and normalized_augment_only is not None:
            if label not in normalized_augment_only:
                continue
        block_offsets = block_map.get(block_index)
        if block_offsets is None:
            continue
        start, end = block_offsets
        result_item = _build_annotation_result_item(
            segment_id=segment_id,
            segment_text=segment_text,
            block_index=block_index,
            start=start,
            end=end,
            label=label,
        )
        result_key = _result_key(result_item)
        if result_key in existing_keys:
            continue
        generated.append(result_item)
        existing_keys.add(result_key)

    if not generated:
        return None

    meta: dict[str, Any] = {
        "cookimport_prelabel": True,
        "mode": mode,
        "provider": provider.__class__.__name__,
        "prompt_hash": prompt_hash,
    }
    if normalized_augment_only:
        meta["added_labels"] = sorted(normalized_augment_only)
    return {
        "result": generated,
        "meta": meta,
    }


def annotation_is_cookimport_augment(
    annotation: dict[str, Any] | None,
    *,
    requested_labels: set[str],
) -> bool:
    """Return True when annotation metadata indicates this exact augment pass ran."""
    if not isinstance(annotation, dict):
        return False
    meta = annotation.get("meta")
    if not isinstance(meta, dict):
        return False
    if not meta.get("cookimport_prelabel"):
        return False
    if str(meta.get("mode") or "") != "augment":
        return False
    labels = meta.get("added_labels")
    if not isinstance(labels, list):
        return False
    normalized = {normalize_freeform_label(str(item)) for item in labels}
    wanted = {normalize_freeform_label(item) for item in requested_labels}
    return wanted.issubset(normalized)


def default_codex_cmd() -> str:
    """Resolve default codex command used by prelabel/decorate flows."""
    return os.environ.get("COOKIMPORT_CODEX_CMD", "codex")
