from __future__ import annotations

import typer

from cookimport.cli_support import (
    Annotated,
    Any,
    DEFAULT_BENCH_QUALITY_COMPARISONS,
    DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_EXPERIMENTS,
    DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_PROFILE,
    DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_SERIES,
    DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_THRESHOLDS,
    DEFAULT_BENCH_QUALITY_RUNS,
    DEFAULT_BENCH_QUALITY_SUITES,
    DEFAULT_BENCH_SPEED_COMPARISONS,
    DEFAULT_BENCH_SPEED_RUNS,
    DEFAULT_BENCH_SPEED_SUITES,
    DEFAULT_GOLDEN,
    DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
    DEFAULT_INPUT,
    DEFAULT_OUTPUT,
    Path,
    QUALITY_LIGHTWEIGHT_SERIES_DISABLED_MESSAGE,
    REPO_ROOT,
    RUN_SETTING_CONTRACT_FULL,
    RunSettings,
    _enforce_live_bench_speed_codex_guardrails,
    _ensure_codex_farm_cmd_available,
    _fail,
    _golden_benchmark_root,
    _load_settings,
    _normalize_gold_adaptation_mode,
    _parse_quality_discover_formats,
    _print_codex_decision,
    _print_oracle_followup_summary,
    _print_oracle_upload_summary,
    _processing_timeseries_history_path,
    _resolve_all_method_codex_choice,
    _resolve_speedsuite_codex_farm_confirmation,
    _run_settings_payload_from_settings,
    _run_with_progress_status,
    _unwrap_typer_option_default,
    _write_qualitysuite_agent_bridge_bundle_for_compare,
    _write_qualitysuite_agent_bridge_bundle_for_run,
    dt,
    evaluate_stage_blocks,
    history_root_for_output,
    json,
    normalize_codex_reasoning_effort,
    os,
    project_run_config_payload,
    resolve_codex_execution_policy,
    resolve_oracle_benchmark_bundle,
    resolve_oracle_benchmark_review_profiles,
    run_oracle_benchmark_followup,
    run_oracle_benchmark_followup_background_worker,
    run_oracle_benchmark_upload,
    save_qualitysuite_winner_run_settings,
)


