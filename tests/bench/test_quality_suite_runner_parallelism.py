from __future__ import annotations

import tests.bench.quality_suite_runner_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


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

        assert both_started.wait(timeout=0.2)
        if experiment_id == "baseline":
            time.sleep(0.02)
        else:
            time.sleep(0.002)

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
        "cookimport.bench.qualitysuite.environment.os.cpu_count",
        lambda: 6,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.getloadavg",
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


def test_run_quality_suite_auto_parallelism_uses_default_auto_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiment_count = 6
    experiments_file = tmp_path / "experiments_auto_cap.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": f"exp_{index:02d}", "run_settings_patch": {}}
                for index in range(experiment_count)
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {"workers": 2})

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.cpu_count",
        lambda: 64,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.getloadavg",
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
    assert resolved["max_parallel_experiments_mode"] == "auto"
    assert resolved["max_parallel_experiments_effective"] == experiment_count
    assert resolved["max_parallel_experiments_auto_ceiling"] == 64
    assert resolved["max_parallel_experiments_auto_ceiling_source"] == "cpu_count"


def test_run_quality_suite_auto_parallelism_honors_ceiling_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiment_count = 7
    experiments_file = tmp_path / "experiments_auto_cap_env.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 1,
            "experiments": [
                {"id": f"exp_{index:02d}", "run_settings_patch": {}}
                for index in range(experiment_count)
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {"workers": 2})

    monkeypatch.setenv("COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS", "4")
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.cpu_count",
        lambda: 64,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.getloadavg",
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
        report_md_path = root_output_dir / "all_method_benchmark_multi_source_report.md"
        report_json_path = report_md_path.with_suffix(".json")
        source_report = (
            root_output_dir
            / "sources"
            / root_output_dir.name
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
                "total_config_runs_planned": 1,
                "total_config_runs_completed": 1,
                "total_config_runs_successful": 1,
                "evaluation_signatures_unique": 1,
                "evaluation_runs_executed": 1,
                "evaluation_results_reused_in_run": 0,
                "evaluation_results_reused_cross_run": 0,
                "sources": [
                    {
                        "source_group_key": root_output_dir.name,
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
    assert resolved["max_parallel_experiments_mode"] == "auto"
    assert resolved["max_parallel_experiments_effective"] == 4
    assert resolved["max_parallel_experiments_auto_ceiling"] == 4
    assert resolved["max_parallel_experiments_auto_ceiling_source"] == "env"


def test_run_quality_suite_switches_to_subprocess_executor_when_process_pool_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_subprocess.json"
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
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (False, "PermissionError: denied"),
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
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("thread-backed experiment path should not be used")
        ),
    )

    observed_ids: list[str] = []

    def _fake_subprocess_worker(**kwargs):
        experiment = kwargs["experiment"]
        observed_ids.append(experiment.id)
        return {
            "baseline": QualityExperimentResult(
                id="baseline",
                status="ok",
                run_settings_hash=experiment.run_settings.stable_hash(),
                run_settings_summary=experiment.run_settings.summary(),
                strict_f1_macro=0.60,
                practical_f1_macro=0.70,
                source_success_rate=1.0,
                sources_planned=1,
                sources_successful=1,
            ),
            "candidate": QualityExperimentResult(
                id="candidate",
                status="ok",
                run_settings_hash=experiment.run_settings.stable_hash(),
                run_settings_summary=experiment.run_settings.summary(),
                strict_f1_macro=0.61,
                practical_f1_macro=0.71,
                source_success_rate=1.0,
                sources_planned=1,
                sources_successful=1,
            ),
        }[experiment.id]

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment_via_subprocess",
        _fake_subprocess_worker,
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

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["experiment_executor_mode"] == "subprocess"
    assert "process_pool_unavailable" in str(
        resolved["experiment_executor_reason"] or ""
    )
    assert sorted(observed_ids) == ["baseline", "candidate"]


def test_run_quality_suite_uses_thread_executor_for_parallel_wsl_runs_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_wsl_executor.json"
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
    _write_json(base_run_settings_file, {"workers": 8, "pdf_split_workers": 8, "epub_split_workers": 8})

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment._running_in_wsl",
        lambda: True,
    )
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
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
    seen_experiment_ids: list[str] = []

    def _fake_thread_worker(**kwargs):
        run_settings = kwargs["run_settings"]
        experiment_id = kwargs["experiment_id"]
        seen_experiment_ids.append(experiment_id)
        return QualityExperimentResult(
            id=experiment_id,
            status="ok",
            run_settings_hash=run_settings.stable_hash(),
            run_settings_summary=run_settings.summary(),
            strict_f1_macro=0.60,
            practical_f1_macro=0.70,
            source_success_rate=1.0,
            sources_planned=1,
            sources_successful=1,
        )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment",
        _fake_thread_worker,
    )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment_via_subprocess",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess experiment path should not be used when pool is available")
        ),
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

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["experiment_executor_mode"] == "thread"
    assert resolved["experiment_executor_reason"] == "process_pool_available"
    assert resolved["wsl_detected"] is True
    assert sorted(seen_experiment_ids) == ["baseline", "candidate"]


