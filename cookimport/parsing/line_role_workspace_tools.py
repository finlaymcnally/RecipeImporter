from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.llm.canonical_line_role_prompt import build_line_role_label_code_by_label


_LABEL_CODE_BY_LABEL = build_line_role_label_code_by_label()
LINE_ROLE_LABEL_BY_CODE: dict[str, str] = {
    str(code): str(label)
    for label, code in _LABEL_CODE_BY_LABEL.items()
}
LINE_ROLE_ALLOWED_LABELS: tuple[str, ...] = tuple(
    label
    for label, _ in sorted(
        _LABEL_CODE_BY_LABEL.items(),
        key=lambda item: item[1],
    )
)
LINE_ROLE_WORKER_TOOL_FILENAME = "line_role_worker.py"
LINE_ROLE_VALID_OUTPUT_EXAMPLE_FILENAME = "valid_line_role_output.json"
LINE_ROLE_VALID_OUTPUT_EXAMPLE_PAYLOAD = {
    "rows": [
        {"atomic_index": 123, "label": "INGREDIENT_LINE"},
        {
            "atomic_index": 124,
            "label": "OTHER",
            "review_exclusion_reason": "navigation",
        },
    ]
}
LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN = """# Line-Role Output Contract

Use this workspace contract for every `out/<task_id>.json` file.

Required shape:

    {"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}

Rules:

- The file must be one JSON object with exactly one top-level key: `rows`.
- `rows` must be a JSON array.
- Return exactly one row for every owned input row from `in/<task_id>.json`.
- Keep output order identical to the input `rows` order.
- Each row object must use `atomic_index` and `label`, plus optional `review_exclusion_reason`.
- `atomic_index` must match the owned input row at the same position.
- `label` must be one of:
  `RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, `TIME_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `KNOWLEDGE`, `OTHER`
- `review_exclusion_reason`, when present, must be one of:
  `navigation`, `front_matter`, `publishing_metadata`, `copyright_legal`, `endorsement`, `page_furniture`
- Only use `review_exclusion_reason` on rows labeled `OTHER`, and only for overwhelmingly obvious non-recipe junk that should skip knowledge review.
- Do not emit context rows.
- Do not add commentary, markdown, or extra JSON keys.

Paved-road helper loop:

    open CURRENT_TASK.md
    open the metadata.scratch_draft_path named in current_task.json
    use hints/<task_id>.md for the targeted explanation
    open in/<task_id>.json only if the draft or hint is insufficient
    edit scratch/<task_id>.json only where the deterministic seed is wrong
    python3 tools/line_role_worker.py finalize scratch/<task_id>.json

Bulk completion when several drafts are ready:

    python3 tools/line_role_worker.py finalize-all scratch/

Fallback tools:

    python3 tools/line_role_worker.py overview
    python3 tools/line_role_worker.py show <task_id>
    python3 tools/line_role_worker.py prepare-all --dest-dir scratch/
    python3 tools/line_role_worker.py scaffold <task_id> --dest scratch/<task_id>.json
    python3 tools/line_role_worker.py check scratch/<task_id>.json
    python3 tools/line_role_worker.py finalize scratch/<task_id>.json
"""


