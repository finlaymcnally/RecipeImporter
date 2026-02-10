import json

from cookimport.labelstudio.eval_freeform import (
    evaluate_predicted_vs_freeform,
    load_gold_freeform_ranges,
    load_predicted_labeled_ranges,
)
from cookimport.labelstudio.export import run_labelstudio_export
from cookimport.labelstudio.freeform_tasks import (
    build_freeform_span_tasks,
    map_span_offsets_to_blocks,
)
from cookimport.labelstudio.label_config_freeform import build_freeform_label_config


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
    source_blocks = first["source_map"]["blocks"]
    assert source_blocks[0]["segment_start"] == 0
    assert source_blocks[0]["segment_end"] == 5
    assert source_blocks[1]["segment_start"] == 7
    assert source_blocks[1]["segment_end"] == 11

    touched = map_span_offsets_to_blocks(first["source_map"], 0, 4)
    assert [item["block_index"] for item in touched] == [0]


def test_freeform_label_config_includes_knowledge_note_variant() -> None:
    config = build_freeform_label_config()
    assert '<Label value="TIP"/>' in config
    assert '<Label value="NOTES"/>' in config
    assert '<Label value="VARIANT"/>' in config
    assert '<Label value="KNOWLEDGE"/>' not in config
    assert '<Label value="NOTE"/>' not in config


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
                            "start_block_index": 0,
                            "end_block_index": 1,
                            "blocks": [
                                {
                                    "block_id": "urn:cookimport:block:hash123:0",
                                    "block_index": 0,
                                    "segment_start": 0,
                                    "segment_end": 5,
                                },
                                {
                                    "block_id": "urn:cookimport:block:hash123:1",
                                    "block_index": 1,
                                    "segment_start": 7,
                                    "segment_end": 11,
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
        export_scope="freeform-spans",
    )
    summary = result["summary"]
    assert summary["counts"]["labeled"] == 1
    assert summary["counts"]["missing"] == 0

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
    assert rows[0]["touched_block_indices"] == [0]

    segment_manifest = result["export_root"] / "freeform_segment_manifest.jsonl"
    manifest_rows = [
        json.loads(line)
        for line in segment_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["segment_id"] == "urn:cookimport:segment:hash123:0:1"


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
            "touched_block_indices": [1],
        },
        {
            "span_id": "gold-2",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "INSTRUCTION_LINE",
            "touched_block_indices": [2],
        },
        {
            "span_id": "gold-3",
            "source_hash": "deadbeefcafebabe",
            "source_file": "book.epub",
            "label": "NOTES",
            "touched_block_indices": [5],
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


def test_eval_freeform_backcompat_label_aliases(tmp_path) -> None:
    gold_path = tmp_path / "gold_aliases.jsonl"
    gold_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "span_id": "gold-tip",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "KNOWLEDGE",
                        "touched_block_indices": [10],
                    }
                ),
                json.dumps(
                    {
                        "span_id": "gold-note",
                        "source_hash": "h1",
                        "source_file": "book.epub",
                        "label": "NOTE",
                        "touched_block_indices": [11],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    gold = load_gold_freeform_ranges(gold_path)
    assert len(gold) == 2
    assert gold[0].label == "TIP"
    assert gold[1].label == "NOTES"
