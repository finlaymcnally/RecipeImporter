---
summary: "Architecture version/build/fix-attempt log to prevent repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on architecture or program behavior
  - When someone says "we are going in circles on this"
  - When reconciling historical architecture attempts against current code
---

# Architecture Log

Read this if you are going in multi-turn circles on the program, or if the human says "we are going in circles on this."
This file tracks architecture versions, builds, fix attempts, and prior dead ends so we do not repeat them.

## Chronology and Prior Attempts (do not discard)

This section preserves prior attempt outcomes so future work does not repeat dead ends.

Note on historical files:
- Several earlier architecture notes were consolidated into `docs/01-architecture/01-architecture_README.md` and this log, and the original standalone files were deleted. If you need to recover them, use git history or `docs/2026-02-22_14.21.10_recipeimport-docs-summary.md`.

Key outcomes that remain relevant:
- stage outputs default under `data/output` and Label Studio/bench defaults under `data/golden`
- timestamp folder format is `YYYY-MM-DD_HH.MM.SS` (dot-separated time)
- stage report JSON is written at the run root (not a `reports/` subfolder)
- Label Studio split merge must rebase block indices to keep eval alignment
- `run_manifest.json` is the cross-command traceability join point

## Known Bad / Known Confusions (do not re-litigate without new evidence)

1. Timestamp format docs have drifted repeatedly
- Some docs and notes claim colon-separated time.
- Current code uses dot-separated time (`HH.MM.SS`).
- Do not assume one from docs alone; verify in `strftime` calls.

2. Report path assumptions are easy to get wrong
- Some text/comments imply a `reports/` subfolder for stage outputs.
- Current stage writer writes `<workbook_slug>.excel_import_report.json` at run root.
- `cookimport/core/reporting.py` still contains a legacy `ReportBuilder` that writes to `reports/`; this is not the active stage writer path, but it can mislead documentation work.

3. URN namespace naming drift
- Older architecture examples used `urn:cookimport:*`.
- Code currently emits `urn:recipeimport:*`.
- Any downstream parser/indexer should key off real emitted IDs, not old examples.

4. Split-job merge correctness depends on index rebasing
- Particularly for Label Studio freeform/canonical tasks/eval.
- If block indices are not rebased during merge, eval alignment breaks silently.

5. Benchmark command expectations
- `labelstudio-benchmark` is not eval-only in CLI mode; it performs prediction import/upload first.
- interactive benchmark has an eval-only branch if you already have a prediction run.

6. CLI code has duplicate dead-return tail in stage command
- there is a second unreachable `typer.secho(...); return out` tail after the first return in `stage()` (`cookimport/cli.py`).
- harmless at runtime but easy to misread during maintenance.

## Prior Attempt Ledger (with status)

From earlier consolidated architecture notes:

- Attempt: remove root `staging/` default outputs.
  - Status: appears landed and active.
  - Evidence: CLI defaults route stage/inspect to `data/output`; Label Studio artifacts default to `data/golden`.

- Attempt: unify timestamp folder format to a colon-separated time format.
  - Status: not reflected in current code paths.
  - Current reality: dot-separated `YYYY-MM-DD_HH.MM.SS` is still emitted in stage and Label Studio flows.
  - Practical guidance: if standardization is desired, update all timestamp call sites together and then update this doc + conventions in same change.

## Flowchart Notes

If you are reconciling flowcharts vs runtime behavior, use:
- `docs/01-architecture/01-architecture_README.md` -> "Flowchart Branching Contracts"

## 2026-02-23 archival merge batch from `docs/understandings` (cross-cutting test-output rules)

### 2026-02-22_23.25.11 pytest progress glyph suppression

Merged source:
- `docs/understandings/2026-02-22_23.25.11-pytest-progress-glyph-suppression.md`

Preserved rule:
- Pytest 9 compact output requires both classic console style and `pytest_report_teststatus(...)` shortletter suppression; either control alone can still leave noisy progress lines.

### 2026-02-22_23.35.37 pytest addopts-override noise gap

Merged source:
- `docs/understandings/2026-02-22_23.35.37-pytest-addopts-override-noise-gap.md`

Preserved rule:
- Users can bypass `pytest.ini` quiet defaults with `-o addopts=''`; `tests/conftest.py:pytest_configure(...)` should keep compact defaults enforced unless `COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1` is explicitly set.

Anti-loop note:
- If separator/bannner noise returns, verify `tests/conftest.py` hook behavior before editing marker/test-output docs.

## 2026-02-24 archival merge batch from `docs/understandings` (architecture)

### 2026-02-23_23.14.20 golden/history path bucket refactor

Merged source:
- `docs/understandings/2026-02-23_23.14.20-data-layout-golden-history-buckets.md`

Problem captured:
- Label Studio task-generation, label-export, and benchmark-eval artifacts shared overlapping roots, while long-term history lived under stage output roots, causing operator confusion and cross-workflow path drift.

Preserved decisions:
- Separate golden roots by workflow (`sent-to-labelstudio`, `pulled-from-labelstudio`, `benchmark-vs-golden`).
- Move shared history root to `data/.history` for cross-command analytics/dashboard consistency.
- Keep fallback reads for legacy history/settings paths during migration window.

Anti-loop note:
- Path-contract changes must update CLI defaults, collectors, and docs together; partial updates recreate "missing artifact" confusion loops.

## 2026-02-24 docs/tasks archival merge batch (architecture)

### 2026-02-23_23.14.20 data layout refactor task record

Merged source:
- `docs/tasks/2026-02-23_23.14.20-data-layout-golden-history-refactor.md`

Problem captured:
- Golden artifacts for import/export/benchmark were mixed under one root, and cross-run history lived under output-specific roots, causing path drift across CLI, dashboard, and settings loaders.

Decisions preserved:
- Keep one canonical golden root constant (`DEFAULT_GOLDEN`) but route operational defaults to workflow-specific subfolders.
- Make `data/.history` canonical for shared history/dashboard outputs.
- Keep compatibility fallback reads for legacy history/settings paths during migration.

Serious implementation pitfalls already encountered:
- Using import-time frozen golden subfolder constants broke tests that monkeypatch `DEFAULT_GOLDEN`; dynamic derivation fixed this.
- Dashboard/history collectors initially missed rows when only legacy `output/.history` existed; fallback reads were required for migration period.

Evidence preserved from task:
- Targeted validation run recorded as `112 passed, 7 warnings`.
- On-disk migration recorded:
  - `data/output/.history -> data/.history`,
  - golden artifacts moved into `sent-to-labelstudio`, `pulled-from-labelstudio`, `benchmark-vs-golden`.

Anti-loop note:
- Do not split path-contract work across multiple PRs without synchronized CLI defaults + collector fallbacks + docs updates; partial migrations repeatedly recreated "artifact not found" debugging loops.
