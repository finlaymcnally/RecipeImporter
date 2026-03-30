from __future__ import annotations

import csv
import json
from pathlib import Path

import cookimport.cli as cli
from cookimport.bench.cutdown_export import (
    build_line_role_joined_line_rows,
    write_line_role_stable_samples,
)
from cookimport.bench.pairwise_flips import build_line_role_flips_vs_baseline


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            text = raw_line.strip()
            if not text:
                continue
            rows.append(json.loads(text))
    return rows


def _build_line_spans(canonical_text: str) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    cursor = 0
    line_labels = [
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "RECIPE_NOTES",
        "KNOWLEDGE",
    ]
    lines = canonical_text.splitlines()
    for line_index, line in enumerate(lines):
        start_char = cursor
        end_char = cursor + len(line)
        spans.append(
            {
                "span_id": f"s{line_index}",
                "label": line_labels[line_index],
                "start_char": start_char,
                "end_char": end_char,
            }
        )
        cursor = end_char + 1
    return spans


def test_stable_cutdown_samples_share_ids_and_text(tmp_path: Path) -> None:
    eval_output_dir = tmp_path / "eval"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    canonical_text = (
        "Dish Title\n"
        "1 cup flour\n"
        "Mix gently\n"
        "NOTE: Stir briefly\n"
        "Background note\n"
    )
    canonical_text_path = tmp_path / "canonical_text.txt"
    canonical_span_labels_path = tmp_path / "canonical_span_labels.jsonl"
    canonical_text_path.write_text(canonical_text, encoding="utf-8")
    _write_jsonl(canonical_span_labels_path, _build_line_spans(canonical_text))

    _write_jsonl(
        eval_output_dir / "wrong_label_lines.jsonl",
        [
            {"line_index": 1, "gold_label": "INGREDIENT_LINE", "pred_label": "YIELD_LINE"},
            {"line_index": 4, "gold_label": "KNOWLEDGE", "pred_label": "OTHER"},
        ],
    )
    line_role_predictions_path = tmp_path / "line_role_predictions.jsonl"
    _write_jsonl(
        line_role_predictions_path,
        [
            {
                "atomic_index": 0,
                "text": "Dish Title",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
            {
                "atomic_index": 1,
                "text": "1 cup flour",
                "decided_by": "codex",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
            {
                "atomic_index": 2,
                "text": "Mix gently",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
            {
                "atomic_index": 3,
                "text": "NOTE: Stir briefly",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
            {
                "atomic_index": 4,
                "text": "Background note",
                "decided_by": "codex",
                "within_recipe_span": False,
                "recipe_id": None,
            },
        ],
    )

    report = {
        "canonical": {
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_span_labels_path),
        }
    }
    joined_rows = build_line_role_joined_line_rows(
        report=report,
        eval_output_dir=eval_output_dir,
        line_role_predictions_path=line_role_predictions_path,
    )
    by_line_index = {int(row["line_index"]): row for row in joined_rows}
    assert by_line_index[1]["line_role_match_kind"] == "atomic_index_exact_text"
    flips_rows = build_line_role_flips_vs_baseline(
        joined_line_rows=joined_rows,
        line_role_predictions_path=line_role_predictions_path,
    )
    output_dir = tmp_path / "line-role-pipeline"
    write_line_role_stable_samples(
        output_dir=output_dir,
        joined_line_rows=joined_rows,
        flips_rows=flips_rows,
        sample_limit=20,
    )

    aligned_rows = _read_jsonl(output_dir / "aligned_prediction_blocks.sample.jsonl")
    wrong_rows = _read_jsonl(output_dir / "wrong_label_lines.sample.jsonl")
    correct_rows = _read_jsonl(output_dir / "correct_label_lines.sample.jsonl")
    flip_rows = _read_jsonl(output_dir / "line_role_flips_vs_baseline.sample.jsonl")

    assert aligned_rows
    assert wrong_rows
    assert correct_rows
    assert flip_rows

    aligned_by_sample_id = {
        str(row["sample_id"]): (int(row["line_index"]), str(row["line_text"]))
        for row in aligned_rows
    }
    for collection in (wrong_rows, correct_rows, flip_rows):
        for row in collection:
            sample_id = str(row["sample_id"])
            assert sample_id in aligned_by_sample_id
            assert (int(row["line_index"]), str(row["line_text"])) == aligned_by_sample_id[
                sample_id
            ]

    wrong_ids = {str(row["sample_id"]) for row in wrong_rows}
    correct_ids = {str(row["sample_id"]) for row in correct_rows}
    assert wrong_ids
    assert correct_ids
    assert wrong_ids.isdisjoint(correct_ids)


def test_joined_line_rows_match_line_role_metadata_by_exact_text_occurrence_only(
    tmp_path: Path,
) -> None:
    eval_output_dir = tmp_path / "eval"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    canonical_text = (
        "Lemon Vinaigrette\n"
        "A FEW BASIC HOW-TOS\n"
        "4 to 5 tablespoons lime juice\n"
        "Lemon Vinaigrette\n"
        "Background note\n"
    )
    canonical_text_path = tmp_path / "canonical_text.txt"
    canonical_span_labels_path = tmp_path / "canonical_span_labels.jsonl"
    canonical_text_path.write_text(canonical_text, encoding="utf-8")
    _write_jsonl(canonical_span_labels_path, _build_line_spans(canonical_text))

    _write_jsonl(
        eval_output_dir / "wrong_label_lines.jsonl",
        [
            {"line_index": 1, "gold_label": "INGREDIENT_LINE", "pred_label": "RECIPE_VARIANT"},
            {
                "line_index": 2,
                "gold_label": "INSTRUCTION_LINE",
                "pred_label": "INSTRUCTION_LINE",
            },
        ],
    )
    line_role_predictions_path = tmp_path / "line_role_predictions.jsonl"
    _write_jsonl(
        line_role_predictions_path,
        [
            {
                "atomic_index": 74,
                "text": "Lemon Vinaigrette",
                "decided_by": "rule",
                "within_recipe_span": False,
                "recipe_id": None,
            },
            {
                "atomic_index": 1204,
                "text": "A FEW BASIC HOW-TOS",
                "decided_by": "rule",
                "within_recipe_span": False,
                "recipe_id": None,
            },
            {
                "atomic_index": 1439,
                "text": "Lemon Vinaigrette",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:11",
            },
            {
                "atomic_index": 1440,
                "text": (
                    "4 to 5 tablespoons lime juice 4 teaspoons seasoned rice wine vinegar "
                    "1 tablespoon fish sauce"
                ),
                "decided_by": "fallback",
                "within_recipe_span": True,
                "recipe_id": "recipe:11",
            },
        ],
    )

    report = {
        "canonical": {
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_span_labels_path),
        }
    }
    joined_rows = build_line_role_joined_line_rows(
        report=report,
        eval_output_dir=eval_output_dir,
        line_role_predictions_path=line_role_predictions_path,
    )
    by_line_index = {int(row["line_index"]): row for row in joined_rows}

    assert by_line_index[0]["line_role_match_kind"] == "exact_text_occurrence"
    assert by_line_index[0]["line_role_prediction_atomic_index"] == 74

    assert by_line_index[1]["line_role_match_kind"] == "exact_text_occurrence"
    assert by_line_index[1]["line_role_prediction_atomic_index"] == 1204

    assert by_line_index[2]["decided_by"] is None
    assert by_line_index[2]["within_recipe_span"] is None
    assert by_line_index[2]["line_role_match_kind"] == "unmatched"
    assert by_line_index[2]["line_role_prediction_atomic_index"] is None

    assert by_line_index[3]["line_role_match_kind"] == "exact_text_occurrence"
    assert by_line_index[3]["line_role_prediction_atomic_index"] == 1439

    flips = build_line_role_flips_vs_baseline(
        joined_line_rows=joined_rows,
        line_role_predictions_path=line_role_predictions_path,
    )
    assert all(int(row["line_index"]) != 2 for row in flips)


def test_joined_line_rows_uses_sequence_context_for_duplicate_texts(
    tmp_path: Path,
) -> None:
    eval_output_dir = tmp_path / "eval"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    canonical_text = "Salt\nPepper\nSalt\nOil\n"
    canonical_text_path = tmp_path / "canonical_text.txt"
    canonical_span_labels_path = tmp_path / "canonical_span_labels.jsonl"
    canonical_text_path.write_text(canonical_text, encoding="utf-8")
    _write_jsonl(canonical_span_labels_path, _build_line_spans(canonical_text))
    _write_jsonl(eval_output_dir / "wrong_label_lines.jsonl", [])

    line_role_predictions_path = tmp_path / "line_role_predictions.jsonl"
    _write_jsonl(
        line_role_predictions_path,
        [
            {
                "atomic_index": 10,
                "text": "Salt",
                "decided_by": "rule",
                "within_recipe_span": False,
                "recipe_id": None,
            },
            {
                "atomic_index": 11,
                "text": "Salt",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
            {
                "atomic_index": 12,
                "text": "Pepper",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
            {
                "atomic_index": 13,
                "text": "Oil",
                "decided_by": "rule",
                "within_recipe_span": True,
                "recipe_id": "recipe:0",
            },
        ],
    )

    report = {
        "canonical": {
            "canonical_text_path": str(canonical_text_path),
            "canonical_span_labels_path": str(canonical_span_labels_path),
        }
    }
    joined_rows = build_line_role_joined_line_rows(
        report=report,
        eval_output_dir=eval_output_dir,
        line_role_predictions_path=line_role_predictions_path,
    )
    by_line_index = {int(row["line_index"]): row for row in joined_rows}

    assert by_line_index[0]["line_role_prediction_atomic_index"] == 11
    assert by_line_index[2]["line_role_match_kind"] == "unmatched"


def test_line_role_flips_uses_paired_history_baseline_rows() -> None:
    candidate_rows = [
        {
            "sample_id": "line:000001",
            "line_index": 1,
            "line_text": "1 cup flour",
            "gold_label": "INGREDIENT_LINE",
            "pred_label": "INGREDIENT_LINE",
            "decided_by": "rule",
        },
        {
            "sample_id": "line:000002",
            "line_index": 2,
            "line_text": "Mix gently",
            "gold_label": "INSTRUCTION_LINE",
            "pred_label": "INSTRUCTION_LINE",
            "decided_by": "codex",
        },
    ]
    baseline_rows = [
        {
            "sample_id": "line:000001",
            "line_index": 1,
            "line_text": "1 cup flour",
            "gold_label": "INGREDIENT_LINE",
            "pred_label": "YIELD_LINE",
        },
        {
            "sample_id": "line:000002",
            "line_index": 2,
            "line_text": "Mix gently",
            "gold_label": "INSTRUCTION_LINE",
            "pred_label": "INSTRUCTION_LINE",
        },
    ]

    flips = build_line_role_flips_vs_baseline(
        joined_line_rows=candidate_rows,
        line_role_predictions_path=None,
        baseline_joined_line_rows=baseline_rows,
    )

    assert flips == [
        {
            "baseline_label": "YIELD_LINE",
            "baseline_source": "paired_history_baseline",
            "candidate_label": "INGREDIENT_LINE",
            "decided_by": "rule",
            "gold_label": "INGREDIENT_LINE",
            "line_index": 1,
            "line_text": "1 cup flour",
            "sample_id": "line:000001",
        }
    ]


def _write_eval_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_line_role_regression_gate_payload_uses_history_baselines(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "seaandsmokeCUTDOWN.epub").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_INPUT", input_root)

    history_csv = tmp_path / "performance_history.csv"
    with history_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_category",
                "run_timestamp",
                "run_dir",
                "file_name",
                "eval_scope",
                "run_config_json",
            ],
        )
        writer.writeheader()

        def _row(
            *,
            run_timestamp: str,
            run_dir: Path,
            file_name: str,
            llm_recipe_pipeline: str,
            line_role_pipeline: str,
        ) -> None:
            writer.writerow(
                {
                    "run_category": "benchmark_eval",
                    "run_timestamp": run_timestamp,
                    "run_dir": str(run_dir),
                    "file_name": file_name,
                    "eval_scope": "canonical-text",
                    "run_config_json": json.dumps(
                        {
                            "llm_recipe_pipeline": llm_recipe_pipeline,
                            "line_role_pipeline": line_role_pipeline,
                        }
                    ),
                }
            )

        foodlab_vanilla = tmp_path / "foodlab-vanilla"
        foodlab_codex = tmp_path / "foodlab-codex"
        sea_vanilla = tmp_path / "sea-vanilla"
        sea_candidate = tmp_path / "sea-candidate"
        _write_eval_report(
            foodlab_vanilla / "eval_report.json",
            {"macro_f1_excluding_other": 0.60, "overall_line_accuracy": 0.61},
        )
        _write_eval_report(
            foodlab_codex / "eval_report.json",
            {
                "macro_f1_excluding_other": 0.64,
                "overall_line_accuracy": 0.66,
                "confusion": {
                    "INGREDIENT_LINE": {"YIELD_LINE": 10},
                    "OTHER": {"KNOWLEDGE": 10},
                },
            },
        )
        _write_eval_report(
            sea_vanilla / "eval_report.json",
            {"macro_f1_excluding_other": 0.52, "overall_line_accuracy": 0.53},
        )
        _write_eval_report(
            sea_candidate / "eval_report.json",
            {"macro_f1_excluding_other": 0.54, "overall_line_accuracy": 0.55},
        )

        _row(
            run_timestamp="2026-03-03T00:00:01",
            run_dir=foodlab_vanilla,
            file_name="thefoodlabCUTDOWN.epub",
            llm_recipe_pipeline="off",
            line_role_pipeline="off",
        )
        _row(
            run_timestamp="2026-03-03T00:00:02",
            run_dir=foodlab_codex,
            file_name="thefoodlabCUTDOWN.epub",
            llm_recipe_pipeline="codex-recipe-shard-v1",
            line_role_pipeline="off",
        )
        _row(
            run_timestamp="2026-03-03T00:00:03",
            run_dir=sea_vanilla,
            file_name="seaandsmokeCUTDOWN.epub",
            llm_recipe_pipeline="off",
            line_role_pipeline="off",
        )
        _row(
            run_timestamp="2026-03-03T00:00:04",
            run_dir=sea_candidate,
            file_name="seaandsmokeCUTDOWN.epub",
            llm_recipe_pipeline="off",
            line_role_pipeline="deterministic-route-v2",
        )

    candidate_report = {
        "macro_f1_excluding_other": 0.68,
        "overall_line_accuracy": 0.69,
        "confusion": {
            "INGREDIENT_LINE": {"YIELD_LINE": 5},
            "OTHER": {"KNOWLEDGE": 4},
        },
        "per_label": {
            "RECIPE_NOTES": {"recall": 0.5},
            "RECIPE_VARIANT": {"recall": 0.5},
            "INGREDIENT_LINE": {"recall": 0.4},
        },
    }
    payload = cli._build_line_role_regression_gate_payload(
        candidate_report=candidate_report,
        candidate_source_key="thefoodlabcutdown",
        history_csv_path=history_csv,
    )
    overall = payload.get("overall")
    assert isinstance(overall, dict)
    assert overall.get("verdict") == "PASS"


def test_line_role_regression_gate_payload_uses_vanilla_fallback_for_confusion_drop(
    tmp_path: Path,
) -> None:
    history_csv = tmp_path / "performance_history.csv"
    with history_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_category",
                "run_timestamp",
                "run_dir",
                "file_name",
                "eval_scope",
                "run_config_json",
            ],
        )
        writer.writeheader()
        foodlab_vanilla = tmp_path / "foodlab-vanilla"
        _write_eval_report(
            foodlab_vanilla / "eval_report.json",
            {
                "macro_f1_excluding_other": 0.60,
                "overall_line_accuracy": 0.61,
                "confusion": {
                    "INGREDIENT_LINE": {"YIELD_LINE": 10},
                    "OTHER": {"KNOWLEDGE": 10},
                },
            },
        )
        writer.writerow(
            {
                "run_category": "benchmark_eval",
                "run_timestamp": "2026-03-03T00:00:01",
                "run_dir": str(foodlab_vanilla),
                "file_name": "thefoodlabCUTDOWN.epub",
                "eval_scope": "canonical-text",
                "run_config_json": json.dumps(
                    {
                        "llm_recipe_pipeline": "off",
                        "line_role_pipeline": "off",
                    }
                ),
            }
        )

    candidate_report = {
        "macro_f1_excluding_other": 0.68,
        "overall_line_accuracy": 0.69,
        "confusion": {
            "INGREDIENT_LINE": {"YIELD_LINE": 5},
            "OTHER": {"KNOWLEDGE": 4},
        },
        "per_label": {
            "RECIPE_NOTES": {"recall": 0.5},
            "RECIPE_VARIANT": {"recall": 0.5},
            "INGREDIENT_LINE": {"recall": 0.5},
        },
    }
    payload = cli._build_line_role_regression_gate_payload(
        candidate_report=candidate_report,
        candidate_source_key="thefoodlabcutdown",
        history_csv_path=history_csv,
    )
    gates = payload.get("gates")
    assert isinstance(gates, list)
    by_name = {
        str(gate.get("name")): gate
        for gate in gates
        if isinstance(gate, dict) and gate.get("name")
    }
    ingredient_drop_gate = by_name.get("foodlab_ingredient_to_yield_confusion_drop")
    assert isinstance(ingredient_drop_gate, dict)
    assert ingredient_drop_gate.get("passed") is True
    assert "baseline_source=vanilla-off-fallback" in str(ingredient_drop_gate.get("reason"))
    other_drop_gate = by_name.get("foodlab_other_to_knowledge_confusion_drop")
    assert isinstance(other_drop_gate, dict)
    assert other_drop_gate.get("passed") is True
    assert "baseline_source=vanilla-off-fallback" in str(other_drop_gate.get("reason"))


