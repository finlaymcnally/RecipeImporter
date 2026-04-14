from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from cookimport.bench.qualitysuite.runtime import (
    QualityExperimentResult,
    _resolve_quality_alignment_cache_root,
    _resolve_quality_prediction_reuse_cache_root,
    run_quality_suite,
)
from cookimport.bench.quality_suite import QualitySuite


@pytest.fixture(autouse=True)
def _force_non_wsl_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep host-dependent WSL checks from making test expectations non-deterministic.
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment._running_in_wsl",
        lambda: False,
    )


@pytest.fixture(autouse=True)
def _stub_process_pool_probe_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Most tests only care about how runtime metadata propagates after the probe.
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
    )


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
    (gold_spans.parent / "row_gold_labels.jsonl").write_text("abc", encoding="utf-8")

    return QualitySuite(
        name="quality_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str((tmp_path / "input").resolve()),
        seed=42,
        max_targets=1,
        selection={
            "algorithm_version": "quality_representative_v2",
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


def _run_quality_suite_failure_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
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
    observed_prediction_reuse_roots: list[Path] = []

    def _fake_run_all_method_multi_source(**kwargs):
        observed_cache_roots.append(Path(kwargs["canonical_alignment_cache_root"]))
        observed_prediction_reuse_roots.append(
            Path(kwargs["prediction_reuse_cache_root"])
        )
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
    return {
        "run_root": run_root,
        "progress_messages": progress_messages,
        "observed_cache_roots": observed_cache_roots,
        "observed_prediction_reuse_roots": observed_prediction_reuse_roots,
    }


def _run_quality_suite_resume_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_resume.json"
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

    attempts: dict[str, int] = {"baseline": 0, "candidate": 0}

    def _write_fake_report(root_output_dir: Path) -> Path:
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

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        experiment_id = root_output_dir.name
        attempts[experiment_id] = attempts.get(experiment_id, 0) + 1
        root_output_dir.mkdir(parents=True, exist_ok=True)
        if experiment_id == "candidate" and attempts[experiment_id] == 1:
            raise KeyboardInterrupt("simulated crash during candidate experiment")
        return _write_fake_report(root_output_dir)

    monkeypatch.setattr(
        "cookimport.cli._run_all_method_benchmark_multi_source",
        _fake_run_all_method_multi_source,
    )

    with pytest.raises(KeyboardInterrupt):
        run_quality_suite(
            suite,
            tmp_path / "runs",
            experiments_file=experiments_file,
            base_run_settings_file=base_run_settings_file,
            search_strategy="exhaustive",
            max_parallel_experiments=1,
            progress_callback=None,
        )

    run_dirs = sorted((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    run_root = run_dirs[0]

    assert attempts["baseline"] == 1
    assert attempts["candidate"] == 1
    assert (run_root / "experiments" / "baseline" / "quality_experiment_result.json").exists()
    assert not (run_root / "summary.json").exists()

    partial_checkpoint = json.loads((run_root / "checkpoint.json").read_text(encoding="utf-8"))
    partial_summary = json.loads((run_root / "summary.partial.json").read_text(encoding="utf-8"))

    resumed_run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy="exhaustive",
        max_parallel_experiments=1,
        resume_run_dir=run_root,
        progress_callback=None,
    )

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((run_root / "checkpoint.json").read_text(encoding="utf-8"))
    return {
        "attempts": attempts,
        "run_root": run_root,
        "resumed_run_root": resumed_run_root,
        "partial_checkpoint": partial_checkpoint,
        "partial_summary": partial_summary,
        "summary": summary,
        "checkpoint": checkpoint,
    }


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
        (gold_spans.parent / "row_gold_labels.jsonl").write_text(
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
            "algorithm_version": "quality_representative_v2",
            "seed": 42,
            "max_targets": 3,
            "matched_count": 3,
            "strata_counts": {"small:sparse": 3},
        },
        targets=targets,
        selected_target_ids=selected_ids,
        unmatched=[],
    )


def _run_quality_suite_race_prune_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
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
    strategy_payload = json.loads(
        (
            run_root
            / "experiments"
            / "baseline"
            / "search_strategy.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "observed_round_variant_counts": observed_round_variant_counts,
        "strategy_payload": strategy_payload,
    }


def _run_quality_suite_race_exhaustive_fallback_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
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

    all_hashes = ["h1", "h2"]

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

    observed_round_variant_counts: list[tuple[int, int]] = []

    def _fake_run_all_method_multi_source(**kwargs):
        root_output_dir = Path(kwargs["root_output_dir"])
        target_variants = kwargs["target_variants"]
        variant_count = sum(len(rows) for _target, rows in target_variants)
        target_count = len(target_variants)
        observed_round_variant_counts.append((target_count, variant_count))

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
                practical = {"h1": 0.90, "h2": 0.80}[digest]
                strict = {"h1": 0.88, "h2": 0.78}[digest]
                variant_rows.append(
                    {
                        "status": "ok",
                        "run_config_hash": digest,
                        "run_config_summary": f"hash={digest}",
                        "practical_f1": practical,
                        "f1": strict,
                        "duration_seconds": {"h1": 20.0, "h2": 15.0}[digest],
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
        race_finalists=9,
        progress_callback=None,
    )
    strategy_payload = json.loads(
        (
            run_root
            / "experiments"
            / "baseline"
            / "search_strategy.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "observed_round_variant_counts": observed_round_variant_counts,
        "strategy_payload": strategy_payload,
    }
