# Tests Quick Guide

The repo now tags tests by domain automatically in `tests/conftest.py`.
Use marker filters so AI runs only what is needed.
Durable low-noise and modularity contracts live in `tests/CONVENTIONS.md`.

For agent/day-to-day loops, do not run raw `pytest` directly because it can become a long-running full-suite loop. Use `./scripts/test-suite.sh` domain batches instead: `smoke`, `domain <domain>`, `all-fast`, `fast`, and `full` only when intentionally required.
`make test-smoke`, `make test-fast`, `make test-domain DOMAIN=<domain>`, `make test-all-fast`, and `make test-full` are equivalent entry points.

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
pytest tests/analytics/test_stats_dashboard.py
pytest tests/analytics/test_stats_dashboard_slow.py

# Label Studio benchmark-helper split
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_import_eval.py
pytest tests/labelstudio/test_labelstudio_benchmark_smoke.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_run.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_single_offline_artifacts.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_export_selection.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_compare.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_execution.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_pipelined.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload_artifacts.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py
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

# Codex orchestrator split
pytest tests/llm/test_codex_farm_orchestrator.py
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
