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
- stage outputs default under `data/output`
- Label Studio defaults are workflow-specific under `data/golden/*`:
  - `sent-to-labelstudio`, `pulled-from-labelstudio`, `benchmark-vs-golden`
- history CSV root resolves from the output root parent (`<output_root parent>/.history`), which is `data/.history` for default stage output
- timestamp folder format is `YYYY-MM-DD_HH.MM.SS` (dot-separated time)
- stage report JSON is written at the run root (not a `reports/` subfolder)
- stage run-root artifacts include more than drafts/tips/chunks/raw/report; current writer flow also emits `sections`, `.bench/stage_block_predictions.json`, optional `tables`, optional `knowledge`/`tags`, and `run_manifest.json`
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
- Stage recipe/tip/topic IDs currently emit `urn:recipeimport:*`; Label Studio freeform-span export IDs remain `urn:cookimport:freeform_span:*`.
- Any downstream parser/indexer should key off real emitted IDs, not old examples.

4. Split-job merge correctness depends on index rebasing
- Particularly for Label Studio freeform/canonical tasks/eval.
- If block indices are not rebased during merge, eval alignment breaks silently.

5. Benchmark command expectations
- `labelstudio-benchmark` is not eval-only by default in CLI mode; prediction generation happens unless you explicitly pass `--predictions-in`.
- upload is optional (`--no-upload`) and prediction + eval still run in fully offline mode.

6. CLI code has duplicate dead-return tail in stage command
- there is a second unreachable `typer.secho(...); return out` tail after the first return in `stage()` (`cookimport/cli.py`).
- harmless at runtime but easy to misread during maintenance.

7. `stage()` docstring is intentionally shorter than actual writer contract
- `cookimport/cli.py` stage docstring lists only core draft/tip/report paths.
- Actual runtime writes additional lanes (`sections`, `.bench/stage_block_predictions`, optional tables, and run manifest wiring).
- For contract truth, use `staging/writer.py` + architecture README, not the short command docstring alone.

## Prior Attempt Ledger (with status)

From earlier consolidated architecture notes:

- Attempt: remove root `staging/` default outputs.
  - Status: appears landed and active.
  - Evidence: CLI defaults route stage/inspect to `data/output`; Label Studio import/export/benchmark defaults route to `data/golden/sent-to-labelstudio`, `data/golden/pulled-from-labelstudio`, and `data/golden/benchmark-vs-golden`.

- Attempt: unify timestamp folder format to a colon-separated time format.
  - Status: not reflected in current code paths.
  - Current reality: dot-separated `YYYY-MM-DD_HH.MM.SS` is still emitted in stage and Label Studio flows.
  - Practical guidance: if standardization is desired, update all timestamp call sites together and then update this doc + conventions in same change.

## Flowchart Notes

If you are reconciling flowcharts vs runtime behavior, use:
- `docs/01-architecture/01-architecture_README.md` -> "Flowchart Branching Contracts"

## 2026-02-27 merged understanding ledger (architecture + cross-doc pruning)

### 2026-02-27_19.46.01 architecture doc cleanup current path contracts

Problem captured:
- Architecture docs had stale path/default claims.

Durable decisions:
- Keep Label Studio command defaults documented per workflow root under `data/golden/*`.
- Keep history CSV contract documented as `<output_root parent>/.history/performance_history.csv`.
- Keep extractor list current (`unstructured`, `beautifulsoup`, `markdown`, `markitdown`) and remove stale `legacy` mentions.

### 2026-02-27_19.52.07 architecture doc coverage audit

Problem captured:
- Architecture docs under-described stage and Label Studio artifact surfaces.

Durable decisions:
- Document stage run-root artifacts beyond draft/tip/report (`sections`, `.bench/stage_block_predictions.json`, optional `tables`, optional `knowledge`/`tags`, `run_manifest.json`).
- Document Label Studio prediction/import optional artifacts (`label_studio_tasks.jsonl` in offline mode, optional copied `stage_block_predictions.json`, prelabel report/error/prompt-log files).
- Keep explicit note that `run_manifest` emission is stage/Label Studio scoped, not universal to every benchmark command.

### 2026-02-27_19.52.19 docs removed-feature prune map

Problem captured:
- Large docs had historical branches for removed runtime features that were creating debugging loops.

Durable decisions:
- Keep compatibility/rejection behavior only where runtime still enforces it.
- Treat EPUB race fields, Label Studio decorate mode, and legacy runtime scope execution branches as retired history.
- Prefer concise retired-feature notes over long archival execution narratives.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_21.16.59 priority plan overlap parallelization map

Source: `docs/understandings/2026-02-27_21.16.59-priority-plan-overlap-parallelization-map.md`
Summary: Priority 1-8 overlap map for safe parallel implementation sequencing.

Details preserved:


# Priority Plan Overlap Map (2026-02-27)

Derived from explicit `cookimport/...` paths in `docs/plans/priority-1.md` through `priority-8.md`, with a quick pass for conceptual collisions.

## High-overlap clusters

