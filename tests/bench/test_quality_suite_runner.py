from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from cookimport.bench.quality_runner import (
    _resolve_quality_alignment_cache_root,
    run_quality_suite,
)
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

    observed_cache_roots: list[Path] = []

    def _fake_run_all_method_multi_source(**kwargs):
        observed_cache_roots.append(Path(kwargs["canonical_alignment_cache_root"]))
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
        max_parallel_experiments=1,
        progress_callback=progress_messages.append,
    )

    assert progress_messages
    assert "task 1/2" in progress_messages[0]
    assert (run_root / "suite_resolved.json").exists()
    assert (run_root / "experiments_resolved.json").exists()
    assert (run_root / "summary.json").exists()
    assert (run_root / "report.md").exists()

    resolved = json.loads((run_root / "experiments_resolved.json").read_text(encoding="utf-8"))
    assert Path(resolved["canonical_alignment_cache_root"]) == (
        tmp_path / ".cache" / "canonical_alignment"
    )

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
    assert observed_cache_roots
    assert observed_cache_roots[0] == (
        tmp_path / ".cache" / "canonical_alignment"
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


def test_run_quality_suite_rejects_codex_farm_without_confirmation(
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [{"id": "baseline", "run_settings_patch": {}}],
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
            include_codex_farm_requested=True,
            codex_farm_confirmed=False,
            progress_callback=None,
        )

    assert "explicit positive user confirmation" in str(excinfo.value)


def test_run_quality_suite_parallelizes_experiments_and_preserves_summary_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_parallel.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {}},
                {"id": "candidate", "run_settings_patch": {"workers": 3}},
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
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
    )

    started: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    completion_order: list[str] = []

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        experiment_id = root_output_dir.name

        with started_lock:
            started.add(experiment_id)
            if len(started) >= 2:
                both_started.set()

        assert both_started.wait(timeout=0.5)
        if experiment_id == "baseline":
            time.sleep(0.06)
        else:
            time.sleep(0.01)

        source_report = (
            root_output_dir
            / "sources"
            / experiment_id
            / "all_method_benchmark_report.json"
        )
        _write_json(
            source_report,
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

        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = report_md_path.with_suffix(".json")
        _write_json(
            report_json_path,
            {
                "matched_target_count": 1,
                "total_config_runs_planned": 1,
                "total_config_runs_completed": 1,
                "total_config_runs_successful": 1,
                "evaluation_signatures_unique": 1,
                "evaluation_runs_executed": 1,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": experiment_id,
                        "status": "ok",
                        "source_shard_total": 1,
                        "report_json_path": str(
                            source_report.relative_to(root_output_dir)
                        ),
                        "winner_metrics": {"precision": 0.6, "recall": 0.6, "f1": 0.6},
                    }
                ],
            },
        )
        report_md_path.write_text("report", encoding="utf-8")
        completion_order.append(experiment_id)
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy="exhaustive",
        max_parallel_experiments=2,
        progress_callback=None,
    )

    assert both_started.is_set()
    assert completion_order[0] == "candidate"

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in summary["experiments"]] == ["baseline", "candidate"]

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["max_parallel_experiments_requested"] == 2
    assert resolved["max_parallel_experiments_effective"] == 2


def test_run_quality_suite_auto_parallelism_uses_cpu_aware_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_auto.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {}},
                {"id": "candidate", "run_settings_patch": {"workers": 3}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {"workers": 2})

    monkeypatch.setattr(
        "cookimport.bench.quality_runner.os.cpu_count",
        lambda: 6,
    )
    monkeypatch.setattr(
        "cookimport.bench.quality_runner.os.getloadavg",
        lambda: (0.05, 0.05, 0.05),
    )
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
        experiment_id = root_output_dir.name
        source_report = (
            root_output_dir
            / "sources"
            / experiment_id
            / "all_method_benchmark_report.json"
        )
        _write_json(
            source_report,
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
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = report_md_path.with_suffix(".json")
        _write_json(
            report_json_path,
            {
                "matched_target_count": 1,
                "total_config_runs_planned": 1,
                "total_config_runs_completed": 1,
                "total_config_runs_successful": 1,
                "evaluation_signatures_unique": 1,
                "evaluation_runs_executed": 1,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": experiment_id,
                        "status": "ok",
                        "source_shard_total": 1,
                        "report_json_path": str(
                            source_report.relative_to(root_output_dir)
                        ),
                        "winner_metrics": {"precision": 0.6, "recall": 0.6, "f1": 0.6},
                    }
                ],
            },
        )
        report_md_path.write_text("report", encoding="utf-8")
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy="exhaustive",
        max_parallel_experiments=None,
        progress_callback=None,
    )

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["max_parallel_experiments_requested"] == "auto"
    assert resolved["max_parallel_experiments_mode"] == "auto"
    assert resolved["max_parallel_experiments_cpu_count"] == 6
    assert resolved["max_parallel_experiments_effective"] == 2
    assert resolved["max_parallel_experiments_adaptive"] is True


