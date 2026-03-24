"""Speed benchmark CLI wiring tests."""

from __future__ import annotations

import tests.bench.test_bench as _base

# Reuse shared imports/helpers from the base bench test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})

def test_bench_speed_discover_writes_suite(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    exports = gold_root / "alpha" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "freeform_span_labels.jsonl").write_text(
        '{"source_file":"alpha.epub"}\n',
        encoding="utf-8",
    )

    suite_out = tmp_path / "suite.json"
    cli.bench_speed_discover(
        gold_root=gold_root,
        input_root=input_root,
        out=suite_out,
    )

    payload = json.loads(suite_out.read_text(encoding="utf-8"))
    assert payload["targets"]
    assert payload["targets"][0]["target_id"] == "alpha"


def test_bench_speed_run_wires_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr("cookimport.cli._load_settings", lambda: {})
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )

    def _fake_run_speed_suite(
        suite,
        out_dir,
        *,
        scenarios,
        warmups,
        repeats,
        max_targets,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        run_settings,
        include_codex_farm_requested,
        codex_farm_confirmed,
        progress_callback,
    ):
        _ = progress_callback
        captured["include_codex_farm_requested"] = include_codex_farm_requested
        captured["codex_farm_confirmed"] = codex_farm_confirmed
        captured["suite"] = suite
        captured["out_dir"] = out_dir
        captured["scenarios"] = scenarios
        captured["warmups"] = warmups
        captured["repeats"] = repeats
        captured["max_targets"] = max_targets
        captured["max_parallel_tasks"] = max_parallel_tasks
        captured["require_process_workers"] = require_process_workers
        captured["resume_run_dir"] = resume_run_dir
        captured["run_settings"] = run_settings
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=2,
        max_targets=1,
        sequence_matcher="dmp",
    )

    assert captured["suite"] == loaded_suite
    assert captured["scenarios"] == [SpeedScenario.STAGE_IMPORT]
    assert captured["warmups"] == 1
    assert captured["repeats"] == 2
    assert captured["max_targets"] == 1
    assert captured["max_parallel_tasks"] is None
    assert captured["require_process_workers"] is False
    assert captured["resume_run_dir"] is None
    assert captured["include_codex_farm_requested"] is False
    assert captured["codex_farm_confirmed"] is False
    assert isinstance(captured["run_settings"], cli.RunSettings)
    assert captured["run_settings"].benchmark_sequence_matcher == "dmp"


