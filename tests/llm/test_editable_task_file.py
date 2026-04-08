from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.editable_task_file import _load_answer_mapping_file
from cookimport.llm.editable_task_file import apply_answers_to_task_file
from cookimport.llm.editable_task_file import build_worker_task_brief
from cookimport.llm.editable_task_file import build_repair_task_file
from cookimport.llm.editable_task_file import build_task_file
from cookimport.llm.editable_task_file import inspect_task_file_units
from cookimport.llm.editable_task_file import load_task_file
from cookimport.llm.editable_task_file import SUMMARY_UNIT_ID_SAMPLE_LIMIT
from cookimport.llm.editable_task_file import summarize_task_file
from cookimport.llm.editable_task_file import write_task_file
from cookimport.llm.editable_task_file import validate_edited_task_file
from cookimport.llm.task_file_guardrails import render_task_file_text


def _base_task_file() -> dict[str, object]:
    return build_task_file(
        stage_key="line_role",
        assignment_id="worker-001",
        worker_id="worker-001",
        helper_commands={"status": "python3 -m stage --status"},
        next_action="fill answers then run helper",
        answer_schema={
            "editable_pointer_pattern": "/units/*/answer",
            "example_answers": [{"label": "RECIPE_NOTES"}],
        },
        units=[
            {
                "unit_id": "line::0",
                "owned_id": "0",
                "evidence": {"atomic_index": 0, "text": "Ambiguous line"},
                "answer": {"label": "NONRECIPE_CANDIDATE"},
            },
            {
                "unit_id": "line::1",
                "owned_id": "1",
                "evidence": {"atomic_index": 1, "text": "Discard me"},
                "answer": {"label": "NONRECIPE_CANDIDATE"},
            },
        ],
    )


def test_validate_edited_task_file_accepts_answer_only_edits() -> None:
    original = _base_task_file()
    edited = _base_task_file()
    edited["units"][0]["answer"] = {  # type: ignore[index]
        "label": "RECIPE_NOTES",
    }

    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["changed_unit_count"] == 1
    assert answers_by_unit_id == {
        "line::0": {"label": "RECIPE_NOTES"},
        "line::1": {"label": "NONRECIPE_CANDIDATE"},
    }


def test_validate_edited_task_file_rejects_immutable_field_change() -> None:
    original = _base_task_file()
    edited = _base_task_file()
    edited["units"][0]["evidence"]["text"] = "mutated"  # type: ignore[index]

    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original,
        edited_task_file=edited,
    )

    assert answers_by_unit_id is None
    assert errors == ("immutable_field_changed",)
    assert metadata["error_details"] == [
        {
            "path": "/units/0/evidence",
            "code": "immutable_field_changed",
            "message": "/units/0/evidence must not change",
        }
    ]


def test_validate_edited_task_file_can_recover_answers_while_ignoring_immutable_drift() -> None:
    original = _base_task_file()
    edited = _base_task_file()
    edited["units"][0]["evidence"]["text"] = "mutated"  # type: ignore[index]
    edited["units"][0]["answer"] = {  # type: ignore[index]
        "label": "RECIPE_NOTES",
    }

    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original,
        edited_task_file=edited,
        allow_immutable_field_changes=True,
    )

    assert errors == ()
    assert metadata["immutable_field_drift_ignored"] is True
    assert metadata["error_details"] == []
    assert metadata["ignored_error_details"] == [
        {
            "path": "/units/0/evidence",
            "code": "immutable_field_changed",
            "message": "/units/0/evidence must not change",
        }
    ]
    assert answers_by_unit_id == {
        "line::0": {"label": "RECIPE_NOTES"},
        "line::1": {"label": "NONRECIPE_CANDIDATE"},
    }


def test_build_repair_task_file_keeps_only_failed_units_with_feedback() -> None:
    original = _base_task_file()
    original["ontology"] = {"catalog_version": "test-catalog"}

    repair = build_repair_task_file(
        original_task_file=original,
        failed_unit_ids=["line::1"],
        previous_answers_by_unit_id={
            "line::1": {
                "label": "NONRECIPE_CANDIDATE",
            }
        },
        validation_feedback_by_unit_id={
            "line::1": {"errors": ["label_not_allowed_here"]}
        },
    )

    assert repair["mode"] == "repair"
    assert "editable_json_pointers" not in repair
    assert [unit["unit_id"] for unit in repair["units"]] == ["line::1"]  # type: ignore[index]
    assert repair["units"][0]["previous_answer"] == {  # type: ignore[index]
        "label": "NONRECIPE_CANDIDATE",
    }
    assert repair["units"][0]["validation_feedback"] == {  # type: ignore[index]
        "errors": ["label_not_allowed_here"]
    }
    assert repair["helper_commands"] == {"status": "python3 -m stage --status"}
    assert repair["next_action"] == "fill answers then run helper"
    assert repair["answer_schema"] == {
        "editable_pointer_pattern": "/units/*/answer",
        "example_answers": [{"label": "RECIPE_NOTES"}]
    }
    assert repair["ontology"] == {"catalog_version": "test-catalog"}


def test_render_task_file_text_is_multiline_json() -> None:
    rendered = render_task_file_text(_base_task_file())

    assert rendered.endswith("\n")
    assert rendered.count("\n") > 1
    assert '  "' in rendered
    assert json.loads(rendered)["stage_key"] == "line_role"


