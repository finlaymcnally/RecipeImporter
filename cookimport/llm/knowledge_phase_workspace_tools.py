from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


KNOWLEDGE_WORKER_TOOL_FILENAME = "knowledge_worker.py"
KNOWLEDGE_VALID_OUTPUT_EXAMPLE_FILENAME = "valid_knowledge_output.json"
PASS1_SEMANTIC_AUDIT_SCHEMA_VERSION = "knowledge_pass1_semantic_audit.v1"
PASS1_SEMANTIC_SUSPICION_ERROR = "semantic_suspicion_requires_repair"
KNOWLEDGE_VALID_OUTPUT_EXAMPLE_PAYLOAD = {
    "packet_id": "book.ks0000.nr",
    "block_decisions": [
        {"block_index": 10, "category": "knowledge", "reviewer_category": "knowledge"},
        {"block_index": 11, "category": "other", "reviewer_category": "other"},
    ],
    "idea_groups": [
        {
            "group_id": "g01",
            "topic_label": "Heat control",
            "block_indices": [10],
        }
    ],
}
KNOWLEDGE_OUTPUT_CONTRACT_MARKDOWN = """# Knowledge Ledger Contract

Use this contract for every installed `out/<shard_id>.json`.
The normal loop still starts from `CURRENT_PHASE.md` and the active `work/<shard_id>.pass{1,2}.json` ledger. Open this file only when you need the installed output shape.
Pass 1 only advances after the work ledger is structurally valid and the repo-owned semantic suspicion audit has no open flags. If that audit flags rows, patch only the flagged rows in the existing Pass 1 work ledger before Pass 2 can begin.

Required shape:

    {"packet_id":"book.ks0000.nr","block_decisions":[{"block_index":10,"category":"knowledge"}],"idea_groups":[{"group_id":"g01","topic_label":"Heat control","block_indices":[10]}]}

Rules:

- The file must be one JSON object.
- Top level keys: `packet_id`, `block_decisions`, `idea_groups`.
- `packet_id` must match the active shard id.
- `block_decisions` must cover every owned block exactly once and keep the same block order as `in/<shard_id>.json`.
- Each block decision must use `block_index` plus `category`, with optional `reviewer_category`.
- `category` must be `knowledge` or `other`.
- The active Pass 2 work ledger may use any non-empty local `group_key`; the helper canonicalizes final `group_id` values during install.
- Each `knowledge` block must appear in exactly one idea group.
- `idea_groups` rows must use `group_id`, `topic_label`, and `block_indices`.
- Group ids may span more than one kept block, but one `group_id` must keep one `topic_label`.
- Do not add markdown, commentary, or extra JSON wrapper keys.
"""

_MEMOIR_LIKE_PHRASES = (
    "when i ",
    "i remember",
    "i learned",
    "i like",
    "i love",
    "i prefer",
    "growing up",
    "my mother",
    "my grandmother",
    "my wife",
    "my husband",
    "my kids",
    "for me",
    "reminds me",
    "in my kitchen",
    "we always",
)
_GUIDANCE_IMPERATIVE_PREFIXES = (
    "use ",
    "keep ",
    "whisk ",
    "stir ",
    "salt ",
    "season ",
    "preheat ",
    "cool ",
    "let ",
    "rest ",
    "bake ",
    "toast ",
    "simmer ",
    "boil ",
    "fold ",
    "knead ",
)
_GUIDANCE_REASON_PHRASES = (
    "because ",
    "so that ",
    "to avoid ",
    "to prevent ",
    "helps ",
    "help ",
    "prevents ",
    "keeps ",
    "means ",
    "when ",
    "if ",
    "until ",
    "otherwise",
)
_GUIDANCE_COOKING_TERMS = (
    "heat",
    "pan",
    "oven",
    "butter",
    "salt",
    "acid",
    "dough",
    "batter",
    "sauce",
    "stock",
    "whisk",
    "stir",
    "simmer",
    "boil",
    "cook",
    "bake",
    "toast",
    "fry",
    "roast",
    "season",
    "flavor",
    "texture",
    "refriger",
    "cool",
    "rest",
)


def _coerce_metadata(shard_row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = shard_row.get("metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} did not contain a JSON object")
    return dict(payload)


def _save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _workspace_relative_path(workspace_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root))
    except ValueError:
        return str(path)


