import json

import pytest

from cookimport.labelstudio.eval_freeform import (
    LabeledRange,
    attach_recipe_count_diagnostics,
    evaluate_predicted_vs_freeform,
    format_freeform_eval_report_md,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
)
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    map_span_offsets_to_rows,
    resolve_segment_overlap_for_target,
)
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_LABELS,
    build_freeform_label_config,
    normalize_freeform_label,
)


def test_build_freeform_tasks_offsets_are_deterministic() -> None:
    archive = [
        {"index": 0, "text": "Alpha", "location": {"block_index": 0}},
        {"index": 1, "text": "Beta", "location": {"block_index": 1}},
        {"index": 2, "text": "Gamma", "location": {"block_index": 2}},
    ]
    tasks_a = build_freeform_span_tasks(
        archive=archive,
        source_hash="hash123",
        source_file="book.epub",
        book_id="book",
        segment_blocks=2,
        segment_overlap=1,
    )
    tasks_b = build_freeform_span_tasks(
        archive=archive,
        source_hash="hash123",
        source_file="book.epub",
        book_id="book",
        segment_blocks=2,
        segment_overlap=1,
    )
    assert tasks_a == tasks_b
    assert [task["data"]["segment_id"] for task in tasks_a] == [
        "urn:cookimport:segment:hash123:0:1",
        "urn:cookimport:segment:hash123:1:2",
    ]

    first = tasks_a[0]["data"]
    assert first["segment_text"] == "Alpha\n\nBeta"
    source_rows = first["source_map"]["rows"]
    assert source_rows[0]["segment_start"] == 0
    assert source_rows[0]["segment_end"] == 5
    assert source_rows[1]["segment_start"] == 7
    assert source_rows[1]["segment_end"] == 11

    touched = map_span_offsets_to_rows(first["source_map"], 0, 4)
    assert [item["block_index"] for item in touched] == [0]


def test_resolve_segment_overlap_for_target_prefers_closest_task_count() -> None:
    # total_blocks=9 with segment_blocks=4 yields 3 tasks at overlap=1 and 4 tasks at overlap=2.
    assert (
        resolve_segment_overlap_for_target(
            total_blocks=9,
            segment_blocks=4,
            requested_overlap=1,
            target_task_count=4,
        )
        == 2
    )
    assert (
        resolve_segment_overlap_for_target(
            total_blocks=9,
            segment_blocks=4,
            requested_overlap=1,
            target_task_count=None,
        )
        == 1
    )


def test_resolve_segment_overlap_for_target_respects_focus_overlap_floor() -> None:
    assert (
        resolve_segment_overlap_for_target(
            total_blocks=1471,
            segment_blocks=45,
            requested_overlap=5,
            target_task_count=None,
            segment_focus_blocks=30,
        )
        == 15
    )


def test_build_freeform_tasks_include_focus_metadata() -> None:
    archive = [
        {"index": 0, "text": "A", "location": {"block_index": 0}},
        {"index": 1, "text": "B", "location": {"block_index": 1}},
        {"index": 2, "text": "C", "location": {"block_index": 2}},
        {"index": 3, "text": "D", "location": {"block_index": 3}},
        {"index": 4, "text": "E", "location": {"block_index": 4}},
        {"index": 5, "text": "F", "location": {"block_index": 5}},
    ]
    tasks = build_freeform_span_tasks(
        archive=archive,
        source_hash="hash123",
        source_file="book.epub",
        book_id="book",
        segment_blocks=4,
        segment_overlap=1,
        segment_focus_blocks=2,
    )

    first_source_map = tasks[0]["data"]["source_map"]
    second_source_map = tasks[1]["data"]["source_map"]
    assert tasks[0]["data"]["segment_text"] == "B\n\nC"
    assert tasks[1]["data"]["segment_text"] == "E\n\nF"
    assert first_source_map["focus_start_row_index"] == 1
    assert first_source_map["focus_end_row_index"] == 2
    assert first_source_map["focus_row_indices"] == [1, 2]
    assert first_source_map["context_before_row_indices"] == [0]
    assert first_source_map["context_after_row_indices"] == [3]
    assert first_source_map["focus_row_range"] == "1-2"
    assert first_source_map["context_before_row_range"] == "0"
    assert first_source_map["context_after_row_range"] == "3"
    assert first_source_map["rows"][0]["row_index"] == 1
    assert first_source_map["rows"][0]["segment_start"] == 0
    assert first_source_map["rows"][0]["segment_end"] == 1
    assert first_source_map["rows"][1]["row_index"] == 2
    assert first_source_map["rows"][1]["segment_start"] == 3
    assert first_source_map["rows"][1]["segment_end"] == 4
    assert len(first_source_map["context_before_rows"]) == 1
    assert first_source_map["context_before_rows"][0]["row_index"] == 0
    assert first_source_map["context_before_rows"][0]["text"] == "A"
    assert len(first_source_map["context_after_rows"]) == 1
    assert first_source_map["context_after_rows"][0]["row_index"] == 3
    assert first_source_map["context_after_rows"][0]["text"] == "D"
    assert tasks[0]["data"]["focus_scope_hint"] == (
        "Label only rows 1-2. Context only: before 0; after 3."
    )

    assert second_source_map["focus_start_row_index"] == 4
    assert second_source_map["focus_end_row_index"] == 5
    assert second_source_map["focus_row_indices"] == [4, 5]
    assert second_source_map["context_before_row_indices"] == [3]
    assert second_source_map["context_after_row_indices"] == []
    assert second_source_map["focus_row_range"] == "4-5"
    assert second_source_map["context_before_row_range"] == "3"
    assert second_source_map["context_after_row_range"] == "none"
    assert len(second_source_map["context_before_rows"]) == 1
    assert second_source_map["context_before_rows"][0]["row_index"] == 3
    assert second_source_map["context_before_rows"][0]["text"] == "D"
    assert second_source_map["context_after_rows"] == []
    assert tasks[1]["data"]["focus_scope_hint"] == (
        "Label only rows 4-5. Context only: before 3; after none."
    )


