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

This section preserves what prior docs attempted, in creation order, so future work does not repeat dead ends.

1. `README.md` (historical, previously in this folder)
- established baseline ingestion -> staging narrative and plugin-registry model.

2. `2026-02-11-remove-root-staging-defaults.md` (historical)
- attempted migration away from root `staging/` defaults.
- current code confirms this is landed (`DEFAULT_OUTPUT = data/output`, Label Studio defaults under `data/golden`).

3. `2026-02-11-standardize-run-timestamps.md` (historical)
- claimed standardized timestamp behavior.
- current code still uses `YYYY-MM-DD_HH.MM.SS` (dot-separated time), not a colon format.

4. `2026-02-11-architecture-doc-merge-verification.md` (this folder, older than this README)
- recorded 3 key truth checks:
  - timestamp format is dot-separated
  - stage report file is at run root (not `reports/`)
  - Label Studio split merge rebases block indices
- all 3 remain true in current code.

5. `2026-02-15_20.44.30-stage-docs-information-architecture-map.md` (migrated from `docs/understandings/`)
- captured a stage-first docs information architecture to prevent discovery notes from becoming a separate silo.
- mapped runtime module ownership to section docs (`02-cli`, `03-ingestion`, `04-parsing`, `05-staging`, `06-label-studio`, `07-bench`, `08-analytics`, `09-tagging`, `11-reference`).

6. `2026-02-15_22.05.45-architecture-merge-verification.md` (migrated from `docs/understandings/`)
- re-verified that stage report JSON is written at run root by active writer flow.
- re-verified that legacy `core/reporting.py` `ReportBuilder` is not current stage output contract.
- re-verified Label Studio split merge block-index rebasing as required for eval alignment.

7. `2026-02-16_12.30.45-run-manifest-semantics-and-history-root.md` (migrated from `docs/understandings/`)
- established `run_manifest.json` as cross-flow traceability artifact (`stage`, Label Studio import/export/eval/benchmark, bench prediction/eval/suite runs).
- captured output-root-specific CSV history behavior (`stage --out` root and benchmark `processed_output_dir` root).
- captured offline benchmark contract for `labelstudio-benchmark --no-upload` (local prediction generation + eval, no credential/upload path).

8. `2026-02-19_01-architecture-readme-log-split` (this change)
- split architecture docs into:
  - `01-architecture_README.md` for current architecture/source-of-truth behavior.
  - `01-architecture_log.md` for chronology, failed paths, and anti-loop guidance.

Current file timestamps in this folder before consolidation:
- `2026-02-11-architecture-doc-merge-verification.md` (mtime `2026-02-15 20:50:55 -0500`)
- `01-architecture_README.md` (mtime `2026-02-15 21:28:01 -0500`)

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

From the archived architecture docs:

- Attempt: remove root `staging/` default outputs.
  - Status: appears landed and active.
  - Evidence: CLI defaults route stage/inspect to `data/output`; Label Studio artifacts default to `data/golden`.

- Attempt: unify timestamp folder format to a colon-separated time format.
  - Status: not reflected in current code paths.
  - Current reality: dot-separated `YYYY-MM-DD_HH.MM.SS` is still emitted in stage and Label Studio flows.
  - Practical guidance: if standardization is desired, update all timestamp call sites together and then update this doc + conventions in same change.
