# Tests Conventions

Durable test-suite conventions for files under `tests/`.

## Test Modularity Rule

- `pytest.ini` is the source of truth for low-noise defaults (`-q`, `--capture=sys`, no traceback/capture display/summary, plain asserts, strict markers).
- With pytest 9.x, `-q` alone still emits per-test progress rows; keep `console_output_style = classic` in `pytest.ini` and keep `pytest_report_teststatus(...)` in `tests/conftest.py` suppressing pass/skip glyphs to avoid dot-flood output.
- Keep `tests/conftest.py:pytest_configure(...)` enforcing compact mode (`no_header`, `no_summary`, warnings suppressed, `-v/-vv` clamped) so manual `-o addopts=''` invocations do not reintroduce noisy separator floods; `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` should only bypass that for one explicit test file or nodeid.
- Domain markers are assigned centrally in `tests/conftest.py`; keep per-file marker mapping there so targeted runs stay stable.
- `tests/test_*.py` files are grouped under domain folders (`tests/analytics`, `tests/bench`, `tests/cli`, `tests/core`, `tests/ingestion`, `tests/labelstudio`, `tests/llm`, `tests/parsing`, `tests/staging`).
- Path-sensitive tests should resolve shared roots via `tests/paths.py` (fixtures/docs examples) instead of `Path(__file__).parent`.
- Keep expensive files in the shared `slow` set and a tiny sanity slice in `smoke` for low-token checks.
- Failed runs should stay concise and point back to the failing node or test file, not a deleted history log.
- When a test fails during implementation work, classify it first: fix code for regressions, update tests plus owning docs for intentional contract changes, and relax or rewrite tests that were overspecified or stale.