def test_run_quality_suite_applies_wsl_safety_guard_to_nested_parallelism(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_wsl_guard.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 2,
            "all_method_runtime": {
                "max_parallel_sources": 4,
                "max_inflight_pipelines": 5,
                "max_concurrent_split_phases": 4,
                "max_eval_tail_pipelines": 4,
                "wing_backlog_target": 4,
                "smart_scheduler": True,
            },
            "experiments": [
                {"id": "candidate", "run_settings_patch": {"workers": 9}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(base_run_settings_file, {"workers": 9, "pdf_split_workers": 8, "epub_split_workers": 7})

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment._running_in_wsl",
        lambda: True,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.cpu_count",
        lambda: 8,
    )
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
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

    observed_workers: dict[str, int] = {}
    observed_pdf_workers: dict[str, int] = {}
    observed_runtime: dict[str, dict[str, object]] = {}

    def _fake_thread_worker(**kwargs):
        experiment_id = kwargs["experiment_id"]
        run_settings = kwargs["run_settings"]
        all_method_runtime = kwargs["all_method_runtime"]
        observed_workers[experiment_id] = int(run_settings.workers)
        observed_pdf_workers[experiment_id] = int(run_settings.pdf_split_workers)
        observed_runtime[experiment_id] = dict(all_method_runtime)
        return QualityExperimentResult(
            id=experiment_id,
            status="ok",
            run_settings_hash=run_settings.stable_hash(),
            run_settings_summary=run_settings.summary(),
            strict_f1_macro=0.60,
            practical_f1_macro=0.70,
            source_success_rate=1.0,
            sources_planned=1,
            sources_successful=1,
        )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment",
        _fake_thread_worker,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment_via_subprocess",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess experiment path should not be used when pool is available")
        ),
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

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["wsl_safety_guard_applied"] is True
    assert resolved["wsl_safety_guard_reason"] == "applied"
    assert resolved["wsl_safety_guard_worker_cap"] == 2
    assert resolved["wsl_safety_guard_adjusted_experiments"] == 2
    assert all(value == 2 for value in observed_workers.values())
    assert all(value == 2 for value in observed_pdf_workers.values())
    assert all(
        runtime.get("max_inflight_pipelines") == 2
        and runtime.get("max_concurrent_split_phases") == 1
        and runtime.get("max_eval_tail_pipelines") == 2
        and runtime.get("max_parallel_sources") == 1
        and runtime.get("wing_backlog_target") == 1
        and runtime.get("smart_scheduler") is False
        for runtime in observed_runtime.values()
    )


def test_run_quality_suite_applies_wsl_safety_guard_for_single_experiment_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_wsl_guard_single_slot.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 2,
            "all_method_runtime": {
                "max_parallel_sources": 4,
                "max_inflight_pipelines": 5,
                "max_concurrent_split_phases": 4,
                "max_eval_tail_pipelines": 4,
                "wing_backlog_target": 4,
                "smart_scheduler": True,
            },
            "experiments": [
                {"id": "candidate", "run_settings_patch": {"workers": 9}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(
        base_run_settings_file,
        {"workers": 9, "pdf_split_workers": 8, "epub_split_workers": 7},
    )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment._running_in_wsl",
        lambda: True,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment.os.cpu_count",
        lambda: 8,
    )
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
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
    observed_workers: dict[str, int] = {}
    observed_pdf_workers: dict[str, int] = {}
    observed_runtime: dict[str, dict[str, object]] = {}

    def _fake_thread_worker(**kwargs):
        experiment_id = kwargs["experiment_id"]
        run_settings = kwargs["run_settings"]
        all_method_runtime = kwargs["all_method_runtime"]
        observed_workers[experiment_id] = int(run_settings.workers)
        observed_pdf_workers[experiment_id] = int(
            run_settings.pdf_split_workers
        )
        observed_runtime[experiment_id] = dict(all_method_runtime)
        return QualityExperimentResult(
            id=experiment_id,
            status="ok",
            run_settings_hash=run_settings.stable_hash(),
            run_settings_summary=run_settings.summary(),
            strict_f1_macro=0.60,
            practical_f1_macro=0.70,
            source_success_rate=1.0,
            sources_planned=1,
            sources_successful=1,
        )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment",
        _fake_thread_worker,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment_via_subprocess",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess experiment path should not be used in single-worker mode")
        ),
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy="exhaustive",
        max_parallel_experiments=1,
        progress_callback=None,
    )

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["experiment_executor_mode"] == "thread"
    assert resolved["experiment_executor_reason"] == "single_worker"
    assert resolved["wsl_safety_guard_applied"] is True
    assert resolved["wsl_safety_guard_reason"] == "applied"
    assert resolved["wsl_safety_guard_worker_cap"] == 2
    assert resolved["wsl_safety_guard_adjusted_experiments"] == 2
    assert all(value == 2 for value in observed_workers.values())
    assert all(value == 2 for value in observed_pdf_workers.values())
    assert all(
        runtime.get("max_inflight_pipelines") == 2
        and runtime.get("max_concurrent_split_phases") == 1
        and runtime.get("max_eval_tail_pipelines") == 2
        and runtime.get("max_parallel_sources") == 1
        and runtime.get("wing_backlog_target") == 1
        and runtime.get("smart_scheduler") is False
        for runtime in observed_runtime.values()
    )


