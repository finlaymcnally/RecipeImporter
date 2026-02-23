---
summary: "Current test-suite structure and low-noise pytest behavior reference."
read_when:
  - When changing tests folder layout, marker groups, or pytest output defaults
  - When test output noise increases or compact output behavior regresses
---

# Testing README

This file is the source of truth for current test-suite structure and pytest output behavior.

Use `docs/12-testing/12-testing_log.md` for build/fix history and prior attempts.

## Scope

This section covers:

- test folder/domain organization,
- marker-based focused runs,
- compact pytest output defaults,
- compact-output enforcement rules when callers override `addopts`.

## Current Layout and Entry Points

Primary test folders:

- `tests/ingestion`
- `tests/parsing`
- `tests/labelstudio`
- `tests/cli`
- `tests/bench`
- `tests/tagging`
- `tests/llm`
- `tests/core`

Key test-runtime files:

- `pytest.ini`
- `tests/conftest.py`
- `tests/paths.py`
- `tests/README.md`
- `tests/AGENTS.md`

## Marker and Run Contracts

Current contracts:

- Marker assignment is centralized in `tests/conftest.py` (do not require touching every file for domain grouping).
- Smoke slice exists for quick sanity (`pytest -m smoke`).
- Domain-focused runs should work with marker filters and/or domain folders.
- Failure output should include concise pointers to relevant `docs/*_log.md` files.

Common run patterns:

- `. .venv/bin/activate && pytest -m smoke`
- `. .venv/bin/activate && pytest -m "ingestion and not slow" --collect-only`
- `. .venv/bin/activate && pytest tests/labelstudio -m "labelstudio and not slow" --collect-only`

## Compact Output Behavior

Current compact-output behavior:

- Default pytest runs avoid per-test dot/progress floods.
- Success-path print noise is removed from normal test modules.
- Compact mode remains enforced even with `-o addopts=''` unless explicit verbose opt-out is requested.

Verbose opt-out contract:

- Set `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` to restore full verbose output behavior for deep debugging.

Design intent:

- Keep routine AI-assisted test runs low-noise and token-efficient.
- Keep deeper diagnostics explicitly opt-in.

## Known Risks and Sharp Edges

- Overly strict compact-mode enforcement can surprise contributors expecting manual `-v/-vv` alone to restore classic pytest output.
- Path-sensitive tests can regress when files move unless shared helpers in `tests/paths.py` are used consistently.
- Remaining `print(...)` usage in manual helper scripts (for example `tests/fixtures/generate_scanned_pdf.py`) is intentional and should not be treated as test-runner noise.

## Merged Task Specs (2026-02-22_22 to 2026-02-22_23)

### 2026-02-22_22.58.41 modular low-noise tests

Task source:
- `docs/tasks/2026-02-22_22.58.41 - modular-low-noise-tests.md`

Durable outcomes:
- Low-noise defaults in repo test config.
- Central marker mapping for domain runs.
- Smoke marker lane and concise failure hints.

### 2026-02-22_23.06.30 tests folder domain reorg

Task source:
- `docs/tasks/2026-02-22_23.06.30 - tests-folder-domain-reorg.md`

Durable outcomes:
- `tests/test_*.py` files moved into domain folders.
- Shared `tests/paths.py` helper introduced to stabilize path-sensitive tests after moves.

### 2026-02-22_23.24.59 trim test output noise

Task source:
- `docs/tasks/2026-02-22_23.24.59 - trim-test-output-noise.md`

Durable outcomes:
- Dot flood and non-informational output removed from default runs.
- Success-path prints stripped from test modules (manual helper-script prints retained).

### 2026-02-22_23.35.12 enforce compact output on overrides

Task source:
- `docs/tasks/2026-02-22_23.35.12 - enforce-compact-pytest-output-on-overrides.md`

Durable outcomes:
- Compact reporter behavior remains enforced even with `-o addopts=''`.
- Explicit verbose escape hatch stays `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.
