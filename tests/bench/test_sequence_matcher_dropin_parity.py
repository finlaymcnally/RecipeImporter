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


def _accelerated_selection_or_skip(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "auto")
    selection = select_sequence_matcher()
    if selection.implementation == "stdlib":
        pytest.skip("Accelerated matcher unavailable in this environment.")
    return selection


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


def _largeish_edit_example() -> tuple[str, str]:
    left_parts: list[str] = []
    right_parts: list[str] = []
    for index in range(520):
        token = f"token{index % 17}"
        left_parts.append(token)
        if index % 37 == 0:
            right_parts.append(f"{token}_edit")
        else:
            right_parts.append(token)
    return " ".join(left_parts), " ".join(right_parts)


def _many_small_edits_example() -> tuple[str, str]:
    left_chars: list[str] = []
    for index in range(2200):
        left_chars.append(chr(ord("a") + (index % 26)))
        if index % 19 == 0:
            left_chars.append(" ")
    right_chars = list(left_chars)
    for index in range(11, len(right_chars), 97):
        current = right_chars[index]
        if current.isalpha():
            right_chars[index] = current.upper()
        elif current == " ":
            right_chars[index] = "-"
        else:
            right_chars[index] = "#"
    return "".join(left_chars), "".join(right_chars)


_TRICKY_TEXT_PAIRS: list[tuple[str, str]] = [
    (
        " ".join(["salt", "pepper", "garlic"] * 180),
        " ".join(["salt", "pepper", "garlic_x"] * 180),
    ),
    _many_small_edits_example(),
    (
        "step 1:\tmix flour\n\nstep 2:   add sugar\r\n\r\nstep 3:\t\tstir",
        "step 1: mix flour\nstep 2: add sugar\nstep 3: stir",
    ),
    _largeish_edit_example(),
]


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


@pytest.mark.parametrize(("prediction_text", "canonical_text"), _TRICKY_TEXT_PAIRS)
def test_sequence_matcher_opcodes_and_matching_blocks_match_stdlib_when_accelerated_available(
    monkeypatch: pytest.MonkeyPatch,
    prediction_text: str,
    canonical_text: str,
) -> None:
    selection = _accelerated_selection_or_skip(monkeypatch)
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
    assert accelerated_matcher.get_opcodes() == stdlib_matcher.get_opcodes()
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
    assert stdlib_report["alignment"] == auto_report["alignment"]

    stdlib_aligned_bytes = Path(
        stdlib_report["artifacts"]["aligned_prediction_blocks_jsonl"]
    ).read_bytes()
    auto_aligned_bytes = Path(
        auto_report["artifacts"]["aligned_prediction_blocks_jsonl"]
    ).read_bytes()
    assert stdlib_aligned_bytes == auto_aligned_bytes

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
