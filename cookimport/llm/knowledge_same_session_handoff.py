from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .editable_task_file import TASK_FILE_NAME, load_task_file, write_task_file
from .knowledge_stage.task_file_contracts import (
    KnowledgeTaskFileTransition,
    transition_knowledge_classification_task_file,
    transition_knowledge_grouping_task_file,
)

KNOWLEDGE_SAME_SESSION_HANDOFF_SCHEMA_VERSION = "knowledge_same_session_handoff.v1"
KNOWLEDGE_SAME_SESSION_STATE_ENV = "RECIPEIMPORT_KNOWLEDGE_SAME_SESSION_STATE_PATH"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def initialize_knowledge_same_session_state(
    *,
    state_path: Path,
    assignment_id: str,
    worker_id: str,
    classification_task_file: Mapping[str, Any],
    unit_to_shard_id: Mapping[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    payload = {
        "schema_version": KNOWLEDGE_SAME_SESSION_HANDOFF_SCHEMA_VERSION,
        "assignment_id": str(assignment_id),
        "worker_id": str(worker_id),
        "current_stage_key": str(classification_task_file.get("stage_key") or ""),
        "current_original_task_file": dict(classification_task_file),
        "classification_task_file": dict(classification_task_file),
        "classification_answers_by_unit_id": {},
        "grouping_answers_by_unit_id": {},
        "unit_to_shard_id": {
            str(unit_id): str(shard_id)
            for unit_id, shard_id in unit_to_shard_id.items()
        },
        "output_dir": str(output_dir),
        "same_session_transition_count": 0,
        "classification_validation_count": 0,
        "grouping_validation_count": 0,
        "same_session_repair_rewrite_count": 0,
        "grouping_transition_count": 0,
        "grouping_unit_count": 0,
        "final_output_shard_count": 0,
        "completed": False,
        "final_status": None,
        "transition_history": [],
    }
    _write_json(state_path, payload)
    return payload


def _append_transition_history(
    *,
    state: dict[str, Any],
    transition: KnowledgeTaskFileTransition,
) -> None:
    history = list(state.get("transition_history") or [])
    history.append(
        {
            "status": transition.status,
            "current_stage_key": transition.current_stage_key,
            "next_stage_key": transition.next_stage_key,
            "validation_errors": list(transition.validation_errors),
            "validation_metadata": dict(transition.validation_metadata),
            "transition_metadata": dict(transition.transition_metadata),
        }
    )
    state["transition_history"] = history


def _record_transition_counters(
    *,
    state: dict[str, Any],
    transition: KnowledgeTaskFileTransition,
) -> None:
    if transition.status == "no_edits_detected":
        return
    state["same_session_transition_count"] = int(
        state.get("same_session_transition_count") or 0
    ) + 1
    if transition.current_stage_key == "nonrecipe_classify":
        state["classification_validation_count"] = int(
            state.get("classification_validation_count") or 0
        ) + 1
    elif transition.current_stage_key == "knowledge_group":
        state["grouping_validation_count"] = int(
            state.get("grouping_validation_count") or 0
        ) + 1
    if transition.status == "repair_required":
        state["same_session_repair_rewrite_count"] = int(
            state.get("same_session_repair_rewrite_count") or 0
        ) + 1
    if transition.status == "advance_to_grouping":
        state["grouping_transition_count"] = int(
            state.get("grouping_transition_count") or 0
        ) + 1


def _write_final_outputs(*, output_dir: Path, final_outputs: Mapping[str, Mapping[str, Any]]) -> None:
    for shard_id, payload in final_outputs.items():
        _write_json(output_dir / f"{shard_id}.json", payload)


def _repair_exhausted_result(
    *,
    state: Mapping[str, Any],
    transition: KnowledgeTaskFileTransition,
) -> dict[str, Any]:
    return {
        "status": "repair_exhausted",
        "current_stage_key": transition.current_stage_key,
        "next_stage_key": transition.next_stage_key,
        "same_session_transition_count": int(state.get("same_session_transition_count") or 0),
        "classification_validation_count": int(
            state.get("classification_validation_count") or 0
        ),
        "grouping_validation_count": int(state.get("grouping_validation_count") or 0),
        "same_session_repair_rewrite_count": int(
            state.get("same_session_repair_rewrite_count") or 0
        ),
        "grouping_transition_count": int(state.get("grouping_transition_count") or 0),
        "completed": False,
        "final_status": state.get("final_status"),
        "final_output_shard_count": int(state.get("final_output_shard_count") or 0),
        "validation_errors": list(transition.validation_errors),
        "validation_metadata": dict(transition.validation_metadata),
        "transition_metadata": dict(transition.transition_metadata),
    }


def advance_knowledge_same_session_handoff(
    *,
    workspace_root: Path,
    state_path: Path,
) -> dict[str, Any]:
    state = _load_json_dict(state_path)
    task_file_path = workspace_root / TASK_FILE_NAME
    edited_task_file = load_task_file(task_file_path)
    current_stage_key = str(state.get("current_stage_key") or "").strip()
    current_original_task_file = dict(state.get("current_original_task_file") or {})
    unit_to_shard_id = {
        str(unit_id): str(shard_id)
        for unit_id, shard_id in dict(state.get("unit_to_shard_id") or {}).items()
    }

    if current_stage_key == "nonrecipe_classify":
        transition = transition_knowledge_classification_task_file(
            original_task_file=current_original_task_file,
            edited_task_file=edited_task_file,
            unit_to_shard_id=unit_to_shard_id,
        )
    elif current_stage_key == "knowledge_group":
        transition = transition_knowledge_grouping_task_file(
            original_task_file=current_original_task_file,
            edited_task_file=edited_task_file,
            classification_task_file=dict(state.get("classification_task_file") or {}),
            classification_answers_by_unit_id=dict(
                state.get("classification_answers_by_unit_id") or {}
            ),
            unit_to_shard_id=unit_to_shard_id,
        )
    else:
        raise ValueError(f"unsupported current stage key {current_stage_key!r}")

    _record_transition_counters(state=state, transition=transition)
    _append_transition_history(state=state, transition=transition)

    if transition.current_stage_key == "nonrecipe_classify" and transition.validated_answers_by_unit_id:
        state["classification_answers_by_unit_id"] = dict(
            transition.validated_answers_by_unit_id
        )
    if transition.current_stage_key == "knowledge_group" and transition.validated_answers_by_unit_id:
        state["grouping_answers_by_unit_id"] = dict(transition.validated_answers_by_unit_id)

    current_mode = str(current_original_task_file.get("mode") or "initial").strip() or "initial"
    if transition.status == "repair_required" and current_mode == "repair":
        state["same_session_repair_rewrite_count"] = max(
            0,
            int(state.get("same_session_repair_rewrite_count") or 0) - 1,
        )
        state["completed"] = False
        state["final_status"] = "repair_exhausted"
        _write_json(state_path, state)
        return _repair_exhausted_result(state=state, transition=transition)

    if transition.next_task_file is not None:
        write_task_file(path=task_file_path, payload=transition.next_task_file)
        state["current_original_task_file"] = dict(transition.next_task_file)
        state["current_stage_key"] = str(
            transition.next_stage_key or transition.current_stage_key
        )
    if transition.status == "advance_to_grouping":
        state["grouping_unit_count"] = int(
            transition.transition_metadata.get("grouping_unit_count") or 0
        )
    if transition.final_outputs is not None:
        output_dir = Path(str(state.get("output_dir") or "")).expanduser()
        _write_final_outputs(output_dir=output_dir, final_outputs=transition.final_outputs)
        state["completed"] = True
        state["final_status"] = transition.status
        state["final_output_shard_count"] = len(transition.final_outputs)

    _write_json(state_path, state)
    return {
        "status": transition.status,
        "current_stage_key": transition.current_stage_key,
        "next_stage_key": transition.next_stage_key,
        "same_session_transition_count": int(state.get("same_session_transition_count") or 0),
        "classification_validation_count": int(
            state.get("classification_validation_count") or 0
        ),
        "grouping_validation_count": int(state.get("grouping_validation_count") or 0),
        "same_session_repair_rewrite_count": int(
            state.get("same_session_repair_rewrite_count") or 0
        ),
        "grouping_transition_count": int(state.get("grouping_transition_count") or 0),
        "completed": bool(state.get("completed")),
        "final_status": state.get("final_status"),
        "final_output_shard_count": int(state.get("final_output_shard_count") or 0),
        "validation_errors": list(transition.validation_errors),
        "validation_metadata": dict(transition.validation_metadata),
        "transition_metadata": dict(transition.transition_metadata),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and advance one knowledge same-session task.json handoff."
    )
    parser.add_argument(
        "--state-path",
        default=os.environ.get(KNOWLEDGE_SAME_SESSION_STATE_ENV),
        help=f"Path to the hidden repo-owned handoff state file. Defaults to ${KNOWLEDGE_SAME_SESSION_STATE_ENV}.",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root containing task.json. Defaults to the current directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    state_path = Path(str(args.state_path or "")).expanduser()
    if not str(args.state_path or "").strip():
        raise SystemExit(f"missing --state-path or ${KNOWLEDGE_SAME_SESSION_STATE_ENV}")
    result = advance_knowledge_same_session_handoff(
        workspace_root=Path(str(args.workspace_root)).expanduser(),
        state_path=state_path,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
