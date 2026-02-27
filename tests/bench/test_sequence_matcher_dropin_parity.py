from __future__ import annotations

import importlib.util
import json
from difflib import SequenceMatcher as StdlibSequenceMatcher
from pathlib import Path

import pytest

import cookimport.bench.eval_canonical_text as canonical_eval
from cookimport.bench.eval_canonical_text import evaluate_canonical_text
from cookimport.bench.sequence_matcher_select import (
    SEQUENCE_MATCHER_ENV,
    get_sequence_matcher_selection,
    reset_sequence_matcher_selection_cache,
    select_sequence_matcher,
)


@pytest.fixture(autouse=True)
def _reset_sequence_matcher_cache() -> None:
    reset_sequence_matcher_selection_cache()
    yield
    reset_sequence_matcher_selection_cache()


def _matching_blocks_as_tuples(matcher: object) -> list[tuple[int, int, int]]:
    return [
        (int(match.a), int(match.b), int(match.size))
        for match in matcher.get_matching_blocks()  # type: ignore[attr-defined]
        if int(match.size) > 0
    ]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_minimal_canonical_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    gold_export_root = tmp_path / "exports"
    gold_export_root.mkdir(parents=True, exist_ok=True)
    canonical_text = "Title\nSubtitle\n1 cup stock"
    (gold_export_root / "canonical_text.txt").write_text(
        canonical_text,
        encoding="utf-8",
    )
    _write_jsonl(
        gold_export_root / "canonical_block_map.jsonl",
        [
            {"block_index": 0, "start_char": 0, "end_char": 5},
            {"block_index": 1, "start_char": 6, "end_char": 14},
            {"block_index": 2, "start_char": 15, "end_char": 26},
        ],
    )
    _write_jsonl(
        gold_export_root / "canonical_span_labels.jsonl",
        [
            {"span_id": "s0", "label": "RECIPE_TITLE", "start_char": 0, "end_char": 5},
            {"span_id": "s1", "label": "RECIPE_TITLE", "start_char": 6, "end_char": 14},
            {
                "span_id": "s2",
                "label": "INGREDIENT_LINE",
                "start_char": 15,
                "end_char": 26,
            },
        ],
    )
    (gold_export_root / "canonical_manifest.json").write_text(
        json.dumps({"schema_version": "canonical_gold.v1"}, sort_keys=True),
        encoding="utf-8",
    )

    stage_predictions_path = tmp_path / "stage_block_predictions.json"
    stage_predictions_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_block_predictions.v1",
                "workbook_slug": "demo",
                "source_file": "demo.epub",
                "source_hash": "abc123",
                "block_count": 2,
                "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    extracted_archive_path = tmp_path / "extracted_archive.json"
    extracted_archive_path.write_text(
        json.dumps(
            [
                {"index": 0, "text": "Title\nSubtitle"},
                {"index": 1, "text": "1 cup stock"},
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return gold_export_root, stage_predictions_path, extracted_archive_path


def test_sequence_matcher_selector_forced_stdlib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "stdlib")
    selection = get_sequence_matcher_selection()
    assert selection.implementation == "stdlib"
    assert selection.forced_mode == "stdlib"
    assert selection.version


def test_sequence_matcher_selector_invalid_mode_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "not-a-mode")
    with pytest.raises(ValueError, match=SEQUENCE_MATCHER_ENV):
        select_sequence_matcher()


def test_sequence_matcher_selector_forced_missing_mode_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forced_mode: str | None = None
    for mode_name, module_name in (
        ("cydifflib", "cydifflib"),
        ("cdifflib", "cdifflib"),
    ):
        if importlib.util.find_spec(module_name) is None:
            forced_mode = mode_name
            break
    if forced_mode is None:
        pytest.skip("No missing accelerated matcher dependency available to test.")

    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, forced_mode)
    with pytest.raises(RuntimeError, match=forced_mode):
        select_sequence_matcher()


def test_sequence_matcher_matching_blocks_match_stdlib_when_accelerated_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "auto")
    selection = select_sequence_matcher()
    if selection.implementation == "stdlib":
        pytest.skip("Accelerated matcher unavailable in this environment.")

    examples = [
        ("Title\n\nSubtitle\n\n1 cup stock", "Title\nSubtitle\n1 cup stock"),
        ("A quick-brown fox", "A quick brown fox"),
        ("mix flour\nand sugar", "mix flour and sugar"),
    ]
    for prediction_text, canonical_text in examples:
        stdlib_matcher = StdlibSequenceMatcher(
            None,
            prediction_text,
            canonical_text,
            autojunk=False,
        )
        accelerated_matcher = selection.matcher_class(
            None,
            prediction_text,
            canonical_text,
            autojunk=False,
        )
        assert _matching_blocks_as_tuples(accelerated_matcher) == _matching_blocks_as_tuples(
            stdlib_matcher
        )


def test_canonical_eval_stdlib_and_auto_modes_have_equal_scoring_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gold_export_root, stage_predictions_path, extracted_archive_path = (
        _write_minimal_canonical_fixture(tmp_path)
    )
    monkeypatch.setenv(canonical_eval._ALIGNMENT_STRATEGY_ENV, "legacy")

    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "stdlib")
    reset_sequence_matcher_selection_cache()
    stdlib_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "stdlib",
    )

    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "auto")
    reset_sequence_matcher_selection_cache()
    auto_result = evaluate_canonical_text(
        gold_export_root=gold_export_root,
        stage_predictions_json=stage_predictions_path,
        extracted_blocks_json=extracted_archive_path,
        out_dir=tmp_path / "auto",
    )

    stdlib_report = stdlib_result["report"]
    auto_report = auto_result["report"]
    assert stdlib_report["overall_line_accuracy"] == pytest.approx(
        auto_report["overall_line_accuracy"]
    )
    assert stdlib_report["macro_f1_excluding_other"] == pytest.approx(
        auto_report["macro_f1_excluding_other"]
    )
    assert stdlib_report["wrong_label_blocks"] == auto_report["wrong_label_blocks"]
    assert stdlib_report["missed_gold_blocks"] == auto_report["missed_gold_blocks"]

    stdlib_telemetry = stdlib_report["evaluation_telemetry"]
    auto_telemetry = auto_report["evaluation_telemetry"]
    assert stdlib_telemetry["alignment_sequence_matcher_impl"] == "stdlib"
    assert stdlib_telemetry["alignment_sequence_matcher_mode"] == "stdlib"
    assert auto_telemetry["alignment_sequence_matcher_impl"] in {
        "stdlib",
        "cydifflib",
        "cdifflib",
    }
    assert auto_telemetry["alignment_sequence_matcher_mode"] == "auto"