def test_quality_cache_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override_root = tmp_path / "external-cache"
    monkeypatch.setenv(
        "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT",
        str(override_root),
    )

    resolved = _resolve_quality_alignment_cache_root(out_dir=tmp_path / "runs")
    assert resolved == override_root


def test_quality_suite_schema_v2_levers_expand_and_pass_runtime_knobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_v2.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 2,
            "include_baseline": True,
            "include_all_on": True,
            "levers": [
                {
                    "id": "section_shared",
                    "enabled": True,
                    "run_settings_patch": {"section_detector_backend": "shared_v1"},
                },
                {
                    "id": "runtime_parallel_5",
                    "enabled": True,
                    "all_method_runtime_patch": {"max_parallel_sources": 5},
                },
                {
                    "id": "disabled",
                    "enabled": False,
                    "run_settings_patch": {"multi_recipe_splitter": "rules_v1"},
                },
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(
        base_run_settings_file,
        {
            "workers": 2,
            "all_method_max_parallel_sources": 2,
        },
    )

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

    observed_parallel_by_experiment: dict[str, int | None] = {}

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        experiment_id = root_output_dir.name
        observed_parallel_by_experiment[experiment_id] = kwargs.get(
            "max_parallel_sources"
        )

        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"

        shard_report = (
            root_output_dir
            / "sources"
            / "book_alpha"
            / "all_method_benchmark_report.json"
        )
        _write_json(
            shard_report,
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
            report_json_path,
            {
                "matched_target_count": 1,
                "total_config_runs_planned": 1,
                "total_config_runs_completed": 1,
                "total_config_runs_successful": 1,
                "evaluation_signatures_unique": 1,
                "evaluation_runs_executed": 1,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": "book_alpha",
                        "status": "ok",
                        "source_shard_total": 1,
                        "report_json_path": "sources/book_alpha/all_method_benchmark_report.json",
                        "winner_metrics": {"precision": 0.6, "recall": 0.6, "f1": 0.6},
                    }
                ],
            },
        )
        report_md_path.write_text("report", encoding="utf-8")
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        progress_callback=None,
    )

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    resolved_ids = [row["id"] for row in resolved["experiments"]]
    assert "baseline" in resolved_ids
    assert "section_shared" in resolved_ids
    assert "runtime_parallel_5" in resolved_ids
    assert "all_on" in resolved_ids
    assert "disabled" not in resolved_ids

    assert observed_parallel_by_experiment["baseline"] == 2
    assert observed_parallel_by_experiment["section_shared"] == 2
    assert observed_parallel_by_experiment["runtime_parallel_5"] == 5
    assert observed_parallel_by_experiment["all_on"] == 5


def test_quality_suite_schema_v2_rejects_unknown_runtime_keys(tmp_path: Path) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_bad_v2.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 2,
            "include_baseline": False,
            "levers": [
                {
                    "id": "bad",
                    "enabled": True,
                    "all_method_runtime_patch": {"not_a_real_knob": 1},
                }
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

    assert "unknown all_method_runtime_patch key" in str(excinfo.value)


def test_quality_suite_can_enable_deterministic_sweeps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [{"id": "baseline", "run_settings_patch": {}}],
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

    observed_include_deterministic_sweeps: list[bool] = []

    def _fake_build_all_method_target_variants(**kwargs):
        observed_include_deterministic_sweeps.append(
            bool(kwargs.get("include_deterministic_sweeps"))
        )
        return []

    monkeypatch.setattr(
        "cookimport.cli._build_all_method_target_variants",
        _fake_build_all_method_target_variants,
    )

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = report_md_path.with_suffix(".json")
        source_report = (
            root_output_dir
            / "sources"
            / "book_alpha"
            / "all_method_benchmark_report.json"
        )
        _write_json(
            source_report,
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
            report_json_path,
            {
                "matched_target_count": 1,
                "total_config_runs_planned": 0,
                "total_config_runs_completed": 0,
                "total_config_runs_successful": 0,
                "evaluation_signatures_unique": 0,
                "evaluation_runs_executed": 0,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": "book_alpha",
                        "status": "ok",
                        "source_shard_total": 1,
                        "report_json_path": "sources/book_alpha/all_method_benchmark_report.json",
                        "winner_metrics": {"precision": 0.6, "recall": 0.6, "f1": 0.6},
                    }
                ],
            },
        )
        report_md_path.write_text("report", encoding="utf-8")
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        include_deterministic_sweeps_requested=True,
        search_strategy="exhaustive",
        progress_callback=None,
    )

    assert observed_include_deterministic_sweeps == [True]
    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["include_deterministic_sweeps_requested"] is True


