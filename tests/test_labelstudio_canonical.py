import json

from cookimport.labelstudio.block_tasks import (
    build_block_id,
    build_block_tasks,
    load_task_ids_from_jsonl,
)
from cookimport.labelstudio.canonical import derive_gold_spans
from cookimport.labelstudio.eval_canonical import Span, evaluate_structural_vs_gold
from cookimport.labelstudio.models import ArchiveBlock


def test_block_tasks_deterministic_and_resumable(tmp_path) -> None:
    archive = [
        ArchiveBlock(index=0, text="Title", location={"block_index": 0}),
        ArchiveBlock(index=1, text="Ingredient", location={"block_index": 1}),
        ArchiveBlock(index=2, text="Step", location={"block_index": 2}),
    ]
    tasks_a = build_block_tasks(
        archive,
        source_hash="hash123",
        source_file="book.epub",
        context_window=1,
    )
    tasks_b = build_block_tasks(
        archive,
        source_hash="hash123",
        source_file="book.epub",
        context_window=1,
    )
    assert tasks_a == tasks_b
    assert tasks_a[1]["data"]["context_before"] == "Title"
    assert tasks_a[1]["data"]["context_after"] == "Step"

    tasks_path = tmp_path / "tasks.jsonl"
    tasks_path.write_text("\n".join(json.dumps(task) for task in tasks_a) + "\n")
    loaded = load_task_ids_from_jsonl(tasks_path, "block_id")
    assert build_block_id("hash123", 0) in loaded
    assert build_block_id("hash123", 2) in loaded


def test_derive_gold_spans_with_end_runs() -> None:
    labels = [
        {"block_id": "b0", "source_hash": "hash", "source_file": "book", "block_index": 0, "label": "RECIPE_TITLE"},
        {"block_id": "b1", "source_hash": "hash", "source_file": "book", "block_index": 1, "label": "INGREDIENT_LINE"},
        {"block_id": "b2", "source_hash": "hash", "source_file": "book", "block_index": 2, "label": "INSTRUCTION_LINE"},
        {"block_id": "b3", "source_hash": "hash", "source_file": "book", "block_index": 3, "label": "NARRATIVE"},
        {"block_id": "b4", "source_hash": "hash", "source_file": "book", "block_index": 4, "label": "INSTRUCTION_LINE"},
        {"block_id": "b5", "source_hash": "hash", "source_file": "book", "block_index": 5, "label": "NARRATIVE"},
        {"block_id": "b6", "source_hash": "hash", "source_file": "book", "block_index": 6, "label": "NARRATIVE"},
        {"block_id": "b7", "source_hash": "hash", "source_file": "book", "block_index": 7, "label": "RECIPE_TITLE"},
        {"block_id": "b8", "source_hash": "hash", "source_file": "book", "block_index": 8, "label": "INGREDIENT_LINE"},
    ]
    spans = derive_gold_spans(labels, k_end_run=2)
    assert len(spans) == 2
    assert spans[0]["start_block_index"] == 0
    assert spans[0]["end_block_index"] == 4
    assert spans[1]["start_block_index"] == 7
    assert spans[1]["end_block_index"] == 8


def test_eval_structural_vs_gold() -> None:
    gold = [
        Span(
            span_id="gold:0",
            source_hash="hash",
            source_file="book",
            start_block_index=0,
            end_block_index=4,
        ),
        Span(
            span_id="gold:1",
            source_hash="hash",
            source_file="book",
            start_block_index=7,
            end_block_index=8,
        ),
    ]
    predicted = [
        Span(
            span_id="pred:0",
            source_hash="hash",
            source_file="book",
            start_block_index=0,
            end_block_index=4,
        ),
        Span(
            span_id="pred:1",
            source_hash="hash",
            source_file="book",
            start_block_index=7,
            end_block_index=9,
        ),
        Span(
            span_id="pred:2",
            source_hash="hash",
            source_file="book",
            start_block_index=12,
            end_block_index=14,
        ),
    ]
    result = evaluate_structural_vs_gold(predicted, gold, overlap_threshold=0.5)
    report = result["report"]
    assert report["counts"]["gold_total"] == 2
    assert report["counts"]["pred_total"] == 3
    assert report["counts"]["gold_matched"] == 2
    assert report["counts"]["pred_matched"] == 2
    assert report["boundary"]["correct"] == 1
    assert report["boundary"]["over"] == 1


def test_eval_prefix_hash_match() -> None:
    gold = [
        Span(
            span_id="gold:0",
            source_hash="deadbeefcafebabe",
            source_file="book",
            start_block_index=0,
            end_block_index=2,
        )
    ]
    predicted = [
        Span(
            span_id="pred:0",
            source_hash="deadbeef",
            source_file="book",
            start_block_index=0,
            end_block_index=2,
        )
    ]
    result = evaluate_structural_vs_gold(predicted, gold, overlap_threshold=0.5)
    report = result["report"]
    assert report["counts"]["gold_matched"] == 1
