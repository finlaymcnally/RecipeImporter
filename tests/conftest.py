from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest

_FORCE_VERBOSE_OUTPUT_ENV = "COOKIMPORT_PYTEST_VERBOSE_OUTPUT"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_TEST_SUITE_ENV = "COOKIMPORT_TEST_SUITE"
_RUNNING_UNDER_PYTEST_ENV = "COOKIMPORT_RUNNING_UNDER_PYTEST"
_DISABLE_HEAVY_TEST_SIDE_EFFECTS_ENV = "COOKIMPORT_DISABLE_HEAVY_TEST_SIDE_EFFECTS"
_ALLOW_HEAVY_TEST_SIDE_EFFECTS_ENV = "COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS"

_FILE_MARKERS: dict[str, tuple[str, ...]] = {
    "test_atoms.py": ("core", "parsing"),
    "test_bench.py": ("bench",),
    "test_bench_quality_cli.py": ("bench",),
    "test_bench_speed_cli.py": ("bench",),
    "test_benchmark_undefined_names.py": ("core", "bench", "cli"),
    "test_benchmark_gc.py": ("bench", "cli", "analytics"),
    "test_benchmark_csv_backfill_cli.py": ("analytics", "bench", "cli"),
    "test_benchmark_cutdown_for_external_ai.py": ("bench",),
    "test_benchmark_heavy_side_effects.py": ("bench",),
    "test_cutdown_export_consistency.py": ("bench",),
    "test_canonical_alignment_cache.py": ("bench",),
    "test_canonical_line_role_env.py": ("parsing", "llm"),
    "test_canonical_line_roles.py": ("parsing", "llm"),
    "test_c3imp_interactive_menu.py": ("cli",),
    "test_compare_control_cli.py": ("analytics", "cli"),
    "test_compare_control_engine.py": ("analytics",),
    "test_dashboard_state_server.py": ("analytics",),
    "test_chunks.py": ("parsing",),
    "test_cleaning_epub.py": ("parsing",),
    "test_cli_limits.py": ("cli",),
    "test_cli_command_resolution.py": ("cli",),
    "test_cli_llm_flags.py": ("cli", "llm"),
    "test_cli_output_structure_fast.py": ("cli", "llm", "labelstudio"),
    "test_cli_output_structure_epub_fast.py": ("cli", "staging", "ingestion"),
    "test_cli_output_structure_text_fast.py": ("cli", "staging", "ingestion"),
    "test_cli_output_structure_slow.py": ("cli", "staging", "ingestion"),
    "test_run_settings_adapters.py": ("cli",),
    "test_codex_farm_contracts.py": ("llm",),
    "test_codex_farm_knowledge_orchestrator.py": ("llm",),
    "test_codex_farm_knowledge_orchestrator_runtime.py": ("llm",),
    "test_knowledge_orchestrator_contracts.py": ("llm",),
    "test_knowledge_stage_bindings.py": ("llm",),
    "test_knowledge_orchestrator_runtime_progress.py": ("llm",),
    "test_knowledge_orchestrator_runtime_leasing.py": ("llm",),
    "test_codex_farm_orchestrator.py": ("llm",),
    "test_codex_farm_orchestrator_runner_transport.py": ("llm",),
    "test_codex_farm_orchestrator_stage_integration.py": ("llm",),
    "test_codex_bridge_projection_policy.py": ("bench",),
    "test_codex_exec_runner_workspace.py": ("llm",),
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
    "test_label_first_conversion.py": ("parsing", "staging"),
    "test_yield_extraction.py": ("parsing",),
    "test_knowledge_job_bundles.py": ("llm",),
    "test_llm_module_bindings.py": ("llm",),
    "test_knowledge_output_ingest.py": ("llm",),
    "test_knowledge_phase_workers.py": ("llm",),
    "test_knowledge_phase_workers_packets.py": ("llm",),
    "test_knowledge_prompt_builder.py": ("llm",),
    "test_knowledge_runtime_replay.py": ("llm",),
    "test_knowledge_workspace_tools_packets.py": ("llm",),
    "test_knowledge_writer.py": ("llm",),
    "test_label_phase_workers.py": ("llm", "parsing"),
    "test_labelstudio_benchmark_helpers_artifacts.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_eval_payload_artifacts.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_eval_payload_compare.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_eval_payload_execution.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_eval_payload_pipelined.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_export_selection.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_import_eval.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_interactive.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_progress.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_scheduler_multi_source.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_scheduler_planning.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_scheduler_global_queue.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_scheduler_prediction_reuse.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_scheduler_run_reports.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_scheduler_targets.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_smoke.py": ("labelstudio", "bench", "cli"),
    "test_labelstudio_benchmark_helpers_single_book_artifacts.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
    "test_labelstudio_benchmark_helpers_single_book_run.py": (
        "labelstudio",
        "bench",
        "cli",
    ),
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
    "test_pytest_output_guidance.py": ("core",),
    "test_prediction_records.py": ("bench",),
    "test_progress_messages.py": ("bench",),
    "test_quality_suite_compare.py": ("bench",),
    "test_quality_suite_discovery.py": ("bench",),
    "test_quality_eta.py": ("bench",),
    "test_quality_leaderboard.py": ("bench",),
    "test_quality_suite_runner.py": ("bench",),
    "test_recipe_sections.py": ("parsing",),
    "test_recipe_block_atomizer.py": ("parsing",),
    "test_recipe_span_grouping.py": ("parsing",),
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
    "test_cli_output_structure_epub_fast.py",
    "test_cli_output_structure_text_fast.py",
    "test_codex_farm_orchestrator.py",
    "test_codex_farm_orchestrator_runner_transport.py",
    "test_canonical_line_roles.py",
    "test_labelstudio_benchmark_helpers_eval_payload_artifacts.py",
    "test_labelstudio_benchmark_helpers_eval_payload_compare.py",
    "test_labelstudio_benchmark_helpers_eval_payload_execution.py",
    "test_labelstudio_benchmark_helpers_eval_payload_pipelined.py",
    "test_labelstudio_benchmark_helpers_scheduler_multi_source.py",
    "test_labelstudio_benchmark_helpers_scheduler_planning.py",
    "test_labelstudio_benchmark_helpers_scheduler_global_queue.py",
    "test_labelstudio_benchmark_helpers_scheduler_prediction_reuse.py",
    "test_labelstudio_benchmark_helpers_scheduler_run_reports.py",
    "test_labelstudio_benchmark_helpers_scheduler_targets.py",
    "test_labelstudio_benchmark_helpers_single_book_run.py",
    "test_performance_features.py",
    "test_pdf_importer_ocr_slow.py",
    "test_stats_dashboard.py",
    "test_stats_dashboard_slow.py",
}

