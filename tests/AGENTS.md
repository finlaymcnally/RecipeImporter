# Tests Agent Rules

This file sets test-folder-specific standards.
If this conflicts with root `AGENTS.md`, this file wins for `tests/`.

## What Changed (Token/Context Optimization)

- Pytest defaults are now ultra-brief in `pytest.ini`:
  - `-q --tb=no --assert=plain --show-capture=no --strict-markers --disable-warnings --no-summary`
- Tests are modularized by marker in `tests/conftest.py` via centralized file mapping:
  - domain markers: `ingestion`, `parsing`, `staging`, `cli`, `labelstudio`, `bench`, `analytics`, `tagging`, `llm`, `core`
  - scope markers: `smoke` (tiny sanity slice), `slow` (higher-cost suites)
- Tests are physically grouped into domain folders:
  - `tests/analytics`, `tests/bench`, `tests/cli`, `tests/core`, `tests/ingestion`, `tests/labelstudio`, `tests/llm`, `tests/parsing`, `tests/staging`, `tests/tagging`
- Shared fixture/docs path resolution now goes through `tests/paths.py` so nested folders do not break file lookups.
- Failures now emit minimal pointer lines only:
  - `log: docs/<domain>/<domain>_log.md`
  - optional verbose rerun command
- A short run guide lives in `tests/README.md`.

## Standards to Hold

- Keep tests modular:
  - Every new `tests/**/test_*.py` file must be placed in the correct domain folder.
  - Every new `tests/**/test_*.py` file must be added to `tests/conftest.py` marker mapping.
  - Mark costly files in `_SLOW_FILES`.
  - Keep at least a few fast sanity tests in `_SMOKE_FILES`.
- Keep output minimal:
  - Do not add decorative or verbose terminal output in tests.
  - Avoid `print(...)` in normal test paths.
  - Keep assertion text short; do not dump large payloads in failures.
  - Put deep debugging detail in matching `docs/*_log.md`, not test stdout.
- Keep runs scoped:
  - Prefer marker/file-targeted runs over full-suite runs.
  - Typical default for AI loops: `pytest -m smoke` or one domain marker.
- Keep fixtures lean:
  - Use the smallest fixture content needed to prove behavior.
  - Avoid large/generated artifacts unless behavior requires them.
