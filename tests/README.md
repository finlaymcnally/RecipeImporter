# Tests Quick Guide

The repo now tags tests by domain automatically in `tests/conftest.py`.
Use marker filters so AI runs only what is needed.
Durable low-noise and modularity contracts live in `tests/CONVENTIONS.md`.

For agent/day-to-day loops, do not run raw `pytest` directly because it can become a long-running full-suite loop. Use `./scripts/test-suite.sh` domain batches instead: `smoke`, `domain <domain>`, `all-fast`, `fast`, and `full` only when intentionally required.
`make test-smoke`, `make test-fast`, `make test-domain DOMAIN=<domain>`, `make test-all-fast`, and `make test-full` are equivalent entry points.
Bench Oracle and `cf-debug` fast tests now use tiny synthetic `upload_bundle_v1` fixtures under `tmp_path`; do not reintroduce copied large benchmark roots into routine fast slices.
When a CLI wiring test patches helpers used inside `cookimport.cli` command callables, patch `cookimport.cli` globals directly; patch `cookimport.cli_support` only for helpers whose `__module__` actually lives there (for example the background Oracle support helpers). Direct calls to foreground Oracle helpers such as `_maybe_upload_benchmark_bundle_to_oracle()` resolve through `cookimport.cli_support.bench_oracle`, so patch that module too when testing those seams.

## Folder Layout

```text
tests/
  analytics/
  bench/
  cli/
  core/
  ingestion/
  labelstudio/
  llm/
  parsing/
  staging/
```

## Minimal Runs

```bash
source .venv/bin/activate
./scripts/test-suite.sh smoke
./scripts/test-suite.sh fast
./scripts/test-suite.sh all-fast
./scripts/test-suite.sh domain <domain>

# all test-suite.sh commands accept extra pytest args after mode/domain
./scripts/test-suite.sh domain parsing -k "table"

# marker-based equivalents
pytest -m smoke
pytest -m "not slow"
pytest -m "<domain> and not slow"

# CLI structure split
pytest tests/cli/test_cli_output_structure_fast.py
pytest tests/cli/test_cli_output_structure_epub_fast.py
pytest tests/cli/test_cli_output_structure_text_fast.py
pytest tests/cli/test_cli_output_structure_slow.py

# PDF importer OCR split
pytest tests/ingestion/test_pdf_importer.py
pytest tests/ingestion/test_pdf_importer_ocr_slow.py

# Dashboard split
pytest tests/analytics/test_stats_dashboard_schema.py
pytest tests/analytics/test_stats_dashboard_collectors.py
pytest tests/analytics/test_stats_dashboard.py
pytest tests/analytics/test_stats_dashboard_benchmark_semantics.py
pytest tests/analytics/test_stats_dashboard_csv.py
pytest tests/analytics/test_stats_dashboard_slow.py

# Canonical line-role split
pytest tests/parsing/test_canonical_line_role_env.py
pytest tests/parsing/test_canonical_line_roles_recipe_span.py
pytest tests/parsing/test_canonical_line_roles.py
pytest tests/parsing/test_canonical_line_roles_codex.py
pytest tests/parsing/test_canonical_line_roles_prompting.py
pytest tests/parsing/test_canonical_line_roles_taskfile.py
pytest tests/parsing/test_canonical_line_roles_runtime.py
pytest tests/parsing/test_canonical_line_roles_runtime_recovery.py

# Benchmark cutdown split
pytest tests/bench/test_benchmark_cutdown_for_external_ai.py
pytest tests/bench/test_benchmark_cutdown_for_external_ai_starter_pack.py
pytest tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle.py
pytest tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle_runtime.py
pytest tests/bench/test_benchmark_cutdown_for_external_ai_high_level.py

# Benchmark Oracle upload split
pytest tests/bench/test_benchmark_oracle_upload.py
pytest tests/bench/test_benchmark_oracle_upload_background.py

# QualitySuite split
pytest tests/bench/test_quality_suite_runner.py
pytest tests/bench/test_quality_suite_runner_resume.py
pytest tests/bench/test_quality_suite_runner_parallelism.py
pytest tests/bench/test_quality_suite_runner_race.py

# Label Studio benchmark-helper split
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py
pytest tests/labelstudio/test_labelstudio_benchmark_smoke.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_prompt_budget.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_book_run.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_book_artifacts.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_export_selection.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_compare.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_execution.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_pipelined.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_artifacts.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_progress_dashboard.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_targets.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_planning.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_global_queue.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_prediction_reuse.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_run_reports.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_multi_source.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_profile.py

# Label Studio prelabel split
pytest tests/labelstudio/test_labelstudio_prelabel.py
pytest tests/labelstudio/test_labelstudio_prelabel_codex_cli.py

# Label Studio ingest split
pytest tests/labelstudio/test_labelstudio_ingest_parallel.py
pytest tests/labelstudio/test_labelstudio_ingest_parallel_prediction_run.py

# Codex orchestrator split
pytest tests/llm/test_codex_farm_orchestrator.py
pytest tests/llm/test_codex_farm_orchestrator_repair.py
pytest tests/llm/test_codex_farm_orchestrator_watchdog.py
pytest tests/llm/test_codex_farm_orchestrator_runner_transport.py
pytest tests/llm/test_codex_farm_orchestrator_stage_integration.py

# Bench CLI split
pytest tests/bench/test_bench.py
pytest tests/bench/test_bench_speed_cli.py
pytest tests/bench/test_bench_quality_cli.py

# Step ingredient linking split
pytest tests/parsing/test_step_ingredient_linking.py
pytest tests/parsing/test_step_ingredient_linking_semantic.py
```

Default output is intentionally compact, and this is enforced in `tests/conftest.py`
even if someone passes `-o addopts=''` by hand.

On failures, pytest prints short hints to matching `docs/*_log.md` files.
First rerun the one failing file or nodeid in normal compact mode:

```bash
pytest <failing_test_or_nodeid>
```

If that still is not enough, `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is honored only for
one explicit file or nodeid, not for broad/marker/directory runs.
