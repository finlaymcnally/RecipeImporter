from __future__ import annotations

import importlib
import sys

from cookimport.staging.import_session import (
    build_shard_recommendations_from_prep_bundle,
    resolve_or_build_deterministic_prep_bundle,
)

from .command_resolution import resolve_registered_command
from .bench_all_method import (
    _all_method_apply_baseline_contract,
    _all_method_apply_codex_contract_from_baseline,
    _report_metric,
    _report_optional_metric,
    _resolve_benchmark_gold_and_source,
)
from .bench_cache import (
    _build_all_method_prediction_reuse_key,
    _build_all_method_split_convert_input_key,
    _build_single_book_split_cache_key,
    _resolve_interactive_prediction_reuse_cache_dir,
    _run_prediction_with_reuse,
    _normalize_single_book_split_cache_mode,
)

runtime = sys.modules["cookimport.cli_support.bench"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)


def _labelstudio_benchmark_command():
    return resolve_registered_command(
        "cookimport.cli_commands.labelstudio", "labelstudio_benchmark"
    )


def _resolve_artifact_path(base_dir: Path, value: Any) -> Path | None:
    bench_compare = importlib.import_module("cookimport.cli_support.bench_compare")
    return bench_compare._resolve_artifact_path(base_dir, value)


def _interactive_single_book_preview_baseline_settings(
    selected_settings: RunSettings,
) -> RunSettings:
    run_config = project_run_config_payload(
        selected_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    baseline_payload = _all_method_apply_baseline_contract(run_config)
    return RunSettings.from_dict(
        baseline_payload,
        warn_context="interactive single-book shard preview baseline",
    )


def _build_single_book_interactive_shard_recommendations(
    *,
    source_file: Path,
    selected_settings: RunSettings,
    processed_output_root: Path,
) -> dict[str, dict[str, Any]]:
    preview_baseline_settings = _interactive_single_book_preview_baseline_settings(
        selected_settings
    )
    prep_bundle = resolve_or_build_deterministic_prep_bundle(
        source_file=source_file,
        run_settings=preview_baseline_settings,
        processed_output_root=processed_output_root,
    )
    return build_shard_recommendations_from_prep_bundle(
        prep_bundle=prep_bundle,
        selected_settings=selected_settings,
    )


def _variant_can_reuse_deterministic_prep_bundle(
    *,
    bundle_settings: RunSettings,
    variant_settings: RunSettings,
) -> bool:
    # The shared prep bundle carries authoritative line-role outputs, so a codex
    # line-role variant must not inherit a bundle that was built with line-role off.
    return (
        str(getattr(bundle_settings.line_role_pipeline, "value", "off")).strip().lower()
        == str(getattr(variant_settings.line_role_pipeline, "value", "off")).strip().lower()
    )


def _write_single_book_summary_markdown(
    *,
    run_timestamp: str,
    session_root: Path,
    variant_results: dict[str, dict[str, Any]],
    comparison_json_path: Path | None,
) -> Path:
    lines: list[str] = [
        "# Single Book Benchmark Summary",
        "",
        f"- Run timestamp: {run_timestamp}",
        "",
        "## Variant Results",
        "",
    ]
    variant_order: list[str] = []
    for preferred_slug in ("vanilla", "codex-exec"):
        if preferred_slug in variant_results:
            variant_order.append(preferred_slug)
    variant_order.extend(
        sorted(
            slug for slug in variant_results.keys() if slug not in {"vanilla", "codex-exec"}
        )
    )
    for variant_slug in variant_order:
        row = variant_results.get(variant_slug)
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown").strip().lower() or "unknown"
        eval_output_dir_raw = row.get("eval_output_dir")
        eval_output_dir = (
            Path(str(eval_output_dir_raw)) if eval_output_dir_raw is not None else None
        )
        eval_report_json = (
            eval_output_dir / "eval_report.json"
            if eval_output_dir is not None
            else None
        )
        eval_report_payload = (
            _load_json_dict(eval_report_json)
            if eval_report_json is not None and status == "ok"
            else None
        )
        relative_eval_report_json = (
            eval_report_json.relative_to(session_root)
            if eval_report_json is not None
            and eval_report_json.is_absolute()
            and str(eval_report_json).startswith(str(session_root))
            else eval_report_json
        )
        metrics = (
            _load_single_book_eval_metrics(eval_output_dir)
            if eval_output_dir is not None and status == "ok"
            else None
        )
        lines.append(f"### `{variant_slug}`")
        lines.append("")
        lines.append(f"- Status: `{status}`")
        if relative_eval_report_json is not None:
            lines.append(f"- Eval report JSON: `{relative_eval_report_json}`")
        if isinstance(metrics, dict):
            for metric_name, _display_name in SINGLE_BOOK_COMPARISON_METRICS:
                metric_value = _benchmark_report_metric_value(metrics, metric_name)
                metric_text = (
                    f"{metric_value:.6f}" if metric_value is not None else "null"
                )
                lines.append(f"- `{metric_name}`: `{metric_text}`")
        else:
            error_text = str(row.get("error") or "").strip()
            if error_text:
                lines.append(f"- Error: `{error_text}`")
        variant_per_label_breakdown = _build_single_book_variant_per_label_breakdown(
            run_timestamp=run_timestamp,
            eval_report=eval_report_payload,
        )
        if isinstance(variant_per_label_breakdown, dict):
            lines.extend(
                _single_book_per_label_breakdown_markdown_lines(
                    per_label_breakdown_payload=variant_per_label_breakdown,
                    heading_level=4,
                    intro_text=(
                        "Variant-local values from this variant's eval report."
                    ),
                )
            )
        lines.append("")

    if comparison_json_path is not None and comparison_json_path.exists():
        comparison_payload = _load_json_dict(comparison_json_path)
        if isinstance(comparison_payload, dict):
            lines.extend(
                [
                    "## Codex vs Vanilla",
                    "",
                    f"- Comparison JSON: `{comparison_json_path.name}`",
                    "",
                ]
            )
            comparison_md_lines = (
                _format_single_book_comparison_markdown(comparison_payload)
                .strip()
                .splitlines()
            )
            comparison_md_lines = _strip_markdown_section(
                comparison_md_lines,
                heading_prefix="## Per-Label Breakdown",
            )
            if comparison_md_lines and comparison_md_lines[0].startswith("# "):
                comparison_md_lines = comparison_md_lines[1:]
            while comparison_md_lines and not comparison_md_lines[0].strip():
                comparison_md_lines = comparison_md_lines[1:]
            lines.extend(comparison_md_lines)
            lines.append("")

    summary_md_path = session_root / "single_book_summary.md"
    summary_md_path.parent.mkdir(parents=True, exist_ok=True)
    summary_md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary_md_path


@dataclass(frozen=True)
class _SingleBookBenchmarkComputationResult:
    variants: list[tuple[str, RunSettings]]
    variant_results: dict[str, dict[str, Any]]
    session_root: Path
    session_processed_root: Path
    succeeded: int
    has_codex_variants: bool
    comparison_json_path: Path | None
    summary_md_path: Path | None


@dataclass(frozen=True)
class _SingleBookBenchmarkPublicationResult:
    upload_bundle_dir: Path | None = None
    starter_pack_dir: Path | None = None
    flattened_summary_path: Path | None = None


def _upsert_single_book_metadata_entry(
    comparison_json_path: Path,
    *,
    key: str,
    value: dict[str, Any],
) -> None:
    payload = _load_json_dict(comparison_json_path) or {}
    metadata_payload = payload.get("metadata")
    if not isinstance(metadata_payload, dict):
        metadata_payload = {}
    metadata_payload[key] = value
    payload["metadata"] = metadata_payload
    comparison_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _publish_single_book_benchmark_result(
    result: _SingleBookBenchmarkComputationResult,
    *,
    golden_root: Path,
    processed_output_root: Path,
    write_starter_pack: bool,
) -> _SingleBookBenchmarkPublicationResult:
    starter_pack_dir: Path | None = None
    flattened_summary_path: Path | None = None
    if write_starter_pack and result.comparison_json_path is not None:
        starter_pack_dir = _write_single_book_starter_pack(
            session_root=result.session_root
        )
        if starter_pack_dir is not None:
            _upsert_single_book_metadata_entry(
                result.comparison_json_path,
                key="starter_pack_v1",
                value={
                    "path": str(starter_pack_dir),
                    "relative_path": "starter_pack_v1",
                    "manifest_file": "starter_pack_v1/10_process_manifest.json",
                },
            )
            flattened_summary_path = result.session_root / "benchmark_summary.md"
            if flattened_summary_path.is_file():
                _upsert_single_book_metadata_entry(
                    result.comparison_json_path,
                    key="flattened_summary",
                    value={
                        "path": str(flattened_summary_path),
                        "relative_path": "benchmark_summary.md",
                    },
                )
            else:
                flattened_summary_path = None

    upload_bundle_dir: Path | None = None
    if result.succeeded > 0 and result.has_codex_variants:
        upload_bundle_dir = _write_benchmark_upload_bundle(
            source_root=result.session_root,
            output_dir=result.session_root / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
            suppress_summary=False,
            high_level_only=True,
            target_bundle_size_bytes=BENCHMARK_SINGLE_BOOK_UPLOAD_BUNDLE_TARGET_BYTES,
        )
        if upload_bundle_dir is not None:
            _start_benchmark_bundle_oracle_upload_background(
                bundle_dir=upload_bundle_dir,
                scope="single_book",
            )

    history_csv_path = history_csv_for_output(
        result.session_processed_root / _DASHBOARD_REFRESH_SENTINEL_DIRNAME
    )
    _refresh_dashboard_after_history_write(
        csv_path=history_csv_path,
        output_root=processed_output_root,
        golden_root=golden_root,
        dashboard_out_dir=history_root_for_output(processed_output_root) / "dashboard",
        reason="single-book benchmark variant batch append",
    )
    return _SingleBookBenchmarkPublicationResult(
        upload_bundle_dir=upload_bundle_dir,
        starter_pack_dir=starter_pack_dir,
        flattened_summary_path=flattened_summary_path,
    )


def _make_single_book_benchmark_publisher(
    *,
    golden_root: Path,
    processed_output_root: Path,
    write_starter_pack: bool,
) -> Callable[
    [_SingleBookBenchmarkComputationResult],
    _SingleBookBenchmarkPublicationResult,
]:
    return lambda result: _publish_single_book_benchmark_result(
        result,
        golden_root=golden_root,
        processed_output_root=processed_output_root,
        write_starter_pack=write_starter_pack,
    )


def _interactive_single_book_benchmark(
    *,
    selected_benchmark_settings: RunSettings,
    benchmark_eval_output: Path,
    processed_output_root: Path,
    golden_root: Path | None = None,
    write_markdown: bool = False,
    write_label_studio_tasks: bool = False,
    write_starter_pack: bool = False,
    single_book_split_cache_mode: str = "auto",
    single_book_split_cache_dir: Path | None = None,
    single_book_split_cache_force: bool = False,
    preselected_gold_spans: Path | None = None,
    preselected_source_file: Path | None = None,
    publisher: Callable[
        [_SingleBookBenchmarkComputationResult],
        _SingleBookBenchmarkPublicationResult,
    ]
    | None = None,
) -> bool:
    resolved_golden_root = golden_root or DEFAULT_GOLDEN
    variants = _interactive_single_book_variants(selected_benchmark_settings)
    if not variants:
        typer.secho("No single-book benchmark variants were planned.", fg=typer.colors.YELLOW)
        return False

    selected_gold = preselected_gold_spans
    selected_source = preselected_source_file
    if (
        (selected_gold is None or selected_source is None)
        and hasattr(sys.stdin, "isatty")
        and sys.stdin.isatty()
    ):
        resolved_inputs = _resolve_benchmark_gold_and_source(
            gold_spans=selected_gold,
            source_file=selected_source,
            output_dir=resolved_golden_root,
            allow_cancel=True,
        )
        if resolved_inputs is None:
            typer.secho("Benchmark cancelled.", fg=typer.colors.YELLOW)
            return False
        selected_gold, selected_source = resolved_inputs

    session_root = benchmark_eval_output / "single-book-benchmark"
    session_processed_root = (
        processed_output_root / benchmark_eval_output.name / "single-book-benchmark"
    )
    if selected_source is not None:
        source_slug = slugify_name(selected_source.stem) or "source"
        session_root = session_root / source_slug
        session_processed_root = session_processed_root / source_slug

    typer.secho(
        f"Single-book benchmark variants: {', '.join(slug for slug, _ in variants)}",
        fg=typer.colors.CYAN,
    )

    selected_split_cache_mode = _normalize_single_book_split_cache_mode(
        single_book_split_cache_mode
    )
    split_cache_key: str | None = None
    split_cache_root: Path | None = None
    split_cache_source_hash: str | None = None
    deterministic_prep_bundle = None
    if len(variants) > 1 and selected_split_cache_mode != "off":
        split_cache_root = _resolve_single_book_split_cache_root(
            session_root=session_root,
            split_cache_dir=single_book_split_cache_dir,
        )
        key_source_path = (
            selected_source
            if selected_source is not None
            else session_root / "__single_book_split_cache_source__"
        )
        try:
            split_cache_source_hash = (
                compute_file_hash(key_source_path)
                if key_source_path.exists() and key_source_path.is_file()
                else None
            )
        except Exception:  # noqa: BLE001
            split_cache_source_hash = None
        split_cache_key = _build_single_book_split_cache_key(
            source_file=key_source_path,
            source_hash=split_cache_source_hash,
            pipeline="auto",
            run_settings=variants[0][1],
        )
        typer.secho(
            (
                "Single-book split cache enabled: "
                f"mode={selected_split_cache_mode} key={split_cache_key[:12]}..."
            ),
            fg=typer.colors.BRIGHT_BLACK,
        )
    if selected_source is not None:
        deterministic_prep_bundle = resolve_or_build_deterministic_prep_bundle(
            source_file=selected_source,
            run_settings=variants[0][1],
            processed_output_root=processed_output_root,
        )
        typer.secho(
            (
                "Deterministic prep bundle: "
                f"{deterministic_prep_bundle.prep_key[:12]}..."
                f" ({'hit' if deterministic_prep_bundle.cache_hit else 'built'})"
            ),
            fg=typer.colors.BRIGHT_BLACK,
        )
    prediction_reuse_cache_dir = _resolve_interactive_prediction_reuse_cache_dir(
        processed_output_root=processed_output_root,
    )

    variant_results: dict[str, dict[str, Any]] = {}
    for index, (variant_slug, variant_settings) in enumerate(variants, start=1):
        variant_eval_output = session_root / variant_slug
        variant_processed_output = session_processed_root / variant_slug
        typer.secho(
            f"Single-book benchmark {index}/{len(variants)}: {variant_slug}",
            fg=typer.colors.CYAN,
        )
        variant_kwargs = build_benchmark_call_kwargs_from_run_settings(
            variant_settings,
            output_dir=_golden_benchmark_root(),
            eval_output_dir=variant_eval_output,
            processed_output_dir=variant_processed_output,
            eval_mode=BENCHMARK_EVAL_MODE_CANONICAL_TEXT,
            no_upload=True,
            # Single-offline keeps per-variant runs JSON-first and writes one
            # consolidated markdown summary at the session root.
            write_markdown=False,
            write_label_studio_tasks=write_label_studio_tasks,
        )
        variant_kwargs["allow_codex"] = codex_surfaces_enabled(
            variant_settings.to_run_config_dict()
        )
        if selected_gold is not None:
            variant_kwargs["gold_spans"] = selected_gold
        if selected_source is not None:
            variant_kwargs["source_file"] = selected_source
        if split_cache_root is not None and split_cache_key:
            variant_kwargs.update(
                {
                    "single_book_split_cache_mode": selected_split_cache_mode,
                    "single_book_split_cache_dir": split_cache_root,
                    "single_book_split_cache_key": split_cache_key,
                    "single_book_split_cache_force": bool(
                        single_book_split_cache_force and index == 1
                    ),
                }
            )
        if (
            deterministic_prep_bundle is not None
            and _variant_can_reuse_deterministic_prep_bundle(
                bundle_settings=variants[0][1],
                variant_settings=variant_settings,
            )
        ):
            variant_kwargs["deterministic_prep_manifest_path"] = (
                deterministic_prep_bundle.manifest_path
            )
        try:
            def _execute_prediction() -> None:
                with _benchmark_progress_overrides(
                    suppress_dashboard_refresh=True,
                    suppress_output_prune=True,
                ):
                    _labelstudio_benchmark_command()(**variant_kwargs)

            prediction_reuse_summary: dict[str, Any] | None = None
            if selected_source is not None:
                prediction_reuse_summary = _run_prediction_with_reuse(
                    cache_dir=prediction_reuse_cache_dir,
                    prediction_reuse_key=_build_all_method_prediction_reuse_key(
                        source_file=selected_source,
                        run_settings=variant_settings,
                    ),
                    prediction_split_convert_input_key=(
                        _build_all_method_split_convert_input_key(
                            source_file=selected_source,
                            run_settings=variant_settings,
                        )
                    ),
                    source_file=selected_source,
                    target_eval_output_dir=variant_eval_output,
                    target_processed_output_dir=variant_processed_output,
                    config_dir_name=variant_slug,
                    execute_prediction=_execute_prediction,
                )
                if str(
                    prediction_reuse_summary.get("prediction_result_source") or ""
                ).startswith("reused_"):
                    typer.secho(
                        (
                            f"Single-book {variant_slug}: "
                            f"{prediction_reuse_summary['prediction_result_source']} "
                            f"({prediction_reuse_summary['prediction_reuse_key'][:12]}...)"
                        ),
                        fg=typer.colors.BRIGHT_BLACK,
                    )
            else:
                _execute_prediction()
            source_file = _load_single_book_source_path(variant_eval_output)
            split_cache_metadata = _load_single_book_split_cache_metadata(
                variant_eval_output
            )
            variant_results[variant_slug] = {
                "status": "ok",
                "settings": variant_settings,
                "eval_output_dir": variant_eval_output,
                "processed_output_dir": variant_processed_output,
                "source_file": source_file,
                "single_book_split_cache": split_cache_metadata,
                "prediction_reuse": prediction_reuse_summary,
            }
        except typer.Exit as exc:
            exit_code = int(getattr(exc, "exit_code", 1))
            variant_results[variant_slug] = {
                "status": "failed",
                "settings": variant_settings,
                "eval_output_dir": variant_eval_output,
                "processed_output_dir": variant_processed_output,
                "error": f"exit code {exit_code}",
            }
            typer.secho(
                (
                    f"Single-book {variant_slug} failed "
                    f"(exit code {exit_code}); continuing."
                ),
                fg=typer.colors.YELLOW,
            )
        except Exception as exc:  # noqa: BLE001
            variant_results[variant_slug] = {
                "status": "failed",
                "settings": variant_settings,
                "eval_output_dir": variant_eval_output,
                "processed_output_dir": variant_processed_output,
                "error": str(exc),
            }
            typer.secho(
                f"Single-book {variant_slug} failed: {exc}; continuing.",
                fg=typer.colors.YELLOW,
            )

    succeeded = sum(
        1 for payload in variant_results.values() if payload.get("status") == "ok"
    )
    summary_color = typer.colors.GREEN if succeeded == len(variants) else typer.colors.YELLOW
    typer.secho(
        (
            "Single-book benchmark complete: "
            f"{succeeded}/{len(variants)} variant runs succeeded."
        ),
        fg=summary_color,
    )
    typer.secho(
        f"Single-book benchmark outputs: {session_root}",
        fg=typer.colors.CYAN,
    )
    typer.secho(
        f"Single-book processed outputs: {session_processed_root}",
        fg=typer.colors.CYAN,
    )

    comparison_written = False
    comparison_json_path: Path | None = None
    codex_result = variant_results.get("codex-exec")
    vanilla_result = variant_results.get("vanilla")
    if (
        isinstance(codex_result, dict)
        and isinstance(vanilla_result, dict)
        and codex_result.get("status") == "ok"
        and vanilla_result.get("status") == "ok"
    ):
        source_file = (
            str(codex_result.get("source_file") or "").strip()
            or str(vanilla_result.get("source_file") or "").strip()
            or None
        )
        comparison_paths = _write_single_book_comparison_artifacts(
            run_timestamp=benchmark_eval_output.name,
            session_root=session_root,
            source_file=source_file,
            codex_eval_output_dir=Path(str(codex_result["eval_output_dir"])),
            vanilla_eval_output_dir=Path(str(vanilla_result["eval_output_dir"])),
            split_cache_metadata=_single_book_split_cache_summary(
                vanilla_metadata=cast(
                    dict[str, Any] | None,
                    vanilla_result.get("single_book_split_cache"),
                ),
                codex_metadata=cast(
                    dict[str, Any] | None,
                    codex_result.get("single_book_split_cache"),
                ),
            ),
            write_markdown=False,
            write_starter_pack=False,
        )
        if comparison_paths is not None:
            comparison_written = True
            comparison_json_path, _comparison_md_path = comparison_paths
            typer.secho(
                f"Comparison JSON: {comparison_json_path}",
                fg=typer.colors.CYAN,
            )

    summary_md_path: Path | None = None
    if (
        not comparison_written
        and isinstance(codex_result, dict)
        and isinstance(vanilla_result, dict)
    ):
        typer.secho(
            (
                "Skipped codex-vs-vanilla comparison artifact: "
                "both codex-exec and vanilla variant runs must succeed."
            ),
            fg=typer.colors.YELLOW,
        )

    if write_markdown:
        summary_md_path = _write_single_book_summary_markdown(
            run_timestamp=benchmark_eval_output.name,
            session_root=session_root,
            variant_results=variant_results,
            comparison_json_path=comparison_json_path,
        )
        typer.secho(f"Summary report: {summary_md_path}", fg=typer.colors.CYAN)

    result = _SingleBookBenchmarkComputationResult(
        variants=variants,
        variant_results=variant_results,
        session_root=session_root,
        session_processed_root=session_processed_root,
        succeeded=succeeded,
        has_codex_variants=any(
            codex_surfaces_enabled(variant_settings.to_run_config_dict())
            for _variant_slug, variant_settings in variants
        ),
        comparison_json_path=comparison_json_path,
        summary_md_path=summary_md_path,
    )
    if publisher is None:
        publisher = _make_single_book_benchmark_publisher(
            golden_root=resolved_golden_root,
            processed_output_root=processed_output_root,
            write_starter_pack=write_starter_pack,
        )
    publication = publisher(result)
    if publication.upload_bundle_dir is not None:
        typer.secho(
            f"External-AI upload bundle: {publication.upload_bundle_dir}",
            fg=typer.colors.CYAN,
        )
    if publication.starter_pack_dir is not None:
        typer.secho(
            f"Starter pack: {publication.starter_pack_dir}",
            fg=typer.colors.CYAN,
        )
    if publication.flattened_summary_path is not None:
        typer.secho(
            f"Flattened summary: {publication.flattened_summary_path}",
            fg=typer.colors.CYAN,
        )

    if len(variants) == 1:
        return succeeded == 1
    return succeeded > 0

def _interactive_single_book_variants(
    selected_benchmark_settings: RunSettings,
) -> list[tuple[str, RunSettings]]:
    run_config = project_run_config_payload(
        selected_benchmark_settings.to_run_config_dict(),
        contract=RUN_SETTING_CONTRACT_FULL,
    )
    current_pipeline = str(run_config.get("llm_recipe_pipeline") or "off").strip().lower()
    if current_pipeline != "off":
        baseline_payload = _all_method_apply_baseline_contract(run_config)
        shared_atomic_block_splitter = _normalize_atomic_block_splitter(
            str(
                run_config.get("atomic_block_splitter")
                or baseline_payload.get("atomic_block_splitter")
                or "off"
            )
        )
        baseline_payload["atomic_block_splitter"] = shared_atomic_block_splitter
        codex_payload = _all_method_apply_codex_contract_from_baseline(
            baseline_payload
        )
        codex_payload["llm_recipe_pipeline"] = current_pipeline
        codex_payload["atomic_block_splitter"] = shared_atomic_block_splitter
        return [
            (
                "vanilla",
                RunSettings.from_dict(
                    baseline_payload,
                    warn_context="interactive benchmark vanilla variant",
                ),
            ),
            (
                "codex-exec",
                RunSettings.from_dict(
                    codex_payload,
                    warn_context="interactive benchmark codex-exec variant",
                ),
            ),
        ]
    return [
        (
            _single_book_variant_slug(selected_benchmark_settings),
            selected_benchmark_settings,
        )
    ]


def _single_book_variant_slug(settings: RunSettings) -> str:
    run_config = settings.to_run_config_dict()
    recipe_pipeline = str(run_config.get("llm_recipe_pipeline") or "off").strip().lower()
    line_role_pipeline = str(run_config.get("line_role_pipeline") or "off").strip().lower()
    if recipe_pipeline == "off" and line_role_pipeline in {"off", "deterministic-route-v2", "deterministic"}:
        return "vanilla"
    if recipe_pipeline == "off":
        return "line_role_only"
    if line_role_pipeline == "off":
        return "recipe_only"
    return "full_stack"

def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_single_book_eval_metrics(
    eval_output_dir: Path,
) -> dict[str, float | None] | None:
    eval_report = _load_json_dict(eval_output_dir / "eval_report.json")
    if eval_report is None:
        return None
    return _single_book_eval_metrics_from_report(eval_report)


def _single_book_eval_metrics_from_report(
    eval_report: dict[str, Any],
) -> dict[str, float | None]:
    return {
        metric_name: _benchmark_report_metric_value(eval_report, metric_name)
        for metric_name, _display_name in SINGLE_BOOK_COMPARISON_METRICS
    }


def _build_single_book_per_label_breakdown(
    *,
    run_timestamp: str,
    eval_reports: Iterable[dict[str, Any] | None],
) -> dict[str, Any] | None:
    by_label: dict[str, dict[str, Any]] = {}
    eval_count = 0
    for eval_report in eval_reports:
        if not isinstance(eval_report, dict):
            continue
        per_label_payload = eval_report.get("per_label")
        if not isinstance(per_label_payload, dict) or not per_label_payload:
            continue
        eval_count += 1
        for label_name, label_metrics_payload in per_label_payload.items():
            if not isinstance(label_metrics_payload, dict):
                continue
            label = str(label_name or "").strip()
            if not label:
                continue
            aggregate = by_label.setdefault(
                label,
                {
                    "label": label,
                    "gold_total": 0.0,
                    "pred_total": 0.0,
                    "tp_from_recall": 0.0,
                    "tp_from_precision": 0.0,
                    "has_gold": False,
                    "has_pred": False,
                },
            )
            gold_total = _report_optional_metric(label_metrics_payload.get("gold_total"))
            pred_total = _report_optional_metric(label_metrics_payload.get("pred_total"))
            recall = _report_optional_metric(label_metrics_payload.get("recall"))
            precision = _report_optional_metric(label_metrics_payload.get("precision"))

            if gold_total is not None:
                aggregate["gold_total"] += gold_total
                aggregate["has_gold"] = True
                if recall is not None:
                    aggregate["tp_from_recall"] += recall * gold_total
            if pred_total is not None:
                aggregate["pred_total"] += pred_total
                aggregate["has_pred"] = True
                if precision is not None:
                    aggregate["tp_from_precision"] += precision * pred_total

    if not by_label:
        return None

    rows: list[dict[str, Any]] = []
    for label in sorted(by_label):
        aggregate = by_label[label]
        gold_total = aggregate["gold_total"] if aggregate["has_gold"] else None
        pred_total = aggregate["pred_total"] if aggregate["has_pred"] else None
        tp: float | None = None
        if aggregate["has_gold"] and aggregate["has_pred"]:
            tp = (aggregate["tp_from_recall"] + aggregate["tp_from_precision"]) / 2.0
        elif aggregate["has_gold"]:
            tp = aggregate["tp_from_recall"]
        elif aggregate["has_pred"]:
            tp = aggregate["tp_from_precision"]

        precision: float | None = None
        if pred_total is not None:
            precision = tp / pred_total if pred_total > 0 and tp is not None else 0.0
        recall: float | None = None
        if gold_total is not None:
            recall = tp / gold_total if gold_total > 0 and tp is not None else 0.0

        def _count_value(raw_value: float | None) -> int | float | None:
            if raw_value is None:
                return None
            rounded = round(raw_value)
            if abs(raw_value - rounded) <= 1e-9:
                return int(rounded)
            return raw_value

        rows.append(
            {
                "label": label,
                "precision": precision,
                "recall": recall,
                "gold_total": _count_value(gold_total),
                "pred_total": _count_value(pred_total),
            }
        )

    return {
        "schema_version": SINGLE_BOOK_PER_LABEL_BREAKDOWN_SCHEMA_VERSION,
        "run_timestamp": run_timestamp,
        "eval_count": eval_count,
        "rows": rows,
    }


def _build_single_book_variant_per_label_breakdown(
    *,
    run_timestamp: str,
    eval_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(eval_report, dict):
        return None
    per_label_payload = eval_report.get("per_label")
    if not isinstance(per_label_payload, dict) or not per_label_payload:
        return None

    rows: list[dict[str, Any]] = []
    for label_name in sorted(per_label_payload):
        label_metrics_payload = per_label_payload.get(label_name)
        if not isinstance(label_metrics_payload, dict):
            continue
        label = str(label_name or "").strip()
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "precision": _report_optional_metric(label_metrics_payload.get("precision")),
                "recall": _report_optional_metric(label_metrics_payload.get("recall")),
                "gold_total": label_metrics_payload.get("gold_total"),
                "pred_total": label_metrics_payload.get("pred_total"),
            }
        )
    if not rows:
        return None
    return {
        "schema_version": SINGLE_BOOK_PER_LABEL_BREAKDOWN_SCHEMA_VERSION,
        "run_timestamp": run_timestamp,
        "eval_count": 1,
        "rows": rows,
    }


