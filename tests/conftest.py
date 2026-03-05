from __future__ import annotations

import os

import pytest

_FORCE_VERBOSE_OUTPUT_ENV = "COOKIMPORT_PYTEST_VERBOSE_OUTPUT"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}

_FILE_MARKERS: dict[str, tuple[str, ...]] = {
    "test_atoms.py": ("core", "parsing"),
    "test_bench.py": ("bench",),
    "test_bench_quality_cli.py": ("bench",),
    "test_bench_speed_cli.py": ("bench",),
    "test_benchmark_gc.py": ("bench", "cli", "analytics"),
    "test_benchmark_csv_backfill_cli.py": ("analytics", "bench", "cli"),
    "test_benchmark_cutdown_for_external_ai.py": ("bench",),
    "test_cutdown_export_consistency.py": ("bench",),
    "test_canonical_alignment_cache.py": ("bench",),
    "test_canonical_line_roles.py": ("parsing", "llm"),
    "test_c3imp_interactive_menu.py": ("cli",),
    "test_compare_control_cli.py": ("analytics", "cli"),
    "test_compare_control_engine.py": ("analytics",),
    "test_dashboard_state_server.py": ("analytics",),
    "test_chunks.py": ("parsing",),
    "test_classifier.py": ("tagging",),
    "test_cleaning_epub.py": ("parsing",),
    "test_cli_limits.py": ("cli",),
    "test_cli_llm_flags.py": ("cli", "llm"),
    "test_cli_output_structure_fast.py": ("cli", "llm", "labelstudio"),
    "test_cli_output_structure_epub_fast.py": ("cli", "staging", "ingestion"),
    "test_cli_output_structure_text_fast.py": ("cli", "staging", "ingestion"),
    "test_cli_output_structure_slow.py": ("cli", "staging", "ingestion"),
    "test_run_settings_adapters.py": ("cli",),
    "test_codex_farm_contracts.py": ("llm",),
    "test_codex_farm_knowledge_orchestrator.py": ("llm",),
    "test_codex_farm_orchestrator.py": ("llm",),
    "test_codex_farm_orchestrator_runner_transport.py": ("llm",),
    "test_codex_farm_orchestrator_stage_integration.py": ("llm",),
    "test_codex_farm_transport.py": ("llm",),
    "test_codex_bridge_projection_policy.py": ("bench",),
    "test_evidence_normalizer.py": ("llm",),
    "test_draft_v1_lowercase.py": ("staging",),
    "test_draft_v1_priority6.py": ("staging",),
    "test_draft_v1_staging_alignment.py": ("staging",),
    "test_draft_v1_variants.py": ("staging",),
    "test_docs_plans_policy.py": ("core",),
    "test_epub_debug_cli.py": ("cli", "ingestion"),
    "test_epub_debug_extract_cli.py": ("cli", "ingestion"),
    "test_epub_extraction_quickwins.py": ("ingestion", "parsing"),
    "test_eval_stage_blocks.py": ("bench", "staging"),
    "test_eval_metrics_label_accounting.py": ("labelstudio", "bench"),
    "test_eval_freeform_practical_metrics.py": ("labelstudio", "bench"),
    "test_epub_html_normalize.py": ("parsing",),
    "test_epub_importer.py": ("ingestion",),
    "test_epub_job_merge.py": ("ingestion", "staging"),
    "test_excel_importer.py": ("ingestion",),
    "test_ingredient_parser.py": ("parsing",),
    "test_instruction_parser.py": ("parsing",),
    "test_joblib_runtime.py": ("core",),
    "test_yield_extraction.py": ("parsing",),
    "test_knowledge_job_bundles.py": ("llm",),
    "test_knowledge_output_ingest.py": ("llm",),
    "test_knowledge_writer.py": ("llm",),
    "test_labelstudio_benchmark_helpers.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_eval_payload.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_progress.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_scheduler.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_single_profile.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_export.py": ("labelstudio",),
    "test_labelstudio_freeform.py": ("labelstudio",),
    "test_labelstudio_import_naming.py": ("labelstudio",),
    "test_labelstudio_ingest_parallel.py": ("labelstudio", "ingestion"),
    "test_canonical_line_projection.py": ("labelstudio", "parsing"),
    "test_labelstudio_prelabel.py": ("labelstudio", "llm"),
    "test_labelstudio_prelabel_codex_cli.py": ("labelstudio", "llm"),
    "test_llm_pipeline_pack.py": ("llm",),
    "test_llm_pipeline_pack_assets.py": ("llm",),
    "test_markdown_blocks.py": ("parsing",),
    "test_multi_recipe_splitter.py": ("parsing",),
    "test_non_recipe_spans.py": ("parsing",),
    "test_paprika_importer.py": ("ingestion",),
    "test_paprika_merge.py": ("ingestion",),
    "test_pdf_importer.py": ("ingestion",),
    "test_pdf_importer_ocr_slow.py": ("ingestion",),
    "test_pdf_job_merge.py": ("ingestion", "staging"),
    "test_perf_report.py": ("analytics",),
    "test_performance_features.py": ("ingestion",),
    "test_phase1_manual.py": ("core",),
    "test_prediction_records.py": ("bench",),
    "test_progress_messages.py": ("bench",),
    "test_quality_suite_compare.py": ("bench",),
    "test_quality_suite_discovery.py": ("bench",),
    "test_quality_eta.py": ("bench",),
    "test_quality_lightweight_series.py": ("bench",),
    "test_quality_leaderboard.py": ("bench",),
    "test_quality_top_tier_tournament.py": ("bench",),
    "test_quality_suite_runner.py": ("bench",),
    "test_recipe_sections.py": ("parsing",),
    "test_recipe_block_atomizer.py": ("parsing",),
    "test_recipe_likeness_scoring.py": ("core",),
    "test_recipesage_importer.py": ("ingestion",),
    "test_run_manifest_parity.py": ("staging", "llm"),
    "test_run_settings.py": ("llm", "cli"),
    "test_section_detector.py": ("parsing",),
    "test_section_outputs.py": ("staging", "parsing"),
    "test_segmentation_metrics.py": ("bench",),
    "test_sequence_matcher_dropin_parity.py": ("bench",),
    "test_speed_suite_compare.py": ("bench",),
    "test_speed_suite_discovery.py": ("bench",),
    "test_speed_suite_runner.py": ("bench",),
    "test_source_field.py": ("parsing",),
    "test_schemaorg_ingest.py": ("parsing",),
    "test_split_merge_status.py": ("staging", "bench"),
    "test_stats_dashboard.py": ("analytics",),
    "test_stats_dashboard_slow.py": ("analytics",),
    "test_stage_block_predictions.py": ("staging", "bench"),
    "test_stage_progress_dashboard.py": ("cli", "staging"),
    "test_step_ingredient_linking.py": ("parsing",),
    "test_step_ingredient_linking_semantic.py": ("parsing",),
    "test_step_segmentation.py": ("parsing",),
    "test_tagging.py": ("tagging",),
    "test_tables.py": ("parsing",),
    "test_text_importer.py": ("ingestion",),
    "test_tip_extraction.py": ("parsing",),
    "test_tip_recipe_notes.py": ("parsing",),
    "test_tip_writer.py": ("staging", "parsing"),
    "test_progress_dashboard.py": ("core",),
    "test_unstructured_adapter.py": ("ingestion",),
    "test_webschema_importer.py": ("ingestion",),
    "test_writer_overrides.py": ("llm", "staging"),
}

