import json

import pytest

from cookimport.labelstudio.export import (
    _infer_scope_from_project_payload,
    _select_annotation,
    run_labelstudio_export,
)


def test_select_annotation_latest() -> None:
    task = {
        "annotations": [
            {"id": 1, "result": [{"value": {"labels": ["INGREDIENT_LINE"]}}]},
            {"id": 2, "result": [{"value": {"labels": ["RECIPE_TITLE"]}}]},
        ]
    }
    selected = _select_annotation(task)
    assert selected is not None
    assert selected["id"] == 2


def test_infer_scope_from_project_payload_detects_known_scopes() -> None:
    assert (
        _infer_scope_from_project_payload(
            {"label_config": "<View><Label value='RECIPE_VARIANT'/></View>"}
        )
        == "freeform-spans"
    )
    assert (
        _infer_scope_from_project_payload(
            {"label_config": "<View><Choices name='mixed'><Choice value='x'/></Choices><Choices name='value_usefulness'/></View>"}
        )
        == "pipeline"
    )


@pytest.mark.parametrize("legacy_scope", ["pipeline", "canonical-blocks"])
def test_export_rejects_legacy_scope_from_manifest(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_scope: str,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 9, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return []

    run_root = tmp_path / "2026-02-25_22.45.00" / "labelstudio" / "book"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "project_name": "Legacy Project",
                "project_id": 9,
                "task_scope": legacy_scope,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    with pytest.raises(RuntimeError, match="supports freeform-spans projects only"):
        run_labelstudio_export(
            project_name="Legacy Project",
            output_dir=tmp_path,
            label_studio_url="http://localhost:8080",
            label_studio_api_key="token",
            run_dir=run_root,
        )


def test_labelstudio_export_writes_canonical_gold_artifacts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {
                "id": 7,
                "title": title,
                "label_config": "<View><Label value='RECIPE_VARIANT'/></View>",
            }

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 1,
                    "data": {
                        "segment_id": "seg-1",
                        "source_hash": "hash-123",
                        "source_file": "/tmp/book.epub",
                        "book_id": "book",
                        "segment_text": "Simple Soup\n1 cup stock",
                        "source_map": {
                            "blocks": [
                                {
                                    "block_id": "b-0",
                                    "block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 11,
                                },
                                {
                                    "block_id": "b-1",
                                    "block_index": 1,
                                    "segment_start": 12,
                                    "segment_end": 23,
                                },
                            ]
                        },
                    },
                    "annotations": [
                        {
                            "id": 10,
                            "result": [
                                {
                                    "id": "r-1",
                                    "to_name": "text",
                                    "value": {
                                        "labels": ["RECIPE_TITLE"],
                                        "start": 0,
                                        "end": 11,
                                        "text": "Simple Soup",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    result = run_labelstudio_export(
        project_name="Book",
        output_dir=tmp_path / "pulled-from-labelstudio",
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )

    export_root = result["export_root"]
    canonical_text_path = export_root / "canonical_text.txt"
    canonical_span_labels_path = export_root / "canonical_span_labels.jsonl"
    canonical_manifest_path = export_root / "canonical_manifest.json"
    canonical_errors_path = export_root / "canonical_span_label_errors.jsonl"

    assert canonical_text_path.exists()
    assert canonical_span_labels_path.exists()
    assert canonical_manifest_path.exists()
    assert canonical_errors_path.exists()

    assert canonical_text_path.read_text(encoding="utf-8") == "Simple Soup\n\n1 cup stock"

    canonical_rows = [
        json.loads(line)
        for line in canonical_span_labels_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert canonical_rows
    assert canonical_rows[0]["label"] == "RECIPE_TITLE"
    assert canonical_rows[0]["start_char"] == 0
    assert canonical_rows[0]["end_char"] == 11

    canonical_manifest = json.loads(canonical_manifest_path.read_text(encoding="utf-8"))
    assert canonical_manifest["schema_version"] == "canonical_gold.v1"
    assert canonical_manifest["canonical_span_error_count"] == 0