def _single_book_per_label_breakdown_markdown_lines(
    *,
    per_label_breakdown_payload: dict[str, Any],
    heading_level: int = 2,
    intro_text: str,
) -> list[str]:
    rows_payload = per_label_breakdown_payload.get("rows")
    if not isinstance(rows_payload, list):
        return []
    per_label_rows: list[tuple[str, str, str, str, str]] = []
    for row_payload in rows_payload:
        if not isinstance(row_payload, dict):
            continue
        label = str(row_payload.get("label") or "").strip()
        if not label:
            continue
        precision = _report_optional_metric(row_payload.get("precision"))
        recall = _report_optional_metric(row_payload.get("recall"))
        gold_total = _report_optional_metric(row_payload.get("gold_total"))
        pred_total = _report_optional_metric(row_payload.get("pred_total"))

        def _format_count(value: float | None) -> str:
            if value is None:
                return "null"
            rounded = round(value)
            if abs(value - rounded) <= 1e-9:
                return str(int(rounded))
            return f"{value:.4f}"

        per_label_rows.append(
            (
                label,
                f"{precision:.4f}" if precision is not None else "null",
                f"{recall:.4f}" if recall is not None else "null",
                _format_count(gold_total),
                _format_count(pred_total),
            )
        )
    if not per_label_rows:
        return []

    eval_count = _coerce_non_negative_int(per_label_breakdown_payload.get("eval_count"))
    run_label = str(per_label_breakdown_payload.get("run_timestamp") or "").strip() or "unknown"
    eval_count_text = (
        f"{eval_count} eval{'s' if eval_count != 1 else ''}"
        if eval_count is not None
        else "unknown evals"
    )
    label_col_width = max(len("Label"), *(len(row[0]) for row in per_label_rows))
    precision_col_width = max(len("Precision"), *(len(row[1]) for row in per_label_rows))
    recall_col_width = max(len("Recall"), *(len(row[2]) for row in per_label_rows))
    gold_col_width = max(len("Gold"), *(len(row[3]) for row in per_label_rows))
    pred_col_width = max(len("Pred"), *(len(row[4]) for row in per_label_rows))
    heading_marks = "#" * max(2, int(heading_level))
    lines = [
        "",
        f"{heading_marks} Per-Label Breakdown ({run_label}, {eval_count_text})",
        "",
        intro_text,
        (
            f"| {'Label':<{label_col_width}}"
            f" | {'Precision':>{precision_col_width}}"
            f" | {'Recall':>{recall_col_width}}"
            f" | {'Gold':>{gold_col_width}}"
            f" | {'Pred':>{pred_col_width}} |"
        ),
        (
            f"| {'-' * max(label_col_width, 3)}"
            f" | {'-' * (max(precision_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(recall_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(gold_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(pred_col_width, 3) - 1) + ':'} |"
        ),
    ]
    for (
        label_text,
        precision_text,
        recall_text,
        gold_text,
        pred_text,
    ) in per_label_rows:
        lines.append(
            f"| {label_text:<{label_col_width}}"
            f" | {precision_text:>{precision_col_width}}"
            f" | {recall_text:>{recall_col_width}}"
            f" | {gold_text:>{gold_col_width}}"
            f" | {pred_text:>{pred_col_width}} |"
        )
    return lines