def _format_size_compact(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    value = float(num_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{num_bytes} B"


def register(app: typer.Typer) -> dict[str, object]:
    @app.command("oracle-upload")
    def bench_oracle_upload(
        path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Existing benchmark session root or upload_bundle_v1 directory.",
        ),
        mode: str = typer.Option(
            "browser",
            "--mode",
            help="Oracle execution mode: browser or dry-run.",
        ),
        model: str | None = typer.Option(
            None,
            "--model",
            help="Oracle model used for browser uploads. Defaults to the genuine model lane, or the test lane when helper-mode env is set.",
        ),
        profile: str = typer.Option(
            "all",
            "--profile",
            help="Oracle review profile to launch: quality, token, or all.",
        ),
    ) -> None:
        """Upload an existing benchmark upload bundle to Oracle."""
        try:
            target = resolve_oracle_benchmark_bundle(path)
            profiles = resolve_oracle_benchmark_review_profiles(profile)
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"Oracle benchmark upload failed: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        had_failure = False
        for review_profile in profiles:
            try:
                result = run_oracle_benchmark_upload(
                    target=target,
                    mode=mode,
                    model=model,
                    review_profile=review_profile.profile_id,
                )
            except Exception as exc:  # noqa: BLE001
                typer.secho(
                    f"Oracle benchmark upload failed for {review_profile.profile_id}: {exc}",
                    fg=typer.colors.RED,
                )
                had_failure = True
                continue

            status_color = typer.colors.GREEN if result.success else typer.colors.RED
            typer.secho(
                (
                    f"Oracle {review_profile.profile_id} benchmark upload "
                    f"{'completed' if result.success else 'failed'}."
                    + (f" Status: {result.status}." if result.status else "")
                ),
                fg=status_color,
            )
            _print_oracle_upload_summary(
                target=target,
                result=result,
                success_color=status_color,
            )
            if not result.success:
                had_failure = True
        if had_failure:
            raise typer.Exit(1)

    @app.command("oracle-followup")
    def bench_oracle_followup(
        path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Existing benchmark session root or upload_bundle_v1 directory.",
        ),
        from_run: str = typer.Option(
            "latest",
            "--from-run",
            help="Source Oracle run directory name under .oracle_upload_runs, or latest.",
        ),
        request_file: Path | None = typer.Option(
            None,
            "--request-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Optional cf.followup_request.v1 JSON override.",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Prepare the follow-up workspace and packet without calling Oracle.",
        ),
        model: str | None = typer.Option(
            None,
            "--model",
            help="Oracle model used for the follow-up continuation turn. Defaults to the genuine model lane.",
        ),
    ) -> None:
        """Build a follow-up packet from an Oracle review and continue the same chat."""
        try:
            target = resolve_oracle_benchmark_bundle(path)
            result, workspace = run_oracle_benchmark_followup(
                target=target,
                from_run=from_run,
                model=model,
                request_file=request_file,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"Oracle benchmark follow-up failed: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        status_color = typer.colors.GREEN if result.success else typer.colors.YELLOW
        typer.secho(
            (
                "Oracle benchmark follow-up "
                + ("prepared." if dry_run else ("completed." if result.success else "failed."))
            ),
            fg=status_color,
        )
        _print_oracle_followup_summary(
            target=target,
            source_run=from_run,
            result=result,
            workspace=workspace,
            success_color=status_color,
        )
        if not dry_run and not result.success:
            raise typer.Exit(1)

    @app.command("oracle-autofollowup-worker", hidden=True)
    def bench_oracle_autofollowup_worker(
        path: Path = typer.Argument(
            ...,
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Existing benchmark session root or upload_bundle_v1 directory.",
        ),
        from_run: str = typer.Option(
            ...,
            "--from-run",
            help="Source Oracle run directory name under .oracle_upload_runs.",
        ),
        model: str | None = typer.Option(
            None,
            "--model",
            help="Oracle model used for the automatic follow-up continuation turn.",
        ),
    ) -> None:
        """Internal worker that chains Oracle turn 2 after a completed benchmark review."""
        try:
            target = resolve_oracle_benchmark_bundle(path)
            result = run_oracle_benchmark_followup_background_worker(
                target=target,
                from_run=from_run,
                model=model,
            )
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"Oracle auto-follow-up worker failed: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result, indent=2, sort_keys=True))

    @app.command("speed-discover")
    def bench_speed_discover(
        gold_root: Path = typer.Option(
            DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
            "--gold-root",
            help="Root folder containing pulled gold export folders.",
        ),
        input_root: Path = typer.Option(
            DEFAULT_INPUT,
            "--input-root",
            help="Root folder containing source files used for import runs.",
        ),
        out: Path = typer.Option(
            DEFAULT_BENCH_SPEED_SUITES / "pulled_from_labelstudio.json",
            "--out",
            help="Output path for the generated speed suite manifest.",
        ),
    ) -> None:
        """Discover speed-suite targets from pulled gold exports."""
        from cookimport.bench.speed_suite import discover_speed_targets, write_speed_suite

        suite = discover_speed_targets(gold_root=gold_root, input_root=input_root)
        write_speed_suite(out, suite)

        typer.secho("Speed suite discovery complete.", fg=typer.colors.GREEN)
        typer.secho(f"Suite: {out}", fg=typer.colors.CYAN)
        typer.secho(f"Targets matched: {len(suite.targets)}", fg=typer.colors.CYAN)
        typer.secho(f"Targets unmatched: {len(suite.unmatched)}", fg=typer.colors.CYAN)
        if suite.unmatched:
            preview_rows = suite.unmatched[:5]
            typer.secho("Unmatched preview:", fg=typer.colors.YELLOW)
            for row in preview_rows:
                gold_display = str(row.get("gold_display") or row.get("gold_spans_path") or "")
                reason = str(row.get("reason") or "unmatched")
                typer.secho(f"  - {gold_display}: {reason}", fg=typer.colors.YELLOW)

    @app.command("speed-run")
    def bench_speed_run(
        suite: Path = typer.Option(
            ...,
            "--suite",
            help="Path to a speed suite JSON generated by bench speed-discover.",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_BENCH_SPEED_RUNS,
            "--out-dir",
            help="Output directory for timestamped speed suite runs.",
        ),
        scenarios: str = typer.Option(
            "stage_import,benchmark_canonical_pipelined",
            "--scenarios",
            help=(
                "Comma-separated scenario list. "
                "Allowed: stage_import, benchmark_canonical_pipelined, "
                "benchmark_all_method_multi_source."
            ),
        ),
        warmups: int = typer.Option(
            1,
            "--warmups",
            min=0,
            help="Warmup samples per target+scenario (excluded from medians).",
        ),
        repeats: int = typer.Option(
            2,
            "--repeats",
            min=1,
            help="Measured samples per target+scenario (used for medians).",
        ),
        max_targets: int | None = typer.Option(
            None,
            "--max-targets",
            min=1,
            help="Optional cap on number of targets from the suite.",
        ),
        max_parallel_tasks: int | None = typer.Option(
            None,
            "--max-parallel-tasks",
            min=1,
            help=(
                "Maximum SpeedSuite tasks dispatched concurrently. "
                "When omitted, speed-run auto-selects a bounded CPU-aware cap."
            ),
        ),
        require_process_workers: bool = typer.Option(
            False,
            "--require-process-workers/--allow-worker-fallback",
            help=(
                "Fail fast when process-based worker concurrency is unavailable in "
                "stage/all-method internals instead of falling back to subprocess/thread/serial paths."
            ),
        ),
        resume_run_dir: Path | None = typer.Option(
            None,
            "--resume-run-dir",
            help=(
                "Resume an existing speed run directory. Completed sample snapshots "
                "are reused and pending tasks continue."
            ),
        ),
        run_settings_file: Path | None = typer.Option(
            None,
            "--run-settings-file",
            help=(
                "Optional JSON file with RunSettings-shaped payload used for this speed run. "
                "When omitted, uses cookimport.json global settings."
            ),
        ),
        sequence_matcher: str | None = typer.Option(
            None,
            "--sequence-matcher",
            hidden=True,
            help=(
                "Optional override for benchmark SequenceMatcher mode "
                "(dmp only). "
                "When omitted, uses run settings value."
            ),
        ),
        include_codex_farm: bool = typer.Option(
            False,
            "--include-codex-farm/--no-include-codex-farm",
            help=(
                "Include Codex Farm recipe pipeline permutations in all-method scenarios."
            ),
        ),
        speedsuite_codex_farm_confirmation: str | None = typer.Option(
            None,
            "--speedsuite-codex-farm-confirmation",
            help=(
                "Required with --include-codex-farm. Set to "
                "I_HAVE_EXPLICIT_USER_CONFIRMATION only after explicit positive user approval."
            ),
        ),
        codex_farm_model: str | None = typer.Option(
            None,
            "--codex-farm-model",
            help="Optional Codex Farm model override (blank uses pipeline defaults).",
        ),
        codex_farm_reasoning_effort: Annotated[
            str | None,
            typer.Option(
                "--codex-farm-thinking-effort",
                "--codex-farm-reasoning-effort",
                help=(
                    "Codex Farm thinking effort override "
                    "(none, minimal, low, medium, high, xhigh). "
                    "Blank uses pipeline defaults."
                ),
            ),
        ] = None,
    ) -> None:
        """Run deterministic speed scenarios for a speed suite."""
        from cookimport.bench.speed_runner import (
            parse_speed_scenarios,
            run_speed_suite,
        )
        from cookimport.bench.speed_suite import (
            load_speed_suite,
            validate_speed_suite,
        )

        suite = _unwrap_typer_option_default(suite)
        out_dir = _unwrap_typer_option_default(out_dir)
        scenarios = _unwrap_typer_option_default(scenarios)
        warmups = _unwrap_typer_option_default(warmups)
        repeats = _unwrap_typer_option_default(repeats)
        max_targets = _unwrap_typer_option_default(max_targets)
        max_parallel_tasks = _unwrap_typer_option_default(max_parallel_tasks)
        require_process_workers = _unwrap_typer_option_default(require_process_workers)
        resume_run_dir = _unwrap_typer_option_default(resume_run_dir)
        run_settings_file = _unwrap_typer_option_default(run_settings_file)
        sequence_matcher = _unwrap_typer_option_default(sequence_matcher)
        include_codex_farm = _unwrap_typer_option_default(include_codex_farm)
        speedsuite_codex_farm_confirmation = _unwrap_typer_option_default(
            speedsuite_codex_farm_confirmation
        )
        codex_farm_model = _unwrap_typer_option_default(codex_farm_model)
        codex_farm_reasoning_effort = _unwrap_typer_option_default(codex_farm_reasoning_effort)
        codex_farm_confirmed = _resolve_speedsuite_codex_farm_confirmation(
            include_codex_farm=include_codex_farm,
            confirmation=speedsuite_codex_farm_confirmation,
        )
        _enforce_live_bench_speed_codex_guardrails(
            include_codex_farm=include_codex_farm,
        )

        try:
            loaded_suite = load_speed_suite(suite)
        except Exception as exc:  # noqa: BLE001
            _fail(f"Failed to load speed suite: {exc}")

        validation_errors = validate_speed_suite(loaded_suite, repo_root=REPO_ROOT)
        if validation_errors:
            typer.secho("Speed suite validation errors:", fg=typer.colors.RED)
            for error in validation_errors:
                typer.secho(f"  - {error}", fg=typer.colors.RED)
            raise typer.Exit(1)

        try:
            selected_scenarios = parse_speed_scenarios(scenarios)
        except ValueError as exc:
            _fail(str(exc))

        if max_parallel_tasks is not None:
            try:
                max_parallel_tasks = int(max_parallel_tasks)
            except (TypeError, ValueError):
                _fail("--max-parallel-tasks must be an integer >= 1.")
            if max_parallel_tasks < 1:
                _fail("--max-parallel-tasks must be >= 1 when provided.")

        if resume_run_dir is not None:
            if not resume_run_dir.exists() or not resume_run_dir.is_dir():
                _fail(f"--resume-run-dir must point to an existing directory: {resume_run_dir}")

        run_settings_payload: dict[str, Any]
        if run_settings_file is not None:
            if not run_settings_file.exists() or not run_settings_file.is_file():
                _fail(f"Run settings file not found: {run_settings_file}")
            try:
                loaded_payload = json.loads(run_settings_file.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                _fail(f"Failed to read run settings file: {exc}")
            if not isinstance(loaded_payload, dict):
                _fail("Run settings file must contain a JSON object.")
            run_settings_payload = dict(loaded_payload)
            run_settings_context = "bench speed-run settings file"
        else:
            run_settings_payload = _run_settings_payload_from_settings(_load_settings())
            run_settings_context = "bench speed-run global settings"

        if codex_farm_model is not None:
            run_settings_payload["codex_farm_model"] = str(codex_farm_model).strip() or None
        if codex_farm_reasoning_effort is not None:
            try:
                normalized_effort = normalize_codex_reasoning_effort(codex_farm_reasoning_effort)
            except ValueError as exc:
                _fail(f"--codex-farm-thinking-effort invalid: {exc}")
            run_settings_payload["codex_farm_reasoning_effort"] = normalized_effort

        run_settings = RunSettings.from_dict(
            run_settings_payload,
            warn_context=run_settings_context,
        )
        speed_codex_decision = resolve_codex_execution_policy(
            "bench_speed_run",
            run_settings.to_run_config_dict(),
            include_codex_farm_requested=include_codex_farm,
            explicit_confirmation_granted=codex_farm_confirmed,
        )
        typer.secho(
            "Run settings: "
            f"{run_settings.summary()} (hash {run_settings.short_hash()})",
            fg=typer.colors.CYAN,
        )
        _print_codex_decision(speed_codex_decision)
        if include_codex_farm:
            _ensure_codex_farm_cmd_available(run_settings.codex_farm_cmd)
            include_effective, warning = _resolve_all_method_codex_choice(True)
            if warning is not None:
                typer.secho(warning, fg=typer.colors.YELLOW)
            elif include_effective:
                typer.secho("Codex Farm permutations: enabled.", fg=typer.colors.CYAN)

        speed_run_timeseries_path = _processing_timeseries_history_path(
            root=out_dir,
            scope="bench_speed_run",
            source_name=loaded_suite.name,
        )
        try:
            speed_run_root = _run_with_progress_status(
                initial_status="Running bench speed suite...",
                progress_prefix="Bench speed",
                telemetry_path=speed_run_timeseries_path,
                run=lambda update_progress: run_speed_suite(
                    loaded_suite,
                    out_dir,
                    scenarios=selected_scenarios,
                    warmups=warmups,
                    repeats=repeats,
                    max_targets=max_targets,
                    max_parallel_tasks=max_parallel_tasks,
                    require_process_workers=bool(require_process_workers),
                    resume_run_dir=resume_run_dir,
                    run_settings=run_settings,
                    include_codex_farm_requested=include_codex_farm,
                    codex_farm_confirmed=codex_farm_confirmed,
                    progress_callback=update_progress,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))
            return

        typer.secho("Speed suite run complete.", fg=typer.colors.GREEN)
        typer.secho(f"Run: {speed_run_root}", fg=typer.colors.CYAN)
        typer.secho(f"Report: {speed_run_root / 'report.md'}", fg=typer.colors.CYAN)
        typer.secho(f"Summary: {speed_run_root / 'summary.json'}", fg=typer.colors.CYAN)
        typer.secho(
            f"Processing telemetry: {speed_run_timeseries_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )

    @app.command("speed-compare")
    def bench_speed_compare(
        baseline: Path = typer.Option(
            ...,
            "--baseline",
            help="Baseline speed run directory (contains summary.json).",
        ),
        candidate: Path = typer.Option(
            ...,
            "--candidate",
            help="Candidate speed run directory (contains summary.json).",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_BENCH_SPEED_COMPARISONS,
            "--out-dir",
            help="Output directory for timestamped comparison reports.",
        ),
        regression_pct: float = typer.Option(
            5.0,
            "--regression-pct",
            min=0.0,
            help="Percent threshold required (with absolute floor) to mark regression.",
        ),
        absolute_seconds_floor: float = typer.Option(
            0.5,
            "--absolute-seconds-floor",
            min=0.0,
            help="Absolute seconds increase required to mark regression.",
        ),
        fail_on_regression: bool = typer.Option(
            False,
            "--fail-on-regression/--no-fail-on-regression",
            help="Return non-zero exit when comparison verdict is FAIL.",
        ),
        allow_settings_mismatch: bool = typer.Option(
            False,
            "--allow-settings-mismatch/--no-allow-settings-mismatch",
            help=(
                "Allow PASS/FAIL timing verdicts even when baseline/candidate run settings "
                "hashes differ."
            ),
        ),
    ) -> None:
        """Compare baseline and candidate speed runs and gate regressions."""
        from cookimport.bench.speed_compare import (
            SpeedThresholds,
            compare_speed_runs,
            format_speed_compare_report,
        )

        baseline = _unwrap_typer_option_default(baseline)
        candidate = _unwrap_typer_option_default(candidate)
        out_dir = _unwrap_typer_option_default(out_dir)
        regression_pct = _unwrap_typer_option_default(regression_pct)
        absolute_seconds_floor = _unwrap_typer_option_default(absolute_seconds_floor)
        fail_on_regression = _unwrap_typer_option_default(fail_on_regression)
        allow_settings_mismatch = _unwrap_typer_option_default(allow_settings_mismatch)

        if not baseline.exists() or not baseline.is_dir():
            _fail(f"Baseline run directory not found: {baseline}")
        if not candidate.exists() or not candidate.is_dir():
            _fail(f"Candidate run directory not found: {candidate}")

        thresholds = SpeedThresholds(
            regression_pct=regression_pct,
            absolute_seconds_floor=absolute_seconds_floor,
        )
        try:
            comparison = compare_speed_runs(
                baseline_run_dir=baseline,
                candidate_run_dir=candidate,
                thresholds=thresholds,
                allow_settings_mismatch=allow_settings_mismatch,
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))
            return

        comparison_root = out_dir / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        comparison_root.mkdir(parents=True, exist_ok=True)
        comparison_json_path = comparison_root / "comparison.json"
        comparison_md_path = comparison_root / "comparison.md"
        comparison_json_path.write_text(
            json.dumps(comparison, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        comparison_md_path.write_text(
            format_speed_compare_report(comparison),
            encoding="utf-8",
        )

        verdict = str((comparison.get("overall") or {}).get("verdict") or "UNKNOWN").upper()
        color = typer.colors.GREEN if verdict == "PASS" else typer.colors.RED
        typer.secho("Comparison complete.", fg=typer.colors.GREEN)
        typer.secho(f"Overall verdict: {verdict}", fg=color)
        typer.secho(f"Report: {comparison_md_path}", fg=typer.colors.CYAN)
        typer.secho(f"JSON: {comparison_json_path}", fg=typer.colors.CYAN)

        if fail_on_regression and verdict == "FAIL":
            raise typer.Exit(1)

    @app.command("gc")
    def bench_gc(
        golden_root: Path = typer.Option(
            DEFAULT_GOLDEN,
            "--golden-root",
            help="Golden root containing benchmark artifacts (default: data/golden).",
        ),
        output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--output-root",
            help="Output root used to resolve benchmark history CSV (default: data/output).",
        ),
        keep_full_runs: int = typer.Option(
            2,
            "--keep-full-runs",
            min=0,
            help="Keep this many newest benchmark run roots in full form.",
        ),
        keep_full_days: int = typer.Option(
            14,
            "--keep-full-days",
            min=0,
            help="Keep full benchmark run roots newer than this many days.",
        ),
        drop_speed_artifacts: bool = typer.Option(
            False,
            "--drop-speed-artifacts/--keep-speed-artifacts",
            help=(
                "Prune speed run roots regardless of keep policy. "
                "Use with caution."
            ),
        ),
        include_labelstudio_benchmark: bool = typer.Option(
            True,
            "--include-labelstudio-benchmark/--no-include-labelstudio-benchmark",
            help=(
                "Also prune timestamped Label Studio benchmark roots under "
                "`data/golden/benchmark-vs-golden/*` while keeping only the newest "
                "`--keep-labelstudio-runs` roots plus pinned runs."
            ),
        ),
        keep_labelstudio_runs: int = typer.Option(
            5,
            "--keep-labelstudio-runs",
            min=0,
            help="Keep this many newest run roots under `data/golden/benchmark-vs-golden/`.",
        ),
        wipe_output_runs: bool = typer.Option(
            True,
            "--wipe-output-runs/--keep-output-runs",
            help=(
                "Delete all timestamped run roots directly under `--output-root/` while leaving "
                "non-run folders such as `history/dashboard` untouched."
            ),
        ),
        prune_benchmark_processed_outputs: bool = typer.Option(
            False,
            "--prune-benchmark-processed-outputs/--keep-benchmark-processed-outputs",
            help=(
                "Legacy mode: when `--keep-output-runs` is set, also prune matching processed "
                "output roots under `--output-root/<run_id>/` when confirmed by CSV history."
            ),
        ),
        dry_run: bool = typer.Option(
            True,
            "--dry-run/--apply",
            help="Preview only by default; pass --apply to delete artifacts.",
        ),
    ) -> None:
        """Garbage-collect old benchmark artifacts without mutating history CSV."""
        from cookimport.bench.artifact_gc import run_benchmark_gc

        result = run_benchmark_gc(
            golden_root=golden_root,
            output_root=output_root,
            keep_full_runs=keep_full_runs,
            keep_full_days=keep_full_days,
            dry_run=dry_run,
            drop_speed_artifacts=drop_speed_artifacts,
            include_labelstudio_benchmark=include_labelstudio_benchmark,
            keep_labelstudio_runs=keep_labelstudio_runs,
            wipe_output_runs=wipe_output_runs,
            prune_benchmark_processed_outputs=prune_benchmark_processed_outputs,
        )

        mode = "Dry Run" if result.dry_run else "Apply"
        typer.secho(f"Benchmark GC {mode}", fg=typer.colors.CYAN)
        typer.echo(
            "policy: "
            f"keep_full_runs={result.keep_full_runs} "
            f"keep_full_days={result.keep_full_days} "
            f"drop_speed_artifacts={str(result.drop_speed_artifacts).lower()} "
            f"include_labelstudio_benchmark={str(result.include_labelstudio_benchmark).lower()} "
            f"keep_labelstudio_runs={result.keep_labelstudio_runs} "
            f"wipe_output_runs={str(result.wipe_output_runs).lower()} "
            f"prune_benchmark_processed_outputs={str(result.prune_benchmark_processed_outputs).lower()}"
        )
        typer.echo(f"candidate run roots: {result.total_run_roots}")
        typer.echo(f"candidate output run roots: {result.total_output_run_roots}")
        typer.echo(f"full keep (policy): {result.policy_kept_run_roots}")
        if result.pinned_kept_run_roots:
            typer.echo(f"pinned keep (sentinel): {result.pinned_kept_run_roots}")
        typer.echo(f"kept (unconfirmed durable history): {result.skipped_unconfirmed_run_roots}")
        typer.echo(
            "prune: "
            f"{result.pruned_run_roots} "
            f"(quality={result.pruned_quality_run_roots}, "
                f"speed={result.pruned_speed_run_roots}, "
                f"labelstudio={result.pruned_labelstudio_run_roots})"
        )
        typer.echo(f"prune output runs: {result.pruned_output_run_roots}")
        reclaim_parts = [_format_size_compact(result.reclaimed_bytes)]
        if result.reclaimed_output_run_bytes:
            reclaim_parts.append(
                f"+ output_runs={_format_size_compact(result.reclaimed_output_run_bytes)}"
            )
        if result.reclaimed_processed_output_bytes:
            reclaim_parts.append(
                f"+ processed_outputs={_format_size_compact(result.reclaimed_processed_output_bytes)}"
            )
        typer.echo(f"estimated reclaim: {' '.join(reclaim_parts)}")
        typer.echo(f"history rows scanned: {result.history_rows_scanned}")
        typer.echo(f"history rows updated: {result.history_rows_updated}")
        typer.echo(f"history rows pruned: {result.history_rows_pruned}")
        typer.echo("history csv mutation: disabled")

        if result.history_backup_path is not None:
            typer.echo(f"wrote backup: {result.history_backup_path}")

        if result.warnings:
            typer.secho(
                f"Warnings ({len(result.warnings)}):",
                fg=typer.colors.YELLOW,
            )
            for warning in result.warnings[:10]:
                typer.secho(f"  - {warning}", fg=typer.colors.YELLOW)

        if result.dry_run:
            typer.secho("no files changed (dry-run)", fg=typer.colors.CYAN)
        else:
            typer.secho("done", fg=typer.colors.GREEN)

    @app.command("pin")
    def bench_pin(
        path: Annotated[Path, typer.Argument(help="Run root to pin (kept from bench gc).")],
        note: Annotated[str | None, typer.Option("--note", help="Optional note written to the pin file.")] = None,
    ) -> None:
        """Pin a run root by writing a `.gc_keep.*.txt` sentinel file."""
        resolved = path.expanduser()
        if not resolved.exists() or not resolved.is_dir():
            _fail(f"Pin target must be an existing directory: {resolved}")

        timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        sentinel_path = resolved / f".gc_keep.{timestamp}.txt"
        body = (note or "").strip()
        if not body:
            body = "Pinned by cookimport bench pin."
        sentinel_path.write_text(body.rstrip() + "\n", encoding="utf-8")
        typer.secho(f"Pinned: {resolved}", fg=typer.colors.GREEN)
        typer.secho(f"Sentinel: {sentinel_path}", fg=typer.colors.CYAN)

    @app.command("unpin")
    def bench_unpin(
        path: Annotated[Path, typer.Argument(help="Run root to unpin (removes `.gc_keep*` sentinels).")],
    ) -> None:
        """Unpin a run root by removing `.gc_keep*` sentinel files."""
        resolved = path.expanduser()
        if not resolved.exists() or not resolved.is_dir():
            _fail(f"Unpin target must be an existing directory: {resolved}")

        removed = 0
        try:
            for child in resolved.iterdir():
                if child.name.startswith(".gc_keep"):
                    try:
                        child.unlink()
                        removed += 1
                    except OSError as exc:
                        typer.secho(f"Failed to remove {child}: {exc}", fg=typer.colors.YELLOW)
        except OSError as exc:
            _fail(f"Unable to scan directory for sentinels: {resolved} ({exc})")

        if removed:
            typer.secho(f"Unpinned: {resolved} (removed {removed} sentinel file(s))", fg=typer.colors.GREEN)
        else:
            typer.secho(f"No `.gc_keep*` sentinels found in: {resolved}", fg=typer.colors.YELLOW)

    @app.command("quality-discover")
    def bench_quality_discover(
        gold_root: Path = typer.Option(
            DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
            "--gold-root",
            help="Root folder containing pulled gold export folders.",
        ),
        input_root: Path = typer.Option(
            DEFAULT_INPUT,
            "--input-root",
            help="Root folder containing source files used for import runs.",
        ),
        out: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_SUITES / "pulled_representative.json",
            "--out",
            help="Output path for the generated quality suite manifest.",
        ),
        max_targets: int | None = typer.Option(
            None,
            "--max-targets",
            min=1,
            help=(
                "Optional cap for selected targets "
                "(curated CUTDOWN focus IDs when available, representative fallback otherwise)."
            ),
        ),
        seed: int = typer.Option(
            42,
            "--seed",
            help="Deterministic selection seed recorded in suite metadata.",
        ),
        formats: str | None = typer.Option(
            None,
            "--formats",
            help=(
                "Optional comma-separated source extensions to include "
                "(for example: .pdf,.epub)."
            ),
        ),
        prefer_curated: bool = typer.Option(
            True,
            "--prefer-curated/--no-prefer-curated",
            help=(
                "Prefer curated CUTDOWN focus IDs when available. "
                "Disable to select representative targets (all matched when --max-targets is omitted)."
            ),
        ),
    ) -> None:
        """Discover deterministic quality-suite targets from pulled gold exports."""
        from cookimport.bench.quality_suite import (
            discover_quality_suite,
            write_quality_suite,
        )

        gold_root = _unwrap_typer_option_default(gold_root)
        input_root = _unwrap_typer_option_default(input_root)
        out = _unwrap_typer_option_default(out)
        max_targets = _unwrap_typer_option_default(max_targets)
        seed = _unwrap_typer_option_default(seed)
        formats = _unwrap_typer_option_default(formats)
        prefer_curated = _unwrap_typer_option_default(prefer_curated)

        suite_kwargs: dict[str, Any] = {}
        if not prefer_curated:
            suite_kwargs["preferred_target_ids"] = None
        parsed_formats = _parse_quality_discover_formats(formats)
        if parsed_formats:
            suite_kwargs["formats"] = parsed_formats
        suite = discover_quality_suite(
            gold_root=gold_root,
            input_root=input_root,
            max_targets=max_targets,
            seed=seed,
            **suite_kwargs,
        )
        write_quality_suite(out, suite)

        typer.secho("Quality suite discovery complete.", fg=typer.colors.GREEN)
        typer.secho(f"Suite: {out}", fg=typer.colors.CYAN)
        typer.secho(f"Targets matched: {len(suite.targets)}", fg=typer.colors.CYAN)
        typer.secho(
            f"Targets selected: {len(suite.selected_target_ids)}",
            fg=typer.colors.CYAN,
        )
        format_counts = (
            suite.selection.get("format_counts")
            if isinstance(suite.selection, dict)
            else None
        )
        if isinstance(format_counts, dict) and format_counts:
            rendered = ", ".join(
                f"{key}={value}" for key, value in sorted(format_counts.items())
            )
            typer.secho(f"Matched formats: {rendered}", fg=typer.colors.CYAN)
        selected_format_counts = (
            suite.selection.get("selected_format_counts")
            if isinstance(suite.selection, dict)
            else None
        )
        if isinstance(selected_format_counts, dict) and selected_format_counts:
            rendered = ", ".join(
                f"{key}={value}" for key, value in sorted(selected_format_counts.items())
            )
            typer.secho(f"Selected formats: {rendered}", fg=typer.colors.CYAN)
        typer.secho(f"Targets unmatched: {len(suite.unmatched)}", fg=typer.colors.CYAN)
        if suite.unmatched:
            preview_rows = suite.unmatched[:5]
            typer.secho("Unmatched preview:", fg=typer.colors.YELLOW)
            for row in preview_rows:
                gold_display = str(
                    row.get("gold_display") or row.get("gold_spans_path") or ""
                )
                reason = str(row.get("reason") or "unmatched")
                typer.secho(f"  - {gold_display}: {reason}", fg=typer.colors.YELLOW)

    @app.command("quality-run")
    def bench_quality_run(
        suite: Path = typer.Option(
            ...,
            "--suite",
            help="Path to a quality suite JSON generated by bench quality-discover.",
        ),
        experiments_file: Path = typer.Option(
            ...,
            "--experiments-file",
            help="Path to JSON experiment definitions for this quality run.",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_RUNS,
            "--out-dir",
            help="Output directory for timestamped quality suite runs.",
        ),
        resume_run_dir: Path | None = typer.Option(
            None,
            "--resume-run-dir",
            help=(
                "Resume an existing quality run directory. Completed experiments are reused "
                "from on-disk checkpoints and skipped."
            ),
        ),
        base_run_settings_file: Path | None = typer.Option(
            None,
            "--base-run-settings-file",
            help=(
                "Optional JSON file with base RunSettings payload for all experiments. "
                "When omitted, uses experiments.base_run_settings_file or cookimport.json."
            ),
        ),
        search_strategy: str = typer.Option(
            "race",
            "--search-strategy",
            help=(
                "Experiment search strategy: 'race' prunes the all-method config grid in rounds; "
                "'exhaustive' runs the full grid across all selected targets."
            ),
        ),
        race_probe_targets: int = typer.Option(
            2,
            "--race-probe-targets",
            min=1,
            help="Number of target sources used in the first pruning round when --search-strategy=race.",
        ),
        race_mid_targets: int = typer.Option(
            4,
            "--race-mid-targets",
            min=1,
            help="Number of target sources used in the second pruning round when --search-strategy=race.",
        ),
        race_keep_ratio: float = typer.Option(
            0.35,
            "--race-keep-ratio",
            min=0.01,
            max=1.0,
            help="Fraction of configs kept after the probe round when --search-strategy=race.",
        ),
        race_finalists: int = typer.Option(
            64,
            "--race-finalists",
            min=1,
            help="Minimum finalist config count preserved for the full-suite round in race mode.",
        ),
        max_parallel_experiments: int | None = typer.Option(
            None,
            "--max-parallel-experiments",
            help=(
                "Maximum number of quality experiments executed concurrently. "
                "Each experiment still uses all-method internal scheduling. "
                "When omitted, quality-run auto-selects a CPU-aware adaptive cap."
            ),
        ),
        require_process_workers: bool = typer.Option(
            False,
            "--require-process-workers/--allow-worker-fallback",
            help=(
                "Fail fast when process-based all-method config workers are unavailable "
                "instead of degrading to fallback worker backends."
            ),
        ),
        include_deterministic_sweeps: bool = typer.Option(
            False,
            "--include-deterministic-sweeps/--no-include-deterministic-sweeps",
            help=(
                "Enable deterministic all-method option sweeps during quality-run "
                "(section detector, multi-recipe splitting, ingredient missing-unit policy, "
                "instruction step segmentation, time/temp/yield)."
            ),
        ),
        include_codex_farm: bool = typer.Option(
            False,
            "--include-codex-farm/--no-include-codex-farm",
            help=(
                "Include Codex Farm recipe pipeline permutations in all-method runs."
            ),
        ),
        qualitysuite_codex_farm_confirmation: str | None = typer.Option(
            None,
            "--qualitysuite-codex-farm-confirmation",
            help=(
                "Required with --include-codex-farm. Set to "
                "I_HAVE_EXPLICIT_USER_CONFIRMATION only after explicit positive user approval."
            ),
        ),
        codex_farm_model: str | None = typer.Option(
            None,
            "--codex-farm-model",
            help="Optional Codex Farm model override applied to all experiments.",
        ),
        codex_farm_reasoning_effort: Annotated[
            str | None,
            typer.Option(
                "--codex-farm-thinking-effort",
                "--codex-farm-reasoning-effort",
                help=(
                    "Codex Farm thinking effort override applied to all experiments "
                    "(none, minimal, low, medium, high, xhigh)."
                ),
            ),
        ] = None,
        io_pace_every_writes: int = typer.Option(
            200,
            "--io-pace-every-writes",
            min=0,
            help=(
                "Optional disk I/O pacing: sleep briefly every N output file writes to "
                "reduce WSL host disk-thrash during QualitySuite runs (0 disables). "
                "Default: 200."
            ),
        ),
        io_pace_sleep_ms: float = typer.Option(
            5.0,
            "--io-pace-sleep-ms",
            min=0.0,
            help=(
                "Optional disk I/O pacing: sleep duration in milliseconds used with "
                "--io-pace-every-writes (0 disables). Default: 5."
            ),
        ),
        qualitysuite_agent_bridge: bool = typer.Option(
            True,
            "--qualitysuite-agent-bridge/--no-qualitysuite-agent-bridge",
            help=(
                "Write an agent_compare_control bundle for this quality run "
                "(Compare & Control insights + ready JSONL requests)."
            ),
        ),
        qualitysuite_agent_bridge_since_days: int | None = typer.Option(
            None,
            "--qualitysuite-agent-bridge-since-days",
            help=(
                "Optional compare-control history window for bridge generation. "
                "When omitted, uses all available history."
            ),
        ),
        qualitysuite_agent_bridge_output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--qualitysuite-agent-bridge-output-root",
            help="Output root used when loading compare-control history for the bridge.",
        ),
        qualitysuite_agent_bridge_golden_root: Path = typer.Option(
            DEFAULT_GOLDEN,
            "--qualitysuite-agent-bridge-golden-root",
            help="Golden root used when loading compare-control history for the bridge.",
        ),
    ) -> None:
        """Run all-method quality experiments for a quality suite."""
        from cookimport.bench.quality_runner import run_quality_suite
        from cookimport.bench.quality_suite import (
            load_quality_suite,
            validate_quality_suite,
        )

        suite = _unwrap_typer_option_default(suite)
        experiments_file = _unwrap_typer_option_default(experiments_file)
        out_dir = _unwrap_typer_option_default(out_dir)
        resume_run_dir = _unwrap_typer_option_default(resume_run_dir)
        base_run_settings_file = _unwrap_typer_option_default(base_run_settings_file)
        search_strategy = _unwrap_typer_option_default(search_strategy)
        race_probe_targets = _unwrap_typer_option_default(race_probe_targets)
        race_mid_targets = _unwrap_typer_option_default(race_mid_targets)
        race_keep_ratio = _unwrap_typer_option_default(race_keep_ratio)
        race_finalists = _unwrap_typer_option_default(race_finalists)
        max_parallel_experiments = _unwrap_typer_option_default(max_parallel_experiments)
        require_process_workers = _unwrap_typer_option_default(require_process_workers)
        if max_parallel_experiments is not None:
            try:
                max_parallel_experiments = int(max_parallel_experiments)
            except (TypeError, ValueError):
                _fail("--max-parallel-experiments must be an integer >= 1.")
            if max_parallel_experiments < 1:
                _fail("--max-parallel-experiments must be >= 1 when provided.")
        include_deterministic_sweeps = _unwrap_typer_option_default(
            include_deterministic_sweeps
        )
        include_codex_farm = _unwrap_typer_option_default(include_codex_farm)
        qualitysuite_codex_farm_confirmation = _unwrap_typer_option_default(
            qualitysuite_codex_farm_confirmation
        )
        codex_farm_model = _unwrap_typer_option_default(codex_farm_model)
        codex_farm_reasoning_effort = _unwrap_typer_option_default(codex_farm_reasoning_effort)
        io_pace_every_writes = _unwrap_typer_option_default(io_pace_every_writes)
        io_pace_sleep_ms = _unwrap_typer_option_default(io_pace_sleep_ms)
        qualitysuite_agent_bridge = _unwrap_typer_option_default(
            qualitysuite_agent_bridge
        )
        qualitysuite_agent_bridge_since_days = _unwrap_typer_option_default(
            qualitysuite_agent_bridge_since_days
        )
        qualitysuite_agent_bridge_output_root = _unwrap_typer_option_default(
            qualitysuite_agent_bridge_output_root
        )
        qualitysuite_agent_bridge_golden_root = _unwrap_typer_option_default(
            qualitysuite_agent_bridge_golden_root
        )
        try:
            io_pace_every_writes = int(io_pace_every_writes)
        except (TypeError, ValueError):
            _fail("--io-pace-every-writes must be an integer >= 0.")
        try:
            io_pace_sleep_ms = float(io_pace_sleep_ms)
        except (TypeError, ValueError):
            _fail("--io-pace-sleep-ms must be a number >= 0.")
        if io_pace_every_writes < 0:
            _fail("--io-pace-every-writes must be >= 0.")
        if io_pace_sleep_ms < 0:
            _fail("--io-pace-sleep-ms must be >= 0.")
        if include_codex_farm:
            _fail(
                "bench quality-run no longer permits --include-codex-farm. "
                "QualitySuite is deterministic-only."
            )
        if qualitysuite_codex_farm_confirmation is not None:
            _fail(
                "bench quality-run no longer accepts "
                "--qualitysuite-codex-farm-confirmation because Codex Farm is disabled "
                "for QualitySuite."
            )
        if codex_farm_model is not None:
            _fail(
                "bench quality-run no longer accepts --codex-farm-model because "
                "QualitySuite forbids Codex Farm."
            )
        if codex_farm_reasoning_effort is not None:
            _fail(
                "bench quality-run no longer accepts Codex Farm thinking/reasoning "
                "effort overrides because QualitySuite forbids Codex Farm."
            )
        codex_farm_confirmed = False
        _print_codex_decision(
            resolve_codex_execution_policy(
                "bench_quality_run",
                {},
                include_codex_farm_requested=False,
                explicit_confirmation_granted=codex_farm_confirmed,
            )
        )
        if resume_run_dir is not None:
            if not resume_run_dir.exists() or not resume_run_dir.is_dir():
                _fail(f"--resume-run-dir must point to an existing directory: {resume_run_dir}")
        io_pace_env_key_every = "COOKIMPORT_IO_PACE_EVERY_WRITES"
        io_pace_env_key_sleep = "COOKIMPORT_IO_PACE_SLEEP_MS"
        io_pace_prev_every = os.environ.get(io_pace_env_key_every)
        io_pace_prev_sleep = os.environ.get(io_pace_env_key_sleep)
        io_pace_restore_needed = False
        try:
            io_pace_restore_needed = True
            if io_pace_every_writes > 0 and io_pace_sleep_ms > 0:
                os.environ[io_pace_env_key_every] = str(io_pace_every_writes)
                os.environ[io_pace_env_key_sleep] = str(io_pace_sleep_ms)
            else:
                # Explicitly disable pacing even if inherited env vars exist.
                os.environ.pop(io_pace_env_key_every, None)
                os.environ.pop(io_pace_env_key_sleep, None)

            if not experiments_file.exists() or not experiments_file.is_file():
                _fail(f"Experiments file not found: {experiments_file}")

            try:
                loaded_suite = load_quality_suite(suite)
            except Exception as exc:  # noqa: BLE001
                _fail(f"Failed to load quality suite: {exc}")

            validation_errors = validate_quality_suite(loaded_suite, repo_root=REPO_ROOT)
            if validation_errors:
                typer.secho("Quality suite validation errors:", fg=typer.colors.RED)
                for error in validation_errors:
                    typer.secho(f"  - {error}", fg=typer.colors.RED)
                raise typer.Exit(1)

            quality_run_timeseries_path = _processing_timeseries_history_path(
                root=out_dir,
                scope="bench_quality_run",
                source_name=loaded_suite.name,
            )
            try:
                try:
                    normalized_effort = normalize_codex_reasoning_effort(codex_farm_reasoning_effort)
                except ValueError as exc:
                    _fail(f"--codex-farm-thinking-effort invalid: {exc}")
                quality_run_root = _run_with_progress_status(
                    initial_status="Running bench quality suite...",
                    progress_prefix="Bench quality",
                    telemetry_path=quality_run_timeseries_path,
                    run=lambda update_progress: run_quality_suite(
                        loaded_suite,
                        out_dir,
                        experiments_file=experiments_file,
                        base_run_settings_file=base_run_settings_file,
                        search_strategy=search_strategy,
                        race_probe_targets=race_probe_targets,
                        race_mid_targets=race_mid_targets,
                        race_keep_ratio=race_keep_ratio,
                        race_finalists=race_finalists,
                        max_parallel_experiments=max_parallel_experiments,
                        require_process_workers=bool(require_process_workers),
                        resume_run_dir=resume_run_dir,
                        include_deterministic_sweeps_requested=include_deterministic_sweeps,
                        include_codex_farm_requested=include_codex_farm,
                        codex_farm_confirmed=codex_farm_confirmed,
                        codex_farm_model=str(codex_farm_model).strip() or None
                        if codex_farm_model is not None
                        else None,
                        codex_farm_reasoning_effort=normalized_effort,
                        progress_callback=update_progress,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _fail(str(exc))
                return
        finally:
            if io_pace_restore_needed:
                if io_pace_prev_every is None:
                    os.environ.pop(io_pace_env_key_every, None)
                else:
                    os.environ[io_pace_env_key_every] = io_pace_prev_every
                if io_pace_prev_sleep is None:
                    os.environ.pop(io_pace_env_key_sleep, None)
                else:
                    os.environ[io_pace_env_key_sleep] = io_pace_prev_sleep

        typer.secho("Quality suite run complete.", fg=typer.colors.GREEN)
        typer.secho(f"Run: {quality_run_root}", fg=typer.colors.CYAN)
        typer.secho(f"Report: {quality_run_root / 'report.md'}", fg=typer.colors.CYAN)
        typer.secho(f"Summary: {quality_run_root / 'summary.json'}", fg=typer.colors.CYAN)
        typer.secho(
            f"Processing telemetry: {quality_run_timeseries_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        if bool(qualitysuite_agent_bridge):
            bridge_dir, bridge_warning = _write_qualitysuite_agent_bridge_bundle_for_run(
                run_root=quality_run_root,
                output_root=Path(qualitysuite_agent_bridge_output_root),
                golden_root=Path(qualitysuite_agent_bridge_golden_root),
                since_days=qualitysuite_agent_bridge_since_days,
            )
            if bridge_dir is not None:
                typer.secho(
                    f"Agent bridge: {bridge_dir}",
                    fg=typer.colors.CYAN,
                )
            elif bridge_warning:
                typer.secho(
                    f"Agent bridge skipped: {bridge_warning}",
                    fg=typer.colors.YELLOW,
                )

    @app.command("quality-lightweight-series")
    def bench_quality_lightweight_series(
        gold_root: Path = typer.Option(
            DEFAULT_GOLDEN_PULLED_FROM_LABELSTUDIO,
            "--gold-root",
            help="Root folder containing pulled gold export folders.",
        ),
        input_root: Path = typer.Option(
            DEFAULT_INPUT,
            "--input-root",
            help="Root folder containing source files used for import runs.",
        ),
        profile_file: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_PROFILE,
            "--profile-file",
            help="Versioned lightweight-series profile JSON.",
        ),
        experiments_file: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_EXPERIMENTS,
            "--experiments-file",
            help="Experiments JSON used to resolve candidate patches.",
        ),
        thresholds_file: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_THRESHOLDS,
            "--thresholds-file",
            help="Thresholds JSON used for seed/fold contracts.",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_LIGHTWEIGHT_SERIES,
            "--out-dir",
            help="Output directory for timestamped lightweight series runs.",
        ),
        resume_series_dir: Path | None = typer.Option(
            None,
            "--resume-series-dir",
            help=(
                "Resume an existing lightweight series directory. Existing fold artifacts "
                "are reused when compatible."
            ),
        ),
        max_parallel_experiments: int | None = typer.Option(
            None,
            "--max-parallel-experiments",
            help=(
                "Maximum number of quality experiments executed concurrently inside each fold. "
                "When omitted, quality-run auto mode is used."
            ),
        ),
        require_process_workers: bool = typer.Option(
            False,
            "--require-process-workers/--allow-worker-fallback",
            help=(
                "Fail fast when process-based all-method config workers are unavailable "
                "instead of degrading to fallback worker backends."
            ),
        ),
    ) -> None:
        """Run the lightweight main-effects-first QualitySuite series."""
        _fail(QUALITY_LIGHTWEIGHT_SERIES_DISABLED_MESSAGE)

    @app.command("quality-compare")
    def bench_quality_compare(
        baseline: Path = typer.Option(
            ...,
            "--baseline",
            help="Baseline quality run directory (contains summary.json).",
        ),
        candidate: Path = typer.Option(
            ...,
            "--candidate",
            help="Candidate quality run directory (contains summary.json).",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_COMPARISONS,
            "--out-dir",
            help="Output directory for timestamped quality comparison reports.",
        ),
        baseline_experiment_id: str | None = typer.Option(
            None,
            "--baseline-experiment-id",
            help="Optional experiment id to select in the baseline run.",
        ),
        candidate_experiment_id: str | None = typer.Option(
            None,
            "--candidate-experiment-id",
            help="Optional experiment id to select in the candidate run.",
        ),
        strict_f1_drop_max: float = typer.Option(
            0.005,
            "--strict-f1-drop-max",
            min=0.0,
            help="Maximum allowed strict F1 drop before comparison FAIL.",
        ),
        practical_f1_drop_max: float = typer.Option(
            0.005,
            "--practical-f1-drop-max",
            min=0.0,
            help="Maximum allowed practical F1 drop before comparison FAIL.",
        ),
        source_success_rate_drop_max: float = typer.Option(
            0.0,
            "--source-success-rate-drop-max",
            min=0.0,
            help="Maximum allowed source-success-rate drop before comparison FAIL.",
        ),
        fail_on_regression: bool = typer.Option(
            False,
            "--fail-on-regression/--no-fail-on-regression",
            help="Return non-zero exit when comparison verdict is FAIL.",
        ),
        allow_settings_mismatch: bool = typer.Option(
            False,
            "--allow-settings-mismatch/--no-allow-settings-mismatch",
            help=(
                "Allow PASS/FAIL quality verdicts even when baseline/candidate run settings "
                "hashes differ."
            ),
        ),
        qualitysuite_agent_bridge: bool = typer.Option(
            True,
            "--qualitysuite-agent-bridge/--no-qualitysuite-agent-bridge",
            help=(
                "Write an agent_compare_control bridge bundle for this quality comparison "
                "(baseline/candidate Compare & Control insights + JSONL requests)."
            ),
        ),
        qualitysuite_agent_bridge_since_days: int | None = typer.Option(
            None,
            "--qualitysuite-agent-bridge-since-days",
            help=(
                "Optional compare-control history window for bridge generation. "
                "When omitted, uses all available history."
            ),
        ),
        qualitysuite_agent_bridge_output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--qualitysuite-agent-bridge-output-root",
            help="Output root used when loading compare-control history for the bridge.",
        ),
        qualitysuite_agent_bridge_golden_root: Path = typer.Option(
            DEFAULT_GOLDEN,
            "--qualitysuite-agent-bridge-golden-root",
            help="Golden root used when loading compare-control history for the bridge.",
        ),
    ) -> None:
        """Compare baseline and candidate quality runs and gate regressions."""
        from cookimport.bench.quality_compare import (
            QualityThresholds,
            compare_quality_runs,
            format_quality_compare_report,
        )

        baseline = _unwrap_typer_option_default(baseline)
        candidate = _unwrap_typer_option_default(candidate)
        out_dir = _unwrap_typer_option_default(out_dir)
        baseline_experiment_id = _unwrap_typer_option_default(baseline_experiment_id)
        candidate_experiment_id = _unwrap_typer_option_default(candidate_experiment_id)
        strict_f1_drop_max = _unwrap_typer_option_default(strict_f1_drop_max)
        practical_f1_drop_max = _unwrap_typer_option_default(practical_f1_drop_max)
        source_success_rate_drop_max = _unwrap_typer_option_default(
            source_success_rate_drop_max
        )
        fail_on_regression = _unwrap_typer_option_default(fail_on_regression)
        allow_settings_mismatch = _unwrap_typer_option_default(allow_settings_mismatch)
        qualitysuite_agent_bridge = _unwrap_typer_option_default(
            qualitysuite_agent_bridge
        )
        qualitysuite_agent_bridge_since_days = _unwrap_typer_option_default(
            qualitysuite_agent_bridge_since_days
        )
        qualitysuite_agent_bridge_output_root = _unwrap_typer_option_default(
            qualitysuite_agent_bridge_output_root
        )
        qualitysuite_agent_bridge_golden_root = _unwrap_typer_option_default(
            qualitysuite_agent_bridge_golden_root
        )

        if not baseline.exists() or not baseline.is_dir():
            _fail(f"Baseline run directory not found: {baseline}")
        if not candidate.exists() or not candidate.is_dir():
            _fail(f"Candidate run directory not found: {candidate}")

        thresholds = QualityThresholds(
            strict_f1_drop_max=strict_f1_drop_max,
            practical_f1_drop_max=practical_f1_drop_max,
            source_success_rate_drop_max=source_success_rate_drop_max,
        )
        try:
            comparison = compare_quality_runs(
                baseline_run_dir=baseline,
                candidate_run_dir=candidate,
                thresholds=thresholds,
                baseline_experiment_id=baseline_experiment_id,
                candidate_experiment_id=candidate_experiment_id,
                allow_settings_mismatch=allow_settings_mismatch,
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))
            return

        comparison_root = out_dir / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        comparison_root.mkdir(parents=True, exist_ok=True)
        comparison_json_path = comparison_root / "comparison.json"
        comparison_md_path = comparison_root / "comparison.md"
        comparison_json_path.write_text(
            json.dumps(comparison, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        comparison_md_path.write_text(
            format_quality_compare_report(comparison),
            encoding="utf-8",
        )

        verdict = str((comparison.get("overall") or {}).get("verdict") or "UNKNOWN").upper()
        color = typer.colors.GREEN if verdict == "PASS" else typer.colors.RED
        typer.secho("Comparison complete.", fg=typer.colors.GREEN)
        typer.secho(f"Overall verdict: {verdict}", fg=color)
        typer.secho(f"Report: {comparison_md_path}", fg=typer.colors.CYAN)
        typer.secho(f"JSON: {comparison_json_path}", fg=typer.colors.CYAN)
        if bool(qualitysuite_agent_bridge):
            bridge_dir, bridge_warning = _write_qualitysuite_agent_bridge_bundle_for_compare(
                comparison_root=comparison_root,
                comparison_payload=comparison,
                output_root=Path(qualitysuite_agent_bridge_output_root),
                golden_root=Path(qualitysuite_agent_bridge_golden_root),
                since_days=qualitysuite_agent_bridge_since_days,
            )
            if bridge_dir is not None:
                typer.secho(
                    f"Agent bridge: {bridge_dir}",
                    fg=typer.colors.CYAN,
                )
            elif bridge_warning:
                typer.secho(
                    f"Agent bridge skipped: {bridge_warning}",
                    fg=typer.colors.YELLOW,
                )

        if fail_on_regression and verdict == "FAIL":
            raise typer.Exit(1)

    @app.command("quality-leaderboard")
    def bench_quality_leaderboard(
        experiment_id: str = typer.Option(
            "baseline",
            "--experiment-id",
            help="Experiment id under <run-dir>/experiments/ to score (default: baseline).",
        ),
        run_dir: Path | None = typer.Option(
            None,
            "--run-dir",
            help=(
                "Quality run folder (contains experiments_resolved.json). "
                "When omitted, uses the latest folder under --runs-root."
            ),
        ),
        runs_root: Path = typer.Option(
            DEFAULT_BENCH_QUALITY_RUNS,
            "--runs-root",
            help="Root folder used to locate timestamped quality runs when --run-dir is omitted.",
        ),
        out_dir: Path | None = typer.Option(
            None,
            "--out-dir",
            help="Output directory for leaderboard artifacts (defaults under the run folder).",
        ),
        allow_partial_coverage: bool = typer.Option(
            False,
            "--allow-partial-coverage/--require-full-coverage",
            help=(
                "Allow ranking configs that were not evaluated on every golden-set source. "
                "By default, the leaderboard ranks full-coverage configs when possible."
            ),
        ),
        by_source_extension: bool = typer.Option(
            False,
            "--by-source-extension/--no-by-source-extension",
            help=(
                "Also emit per-format leaderboard artifacts "
                "(for example .pdf vs .epub)."
            ),
        ),
        top_n: int = typer.Option(
            10,
            "--top-n",
            min=1,
            help="How many top configs to print to stdout.",
        ),
    ) -> None:
        """Aggregate all-method variants into a single global leaderboard."""
        from cookimport.bench.quality_leaderboard import (
            build_quality_leaderboard,
            resolve_latest_timestamp_dir,
            write_quality_leaderboard_artifacts,
        )

        experiment_id = str(_unwrap_typer_option_default(experiment_id) or "baseline").strip()
        run_dir = _unwrap_typer_option_default(run_dir)
        runs_root = _unwrap_typer_option_default(runs_root)
        out_dir = _unwrap_typer_option_default(out_dir)
        allow_partial_coverage = _unwrap_typer_option_default(allow_partial_coverage)
        by_source_extension = _unwrap_typer_option_default(by_source_extension)
        top_n = _unwrap_typer_option_default(top_n)

        if run_dir is None:
            resolved = resolve_latest_timestamp_dir(runs_root)
            if resolved is None:
                _fail(f"No quality run folders found under {runs_root}")
            run_dir = resolved
        if not run_dir.exists() or not run_dir.is_dir():
            _fail(f"Run directory not found: {run_dir}")

        timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        if out_dir is None:
            out_dir = run_dir / "leaderboards" / experiment_id / timestamp
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            payload = build_quality_leaderboard(
                run_dir=run_dir,
                experiment_id=experiment_id,
                allow_partial_coverage=bool(allow_partial_coverage),
                include_by_source_extension=bool(by_source_extension),
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))
            return

        paths = write_quality_leaderboard_artifacts(payload, out_dir=out_dir)
        winner = payload.get("winner") if isinstance(payload, dict) else None
        leaderboard = payload.get("leaderboard") if isinstance(payload, dict) else None
        total_sources = payload.get("total_source_groups") if isinstance(payload, dict) else None
        winner_settings_payload = (
            payload.get("winner_run_settings")
            if isinstance(payload, dict)
            else None
        )
        if isinstance(winner_settings_payload, dict):
            try:
                winner_settings = RunSettings.from_dict(
                    project_run_config_payload(
                        winner_settings_payload,
                        contract=RUN_SETTING_CONTRACT_FULL,
                    ),
                    warn_context="quality-leaderboard winner profile",
                )
                save_qualitysuite_winner_run_settings(Path(DEFAULT_OUTPUT), winner_settings)
                typer.secho(
                    "Saved quality-suite winner profile: "
                    f"{history_root_for_output(Path(DEFAULT_OUTPUT)) / 'qualitysuite_winner_run_settings.json'}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            except Exception as exc:  # noqa: BLE001
                typer.secho(
                    f"Warning: failed to save quality-suite winner profile ({exc})",
                    fg=typer.colors.YELLOW,
                )

        typer.secho("Quality leaderboard complete.", fg=typer.colors.GREEN)
        typer.secho(f"Run: {run_dir}", fg=typer.colors.CYAN)
        typer.secho(f"Experiment: {experiment_id}", fg=typer.colors.CYAN)
        if total_sources is not None:
            typer.secho(f"Golden-set sources: {total_sources}", fg=typer.colors.CYAN)

        if isinstance(winner, dict):
            typer.secho("Best overall config:", fg=typer.colors.CYAN)
            typer.echo(
                (
                    f"  rank={winner.get('rank')} "
                    f"config_id={winner.get('config_id')} "
                    f"coverage={winner.get('coverage_sources')}/{total_sources or '?'} "
                    f"mean_practical_f1={float(winner.get('mean_practical_f1') or 0.0):.4f} "
                    f"mean_strict_f1={float(winner.get('mean_strict_f1') or 0.0):.4f} "
                    f"median_seconds={float(winner.get('median_duration_seconds') or 0.0):.2f}"
                )
            )
            line_role_verdict = str(winner.get("line_role_gates_verdict") or "").strip()
            if line_role_verdict:
                typer.echo(f"  line_role_gates={line_role_verdict}")
            typer.secho(
                f"Winner settings: {paths.winner_run_settings_json}",
                fg=typer.colors.CYAN,
            )

        if isinstance(leaderboard, list) and leaderboard:
            typer.secho(f"Top {min(int(top_n), len(leaderboard))} configs:", fg=typer.colors.CYAN)
            for row in leaderboard[: int(top_n)]:
                if not isinstance(row, dict):
                    continue
                typer.echo(
                    (
                        f"  {row.get('rank')}) {row.get('config_id')} "
                        f"coverage={row.get('coverage_sources')}/{total_sources or '?'} "
                        f"practical={float(row.get('mean_practical_f1') or 0.0):.4f} "
                        f"strict={float(row.get('mean_strict_f1') or 0.0):.4f} "
                        f"median_s={float(row.get('median_duration_seconds') or 0.0):.2f}"
                    )
                )
                row_line_role_verdict = str(row.get("line_role_gates_verdict") or "").strip()
                if row_line_role_verdict:
                    typer.echo(f"     line_role_gates={row_line_role_verdict}")

        typer.secho(f"Artifacts: {paths.out_dir}", fg=typer.colors.CYAN)
        typer.secho(f"Leaderboard JSON: {paths.leaderboard_json}", fg=typer.colors.CYAN)
        typer.secho(f"Leaderboard CSV: {paths.leaderboard_csv}", fg=typer.colors.CYAN)
        typer.secho(f"Pareto JSON: {paths.pareto_json}", fg=typer.colors.CYAN)
        typer.secho(f"Pareto CSV: {paths.pareto_csv}", fg=typer.colors.CYAN)
        by_extension_json = getattr(paths, "leaderboard_by_source_extension_json", None)
        by_extension_csv = getattr(paths, "leaderboard_by_source_extension_csv", None)
        if by_extension_json is not None:
            typer.secho(
                (
                    "Leaderboard by source extension JSON: "
                    f"{by_extension_json}"
                ),
                fg=typer.colors.CYAN,
            )
        if by_extension_csv is not None:
            typer.secho(
                (
                    "Leaderboard by source extension CSV: "
                    f"{by_extension_csv}"
                ),
                fg=typer.colors.CYAN,
            )

    @app.command("eval-stage")
    def bench_eval_stage(
        gold_spans: Path = typer.Option(
            ...,
            "--gold-spans",
            help="Path to exported freeform_span_labels.jsonl gold file.",
        ),
        stage_run: Path = typer.Option(
            ...,
            "--stage-run",
            help="Path to a stage run directory (for example data/output/<timestamp>).",
        ),
        workbook_slug: str | None = typer.Option(
            None,
            "--workbook-slug",
            help="Workbook folder name under .bench (required when stage run contains multiple workbooks).",
        ),
        extracted_archive: Path | None = typer.Option(
            None,
            "--extracted-archive",
            help="Optional extracted archive JSON path. Defaults to stage run raw/**/full_text.json when unique.",
        ),
        out_dir: Path | None = typer.Option(
            None,
            "--out-dir",
            help="Output directory for eval artifacts. Defaults to data/golden/benchmark/<timestamp>/.",
        ),
        label_projection: str = typer.Option(
            "core_structural_v1",
            "--label-projection",
            help=(
                "Segmentation label projection used for boundary diagnostics "
                "(core_structural_v1 only)."
            ),
        ),
        boundary_tolerance_blocks: int = typer.Option(
            0,
            "--boundary-tolerance-blocks",
            min=0,
            help="Boundary matching tolerance (in block indices) for segmentation metrics.",
        ),
        segmentation_metrics: str = typer.Option(
            "boundary_f1",
            "--segmentation-metrics",
            help=(
                "Comma-separated segmentation metrics to compute. "
                "Supported: boundary_f1,pk,windowdiff,boundary_similarity."
            ),
        ),
        gold_adaptation_mode: str = typer.Option(
            "auto",
            "--gold-adaptation-mode",
            help=(
                "Gold remap policy for stage-block evaluation: off (strict), "
                "auto (adapt when fingerprints drift), force (always adapt)."
            ),
        ),
        gold_adaptation_min_coverage: float = typer.Option(
            0.7,
            "--gold-adaptation-min-coverage",
            min=0.0,
            max=1.0,
            help="Minimum remap coverage required when adaptive mode runs.",
        ),
        gold_adaptation_max_ambiguous: int = typer.Option(
            50,
            "--gold-adaptation-max-ambiguous",
            min=0,
            help="Maximum ambiguous remap assignments allowed.",
        ),
    ) -> None:
        if not gold_spans.exists() or not gold_spans.is_file():
            _fail(f"Gold spans file not found: {gold_spans}")
        if not stage_run.exists() or not stage_run.is_dir():
            _fail(f"Stage run folder not found: {stage_run}")

        stage_prediction_files = sorted(
            stage_run.glob(".bench/*/stage_block_predictions.json")
        )
        if not stage_prediction_files:
            _fail(
                "No stage block prediction manifests found under "
                f"{stage_run / '.bench'}."
            )

        stage_predictions_path: Path
        if workbook_slug:
            stage_predictions_path = (
                stage_run / ".bench" / workbook_slug / "stage_block_predictions.json"
            )
            if not stage_predictions_path.exists():
                _fail(
                    "Stage block predictions not found for workbook "
                    f"{workbook_slug}: {stage_predictions_path}"
                )
        elif len(stage_prediction_files) == 1:
            stage_predictions_path = stage_prediction_files[0]
        else:
            choices = ", ".join(path.parent.name for path in stage_prediction_files)
            _fail(
                "Stage run contains multiple workbooks. "
                f"Pass --workbook-slug. Choices: {choices}"
            )

        extracted_archive_path = extracted_archive
        if extracted_archive_path is None:
            candidates = sorted(stage_run.glob("raw/**/full_text.json"))
            if len(candidates) == 1:
                extracted_archive_path = candidates[0]
            else:
                _fail(
                    "Could not auto-resolve extracted archive. "
                    "Pass --extracted-archive explicitly."
                )
        if not extracted_archive_path.exists() or not extracted_archive_path.is_file():
            _fail(f"Extracted archive not found: {extracted_archive_path}")

        if out_dir is None:
            out_dir = _golden_benchmark_root() / dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            selected_gold_adaptation_mode = _normalize_gold_adaptation_mode(
                gold_adaptation_mode
            )
            result = evaluate_stage_blocks(
                gold_freeform_jsonl=gold_spans,
                stage_predictions_json=stage_predictions_path,
                extracted_blocks_json=extracted_archive_path,
                out_dir=out_dir,
                label_projection=label_projection,
                boundary_tolerance_blocks=boundary_tolerance_blocks,
                segmentation_metrics=segmentation_metrics,
                gold_adaptation_mode=selected_gold_adaptation_mode,
                gold_adaptation_min_coverage=float(gold_adaptation_min_coverage),
                gold_adaptation_max_ambiguous=int(gold_adaptation_max_ambiguous),
            )
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))

        report = result.get("report") if isinstance(result, dict) else {}
        typer.secho("Stage evaluation complete.", fg=typer.colors.GREEN)
        typer.secho(f"Stage predictions: {stage_predictions_path}", fg=typer.colors.CYAN)
        typer.secho(f"Report: {out_dir / 'eval_report.md'}", fg=typer.colors.CYAN)
        typer.secho(
            "Overall block accuracy: "
            f"{float((report or {}).get('overall_block_accuracy') or 0.0):.3f}",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            "Macro F1 (excluding OTHER): "
            f"{float((report or {}).get('macro_f1_excluding_other') or 0.0):.3f}",
            fg=typer.colors.CYAN,
        )

    exports = {
        "bench_oracle_upload": bench_oracle_upload,
        "bench_oracle_followup": bench_oracle_followup,
        "bench_oracle_autofollowup_worker": bench_oracle_autofollowup_worker,
        "bench_speed_discover": bench_speed_discover,
        "bench_speed_run": bench_speed_run,
        "bench_speed_compare": bench_speed_compare,
        "bench_gc": bench_gc,
        "bench_pin": bench_pin,
        "bench_unpin": bench_unpin,
        "bench_quality_discover": bench_quality_discover,
        "bench_quality_run": bench_quality_run,
        "bench_quality_lightweight_series": bench_quality_lightweight_series,
        "bench_quality_compare": bench_quality_compare,
        "bench_quality_leaderboard": bench_quality_leaderboard,
        "bench_eval_stage": bench_eval_stage,
    }
    globals().update(exports)
    return exports