def test_summarize_task_file_reports_answer_progress() -> None:
    task_file = _base_task_file()
    task_file["units"][0]["answer"] = {  # type: ignore[index]
        "label": "RECIPE_NOTES",
    }

    summary = summarize_task_file(payload=task_file, task_file_path="task.json")

    assert summary["stage_key"] == "line_role"
    assert summary["answered_units"] == 2
    assert summary["total_units"] == 2
    assert summary["unanswered_unit_count"] == 0
    assert summary["unanswered_unit_ids"] == []
    assert summary["unanswered_unit_ids_truncated"] is False
    assert summary["editable_pointer_count"] == 2
    assert summary["editable_pointer_pattern"] == "/units/*/answer"
    assert summary["editable_json_pointers_sample"] == []
    assert summary["editable_json_pointers_truncated"] is False


def test_build_worker_task_brief_keeps_progress_but_drops_pointer_noise() -> None:
    brief = build_worker_task_brief(payload=_base_task_file(), task_file_path="task.json")

    assert brief == {
        "task_file": "task.json",
        "stage_key": "line_role",
        "mode": "initial",
        "answered_units": 2,
        "total_units": 2,
        "remaining_units": 0,
        "next_action": "fill answers then run helper",
    }


def test_summarize_task_file_samples_large_unanswered_unit_lists() -> None:
    task_file = build_task_file(
        stage_key="line_role",
        assignment_id="worker-001",
        worker_id="worker-001",
        units=[
            {
                "unit_id": f"line::{index}",
                "owned_id": str(index),
                "evidence": {"atomic_index": index, "text": f"Line {index}"},
                "answer": {},
            }
            for index in range(SUMMARY_UNIT_ID_SAMPLE_LIMIT + 3)
        ],
    )

    summary = summarize_task_file(payload=task_file, task_file_path="task.json")

    assert summary["answered_units"] == 0
    assert summary["total_units"] == SUMMARY_UNIT_ID_SAMPLE_LIMIT + 3
    assert summary["unanswered_unit_count"] == SUMMARY_UNIT_ID_SAMPLE_LIMIT + 3
    assert summary["unanswered_unit_ids"] == [
        f"line::{index}" for index in range(SUMMARY_UNIT_ID_SAMPLE_LIMIT)
    ]
    assert summary["unanswered_unit_ids_truncated"] is True


def test_summarize_task_file_surfaces_grouping_batch_context() -> None:
    task_file = _base_task_file()
    task_file["grouping_batch"] = {
        "current_batch_index": 2,
        "total_batches": 3,
        "unit_count": 2,
        "total_grouping_unit_count": 5,
        "remaining_batches_after_this": 1,
        "estimated_evidence_chars": 321,
        "shard_ids": ["book.ks0000.nr", "book.ks0001.nr"],
    }

    summary = summarize_task_file(payload=task_file, task_file_path="task.json")

    assert summary["grouping_batch"] == {
        "current_batch_index": 2,
        "total_batches": 3,
        "unit_count": 2,
        "total_grouping_unit_count": 5,
        "remaining_batches_after_this": 1,
        "estimated_evidence_chars": 321,
        "shard_ids": ["book.ks0000.nr", "book.ks0001.nr"],
        "shard_ids_truncated": False,
    }


def test_inspect_task_file_units_returns_specific_requested_units() -> None:
    task_file = _base_task_file()

    result = inspect_task_file_units(
        payload=task_file,
        task_file_path="task.json",
        unit_ids=["line::1", "missing-unit", "line::0"],
    )

    assert result["returned_unit_ids"] == ["line::1", "line::0"]
    assert result["missing_unit_ids"] == ["missing-unit"]
    assert [unit["unit_id"] for unit in result["units"]] == ["line::1", "line::0"]
    assert result["matching_unit_count"] == 2


def test_inspect_task_file_units_can_filter_and_page_unanswered_rows() -> None:
    task_file = _base_task_file()
    task_file["units"][0]["answer"] = {  # type: ignore[index]
        "label": "RECIPE_NOTES",
    }
    task_file["units"][1]["answer"] = {}  # type: ignore[index]

    result = inspect_task_file_units(
        payload=task_file,
        task_file_path="task.json",
        answered=False,
        limit=1,
    )

    assert result["answered_filter"] is False
    assert result["matching_unit_count"] == 1
    assert result["returned_unit_ids"] == ["line::1"]
    assert result["units"][0]["evidence"]["text"] == "Discard me"


def test_apply_answers_to_task_file_updates_only_answer_objects(tmp_path: Path) -> None:
    task_file_path = tmp_path / "task.json"
    write_task_file(path=task_file_path, payload=_base_task_file())

    result = apply_answers_to_task_file(
        path=task_file_path,
        answers_by_unit_id={
            "line::0": {"label": "RECIPE_NOTES"},
            "missing-unit": {"label": "NONRECIPE_CANDIDATE"},
        },
    )

    updated_task_file = load_task_file(task_file_path)
    assert updated_task_file["units"][0]["answer"] == {"label": "RECIPE_NOTES"}  # type: ignore[index]
    assert updated_task_file["units"][0]["evidence"]["text"] == "Ambiguous line"  # type: ignore[index]
    assert result["applied_unit_ids"] == ["line::0"]
    assert result["skipped_unit_ids"] == ["missing-unit"]
    assert result["changed"] is True


def test_load_answer_mapping_file_prefers_nested_answers_by_unit_id(tmp_path: Path) -> None:
    mapping_path = tmp_path / "answers.json"
    mapping_path.write_text(
        json.dumps(
            {
                "answers_by_unit_id": {
                    "line::0": {"label": "RECIPE_NOTES"},
                }
            }
        ),
        encoding="utf-8",
    )

    result = _load_answer_mapping_file(mapping_path)

    assert result == {"line::0": {"label": "RECIPE_NOTES"}}
