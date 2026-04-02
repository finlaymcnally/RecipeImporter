from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

STRUCTURED_SESSION_LINEAGE_FILE_NAME = "session_lineage.json"
STRUCTURED_SESSION_LINEAGE_SCHEMA_VERSION = "structured_session_lineage.v1"


def structured_session_lineage_path(worker_root: Path) -> Path:
    return Path(worker_root) / STRUCTURED_SESSION_LINEAGE_FILE_NAME


def load_structured_session_lineage(worker_root: Path) -> dict[str, Any]:
    path = structured_session_lineage_path(worker_root)
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def initialize_structured_session_lineage(
    *,
    worker_root: Path,
    assignment_id: str,
    execution_working_dir: Path,
) -> dict[str, Any]:
    lineage_path = structured_session_lineage_path(worker_root)
    resolved_execution_dir = str(Path(execution_working_dir).resolve(strict=False))
    existing = load_structured_session_lineage(worker_root)
    if existing:
        existing_execution_dir = str(existing.get("execution_working_dir") or "").strip()
        if existing_execution_dir and existing_execution_dir != resolved_execution_dir:
            raise ValueError(
                "Structured session lineage is ambiguous: "
                f"{existing_execution_dir} vs {resolved_execution_dir}"
            )
        return existing
    payload = {
        "schema_version": STRUCTURED_SESSION_LINEAGE_SCHEMA_VERSION,
        "assignment_id": str(assignment_id or "").strip(),
        "execution_working_dir": resolved_execution_dir,
        "session_lineage_count": 1,
        "turn_count": 0,
        "turns": [],
    }
    lineage_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def assert_structured_session_can_resume(
    *,
    worker_root: Path,
    execution_working_dir: Path,
) -> dict[str, Any]:
    payload = load_structured_session_lineage(worker_root)
    if not payload:
        raise ValueError("Structured session lineage is missing.")
    if int(payload.get("session_lineage_count") or 0) != 1:
        raise ValueError(
            "Structured session lineage is ambiguous: "
            f"session_lineage_count={payload.get('session_lineage_count')!r}"
        )
    expected_execution_dir = str(payload.get("execution_working_dir") or "").strip()
    resolved_execution_dir = str(Path(execution_working_dir).resolve(strict=False))
    if not expected_execution_dir or expected_execution_dir != resolved_execution_dir:
        raise ValueError(
            "Structured session lineage execution workspace mismatch: "
            f"{expected_execution_dir or '[missing]'} vs {resolved_execution_dir}"
        )
    if int(payload.get("turn_count") or 0) <= 0:
        raise ValueError("Structured session resume requested before any initial turn was recorded.")
    return payload


def record_structured_session_turn(
    *,
    worker_root: Path,
    execution_working_dir: Path,
    turn_kind: str,
    packet_path: Path | None = None,
    prompt_path: Path | None = None,
    response_path: Path | None = None,
) -> dict[str, Any]:
    payload = initialize_structured_session_lineage(
        worker_root=worker_root,
        assignment_id=str(load_structured_session_lineage(worker_root).get("assignment_id") or ""),
        execution_working_dir=execution_working_dir,
    )
    turns = [dict(row) for row in (payload.get("turns") or []) if isinstance(row, Mapping)]
    turn_index = len(turns) + 1
    turns.append(
        {
            "turn_index": turn_index,
            "turn_kind": str(turn_kind or "").strip() or f"turn_{turn_index}",
            "packet_path": str(packet_path) if packet_path is not None else None,
            "prompt_path": str(prompt_path) if prompt_path is not None else None,
            "response_path": str(response_path) if response_path is not None else None,
        }
    )
    updated = {
        **payload,
        "execution_working_dir": str(Path(execution_working_dir).resolve(strict=False)),
        "session_lineage_count": 1,
        "turn_count": turn_index,
        "turns": turns,
    }
    structured_session_lineage_path(worker_root).write_text(
        json.dumps(updated, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return updated
