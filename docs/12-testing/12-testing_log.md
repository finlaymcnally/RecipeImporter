---
summary: "Testing architecture/build/fix-attempt log for suite structure and low-noise pytest behavior."
read_when:
  - When test-suite organization or pytest output behavior starts going in circles
  - When compact pytest output contracts, marker grouping, or path helpers are being changed
---

# Testing Log

Read `docs/12-testing/12-testing_README.md` first for current behavior.
Use this log for historical decisions, verification evidence, and anti-loop notes.

## Current Verification Snapshot (2026-02-27_19.50)

Repository checks rerun against current code:

- `. .venv/bin/activate && pytest -m smoke`
  - `39 passed, 662 deselected, 2 warnings in 2.59s`
- `. .venv/bin/activate && pytest -m "ingestion and not slow" --collect-only`
  - `41/701 tests collected (660 deselected) in 2.16s`
- `. .venv/bin/activate && pytest tests/labelstudio -m "labelstudio and not slow" --collect-only`
  - `8/193 tests collected (185 deselected) in 2.06s`

Current contract confirmation:

- Marker assignment and smoke/slow slices are still centralized in `tests/conftest.py`.
- `_FILE_MARKERS` currently covers all `74/74` `test_*.py` filenames; no unmapped files were found.
- Fallback behavior remains: unmapped test filenames would receive marker `core`.
- Compact output is still enforced from `pytest_configure(...)` even when callers pass `-o addopts=''`.
- Verbose opt-out is still only `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.
- Domain folders remain the primary layout, with one intentional root-level cross-domain module: `tests/test_eval_freeform_practical_metrics.py`.
- Support data surfaces under tests remain active: `tests/fixtures/*` and `tests/tagging_gold/*`.
- Shared path helper constants in `tests/paths.py` remain active (`REPO_ROOT`, `FIXTURES_DIR`, `TAGGING_GOLD_DIR`, `DOCS_EXAMPLES_DIR`).

## Durable History (Still Relevant)

### 2026-02-22_22.58.41 - modular low-noise tests

Problem captured:
- Test runs were easy to over-scope and output-heavy for AI-driven workflows.

Decisions still active:
- Centralized marker grouping in `tests/conftest.py`.
- Low-noise pytest defaults in `pytest.ini`.
- Concise failure hints pointing to domain logs.

Anti-loop note:
- Keep marker logic centralized; avoid per-file marker churn.

### 2026-02-22_23.06.30 - tests folder domain reorg

Problem captured:
- Flat `tests/` root made focused runs and navigation noisy.

Decisions still active:
- Domain subfolders under `tests/` are the required layout.
- Shared `tests/paths.py` remains the path-stability helper for nested tests.

Anti-loop note:
- If path-sensitive tests regress after moves, verify `tests/paths.py` usage before changing test logic.

### 2026-02-22_23.24.59 - trim test output noise

Problem captured:
- Non-informational formatting and success-path prints bloated output.

Decisions still active:
- Suppress pass/skip glyph output via `pytest_report_teststatus(...)`.
- Keep `console_output_style = classic` for compact terminal output.
- Keep success-path `print(...)` out of normal test modules.

Guardrail:
- Assertion strings that validate product status/progress contracts are intentional and should not be removed as noise.

### 2026-02-22_23.35.12 - enforce compact output on addopts override

Problem captured:
- `pytest -o addopts='' -vv ...` bypassed compact defaults.

Decisions still active:
- Enforce compact terminal settings in `pytest_configure(...)` independent of `addopts`.
- Keep explicit opt-out via `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.

Anti-loop note:
- If full verbosity is needed, use the env opt-out instead of weakening compact defaults.

### 2026-02-27_19.44.54 testing docs pruning current contracts

Problem captured:
- Testing docs retained stale task-link references and old flat-path examples.

Durable decisions:
- Keep low-noise pytest and marker-centralization history.
- Remove stale path/count evidence that no longer helps operate current layout.

### 2026-02-27_19.50.34 testing docs code-coverage audit

Problem captured:
- Testing docs under-described active support surfaces and fallback marker behavior.

Durable decisions:
- Keep root-level cross-domain module, support asset folders, and `tests/paths.py` constants documented.
- Keep explicit marker fallback (`core`) and full filename-coverage contract documented.
