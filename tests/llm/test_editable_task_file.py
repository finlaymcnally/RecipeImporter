from __future__ import annotations

from cookimport.llm.editable_task_file import build_repair_task_file
from cookimport.llm.editable_task_file import build_task_file
from cookimport.llm.editable_task_file import validate_edited_task_file


def _base_task_file() -> dict[str, object]:
    return build_task_file(
        stage_key="line_role",
        assignment_id="worker-001",
        worker_id="worker-001",
        units=[
            {
                "unit_id": "line::0",
                "owned_id": "0",
                "evidence": {"atomic_index": 0, "text": "Ambiguous line"},
                "answer": {"label": "NONRECIPE_CANDIDATE", "exclusion_reason": None},
            },
            {
                "unit_id": "line::1",
                "owned_id": "1",
                "evidence": {"atomic_index": 1, "text": "Discard me"},
                "answer": {"label": "NONRECIPE_CANDIDATE", "exclusion_reason": None},
            },
        ],
    )


def test_validate_edited_task_file_accepts_answer_only_edits() -> None:
    original = _base_task_file()
    edited = _base_task_file()
    edited["units"][0]["answer"] = {  # type: ignore[index]
        "label": "RECIPE_NOTES",
        "exclusion_reason": None,
    }

    answers_by_unit_id, errors, metadata = validate_edited_task_file(
        original_task_file=original,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["changed_unit_count"] == 1
    assert answers_by_unit_id == {
        "line::0": {"label": "RECIPE_NOTES", "exclusion_reason": None},
        "line::1": {"label": "NONRECIPE_CANDIDATE", "exclusion_reason": None},
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
        "exclusion_reason": None,
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
        "line::0": {"label": "RECIPE_NOTES", "exclusion_reason": None},
        "line::1": {"label": "NONRECIPE_CANDIDATE", "exclusion_reason": None},
    }


def test_build_repair_task_file_keeps_only_failed_units_with_feedback() -> None:
    original = _base_task_file()

    repair = build_repair_task_file(
        original_task_file=original,
        failed_unit_ids=["line::1"],
        previous_answers_by_unit_id={
            "line::1": {
                "label": "NONRECIPE_CANDIDATE",
                "exclusion_reason": None,
            }
        },
        validation_feedback_by_unit_id={
            "line::1": {"errors": ["label_not_allowed_here"]}
        },
    )

    assert repair["mode"] == "repair"
    assert repair["editable_json_pointers"] == ["/units/0/answer"]
    assert [unit["unit_id"] for unit in repair["units"]] == ["line::1"]  # type: ignore[index]
    assert repair["units"][0]["previous_answer"] == {  # type: ignore[index]
        "label": "NONRECIPE_CANDIDATE",
        "exclusion_reason": None,
    }
    assert repair["units"][0]["validation_feedback"] == {  # type: ignore[index]
        "errors": ["label_not_allowed_here"]
    }