def test_freeform_label_config_uses_expected_label_order_and_names() -> None:
    assert FREEFORM_LABELS == (
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "HOWTO_SECTION",
        "YIELD_LINE",
        "TIME_LINE",
        "RECIPE_NOTES",
        "RECIPE_VARIANT",
        "KNOWLEDGE",
        "OTHER",
    )
    config = build_freeform_label_config()
    assert '<Label value="RECIPE_NOTES"/>' in config
    assert '<Label value="RECIPE_VARIANT"/>' in config
    assert '<Label value="KNOWLEDGE"/>' in config
    assert '<Label value="YIELD_LINE"/>' in config
    assert '<Label value="TIME_LINE"/>' in config
    assert '<Label value="HOWTO_SECTION"/>' in config
    assert '<Label value="OTHER"/>' in config
    assert '<Label value="NARRATIVE"/>' not in config
    assert '<Label value="TIP"/>' not in config
    assert '<Label value="NOTES"/>' not in config
    assert '<Label value="VARIANT"/>' not in config
    assert '<Label value="NOTE"/>' not in config
    assert "$focus_scope_hint" in config
    assert (
        "Focus rows: $focus_row_range | Context before: $context_before_row_range | "
        "Context after: $context_after_row_range"
    ) in config


def test_normalize_freeform_label_keeps_only_canonical_spelling_variants() -> None:
    assert normalize_freeform_label("HowToSection") == "HOWTO_SECTION"
    assert normalize_freeform_label("HOWTO_SECTION") == "HOWTO_SECTION"
    assert normalize_freeform_label("recipe title") == "RECIPE_TITLE"
    assert normalize_freeform_label("recipe-notes") == "RECIPE_NOTES"
    assert normalize_freeform_label("TIP") == "TIP"
    assert normalize_freeform_label("NOTES") == "NOTES"
    assert normalize_freeform_label("NOTE") == "NOTE"
    assert normalize_freeform_label("VARIANT") == "VARIANT"
    assert normalize_freeform_label("NARRATIVE") == "NARRATIVE"
    assert normalize_freeform_label("YIELD") == "YIELD"
    assert normalize_freeform_label("TIME") == "TIME"


def test_eval_freeform_maps_howto_section_to_neighboring_structural_label(tmp_path) -> None:
    gold_path = tmp_path / "gold.jsonl"
    gold_rows = [
        {
            "span_id": "g1",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "INGREDIENT_LINE",
            "touched_row_indices": [1],
        },
        {
            "span_id": "g2",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "HowToSection",
            "touched_row_indices": [2],
        },
        {
            "span_id": "g3",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "INGREDIENT_LINE",
            "touched_row_indices": [3],
        },
        {
            "span_id": "g4",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "INSTRUCTION_LINE",
            "touched_row_indices": [5],
        },
        {
            "span_id": "g5",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "HOWTO_SECTION",
            "touched_row_indices": [6],
        },
        {
            "span_id": "g6",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "INSTRUCTION_LINE",
            "touched_row_indices": [7],
        },
    ]
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n",
        encoding="utf-8",
    )
    gold = load_gold_freeform_ranges(gold_path)

    predicted = [
        LabeledRange("p1", "h1", "book.epub", "INGREDIENT_LINE", 1, 1),
        LabeledRange("p2", "h1", "book.epub", "INGREDIENT_LINE", 2, 2),
        LabeledRange("p3", "h1", "book.epub", "INGREDIENT_LINE", 3, 3),
        LabeledRange("p4", "h1", "book.epub", "INSTRUCTION_LINE", 5, 5),
        LabeledRange("p5", "h1", "book.epub", "INSTRUCTION_LINE", 6, 6),
        LabeledRange("p6", "h1", "book.epub", "INSTRUCTION_LINE", 7, 7),
    ]

    result = evaluate_predicted_vs_freeform(predicted, gold, overlap_threshold=0.5)
    report = result["report"]

    assert report["counts"]["gold_total"] == 6
    assert report["counts"]["gold_matched"] == 6
    assert report["counts"]["pred_false_positive"] == 0
    assert report["per_label"]["INGREDIENT_LINE"]["gold_total"] == 3
    assert report["per_label"]["INSTRUCTION_LINE"]["gold_total"] == 3
    assert "HOWTO_SECTION" not in report["per_label"]


