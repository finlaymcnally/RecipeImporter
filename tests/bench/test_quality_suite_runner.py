from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.bench.quality_runner import run_quality_suite
from cookimport.bench.quality_suite import QualitySuite


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _build_suite(tmp_path: Path) -> QualitySuite:
    source = tmp_path / "input" / "alpha.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("epub", encoding="utf-8")

    gold_spans = tmp_path / "gold" / "alpha" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub","label":"OTHER"}\n', encoding="utf-8")
    (gold_spans.parent / "canonical_text.txt").write_text("abc", encoding="utf-8")

    return QualitySuite(
        name="quality_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str((tmp_path / "input").resolve()),
        seed=42,
        max_targets=1,
        selection={
            "algorithm_version": "quality_representative_v1",
            "seed": 42,
            "max_targets": 1,
            "matched_count": 1,
            "strata_counts": {"small:sparse": 1},
        },
        targets=[
            {
                "target_id": "alpha",
                "source_file": str(source.resolve()),
                "gold_spans_path": str(gold_spans.resolve()),
                "source_hint": "alpha.epub",
                "canonical_text_chars": 3,
                "gold_span_rows": 1,
                "label_count": 1,
                "size_bucket": "small",
                "label_bucket": "sparse",
            }
        ],
        selected_target_ids=["alpha"],
        unmatched=[],
    )


def test_run_quality_suite_writes_artifacts_and_continues_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {}},
                {"id": "broken", "run_settings_patch": {"workers": 3}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {"workers": 2})

    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include_codex: (False, None),
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_markdown_extractors_choice",
        lambda: False,
    )
    monkeypatch.setattr(
        "cookimport.cli._build_all_method_target_variants",
        lambda **_kwargs: [],
    )

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        root_output_dir.mkdir(parents=True, exist_ok=True)
        if root_output_dir.name == "broken":
            raise RuntimeError("simulated benchmark failure")

        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"

        shard_1 = (
            root_output_dir
            / "sources"
            / "book_alpha"
            / "shard_01"
            / "all_method_benchmark_report.json"
        )
        shard_2 = (
            root_output_dir
            / "sources"
            / "book_alpha"
            / "shard_02"
            / "all_method_benchmark_report.json"
        )
        beta = (
            root_output_dir
            / "sources"
            / "book_beta"
            / "all_method_benchmark_report.json"
        )

        _write_json(
            shard_1,
            {
                "winner_by_f1": {
                    "precision": 0.60,
                    "recall": 0.60,
                    "f1": 0.60,
                    "practical_precision": 0.70,
                    "practical_recall": 0.70,
                    "practical_f1": 0.70,
                }
            },
        )
        _write_json(
            shard_2,
            {
                "winner_by_f1": {
                    "precision": 0.80,
                    "recall": 0.80,
                    "f1": 0.80,
                    "practical_precision": 0.75,
                    "practical_recall": 0.75,
                    "practical_f1": 0.75,
                }
            },
        )
        _write_json(
            beta,
            {
                "winner_by_f1": {
                    "precision": 0.40,
                    "recall": 0.40,
                    "f1": 0.40,
                    "practical_precision": 0.50,
                    "practical_recall": 0.50,
                    "practical_f1": 0.50,
                }
            },
        )

        _write_json(
            report_json_path,
            {
                "matched_target_count": 2,
                "total_config_runs_planned": 4,
                "total_config_runs_completed": 4,
                "total_config_runs_successful": 4,
                "evaluation_signatures_unique": 3,
                "evaluation_runs_executed": 2,
                "evaluation_results_reused_in_run": 1,
                "evaluation_results_reused_cross_run": 1,
                "sources": [
                    {
                        "source_group_key": "book_alpha",
                        "status": "ok",
                        "source_shard_total": 2,
                        "report_json_path": "sources/book_alpha/shard_01/all_method_benchmark_report.json",
                        "report_json_paths": [
                            "sources/book_alpha/shard_01/all_method_benchmark_report.json",
                            "sources/book_alpha/shard_02/all_method_benchmark_report.json",
                        ],
                        "winner_metrics": {"precision": 0.6, "recall": 0.6, "f1": 0.6},
                    },
                    {
                        "source_group_key": "book_beta",
                        "status": "ok",
                        "source_shard_total": 1,
                        "report_json_path": "sources/book_beta/all_method_benchmark_report.json",
                        "winner_metrics": {"precision": 0.4, "recall": 0.4, "f1": 0.4},
                    },
                ],
            },
        )
        report_md_path.write_text("report", encoding="utf-8")
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    progress_messages: list[str] = []
    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        progress_callback=progress_messages.append,
    )

    assert progress_messages
    assert "task 1/2" in progress_messages[0]
    assert (run_root / "suite_resolved.json").exists()
    assert (run_root / "experiments_resolved.json").exists()
    assert (run_root / "summary.json").exists()
    assert (run_root / "report.md").exists()

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in summary["experiments"]}
    baseline = rows["baseline"]
    broken = rows["broken"]

    assert summary["successful_experiments"] == 1
    assert summary["failed_experiments"] == 1
    assert baseline["status"] == "ok"
    assert broken["status"] == "failed"
    assert baseline["strict_f1_macro"] == pytest.approx(0.6)
    assert baseline["practical_f1_macro"] == pytest.approx(0.625)
    assert baseline["source_group_with_multiple_shards"] == 1
    assert baseline["source_success_rate"] == pytest.approx(1.0)
    assert baseline["run_settings_hash"]
    assert baseline["report_json_path"].startswith(
        "experiments/baseline/all_method_benchmark_multi_source_report.json"
    )


def test_run_quality_suite_rejects_unknown_patch_keys(tmp_path: Path) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_bad.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {"unknown_knob": 1}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {})

    with pytest.raises(ValueError) as excinfo:
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=experiments_file,
            base_run_settings_file=base_run_settings_file,
            progress_callback=None,
        )

    assert "unknown run_settings_patch key" in str(excinfo.value)