def _strip_markdown_section(
    lines: list[str],
    *,
    heading_prefix: str,
) -> list[str]:
    stripped_lines: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith(heading_prefix):
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if not skipping:
            stripped_lines.append(line)
    while stripped_lines and not stripped_lines[-1].strip():
        stripped_lines.pop()
    return stripped_lines


def _single_book_display_metric_value(
    metrics: dict[str, Any] | None,
    metric_name: str,
) -> float | None:
    if not isinstance(metrics, dict):
        return None
    if metric_name == "strict_accuracy":
        for key in (
            "strict_accuracy",
            "overall_line_accuracy",
            "overall_block_accuracy",
            "accuracy",
        ):
            value = _report_optional_metric(metrics.get(key))
            if value is not None:
                return value
        precision = _report_optional_metric(metrics.get("precision"))
        recall = _report_optional_metric(metrics.get("recall"))
        f1 = _report_optional_metric(metrics.get("f1"))
        equal_pr = (
            precision is not None
            and recall is not None
            and abs(precision - recall) <= 1e-9
        )
        equal_rf = (
            recall is not None
            and f1 is not None
            and abs(recall - f1) <= 1e-9
        )
        equal_pf = (
            precision is not None
            and f1 is not None
            and abs(precision - f1) <= 1e-9
        )
        if equal_pr and equal_rf and equal_pf:
            return precision
        return None
    if metric_name == "macro_f1_excluding_other":
        return _report_optional_metric(metrics.get("macro_f1_excluding_other"))
    return _report_optional_metric(metrics.get(metric_name))