def test_bench_speed_run_rejects_stale_run_settings_file_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_settings_file = tmp_path / "run_settings.json"
    run_settings_file.write_text(
        json.dumps(
            {
                "workers": 3,
                "benchmark_sequence_matcher": "not-dmp",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="benchmark_sequence_matcher"):
        cli.bench_speed_run(
            suite=suite_path,
            out_dir=tmp_path / "runs",
            scenarios="stage_import",
            warmups=1,
            repeats=2,
            max_targets=1,
            run_settings_file=run_settings_file,
            sequence_matcher="dmp",
        )


def test_bench_speed_run_forwards_parallel_and_resume_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr("cookimport.cli._load_settings", lambda: {})
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    def _fake_run_speed_suite(
        _suite,
        _out_dir,
        *,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        progress_callback,
        **kwargs,
    ):
        _ = progress_callback
        captured["max_parallel_tasks"] = max_parallel_tasks
        captured["require_process_workers"] = require_process_workers
        captured["resume_run_dir"] = resume_run_dir
        captured.update(kwargs)
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=1,
        max_parallel_tasks=3,
        require_process_workers=True,
        resume_run_dir=run_root,
    )

    assert captured["max_parallel_tasks"] == 3
    assert captured["require_process_workers"] is True
    assert captured["resume_run_dir"] == run_root


def test_bench_speed_run_rejects_missing_resume_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )

    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_run(
            suite=suite_path,
            out_dir=tmp_path / "runs",
            scenarios="stage_import",
            warmups=1,
            repeats=1,
            resume_run_dir=tmp_path / "missing-run-dir",
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--resume-run-dir" in failures[0]


def test_bench_speed_run_requires_codex_farm_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_run(
            suite=tmp_path / "suite.json",
            out_dir=tmp_path / "runs",
            scenarios="stage_import",
            warmups=1,
            repeats=1,
            include_codex_farm=True,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "--speedsuite-codex-farm-confirmation" in failures[0]


def test_bench_speed_run_passes_codex_farm_confirmation_to_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "alpha.epub"
    source_file.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text('{"source_file":"alpha.epub"}\n', encoding="utf-8")

    loaded_suite = BenchSpeedSuite(
        name="speed_suite",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str(tmp_path.resolve()),
        targets=[
            SpeedTarget(
                target_id="alpha",
                source_file=str(source_file.resolve()),
                gold_spans_path=str(gold_spans.resolve()),
            )
        ],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "runs" / "2026-02-28_12.00.00"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "report.md").write_text("", encoding="utf-8")
    (run_root / "summary.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cookimport.bench.speed_suite.load_speed_suite",
        lambda _suite_path: loaded_suite,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_suite.validate_speed_suite",
        lambda _suite, repo_root: [],
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_runner.parse_speed_scenarios",
        lambda _raw: [SpeedScenario.STAGE_IMPORT],
    )
    monkeypatch.setattr("cookimport.cli._load_settings", lambda: {})
    monkeypatch.setattr(
        "cookimport.cli._run_with_progress_status",
        lambda *, run, **_kwargs: run(lambda _message: None),
    )
    monkeypatch.setattr(
        "cookimport.cli._ensure_codex_farm_cmd_available",
        lambda _cmd: None,
    )
    monkeypatch.setattr(
        "cookimport.cli._resolve_all_method_codex_choice",
        lambda _include: (True, None),
    )
    monkeypatch.setattr("cookimport.cli._is_agent_execution_environment", lambda: False)

    def _fake_run_speed_suite(
        _suite,
        _out_dir,
        *,
        max_parallel_tasks,
        require_process_workers,
        resume_run_dir,
        progress_callback,
        **kwargs,
    ):
        _ = progress_callback
        captured["max_parallel_tasks"] = max_parallel_tasks
        captured["require_process_workers"] = require_process_workers
        captured["resume_run_dir"] = resume_run_dir
        captured.update(kwargs)
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.speed_runner.run_speed_suite",
        _fake_run_speed_suite,
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_speed_run(
        suite=suite_path,
        out_dir=tmp_path / "runs",
        scenarios="stage_import",
        warmups=1,
        repeats=1,
        include_codex_farm=True,
        speedsuite_codex_farm_confirmation=cli.SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN,
    )

    assert captured["include_codex_farm_requested"] is True
    assert captured["codex_farm_confirmed"] is True
    assert captured["max_parallel_tasks"] is None
    assert captured["require_process_workers"] is False
    assert captured["resume_run_dir"] is None


def test_bench_speed_run_blocks_codex_farm_in_agent_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    failures: list[str] = []

    def _fake_fail(message: str) -> None:
        failures.append(message)
        raise typer.Exit(1)

    monkeypatch.setattr("cookimport.cli._fail", _fake_fail)
    monkeypatch.setattr("cookimport.cli._is_agent_execution_environment", lambda: True)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_run(
            suite=tmp_path / "suite.json",
            out_dir=tmp_path / "runs",
            scenarios="stage_import",
            warmups=1,
            repeats=1,
            include_codex_farm=True,
            speedsuite_codex_farm_confirmation=cli.SPEED_RUN_CODEX_FARM_CONFIRMATION_TOKEN,
        )

    assert excinfo.value.exit_code == 1
    assert failures
    assert "blocked in agent-run environments" in failures[0]


def test_bench_speed_compare_fail_on_regression_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "comparisons"

    monkeypatch.setattr(
        "cookimport.bench.speed_compare.compare_speed_runs",
        lambda **_kwargs: {
            "thresholds": {
                "regression_pct": 5.0,
                "absolute_seconds_floor": 0.5,
            },
            "rows": [],
            "missing_in_baseline": [],
            "missing_in_candidate": [],
            "overall": {"verdict": "FAIL"},
        },
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_compare.format_speed_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    with pytest.raises(typer.Exit) as excinfo:
        cli.bench_speed_compare(
            baseline=baseline,
            candidate=candidate,
            out_dir=out_dir,
            regression_pct=5.0,
            absolute_seconds_floor=0.5,
            fail_on_regression=True,
        )

    assert excinfo.value.exit_code == 1


def test_bench_speed_compare_forwards_allow_settings_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def _fake_compare_speed_runs(**kwargs):
        captured.update(kwargs)
        return {
            "thresholds": {
                "regression_pct": 5.0,
                "absolute_seconds_floor": 0.5,
            },
            "rows": [],
            "missing_in_baseline": [],
            "missing_in_candidate": [],
            "overall": {"verdict": "PASS"},
        }

    monkeypatch.setattr(
        "cookimport.bench.speed_compare.compare_speed_runs",
        _fake_compare_speed_runs,
    )
    monkeypatch.setattr(
        "cookimport.bench.speed_compare.format_speed_compare_report",
        lambda _payload: "report",
    )
    monkeypatch.setattr("typer.secho", lambda *_args, **_kwargs: None)

    cli.bench_speed_compare(
        baseline=baseline,
        candidate=candidate,
        out_dir=tmp_path / "comparisons",
        regression_pct=5.0,
        absolute_seconds_floor=0.5,
        fail_on_regression=False,
        allow_settings_mismatch=True,
    )

    assert captured["allow_settings_mismatch"] is True