def test_eval_freeform_accepts_row_native_range_keys(tmp_path) -> None:
    gold_path = tmp_path / "gold.jsonl"
    gold_rows = [
        {
            "span_id": "g1",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "INGREDIENT_LINE",
            "touched_row_indices": [4],
        },
        {
            "span_id": "g2",
            "source_hash": "h1",
            "source_file": "book.epub",
            "label": "INSTRUCTION_LINE",
            "touched_rows": [{"row_index": 7}],
        },
    ]
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n",
        encoding="utf-8",
    )
    gold = load_gold_freeform_ranges(gold_path)
    assert [(span.label, span.start_row_index, span.end_row_index) for span in gold] == [
        ("INGREDIENT_LINE", 4, 4),
        ("INSTRUCTION_LINE", 7, 7),
    ]

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "label_studio_tasks.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "data": {
                            "chunk_id": "urn:recipeimport:chunk:text:h1:atomic:loc:block_index=8:a",
                            "source_hash": "h1",
                            "source_file": "book.epub",
                            "chunk_level": "atomic",
                            "chunk_type": "ingredient_line",
                            "location": {"start_row": 8, "end_row": 9},
                        }
                    }
                ),
                json.dumps(
                    {
                        "data": {
                            "chunk_id": "urn:recipeimport:chunk:text:h1:atomic:loc:block_index=11:b",
                            "source_hash": "h1",
                            "source_file": "book.epub",
                            "chunk_level": "atomic",
                            "chunk_type": "step_line",
                            "location": {"row_index": 11},
                        }
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    predicted = load_predicted_labeled_ranges(run_dir)
    assert [(span.label, span.start_row_index, span.end_row_index) for span in predicted] == [
        ("INGREDIENT_LINE", 8, 9),
        ("INSTRUCTION_LINE", 11, 11),
    ]


def test_export_freeform_spans_jsonl(tmp_path, monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 9, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 11,
                    "data": {
                        "segment_id": "urn:cookimport:segment:hash123:0:1",
                        "source_hash": "hash123",
                        "source_file": "book.epub",
                        "book_id": "book",
                        "segment_index": 0,
                        "segment_text": "Alpha\n\nBeta",
                        "source_map": {
                            "separator": "\n\n",
                            "start_row_index": 0,
                            "end_row_index": 1,
                            "rows": [
                                {
                                    "row_id": "urn:cookimport:row:hash123:0:0",
                                    "row_index": 0,
                                    "source_block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 5,
                                    "text": "Alpha",
                                },
                                {
                                    "row_id": "urn:cookimport:row:hash123:1:0",
                                    "row_index": 1,
                                    "source_block_index": 1,
                                    "segment_start": 7,
                                    "segment_end": 11,
                                    "text": "Beta",
                                },
                            ],
                        },
                    },
                    "annotations": [
                        {
                            "id": 2,
                            "completed_by": "annotator@example.com",
                            "completed_at": "2026-02-10T00:00:00Z",
                            "result": [
                                {
                                    "id": "r1",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 0,
                                        "end": 5,
                                        "text": "Alpha",
                                        "labels": ["INGREDIENT_LINE"],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    result = run_labelstudio_export(
        project_name="Freeform Test",
        output_dir=tmp_path,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )
    summary = result["summary"]
    assert summary["counts"]["labeled"] == 1
    assert summary["counts"]["missing"] == 0
    assert summary["counts"]["recipe_headers"] == 0
    assert summary["recipe_counts"]["recipe_headers"] == 0

    spans_path = result["export_root"] / "freeform_span_labels.jsonl"
    rows = [
        json.loads(line)
        for line in spans_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["label"] == "INGREDIENT_LINE"
    assert rows[0]["start_offset"] == 0
    assert rows[0]["end_offset"] == 5
    assert rows[0]["touched_row_indices"] == [0]

    segment_manifest = result["export_root"] / "freeform_segment_manifest.jsonl"
    manifest_rows = [
        json.loads(line)
        for line in segment_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["segment_id"] == "urn:cookimport:segment:hash123:0:1"


def _run_freeform_yield_time_export_fixture(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 10, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 20,
                    "data": {
                        "segment_id": "urn:cookimport:segment:hash456:0:2",
                        "source_hash": "hash456",
                        "source_file": "book2.epub",
                        "book_id": "book2",
                        "segment_index": 0,
                        "segment_text": "Serves 4\n\nPrep: 10 min\n\n1 cup flour",
                        "source_map": {
                            "separator": "\n\n",
                            "start_row_index": 0,
                            "end_row_index": 2,
                            "rows": [
                                {
                                    "row_id": "urn:cookimport:row:hash456:0:0",
                                    "row_index": 0,
                                    "source_block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 8,
                                    "text": "Serves 4",
                                },
                                {
                                    "row_id": "urn:cookimport:row:hash456:1:0",
                                    "row_index": 1,
                                    "source_block_index": 1,
                                    "segment_start": 10,
                                    "segment_end": 22,
                                    "text": "Prep: 10 min",
                                },
                                {
                                    "row_id": "urn:cookimport:row:hash456:2:0",
                                    "row_index": 2,
                                    "source_block_index": 2,
                                    "segment_start": 24,
                                    "segment_end": 35,
                                    "text": "1 cup flour",
                                },
                            ],
                        },
                    },
                    "annotations": [
                        {
                            "id": 5,
                            "completed_by": "annotator@example.com",
                            "completed_at": "2026-02-12T00:00:00Z",
                            "result": [
                                {
                                    "id": "r1",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 0,
                                        "end": 8,
                                        "text": "Serves 4",
                                        "labels": ["YIELD_LINE"],
                                    },
                                },
                                {
                                    "id": "r2",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 10,
                                        "end": 22,
                                        "text": "Prep: 10 min",
                                        "labels": ["TIME_LINE"],
                                    },
                                },
                                {
                                    "id": "r3",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 24,
                                        "end": 35,
                                        "text": "1 cup flour",
                                        "labels": ["INGREDIENT_LINE"],
                                    },
                                },
                            ],
                        }
                    ],
                }
            ]

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    result = run_labelstudio_export(
        project_name="Freeform Yield Time Test",
        output_dir=tmp_path,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )
    summary = result["summary"]
    assert summary["counts"]["labeled"] == 3
    assert summary["counts"]["recipe_headers"] == 0

    spans_path = result["export_root"] / "freeform_span_labels.jsonl"
    rows = [
        json.loads(line)
        for line in spans_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "summary": summary,
        "rows": rows,
    }


def test_export_freeform_spans_includes_yield_and_time_labels(
    tmp_path, monkeypatch
) -> None:
    fixture = _run_freeform_yield_time_export_fixture(tmp_path, monkeypatch)
    summary = fixture["summary"]
    rows = fixture["rows"]

    assert summary["counts"]["labeled"] == 3
    assert summary["counts"]["recipe_headers"] == 0
    labels_found = {row["label"] for row in rows}
    assert "YIELD_LINE" in labels_found
    assert "TIME_LINE" in labels_found
    assert "INGREDIENT_LINE" in labels_found


def test_export_freeform_spans_maps_yield_and_time_blocks(
    tmp_path, monkeypatch
) -> None:
    fixture = _run_freeform_yield_time_export_fixture(tmp_path, monkeypatch)
    rows = fixture["rows"]

    yield_row = next(r for r in rows if r["label"] == "YIELD_LINE")
    assert yield_row["selected_text"] == "Serves 4"
    assert yield_row["touched_row_indices"] == [0]

    time_row = next(r for r in rows if r["label"] == "TIME_LINE")
    assert time_row["selected_text"] == "Prep: 10 min"
    assert time_row["touched_row_indices"] == [1]


def _run_freeform_recipe_header_summary_fixture(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 42, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [
                {
                    "id": 1,
                    "data": {
                        "segment_id": "urn:cookimport:segment:hash789:0:1",
                        "source_hash": "hash789",
                        "source_file": "book3.epub",
                        "book_id": "book3",
                        "segment_index": 0,
                        "segment_text": "Recipe A\n\n1 cup sugar",
                        "source_map": {
                            "separator": "\n\n",
                            "start_row_index": 0,
                            "end_row_index": 1,
                            "rows": [
                                {
                                    "row_id": "urn:cookimport:row:hash789:0:0",
                                    "row_index": 0,
                                    "source_block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 8,
                                    "text": "Recipe A",
                                },
                                {
                                    "row_id": "urn:cookimport:row:hash789:1:0",
                                    "row_index": 1,
                                    "source_block_index": 1,
                                    "segment_start": 10,
                                    "segment_end": 21,
                                    "text": "1 cup sugar",
                                },
                            ],
                        },
                    },
                    "annotations": [
                        {
                            "id": 1,
                            "result": [
                                {
                                    "id": "r1",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 0,
                                        "end": 8,
                                        "text": "Recipe A",
                                        "labels": ["RECIPE_TITLE"],
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": 2,
                    "data": {
                        "segment_id": "urn:cookimport:segment:hash789:0:2",
                        "source_hash": "hash789",
                        "source_file": "book3.epub",
                        "book_id": "book3",
                        "segment_index": 1,
                        "segment_text": "Recipe A\n\nStep 1",
                        "source_map": {
                            "separator": "\n\n",
                            "start_row_index": 0,
                            "end_row_index": 2,
                            "rows": [
                                {
                                    "row_id": "urn:cookimport:row:hash789:0:0",
                                    "row_index": 0,
                                    "source_block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 8,
                                    "text": "Recipe A",
                                },
                                {
                                    "row_id": "urn:cookimport:row:hash789:2:0",
                                    "row_index": 2,
                                    "source_block_index": 2,
                                    "segment_start": 10,
                                    "segment_end": 16,
                                    "text": "Step 1",
                                },
                            ],
                        },
                    },
                    "annotations": [
                        {
                            "id": 2,
                            "result": [
                                {
                                    "id": "r2",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 0,
                                        "end": 8,
                                        "text": "Recipe A",
                                        "labels": ["RECIPE_TITLE"],
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": 3,
                    "data": {
                        "segment_id": "urn:cookimport:segment:hash789:5:6",
                        "source_hash": "hash789",
                        "source_file": "book3.epub",
                        "book_id": "book3",
                        "segment_index": 2,
                        "segment_text": "Recipe B\n\n2 eggs",
                        "source_map": {
                            "separator": "\n\n",
                            "start_row_index": 5,
                            "end_row_index": 6,
                            "rows": [
                                {
                                    "row_id": "urn:cookimport:row:hash789:5:0",
                                    "row_index": 5,
                                    "source_block_index": 5,
                                    "segment_start": 0,
                                    "segment_end": 8,
                                    "text": "Recipe B",
                                },
                                {
                                    "row_id": "urn:cookimport:row:hash789:6:0",
                                    "row_index": 6,
                                    "source_block_index": 6,
                                    "segment_start": 10,
                                    "segment_end": 16,
                                    "text": "2 eggs",
                                },
                            ],
                        },
                    },
                    "annotations": [
                        {
                            "id": 3,
                            "result": [
                                {
                                    "id": "r3",
                                    "from_name": "span_labels",
                                    "to_name": "segment_text",
                                    "type": "labels",
                                    "value": {
                                        "start": 0,
                                        "end": 8,
                                        "text": "Recipe B",
                                        "labels": ["RECIPE_TITLE"],
                                    },
                                }
                            ],
                        }
                    ],
                },
            ]

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    result = run_labelstudio_export(
        project_name="Freeform Recipe Header Count",
        output_dir=tmp_path,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )
    return result["summary"]


def test_export_freeform_summary_counts_recipe_headers_deduped(tmp_path, monkeypatch) -> None:
    summary = _run_freeform_recipe_header_summary_fixture(tmp_path, monkeypatch)
    assert summary["counts"]["labeled"] == 3
    assert summary["counts"]["recipe_headers"] == 2


def test_export_freeform_summary_tracks_raw_and_deduped_recipe_header_counts(
    tmp_path, monkeypatch
) -> None:
    summary = _run_freeform_recipe_header_summary_fixture(tmp_path, monkeypatch)
    assert summary["recipe_counts"]["recipe_headers"] == 2
    assert summary["recipe_counts"]["recipe_headers_raw"] == 3


def test_export_uses_project_slug_run_root_when_manifest_exists(tmp_path, monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 123, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return []

    prior_run_root = (
        tmp_path / "2026-02-10_23.04.31" / "labelstudio" / "old_project_root"
    )
    prior_run_root.mkdir(parents=True, exist_ok=True)
    prior_manifest_path = prior_run_root / "manifest.json"
    prior_manifest_path.write_text(
        json.dumps(
            {
                "project_name": "Freeform Project",
                "project_id": 123,
                "task_scope": "freeform-spans",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    result = run_labelstudio_export(
        project_name="Freeform Project",
        output_dir=tmp_path,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        run_dir=None,
    )

    export_root = result["export_root"]
    assert export_root == tmp_path / "freeform_project" / "exports"
    assert export_root.parent != prior_run_root
    assert result["summary"]["manifest_path"] == str(prior_manifest_path)
    assert (export_root / "summary.json").exists()
    assert (export_root / "labelstudio_export.json").exists()


def test_eval_freeform_ranges_smoke(tmp_path) -> None:
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    pred_tasks_path = pred_run / "label_studio_tasks.jsonl"
    pred_tasks = [
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:atomic:loc:block_index=1:abc",
                "chunk_level": "atomic",
                "chunk_type": "ingredient_line",
                "chunk_type_hint": "ingredient",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"block_index": 1},
            }
        },
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:atomic:loc:block_index=2:def",
                "chunk_level": "atomic",
                "chunk_type": "step_line",
                "chunk_type_hint": "step",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"block_index": 2},
            }
        },
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:atomic:loc:block_index=4:ghi",
                "chunk_level": "atomic",
                "chunk_type": "note",
                "chunk_type_hint": "note",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"block_index": 4},
            }
        },
    ]
    pred_tasks_path.write_text(
        "\n".join(json.dumps(row) for row in pred_tasks) + "\n", encoding="utf-8"
    )

    gold_path = tmp_path / "gold.jsonl"
    gold_rows = [
        {
            "span_id": "gold-1",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "INGREDIENT_LINE",
            "touched_row_indices": [1],
        },
        {
            "span_id": "gold-2",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "INSTRUCTION_LINE",
            "touched_row_indices": [2],
        },
        {
            "span_id": "gold-3",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "RECIPE_NOTES",
            "touched_row_indices": [5],
        },
    ]
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n", encoding="utf-8"
    )

    predicted = load_predicted_labeled_ranges(pred_run)
    gold = load_gold_freeform_ranges(gold_path)
    result = evaluate_predicted_vs_freeform(predicted, gold, overlap_threshold=0.5)
    report = result["report"]

    assert report["counts"]["gold_total"] == 3
    assert report["counts"]["pred_total"] == 3
    assert report["counts"]["gold_matched"] == 2
    assert report["counts"]["pred_matched"] == 2
    assert report["counts"]["gold_missed"] == 1
    assert report["counts"]["pred_false_positive"] == 1
    assert "app_aligned" in report
    assert "classification_only" in report


def test_attach_recipe_count_diagnostics_enriches_report() -> None:
    report = {
        "per_label": {
            "RECIPE_TITLE": {
                "gold_total": 4,
                "pred_total": 3,
            }
        }
    }
    attach_recipe_count_diagnostics(
        report,
        gold_recipe_headers=5,
        gold_recipe_headers_source="gold_summary.recipe_counts.recipe_headers",
        predicted_recipe_count=6,
        predicted_recipe_count_source="prediction_manifest.recipe_count",
    )

    recipe_counts = report["recipe_counts"]
    assert recipe_counts["gold_recipe_headers"] == 5
    assert recipe_counts["pred_recipe_headers"] == 3
    assert recipe_counts["predicted_recipe_count"] == 6
    assert recipe_counts["predicted_minus_gold"] == 1
    assert recipe_counts["predicted_to_gold_ratio"] == 1.2
    assert (
        recipe_counts["gold_recipe_headers_source"]
        == "gold_summary.recipe_counts.recipe_headers"
    )
    assert (
        recipe_counts["predicted_recipe_count_source"]
        == "prediction_manifest.recipe_count"
    )


def test_eval_freeform_dedupes_duplicate_gold_ranges_by_default(tmp_path) -> None:
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text(
        json.dumps(
            {
                "data": {
                    "chunk_id": "urn:recipeimport:chunk:text:h1:atomic:loc:block_index=3:a",
                    "chunk_level": "atomic",
                    "chunk_type": "ingredient_line",
                    "chunk_type_hint": "ingredient",
                    "source_hash": "h1",
                    "source_file": "book.epub",
                    "location": {"block_index": 3},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "span_id": "gold-1",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "INGREDIENT_LINE",
                        "touched_row_indices": [3],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-2",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "INGREDIENT_LINE",
                        "touched_row_indices": [3],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_predicted_vs_freeform(
        load_predicted_labeled_ranges(pred_run),
        load_gold_freeform_ranges(gold_path),
        overlap_threshold=0.5,
    )
    report = result["report"]
    dedupe = report["gold_dedupe"]

    assert report["counts"]["gold_total"] == 1
    assert report["counts"]["gold_matched"] == 1
    assert report["counts"]["pred_matched"] == 1
    assert dedupe["rows_removed"] == 1
    assert dedupe["duplicate_groups"] == 1
    assert dedupe["conflict_groups"] == 0
    assert dedupe["conflicts"] == []


def test_eval_freeform_gold_dedupe_conflict_majority_vote(tmp_path) -> None:
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text(
        json.dumps(
            {
                "data": {
                    "chunk_id": "urn:recipeimport:chunk:text:h2:atomic:loc:block_index=4:a",
                    "chunk_level": "atomic",
                    "chunk_type": "ingredient_line",
                    "chunk_type_hint": "ingredient",
                    "source_hash": "h2",
                    "source_file": "book.epub",
                    "location": {"block_index": 4},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "span_id": "gold-a",
                        "source_hash": "h2",
                        "source_file": "book.epub",
                        "label": "INGREDIENT_LINE",
                        "touched_row_indices": [4],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-b",
                        "source_hash": "h2",
                        "source_file": "book.epub",
                        "label": "OTHER",
                        "touched_row_indices": [4],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-c",
                        "source_hash": "h2",
                        "source_file": "book.epub",
                        "label": "INGREDIENT_LINE",
                        "touched_row_indices": [4],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_predicted_vs_freeform(
        load_predicted_labeled_ranges(pred_run),
        load_gold_freeform_ranges(gold_path),
        overlap_threshold=0.5,
    )
    report = result["report"]
    dedupe = report["gold_dedupe"]

    assert report["counts"]["gold_total"] == 1
    assert report["counts"]["gold_matched"] == 1
    assert dedupe["conflict_groups"] == 1
    assert dedupe["conflict_groups_resolved_majority"] == 1
    assert dedupe["conflict_groups_dropped_tie"] == 0
    assert dedupe["conflicts"][0]["resolution"] == "majority_vote"
    assert dedupe["conflicts"][0]["selected_label"] == "INGREDIENT_LINE"


def test_eval_freeform_gold_dedupe_conflict_tie_is_dropped(tmp_path) -> None:
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text(
        json.dumps(
            {
                "data": {
                    "chunk_id": "urn:recipeimport:chunk:text:h3:atomic:loc:block_index=5:a",
                    "chunk_level": "atomic",
                    "chunk_type": "ingredient_line",
                    "chunk_type_hint": "ingredient",
                    "source_hash": "h3",
                    "source_file": "book.epub",
                    "location": {"block_index": 5},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "span_id": "gold-a",
                        "source_hash": "h3",
                        "source_file": "book.epub",
                        "label": "INGREDIENT_LINE",
                        "touched_row_indices": [5],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-b",
                        "source_hash": "h3",
                        "source_file": "book.epub",
                        "label": "OTHER",
                        "touched_row_indices": [5],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_predicted_vs_freeform(
        load_predicted_labeled_ranges(pred_run),
        load_gold_freeform_ranges(gold_path),
        overlap_threshold=0.5,
    )
    report = result["report"]
    dedupe = report["gold_dedupe"]

    assert report["counts"]["gold_total"] == 0
    assert report["counts"]["gold_matched"] == 0
    assert report["counts"]["pred_false_positive"] == 1
    assert dedupe["conflict_groups"] == 1
    assert dedupe["conflict_groups_resolved_majority"] == 0
    assert dedupe["conflict_groups_dropped_tie"] == 1
    assert dedupe["conflict_rows_dropped_tie"] == 2
    assert dedupe["conflicts"][0]["resolution"] == "dropped_tie"
    assert dedupe["conflicts"][0]["selected_label"] is None


def _run_app_aligned_freeform_fixture(tmp_path) -> dict[str, object]:
    predicted = [
        # Duplicate ingredient span (same range/label) should dedupe in app-aligned metrics.
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:atomic:loc:block_index=10:a",
                "chunk_level": "atomic",
                "chunk_type": "ingredient_line",
                "chunk_type_hint": "ingredient",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"start_block": 10, "end_block": 13},
            }
        },
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:atomic:loc:block_index=10:b",
                "chunk_level": "atomic",
                "chunk_type": "ingredient_line",
                "chunk_type_hint": "ingredient",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"start_block": 10, "end_block": 13},
            }
        },
        # Broader title span overlaps gold title but fails strict IoU >= 0.5.
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:structural:loc:block_index=20:c",
                "chunk_level": "structural",
                "chunk_type": "recipe_block",
                "chunk_type_hint": "recipe",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"start_block": 20, "end_block": 25},
            }
        },
        # Overlaps KNOWLEDGE span but with wrong label (OTHER), so classification-only can surface mismatch.
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:atomic:loc:block_index=30:d",
                "chunk_level": "atomic",
                "chunk_type": "recipe_description",
                "chunk_type_hint": "paragraph",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"start_block": 30, "end_block": 31},
            }
        },
    ]
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text(
        "\n".join(json.dumps(row) for row in predicted) + "\n",
        encoding="utf-8",
    )

    gold_rows = [
        {
            "span_id": "gold-ing",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "INGREDIENT_LINE",
            "touched_row_indices": [11, 12],
        },
        {
            "span_id": "gold-title",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "RECIPE_TITLE",
            "touched_row_indices": [22],
        },
        {
            "span_id": "gold-tip",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "KNOWLEDGE",
            "touched_row_indices": [30],
        },
    ]
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n",
        encoding="utf-8",
    )

    result = evaluate_predicted_vs_freeform(
        load_predicted_labeled_ranges(pred_run),
        load_gold_freeform_ranges(gold_path),
        overlap_threshold=0.5,
    )
    report = result["report"]
    return {
        "report": report,
        "report_md": format_freeform_eval_report_md(report),
    }


def test_eval_freeform_app_aligned_summary(tmp_path) -> None:
    fixture = _run_app_aligned_freeform_fixture(tmp_path)
    report = fixture["report"]
    app = report["app_aligned"]

    deduped = app["deduped_predictions"]
    assert deduped["counts"]["pred_total"] == 3
    assert deduped["counts"]["gold_total"] == 3

    supported_strict = app["supported_labels_strict"]
    assert supported_strict["counts"]["gold_total"] == 2
    assert supported_strict["counts"]["gold_matched"] == 1

    supported_relaxed = app["supported_labels_relaxed"]
    assert supported_relaxed["counts"]["gold_matched"] == 2
    assert supported_relaxed["overlap_threshold"] == 0.1

    any_overlap = app["any_overlap_coverage"]
    assert any_overlap["RECIPE_TITLE"]["gold_with_any_overlap"] == 1
    assert any_overlap["INGREDIENT_LINE"]["gold_with_any_overlap"] == 1

    classification_only = report["classification_only"]
    assert classification_only["gold_total"] == 3
    assert classification_only["gold_with_any_overlap"] == 3
    assert classification_only["gold_with_same_label_any_overlap"] == 2
    assert classification_only["gold_best_label_match"] == 2
    assert classification_only["same_label_any_overlap_rate"] == (2 / 3)
    assert classification_only["supported_gold_total"] == 2
    assert classification_only["supported_gold_with_same_label_any_overlap"] == 2
    assert classification_only["supported_same_label_any_overlap_rate"] == 1.0
    assert classification_only["confusion_by_gold_label"]["KNOWLEDGE"]["OTHER"] == 1

    assert "f1" in report
    assert "practical_precision" in report
    assert "practical_recall" in report
    assert "practical_f1" in report
    assert report["practical_recall"] >= report["recall"]
    assert report["practical_f1"] >= report["f1"]
    assert "span_width_stats" in report
    assert "granularity_mismatch" in report

def test_eval_freeform_app_aligned_markdown_section(tmp_path) -> None:
    fixture = _run_app_aligned_freeform_fixture(tmp_path)
    report_md = fixture["report_md"]

    assert "Practical / Content overlap (any-overlap):" in report_md
    assert "Strict / Localization (IoU>=0.5):" in report_md
    assert "Gold dedupe:" in report_md
    assert "Default dedupe: enabled" in report_md
    assert "App-aligned diagnostics:" in report_md
    assert "Recipe count diagnostics:" in report_md
    assert "Supported labels only (relaxed)" in report_md
    assert "Any-overlap coverage (same label, IoU>0):" in report_md
    assert "Classification-only diagnostics (boundary-insensitive):" in report_md
    assert "Same-label any-overlap:" in report_md
    assert "Supported-label same-label any-overlap:" in report_md


def test_eval_freeform_prefers_recipe_title_over_recipe_block(tmp_path) -> None:
    predicted = [
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:structural:loc:block_index=22:title",
                "chunk_level": "structural",
                "chunk_type": "recipe_title",
                "chunk_type_hint": "recipe_title",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"start_block": 22, "end_block": 22},
            }
        },
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:deadbeef:structural:loc:block_index=20:block",
                "chunk_level": "structural",
                "chunk_type": "recipe_block",
                "chunk_type_hint": "recipe",
                "source_hash": "deadbeefcafebabe",
                "source_file": "book.epub",
                "location": {"start_block": 20, "end_block": 25},
            }
        },
    ]
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text(
        "\n".join(json.dumps(row) for row in predicted) + "\n",
        encoding="utf-8",
    )

    gold_rows = [
        {
            "span_id": "gold-title",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "RECIPE_TITLE",
            "touched_row_indices": [22],
        }
    ]
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n",
        encoding="utf-8",
    )

    result = evaluate_predicted_vs_freeform(
        load_predicted_labeled_ranges(pred_run),
        load_gold_freeform_ranges(gold_path),
        overlap_threshold=0.5,
    )
    report = result["report"]
    title = report["per_label"]["RECIPE_TITLE"]
    assert title["pred_total"] == 1
    assert title["gold_total"] == 1
    assert title["precision"] == 1.0
    assert title["recall"] == 1.0


def test_eval_freeform_rejects_removed_label_aliases(tmp_path) -> None:
    gold_path = tmp_path / "gold_aliases.jsonl"
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "span_id": "gold-tip",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "TIP",
                        "touched_row_indices": [10],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-notes",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "NOTES",
                        "touched_row_indices": [11],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-note",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "NOTE",
                        "touched_row_indices": [12],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-variant",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "VARIANT",
                        "touched_row_indices": [13],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-narrative",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "NARRATIVE",
                        "touched_row_indices": [14],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-yield",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "YIELD",
                        "touched_row_indices": [15],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-time",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "TIME",
                        "touched_row_indices": [16],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid freeform label"):
        load_gold_freeform_ranges(gold_path)


def _run_freeform_yield_time_additive_fixture(tmp_path) -> dict[str, object]:
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    pred_tasks = [
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:abc123:atomic:loc:block_index=1:a",
                "chunk_level": "atomic",
                "chunk_type": "ingredient_line",
                "chunk_type_hint": "ingredient",
                "source_hash": "abc123",
                "source_file": "book.epub",
                "location": {"block_index": 1},
            }
        },
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:abc123:atomic:loc:block_index=5:b",
                "chunk_level": "atomic",
                "chunk_type": "yield_line",
                "chunk_type_hint": "yield",
                "source_hash": "abc123",
                "source_file": "book.epub",
                "location": {"block_index": 5},
            }
        },
        {
            "data": {
                "chunk_id": "urn:recipeimport:chunk:text:abc123:atomic:loc:block_index=6:c",
                "chunk_level": "atomic",
                "chunk_type": "time_line",
                "chunk_type_hint": "time_line",
                "source_hash": "abc123",
                "source_file": "book.epub",
                "location": {"block_index": 6},
            }
        },
    ]
    (pred_run / "label_studio_tasks.jsonl").write_text(
        "\n".join(json.dumps(row) for row in pred_tasks) + "\n",
        encoding="utf-8",
    )

    gold_rows = [
        {
            "span_id": "gold-ing",
            "source_hash": "abc123",
            "source_file": "book.epub",
            "label": "INGREDIENT_LINE",
            "touched_row_indices": [1],
        },
        {
            "span_id": "gold-yield",
            "source_hash": "abc123",
            "source_file": "book.epub",
            "label": "YIELD_LINE",
            "touched_row_indices": [5],
        },
        {
            "span_id": "gold-time",
            "source_hash": "abc123",
            "source_file": "book.epub",
            "label": "TIME_LINE",
            "touched_row_indices": [6],
        },
    ]
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(json.dumps(row) for row in gold_rows) + "\n",
        encoding="utf-8",
    )

    predicted = load_predicted_labeled_ranges(pred_run)
    gold = load_gold_freeform_ranges(gold_path)
    result = evaluate_predicted_vs_freeform(predicted, gold, overlap_threshold=0.5)
    report = result["report"]
    return {
        "report": report,
        "markdown": format_freeform_eval_report_md(report),
    }