- `priority-1` overlaps heavily with `priority-2` (shared importer + parsing surfaces) and also overlaps segmentation scope with `priority-8`.
- `priority-2` and `priority-3` both modify EPUB/PDF block-role/signal/splitting flow.
- `priority-3` and `priority-8` both propose segmentation-eval + optional `segeval` flows (conceptual conflict even when file-path overlap is small).
- `priority-5`, `priority-6`, and `priority-7` overlap strongly in staging and settings surfaces (`run_settings`, `draft_v1`, `jsonld`, `writer`).
- All priorities touch `cookimport/cli.py`, so concurrent implementation requires strict subcommand/flag ownership.

## Lower-overlap opportunities

- `priority-4` (ingredient parsing hardening) is comparatively isolated from `priority-2`/`priority-3` core internals.
- `priority-8` is mostly bench/eval-focused and can run parallel with `priority-4` if CLI edits are coordinated.

## Practical lane recommendation

- Lane A (core structure): `priority-2 -> priority-3`
- Lane B (field quality): `priority-4` then `priority-6`
- Lane C (schema/web lane): `priority-7` after `priority-2` stabilizes shared section/fallback expectations
- Lane D (evaluation): `priority-8` (ideally after at least `priority-3` MVP)
- `priority-1` is best treated as an umbrella/integration phase after 2/3/4/6/7/8 foundations are in place.

### 2026-02-28_00.17.07 docs tasks domain mapping merge

Source: `docs/understandings/2026-02-28_00.17.07-docs-tasks-domain-mapping-merge.md`
Summary: Captured cross-domain mapping and merge method used to retire `docs/tasks` files without losing failed-attempt context.

Details preserved:


# Docs Tasks Domain Mapping Merge

Date: 2026-02-28

Mapping used for `docs/tasks` retirement:

- `docs/tasks/2026-02-27_18.51.16-speed-regression-benchmark-suite-from-pulled-goldens.md` -> `docs/07-bench`
- `docs/tasks/2026-02-27_19.45.53-all-method-eval-signature-dedupe.md` -> `docs/07-bench`
- `docs/tasks/2026-02-27_20.08.17-speed-suite-runtime-parity-single-path.md` -> `docs/07-bench`
- `docs/tasks/2026-02-27_20.43.12-quality-suite-representative-all-method-agent-loop.md` -> `docs/07-bench`
- `docs/tasks/2026-02-27_20.43.54-stage-block-recipe-notes-from-description.md` -> `docs/07-bench`
- `docs/tasks/2026-02-27_20.58.16-all-method-global-mega-run-scheduler.md` -> `docs/07-bench`
- `docs/tasks/priority-8.md` -> `docs/07-bench`
- `docs/tasks/priority-1.md` -> `docs/03-ingestion`
- `docs/tasks/priority-2.md` -> `docs/03-ingestion`
- `docs/tasks/priority-3.md` -> `docs/03-ingestion`
- `docs/tasks/priority-7.md` -> `docs/03-ingestion`
- `docs/tasks/priority-4.md` -> `docs/04-parsing`
- `docs/tasks/priority-5.md` -> `docs/04-parsing`
- `docs/tasks/priority-6.md` -> `docs/04-parsing`

Merge approach:

- README updates captured current-state contracts and anti-loop reminders per domain.
- `_log` updates captured chronology, critical decisions, failure modes, and unresolved gaps from the retired task docs.
- `docs/tasks` files were removed after merge.

Anti-loop note:
- For future domain cleanup, use explicit mapping + dual-surface merge (`README` + `_log`) before deleting source docs; deleting first causes repeated "why was this choice made?" loops.

## 2026-02-28 migrated understanding ledger (09:18 docs routing and supersession)

### 2026-02-28_09.18.47 docs/tasks routing and supersession map

Source: `docs/understandings/2026-02-28_09.18.47-docs-tasks-routing-and-supersession-map.md`

Problem captured:
- Cross-domain docs/task consolidation risked losing major decision history or reintroducing stale codex-gate claims.

Routing decisions preserved:
- `2026-02-28_00.42.17-howto-section-importer-auto-emission.md` -> `docs/05-staging` (with benchmark-remap cross-reference to `docs/07-bench`).
- `2026-02-28_01.11.10-qualitysuite-levers.md` -> `docs/07-bench`.
- `2026-02-28_02.31.09-enable-codex-farm-in-benchmarks.md` -> `docs/10-llm` (historical env-gated rollout context, now superseded).
- `2026-02-28_02.48.43-setup-codex-farm-cli-for-epub-benchmarks.md` -> `docs/10-llm`.
- `2026-02-28_04.14.07-codex-farm-model-picker-in-run-settings.md` -> `docs/02-cli`.

Supersession rules preserved:
- Retain env-gated Codex Farm content only as historical context in logs.
- Keep README sections authoritative for current ungated behavior.

Anti-loop note:
- For future docs consolidation, do not delete source docs before two-surface merge (`README` current contract + `_log` chronology/failures) is complete.

## 2026-02-28 migrated understanding ledger (cross-domain fallback surface + OG-plan closure evidence)

### 2026-02-28_12.18.33 sandbox process-pool fallback surface map

Source: `docs/understandings/2026-02-28_12.18.33-sandbox-processpool-fallback-surface-map.md`