def test_quality_suite_keeps_global_scheduler_when_process_workers_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    source_beta = tmp_path / "input" / "beta.epub"
    source_beta.write_text("beta", encoding="utf-8")
    gold_beta = tmp_path / "gold" / "beta" / "exports" / "freeform_span_labels.jsonl"
    gold_beta.parent.mkdir(parents=True, exist_ok=True)
    gold_beta.write_text('{"source_file":"beta.epub","label":"OTHER"}\n', encoding="utf-8")
    (gold_beta.parent / "canonical_text.txt").write_text("beta", encoding="utf-8")
    quality_target_cls = type(suite.targets[0])
    suite.targets.append(
        quality_target_cls.model_validate(
            {
                "target_id": "beta",
                "source_file": str(source_beta.resolve()),
                "gold_spans_path": str(gold_beta.resolve()),
                "source_hint": "beta.epub",
                "canonical_text_chars": 4,
                "gold_span_rows": 1,
                "label_count": 1,
                "size_bucket": "small",
                "label_bucket": "sparse",
            }
        )
    )
    suite.selected_target_ids = ["alpha", "beta"]
    suite.max_targets = 2
    suite.selection["matched_count"] = 2
    suite.selection["strata_counts"] = {"small:sparse": 2}

    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [{"id": "baseline", "run_settings_patch": {}}],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(
        base_run_settings_file,
        {
            "workers": 2,
            "all_method_max_parallel_sources": 1,
            "all_method_scheduler_scope": "global",
        },
    )

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
        lambda **kwargs: [
            (target, [{"slug": str(target.gold_display)}])
            for target in kwargs.get("targets", [])
        ],
    )
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (False, "PermissionError: denied"),
    )

    observed_runtime: dict[str, object] = {}

    def _fake_run_all_method_multi_source(**kwargs):
        observed_runtime["scheduler_scope"] = kwargs.get("scheduler_scope")
        observed_runtime["max_parallel_sources"] = kwargs.get("max_parallel_sources")
        root_output_dir = Path(kwargs["root_output_dir"])
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = report_md_path.with_suffix(".json")
        _write_json(
            report_json_path,
            {
                "matched_target_count": 2,
                "total_config_runs_planned": 2,
                "total_config_runs_completed": 2,
                "total_config_runs_successful": 2,
                "evaluation_signatures_unique": 2,
                "evaluation_runs_executed": 2,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": "alpha",
                        "status": "ok",
                        "source_shard_total": 1,
                        "winner_metrics": {
                            "precision": 0.6,
                            "recall": 0.6,
                            "f1": 0.6,
                            "practical_precision": 0.7,
                            "practical_recall": 0.7,
                            "practical_f1": 0.7,
                        },
                    },
                    {
                        "source_group_key": "beta",
                        "status": "ok",
                        "source_shard_total": 1,
                        "winner_metrics": {
                            "precision": 0.5,
                            "recall": 0.5,
                            "f1": 0.5,
                            "practical_precision": 0.6,
                            "practical_recall": 0.6,
                            "practical_f1": 0.6,
                        },
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
        search_strategy="exhaustive",
        progress_callback=progress_messages.append,
    )

    assert run_root.exists()
    assert observed_runtime["scheduler_scope"] == "global"
    assert observed_runtime["max_parallel_sources"] == 1
    assert any(
        "staying on global scheduler and using thread-backed config workers" in message
        for message in progress_messages
    )


def _build_suite_multi(tmp_path: Path) -> QualitySuite:
    input_root = tmp_path / "input"
    gold_root = tmp_path / "gold"
    input_root.mkdir(parents=True, exist_ok=True)
    gold_root.mkdir(parents=True, exist_ok=True)

    targets: list[dict[str, object]] = []
    selected_ids: list[str] = []
    for target_id, canonical_chars in (
        ("alpha", 1000),
        ("beta", 5000),
        ("gamma", 9000),
    ):
        source = input_root / f"{target_id}.epub"
        source.write_text("epub", encoding="utf-8")
        gold_spans = gold_root / target_id / "exports" / "freeform_span_labels.jsonl"
        gold_spans.parent.mkdir(parents=True, exist_ok=True)
        gold_spans.write_text(
            '{"source_file":"%s.epub","label":"OTHER"}\n' % target_id,
            encoding="utf-8",
        )
        (gold_spans.parent / "canonical_text.txt").write_text(
            target_id * 2,
            encoding="utf-8",
        )
        targets.append(
            {
                "target_id": target_id,
                "source_file": str(source.resolve()),
                "gold_spans_path": str(gold_spans.resolve()),
                "source_hint": f"{target_id}.epub",
                "canonical_text_chars": canonical_chars,
                "gold_span_rows": 10,
                "label_count": 5,
                "size_bucket": "small",
                "label_bucket": "sparse",
            }
        )
        selected_ids.append(target_id)

    return QualitySuite(
        name="quality_suite_multi",
        generated_at="2026-02-28_12.00.00",
        gold_root=str(gold_root.resolve()),
        input_root=str(input_root.resolve()),
        seed=42,
        max_targets=3,
        selection={
            "algorithm_version": "quality_representative_v1",
            "seed": 42,
            "max_targets": 3,
            "matched_count": 3,
            "strata_counts": {"small:sparse": 3},
        },
        targets=targets,
        selected_target_ids=selected_ids,
        unmatched=[],
    )


def test_quality_suite_race_prunes_configs_between_rounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite_multi(tmp_path)
    experiments_file = tmp_path / "experiments.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": "baseline", "run_settings_patch": {}},
            ],
        },
    )

    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include_codex: (False, None),
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_markdown_extractors_choice",
        lambda: False,
    )

    class _FakeRunSettings:
        def __init__(self, digest: str) -> None:
            self._digest = digest

        def stable_hash(self) -> str:
            return self._digest

    class _FakeVariant:
        def __init__(self, digest: str) -> None:
            self.run_settings = _FakeRunSettings(digest)

    all_hashes = ["h1", "h2", "h3", "h4"]

    def _fake_build_target_variants(**kwargs):
        targets = kwargs["targets"]
        output = []
        for target in targets:
            variants = [_FakeVariant(digest) for digest in all_hashes]
            output.append((target, variants))
        return output

    monkeypatch.setattr(
        "cookimport.cli._build_all_method_target_variants",
        _fake_build_target_variants,
    )

    observed_round_variant_counts: list[tuple[Path, int, int]] = []

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        target_variants = kwargs["target_variants"]
        variant_count = sum(len(rows) for _target, rows in target_variants)
        target_count = len(target_variants)
        observed_round_variant_counts.append((root_output_dir, target_count, variant_count))

        sources_payload: list[dict[str, object]] = []
        for target, variants in target_variants:
            source_group_key = str(target.gold_display)
            source_report_path = (
                root_output_dir
                / "sources"
                / source_group_key
                / "all_method_benchmark_report.json"
            )
            variant_rows = []
            for variant in variants:
                digest = variant.run_settings.stable_hash()
                practical = {"h1": 0.90, "h2": 0.80, "h3": 0.70, "h4": 0.60}[digest]
                strict = {"h1": 0.88, "h2": 0.78, "h3": 0.68, "h4": 0.58}[digest]
                variant_rows.append(
                    {
                        "status": "ok",
                        "run_config_hash": digest,
                        "run_config_summary": f"hash={digest}",
                        "practical_f1": practical,
                        "f1": strict,
                        "duration_seconds": {"h1": 20.0, "h2": 15.0, "h3": 10.0, "h4": 5.0}[digest],
                    }
                )
            _write_json(source_report_path, {"variants": variant_rows})
            sources_payload.append(
                {
                    "source_group_key": source_group_key,
                    "status": "ok",
                    "source_shard_total": 1,
                    "report_json_path": str(
                        source_report_path.relative_to(root_output_dir)
                    ),
                    "winner_metrics": {"precision": 0.9, "recall": 0.9, "f1": 0.9},
                }
            )

        report_json_path = root_output_dir / "all_method_benchmark_multi_source_report.json"
        _write_json(
            report_json_path,
            {
                "matched_target_count": target_count,
                "total_config_runs_planned": variant_count,
                "total_config_runs_completed": variant_count,
                "total_config_runs_successful": variant_count,
                "evaluation_signatures_unique": variant_count,
                "evaluation_runs_executed": variant_count,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": sources_payload,
            },
        )
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_md_path.write_text("report", encoding="utf-8")
        return report_md_path

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        search_strategy="race",
        race_probe_targets=1,
        race_mid_targets=2,
        race_keep_ratio=0.5,
        race_finalists=1,
        progress_callback=None,
    )

    # probe round: 1 target * 4 variants
    # mid round: 2 targets * 2 variants (kept 50%)
    # final round: 3 targets * 1 variant (finalists=1)
    counts = [(targets, variants) for _root, targets, variants in observed_round_variant_counts]
    assert counts == [(1, 4), (2, 4), (3, 3)]

    strategy_payload = json.loads(
        (
            run_root
            / "experiments"
            / "baseline"
            / "search_strategy.json"
        ).read_text(encoding="utf-8")
    )
    assert strategy_payload["strategy"] == "race"
    assert strategy_payload["final"]["variants_effective"] == 3