def test_eval_freeform_yield_time_are_additive_diagnostics(tmp_path) -> None:
    """YIELD_LINE and TIME_LINE appear in per-label metrics but not in app-aligned supported labels."""
    fixture = _run_freeform_yield_time_additive_fixture(tmp_path)
    report = fixture["report"]

    assert report["counts"]["gold_matched"] == 3
    assert report["counts"]["gold_total"] == 3

    assert "YIELD_LINE" in report["per_label"]
    assert "TIME_LINE" in report["per_label"]
    assert report["per_label"]["YIELD_LINE"]["recall"] == 1.0
    assert report["per_label"]["TIME_LINE"]["recall"] == 1.0

    app = report["app_aligned"]
    assert "YIELD_LINE" not in app["supported_labels"]
    assert "TIME_LINE" not in app["supported_labels"]
    assert app["supported_labels_strict"]["counts"]["gold_total"] == 1
    assert app["supported_labels_strict"]["counts"]["gold_matched"] == 1


def test_eval_freeform_yield_time_remain_visible_in_classification_and_markdown(
    tmp_path,
) -> None:
    fixture = _run_freeform_yield_time_additive_fixture(tmp_path)
    report = fixture["report"]
    md = fixture["markdown"]

    cls = report["classification_only"]
    assert "YIELD_LINE" in cls["per_label"]
    assert "TIME_LINE" in cls["per_label"]
    assert "YIELD_LINE" in md
    assert "TIME_LINE" in md