def test_line_role_regression_gate_payload_fails_missing_history_comparators(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "seaandsmokeCUTDOWN.epub").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_INPUT", input_root)

    history_csv = tmp_path / "performance_history.csv"
    with history_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_category",
                "run_timestamp",
                "run_dir",
                "file_name",
                "eval_scope",
                "run_config_json",
            ],
        )
        writer.writeheader()

    candidate_report = {
        "macro_f1_excluding_other": 0.31,
        "overall_line_accuracy": 0.47,
        "per_label": {
            "RECIPE_NOTES": {"recall": 0.22},
            "RECIPE_VARIANT": {"recall": 0.08},
            "INGREDIENT_LINE": {"recall": 0.74},
        },
    }
    payload = cli._build_line_role_regression_gate_payload(
        candidate_report=candidate_report,
        candidate_source_key="thefoodlabcutdown",
        history_csv_path=history_csv,
    )

    gates = payload.get("gates")
    assert isinstance(gates, list)
    by_name = {
        str(gate.get("name")): gate
        for gate in gates
        if isinstance(gate, dict) and gate.get("name")
    }
    for gate_name in (
        "foodlab_macro_f1_delta_min",
        "foodlab_line_accuracy_delta_min",
        "foodlab_ingredient_to_yield_confusion_drop",
        "foodlab_other_to_knowledge_confusion_drop",
        "sea_macro_f1_no_regression",
        "sea_line_accuracy_no_regression",
    ):
        gate = by_name.get(gate_name)
        assert isinstance(gate, dict)
        assert gate.get("passed") is False
    overall = payload.get("overall")
    assert isinstance(overall, dict)
    assert overall.get("verdict") == "FAIL"