def _coerce_task_row(task_row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(task_row or {})


def _coerce_metadata(task_row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = task_row.get("metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _load_task_input_payload(
    task_row: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    input_payload = task_row.get("input_payload")
    if isinstance(input_payload, Mapping):
        return dict(input_payload)
    if workspace_root is None:
        return {}
    metadata = _coerce_metadata(task_row)
    input_path = str(metadata.get("input_path") or "").strip()
    if not input_path:
        return {}
    try:
        payload = json.loads((workspace_root / input_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _coerce_input_rows(
    task_row: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> list[list[Any]]:
    rows = _load_task_input_payload(task_row, workspace_root=workspace_root).get("rows")
    if not isinstance(rows, list):
        return []
    normalized: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        normalized.append([row[0], row[1], row[2]])
    return normalized


def build_line_role_scratch_draft_path(task_id: str) -> str:
    cleaned_task_id = str(task_id or "").strip()
    return f"scratch/{cleaned_task_id}.json"


def build_line_role_workspace_task_metadata(
    *,
    task_id: str,
    parent_shard_id: str,
    input_payload: Mapping[str, Any] | None,
    input_path: str,
    hint_path: str,
    result_path: str,
    scratch_draft_path: str | None = None,
) -> dict[str, Any]:
    rows = []
    if isinstance(input_payload, Mapping):
        candidate_rows = input_payload.get("rows")
        if isinstance(candidate_rows, list):
            rows = candidate_rows
    owned_atomic_indices: list[int] = []
    deterministic_label_counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            continue
        owned_atomic_indices.append(atomic_index)
        deterministic_label = LINE_ROLE_LABEL_BY_CODE.get(str(row[1]).strip(), "OTHER")
        deterministic_label_counts[deterministic_label] += 1
    return {
        "phase_key": "line_role",
        "task_id": str(task_id),
        "parent_shard_id": str(parent_shard_id),
        "input_path": str(input_path),
        "hint_path": str(hint_path),
        "result_path": str(result_path),
        "scratch_draft_path": str(scratch_draft_path or build_line_role_scratch_draft_path(task_id)),
        "owned_row_count": len(owned_atomic_indices),
        "atomic_index_start": owned_atomic_indices[0] if owned_atomic_indices else None,
        "atomic_index_end": owned_atomic_indices[-1] if owned_atomic_indices else None,
        "deterministic_label_counts": dict(sorted(deterministic_label_counts.items())),
    }


def build_line_role_seed_output(task_row: Mapping[str, Any]) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    unknown_codes: list[str] = []
    for row in _coerce_input_rows(task_row):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("input row is missing a valid atomic_index") from exc
        label_code = str(row[1]).strip()
        label = LINE_ROLE_LABEL_BY_CODE.get(label_code)
        if label is None:
            unknown_codes.append(label_code or "<blank>")
            label = "OTHER"
        rows_payload.append(
            {
                "atomic_index": atomic_index,
                "label": label,
            }
        )
    if unknown_codes:
        rendered = ", ".join(sorted(set(unknown_codes)))
        raise ValueError(f"unknown line-role label code(s): {rendered}")
    return {"rows": rows_payload}


def build_line_role_seed_output_for_workspace(
    workspace_root: Path,
    task_row: Mapping[str, Any],
) -> dict[str, Any]:
    rows_payload: list[dict[str, Any]] = []
    unknown_codes: list[str] = []
    for row in _coerce_input_rows(task_row, workspace_root=workspace_root):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("input row is missing a valid atomic_index") from exc
        label_code = str(row[1]).strip()
        label = LINE_ROLE_LABEL_BY_CODE.get(label_code)
        if label is None:
            unknown_codes.append(label_code or "<blank>")
            label = "OTHER"
        rows_payload.append(
            {
                "atomic_index": atomic_index,
                "label": label,
            }
        )
    if unknown_codes:
        rendered = ", ".join(sorted(set(unknown_codes)))
        raise ValueError(f"unknown line-role label code(s): {rendered}")
    return {"rows": rows_payload}


def validate_line_role_output_payload(
    task_row: Mapping[str, Any],
    payload: Any,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    expected_rows = _coerce_input_rows(task_row)
    expected_atomic_indices: list[int] = []
    for row in expected_rows:
        try:
            expected_atomic_indices.append(int(row[0]))
        except (TypeError, ValueError):
            errors.append("invalid_input_atomic_index")
            return tuple(sorted(set(errors))), metadata
    metadata["owned_row_count"] = len(expected_atomic_indices)
    if not isinstance(payload, Mapping):
        return ("payload_not_object",), metadata
    extra_top_level_keys = sorted(
        key for key in payload.keys() if str(key) != "rows"
    )
    if extra_top_level_keys:
        errors.append("extra_top_level_keys")
        metadata["extra_top_level_keys"] = extra_top_level_keys
    rows_payload = payload.get("rows")
    if not isinstance(rows_payload, list):
        errors.append("rows_not_list")
        return tuple(sorted(set(errors))), metadata
    metadata["returned_row_count"] = len(rows_payload)
    if len(rows_payload) != len(expected_atomic_indices):
        errors.append("wrong_row_count")
    returned_atomic_indices: list[int] = []
    for row_payload in rows_payload:
        if not isinstance(row_payload, Mapping):
            errors.append("row_not_object")
            continue
        extra_row_keys = sorted(
            key
            for key in row_payload.keys()
            if str(key) not in {"atomic_index", "label", "review_exclusion_reason"}
        )
        if extra_row_keys:
            errors.append("extra_row_keys")
        try:
            returned_atomic_indices.append(int(row_payload.get("atomic_index")))
        except (TypeError, ValueError):
            errors.append("invalid_atomic_index")
        label = str(row_payload.get("label") or "").strip().upper()
        if label not in LINE_ROLE_ALLOWED_LABELS:
            errors.append("invalid_label")
        review_exclusion_reason = str(
            row_payload.get("review_exclusion_reason") or ""
        ).strip()
        if review_exclusion_reason:
            if label != "OTHER":
                errors.append("review_exclusion_reason_requires_other")
            if review_exclusion_reason not in {
                "navigation",
                "front_matter",
                "publishing_metadata",
                "copyright_legal",
                "endorsement",
                "page_furniture",
            }:
                errors.append("invalid_review_exclusion_reason")
    if returned_atomic_indices != expected_atomic_indices:
        if len(returned_atomic_indices) == len(expected_atomic_indices):
            errors.append("row_order_mismatch")
        else:
            errors.append("atomic_index_mismatch")
    metadata["expected_atomic_indices"] = expected_atomic_indices
    metadata["returned_atomic_indices"] = returned_atomic_indices
    return tuple(sorted(set(errors))), metadata


def render_line_role_task_overview(
    *,
    task_rows: Sequence[Mapping[str, Any]],
    current_task_id: str | None,
) -> str:
    lines = ["Line-role worker queue:"]
    for index, task_row in enumerate(task_rows, start=1):
        task_id = str(task_row.get("task_id") or "").strip() or f"task-{index:03d}"
        metadata = _coerce_metadata(task_row)
        owned_row_count = metadata.get("owned_row_count")
        atomic_start = metadata.get("atomic_index_start")
        atomic_end = metadata.get("atomic_index_end")
        counts = metadata.get("deterministic_label_counts")
        rendered_counts = (
            ", ".join(f"{label}={count}" for label, count in dict(counts).items())
            if isinstance(counts, Mapping) and counts
            else "unknown"
        )
        current_marker = " current" if task_id == str(current_task_id or "").strip() else ""
        lines.append(
            f"- {task_id}{current_marker}: rows={owned_row_count}, "
            f"atomic={atomic_start}..{atomic_end}, labels={rendered_counts}, "
            f"result={metadata.get('result_path') or 'unknown'}"
        )
    return "\n".join(lines) + "\n"


def render_line_role_task_show(task_row: Mapping[str, Any]) -> str:
    task_id = str(task_row.get("task_id") or "").strip() or "<unknown>"
    parent_shard_id = str(task_row.get("parent_shard_id") or "").strip() or "<unknown>"
    metadata = _coerce_metadata(task_row)
    lines = [
        f"task_id: {task_id}",
        f"parent_shard_id: {parent_shard_id}",
        f"input_path: {metadata.get('input_path') or '<missing>'}",
        f"hint_path: {metadata.get('hint_path') or '<missing>'}",
        f"result_path: {metadata.get('result_path') or '<missing>'}",
        f"scratch_draft_path: {metadata.get('scratch_draft_path') or '<missing>'}",
        f"owned_row_count: {metadata.get('owned_row_count')}",
        f"atomic_index_start: {metadata.get('atomic_index_start')}",
        f"atomic_index_end: {metadata.get('atomic_index_end')}",
    ]
    counts = metadata.get("deterministic_label_counts")
    if isinstance(counts, Mapping) and counts:
        lines.append(
            "deterministic_label_counts: "
            + ", ".join(f"{label}={count}" for label, count in dict(counts).items())
        )
    else:
        lines.append("deterministic_label_counts: none")
    return "\n".join(lines) + "\n"


def render_line_role_current_task_brief(task_row: Mapping[str, Any]) -> str:
    task_id = str(task_row.get("task_id") or "").strip() or "<unknown>"
    parent_shard_id = str(task_row.get("parent_shard_id") or "").strip() or "<unknown>"
    metadata = _coerce_metadata(task_row)
    counts = metadata.get("deterministic_label_counts")
    rendered_counts = (
        ", ".join(f"{label}={count}" for label, count in dict(counts).items())
        if isinstance(counts, Mapping) and counts
        else "unknown"
    )
    return "\n".join(
        [
            "# Current Line-Role Task",
            "",
            f"Task id: `{task_id}`",
            f"Parent shard: `{parent_shard_id}`",
            f"Owned rows: `{metadata.get('owned_row_count')}`",
            f"Atomic span: `{metadata.get('atomic_index_start')}..{metadata.get('atomic_index_end')}`",
            f"Deterministic labels: {rendered_counts}",
            "",
            "Read order:",
            f"1. Draft: `{metadata.get('scratch_draft_path') or '<missing>'}`",
            f"2. Hint: `{metadata.get('hint_path') or '<missing>'}`",
            "3. Open the raw `input_path` only if the draft or hint is insufficient.",
            f"4. Finalize to: `{metadata.get('result_path') or '<missing>'}`",
            "",
            "`assigned_tasks.json` is queue/progress context only.",
        ]
    ) + "\n"


def render_line_role_worker_script() -> str:
    allowed_labels_json = json.dumps(list(LINE_ROLE_ALLOWED_LABELS), sort_keys=True)
    label_by_code_json = json.dumps(LINE_ROLE_LABEL_BY_CODE, sort_keys=True)
    return """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ALLOWED_LABELS = {allowed_labels_json}
LABEL_BY_CODE = {label_by_code_json}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")


def workspace_relative_path(workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def coerce_metadata(task_row):
    metadata = task_row.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    return {{}}


def coerce_input_rows(workspace_root: Path, task_row):
    input_payload = task_row.get("input_payload")
    if not isinstance(input_payload, dict):
        metadata = coerce_metadata(task_row)
        input_path = str(metadata.get("input_path") or "").strip()
        if not input_path:
            return []
        candidate_path = (workspace_root / input_path).resolve()
        if not candidate_path.exists():
            return []
        input_payload = load_json(candidate_path)
        if not isinstance(input_payload, dict):
            return []
    rows = input_payload.get("rows")
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        normalized.append([row[0], row[1], row[2]])
    return normalized


def read_assigned_tasks(workspace_root: Path):
    path = workspace_root / "assigned_tasks.json"
    payload = load_json(path)
    if not isinstance(payload, list):
        raise SystemExit("assigned_tasks.json is not a list")
    return [row for row in payload if isinstance(row, dict)]


def read_current_task(workspace_root: Path):
    path = workspace_root / "current_task.json"
    if not path.exists():
        return None
    payload = load_json(path)
    if isinstance(payload, dict):
        return payload
    return None


def resolve_task_row(workspace_root: Path, task_id: str | None):
    assigned_tasks = read_assigned_tasks(workspace_root)
    current_task = read_current_task(workspace_root)
    wanted = (task_id or "").strip()
    if wanted:
        for row in assigned_tasks:
            if str(row.get("task_id") or "").strip() == wanted:
                return row
        raise SystemExit(f"unknown task_id: {{wanted}}")
    if current_task is not None:
        return current_task
    if len(assigned_tasks) == 1:
        return assigned_tasks[0]
    raise SystemExit("task_id is required when current_task.json is absent")


def build_seed_output(task_row):
    rows_payload = []
    unknown_codes = []
    for row in coerce_input_rows(Path.cwd(), task_row):
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            raise SystemExit("input row is missing a valid atomic_index")
        code = str(row[1]).strip()
        label = LABEL_BY_CODE.get(code)
        if label is None:
            unknown_codes.append(code or "<blank>")
            label = "OTHER"
        rows_payload.append({{"atomic_index": atomic_index, "label": label}})
    if unknown_codes:
        rendered = ", ".join(sorted(set(unknown_codes)))
        raise SystemExit(f"unknown line-role label code(s): {{rendered}}")
    return {{"rows": rows_payload}}


def validate_payload(task_row, payload):
    errors = []
    expected_rows = coerce_input_rows(Path.cwd(), task_row)
    expected_atomic_indices = []
    for row in expected_rows:
        try:
            expected_atomic_indices.append(int(row[0]))
        except (TypeError, ValueError):
            return ["invalid_input_atomic_index"], {{}}
    metadata = {{
        "owned_row_count": len(expected_atomic_indices),
    }}
    if not isinstance(payload, dict):
        return ["payload_not_object"], metadata
    extra_top_level_keys = sorted(key for key in payload.keys() if str(key) != "rows")
    if extra_top_level_keys:
        errors.append("extra_top_level_keys")
        metadata["extra_top_level_keys"] = extra_top_level_keys
    rows_payload = payload.get("rows")
    if not isinstance(rows_payload, list):
        errors.append("rows_not_list")
        return sorted(set(errors)), metadata
    metadata["returned_row_count"] = len(rows_payload)
    if len(rows_payload) != len(expected_atomic_indices):
        errors.append("wrong_row_count")
    returned_atomic_indices = []
    for row_payload in rows_payload:
        if not isinstance(row_payload, dict):
            errors.append("row_not_object")
            continue
        extra_row_keys = sorted(
            key for key in row_payload.keys() if str(key) not in {{"atomic_index", "label"}}
        )
        if extra_row_keys:
            errors.append("extra_row_keys")
        try:
            returned_atomic_indices.append(int(row_payload.get("atomic_index")))
        except (TypeError, ValueError):
            errors.append("invalid_atomic_index")
        label = str(row_payload.get("label") or "").strip().upper()
        if label not in ALLOWED_LABELS:
            errors.append("invalid_label")
    if returned_atomic_indices != expected_atomic_indices:
        if len(returned_atomic_indices) == len(expected_atomic_indices):
            errors.append("row_order_mismatch")
        else:
            errors.append("atomic_index_mismatch")
    metadata["expected_atomic_indices"] = expected_atomic_indices
    metadata["returned_atomic_indices"] = returned_atomic_indices
    return sorted(set(errors)), metadata


def infer_task_id_from_path(workspace_root: Path, json_path: Path):
    stem = json_path.stem
    assigned_tasks = read_assigned_tasks(workspace_root)
    task_ids = {{
        str(row.get("task_id") or "").strip()
        for row in assigned_tasks
        if str(row.get("task_id") or "").strip()
    }}
    if stem in task_ids:
        return stem
    current_task = read_current_task(workspace_root)
    if isinstance(current_task, dict):
        current_task_id = str(current_task.get("task_id") or "").strip()
        if current_task_id:
            return current_task_id
    return None


def cmd_overview(workspace_root: Path):
    assigned_tasks = read_assigned_tasks(workspace_root)
    current_task = read_current_task(workspace_root)
    current_task_id = str((current_task or {{}}).get("task_id") or "").strip()
    print("Line-role worker queue:")
    for index, task_row in enumerate(assigned_tasks, start=1):
        task_id = str(task_row.get("task_id") or "").strip() or f"task-{{index:03d}}"
        metadata = coerce_metadata(task_row)
        counts = metadata.get("deterministic_label_counts")
        if isinstance(counts, dict) and counts:
            rendered_counts = ", ".join(f"{{label}}={{count}}" for label, count in counts.items())
        else:
            rendered_counts = "unknown"
        current_marker = " current" if task_id == current_task_id else ""
        print(
            f"- {{task_id}}{{current_marker}}: rows={{metadata.get('owned_row_count')}}, "
            f"atomic={{metadata.get('atomic_index_start')}}..{{metadata.get('atomic_index_end')}}, "
            f"labels={{rendered_counts}}, result={{metadata.get('result_path') or 'unknown'}}"
        )


def cmd_show(workspace_root: Path, task_id: str | None):
    task_row = resolve_task_row(workspace_root, task_id)
    metadata = coerce_metadata(task_row)
    print(f"task_id: {{task_row.get('task_id')}}")
    print(f"parent_shard_id: {{task_row.get('parent_shard_id')}}")
    print(f"input_path: {{metadata.get('input_path') or '<missing>'}}")
    print(f"hint_path: {{metadata.get('hint_path') or '<missing>'}}")
    print(f"result_path: {{metadata.get('result_path') or '<missing>'}}")
    print(f"scratch_draft_path: {{metadata.get('scratch_draft_path') or '<missing>'}}")
    print(f"owned_row_count: {{metadata.get('owned_row_count')}}")
    print(f"atomic_index_start: {{metadata.get('atomic_index_start')}}")
    print(f"atomic_index_end: {{metadata.get('atomic_index_end')}}")
    counts = metadata.get("deterministic_label_counts")
    if isinstance(counts, dict) and counts:
        rendered_counts = ", ".join(f"{{label}}={{count}}" for label, count in counts.items())
    else:
        rendered_counts = "none"
    print(f"deterministic_label_counts: {{rendered_counts}}")


def cmd_scaffold(workspace_root: Path, task_id: str | None, dest: str | None):
    task_row = resolve_task_row(workspace_root, task_id)
    payload = build_seed_output(task_row)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\\n"
    if dest:
        save_json((workspace_root / dest).resolve(), payload)
        print(dest)
        return
    print(rendered, end="")


def cmd_prepare_all(workspace_root: Path, dest_dir: str):
    normalized_dest_dir = Path(dest_dir)
    if normalized_dest_dir.is_absolute():
        raise SystemExit("dest_dir must stay relative to the workspace root")
    assigned_tasks = read_assigned_tasks(workspace_root)
    written_paths = []
    for task_row in assigned_tasks:
        row_task_id = str(task_row.get("task_id") or "").strip()
        if not row_task_id:
            continue
        destination = workspace_root / normalized_dest_dir / f"{{row_task_id}}.json"
        save_json(destination, build_seed_output(task_row))
        written_paths.append(destination)
    noun = "draft" if len(written_paths) == 1 else "drafts"
    print(
        f"prepared {{len(written_paths)}} {{noun}} under "
        f"{{workspace_relative_path(workspace_root, (workspace_root / normalized_dest_dir).resolve())}}"
    )


def cmd_check(workspace_root: Path, json_path: str, task_id: str | None, verbose: bool):
    resolved_json_path = (workspace_root / json_path).resolve()
    payload = load_json(resolved_json_path)
    resolved_task_id = task_id or infer_task_id_from_path(workspace_root, resolved_json_path)
    task_row = resolve_task_row(workspace_root, resolved_task_id)
    errors, metadata = validate_payload(task_row, payload)
    if errors:
        print(json.dumps({{"status": "invalid", "errors": errors, "metadata": metadata}}, indent=2, sort_keys=True))
        raise SystemExit(1)
    if verbose:
        print(json.dumps({{"status": "ok", "metadata": metadata}}, indent=2, sort_keys=True))
    else:
        print(f"OK {{str(task_row.get('task_id') or '').strip()}}")


def install_payloads(workspace_root: Path, json_paths: list[Path], task_ids: list[str | None]) -> list[Path]:
    planned_writes = []
    errors = []
    for json_path, task_id in zip(json_paths, task_ids):
        resolved_json_path = json_path.resolve()
        payload = load_json(resolved_json_path)
        resolved_task_id = task_id or infer_task_id_from_path(workspace_root, resolved_json_path)
        task_row = resolve_task_row(workspace_root, resolved_task_id)
        payload_errors, metadata = validate_payload(task_row, payload)
        if payload_errors:
            errors.append(
                json.dumps(
                    {{"draft": workspace_relative_path(workspace_root, resolved_json_path), "status": "invalid", "errors": payload_errors, "metadata": metadata}},
                    indent=2,
                    sort_keys=True,
                )
            )
            continue
        metadata_row = coerce_metadata(task_row)
        result_path = str(metadata_row.get("result_path") or "").strip()
        if not result_path:
            errors.append(
                json.dumps(
                    {{"draft": workspace_relative_path(workspace_root, resolved_json_path), "status": "invalid", "errors": ["missing_result_path"]}},
                    indent=2,
                    sort_keys=True,
                )
            )
            continue
        destination = (workspace_root / result_path).resolve()
        planned_writes.append((destination, payload))
    if errors:
        print("\\n".join(errors))
        raise SystemExit(1)
    written_paths = []
    for destination, payload in planned_writes:
        save_json(destination, payload)
        written_paths.append(destination)
    return written_paths


def cmd_install(workspace_root: Path, json_path: str, task_id: str | None):
    written_paths = install_payloads(workspace_root, [workspace_root / json_path], [task_id])
    print(workspace_relative_path(workspace_root, written_paths[0]))


def cmd_finalize_all(workspace_root: Path, draft_dir: str):
    normalized_draft_dir = Path(draft_dir)
    if normalized_draft_dir.is_absolute():
        raise SystemExit("draft_dir must stay relative to the workspace root")
    assigned_tasks = read_assigned_tasks(workspace_root)
    json_paths = []
    task_ids = []
    for task_row in assigned_tasks:
        row_task_id = str(task_row.get("task_id") or "").strip()
        if not row_task_id:
            continue
        json_paths.append(workspace_root / normalized_draft_dir / f"{{row_task_id}}.json")
        task_ids.append(row_task_id)
    written_paths = install_payloads(workspace_root, json_paths, task_ids)
    noun = "task output" if len(written_paths) == 1 else "task outputs"
    print(
        f"installed {{len(written_paths)}} {{noun}} from "
        f"{{workspace_relative_path(workspace_root, (workspace_root / normalized_draft_dir).resolve())}}"
    )


def build_parser():
    parser = argparse.ArgumentParser(prog="line_role_worker.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("overview")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("task_id", nargs="?")

    scaffold_parser = subparsers.add_parser("scaffold")
    scaffold_parser.add_argument("task_id", nargs="?")
    scaffold_parser.add_argument("--dest")

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("task_id", nargs="?")
    prepare_parser.add_argument("--dest")

    prepare_all_parser = subparsers.add_parser("prepare-all")
    prepare_all_parser.add_argument("--dest-dir", default="scratch")

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("json_path")
    check_parser.add_argument("--task-id")
    check_parser.add_argument("--verbose", action="store_true")

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("json_path")
    install_parser.add_argument("--task-id")

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("json_path")
    finalize_parser.add_argument("--task-id")

    finalize_all_parser = subparsers.add_parser("finalize-all")
    finalize_all_parser.add_argument("draft_dir")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    workspace_root = Path.cwd()
    if args.command == "overview":
        cmd_overview(workspace_root)
    elif args.command == "show":
        cmd_show(workspace_root, args.task_id)
    elif args.command == "scaffold":
        cmd_scaffold(workspace_root, args.task_id, args.dest)
    elif args.command == "prepare":
        cmd_scaffold(workspace_root, args.task_id, args.dest)
    elif args.command == "prepare-all":
        cmd_prepare_all(workspace_root, args.dest_dir)
    elif args.command == "check":
        cmd_check(workspace_root, args.json_path, args.task_id, args.verbose)
    elif args.command == "install":
        cmd_install(workspace_root, args.json_path, args.task_id)
    elif args.command == "finalize":
        cmd_install(workspace_root, args.json_path, args.task_id)
    elif args.command == "finalize-all":
        cmd_finalize_all(workspace_root, args.draft_dir)
    else:
        raise SystemExit(f"unknown command: {{args.command}}")


if __name__ == "__main__":
    main()
""".format(
        allowed_labels_json=allowed_labels_json,
        label_by_code_json=label_by_code_json,
    )
