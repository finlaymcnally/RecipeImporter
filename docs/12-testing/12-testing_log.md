---
summary: "Testing architecture/build/fix-attempt log for suite structure and low-noise pytest behavior."
read_when:
  - When test-suite organization or pytest output behavior starts going in circles
  - When compact pytest output contracts, marker grouping, or path helpers are being changed
---

# Testing Log

Read `docs/12-testing/12-testing_README.md` first for current behavior.
Use this log for historical decisions, verification evidence, and anti-loop notes.

## 2026-02-22_22 to 2026-02-22_23 docs/tasks merge batch

### 2026-02-22_22.58.41 - modular low-noise tests (`docs/tasks/2026-02-22_22.58.41 - modular-low-noise-tests.md`)

Problem captured:
- Test runs were easy to over-scope and output-heavy for AI-driven workflows.

Decisions preserved:
- Centralize marker grouping in `tests/conftest.py`.
- Establish low-noise pytest defaults in repo config.
- Provide small smoke lane and concise failure hints to relevant domain logs.

Evidence preserved from task:
- `. .venv/bin/activate && pip install -e .[dev]` completed.
- `pytest -m smoke` -> `33 passed, 485 deselected, 2 warnings in 2.72s`.
- `pytest -m "ingestion and not slow" --collect-only` -> `46/517 tests collected`.
- `pytest -m "labelstudio and not slow" --collect-only` -> `11/517 tests collected`.
- `pytest tests/test_paprika_importer.py` remained compact and printed `log: docs/03-ingestion/03-ingestion_log.md`.

Anti-loop notes:
- Keep marker logic centralized; avoid manual per-file marker churn.
- Keep debug verbosity opt-in (`-vv` etc.) instead of raising default noise.

### 2026-02-22_23.06.30 - tests folder domain reorg (`docs/tasks/2026-02-22_23.06.30 - tests-folder-domain-reorg.md`)

Problem captured:
- Flat `tests/` root made focused runs and navigation noisy.

Decisions preserved:
- Move tests into domain subfolders.
- Keep discovery/marker behavior stable after moves.
- Use shared `tests/paths.py` helpers so path-sensitive tests do not break with deeper file nesting.

Evidence preserved from task:
- `pytest -m smoke` -> `33 passed, 485 deselected, 2 warnings in 2.59s`.
- `pytest tests/parsing -m "parsing and not slow" --collect-only` -> `138 tests collected`.
- `pytest tests/ingestion -m "ingestion and not slow" --collect-only` -> `40/97 tests collected (57 deselected)`.
- Targeted path-sensitive checks in ingestion/tagging/llm/cli test modules passed.

Anti-loop notes:
- If post-move path issues appear, check `tests/paths.py` imports before changing test logic.

### 2026-02-22_23.24.59 - trim test output noise (`docs/tasks/2026-02-22_23.24.59 - trim-test-output-noise.md`)

Problem captured:
- Remaining non-informational formatting and success-path prints still bloated output.

Decisions preserved:
- Suppress pass/skip glyph output via `pytest_report_teststatus(...)`.
- Use `console_output_style = classic` to remove progress-bar row.
- Remove success-path `print(...)` noise from test modules.

Evidence preserved from task:
- `pytest -m smoke` -> `33 passed, 489 deselected, 2 warnings in 2.08s` (no dot flood).
- `pytest tests/core/test_phase1_manual.py tests/tagging/test_tagging.py` -> `23 passed, 2 warnings in 1.24s`.
- `rg -n "print\\(" tests` left only manual helper script and docs references.

Important guardrail preserved:
- Keep assertion strings that validate product status-message contracts; those are not noise.

### 2026-02-22_23.35.12 - enforce compact output on addopts override (`docs/tasks/2026-02-22_23.35.12 - enforce-compact-pytest-output-on-overrides.md`)

Problem captured:
- `pytest -o addopts='' -vv ...` bypassed compact defaults and reintroduced high-noise output.

Decisions preserved:
- Enforce compact terminal settings in `pytest_configure(...)` independent of `addopts` defaults.
- Keep explicit opt-out via `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`.

Evidence preserved from task:
- Without env opt-out, override command stayed compact.
- With `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1`, full verbose output returned intentionally.
- `pytest tests/labelstudio` remained green after guard introduction.

Anti-loop notes:
- This behavior is intentionally opinionated for token efficiency; do not soften by accident when adjusting conftest hooks.
- If users need full verbosity, point them to the env opt-out instead of removing compact enforcement.