def _benchmark_report_metric_value(
    metrics: dict[str, Any] | None,
    metric_name: str,
) -> float | None:
    return _single_book_display_metric_value(metrics, metric_name)


def _benchmark_report_metric_bundle(
    metrics: dict[str, Any] | None,
) -> dict[str, float]:
    metrics_payload = metrics or {}
    strict_accuracy_raw = _benchmark_report_metric_value(metrics, "strict_accuracy")
    macro_f1_raw = _benchmark_report_metric_value(metrics, "macro_f1_excluding_other")
    has_explicit_strict_metric = any(
        _report_optional_metric(metrics_payload.get(key)) is not None
        for key in (
            "strict_accuracy",
            "overall_line_accuracy",
            "overall_block_accuracy",
            "accuracy",
        )
    )

    if has_explicit_strict_metric and strict_accuracy_raw is not None:
        precision = strict_accuracy_raw
        recall = strict_accuracy_raw
        f1 = strict_accuracy_raw
    else:
        precision = _report_metric(_report_optional_metric(metrics_payload.get("precision")))
        recall = _report_metric(_report_optional_metric(metrics_payload.get("recall")))
        f1_raw = _report_optional_metric(metrics_payload.get("f1"))
        if f1_raw is None and (precision + recall) > 0:
            f1_raw = (2.0 * precision * recall) / (precision + recall)
        f1 = _report_metric(f1_raw)
        strict_accuracy_raw = f1_raw

    has_explicit_macro_metric = (
        _report_optional_metric(metrics_payload.get("macro_f1_excluding_other"))
        is not None
    )
    if has_explicit_macro_metric and macro_f1_raw is not None:
        practical_precision = macro_f1_raw
        practical_recall = macro_f1_raw
        practical_f1 = macro_f1_raw
    else:
        practical_precision = _report_metric(_report_optional_metric(metrics_payload.get("practical_precision")))
        practical_recall = _report_metric(_report_optional_metric(metrics_payload.get("practical_recall")))
        practical_f1_raw = _report_optional_metric(metrics_payload.get("practical_f1"))
        if practical_f1_raw is None and (practical_precision + practical_recall) > 0:
            practical_f1_raw = (
                2.0 * practical_precision * practical_recall
            ) / (practical_precision + practical_recall)
        practical_f1 = _report_metric(practical_f1_raw)
        macro_f1_raw = practical_f1_raw

    strict_accuracy = _report_metric(strict_accuracy_raw)
    macro_f1 = _report_metric(macro_f1_raw)
    return {
        "strict_accuracy": strict_accuracy,
        "macro_f1_excluding_other": macro_f1,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "practical_precision": practical_precision,
        "practical_recall": practical_recall,
        "practical_f1": practical_f1,
    }


def _load_single_book_source_path(eval_output_dir: Path) -> str | None:
    manifest_payload = _load_json_dict(eval_output_dir / "run_manifest.json")
    if not isinstance(manifest_payload, dict):
        return None
    source_payload = manifest_payload.get("source")
    if not isinstance(source_payload, dict):
        return None
    source_path = str(source_payload.get("path") or "").strip()
    return source_path or None


def _load_single_book_split_cache_metadata(
    eval_output_dir: Path,
) -> dict[str, Any] | None:
    manifest_payload = _load_json_dict(eval_output_dir / "run_manifest.json")
    if not isinstance(manifest_payload, dict):
        return None
    run_config_payload = manifest_payload.get("run_config")
    if not isinstance(run_config_payload, dict):
        return None
    split_cache_payload = run_config_payload.get("single_book_split_cache")
    if isinstance(split_cache_payload, dict):
        return dict(split_cache_payload)
    return None


def _single_book_text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _resolve_single_book_reasoning_effort(
    effort: str | None,
    *,
    codex_cmd: str | None,
    codex_model: str | None = None,
) -> str | None:
    normalized_effort = _single_book_text_or_none(effort)
    if normalized_effort is None:
        return default_codex_reasoning_effort_for_model(
            codex_model,
            cmd=codex_cmd,
        )
    if normalized_effort.lower() in {"<default>", "default"}:
        return default_codex_reasoning_effort(
            cmd=codex_cmd
        ) or default_codex_reasoning_effort_for_model(
            codex_model,
            cmd=codex_cmd,
        )
    try:
        return normalize_codex_reasoning_effort(normalized_effort)
    except ValueError:
        return normalized_effort


def _find_single_book_llm_manifest_path(
    prediction_run_dir: Path,
) -> Path | None:
    prediction_manifest = _load_json_dict(prediction_run_dir / "run_manifest.json")
    if isinstance(prediction_manifest, dict):
        prediction_artifacts = prediction_manifest.get("artifacts")
        if isinstance(prediction_artifacts, dict):
            candidate = _resolve_artifact_path(
                prediction_run_dir,
                prediction_artifacts.get("recipe_manifest_json"),
            )
            if candidate is not None and candidate.exists() and candidate.is_file():
                return candidate

    raw_llm_root = prediction_run_dir / "raw" / "llm"
    if not raw_llm_root.exists() or not raw_llm_root.is_dir():
        return None
    for run_dir in sorted(raw_llm_root.iterdir(), key=lambda path: path.name):
        if not run_dir.is_dir():
            continue
        candidate = run_dir / RECIPE_MANIFEST_FILE_NAME
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _extract_codex_farm_runtime_from_llm_manifest(
    llm_manifest: dict[str, Any],
) -> tuple[str | None, str | None]:
    model = _single_book_text_or_none(llm_manifest.get("codex_farm_model"))
    reasoning_effort = _single_book_text_or_none(
        llm_manifest.get("codex_farm_reasoning_effort")
    )

    process_runs = llm_manifest.get("process_runs")
    if not isinstance(process_runs, dict):
        return model, reasoning_effort

    for pass_payload in process_runs.values():
        if not isinstance(pass_payload, dict):
            continue

        process_payload = pass_payload.get("process_payload")
        if isinstance(process_payload, dict):
            if model is None:
                model = _single_book_text_or_none(process_payload.get("codex_model"))
            if reasoning_effort is None:
                reasoning_effort = _single_book_text_or_none(
                    process_payload.get("codex_reasoning_effort")
                )

        if reasoning_effort is None:
            telemetry_report = pass_payload.get("telemetry_report")
            insights = (
                telemetry_report.get("insights")
                if isinstance(telemetry_report, dict)
                else None
            )
            breakdown_rows = (
                insights.get("model_reasoning_breakdown")
                if isinstance(insights, dict)
                else None
            )
            if isinstance(breakdown_rows, list):
                for row in breakdown_rows:
                    if not isinstance(row, dict):
                        continue
                    if model is None:
                        model = _single_book_text_or_none(row.get("model"))
                    candidate_reasoning = _single_book_text_or_none(
                        row.get("reasoning_effort")
                    )
                    if candidate_reasoning is not None:
                        reasoning_effort = candidate_reasoning
                        break

        if model is not None and reasoning_effort is not None:
            break

    return model, reasoning_effort