def test_line_role_regression_gate_payload_fails_when_recall_floors_not_met(
    tmp_path: Path,
) -> None:
    history_csv = tmp_path / "performance_history.csv"
    with history_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_category",
                "run_timestamp",
                "run_dir",
                "file_name",
                "eval_scope",
                "run_config_json",
            ],
        )
        writer.writeheader()

    candidate_report = {
        "macro_f1_excluding_other": 0.31,
        "overall_line_accuracy": 0.47,
        "per_label": {
            "RECIPE_NOTES": {"recall": 0.19},
            "RECIPE_VARIANT": {"recall": 0.06},
            "INGREDIENT_LINE": {"recall": 0.74},
        },
    }
    payload = cli._build_line_role_regression_gate_payload(
        candidate_report=candidate_report,
        candidate_source_key="thefoodlabcutdown",
        history_csv_path=history_csv,
    )
    gates = payload.get("gates")
    assert isinstance(gates, list)
    by_name = {
        str(gate.get("name")): gate
        for gate in gates
        if isinstance(gate, dict) and gate.get("name")
    }
    notes_gate = by_name.get("foodlab_recipe_notes_recall_min")
    assert isinstance(notes_gate, dict)
    assert notes_gate.get("passed") is False
    variant_gate = by_name.get("foodlab_recipe_variant_recall_min")
    assert isinstance(variant_gate, dict)
    assert variant_gate.get("passed") is False
    overall = payload.get("overall")
    assert isinstance(overall, dict)
    assert overall.get("verdict") == "FAIL"
