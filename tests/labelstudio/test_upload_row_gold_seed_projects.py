from scripts.upload_row_gold_seed_projects_to_labelstudio import (
    _annotation_label_counts,
    _build_target_project_name,
    _verify_uploaded_project_annotations,
)


def _task(
    segment_id: str,
    labels: list[str],
) -> dict[str, object]:
    result = []
    for index, label in enumerate(labels):
        result.append(
            {
                "id": f"r{index}",
                "type": "labels",
                "from_name": "span_labels",
                "to_name": "segment_text",
                "value": {
                    "start": index,
                    "end": index + 1,
                    "text": label,
                    "labels": [label],
                },
            }
        )
    return {
        "data": {
            "segment_id": segment_id,
            "segment_text": "placeholder",
        },
        "annotations": [
            {
                "result": result,
            }
        ],
    }


def test_annotation_label_counts_collapses_result_rows() -> None:
    task = _task(
        "seg-1",
        ["RECIPE_TITLE", "INGREDIENT_LINE", "INGREDIENT_LINE", "OTHER"],
    )

    assert _annotation_label_counts(task) == {
        "INGREDIENT_LINE": 2,
        "OTHER": 1,
        "RECIPE_TITLE": 1,
    }


def test_verify_uploaded_project_annotations_reports_mismatched_labels() -> None:
    seed_tasks = [_task("seg-1", ["RECIPE_TITLE", "INGREDIENT_LINE", "OTHER"])]
    exported_tasks = [_task("seg-1", ["KNOWLEDGE", "OTHER", "OTHER"])]

    class FakeClient:
        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return exported_tasks

    mismatches = _verify_uploaded_project_annotations(
        client=FakeClient(),
        project_id=1,
        tasks=seed_tasks,
    )

    assert mismatches == [
        {
            "segment_id": "seg-1",
            "expected": {
                "INGREDIENT_LINE": 1,
                "OTHER": 1,
                "RECIPE_TITLE": 1,
            },
            "actual": {
                "KNOWLEDGE": 1,
                "OTHER": 2,
            },
            "reason": "annotation_label_mismatch",
        }
    ]


def test_verify_uploaded_project_annotations_accepts_matching_labels() -> None:
    seed_tasks = [_task("seg-1", ["RECIPE_TITLE", "INGREDIENT_LINE", "OTHER"])]

    class FakeClient:
        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return seed_tasks

    assert _verify_uploaded_project_annotations(
        client=FakeClient(),
        project_id=1,
        tasks=seed_tasks,
    ) == []


def test_build_target_project_name_does_not_double_suffix() -> None:
    assert (
        _build_target_project_name(
            "saltfatacidheatCUTDOWN source_rows_gold",
            "source_rows_gold",
        )
        == "saltfatacidheatCUTDOWN source_rows_gold"
    )