_SMOKE_FILES = {
    "test_atoms.py",
    "test_cli_limits.py",
    "test_cli_command_resolution.py",
    "test_compare_control_cli.py",
    "test_compare_control_engine.py",
    "test_draft_v1_lowercase.py",
    "test_benchmark_cutdown_for_external_ai.py",
    "test_benchmark_undefined_names.py",
    "test_dashboard_state_server.py",
    "test_knowledge_output_ingest.py",
    "test_llm_module_bindings.py",
    "test_knowledge_stage_bindings.py",
    "test_labelstudio_benchmark_smoke.py",
    "test_labelstudio_import_naming.py",
    "test_llm_pipeline_pack.py",
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
}

_FAILED_MARKERS: set[str] = set()
_FAILED_NODEIDS: list[str] = []
_HINTS_EMITTED = False
_RAW_PYTEST_GUIDANCE_EMITTED = False
_VERBOSE_ENV_GUIDANCE_EMITTED = False


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in _TRUTHY_ENV_VALUES


def _looks_like_test_target(arg: str) -> bool:
    return arg.startswith("tests") or arg.endswith(".py")


def _classify_test_target(arg: str) -> tuple[str, bool] | None:
    normalized = arg.split("::", 1)[0]
    target = Path(normalized)
    parts = target.parts
    if not parts:
        return None
    if parts[0] == "tests":
        if len(parts) == 1:
            return ("tests", True)
        if len(parts) >= 2 and parts[1].endswith(".py"):
            return ("root-file", False)
        return (parts[1], target.suffix == "")
    if target.suffix == ".py":
        return ("file", False)
    return None


