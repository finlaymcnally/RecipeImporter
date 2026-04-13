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


@pytest.mark.parametrize("unsupported_scope", ["pipeline", "canonical-blocks"])
def test_export_rejects_non_freeform_scope_from_manifest(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    unsupported_scope: str,
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
                "project_name": "Unsupported Scope Project",
                "project_id": 9,
                "task_scope": unsupported_scope,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    with pytest.raises(RuntimeError, match="supports freeform-spans projects only"):
        run_labelstudio_export(
            project_name="Unsupported Scope Project",
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
    block_gold_path = export_root / "block_gold_labels.jsonl"
    canonical_text_path = export_root / "canonical_text.txt"
    canonical_span_labels_path = export_root / "canonical_span_labels.jsonl"
    canonical_manifest_path = export_root / "canonical_manifest.json"
    canonical_errors_path = export_root / "canonical_span_label_errors.jsonl"

    assert block_gold_path.exists()
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
    block_gold_rows = [
        json.loads(line)
        for line in block_gold_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(block_gold_rows) == 1
    assert block_gold_rows[0]["block_index"] == 0
    assert block_gold_rows[0]["labels"] == ["RECIPE_TITLE"]
    assert block_gold_rows[0]["source_hash"] == "hash-123"
    assert block_gold_rows[0]["source_file"] == "/tmp/book.epub"
    assert block_gold_rows[0]["segment_ids"] == ["seg-1"]
    assert block_gold_rows[0]["book_ids"] == ["book"]
    assert canonical_rows
    assert canonical_rows[0]["label"] == "RECIPE_TITLE"
    assert canonical_rows[0]["start_char"] == 0
    assert canonical_rows[0]["end_char"] == 11

    canonical_manifest = json.loads(canonical_manifest_path.read_text(encoding="utf-8"))
    assert canonical_manifest["schema_version"] == "canonical_gold.v1"
    assert canonical_manifest["canonical_span_error_count"] == 0


def test_labelstudio_export_mass_labeling_is_block_authoritative(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run_export(annotation_result: list[dict[str, object]], export_slug: str) -> tuple[list[dict], list[dict]]:
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
                            "segment_text": "Alpha\nBeta",
                            "source_map": {
                                "blocks": [
                                    {
                                        "block_id": "b-0",
                                        "block_index": 0,
                                        "segment_start": 0,
                                        "segment_end": 5,
                                    },
                                    {
                                        "block_id": "b-1",
                                        "block_index": 1,
                                        "segment_start": 6,
                                        "segment_end": 10,
                                    },
                                ]
                            },
                        },
                        "annotations": [{"id": 10, "result": annotation_result}],
                    }
                ]

        monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

        result = run_labelstudio_export(
            project_name="Book",
            output_dir=tmp_path / export_slug,
            label_studio_url="http://localhost:8080",
            label_studio_api_key="token",
            run_dir=None,
        )
        export_root = result["export_root"]
        block_gold_rows = [
            json.loads(line)
            for line in (export_root / "block_gold_labels.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        canonical_rows = [
            json.loads(line)
            for line in (export_root / "canonical_span_labels.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        return block_gold_rows, canonical_rows

    sweep_block_gold_rows, sweep_canonical_rows = _run_export(
        [
            {
                "id": "r-1",
                "to_name": "text",
                "value": {
                    "labels": ["KNOWLEDGE"],
                    "start": 1,
                    "end": 8,
                    "text": "lpha\nBe",
                },
            }
        ],
        "mass-label",
    )
    per_block_gold_rows, per_block_canonical_rows = _run_export(
        [
            {
                "id": "r-1",
                "to_name": "text",
                "value": {
                    "labels": ["KNOWLEDGE"],
                    "start": 0,
                    "end": 5,
                    "text": "Alpha",
                },
            },
            {
                "id": "r-2",
                "to_name": "text",
                "value": {
                    "labels": ["KNOWLEDGE"],
                    "start": 6,
                    "end": 10,
                    "text": "Beta",
                },
            },
        ],
        "per-block",
    )

    assert sweep_block_gold_rows == per_block_gold_rows
    assert sweep_canonical_rows == per_block_canonical_rows
    assert [
        (row["block_index"], row["start_char"], row["end_char"], row["selected_text"])
        for row in sweep_canonical_rows
    ] == [
        (0, 0, 5, "Alpha"),
        (1, 7, 11, "Beta"),
    ]


def test_labelstudio_export_uses_source_slug_for_default_run_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 51, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 1,
                    "data": {
                        "segment_id": "seg-1",
                        "source_hash": "hash-1",
                        "source_file": "/tmp/My Book.epub",
                        "book_id": "book",
                        "segment_text": "Hello",
                        "source_map": {
                            "blocks": [
                                {
                                    "block_id": "b-0",
                                    "block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 5,
                                }
                            ]
                        },
                    },
                    "annotations": [],
                }
            ]

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    output_dir = tmp_path / "pulled-from-labelstudio"
    result = run_labelstudio_export(
        project_name="My Book-2",
        output_dir=output_dir,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )

    assert result["export_root"] == output_dir / "my_book" / "exports"
    assert not (output_dir / "my_book_2").exists()


def test_labelstudio_export_reuses_existing_run_root_for_same_source(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 77, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 1,
                    "data": {
                        "segment_id": "seg-1",
                        "source_hash": "hash-existing",
                        "source_file": "/tmp/My Book.epub",
                        "book_id": "book",
                        "segment_text": "Hello",
                        "source_map": {
                            "blocks": [
                                {
                                    "block_id": "b-0",
                                    "block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 5,
                                }
                            ]
                        },
                    },
                    "annotations": [],
                }
            ]

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    output_dir = tmp_path / "pulled-from-labelstudio"
    existing_run_root = output_dir / "my_book"
    (existing_run_root / "exports").mkdir(parents=True, exist_ok=True)
    (existing_run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "source": {
                    "path": "/tmp/My Book.epub",
                    "source_hash": "hash-existing",
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = run_labelstudio_export(
        project_name="My Book-2",
        output_dir=output_dir,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )

    assert result["export_root"] == existing_run_root / "exports"
    assert not (output_dir / "my_book_2").exists()

    run_manifest = json.loads(
        (existing_run_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert run_manifest["artifacts"]["label_studio_project_name"] == "My Book-2"