def _input_blocks(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks = input_payload.get("b")
    if not isinstance(blocks, list):
        return []
    return [dict(block) for block in blocks if isinstance(block, Mapping)]


def _truth_row_from_input_block(block: Mapping[str, Any]) -> dict[str, Any] | None:
    if block.get("i") is None:
        return None
    row = {
        "block_index": int(block.get("i")),
        "text": str(block.get("t") or "").strip(),
    }
    if block.get("hl") is not None:
        row["heading_level"] = block.get("hl")
    if isinstance(block.get("th"), Mapping):
        row["table_hint"] = dict(block["th"])
    return row


def _pass1_row_from_input_block(block: Mapping[str, Any]) -> dict[str, Any] | None:
    truth_row = _truth_row_from_input_block(block)
    if truth_row is None:
        return None
    return {
        **truth_row,
        "category": "",
    }


def _pass2_group_key_from_row(row: Mapping[str, Any]) -> str:
    return str(row.get("group_key") or row.get("group_id") or "").strip()


def _pass2_row_from_input_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("block_index") is None:
        return None
    block_index = int(row.get("block_index"))
    projected = {
        "block_index": block_index,
        "category": "knowledge",
        "text": str(row.get("text") or "").strip(),
        "group_key": "",
        "topic_label": "",
    }
    if row.get("heading_level") is not None:
        projected["heading_level"] = row.get("heading_level")
    if isinstance(row.get("table_hint"), Mapping):
        projected["table_hint"] = dict(row["table_hint"])
    return projected


def _load_optional_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _load_payload(path)
    except Exception:
        return None


def _excerpt(text: str, *, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _is_heading_like_row(row: Mapping[str, Any]) -> bool:
    text = str(row.get("text") or "").strip()
    if not text:
        return False
    words = re.findall(r"[A-Za-z0-9']+", text)
    if len(words) > 8:
        return False
    if row.get("heading_level") is not None:
        return True
    if text.endswith(":"):
        return True
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and text.upper() == text


def _is_memoir_like_text(text: str) -> bool:
    lowered = f" {str(text or '').strip().lower()} "
    return any(phrase in lowered for phrase in _MEMOIR_LIKE_PHRASES)


def _guidance_drop_signal(text: str) -> str | None:
    lowered = f" {str(text or '').strip().lower()} "
    if any(lowered.lstrip().startswith(prefix) for prefix in _GUIDANCE_IMPERATIVE_PREFIXES):
        return "imperative"
    if (
        any(phrase in lowered for phrase in _GUIDANCE_REASON_PHRASES)
        and any(term in lowered for term in _GUIDANCE_COOKING_TERMS)
    ):
        return "explanatory"
    return None


def _pass1_rows_by_block_index(payload: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    rows_by_block_index: dict[int, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            continue
        rows_by_block_index[int(row.get("block_index"))] = dict(row)
    return rows_by_block_index


def build_pass1_semantic_audit(
    *,
    shard_id: str,
    input_payload: Mapping[str, Any],
    pass1_payload: Mapping[str, Any],
    previous_audit_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    input_rows = [
        row
        for row in (
            _truth_row_from_input_block(block) for block in _input_blocks(input_payload)
        )
        if row is not None
    ]
    pass1_rows_by_block_index = _pass1_rows_by_block_index(pass1_payload)
    flags: list[dict[str, Any]] = []
    ordered_block_indices = [int(row["block_index"]) for row in input_rows]
    category_by_block_index = {
        block_index: str(pass1_rows_by_block_index.get(block_index, {}).get("category") or "").strip()
        for block_index in ordered_block_indices
    }
    previous_requested = bool(
        dict(previous_audit_payload or {}).get("repair_requested")
    )

    for position, row in enumerate(input_rows):
        block_index = int(row["block_index"])
        category = category_by_block_index.get(block_index)
        text = str(row.get("text") or "").strip()
        if category == "knowledge":
            previous_category = (
                category_by_block_index.get(ordered_block_indices[position - 1])
                if position > 0
                else None
            )
            next_category = (
                category_by_block_index.get(ordered_block_indices[position + 1])
                if position + 1 < len(ordered_block_indices)
                else None
            )
            if (
                _is_heading_like_row(row)
                and previous_category != "knowledge"
                and next_category != "knowledge"
            ):
                flags.append(
                    {
                        "block_index": block_index,
                        "category": category,
                        "code": "heading_like_keep_without_supported_body",
                        "evidence": (
                            "short heading-like row was marked knowledge without an adjacent "
                            "kept explanatory body"
                        ),
                        "text_excerpt": _excerpt(text),
                    }
                )
            if _is_memoir_like_text(text):
                flags.append(
                    {
                        "block_index": block_index,
                        "category": category,
                        "code": "memoir_like_keep",
                        "evidence": "first-person or memoir-like prose was marked knowledge",
                        "text_excerpt": _excerpt(text),
                    }
                )
        elif category == "other":
            guidance_signal = _guidance_drop_signal(text)
            if guidance_signal:
                evidence = (
                    "actionable cooking instruction was marked other"
                    if guidance_signal == "imperative"
                    else "cause-and-effect or troubleshooting cooking guidance was marked other"
                )
                flags.append(
                    {
                        "block_index": block_index,
                        "category": category,
                        "code": "guidance_like_other",
                        "evidence": evidence,
                        "signal": guidance_signal,
                        "text_excerpt": _excerpt(text),
                    }
                )

    flagged_block_indices = sorted(
        {
            int(flag.get("block_index"))
            for flag in flags
            if flag.get("block_index") is not None
        }
    )
    if flagged_block_indices:
        status = "repair_required"
    elif previous_requested:
        status = "passed_after_repair"
    else:
        status = "passed_clean"
    return {
        "schema_version": PASS1_SEMANTIC_AUDIT_SCHEMA_VERSION,
        "phase": "pass1",
        "shard_id": str(shard_id),
        "status": status,
        "repair_requested": previous_requested or bool(flagged_block_indices),
        "repair_cleared": bool(previous_requested and not flagged_block_indices),
        "flag_count": len(flags),
        "max_flag_count": max(
            len(flags),
            int(dict(previous_audit_payload or {}).get("max_flag_count") or 0),
        ),
        "flagged_block_indices": flagged_block_indices,
        "kept_block_indices": [
            block_index
            for block_index in ordered_block_indices
            if category_by_block_index.get(block_index) == "knowledge"
        ],
        "other_block_indices": [
            block_index
            for block_index in ordered_block_indices
            if category_by_block_index.get(block_index) == "other"
        ],
        "flags": flags,
    }


def build_knowledge_workspace_shard_metadata(
    *,
    shard_id: str,
    input_payload: Mapping[str, Any] | None,
    input_path: str,
    hint_path: str,
    result_path: str,
) -> dict[str, Any]:
    blocks = _input_blocks(dict(input_payload or {}))
    block_indices = [
        int(block.get("i"))
        for block in blocks
        if block.get("i") is not None
    ]
    return {
        "phase_key": "knowledge_pass_1",
        "shard_id": str(shard_id),
        "input_path": str(input_path),
        "hint_path": str(hint_path),
        "result_path": str(result_path),
        "semantic_audit_path": str(Path("shards") / str(shard_id) / "semantic_audit.json"),
        "owned_row_count": len(block_indices),
        "block_index_start": block_indices[0] if block_indices else None,
        "block_index_end": block_indices[-1] if block_indices else None,
    }


def build_knowledge_seed_output(
    input_payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "packet_id": str(input_payload.get("bid") or input_payload.get("packet_id") or ""),
        "block_decisions": [
            {
                "block_index": int(block.get("i")),
                "category": "other",
                "reviewer_category": "other",
            }
            for block in _input_blocks(input_payload)
            if block.get("i") is not None
        ],
        "idea_groups": [],
    }


def build_pass1_work_ledger(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for block in _input_blocks(input_payload):
        row = _pass1_row_from_input_block(block)
        if row is not None:
            rows.append(row)
    return {
        "phase": "pass1",
        "rows": rows,
    }


def build_pass2_input_ledger(
    *,
    input_payload: Mapping[str, Any],
    pass1_payload: Mapping[str, Any],
) -> dict[str, Any]:
    rows_by_index = {}
    for block in _input_blocks(input_payload):
        truth_row = _truth_row_from_input_block(block)
        if truth_row is None:
            continue
        rows_by_index[int(truth_row["block_index"])] = truth_row
    kept_indices = [
        int(row.get("block_index"))
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, Mapping) and str(row.get("category") or "").strip() == "knowledge"
    ]
    return {
        "phase": "pass2",
        "rows": [
            {
                "block_index": block_index,
                "category": "knowledge",
                "text": str(rows_by_index.get(block_index, {}).get("text") or ""),
                **(
                    {
                        "heading_level": rows_by_index[block_index]["heading_level"],
                    }
                    if rows_by_index.get(block_index, {}).get("heading_level") is not None
                    else {}
                ),
                **(
                    {
                        "table_hint": dict(rows_by_index[block_index]["table_hint"]),
                    }
                    if isinstance(rows_by_index.get(block_index, {}).get("table_hint"), Mapping)
                    else {}
                ),
            }
            for block_index in kept_indices
        ],
    }


def build_pass2_work_ledger(pass2_input_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    work_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        projected = _pass2_row_from_input_row(row)
        if projected is None:
            continue
        work_rows.append(projected)
    return {"phase": "pass2", "rows": work_rows}


def build_final_output(
    *,
    shard_id: str,
    pass1_payload: Mapping[str, Any],
    pass2_payload: Mapping[str, Any],
) -> dict[str, Any]:
    decisions = [
        {
            "block_index": int(row.get("block_index")),
            "category": str(row.get("category") or "").strip(),
            "reviewer_category": (
                "knowledge"
                if str(row.get("category") or "").strip() == "knowledge"
                else "other"
            ),
        }
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, Mapping) and row.get("block_index") is not None
    ]
    groups_by_key: dict[str, dict[str, Any]] = {}
    for row in (pass2_payload.get("rows") or []):
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            continue
        group_key = _pass2_group_key_from_row(row)
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_key or not topic_label:
            continue
        group = groups_by_key.setdefault(
            group_key,
            {
                "group_key": group_key,
                "topic_label": topic_label,
                "block_indices": [],
            },
        )
        group["block_indices"].append(int(row.get("block_index")))
    ordered_groups = [
        {
            "group_id": f"g{index:02d}",
            "topic_label": group["topic_label"],
            "block_indices": group["block_indices"],
        }
        for index, group in enumerate(groups_by_key.values(), start=1)
    ]
    return {
        "packet_id": shard_id,
        "block_decisions": decisions,
        "idea_groups": ordered_groups,
    }


def _normalize_frozen_rows_by_block_index(
    frozen_rows: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None,
) -> dict[int, dict[str, Any]]:
    normalized: dict[int, dict[str, Any]] = {}
    if isinstance(frozen_rows, Mapping):
        values = frozen_rows.values()
    elif isinstance(frozen_rows, Sequence):
        values = frozen_rows
    else:
        values = ()
    for row in values:
        if not isinstance(row, Mapping):
            continue
        try:
            block_index = int(row.get("block_index"))
        except (TypeError, ValueError):
            continue
        normalized_row = {"block_index": block_index}
        if row.get("category") is not None:
            normalized_row["category"] = str(row.get("category") or "").strip()
        group_key = _pass2_group_key_from_row(row)
        if group_key:
            normalized_row["group_key"] = group_key
        if row.get("topic_label") is not None:
            normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
        normalized[block_index] = normalized_row
    return normalized


def _pass1_input_rows_by_block_index(
    input_payload: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    rows_by_block_index: dict[int, dict[str, Any]] = {}
    for block in _input_blocks(input_payload):
        row = _pass1_row_from_input_block(block)
        if row is None:
            continue
        rows_by_block_index[int(row["block_index"])] = row
    return rows_by_block_index


def _pass2_input_rows_by_block_index(
    pass2_input_payload: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    rows_by_block_index: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        projected = _pass2_row_from_input_row(row)
        if projected is None:
            continue
        rows_by_block_index[int(projected["block_index"])] = projected
    return rows_by_block_index


def _resolved_unresolved_block_indices(
    *,
    metadata: Mapping[str, Any],
) -> list[int]:
    unresolved = [
        int(value)
        for value in (metadata.get("unresolved_block_indices") or [])
        if str(value).strip()
    ]
    if unresolved:
        return unresolved
    return [
        int(value)
        for value in (metadata.get("expected_block_indices") or [])
        if str(value).strip()
    ]


def _merge_frozen_rows_by_block_index(
    *,
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
    accepted_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    merged = _normalize_frozen_rows_by_block_index(frozen_rows_by_block_index)
    for row in accepted_rows or ():
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            continue
        block_index = int(row.get("block_index"))
        merged[block_index] = {
            key: value
            for key, value in dict(row).items()
            if key in {"block_index", "category", "group_key", "topic_label"}
        }
        merged[block_index]["block_index"] = block_index
    return [merged[block_index] for block_index in sorted(merged)]


def build_pass1_repair_request_payload(
    *,
    input_payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    validation_errors: Sequence[str],
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    unresolved_block_indices = _resolved_unresolved_block_indices(metadata=metadata)
    input_rows_by_block_index = _pass1_input_rows_by_block_index(input_payload)
    frozen_rows = _merge_frozen_rows_by_block_index(
        frozen_rows_by_block_index=frozen_rows_by_block_index,
        accepted_rows=[
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, Mapping)
        ],
    )
    semantic_flags = [
        dict(flag)
        for flag in (metadata.get("semantic_audit_flags") or [])
        if isinstance(flag, Mapping)
    ]
    payload = {
        "repair_mode": "knowledge_phase",
        "phase": "pass1",
        "repair_request_kind": (
            "semantic_suspicion" if semantic_flags else "validation"
        ),
        "accepted_block_indices": [int(row["block_index"]) for row in frozen_rows],
        "unresolved_block_indices": unresolved_block_indices,
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
        "frozen_rows": frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved_block_indices
            if block_index in input_rows_by_block_index
        ],
    }
    if metadata.get("semantic_audit_path"):
        payload["semantic_audit_path"] = str(metadata.get("semantic_audit_path"))
    if metadata.get("semantic_audit_status"):
        payload["semantic_audit_status"] = str(metadata.get("semantic_audit_status"))
    if semantic_flags:
        payload["semantic_flags"] = semantic_flags
    return payload


def build_pass2_repair_request_payload(
    *,
    pass2_input_payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    validation_errors: Sequence[str],
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    unresolved_block_indices = _resolved_unresolved_block_indices(metadata=metadata)
    input_rows_by_block_index = _pass2_input_rows_by_block_index(pass2_input_payload)
    frozen_rows = _merge_frozen_rows_by_block_index(
        frozen_rows_by_block_index=frozen_rows_by_block_index,
        accepted_rows=[
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, Mapping)
        ],
    )
    return {
        "repair_mode": "knowledge_phase",
        "phase": "pass2",
        "accepted_block_indices": [int(row["block_index"]) for row in frozen_rows],
        "unresolved_block_indices": unresolved_block_indices,
        "validation_errors": [
            str(error).strip() for error in validation_errors if str(error).strip()
        ],
        "frozen_rows": frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved_block_indices
            if block_index in input_rows_by_block_index
        ],
    }


def validate_pass1_work_ledger(
    *,
    input_payload: Mapping[str, Any],
    payload: Any,
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    expected_block_indices = [
        int(block.get("i"))
        for block in _input_blocks(input_payload)
        if block.get("i") is not None
    ]
    metadata: dict[str, Any] = {
        "expected_block_indices": expected_block_indices,
        "owned_row_count": len(expected_block_indices),
    }
    if not isinstance(payload, Mapping):
        return ("payload_not_object",), metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ("rows_not_list",), metadata
    actual_indices: list[int] = []
    errors: list[str] = []
    invalid_block_indices: list[int] = []
    unresolved_block_indices: set[int] = set()
    row_error_map: dict[int, list[str]] = {}
    parsed_rows: list[dict[str, Any] | None] = []
    seen_block_indices: set[int] = set()
    duplicate_block_indices: set[int] = set()
    frozen_by_block_index = _normalize_frozen_rows_by_block_index(
        frozen_rows_by_block_index
    )
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual_indices.append(block_index)
        row_errors: list[str] = []
        category = str(row.get("category") or "").strip()
        if category not in {"knowledge", "other"}:
            row_errors.append("invalid_block_category")
        if block_index in seen_block_indices:
            duplicate_block_indices.add(block_index)
            row_errors.append("duplicate_block_index")
        seen_block_indices.add(block_index)
        if row_errors:
            invalid_block_indices.append(block_index)
            unresolved_block_indices.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append(
            {
                "block_index": block_index,
                "category": category,
            }
        )
    if actual_indices != expected_block_indices:
        missing = [idx for idx in expected_block_indices if idx not in actual_indices]
        unexpected = [idx for idx in actual_indices if idx not in expected_block_indices]
        if missing:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing
            unresolved_block_indices.update(missing)
        if unexpected:
            errors.append("unexpected_block_decisions")
            metadata["unexpected_block_indices"] = unexpected
            unresolved_block_indices.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved_block_indices.update(expected_block_indices)
    if invalid_block_indices:
        errors.append("invalid_block_category")
        metadata["invalid_block_category_indices"] = invalid_block_indices
    accepted_rows: list[dict[str, Any]] = []
    accepted_block_indices: list[int] = []
    for position, expected_block_index in enumerate(expected_block_indices):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved_block_indices.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in duplicate_block_indices:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved_block_indices.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{expected_block_index}")
            invalid_block_indices.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append(
                "frozen_row_modified"
            )
            unresolved_block_indices.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["kept_block_indices"] = [
        int(row.get("block_index"))
        for row in rows
        if isinstance(row, Mapping) and str(row.get("category") or "").strip() == "knowledge"
    ]
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index
        for block_index in expected_block_indices
        if block_index in unresolved_block_indices
    ] or list(expected_block_indices if errors else [])
    return tuple(dict.fromkeys(errors)), metadata


def validate_pass2_work_ledger(
    *,
    pass2_input_payload: Mapping[str, Any],
    payload: Any,
    frozen_rows_by_block_index: Mapping[int, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    expected_block_indices = [
        int(row.get("block_index"))
        for row in (pass2_input_payload.get("rows") or [])
        if isinstance(row, Mapping) and row.get("block_index") is not None
    ]
    metadata: dict[str, Any] = {
        "expected_block_indices": expected_block_indices,
        "owned_row_count": len(expected_block_indices),
    }
    if not isinstance(payload, Mapping):
        return ("payload_not_object",), metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ("rows_not_list",), metadata
    actual_indices: list[int] = []
    errors: list[str] = []
    group_key_to_topic: dict[str, str] = {}
    invalid_block_indices: list[int] = []
    unresolved_block_indices: set[int] = set()
    row_error_map: dict[int, list[str]] = {}
    parsed_rows: list[dict[str, Any] | None] = []
    seen_block_indices: set[int] = set()
    duplicate_block_indices: set[int] = set()
    frozen_by_block_index = _normalize_frozen_rows_by_block_index(
        frozen_rows_by_block_index
    )
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual_indices.append(block_index)
        row_errors: list[str] = []
        group_key = _pass2_group_key_from_row(row)
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_key or not topic_label:
            row_errors.append("knowledge_block_missing_group")
        previous_topic = group_key_to_topic.get(group_key)
        if group_key and previous_topic is None:
            group_key_to_topic[group_key] = topic_label
        elif group_key and previous_topic != topic_label:
            row_errors.append("knowledge_block_group_conflict")
            metadata.setdefault("group_key_topic_conflicts", []).append(group_key)
        if block_index in seen_block_indices:
            duplicate_block_indices.add(block_index)
            row_errors.append("duplicate_block_index")
        seen_block_indices.add(block_index)
        if row_errors:
            invalid_block_indices.append(block_index)
            unresolved_block_indices.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append(
            {
                "block_index": block_index,
                "group_key": group_key,
                "topic_label": topic_label,
            }
        )
    if actual_indices != expected_block_indices:
        missing = [idx for idx in expected_block_indices if idx not in actual_indices]
        unexpected = [idx for idx in actual_indices if idx not in expected_block_indices]
        if missing:
            errors.append("knowledge_block_missing_group")
            metadata["knowledge_blocks_missing_group"] = missing
            unresolved_block_indices.update(missing)
        if unexpected:
            errors.append("group_contains_other_block")
            metadata["group_blocks_out_of_surface"] = unexpected
            unresolved_block_indices.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved_block_indices.update(expected_block_indices)
    if invalid_block_indices:
        errors.append("knowledge_block_missing_group")
        metadata.setdefault("knowledge_blocks_missing_group", []).extend(invalid_block_indices)
    accepted_rows: list[dict[str, Any]] = []
    accepted_block_indices: list[int] = []
    for position, expected_block_index in enumerate(expected_block_indices):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved_block_indices.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in duplicate_block_indices:
            unresolved_block_indices.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved_block_indices.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{expected_block_index}")
            invalid_block_indices.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append(
                "frozen_row_modified"
            )
            unresolved_block_indices.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["group_keys"] = sorted(group_key_to_topic)
    metadata["group_ids"] = list(metadata["group_keys"])
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index
        for block_index in expected_block_indices
        if block_index in unresolved_block_indices
    ] or list(expected_block_indices if errors else [])
    return tuple(dict.fromkeys(errors)), metadata


def render_knowledge_current_phase_brief(
    phase_row: Mapping[str, Any] | None,
) -> str:
    if phase_row is None:
        return "# Current Knowledge Phase\n\nNo active knowledge shard.\n"
    if str(phase_row.get("status") or "").strip() == "completed":
        return "# Current Knowledge Phase\n\nAll assigned knowledge shards are installed.\n"
    lines = [
        "# Current Knowledge Phase",
        "",
        f"Shard id: `{phase_row.get('shard_id') or '[unknown shard]'}`",
        f"Phase: `{phase_row.get('phase') or '[unknown phase]'}`",
        f"Hint file: `{phase_row.get('hint_path') or '?'}`",
        f"Input file: `{phase_row.get('input_path') or '?'}`",
        f"Active work ledger: `{phase_row.get('work_path') or '?'}`",
        f"Repair file: `{phase_row.get('repair_path') or '?'}`",
        f"Semantic audit file: `{phase_row.get('semantic_audit_path') or '?'}`",
        f"Result file: `{phase_row.get('result_path') or '?'}`",
        "",
    ]
    if str(phase_row.get("phase") or "").strip() == "pass1":
        lines.extend(
            [
                "Pass 1 contract: make the first-authority semantic judgment on the owned rows.",
                "The repo does not know the `knowledge` versus `other` answer ahead of time.",
                "Each work row carries raw block text plus mechanical truth; fill only `category` with `knowledge` or `other`.",
                "Do not create topic labels or grouping keys in Pass 1.",
                "Before Pass 2, repo code runs one narrow semantic suspicion audit over structurally valid Pass 1 rows.",
                "If that audit flags rows, patch only the flagged rows in the same Pass 1 work ledger. The audit packages evidence; it does not know the right semantic answer for you.",
            ]
        )
    else:
        lines.extend(
            [
                "Pass 2 contract: continue from the accepted Pass 1 knowledge rows only.",
                "Assign each kept row a non-empty local `group_key` and `topic_label`.",
                "Use the same `group_key` on rows that belong in the same idea group; the repo will canonicalize final `group_id` values later.",
            ]
        )
    lines.extend(
        [
            "",
            "Preferred loop:",
            "1. Open `CURRENT_PHASE.md`, then the named active work ledger.",
            f"2. Open `{phase_row.get('hint_path') or '?'}` before `{phase_row.get('input_path') or '?'}`.",
            f"3. Open `{phase_row.get('input_path') or '?'}` only if the phase brief, feedback, hint, and work ledger are still insufficient.",
            "4. Run `python3 tools/knowledge_worker.py check-phase`.",
            "5. If `CURRENT_PHASE_FEEDBACK.md` names a repair file, fix only those unresolved rows in the same active work ledger.",
            "6. Run `python3 tools/knowledge_worker.py install-phase` after the current work ledger validates cleanly.",
            "7. Treat `OUTPUT_CONTRACT.md`, `examples/`, and `tools/knowledge_worker.py` as fallback contract/debug surfaces, not the normal first read.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_knowledge_current_phase_feedback(
    *,
    phase_row: Mapping[str, Any] | None,
    validation_errors: Sequence[str] = (),
    validation_metadata: Mapping[str, Any] | None = None,
    completed: bool = False,
) -> str:
    if completed:
        return "# Current Phase Feedback\n\nAll assigned knowledge shards are installed.\n"
    if phase_row is None:
        return "# Current Phase Feedback\n\nNo active knowledge shard.\n"
    if not validation_errors:
        clean_line = "Current work ledger validates cleanly."
        semantic_audit_status = ""
        if isinstance(validation_metadata, Mapping):
            semantic_audit_status = str(validation_metadata.get("semantic_audit_status") or "").strip()
        if semantic_audit_status:
            clean_line = "Current work ledger and Pass 1 semantic suspicion audit validate cleanly."
        cleared_line = (
            "Previous semantic suspicion flags were cleared in this same session.\n"
            if semantic_audit_status == "passed_after_repair"
            else ""
        )
        return (
            "# Current Phase Feedback\n\n"
            f"{clean_line}\n"
            f"Active work ledger: `{phase_row.get('work_path') or '<missing>'}`\n"
            f"Install target: `{phase_row.get('result_path') or '<missing>'}`\n"
            f"{cleared_line}"
            "Next command: `python3 tools/knowledge_worker.py install-phase`.\n"
        )
    unresolved = []
    if isinstance(validation_metadata, Mapping):
        unresolved = [
            int(value)
            for value in (validation_metadata.get("unresolved_block_indices") or [])
            if str(value).strip()
        ]
    lines = [
        "# Current Phase Feedback",
        "",
        (
            "Pass 1 semantic suspicion audit flagged rows for same-session repair."
            if isinstance(validation_metadata, Mapping)
            and bool(validation_metadata.get("semantic_audit_flags"))
            else "Current work ledger is still unresolved."
        ),
        f"Edit only `{phase_row.get('work_path') or '<missing>'}`.",
        "Validation errors:",
    ]
    lines.extend(f"- `{error}`" for error in validation_errors if str(error).strip())
    if phase_row.get("repair_path"):
        lines.append(f"Repair request: `{phase_row.get('repair_path')}`")
    if (
        isinstance(validation_metadata, Mapping)
        and validation_metadata.get("semantic_audit_path")
    ):
        lines.append(
            f"Semantic audit file: `{validation_metadata.get('semantic_audit_path')}`"
        )
    if unresolved:
        lines.append(
            "Unresolved block indices: "
            f"`{', '.join(str(value) for value in unresolved)}`"
        )
    accepted = []
    if isinstance(validation_metadata, Mapping):
        accepted = [
            int(value)
            for value in (
                validation_metadata.get("frozen_block_indices")
                or validation_metadata.get("accepted_block_indices")
                or []
            )
            if str(value).strip()
        ]
    if accepted:
        lines.append(
            "Frozen accepted block indices: "
            f"`{', '.join(str(value) for value in accepted)}`"
        )
    semantic_flags = []
    if isinstance(validation_metadata, Mapping):
        semantic_flags = [
            dict(flag)
            for flag in (validation_metadata.get("semantic_audit_flags") or [])
            if isinstance(flag, Mapping)
        ]
    if semantic_flags:
        lines.append("Semantic suspicion evidence:")
        for flag in semantic_flags:
            lines.append(
                "- block "
                f"{flag.get('block_index')}: `{flag.get('code')}` {flag.get('evidence')}"
            )
    lines.append(
        "Next command after fixes: `python3 tools/knowledge_worker.py check-phase`."
    )
    return "\n".join(lines) + "\n"


def render_knowledge_worker_script() -> str:
    output_contract_markdown = json.dumps(KNOWLEDGE_OUTPUT_CONTRACT_MARKDOWN)
    valid_example_json = json.dumps(
        json.dumps(KNOWLEDGE_VALID_OUTPUT_EXAMPLE_PAYLOAD, indent=2, sort_keys=True) + "\n"
    )
    script = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

OUTPUT_CONTRACT_MARKDOWN = __OUTPUT_CONTRACT_MARKDOWN__
VALID_EXAMPLE_JSON = __VALID_EXAMPLE_JSON__
PASS1_SEMANTIC_AUDIT_SCHEMA_VERSION = "knowledge_pass1_semantic_audit.v1"
PASS1_SEMANTIC_SUSPICION_ERROR = "semantic_suspicion_requires_repair"
MEMOIR_LIKE_PHRASES = (
    "when i ",
    "i remember",
    "i learned",
    "i like",
    "i love",
    "i prefer",
    "growing up",
    "my mother",
    "my grandmother",
    "my wife",
    "my husband",
    "my kids",
    "for me",
    "reminds me",
    "in my kitchen",
    "we always",
)
GUIDANCE_IMPERATIVE_PREFIXES = (
    "use ",
    "keep ",
    "whisk ",
    "stir ",
    "salt ",
    "season ",
    "preheat ",
    "cool ",
    "let ",
    "rest ",
    "bake ",
    "toast ",
    "simmer ",
    "boil ",
    "fold ",
    "knead ",
)
GUIDANCE_REASON_PHRASES = (
    "because ",
    "so that ",
    "to avoid ",
    "to prevent ",
    "helps ",
    "help ",
    "prevents ",
    "keeps ",
    "means ",
    "when ",
    "if ",
    "until ",
    "otherwise",
)
GUIDANCE_COOKING_TERMS = (
    "heat",
    "pan",
    "oven",
    "butter",
    "salt",
    "acid",
    "dough",
    "batter",
    "sauce",
    "stock",
    "whisk",
    "stir",
    "simmer",
    "boil",
    "cook",
    "bake",
    "toast",
    "fry",
    "roast",
    "season",
    "flavor",
    "texture",
    "refriger",
    "cool",
    "rest",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")


def save_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def workspace_root() -> Path:
    return Path.cwd()


def assigned_shards():
    payload = load_json(workspace_root() / "assigned_shards.json")
    if not isinstance(payload, list):
        raise SystemExit("assigned_shards.json is not a list")
    return [row for row in payload if isinstance(row, dict)]


def current_phase():
    path = workspace_root() / "current_phase.json"
    if not path.exists():
        return None
    payload = load_json(path)
    return payload if isinstance(payload, dict) else None


def load_optional_json(path: Path):
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(workspace_root()))
    except ValueError:
        return str(path)


def load_phase_input(phase_row):
    return load_json(workspace_root() / str(phase_row.get("input_path") or ""))


def load_phase_work(phase_row):
    return load_json(workspace_root() / str(phase_row.get("work_path") or ""))


def input_blocks(input_payload):
    blocks = input_payload.get("b")
    if not isinstance(blocks, list):
        return []
    return [dict(block) for block in blocks if isinstance(block, dict)]


def truth_row_from_input_block(block):
    if block.get("i") is None:
        return None
    row = {{
        "block_index": int(block.get("i")),
        "text": str(block.get("t") or "").strip(),
    }}
    if block.get("hl") is not None:
        row["heading_level"] = block.get("hl")
    if isinstance(block.get("th"), dict):
        row["table_hint"] = dict(block["th"])
    return row


def build_pass1_row(block):
    truth_row = truth_row_from_input_block(block)
    if truth_row is None:
        return None
    return {{
        **truth_row,
        "category": "",
    }}


def pass2_group_key(row):
    return str(row.get("group_key") or row.get("group_id") or "").strip()


def build_pass2_row(row):
    if row.get("block_index") is None:
        return None
    projected = {{
        "block_index": int(row.get("block_index")),
        "category": "knowledge",
        "text": str(row.get("text") or "").strip(),
        "group_key": "",
        "topic_label": "",
    }}
    if row.get("heading_level") is not None:
        projected["heading_level"] = row.get("heading_level")
    if isinstance(row.get("table_hint"), dict):
        projected["table_hint"] = dict(row["table_hint"])
    return projected


def excerpt(text, *, limit=120):
    cleaned = re.sub(r"\\s+", " ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def is_heading_like_row(row):
    text = str(row.get("text") or "").strip()
    if not text:
        return False
    words = re.findall(r"[A-Za-z0-9']+", text)
    if len(words) > 8:
        return False
    if row.get("heading_level") is not None:
        return True
    if text.endswith(":"):
        return True
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and text.upper() == text


def is_memoir_like_text(text):
    lowered = f" {{str(text or '').strip().lower()}} "
    return any(phrase in lowered for phrase in MEMOIR_LIKE_PHRASES)


def guidance_drop_signal(text):
    lowered = f" {{str(text or '').strip().lower()}} "
    if any(lowered.lstrip().startswith(prefix) for prefix in GUIDANCE_IMPERATIVE_PREFIXES):
        return "imperative"
    if (
        any(phrase in lowered for phrase in GUIDANCE_REASON_PHRASES)
        and any(term in lowered for term in GUIDANCE_COOKING_TERMS)
    ):
        return "explanatory"
    return None


def build_pass1_seed(input_payload):
    return {{
        "phase": "pass1",
        "rows": [
            row
            for row in (build_pass1_row(block) for block in input_blocks(input_payload))
            if row is not None
        ],
    }}

def build_pass2_input(input_payload, pass1_payload):
    rows_by_index = {{}}
    for block in input_blocks(input_payload):
        truth_row = truth_row_from_input_block(block)
        if truth_row is None:
            continue
        rows_by_index[int(truth_row["block_index"])] = truth_row
    kept = [
        int(row.get("block_index"))
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, dict) and str(row.get("category") or "").strip() == "knowledge"
    ]
    return {{
        "phase": "pass2",
        "rows": [
            {{
                "block_index": block_index,
                "category": "knowledge",
                "text": str(rows_by_index.get(block_index, {{}}).get("text") or ""),
                **(
                    {{"heading_level": rows_by_index[block_index]["heading_level"]}}
                    if rows_by_index.get(block_index, {{}}).get("heading_level") is not None
                    else {{}}
                ),
                **(
                    {{"table_hint": dict(rows_by_index[block_index]["table_hint"])}}
                    if isinstance(rows_by_index.get(block_index, {{}}).get("table_hint"), dict)
                    else {{}}
                ),
            }}
            for block_index in kept
        ],
    }}


def build_pass2_seed(pass2_input_payload):
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {{
        "phase": "pass2",
        "rows": [
            projected
            for projected in (
                build_pass2_row(row)
                for row in rows
                if isinstance(row, dict)
            )
            if projected is not None
        ],
    }}


def normalize_frozen_rows(frozen_rows):
    normalized = {{}}
    if isinstance(frozen_rows, dict):
        values = frozen_rows.values()
    elif isinstance(frozen_rows, list):
        values = frozen_rows
    else:
        values = []
    for row in values:
        if not isinstance(row, dict):
            continue
        try:
            block_index = int(row.get("block_index"))
        except (TypeError, ValueError):
            continue
        normalized_row = {{"block_index": block_index}}
        if row.get("category") is not None:
            normalized_row["category"] = str(row.get("category") or "").strip()
        group_key = pass2_group_key(row)
        if group_key:
            normalized_row["group_key"] = group_key
        if row.get("topic_label") is not None:
            normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
        normalized[block_index] = normalized_row
    return normalized


def merge_frozen_rows(frozen_rows, accepted_rows):
    merged = normalize_frozen_rows(frozen_rows)
    for row in accepted_rows or []:
        if not isinstance(row, dict) or row.get("block_index") is None:
            continue
        block_index = int(row.get("block_index"))
        normalized_row = {{"block_index": block_index}}
        if row.get("category") is not None:
            normalized_row["category"] = str(row.get("category") or "").strip()
        group_key = pass2_group_key(row)
        if group_key:
            normalized_row["group_key"] = group_key
        if row.get("topic_label") is not None:
            normalized_row["topic_label"] = str(row.get("topic_label") or "").strip()
        merged[block_index] = normalized_row
    return [merged[block_index] for block_index in sorted(merged)]


def pass1_input_rows_by_block_index(input_payload):
    rows_by_block_index = {{}}
    for block in input_blocks(input_payload):
        row = build_pass1_row(block)
        if row is None:
            continue
        rows_by_block_index[int(row["block_index"])] = row
    return rows_by_block_index


def pass2_input_rows_by_block_index(pass2_input_payload):
    rows = pass2_input_payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    rows_by_block_index = {{}}
    for row in rows:
        if not isinstance(row, dict):
            continue
        projected = build_pass2_row(row)
        if projected is None:
            continue
        rows_by_block_index[int(projected["block_index"])] = projected
    return rows_by_block_index


def resolved_unresolved_block_indices(metadata):
    unresolved = [
        int(value)
        for value in (metadata.get("unresolved_block_indices") or [])
        if str(value).strip()
    ]
    if unresolved:
        return unresolved
    return [
        int(value)
        for value in (metadata.get("expected_block_indices") or [])
        if str(value).strip()
    ]


def pass1_rows_by_block_index(pass1_payload):
    rows_by_block_index = {}
    for row in pass1_payload.get("rows") or []:
        if not isinstance(row, dict) or row.get("block_index") is None:
            continue
        rows_by_block_index[int(row.get("block_index"))] = dict(row)
    return rows_by_block_index


def build_pass1_semantic_audit(shard_id, input_payload, pass1_payload, *, previous_audit_payload=None):
    input_rows = [
        row
        for row in (
            truth_row_from_input_block(block) for block in input_blocks(input_payload)
        )
        if row is not None
    ]
    pass1_rows = pass1_rows_by_block_index(pass1_payload)
    ordered_block_indices = [int(row["block_index"]) for row in input_rows]
    category_by_block_index = {
        block_index: str(pass1_rows.get(block_index, {}).get("category") or "").strip()
        for block_index in ordered_block_indices
    }
    previous_requested = bool(dict(previous_audit_payload or {}).get("repair_requested"))
    flags = []
    for position, row in enumerate(input_rows):
        block_index = int(row["block_index"])
        category = category_by_block_index.get(block_index)
        text = str(row.get("text") or "").strip()
        if category == "knowledge":
            previous_category = (
                category_by_block_index.get(ordered_block_indices[position - 1])
                if position > 0
                else None
            )
            next_category = (
                category_by_block_index.get(ordered_block_indices[position + 1])
                if position + 1 < len(ordered_block_indices)
                else None
            )
            if (
                is_heading_like_row(row)
                and previous_category != "knowledge"
                and next_category != "knowledge"
            ):
                flags.append(
                    {
                        "block_index": block_index,
                        "category": category,
                        "code": "heading_like_keep_without_supported_body",
                        "evidence": (
                            "short heading-like row was marked knowledge without an adjacent kept explanatory body"
                        ),
                        "text_excerpt": excerpt(text),
                    }
                )
            if is_memoir_like_text(text):
                flags.append(
                    {
                        "block_index": block_index,
                        "category": category,
                        "code": "memoir_like_keep",
                        "evidence": "first-person or memoir-like prose was marked knowledge",
                        "text_excerpt": excerpt(text),
                    }
                )
        elif category == "other":
            signal = guidance_drop_signal(text)
            if signal:
                flags.append(
                    {
                        "block_index": block_index,
                        "category": category,
                        "code": "guidance_like_other",
                        "signal": signal,
                        "evidence": (
                            "actionable cooking instruction was marked other"
                            if signal == "imperative"
                            else "cause-and-effect or troubleshooting cooking guidance was marked other"
                        ),
                        "text_excerpt": excerpt(text),
                    }
                )
    flagged_block_indices = sorted(
        {
            int(flag.get("block_index"))
            for flag in flags
            if flag.get("block_index") is not None
        }
    )
    if flagged_block_indices:
        status = "repair_required"
    elif previous_requested:
        status = "passed_after_repair"
    else:
        status = "passed_clean"
    return {
        "schema_version": PASS1_SEMANTIC_AUDIT_SCHEMA_VERSION,
        "phase": "pass1",
        "shard_id": str(shard_id),
        "status": status,
        "repair_requested": previous_requested or bool(flagged_block_indices),
        "repair_cleared": bool(previous_requested and not flagged_block_indices),
        "flag_count": len(flags),
        "max_flag_count": max(
            len(flags),
            int(dict(previous_audit_payload or {}).get("max_flag_count") or 0),
        ),
        "flagged_block_indices": flagged_block_indices,
        "kept_block_indices": [
            block_index
            for block_index in ordered_block_indices
            if category_by_block_index.get(block_index) == "knowledge"
        ],
        "other_block_indices": [
            block_index
            for block_index in ordered_block_indices
            if category_by_block_index.get(block_index) == "other"
        ],
        "flags": flags,
    }


def build_pass1_repair_payload(input_payload, metadata, validation_errors, *, frozen_rows=None):
    unresolved = resolved_unresolved_block_indices(metadata)
    input_rows_by_block_index = pass1_input_rows_by_block_index(input_payload)
    merged_frozen_rows = merge_frozen_rows(
        frozen_rows,
        [
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, dict)
        ],
    )
    semantic_flags = [
        dict(flag)
        for flag in (metadata.get("semantic_audit_flags") or [])
        if isinstance(flag, dict)
    ]
    payload = {{
        "repair_mode": "knowledge_phase",
        "phase": "pass1",
        "repair_request_kind": (
            "semantic_suspicion" if semantic_flags else "validation"
        ),
        "accepted_block_indices": [
            int(row.get("block_index"))
            for row in merged_frozen_rows
            if row.get("block_index") is not None
        ],
        "unresolved_block_indices": unresolved,
        "validation_errors": [
            str(error).strip()
            for error in validation_errors
            if str(error).strip()
        ],
        "frozen_rows": merged_frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved
            if block_index in input_rows_by_block_index
        ],
    }}
    if metadata.get("semantic_audit_path"):
        payload["semantic_audit_path"] = str(metadata.get("semantic_audit_path"))
    if metadata.get("semantic_audit_status"):
        payload["semantic_audit_status"] = str(metadata.get("semantic_audit_status"))
    if semantic_flags:
        payload["semantic_flags"] = semantic_flags
    return payload


def build_pass2_repair_payload(pass2_input_payload, metadata, validation_errors, *, frozen_rows=None):
    unresolved = resolved_unresolved_block_indices(metadata)
    input_rows_by_block_index = pass2_input_rows_by_block_index(pass2_input_payload)
    merged_frozen_rows = merge_frozen_rows(
        frozen_rows,
        [
            dict(row)
            for row in (metadata.get("accepted_rows") or [])
            if isinstance(row, dict)
        ],
    )
    return {{
        "repair_mode": "knowledge_phase",
        "phase": "pass2",
        "accepted_block_indices": [
            int(row.get("block_index"))
            for row in merged_frozen_rows
            if row.get("block_index") is not None
        ],
        "unresolved_block_indices": unresolved,
        "validation_errors": [
            str(error).strip()
            for error in validation_errors
            if str(error).strip()
        ],
        "frozen_rows": merged_frozen_rows,
        "rows": [
            input_rows_by_block_index[block_index]
            for block_index in unresolved
            if block_index in input_rows_by_block_index
        ],
    }}


def validate_pass1(input_payload, payload, *, frozen_rows_by_block_index=None):
    expected = [
        int(block.get("i"))
        for block in input_blocks(input_payload)
        if block.get("i") is not None
    ]
    metadata = {{"expected_block_indices": expected, "owned_row_count": len(expected)}}
    if not isinstance(payload, dict):
        return ["payload_not_object"], metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ["rows_not_list"], metadata
    actual = []
    errors = []
    invalid = []
    unresolved = set()
    row_error_map = {{}}
    parsed_rows = []
    seen = set()
    duplicates = set()
    frozen_by_block_index = normalize_frozen_rows(frozen_rows_by_block_index)
    for row in rows:
        if not isinstance(row, dict) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual.append(block_index)
        row_errors = []
        category = str(row.get("category") or "").strip()
        if category not in {{"knowledge", "other"}}:
            row_errors.append("invalid_block_category")
        if block_index in seen:
            duplicates.add(block_index)
            row_errors.append("duplicate_block_index")
        seen.add(block_index)
        if row_errors:
            invalid.append(block_index)
            unresolved.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append({{"block_index": block_index, "category": category}})
    if actual != expected:
        missing = [idx for idx in expected if idx not in actual]
        unexpected = [idx for idx in actual if idx not in expected]
        if missing:
            errors.append("missing_owned_block_decisions")
            metadata["missing_owned_block_indices"] = missing
            unresolved.update(missing)
        if unexpected:
            errors.append("unexpected_block_decisions")
            metadata["unexpected_block_indices"] = unexpected
            unresolved.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved.update(expected)
    if invalid:
        errors.append("invalid_block_category")
        metadata["invalid_block_category_indices"] = invalid
    accepted_rows = []
    accepted_block_indices = []
    for position, expected_block_index in enumerate(expected):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in duplicates:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{{expected_block_index}}")
            invalid.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append("frozen_row_modified")
            unresolved.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["kept_block_indices"] = [
        int(row.get("block_index"))
        for row in rows
        if isinstance(row, dict) and str(row.get("category") or "").strip() == "knowledge"
    ]
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["row_errors_by_block_index"] = {{
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }}
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index for block_index in expected if block_index in unresolved
    ] or list(expected if errors else [])
    return list(dict.fromkeys(errors)), metadata


def validate_pass2(pass2_input_payload, payload, *, frozen_rows_by_block_index=None):
    expected = [
        int(row.get("block_index"))
        for row in (pass2_input_payload.get("rows") or [])
        if isinstance(row, dict) and row.get("block_index") is not None
    ]
    metadata = {{"expected_block_indices": expected, "owned_row_count": len(expected)}}
    if not isinstance(payload, dict):
        return ["payload_not_object"], metadata
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ["rows_not_list"], metadata
    actual = []
    group_key_to_topic = {{}}
    errors = []
    invalid = []
    unresolved = set()
    row_error_map = {{}}
    parsed_rows = []
    seen = set()
    duplicates = set()
    frozen_by_block_index = normalize_frozen_rows(frozen_rows_by_block_index)
    for row in rows:
        if not isinstance(row, dict) or row.get("block_index") is None:
            errors.append("row_missing_block_index")
            parsed_rows.append(None)
            continue
        block_index = int(row.get("block_index"))
        actual.append(block_index)
        row_errors = []
        group_key = pass2_group_key(row)
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_key or not topic_label:
            row_errors.append("knowledge_block_missing_group")
        previous = group_key_to_topic.get(group_key)
        if group_key and previous is None:
            group_key_to_topic[group_key] = topic_label
        elif group_key and previous != topic_label:
            row_errors.append("knowledge_block_group_conflict")
            metadata.setdefault("group_key_topic_conflicts", []).append(group_key)
        if block_index in seen:
            duplicates.add(block_index)
            row_errors.append("duplicate_block_index")
        seen.add(block_index)
        if row_errors:
            invalid.append(block_index)
            unresolved.add(block_index)
            row_error_map.setdefault(block_index, []).extend(row_errors)
        parsed_rows.append(
            {{
                "block_index": block_index,
                "group_key": group_key,
                "topic_label": topic_label,
            }}
        )
    if actual != expected:
        missing = [idx for idx in expected if idx not in actual]
        unexpected = [idx for idx in actual if idx not in expected]
        if missing:
            errors.append("knowledge_block_missing_group")
            metadata["knowledge_blocks_missing_group"] = missing
            unresolved.update(missing)
        if unexpected:
            errors.append("group_contains_other_block")
            metadata["group_blocks_out_of_surface"] = unexpected
            unresolved.update(unexpected)
        if not missing and not unexpected:
            errors.append("block_decision_order_mismatch")
            unresolved.update(expected)
    if invalid:
        errors.append("knowledge_block_missing_group")
        metadata.setdefault("knowledge_blocks_missing_group", []).extend(invalid)
    accepted_rows = []
    accepted_block_indices = []
    for position, expected_block_index in enumerate(expected):
        parsed_row = parsed_rows[position] if position < len(parsed_rows) else None
        if parsed_row is None:
            unresolved.add(expected_block_index)
            continue
        actual_block_index = int(parsed_row.get("block_index"))
        if actual_block_index != expected_block_index:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in duplicates:
            unresolved.add(expected_block_index)
            continue
        if actual_block_index in row_error_map:
            unresolved.add(expected_block_index)
            continue
        frozen_row = frozen_by_block_index.get(expected_block_index)
        if frozen_row is not None and dict(parsed_row) != frozen_row:
            errors.append(f"frozen_row_modified:{{expected_block_index}}")
            invalid.append(expected_block_index)
            row_error_map.setdefault(expected_block_index, []).append("frozen_row_modified")
            unresolved.add(expected_block_index)
            continue
        accepted_block_indices.append(expected_block_index)
        accepted_rows.append(dict(parsed_row))
    metadata["accepted_block_indices"] = accepted_block_indices
    metadata["accepted_rows"] = accepted_rows
    metadata["group_keys"] = sorted(group_key_to_topic)
    metadata["group_ids"] = list(metadata["group_keys"])
    metadata["row_errors_by_block_index"] = {{
        str(block_index): sorted(set(row_errors))
        for block_index, row_errors in sorted(row_error_map.items())
    }}
    metadata["frozen_block_indices"] = sorted(frozen_by_block_index)
    metadata["unresolved_block_indices"] = [
        block_index for block_index in expected if block_index in unresolved
    ] or list(expected if errors else [])
    return list(dict.fromkeys(errors)), metadata


def render_phase_brief(phase_row):
    if phase_row is None:
        return "# Current Knowledge Phase\\n\\nNo active knowledge shard.\\n"
    if str(phase_row.get("status") or "").strip() == "completed":
        return "# Current Knowledge Phase\\n\\nAll assigned knowledge shards are installed.\\n"
    lines = [
        "# Current Knowledge Phase",
        "",
        f"Shard id: `{{phase_row.get('shard_id') or '[unknown shard]'}}`",
        f"Phase: `{{phase_row.get('phase') or '[unknown phase]'}}`",
        f"Input file: `{{phase_row.get('input_path') or '?'}}`",
        f"Work file: `{{phase_row.get('work_path') or '?'}}`",
        f"Repair file: `{{phase_row.get('repair_path') or '?'}}`",
        f"Semantic audit file: `{{phase_row.get('semantic_audit_path') or '?'}}`",
        f"Result file: `{{phase_row.get('result_path') or '?'}}`",
        "",
    ]
    if str(phase_row.get("phase") or "").strip() == "pass1":
        lines.extend([
            "Pass 1 contract: make the first-authority semantic judgment on the owned rows.",
            "The repo does not know the `knowledge` versus `other` answer ahead of time.",
            "Each work row carries raw block text plus mechanical truth; fill only `category` with `knowledge` or `other`.",
            "Do not create topic labels or grouping keys in Pass 1.",
            "Before Pass 2, repo code runs one narrow semantic suspicion audit over structurally valid Pass 1 rows.",
            "If that audit flags rows, patch only the flagged rows in the same Pass 1 work ledger. The audit packages evidence; it does not know the right semantic answer for you.",
        ])
    else:
        lines.extend([
            "Pass 2 contract: continue from the accepted Pass 1 knowledge rows only.",
            "Assign each kept row a non-empty local `group_key` and `topic_label`.",
            "Use the same `group_key` on rows that belong in the same idea group; the repo will canonicalize final `group_id` values later.",
        ])
    return "\\n".join(lines) + "\\n"


def render_phase_feedback(phase_row, validation_errors=(), validation_metadata=None, *, completed=False):
    if completed:
        return "# Current Phase Feedback\\n\\nAll assigned knowledge shards are installed.\\n"
    if phase_row is None:
        return "# Current Phase Feedback\\n\\nNo active knowledge shard.\\n"
    if not validation_errors:
        semantic_audit_status = ""
        if isinstance(validation_metadata, dict):
            semantic_audit_status = str(validation_metadata.get("semantic_audit_status") or "").strip()
        clean_line = "Current work ledger validates cleanly."
        if semantic_audit_status:
            clean_line = "Current work ledger and Pass 1 semantic suspicion audit validate cleanly."
        cleared_line = (
            "Previous semantic suspicion flags were cleared in this same session.\\n"
            if semantic_audit_status == "passed_after_repair"
            else ""
        )
        return (
            "# Current Phase Feedback\\n\\n"
            f"{{clean_line}}\\n"
            f"Install target: `{{phase_row.get('result_path') or '<missing>'}}`\\n"
            f"{{cleared_line}}"
            "Next command: `python3 tools/knowledge_worker.py install-phase`.\\n"
        )
    unresolved = []
    if isinstance(validation_metadata, dict):
        unresolved = [
            int(value)
            for value in (validation_metadata.get("unresolved_block_indices") or [])
            if str(value).strip()
        ]
    lines = [
        "# Current Phase Feedback",
        "",
        (
            "Pass 1 semantic suspicion audit flagged rows for same-session repair."
            if isinstance(validation_metadata, dict)
            and bool(validation_metadata.get("semantic_audit_flags"))
            else "Current work ledger is still unresolved."
        ),
        "Validation errors:",
    ]
    lines.extend(f"- `{{error}}`" for error in validation_errors if str(error).strip())
    if phase_row.get("repair_path"):
        lines.append(f"Repair request: `{{phase_row.get('repair_path')}}`")
    if isinstance(validation_metadata, dict) and validation_metadata.get("semantic_audit_path"):
        lines.append(f"Semantic audit file: `{{validation_metadata.get('semantic_audit_path')}}`")
    if unresolved:
        lines.append(
            "Unresolved block indices: "
            f"`{{', '.join(str(value) for value in unresolved)}}`"
        )
    accepted = []
    if isinstance(validation_metadata, dict):
        accepted = [
            int(value)
            for value in (
                validation_metadata.get("frozen_block_indices")
                or validation_metadata.get("accepted_block_indices")
                or []
            )
            if str(value).strip()
        ]
    if accepted:
        lines.append(
            "Frozen accepted block indices: "
            f"`{{', '.join(str(value) for value in accepted)}}`"
        )
    semantic_flags = []
    if isinstance(validation_metadata, dict):
        semantic_flags = [
            dict(flag)
            for flag in (validation_metadata.get("semantic_audit_flags") or [])
            if isinstance(flag, dict)
        ]
    if semantic_flags:
        lines.append("Semantic suspicion evidence:")
        for flag in semantic_flags:
            lines.append(
                "- block "
                f"{{flag.get('block_index')}}: `{{flag.get('code')}}` {{flag.get('evidence')}}"
            )
    lines.append("Next command after fixes: `python3 tools/knowledge_worker.py check-phase`.")
    return "\\n".join(lines) + "\\n"


def write_phase_surface(
    phase_row,
    *,
    validation_errors=(),
    validation_metadata=None,
    completed=False,
    frozen_rows=None,
):
    phase_payload = dict(phase_row or {{}})
    if completed:
        phase_payload = {{
            "status": "completed",
            "phase": None,
            "shard_id": None,
        }}
    elif frozen_rows:
        phase_payload["frozen_rows"] = [
            dict(row)
            for row in frozen_rows
            if isinstance(row, dict) and row.get("block_index") is not None
        ]
    else:
        phase_payload.pop("frozen_rows", None)
    save_json(workspace_root() / "current_phase.json", phase_payload)
    save_text(workspace_root() / "CURRENT_PHASE.md", render_phase_brief(phase_payload))
    save_text(
        workspace_root() / "CURRENT_PHASE_FEEDBACK.md",
        render_phase_feedback(
            phase_payload,
            validation_errors=validation_errors,
            validation_metadata=validation_metadata,
            completed=completed,
        ),
    )


def ensure_pass1_work(phase_row):
    work_path = workspace_root() / str(phase_row.get("work_path") or "")
    expected_seed = build_pass1_seed(load_phase_input(phase_row))
    if work_path.exists():
        try:
            existing_payload = load_json(work_path)
        except Exception:
            existing_payload = None
        if (
            isinstance(existing_payload, dict)
            and str(existing_payload.get("phase") or "").strip() == "pass1"
            and isinstance(existing_payload.get("rows"), list)
        ):
            existing_rows = existing_payload.get("rows") or []
            expected_rows_by_block_index = {{
                int(row["block_index"]): dict(row)
                for row in expected_seed["rows"]
                if row.get("block_index") is not None
            }}
            migrated_rows = []
            for existing_row in existing_rows:
                if not isinstance(existing_row, dict):
                    migrated_rows = []
                    break
                try:
                    block_index = int(existing_row.get("block_index"))
                except (TypeError, ValueError):
                    migrated_rows = []
                    break
                migrated_row = dict(
                    expected_rows_by_block_index.get(
                        block_index,
                        {{
                            "block_index": block_index,
                            "text": "",
                            "category": "",
                        }},
                    )
                )
                if existing_row.get("category") is not None:
                    migrated_row["category"] = str(existing_row.get("category") or "").strip()
                migrated_rows.append(migrated_row)
            if migrated_rows:
                save_json(work_path, {{"phase": "pass1", "rows": migrated_rows}})
                return
        save_json(work_path, expected_seed)
        return
    save_json(work_path, expected_seed)


def ensure_pass2_work(phase_row):
    work_path = workspace_root() / str(phase_row.get("work_path") or "")
    expected_seed = build_pass2_seed(load_phase_input(phase_row))
    if work_path.exists():
        try:
            existing_payload = load_json(work_path)
        except Exception:
            existing_payload = None
        if (
            isinstance(existing_payload, dict)
            and str(existing_payload.get("phase") or "").strip() == "pass2"
            and isinstance(existing_payload.get("rows"), list)
        ):
            existing_rows = existing_payload.get("rows") or []
            expected_rows_by_block_index = {{
                int(row["block_index"]): dict(row)
                for row in expected_seed["rows"]
                if row.get("block_index") is not None
            }}
            migrated_rows = []
            for existing_row in existing_rows:
                if not isinstance(existing_row, dict):
                    migrated_rows = []
                    break
                try:
                    block_index = int(existing_row.get("block_index"))
                except (TypeError, ValueError):
                    migrated_rows = []
                    break
                migrated_row = dict(
                    expected_rows_by_block_index.get(
                        block_index,
                        {{
                            "block_index": block_index,
                            "category": "knowledge",
                            "text": "",
                            "group_key": "",
                            "topic_label": "",
                        }},
                    )
                )
                group_key = pass2_group_key(existing_row)
                if group_key:
                    migrated_row["group_key"] = group_key
                if existing_row.get("topic_label") is not None:
                    migrated_row["topic_label"] = str(existing_row.get("topic_label") or "").strip()
                migrated_rows.append(migrated_row)
            if migrated_rows:
                save_json(work_path, {{"phase": "pass2", "rows": migrated_rows}})
                return
        save_json(work_path, expected_seed)
        return
    save_json(work_path, expected_seed)


def build_final_output(phase_row, pass1_payload, pass2_payload):
    shard_id = str(phase_row.get("shard_id") or "")
    decisions = [
        {{
            "block_index": int(row.get("block_index")),
            "category": str(row.get("category") or "").strip(),
            "reviewer_category": (
                "knowledge"
                if str(row.get("category") or "").strip() == "knowledge"
                else "other"
            ),
        }}
        for row in (pass1_payload.get("rows") or [])
        if isinstance(row, dict) and row.get("block_index") is not None
    ]
    groups_by_key = {{}}
    for row in (pass2_payload.get("rows") or []):
        if not isinstance(row, dict) or row.get("block_index") is None:
            continue
        group_key = pass2_group_key(row)
        topic_label = str(row.get("topic_label") or "").strip()
        if not group_key or not topic_label:
            continue
        group = groups_by_key.setdefault(
            group_key,
            {{"group_key": group_key, "topic_label": topic_label, "block_indices": []}},
        )
        group["block_indices"].append(int(row.get("block_index")))
    return {{
        "packet_id": shard_id,
        "block_decisions": decisions,
        "idea_groups": [
            {{
                "group_id": f"g{{index:02d}}",
                "topic_label": group["topic_label"],
                "block_indices": group["block_indices"],
            }}
            for index, group in enumerate(groups_by_key.values(), start=1)
        ],
    }}


def next_phase_row(current_phase_row):
    shard_rows = assigned_shards()
    shard_ids = [str(row.get("shard_id") or "").strip() for row in shard_rows]
    current_shard_id = str(current_phase_row.get("shard_id") or "").strip()
    if current_shard_id not in shard_ids:
        return {{"status": "completed", "phase": None, "shard_id": None}}
    current_index = shard_ids.index(current_shard_id)
    for next_row in shard_rows[current_index + 1 :]:
        shard_id = str(next_row.get("shard_id") or "").strip()
        if not shard_id:
            continue
        result_path = workspace_root() / "out" / f"{{shard_id}}.json"
        if result_path.exists():
            continue
        return {{
            "status": "active",
            "phase": "pass1",
            "shard_id": shard_id,
            "input_path": f"in/{{shard_id}}.json",
            "work_path": f"work/{{shard_id}}.pass1.json",
            "repair_path": f"repair/{{shard_id}}.pass1.json",
            "semantic_audit_path": f"shards/{{shard_id}}/semantic_audit.json",
            "result_path": f"out/{{shard_id}}.json",
            "hint_path": f"hints/{{shard_id}}.md",
        }}
    return {{"status": "completed", "phase": None, "shard_id": None}}


def scaffold_current_phase():
    phase_row = current_phase()
    if not isinstance(phase_row, dict):
        raise SystemExit("current_phase.json is missing")
    if str(phase_row.get("status") or "").strip() == "completed":
        print("all assigned knowledge shards are installed")
        return 0
    if str(phase_row.get("phase") or "").strip() == "pass1":
        ensure_pass1_work(phase_row)
    else:
        ensure_pass2_work(phase_row)
    print(str(phase_row.get("work_path") or ""))
    return 0


def check_current_phase():
    phase_row = current_phase()
    if not isinstance(phase_row, dict):
        raise SystemExit("current_phase.json is missing")
    if str(phase_row.get("status") or "").strip() == "completed":
        write_phase_surface(phase_row, completed=True)
        print("all assigned knowledge shards are installed")
        return 0
    if str(phase_row.get("phase") or "").strip() == "pass1":
        ensure_pass1_work(phase_row)
    else:
        ensure_pass2_work(phase_row)
    work_payload = load_phase_work(phase_row)
    input_payload = load_phase_input(phase_row)
    frozen_rows = phase_row.get("frozen_rows")
    semantic_audit_path = workspace_root() / str(phase_row.get("semantic_audit_path") or "")
    if str(phase_row.get("phase") or "").strip() == "pass1":
        errors, metadata = validate_pass1(
            input_payload,
            work_payload,
            frozen_rows_by_block_index=frozen_rows,
        )
    else:
        errors, metadata = validate_pass2(
            input_payload,
            work_payload,
            frozen_rows_by_block_index=frozen_rows,
        )
    metadata = dict(metadata)
    accepted_rows = [
        dict(row)
        for row in (metadata.get("accepted_rows") or [])
        if isinstance(row, dict)
    ]
    if str(phase_row.get("phase") or "").strip() == "pass1" and not errors:
        previous_audit_payload = load_optional_json(semantic_audit_path)
        semantic_audit_payload = build_pass1_semantic_audit(
            str(phase_row.get("shard_id") or ""),
            input_payload,
            work_payload,
            previous_audit_payload=previous_audit_payload,
        )
        save_json(semantic_audit_path, semantic_audit_payload)
        metadata["semantic_audit_path"] = relative_path(semantic_audit_path)
        metadata["semantic_audit_status"] = str(semantic_audit_payload.get("status") or "").strip()
        metadata["semantic_audit_flags"] = [
            dict(flag)
            for flag in (semantic_audit_payload.get("flags") or [])
            if isinstance(flag, dict)
        ]
        metadata["semantic_audit_flagged_block_indices"] = [
            int(value)
            for value in (semantic_audit_payload.get("flagged_block_indices") or [])
            if str(value).strip()
        ]
        if metadata["semantic_audit_flagged_block_indices"]:
            flagged = set(metadata["semantic_audit_flagged_block_indices"])
            errors = [PASS1_SEMANTIC_SUSPICION_ERROR]
            accepted_rows = [
                row
                for row in accepted_rows
                if int(row.get("block_index")) not in flagged
            ]
            metadata["accepted_rows"] = accepted_rows
            metadata["accepted_block_indices"] = [
                int(row.get("block_index"))
                for row in accepted_rows
                if row.get("block_index") is not None
            ]
            metadata["unresolved_block_indices"] = list(
                metadata["semantic_audit_flagged_block_indices"]
            )
    merged_frozen_rows = merge_frozen_rows(frozen_rows, accepted_rows)
    metadata["frozen_block_indices"] = [
        int(row.get("block_index"))
        for row in merged_frozen_rows
        if row.get("block_index") is not None
    ]
    repair_path = workspace_root() / str(phase_row.get("repair_path") or "")
    if errors:
        if str(phase_row.get("phase") or "").strip() == "pass1":
            repair_payload = build_pass1_repair_payload(
                input_payload,
                metadata,
                errors,
                frozen_rows=frozen_rows,
            )
        else:
            repair_payload = build_pass2_repair_payload(
                input_payload,
                metadata,
                errors,
                frozen_rows=frozen_rows,
            )
        save_json(repair_path, repair_payload)
        write_phase_surface(
            phase_row,
            validation_errors=errors,
            validation_metadata=metadata,
            frozen_rows=merged_frozen_rows,
        )
        print("\\n".join(errors))
        return 1
    if repair_path.exists():
        repair_path.unlink()
    write_phase_surface(
        phase_row,
        validation_metadata=metadata,
        frozen_rows=merged_frozen_rows,
    )
    print("ok")
    return 0


def install_current_phase():
    phase_row = current_phase()
    if not isinstance(phase_row, dict):
        raise SystemExit("current_phase.json is missing")
    if check_current_phase() != 0:
        raise SystemExit("knowledge phase failed validation")
    phase_row = current_phase()
    work_payload = load_phase_work(phase_row)
    frozen_rows = phase_row.get("frozen_rows")
    if str(phase_row.get("phase") or "").strip() == "pass1":
        input_payload = load_phase_input(phase_row)
        errors, metadata = validate_pass1(
            input_payload,
            work_payload,
            frozen_rows_by_block_index=frozen_rows,
        )
        if errors:
            raise SystemExit("knowledge phase failed validation")
        pass2_input = build_pass2_input(input_payload, work_payload)
        pass2_input_path = workspace_root() / "in" / f"{{phase_row['shard_id']}}.pass2.json"
        save_json(pass2_input_path, pass2_input)
        next_row = dict(phase_row)
        next_row.pop("frozen_rows", None)
        next_row["phase"] = "pass2"
        next_row["input_path"] = relative_path(pass2_input_path)
        next_row["work_path"] = f"work/{{phase_row['shard_id']}}.pass2.json"
        next_row["repair_path"] = f"repair/{{phase_row['shard_id']}}.pass2.json"
        save_json(workspace_root() / next_row["work_path"], build_pass2_seed(pass2_input))
        write_phase_surface(next_row)
        print("advanced to pass2")
        return 0
    pass1_path = workspace_root() / "work" / f"{{phase_row['shard_id']}}.pass1.json"
    pass1_payload = load_json(pass1_path)
    errors, metadata = validate_pass2(
        load_phase_input(phase_row),
        work_payload,
        frozen_rows_by_block_index=frozen_rows,
    )
    if errors:
        raise SystemExit("knowledge phase failed validation")
    final_payload = build_final_output(phase_row, pass1_payload, work_payload)
    save_json(workspace_root() / str(phase_row.get("result_path") or ""), final_payload)
    next_row = next_phase_row(phase_row)
    if str(next_row.get("status") or "").strip() == "completed":
        write_phase_surface(next_row, completed=True)
        print("queue complete")
        return 0
    next_row.pop("frozen_rows", None)
    ensure_pass1_work(next_row)
    write_phase_surface(next_row)
    print(f"advanced to {{next_row['shard_id']}} pass1")
    return 0


def write_static_artifacts():
    save_text(workspace_root() / "OUTPUT_CONTRACT.md", OUTPUT_CONTRACT_MARKDOWN)
    examples_dir = workspace_root() / "examples"
    save_text(examples_dir / "valid_knowledge_output.json", VALID_EXAMPLE_JSON)
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scaffold-phase")
    subparsers.add_parser("check-phase")
    subparsers.add_parser("install-phase")
    subparsers.add_parser("write-static")
    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "scaffold-phase":
        return scaffold_current_phase()
    if args.command == "check-phase":
        return check_current_phase()
    if args.command == "install-phase":
        return install_current_phase()
    if args.command == "write-static":
        return write_static_artifacts()
    raise SystemExit(f"unknown command: {{args.command}}")


if __name__ == "__main__":
    raise SystemExit(main())
"""
    return (
        script.replace("__OUTPUT_CONTRACT_MARKDOWN__", output_contract_markdown)
        .replace("__VALID_EXAMPLE_JSON__", valid_example_json)
        .replace("{{", "{")
        .replace("}}", "}")
    )


def write_knowledge_worker_examples(*, worker_root: Path) -> None:
    examples_dir = worker_root / "examples"
    _save_text(
        examples_dir / KNOWLEDGE_VALID_OUTPUT_EXAMPLE_FILENAME,
        json.dumps(KNOWLEDGE_VALID_OUTPUT_EXAMPLE_PAYLOAD, indent=2, sort_keys=True) + "\n",
    )


def write_knowledge_output_contract(*, worker_root: Path) -> None:
    _save_text(worker_root / "OUTPUT_CONTRACT.md", KNOWLEDGE_OUTPUT_CONTRACT_MARKDOWN)


def write_knowledge_worker_tools(*, worker_root: Path) -> None:
    tools_dir = worker_root / "tools"
    tool_path = tools_dir / KNOWLEDGE_WORKER_TOOL_FILENAME
    _save_text(tool_path, render_knowledge_worker_script())
    tool_path.chmod(0o755)