def _should_emit_raw_pytest_guidance(config: pytest.Config) -> bool:
    if _env_truthy(_TEST_SUITE_ENV):
        return False
    args = [str(arg) for arg in config.invocation_params.args]
    if not args:
        return False
    if any(arg in {"--collect-only", "--fixtures", "--help", "-h"} for arg in args):
        return False
    if any(arg == "-m" or arg.startswith("-m") for arg in args):
        return False

    test_targets = [arg for arg in args if _looks_like_test_target(arg)]
    if not test_targets:
        return False

    classified = [_classify_test_target(arg) for arg in test_targets]
    domains = {entry[0] for entry in classified if entry is not None}
    includes_dir = any(entry and entry[1] for entry in classified)
    if includes_dir:
        return True
    return len(test_targets) >= 3 or len(domains) >= 2


def _should_honor_verbose_output(config: pytest.Config) -> bool:
    if not _env_truthy(_FORCE_VERBOSE_OUTPUT_ENV):
        return False
    args = [str(arg) for arg in config.invocation_params.args]
    if any(arg in {"--collect-only", "--fixtures", "--help", "-h"} for arg in args):
        return False
    if any(arg == "-m" or arg.startswith("-m") for arg in args):
        return False
    test_targets = [arg for arg in args if _looks_like_test_target(arg)]
    if len(test_targets) != 1:
        return False
    classified = _classify_test_target(test_targets[0])
    return classified is not None and not classified[1]


def _emit_raw_pytest_guidance(terminalreporter) -> None:
    global _RAW_PYTEST_GUIDANCE_EMITTED
    if _RAW_PYTEST_GUIDANCE_EMITTED or terminalreporter is None:
        return
    terminalreporter.write_line(
        "note: broad raw pytest run detected; prefer ./scripts/test-suite.sh or make test-fast / make test-domain DOMAIN=<domain> for routine loops."
    )
    _RAW_PYTEST_GUIDANCE_EMITTED = True


def _emit_verbose_env_guidance(terminalreporter) -> None:
    global _VERBOSE_ENV_GUIDANCE_EMITTED
    if _VERBOSE_ENV_GUIDANCE_EMITTED or terminalreporter is None:
        return
    terminalreporter.write_line(
        "note: COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 only applies to one explicit test file/nodeid; broad runs stay compact."
    )
    _VERBOSE_ENV_GUIDANCE_EMITTED = True


def pytest_configure(config: pytest.Config) -> None:
    os.environ["COOKIMPORT_ALLOW_LLM"] = "1"
    os.environ.setdefault(_RUNNING_UNDER_PYTEST_ENV, "1")
    os.environ.setdefault(_DISABLE_HEAVY_TEST_SIDE_EFFECTS_ENV, "1")
    if _should_honor_verbose_output(config):
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


def pytest_sessionstart(session: pytest.Session) -> None:
    terminalreporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if _env_truthy(_FORCE_VERBOSE_OUTPUT_ENV) and not _should_honor_verbose_output(
        session.config
    ):
        _emit_verbose_env_guidance(terminalreporter)
    if not _should_emit_raw_pytest_guidance(session.config):
        return
    _emit_raw_pytest_guidance(terminalreporter)


@pytest.fixture
def allow_heavy_test_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ALLOW_HEAVY_TEST_SIDE_EFFECTS_ENV, "1")
    monkeypatch.delenv(_DISABLE_HEAVY_TEST_SIDE_EFFECTS_ENV, raising=False)


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
    if _FAILED_NODEIDS:
        terminalreporter.write_line(f"rerun: pytest {shlex.quote(_FAILED_NODEIDS[0])}")
    terminalreporter.write_line(
        "deep-debug: after a scoped compact rerun, add COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 only for one explicit file/nodeid if you still need traceback/capture details."
    )
    _HINTS_EMITTED = True


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not report.failed or report.when == "teardown":
        return
    if report.nodeid not in _FAILED_NODEIDS:
        _FAILED_NODEIDS.append(report.nodeid)
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


@pytest.fixture(autouse=True)
def _force_writable_codex_home(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path_factory.mktemp("codex-home")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("COOKIMPORT_CODEX_FARM_CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_FARM_CODEX_HOME_RECIPE", str(codex_home))
