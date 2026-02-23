from __future__ import annotations

import pytest

_FILE_MARKERS: dict[str, tuple[str, ...]] = {
    "test_atoms.py": ("core", "parsing"),
    "test_bench.py": ("bench",),
    "test_bench_progress.py": ("bench",),
    "test_benchmark_csv_backfill_cli.py": ("analytics", "bench", "cli"),
    "test_c3imp_interactive_menu.py": ("cli",),
    "test_chunks.py": ("parsing",),
    "test_classifier.py": ("tagging",),
    "test_cleaning_epub.py": ("parsing",),
    "test_cli_limits.py": ("cli",),
    "test_cli_llm_flags.py": ("cli", "llm"),
    "test_cli_output_structure.py": ("cli", "staging", "ingestion"),
    "test_codex_farm_contracts.py": ("llm",),
    "test_codex_farm_knowledge_orchestrator.py": ("llm",),
    "test_codex_farm_orchestrator.py": ("llm",),
    "test_draft_v1_lowercase.py": ("staging",),
    "test_draft_v1_staging_alignment.py": ("staging",),
    "test_draft_v1_variants.py": ("staging",),
    "test_epub_auto_select.py": ("ingestion",),
    "test_epub_debug_cli.py": ("cli", "ingestion"),
    "test_epub_debug_extract_cli.py": ("cli", "ingestion"),
    "test_epub_extraction_quickwins.py": ("ingestion", "parsing"),
    "test_epub_html_normalize.py": ("parsing",),
    "test_epub_importer.py": ("ingestion",),
    "test_epub_job_merge.py": ("ingestion", "staging"),
    "test_excel_importer.py": ("ingestion",),
    "test_extraction_quality.py": ("ingestion",),
    "test_ingredient_parser.py": ("parsing",),
    "test_instruction_parser.py": ("parsing",),
    "test_knowledge_job_bundles.py": ("llm",),
    "test_knowledge_output_ingest.py": ("llm",),
    "test_knowledge_writer.py": ("llm",),
    "test_labelstudio_benchmark_helpers.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_canonical.py": ("labelstudio",),
    "test_labelstudio_chunking.py": ("labelstudio", "parsing"),
    "test_labelstudio_export.py": ("labelstudio",),
    "test_labelstudio_freeform.py": ("labelstudio",),
    "test_labelstudio_import_naming.py": ("labelstudio",),
    "test_labelstudio_ingest_parallel.py": ("labelstudio", "ingestion"),
    "test_labelstudio_prelabel.py": ("labelstudio", "llm"),
    "test_llm_pipeline_pack.py": ("llm",),
    "test_llm_pipeline_pack_assets.py": ("llm",),
    "test_markdown_blocks.py": ("parsing",),
    "test_non_recipe_spans.py": ("parsing",),
    "test_paprika_importer.py": ("ingestion",),
    "test_paprika_merge.py": ("ingestion",),
    "test_pdf_importer.py": ("ingestion",),
    "test_pdf_job_merge.py": ("ingestion", "staging"),
    "test_perf_report.py": ("analytics",),
    "test_performance_features.py": ("ingestion",),
    "test_phase1_manual.py": ("core",),
    "test_progress_messages.py": ("bench",),
    "test_recipesage_importer.py": ("ingestion",),
    "test_run_manifest_parity.py": ("staging", "llm"),
    "test_run_settings.py": ("llm", "cli"),
    "test_source_field.py": ("parsing",),
    "test_split_merge_status.py": ("staging", "bench"),
    "test_stats_dashboard.py": ("analytics",),
    "test_step_ingredient_linking.py": ("parsing",),
    "test_tagging.py": ("tagging",),
    "test_text_importer.py": ("ingestion",),
    "test_tip_extraction.py": ("parsing",),
    "test_tip_recipe_notes.py": ("parsing",),
    "test_tip_writer.py": ("staging", "parsing"),
    "test_toggle_editor.py": ("cli",),
    "test_unstructured_adapter.py": ("ingestion",),
    "test_writer_overrides.py": ("llm", "staging"),
}

_SLOW_FILES = {
    "test_bench.py",
    "test_cli_output_structure.py",
    "test_codex_farm_orchestrator.py",
    "test_epub_extraction_quickwins.py",
    "test_epub_importer.py",
    "test_labelstudio_benchmark_helpers.py",
    "test_labelstudio_freeform.py",
    "test_labelstudio_ingest_parallel.py",
    "test_labelstudio_prelabel.py",
    "test_phase1_manual.py",
    "test_stats_dashboard.py",
    "test_tagging.py",
    "test_unstructured_adapter.py",
}

_SMOKE_FILES = {
    "test_atoms.py",
    "test_classifier.py",
    "test_cli_limits.py",
    "test_draft_v1_lowercase.py",
    "test_knowledge_output_ingest.py",
    "test_labelstudio_import_naming.py",
    "test_llm_pipeline_pack.py",
    "test_non_recipe_spans.py",
    "test_perf_report.py",
    "test_source_field.py",
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


def _emit_failure_hints(terminalreporter) -> None:
    global _HINTS_EMITTED
    if _HINTS_EMITTED:
        return
    hinted_markers = _FAILED_MARKERS or {"core"}
    terminalreporter.write_line("")
    for marker_name in sorted(hinted_markers):
        terminalreporter.write_line(f"log: {_LOG_HINTS[marker_name]}")
    terminalreporter.write_line(
        "verbose: pytest -vv --tb=short --show-capture=all --assert=rewrite <failing_test>"
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