_SLOW_FILES = {
    "test_cli_output_structure_slow.py",
    "test_codex_farm_orchestrator.py",
    "test_codex_farm_orchestrator_runner_transport.py",
    "test_labelstudio_benchmark_helpers_eval_payload.py",
    "test_labelstudio_benchmark_helpers_scheduler.py",
    "test_pdf_importer_ocr_slow.py",
    "test_stats_dashboard_slow.py",
}

_SMOKE_FILES = {
    "test_atoms.py",
    "test_classifier.py",
    "test_cli_limits.py",
    "test_compare_control_cli.py",
    "test_compare_control_engine.py",
    "test_draft_v1_lowercase.py",
    "test_benchmark_cutdown_for_external_ai.py",
    "test_dashboard_state_server.py",
    "test_knowledge_output_ingest.py",
    "test_labelstudio_import_naming.py",
    "test_llm_pipeline_pack.py",
    "test_evidence_normalizer.py",
    "test_non_recipe_spans.py",
    "test_perf_report.py",
    "test_prediction_records.py",
    "test_run_settings_adapters.py",
    "test_schemaorg_ingest.py",
    "test_source_field.py",
    "test_step_segmentation.py",
    "test_webschema_importer.py",
}

_LOG_HINTS = {
    "analytics": "docs/08-analytics/08-analytics_log.md",
    "bench": "docs/07-bench/07-bench_log.md",
    "cli": "docs/02-cli/02-cli_log.md",
    "core": "docs/01-architecture/01-architecture_log.md",
    "ingestion": "docs/03-ingestion/03-ingestion_log.md",
    "labelstudio": "docs/06-label-studio/06-label-studio_log.md",
    "llm": "docs/10-llm/10-llm_log.md",
    "parsing": "docs/04-parsing/04-parsing_log.md",
    "staging": "docs/05-staging/05-staging_log.md",
    "tagging": "docs/09-tagging/09-tagging_log.md",
}