def _single_book_nonnegative_int_or_none(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = int(float(text))
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _extract_codex_farm_token_usage_from_process_run_payload(
    pass_payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    token_keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    process_payload = (
        pass_payload.get("process_payload")
        if isinstance(pass_payload.get("process_payload"), dict)
        else None
    )
    telemetry_payload = (
        process_payload.get("telemetry")
        if isinstance(process_payload, dict)
        and isinstance(process_payload.get("telemetry"), dict)
        else None
    )
    if telemetry_payload is None and isinstance(pass_payload.get("telemetry"), dict):
        telemetry_payload = pass_payload.get("telemetry")
    telemetry_rows = (
        telemetry_payload.get("rows")
        if isinstance(telemetry_payload, dict)
        and isinstance(telemetry_payload.get("rows"), list)
        else None
    )

    totals: dict[str, int | None] = {key: None for key in token_keys}
    if isinstance(telemetry_rows, list):
        for row in telemetry_rows:
            if not isinstance(row, dict):
                continue
            for key in token_keys:
                value = _single_book_nonnegative_int_or_none(row.get(key))
                if value is None:
                    continue
                current = totals.get(key)
                totals[key] = value if current is None else current + value

    telemetry_report = None
    if isinstance(process_payload, dict) and isinstance(
        process_payload.get("telemetry_report"), dict
    ):
        telemetry_report = process_payload.get("telemetry_report")
    elif isinstance(pass_payload.get("telemetry_report"), dict):
        telemetry_report = pass_payload.get("telemetry_report")
    summary_payload = (
        telemetry_report.get("summary")
        if isinstance(telemetry_report, dict)
        and isinstance(telemetry_report.get("summary"), dict)
        else None
    )
    if isinstance(summary_payload, dict):
        summary_value_map = {
            "tokens_input": summary_payload.get("tokens_input"),
            "tokens_cached_input": summary_payload.get("tokens_cached_input"),
            "tokens_output": summary_payload.get("tokens_output"),
            "tokens_reasoning": (
                summary_payload.get("tokens_reasoning")
                if summary_payload.get("tokens_reasoning") is not None
                else summary_payload.get("tokens_reasoning_total")
            ),
            "tokens_total": summary_payload.get("tokens_total"),
        }
        for key, raw_value in summary_value_map.items():
            if totals.get(key) is not None:
                continue
            parsed_value = _single_book_nonnegative_int_or_none(raw_value)
            if parsed_value is not None:
                totals[key] = parsed_value

    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _extract_codex_farm_token_usage_from_llm_manifest(
    llm_manifest: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    process_runs = llm_manifest.get("process_runs")
    if not isinstance(process_runs, dict):
        return _extract_codex_farm_token_usage_from_process_run_payload(llm_manifest)

    token_keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    totals: dict[str, int | None] = {key: None for key in token_keys}
    for pass_name in sorted(process_runs):
        pass_payload = process_runs.get(pass_name)
        if not isinstance(pass_payload, dict):
            continue
        (
            pass_tokens_input,
            pass_tokens_cached_input,
            pass_tokens_output,
            pass_tokens_reasoning,
            pass_tokens_total,
        ) = _extract_codex_farm_token_usage_from_process_run_payload(pass_payload)
        for key, value in (
            ("tokens_input", pass_tokens_input),
            ("tokens_cached_input", pass_tokens_cached_input),
            ("tokens_output", pass_tokens_output),
            ("tokens_reasoning", pass_tokens_reasoning),
            ("tokens_total", pass_tokens_total),
        ):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    knowledge_payload = llm_manifest.get("knowledge")
    knowledge_tokens = (None, None, None, None, None)
    if isinstance(knowledge_payload, dict):
        process_run_payload = knowledge_payload.get("process_run")
        if isinstance(process_run_payload, dict):
            knowledge_tokens = _extract_codex_farm_token_usage_from_process_run_payload(
                process_run_payload
            )
        if all(value is None for value in knowledge_tokens):
            knowledge_tokens = _extract_codex_farm_token_usage_from_process_run_payload(
                knowledge_payload
            )
    for key, value in zip(token_keys, knowledge_tokens):
        if value is None:
            continue
        current = totals.get(key)
        totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _append_single_book_summary_payload(
    summary: dict[str, Any],
    summaries: list[dict[str, Any]],
    seen: set[int],
) -> None:
    summary_id = id(summary)
    if summary_id in seen:
        return
    seen.add(summary_id)
    summaries.append(summary)


def _collect_single_book_summary_payloads(
    payload: Any,
    summaries: list[dict[str, Any]],
    seen: set[int],
) -> None:
    if isinstance(payload, dict):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            _append_single_book_summary_payload(summary, summaries, seen)
        telemetry_report = payload.get("telemetry_report")
        if isinstance(telemetry_report, dict):
            nested_summary = telemetry_report.get("summary")
            if isinstance(nested_summary, dict):
                _append_single_book_summary_payload(nested_summary, summaries, seen)
        for value in payload.values():
            _collect_single_book_summary_payloads(value, summaries, seen)
    elif isinstance(payload, list):
        for value in payload:
            _collect_single_book_summary_payloads(value, summaries, seen)


def _single_book_token_usage_from_summary_payloads(
    summaries: list[dict[str, Any]],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    token_keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    totals: dict[str, int | None] = {key: None for key in token_keys}
    for summary in summaries:
        for key in token_keys:
            raw_value = summary.get(key)
            if key == "tokens_reasoning" and raw_value is None:
                raw_value = summary.get("tokens_reasoning_total")
            value = _single_book_nonnegative_int_or_none(raw_value)
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _single_book_line_role_summaries_from_attempts(
    telemetry_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    batches = telemetry_payload.get("batches")
    if not isinstance(batches, list):
        return summaries
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        attempts = batch.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            process_run = attempt.get("process_run")
            if isinstance(process_run, dict):
                process_payload = process_run.get("process_payload")
                if isinstance(process_payload, dict):
                    telemetry_report = process_payload.get("telemetry_report")
                    if (
                        isinstance(telemetry_report, dict)
                        and isinstance(telemetry_report.get("summary"), dict)
                    ):
                        summaries.append(telemetry_report.get("summary"))
                        continue
                telemetry_report = process_run.get("telemetry_report")
                if (
                    isinstance(telemetry_report, dict)
                    and isinstance(telemetry_report.get("summary"), dict)
                ):
                    summaries.append(telemetry_report.get("summary"))
                    continue
            telemetry_report = attempt.get("telemetry_report")
            if (
                isinstance(telemetry_report, dict)
                and isinstance(telemetry_report.get("summary"), dict)
            ):
                summaries.append(telemetry_report.get("summary"))
    return summaries


def _extract_line_role_token_usage_from_manifest(
    payload: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    for telemetry_path in _line_role_telemetry_candidate_paths(payload):
        telemetry_payload = _load_json_dict(telemetry_path)
        if not isinstance(telemetry_payload, dict):
            continue
        summary = telemetry_payload.get("summary")
        direct_tokens = (
            _single_book_nonnegative_int_or_none(summary.get("tokens_input"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_cached_input"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_output"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_reasoning"))
            if isinstance(summary, dict)
            else None,
            _single_book_nonnegative_int_or_none(summary.get("tokens_total"))
            if isinstance(summary, dict)
            else None,
        )
        nested_summaries = _single_book_line_role_summaries_from_attempts(
            telemetry_payload
        )
        fallback_tokens = _single_book_token_usage_from_summary_payloads(
            nested_summaries
        )
        summary_looks_incomplete = False
        if isinstance(summary, dict):
            direct_has_positive_usage = any(
                value is not None and value > 0 for value in direct_tokens
            )
            attempts_without_usage = _single_book_nonnegative_int_or_none(
                summary.get("attempts_without_usage")
            )
            visible_input_tokens = _single_book_nonnegative_int_or_none(
                summary.get("visible_input_tokens")
            )
            visible_output_tokens = _single_book_nonnegative_int_or_none(
                summary.get("visible_output_tokens")
            )
            command_execution_count_total = _single_book_nonnegative_int_or_none(
                summary.get("command_execution_count_total")
            )
            summary_looks_incomplete = bool(
                (attempts_without_usage is not None and attempts_without_usage > 0)
                or (
                    not direct_has_positive_usage
                    and any(
                        value is not None and value > 0
                        for value in (
                            visible_input_tokens,
                            visible_output_tokens,
                            command_execution_count_total,
                        )
                    )
                )
            )
        if summary_looks_incomplete:
            return (None, None, None, None, None)
        resolved_tokens = tuple(
            direct if direct is not None else fallback
            for direct, fallback in zip(direct_tokens, fallback_tokens)
        )
        if any(value is not None for value in resolved_tokens):
            return resolved_tokens
    return (None, None, None, None, None)


def _line_role_telemetry_candidate_paths(payload: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _append_candidate(raw_path: Any) -> None:
        text = str(raw_path or "").strip()
        if not text:
            return
        candidate = Path(text)
        if candidate in seen:
            return
        seen.add(candidate)
        candidates.append(candidate)

    _append_candidate(payload.get("line_role_pipeline_telemetry_path"))
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        _append_candidate(artifacts.get("line_role_pipeline_telemetry_json"))
    for root_key in ("processed_run_root", "stage_run_root"):
        root_value = str(payload.get(root_key) or "").strip()
        if not root_value:
            continue
        _append_candidate(Path(root_value) / "line-role-pipeline" / "telemetry_summary.json")
    return [candidate for candidate in candidates if candidate.is_file()]


def _sum_token_usage(
    *token_sets: tuple[int | None, int | None, int | None, int | None, int | None],
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    keys = (
        "tokens_input",
        "tokens_cached_input",
        "tokens_output",
        "tokens_reasoning",
        "tokens_total",
    )
    totals: dict[str, int | None] = {key: None for key in keys}
    for token_values in token_sets:
        for key, value in zip(keys, token_values):
            if value is None:
                continue
            current = totals.get(key)
            totals[key] = value if current is None else current + value
    return (
        totals.get("tokens_input"),
        totals.get("tokens_cached_input"),
        totals.get("tokens_output"),
        totals.get("tokens_reasoning"),
        totals.get("tokens_total"),
    )


def _load_single_book_codex_farm_runtime(
    eval_output_dir: Path,
) -> dict[str, Any] | None:
    manifest_payload = _load_json_dict(eval_output_dir / "run_manifest.json")
    if not isinstance(manifest_payload, dict):
        return None

    run_config_payload = manifest_payload.get("run_config")
    if not isinstance(run_config_payload, dict):
        run_config_payload = {}

    codex_cmd = _single_book_text_or_none(run_config_payload.get("codex_farm_cmd"))
    codex_model = _single_book_text_or_none(
        run_config_payload.get("codex_farm_model")
    ) or _single_book_text_or_none(run_config_payload.get("codex_model"))
    codex_reasoning_effort = _resolve_single_book_reasoning_effort(
        run_config_payload.get("codex_farm_reasoning_effort")
        or run_config_payload.get("codex_reasoning_effort"),
        codex_cmd=codex_cmd,
        codex_model=codex_model,
    )

    artifacts_payload = manifest_payload.get("artifacts")
    prediction_run_dir: Path | None = None
    if isinstance(artifacts_payload, dict):
        prediction_run_dir = _resolve_artifact_path(
            eval_output_dir,
            artifacts_payload.get("artifact_root_dir"),
        )
    if prediction_run_dir is None:
        prediction_run_dir = eval_output_dir

    llm_manifest = None
    if prediction_run_dir.exists() and prediction_run_dir.is_dir():
        llm_manifest_path = _find_single_book_llm_manifest_path(prediction_run_dir)
        if llm_manifest_path is not None:
            llm_manifest = _load_json_dict(llm_manifest_path)
    if isinstance(llm_manifest, dict):
        inferred_model, inferred_reasoning_effort = (
            _extract_codex_farm_runtime_from_llm_manifest(llm_manifest)
        )
        if codex_model is None:
            codex_model = inferred_model
        if codex_reasoning_effort is None:
            codex_reasoning_effort = _resolve_single_book_reasoning_effort(
                inferred_reasoning_effort,
                codex_cmd=codex_cmd,
                codex_model=codex_model,
            )

    if codex_model is None and codex_reasoning_effort is None:
        return None
    return {
        "codex_model": codex_model,
        "codex_reasoning_effort": codex_reasoning_effort,
    }


def _resolve_single_book_split_cache_root(
    *,
    session_root: Path,
    split_cache_dir: Path | None,
) -> Path:
    if split_cache_dir is not None:
        return split_cache_dir.expanduser()
    env_override = str(os.getenv(SINGLE_BOOK_SPLIT_CACHE_ROOT_ENV, "") or "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return session_root / ".split-cache"


def _single_book_split_cache_summary(
    *,
    vanilla_metadata: dict[str, Any] | None,
    codex_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    variant_rows: dict[str, dict[str, Any]] = {}
    for variant_slug, payload in (
        ("vanilla", vanilla_metadata),
        ("codex-exec", codex_metadata),
    ):
        if not isinstance(payload, dict):
            continue
        variant_rows[variant_slug] = {
            "enabled": bool(payload.get("enabled")),
            "mode": str(payload.get("mode") or "").strip() or "off",
            "key": str(payload.get("key") or "").strip() or None,
            "hit": bool(payload.get("hit")),
            "force": bool(payload.get("force")),
            "source_hash": str(payload.get("source_hash") or "").strip() or None,
            "conversion_seconds": _report_optional_metric(
                payload.get("conversion_seconds")
            ),
        }
    if not variant_rows:
        return None
    shared_key: str | None = None
    if "vanilla" in variant_rows and "codex-exec" in variant_rows:
        vanilla_key = str(variant_rows["vanilla"].get("key") or "").strip()
        codex_key = str(variant_rows["codex-exec"].get("key") or "").strip()
        if vanilla_key and vanilla_key == codex_key:
            shared_key = vanilla_key
    return {
        "schema_version": SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION,
        "shared_key": shared_key,
        "variants": variant_rows,
    }


def _single_book_metric_deltas(
    *,
    codex_metrics: dict[str, float | None],
    vanilla_metrics: dict[str, float | None],
) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for metric_name, _display_name in SINGLE_BOOK_COMPARISON_METRICS:
        codex_value = _benchmark_report_metric_value(codex_metrics, metric_name)
        vanilla_value = _benchmark_report_metric_value(vanilla_metrics, metric_name)
        if codex_value is None or vanilla_value is None:
            deltas[metric_name] = None
        else:
            deltas[metric_name] = codex_value - vanilla_value
    return deltas


def _single_book_optional_delta(
    candidate: float | int | None,
    baseline: float | int | None,
) -> float | None:
    if candidate is None or baseline is None:
        return None
    return float(candidate) - float(baseline)


def _single_book_eval_segmentation_summary(
    eval_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(eval_report, dict):
        return {
            "available": False,
            "unavailable_reason": "eval_report_unavailable",
            "boundary_f1": None,
            "boundary_false_positive_count": None,
            "boundary_missed_count": None,
            "error_taxonomy_bucket_counts": {},
        }
    segmentation_payload = eval_report.get("segmentation")
    if not isinstance(segmentation_payload, dict):
        return {
            "available": False,
            "unavailable_reason": "segmentation_not_present_in_eval_report",
            "boundary_f1": None,
            "boundary_false_positive_count": None,
            "boundary_missed_count": None,
            "error_taxonomy_bucket_counts": {},
        }
    boundaries_payload = segmentation_payload.get("boundaries")
    overall_micro = (
        boundaries_payload.get("overall_micro")
        if isinstance(boundaries_payload, dict)
        else None
    )
    boundary_f1 = (
        _report_optional_metric(overall_micro.get("f1"))
        if isinstance(overall_micro, dict)
        else None
    )
    boundary_false_positive_count = (
        _single_book_nonnegative_int_or_none(overall_micro.get("fp"))
        if isinstance(overall_micro, dict)
        else None
    )
    boundary_missed_count = (
        _single_book_nonnegative_int_or_none(overall_micro.get("fn"))
        if isinstance(overall_micro, dict)
        else None
    )
    taxonomy_payload = segmentation_payload.get("error_taxonomy")
    bucket_counts_payload = (
        taxonomy_payload.get("bucket_counts")
        if isinstance(taxonomy_payload, dict)
        else None
    )
    bucket_counts: dict[str, int] = {}
    if isinstance(bucket_counts_payload, dict):
        for key, value in sorted(bucket_counts_payload.items()):
            name = str(key or "").strip()
            parsed = _single_book_nonnegative_int_or_none(value)
            if not name or parsed is None:
                continue
            bucket_counts[name] = parsed
    available = (
        boundary_f1 is not None
        or boundary_false_positive_count is not None
        or boundary_missed_count is not None
        or bool(bucket_counts)
    )
    if available:
        unavailable_reason: str | None = None
    else:
        unavailable_reason = "segmentation_metrics_missing"
    return {
        "available": bool(available),
        "unavailable_reason": unavailable_reason,
        "boundary_f1": boundary_f1,
        "boundary_false_positive_count": boundary_false_positive_count,
        "boundary_missed_count": boundary_missed_count,
        "error_taxonomy_bucket_counts": bucket_counts,
    }


def _single_book_eval_gold_adaptation_summary(
    eval_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(eval_report, dict):
        return {
            "applied": False,
            "mode": "off",
            "coverage_ratio": None,
            "ambiguous_gold_blocks": None,
            "unresolved_gold_blocks": None,
            "confidence_counts": {},
            "unavailable_reason": "eval_report_unavailable",
        }
    diagnostics_payload = eval_report.get("diagnostics")
    adaptation_payload = (
        diagnostics_payload.get("gold_adaptation")
        if isinstance(diagnostics_payload, dict)
        else None
    )
    if not isinstance(adaptation_payload, dict):
        return {
            "applied": False,
            "mode": "off",
            "coverage_ratio": None,
            "ambiguous_gold_blocks": None,
            "unresolved_gold_blocks": None,
            "confidence_counts": {},
            "unavailable_reason": "gold_adaptation_not_present_in_eval_report",
        }
    confidence_counts_payload = adaptation_payload.get("confidence_counts")
    confidence_counts: dict[str, int] = {}
    if isinstance(confidence_counts_payload, dict):
        for key, value in sorted(confidence_counts_payload.items()):
            name = str(key or "").strip()
            parsed = _single_book_nonnegative_int_or_none(value)
            if not name or parsed is None:
                continue
            confidence_counts[name] = parsed
    return {
        "applied": True,
        "mode": str(adaptation_payload.get("mode") or "auto").strip() or "auto",
        "coverage_ratio": _report_optional_metric(adaptation_payload.get("coverage_ratio")),
        "ambiguous_gold_blocks": _single_book_nonnegative_int_or_none(
            adaptation_payload.get("ambiguous_gold_blocks")
        ),
        "unresolved_gold_blocks": _single_book_nonnegative_int_or_none(
            adaptation_payload.get("unresolved_gold_blocks")
        ),
        "confidence_counts": confidence_counts,
        "unavailable_reason": None,
    }


def _build_single_book_variant_diagnostics(
    *,
    codex_eval_report: dict[str, Any] | None,
    vanilla_eval_report: dict[str, Any] | None,
) -> dict[str, Any]:
    variant_rows: dict[str, dict[str, Any]] = {}
    for variant_slug, eval_report in (
        ("vanilla", vanilla_eval_report),
        ("codex-exec", codex_eval_report),
    ):
        strict_accuracy = _benchmark_report_metric_value(
            eval_report if isinstance(eval_report, dict) else None,
            "strict_accuracy",
        )
        macro_f1 = _benchmark_report_metric_value(
            eval_report if isinstance(eval_report, dict) else None,
            "macro_f1_excluding_other",
        )
        classification_error_rate = (
            max(0.0, 1.0 - strict_accuracy) if strict_accuracy is not None else None
        )
        practical_error_rate = (
            max(0.0, 1.0 - macro_f1) if macro_f1 is not None else None
        )
        segmentation_summary = _single_book_eval_segmentation_summary(eval_report)
        boundary_f1 = _report_optional_metric(segmentation_summary.get("boundary_f1"))
        segmentation_boundary_error_rate = (
            max(0.0, 1.0 - boundary_f1) if boundary_f1 is not None else None
        )
        adaptation_summary = _single_book_eval_gold_adaptation_summary(eval_report)
        variant_rows[variant_slug] = {
            "strict_accuracy": strict_accuracy,
            "macro_f1_excluding_other": macro_f1,
            "classification_error_rate": classification_error_rate,
            "practical_error_rate": practical_error_rate,
            "segmentation": segmentation_summary,
            "segmentation_boundary_error_rate": segmentation_boundary_error_rate,
            "gold_adaptation": adaptation_summary,
        }

    codex_row = variant_rows.get("codex-exec") or {}
    vanilla_row = variant_rows.get("vanilla") or {}
    codex_seg = codex_row.get("segmentation")
    vanilla_seg = vanilla_row.get("segmentation")
    codex_adaptation = codex_row.get("gold_adaptation")
    vanilla_adaptation = vanilla_row.get("gold_adaptation")
    codex_confidence_counts = (
        codex_adaptation.get("confidence_counts")
        if isinstance(codex_adaptation, dict)
        and isinstance(codex_adaptation.get("confidence_counts"), dict)
        else {}
    )
    vanilla_confidence_counts = (
        vanilla_adaptation.get("confidence_counts")
        if isinstance(vanilla_adaptation, dict)
        and isinstance(vanilla_adaptation.get("confidence_counts"), dict)
        else {}
    )

    confidence_count_deltas: dict[str, int] = {}
    confidence_count_keys = sorted(
        set(str(key) for key in codex_confidence_counts.keys())
        | set(str(key) for key in vanilla_confidence_counts.keys())
    )
    for key in confidence_count_keys:
        codex_value = _single_book_nonnegative_int_or_none(
            codex_confidence_counts.get(key)
        )
        vanilla_value = _single_book_nonnegative_int_or_none(
            vanilla_confidence_counts.get(key)
        )
        if codex_value is None or vanilla_value is None:
            continue
        confidence_count_deltas[key] = codex_value - vanilla_value

    deltas: dict[str, Any] = {
        "classification_error_rate_delta": _single_book_optional_delta(
            codex_row.get("classification_error_rate"),
            vanilla_row.get("classification_error_rate"),
        ),
        "practical_error_rate_delta": _single_book_optional_delta(
            codex_row.get("practical_error_rate"),
            vanilla_row.get("practical_error_rate"),
        ),
        "segmentation_boundary_error_rate_delta": _single_book_optional_delta(
            codex_row.get("segmentation_boundary_error_rate"),
            vanilla_row.get("segmentation_boundary_error_rate"),
        ),
        "segmentation_boundary_f1_delta": _single_book_optional_delta(
            (
                codex_seg.get("boundary_f1")
                if isinstance(codex_seg, dict)
                else None
            ),
            (
                vanilla_seg.get("boundary_f1")
                if isinstance(vanilla_seg, dict)
                else None
            ),
        ),
        "gold_adaptation_coverage_ratio_delta": _single_book_optional_delta(
            (
                codex_adaptation.get("coverage_ratio")
                if isinstance(codex_adaptation, dict)
                else None
            ),
            (
                vanilla_adaptation.get("coverage_ratio")
                if isinstance(vanilla_adaptation, dict)
                else None
            ),
        ),
        "gold_adaptation_ambiguous_delta": _single_book_optional_delta(
            (
                codex_adaptation.get("ambiguous_gold_blocks")
                if isinstance(codex_adaptation, dict)
                else None
            ),
            (
                vanilla_adaptation.get("ambiguous_gold_blocks")
                if isinstance(vanilla_adaptation, dict)
                else None
            ),
        ),
        "gold_adaptation_unresolved_delta": _single_book_optional_delta(
            (
                codex_adaptation.get("unresolved_gold_blocks")
                if isinstance(codex_adaptation, dict)
                else None
            ),
            (
                vanilla_adaptation.get("unresolved_gold_blocks")
                if isinstance(vanilla_adaptation, dict)
                else None
            ),
        ),
        "gold_adaptation_confidence_count_deltas": confidence_count_deltas,
    }

    abs_classification_delta = (
        abs(float(deltas["classification_error_rate_delta"]))
        if deltas["classification_error_rate_delta"] is not None
        else None
    )
    abs_segmentation_delta = (
        abs(float(deltas["segmentation_boundary_error_rate_delta"]))
        if deltas["segmentation_boundary_error_rate_delta"] is not None
        else None
    )
    likely_driver = "insufficient_data"
    rationale = (
        "Segmentation boundary metrics were not available in one or both variant eval reports."
    )
    if abs_classification_delta is not None and abs_segmentation_delta is not None:
        if abs_classification_delta <= 1e-6 and abs_segmentation_delta <= 1e-6:
            likely_driver = "no_material_change"
            rationale = (
                "Both classification and segmentation error-rate deltas were near zero."
            )
        elif abs_segmentation_delta >= max(0.005, abs_classification_delta * 1.25):
            likely_driver = "segmentation_driven"
            rationale = (
                "Segmentation boundary error-rate delta dominated classification error-rate delta."
            )
        elif abs_classification_delta >= max(0.005, abs_segmentation_delta * 1.25):
            likely_driver = "classification_driven"
            rationale = (
                "Classification error-rate delta dominated segmentation boundary error-rate delta."
            )
        else:
            likely_driver = "mixed"
            rationale = (
                "Classification and segmentation deltas were both present and comparable in magnitude."
            )
    elif abs_classification_delta is not None:
        likely_driver = "classification_signal_only"
        rationale = (
            "Only classification deltas were available; segmentation deltas were unavailable."
        )
    elif abs_segmentation_delta is not None:
        likely_driver = "segmentation_signal_only"
        rationale = (
            "Only segmentation deltas were available; classification deltas were unavailable."
        )

    return {
        "schema_version": "single_book_variant_diagnostics.v1",
        "variants": variant_rows,
        "deltas": deltas,
        "likely_driver": likely_driver,
        "likely_driver_rationale": rationale,
    }


def _format_single_book_comparison_markdown(
    payload: dict[str, Any],
) -> str:
    run_timestamp = str(payload.get("run_timestamp") or "").strip() or "unknown"
    source_file = str(payload.get("source_file") or "").strip() or "unknown"

    variants_payload = payload.get("variants")
    if isinstance(variants_payload, dict):
        codex_dir = str(
            ((variants_payload.get("codex-exec") or {}).get("eval_output_dir"))
            or ""
        ).strip()
        vanilla_dir = str(
            ((variants_payload.get("vanilla") or {}).get("eval_output_dir"))
            or ""
        ).strip()
    else:
        codex_dir = ""
        vanilla_dir = ""

    metrics_payload = payload.get("metrics")
    if isinstance(metrics_payload, dict):
        codex_metrics = metrics_payload.get("codex-exec")
        vanilla_metrics = metrics_payload.get("vanilla")
    else:
        codex_metrics = None
        vanilla_metrics = None

    deltas_payload = payload.get("deltas")
    if isinstance(deltas_payload, dict):
        delta_metrics = deltas_payload.get("codex_minus_vanilla")
    else:
        delta_metrics = None
    metadata_payload = payload.get("metadata")
    split_cache_payload = None
    codex_runtime_payload = None
    per_label_breakdown_payload = None
    variant_diagnostics_payload = None
    if isinstance(metadata_payload, dict):
        split_cache_payload = metadata_payload.get("single_book_split_cache")
        codex_runtime_payload = metadata_payload.get("codex_farm_runtime")
        per_label_breakdown_payload = metadata_payload.get("per_label_breakdown")
        variant_diagnostics_payload = metadata_payload.get("variant_diagnostics")

    codex_model = ""
    codex_reasoning_effort = ""
    if isinstance(codex_runtime_payload, dict):
        codex_model = (
            str(codex_runtime_payload.get("codex_model") or "").strip()
        )
        codex_reasoning_effort = (
            str(codex_runtime_payload.get("codex_reasoning_effort") or "").strip()
        )

    metric_rows: list[tuple[str, str, str, str]] = []
    for metric_name, display_name in SINGLE_BOOK_COMPARISON_METRICS:
        codex_value = _benchmark_report_metric_value(
            codex_metrics if isinstance(codex_metrics, dict) else None,
            metric_name,
        )
        vanilla_value = _benchmark_report_metric_value(
            vanilla_metrics if isinstance(vanilla_metrics, dict) else None,
            metric_name,
        )
        delta_value = _benchmark_report_metric_value(
            delta_metrics if isinstance(delta_metrics, dict) else None,
            metric_name,
        )
        if delta_value is None and codex_value is not None and vanilla_value is not None:
            delta_value = codex_value - vanilla_value
        metric_rows.append(
            (
                f"`{display_name}`",
                f"{codex_value:.6f}" if codex_value is not None else "null",
                f"{vanilla_value:.6f}" if vanilla_value is not None else "null",
                f"{delta_value:.6f}" if delta_value is not None else "null",
            )
        )

    metric_col_width = max(len("Metric"), *(len(row[0]) for row in metric_rows))
    codex_col_width = max(len("Codex Exec"), *(len(row[1]) for row in metric_rows))
    vanilla_col_width = max(len("Vanilla"), *(len(row[2]) for row in metric_rows))
    delta_col_width = max(
        len("Codex - Vanilla"),
        *(len(row[3]) for row in metric_rows),
    )
    lines: list[str] = [
        "# Codex Exec vs Vanilla Comparison",
        "",
        f"- Schema version: {SINGLE_BOOK_COMPARISON_SCHEMA_VERSION}",
        f"- Run timestamp: {run_timestamp}",
        f"- Source file: {source_file}",
        f"- Codex model: {codex_model or 'unknown'}",
        f"- Codex reasoning effort: {codex_reasoning_effort or 'unknown'}",
        f"- Codex eval directory: {codex_dir or 'unknown'}",
        f"- Vanilla eval directory: {vanilla_dir or 'unknown'}",
        "",
        (
            f"| {'Metric':<{metric_col_width}}"
            f" | {'Codex Exec':>{codex_col_width}}"
            f" | {'Vanilla':>{vanilla_col_width}}"
            f" | {'Codex - Vanilla':>{delta_col_width}} |"
        ),
        (
            f"| {'-' * max(metric_col_width, 3)}"
            f" | {'-' * (max(codex_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(vanilla_col_width, 3) - 1) + ':'}"
            f" | {'-' * (max(delta_col_width, 3) - 1) + ':'} |"
        ),
    ]
    for metric_text, codex_text, vanilla_text, delta_text in metric_rows:
        lines.append(
            f"| {metric_text:<{metric_col_width}}"
            f" | {codex_text:>{codex_col_width}}"
            f" | {vanilla_text:>{vanilla_col_width}}"
            f" | {delta_text:>{delta_col_width}} |"
        )
    if isinstance(variant_diagnostics_payload, dict):
        likely_driver = (
            str(variant_diagnostics_payload.get("likely_driver") or "").strip()
            or "unknown"
        )
        rationale = (
            str(variant_diagnostics_payload.get("likely_driver_rationale") or "").strip()
            or "No rationale provided."
        )
        deltas_payload = variant_diagnostics_payload.get("deltas")
        delta_rows = deltas_payload if isinstance(deltas_payload, dict) else {}

        def _format_optional_number(value: Any, *, digits: int = 6) -> str:
            number = _report_optional_metric(value)
            if number is None:
                return "null"
            return f"{number:.{digits}f}"

        lines.extend(
            [
                "",
                "## Delta Attribution",
                "",
                f"- Likely dominant driver: `{likely_driver}`",
                f"- Rationale: {rationale}",
                "- Deltas (`codex - vanilla`): "
                f"classification_error_rate={_format_optional_number(delta_rows.get('classification_error_rate_delta'))}, "
                f"segmentation_boundary_error_rate={_format_optional_number(delta_rows.get('segmentation_boundary_error_rate_delta'))}, "
                f"gold_adaptation_coverage_ratio={_format_optional_number(delta_rows.get('gold_adaptation_coverage_ratio_delta'))}",
            ]
        )
        confidence_deltas = delta_rows.get("gold_adaptation_confidence_count_deltas")
        if isinstance(confidence_deltas, dict) and confidence_deltas:
            confidence_summary = ", ".join(
                f"{str(key)}={int(value)}"
                for key, value in sorted(confidence_deltas.items())
            )
            lines.append(
                "- Gold adaptation confidence deltas (`codex - vanilla`): "
                + confidence_summary
            )

        variant_rows = (
            variant_diagnostics_payload.get("variants")
            if isinstance(variant_diagnostics_payload.get("variants"), dict)
            else {}
        )
        for variant_slug in ("vanilla", "codex-exec"):
            row = variant_rows.get(variant_slug)
            if not isinstance(row, dict):
                continue
            segmentation_payload = (
                row.get("segmentation")
                if isinstance(row.get("segmentation"), dict)
                else {}
            )
            adaptation_payload = (
                row.get("gold_adaptation")
                if isinstance(row.get("gold_adaptation"), dict)
                else {}
            )
            confidence_counts = (
                adaptation_payload.get("confidence_counts")
                if isinstance(adaptation_payload.get("confidence_counts"), dict)
                else {}
            )
            if confidence_counts:
                confidence_summary = ", ".join(
                    f"{str(key)}={int(value)}"
                    for key, value in sorted(confidence_counts.items())
                )
            else:
                confidence_summary = "none"
            lines.append(
                f"- {variant_slug}: "
                f"classification_error_rate={_format_optional_number(row.get('classification_error_rate'))}, "
                f"segmentation_boundary_error_rate={_format_optional_number(row.get('segmentation_boundary_error_rate'))}, "
                f"segmentation_boundary_f1={_format_optional_number(segmentation_payload.get('boundary_f1'))}, "
                f"gold_adaptation_coverage_ratio={_format_optional_number(adaptation_payload.get('coverage_ratio'))}, "
                f"gold_adaptation_mode={str(adaptation_payload.get('mode') or 'off')}, "
                f"gold_adaptation_confidence={confidence_summary}"
            )
    if isinstance(per_label_breakdown_payload, dict):
        lines.extend(
            _single_book_per_label_breakdown_markdown_lines(
                per_label_breakdown_payload=per_label_breakdown_payload,
                heading_level=2,
                intro_text=(
                    "Per label: precision answers false alarms, recall answers misses. "
                    "Values aggregate all benchmark records with the latest run timestamp."
                ),
            )
        )

    if isinstance(split_cache_payload, dict):
        shared_key = str(split_cache_payload.get("shared_key") or "").strip()
        variant_payload = split_cache_payload.get("variants")
        lines.extend(
            [
                "",
                "## Shared Split Cache",
                "",
                f"- Schema version: {split_cache_payload.get('schema_version') or 'unknown'}",
                f"- Shared key: {shared_key or 'unknown'}",
            ]
        )
        if isinstance(variant_payload, dict):
            for variant_slug in ("vanilla", "codex-exec"):
                row = variant_payload.get(variant_slug)
                if not isinstance(row, dict):
                    continue
                mode = str(row.get("mode") or "").strip() or "off"
                hit_text = "yes" if bool(row.get("hit")) else "no"
                conversion_seconds = _report_optional_metric(row.get("conversion_seconds"))
                conversion_text = (
                    f"{conversion_seconds:.3f}s"
                    if conversion_seconds is not None
                    else "unknown"
                )
                lines.append(
                    f"- {variant_slug}: mode={mode} cache_hit={hit_text} conversion={conversion_text}"
                )

    return "\n".join(lines) + "\n"


def _write_single_book_comparison_artifacts(
    *,
    run_timestamp: str,
    session_root: Path,
    source_file: str | None,
    codex_eval_output_dir: Path,
    vanilla_eval_output_dir: Path,
    split_cache_metadata: dict[str, Any] | None = None,
    write_markdown: bool = True,
    write_starter_pack: bool = False,
) -> tuple[Path, Path | None] | None:
    codex_eval_report = _load_json_dict(codex_eval_output_dir / "eval_report.json")
    vanilla_eval_report = _load_json_dict(vanilla_eval_output_dir / "eval_report.json")
    if codex_eval_report is None or vanilla_eval_report is None:
        return None
    codex_metrics = _single_book_eval_metrics_from_report(codex_eval_report)
    vanilla_metrics = _single_book_eval_metrics_from_report(vanilla_eval_report)

    comparison_payload = {
        "schema_version": SINGLE_BOOK_COMPARISON_SCHEMA_VERSION,
        "run_timestamp": run_timestamp,
        "source_file": source_file,
        "variants": {
            "codex-exec": {"eval_output_dir": str(codex_eval_output_dir)},
            "vanilla": {"eval_output_dir": str(vanilla_eval_output_dir)},
        },
        "metrics": {
            "codex-exec": codex_metrics,
            "vanilla": vanilla_metrics,
        },
        "deltas": {
            "codex_minus_vanilla": _single_book_metric_deltas(
                codex_metrics=codex_metrics,
                vanilla_metrics=vanilla_metrics,
            )
        },
    }
    metadata_payload: dict[str, Any] = {}
    codex_runtime_payload = _load_single_book_codex_farm_runtime(codex_eval_output_dir)
    if isinstance(codex_runtime_payload, dict):
        metadata_payload["codex_farm_runtime"] = codex_runtime_payload
    per_label_breakdown = _build_single_book_per_label_breakdown(
        run_timestamp=run_timestamp,
        eval_reports=(vanilla_eval_report, codex_eval_report),
    )
    variant_diagnostics = _build_single_book_variant_diagnostics(
        codex_eval_report=codex_eval_report,
        vanilla_eval_report=vanilla_eval_report,
    )
    metadata_payload["variant_diagnostics"] = variant_diagnostics
    if isinstance(per_label_breakdown, dict):
        metadata_payload["per_label_breakdown"] = per_label_breakdown
    if isinstance(split_cache_metadata, dict):
        metadata_payload["single_book_split_cache"] = split_cache_metadata
    if write_starter_pack:
        starter_pack_dir = _write_single_book_starter_pack(session_root=session_root)
        if starter_pack_dir is not None:
            metadata_payload["starter_pack_v1"] = {
                "path": str(starter_pack_dir),
                "relative_path": "starter_pack_v1",
                "manifest_file": "starter_pack_v1/10_process_manifest.json",
            }
            flattened_summary_path = session_root / "benchmark_summary.md"
            if flattened_summary_path.is_file():
                metadata_payload["flattened_summary"] = {
                    "path": str(flattened_summary_path),
                    "relative_path": "benchmark_summary.md",
                }
    if metadata_payload:
        comparison_payload["metadata"] = metadata_payload
    comparison_json_path = session_root / "codex_vs_vanilla_comparison.json"
    comparison_md_path = session_root / "codex_vs_vanilla_comparison.md"
    comparison_json_path.write_text(
        json.dumps(comparison_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if write_markdown:
        comparison_md_path.write_text(
            _format_single_book_comparison_markdown(comparison_payload),
            encoding="utf-8",
        )
    else:
        comparison_md_path.unlink(missing_ok=True)
        comparison_md_path = None
    return comparison_json_path, comparison_md_path
