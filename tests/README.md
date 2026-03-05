# Tests Quick Guide

The repo now tags tests by domain automatically in `tests/conftest.py`.
Use marker filters so AI runs only what is needed.
Durable low-noise and modularity contracts live in `tests/CONVENTIONS.md`.

For agent/day-to-day loops, do not run raw `pytest` directly because it can become a long-running full-suite loop. Use `./scripts/test-suite.sh` domain batches instead: `smoke`, `domain <domain>`, `all-fast`, `fast`, and `full` only when intentionally required.

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
  tagging/
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
pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_progress.py
pytest tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py
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
For full traceback/details, rerun with:

```bash
COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest -o addopts='' -vv --tb=short --show-capture=all --assert=rewrite <failing_test>
```