Problem captured:
- "parallelism fixed" claims were ambiguous because fallback behavior differed by workflow layer.

Durable findings:
- QualitySuite and stage had subprocess fallback coverage.
- Label Studio split-convert behavior had separate fallback path/state.
- All-method config fanout used thread fallback when process workers were unavailable.

Architecture anti-loop note:
- Always diagnose fallback by layer (stage, all-method, quality, split-convert), not by one global host verdict.

### 2026-02-28_14.28.50 OG-plan implementation coverage audit

Source: `docs/understandings/2026-02-28_14.28.50-ogplan-implementation-coverage-audit.md`

Problem captured:
- Needed a code-and-tests audit for OG-plan items to separate real implementation gaps from docs/checklist drift.

Durable outcomes:
- Audit tied OG-plan claims to current runtime code, targeted pytest evidence, and speed-suite compare artifacts.
- Cross-cut result: most gaps were closure-evidence/docs integrity issues, not missing runtime behavior.

### 2026-02-28_14.37.20 OG-plan gap-closure evidence

Source: `docs/understandings/2026-02-28_14.37.20-ogplan-gap-closure-evidence.md`

Problem captured:
- Remaining OG closure gaps were explicit-evidence gaps (tests/docs/speed comparison records).

Durable outcomes:
- Added missing targeted assertions and recorded speed compare PASS evidence.
- Cleaned stale telemetry summary references to point to canonical merged docs.

### 2026-02-28_15.40.31 process-worker-required failfast surfaces

Source: `docs/understandings/2026-02-28_15.40.31-process-worker-required-failfast-surfaces.md`

Problem captured:
- `--require-process-workers` behaved like preference in some paths, allowing silent fallback.

Durable decisions:
- Promote strict mode to fail-fast contract across stage, all-method, quality-run, and speed-run entrypoints.
- Persist executor-resolution telemetry so strict failures and fallback reasons are auditable.

Anti-loop note:
- If strict mode exits early, treat that as expected contract enforcement unless resolver telemetry shows false-negative probing.

## 2026-03-03 migrated understanding ledger (AI context staleness refresh)

### 2026-03-03_00.01.32 AI context staleness refresh

Source:
- `docs/understandings/2026-03-03_00.01.32-ai-context-staleness-refresh.md`

Problem captured:
- Top-level AI onboarding context drifted from active runtime surfaces and mixed stable architecture with quickly stale snapshots.

Durable findings:
- Bench command narrative had stale naming (`validate/run/sweep/knobs`) versus current `speed/quality/gc/eval-stage` surface.
- Importer inventory needed explicit `webschema` inclusion.
- LLM boundary text needed correction because stage now has optional pass1-5 codex-farm flows via run settings.
- Static test-health snapshots in onboarding docs were identified as high-churn and likely to rot quickly.

Durable documentation direction:
- Keep `docs/AI_Context.md` contract-focused and stable.
- Route volatile behavior details to domain READMEs (`docs/07-bench`, `docs/03-ingestion`, `docs/10-llm`) and reference them from onboarding docs.

Anti-loop note:
- If AI-context onboarding feels stale, verify command/importer/runtime surfaces from section READMEs before rewriting the onboarding doc narrative.

## 2026-03-04 docs/understandings consolidation batch (cross-domain docs mapping note)

### 2026-03-04_00.09.35-docs-tasks-late-batch-domain-mapping

Source:
- `docs/understandings/2026-03-04_00.09.35-docs-tasks-late-batch-domain-mapping.md`

Summary:
- Domain mapping used to consolidate the late 2026-03-03 docs/tasks batch into benchmark, analytics, and llm docs without losing chronology.

Preserved source note:

````md
---
summary: "Domain mapping used to consolidate the late 2026-03-03 docs/tasks batch into benchmark, analytics, and llm docs without losing chronology."
read_when:
  - "When checking where late 2026-03-03 task docs were merged after docs/tasks cleanup."
  - "When re-tracing why Compare/Control notes landed in analytics while upload-bundle notes landed in bench."
---

# Discovery

The `docs/tasks` batch had six files that were cross-cutting, but each had a dominant contract owner:

- Analytics owner (`docs/08-analytics/*`): `IsolateForXv2`, isolate removal, backend compare-control CLI/agent.
- Benchmark owner (`docs/07-bench/*`): candidate-label/pass2-pass3 stage scoring in upload bundle, and upload_bundle starterpack/JSONL-first triage upgrade.
- LLM owner (`docs/10-llm/*`): ProFeedback rebaseline + pass3 ROI/candidate-label/diagnostics closure.

For anti-loop history, sequence matters:
1. Compare/Control was added beside isolate.
2. Isolate was then removed intentionally (not hidden) to keep one slicing path.
3. Backend compare-control parity CLI/agent was added after dashboard semantics stabilized.

Upload-bundle sequence also matters:
1. Candidate-label + pass-stage scoring path was implemented with backward-compatible fallbacks.
2. Later starterpack/triage upgrades changed first-pass navigation to JSONL-first and added deterministic blame/config/low-confidence/locator hardening.
````