_FAILED_MARKERS: set[str] = set()
_HINTS_EMITTED = False


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in _TRUTHY_ENV_VALUES


def pytest_configure(config: pytest.Config) -> None:
    if _env_truthy(_FORCE_VERBOSE_OUTPUT_ENV):
        return
    # Enforce compact output even when callers pass `-o addopts=''`.
    config.option.no_header = True
    config.option.no_summary = True
    config.option.disable_warnings = True
    config.option.verbose = min(getattr(config.option, "verbose", 0), -1)
    terminalreporter = config.pluginmanager.get_plugin("terminalreporter")
    if terminalreporter is not None:
        terminalreporter.showheader = False
        terminalreporter.no_header = True
        terminalreporter.no_summary = True
        terminalreporter.verbosity = min(getattr(terminalreporter, "verbosity", 0), -1)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        file_name = item.path.name
        marker_names = _FILE_MARKERS.get(file_name, ("core",))
        for marker_name in marker_names:
            item.add_marker(getattr(pytest.mark, marker_name))
        if file_name in _SLOW_FILES:
            item.add_marker(pytest.mark.slow)
        if file_name in _SMOKE_FILES:
            item.add_marker(pytest.mark.smoke)


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    if report.when != "call":
        return None
    # Keep pass/skip accounting, but suppress per-test progress glyphs.
    if report.passed:
        return "passed", "", "PASSED"
    if report.skipped:
        if hasattr(report, "wasxfail"):
            return "xfailed", "", "XFAILED"
        return "skipped", "", "SKIPPED"
    return None


def _emit_failure_hints(terminalreporter) -> None:
    global _HINTS_EMITTED
    if _HINTS_EMITTED:
        return
    hinted_markers = _FAILED_MARKERS or {"core"}
    terminalreporter.write_line("")
    for marker_name in sorted(hinted_markers):
        terminalreporter.write_line(f"log: {_LOG_HINTS[marker_name]}")
    terminalreporter.write_line(
        "verbose: COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest -o addopts='' -vv --tb=short --show-capture=all --assert=rewrite <failing_test>"
    )
    _HINTS_EMITTED = True


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not report.failed or report.when == "teardown":
        return
    for marker_name in _LOG_HINTS:
        if marker_name in report.keywords:
            _FAILED_MARKERS.add(marker_name)


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    if exitstatus != 0:
        _emit_failure_hints(terminalreporter)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus == 0:
        return
    terminalreporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminalreporter is not None:
        _emit_failure_hints(terminalreporter)