def test_eval_freeform_force_source_match_allows_mismatched_source_identity(tmp_path) -> None:
    pred_run = tmp_path / "pred_run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text(
        json.dumps(
            {
                "data": {
                    "chunk_id": "urn:recipeimport:chunk:epub:short_hash:atomic:loc:block_index=10:a",
                    "chunk_level": "atomic",
                    "chunk_type": "ingredient_line",
                    "chunk_type_hint": "ingredient",
                    "source_hash": "short_hash",
                    "source_file": "thefoodlabCUTDOWN.epub",
                    "location": {"block_index": 10},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "span_id": "gold-1",
                "source_hash": "full_hash",
                "source_file": "thefoodlab.epub",
                "label": "INGREDIENT_LINE",
                "touched_row_indices": [10],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    predicted = load_predicted_labeled_ranges(pred_run)
    gold = load_gold_freeform_ranges(gold_path)

    strict_result = evaluate_predicted_vs_freeform(
        predicted,
        gold,
        overlap_threshold=0.5,
    )
    assert strict_result["report"]["counts"]["gold_matched"] == 0
    assert strict_result["report"]["source_matching_mode"] == "strict"

    forced_result = evaluate_predicted_vs_freeform(
        predicted,
        gold,
        overlap_threshold=0.5,
        force_source_match=True,
    )
    assert forced_result["report"]["counts"]["gold_matched"] == 1
    assert forced_result["report"]["source_matching_mode"] == "forced"