def test_run_quality_suite_allows_wsl_safety_guard_opt_out_with_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = _build_suite(tmp_path)
    experiments_file = tmp_path / "experiments_wsl_guard_disable_env.json"
    _write_json(
        experiments_file,
        {
            "schema_version": 2,
            "all_method_runtime": {
                "max_parallel_sources": 4,
                "max_inflight_pipelines": 5,
                "max_concurrent_split_phases": 4,
                "max_eval_tail_pipelines": 4,
                "wing_backlog_target": 4,
                "smart_scheduler": True,
            },
            "experiments": [
                {"id": "candidate", "run_settings_patch": {"workers": 9}},
            ],
        },
    )
    base_run_settings_file = tmp_path / "base_run_settings.json"
    _write_json(
        base_run_settings_file,
        {"workers": 9, "pdf_split_workers": 8, "epub_split_workers": 7},
    )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.environment._running_in_wsl",
        lambda: True,
    )
    monkeypatch.setenv("COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD", "1")
    monkeypatch.setattr(
        "cookimport.cli._probe_all_method_process_pool_executor",
        lambda: (True, None),
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

    observed_workers: dict[str, int] = {}
    observed_runtime: dict[str, dict[str, object]] = {}

    def _fake_thread_worker(**kwargs):
        experiment_id = kwargs["experiment_id"]
        run_settings = kwargs["run_settings"]
        all_method_runtime = kwargs["all_method_runtime"]
        observed_workers[experiment_id] = int(run_settings.workers)
        observed_runtime[experiment_id] = dict(all_method_runtime)
        return QualityExperimentResult(
            id=experiment_id,
            status="ok",
            run_settings_hash=run_settings.stable_hash(),
            run_settings_summary=run_settings.summary(),
            strict_f1_macro=0.60,
            practical_f1_macro=0.70,
            source_success_rate=1.0,
            sources_planned=1,
            sources_successful=1,
        )

    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment",
        _fake_thread_worker,
    )
    monkeypatch.setattr(
        "cookimport.bench.qualitysuite.runtime._run_single_experiment_via_subprocess",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess experiment path should not be used when pool is available")
        ),
    )

    run_root = run_quality_suite(
        suite,
        tmp_path / "runs",
        experiments_file=experiments_file,
        base_run_settings_file=base_run_settings_file,
        search_strategy="exhaustive",
        max_parallel_experiments=1,
        progress_callback=None,
    )

    resolved = json.loads(
        (run_root / "experiments_resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["wsl_safety_guard_applied"] is False
    assert resolved["wsl_safety_guard_reason"] == "disabled_by_env"
    assert resolved["wsl_safety_guard_adjusted_experiments"] == 0
    assert all(value == 9 for value in observed_workers.values())
    assert all(
        runtime.get("max_inflight_pipelines") == 5
        and runtime.get("max_concurrent_split_phases") == 4
        and runtime.get("max_eval_tail_pipelines") == 4
        and runtime.get("max_parallel_sources") == 4
        and runtime.get("wing_backlog_target") == 4
        and runtime.get("smart_scheduler") is True
        for runtime in observed_runtime.values()
    )


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


def test_quality_prediction_reuse_cache_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override_root = tmp_path / "external-prediction-reuse"
    monkeypatch.setenv(
        "COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT",
        str(override_root),
    )

    resolved = _resolve_quality_prediction_reuse_cache_root(out_dir=tmp_path / "runs")
    assert resolved == override_root


def test_quality_suite_schema_v2_levers_expand_and_pass_runtime_knobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE", "thread")
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
                    "id": "extractor_unstructured",
                    "enabled": True,
                    "run_settings_patch": {"epub_extractor": "unstructured"},
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
    assert "extractor_unstructured" in resolved_ids
    assert "runtime_parallel_5" in resolved_ids
    assert "all_on" in resolved_ids
    assert "disabled" not in resolved_ids

    assert observed_parallel_by_experiment["baseline"] == 2
    assert observed_parallel_by_experiment["extractor_unstructured"] == 2
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
