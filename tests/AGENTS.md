# Tests Agent Rules

This file sets test-folder-specific standards.
If this conflicts with root `AGENTS.md`, this file wins for `tests/`.

## What Changed (Token/Context Optimization)

- Pytest defaults are now ultra-brief in `pytest.ini`:
  - `-q --tb=no --assert=plain --show-capture=no --strict-markers --disable-warnings --no-summary`
  - `console_output_style = classic`
- `tests/conftest.py:pytest_configure(...)` now enforces compact output even when callers pass `-o addopts=''`:
  - hides header + summary
  - suppresses warnings
  - clamps `-v/-vv` back to compact mode
  - verbose opt-out is only honored for one explicit test file or nodeid: `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`
- Per-test progress glyphs are suppressed in `tests/conftest.py` via `pytest_report_teststatus(...)`.
- Tests are modularized by marker in `tests/conftest.py` via centralized file mapping:
  - domain markers: `ingestion`, `parsing`, `staging`, `cli`, `labelstudio`, `bench`, `analytics`, `llm`, `core`
  - scope markers: `smoke` (tiny sanity slice), `slow` (higher-cost suites)
- Tests are physically grouped into domain folders:
  - `tests/analytics`, `tests/bench`, `tests/cli`, `tests/core`, `tests/ingestion`, `tests/labelstudio`, `tests/llm`, `tests/parsing`, `tests/staging`
- Shared fixture/docs path resolution now goes through `tests/paths.py` so nested folders do not break file lookups.
- Failures now emit minimal pointer lines only:
  - optional verbose rerun command
- A short run guide lives in `tests/README.md`.

## Noise Examples Found (2026-02-23)

- Pytest progress glyph line from default reporter:
  - `................................. [100%]`
- Full pytest header/footer separator flood when running with overrides:
  - `============================= test session starts ==============================`
  - `=============================== warnings summary ===============================`
  - `=================== 1 failed, 23 passed, 2 warnings in 2.10s ===================`
- `tests/core/test_phase1_manual.py` (success-path prints removed):
  - `--- Testing Cleaning ---`
  - `--- Testing Signals ---`
  - `--- Testing Reporting ---`
  - `--- Testing LLM Repair (Mock) ---`
  - `Mojibake Input: ...`, `Mojibake Output: ...`
  - `Hyphen Input: ...`, `Hyphen Output: ...`
  - `Spaces Input: ...`, `Spaces Output: ...`
  - `Text: ... -> Signals: ...`
  - `Report successfully created at ...`
  - `Content: ...`
  - `ERROR: Report file not found!`
  - `LLM Repair returned a candidate object:`
  - `candidate.model_dump_json(indent=2)` payload dump
  - `ERROR: LLM Repair failed to return a candidate`
  - `All manual tests passed execution.`
- `tests/fixtures/generate_scanned_pdf.py` (kept, manual utility script):
  - `Generated scanned PDF: ...`
- Ellipses in status-message assertions were reviewed and kept intentionally because they validate product output contracts (not test-runner decoration), e.g.:
  - `tests/labelstudio/test_labelstudio_ingest_parallel.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers_interactive.py`
  - `tests/bench/test_bench_progress.py`
  - `tests/bench/test_progress_messages.py`
  - `tests/ingestion/test_epub_importer.py`
  - `tests/ingestion/test_pdf_importer.py`
  - `tests/staging/test_split_merge_status.py`

## Standards to Hold

- Keep tests modular:
  - Every new `tests/**/test_*.py` file must be placed in the correct domain folder.
  - Every new `tests/**/test_*.py` file must be added to `tests/conftest.py` marker mapping.
  - For the Label Studio benchmark-helper area, keep shared imports/helper writers in `tests/labelstudio/benchmark_helper_support.py`; do not make one `test_*.py` file serve as the shared helper source for other test files.
  - If a benchmark-helper file starts becoming mixed-purpose or hard to target, split it by behavior before it turns into another mega test module.
  - Mark costly files in `_SLOW_FILES`.
  - Keep at least a few fast sanity tests in `_SMOKE_FILES`.
- Keep output minimal:
  - Do not add decorative or verbose terminal output in tests.
  - Avoid `print(...)` in normal test paths.
  - Keep assertion text short; do not dump large payloads in failures.
  - Keep deep debugging detail in the failing test or focused notes, not noisy broad stdout.
  - Do not set `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` for routine loops; use it only after a compact rerun of one explicit file/nodeid still needs more detail.
- Keep runs scoped:
  - Prefer marker/file-targeted runs over full-suite runs.
  - Typical default for AI loops: `pytest -m smoke` or one domain marker.
- Keep fixtures lean:
  - Use the smallest fixture content needed to prove behavior.
  - Avoid large/generated artifacts unless behavior requires them.
- Keep authority clear when tests fail:
  - Classify the failure before editing anything: `regression`, `intentional contract change`, or `overspecified/stale test`.
  - Fix production code for regressions. Update tests plus the owning docs for intentional contract changes. Relax or rewrite tests that froze implementation details or obsolete policy.
  - Never change tests only to get back to green without stating which of those cases applies.
