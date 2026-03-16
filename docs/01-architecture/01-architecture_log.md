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

## 2026-02-28 runtime parallelism notes

### 2026-02-28_15.40.31 process-worker-required failfast surfaces

Problem captured:
- `--require-process-workers` behaved like preference in some paths, allowing silent fallback.

Durable decisions:
- treat strict mode as a fail-fast contract across stage, quality, and speed entrypoints
- keep executor-resolution telemetry so fallback reasons and strict failures are auditable
- diagnose worker fallback by lane; stage, benchmark, and split-convert do not share one global fallback path

## 2026-03-15 benchmark architecture notes

### 2026-03-15_14.55.23, 2026-03-15_15.03.18, and 2026-03-15_15.06.38 stage-backed benchmark architecture seam

Problem captured:
- benchmark prediction/eval work had drifted into a parallel architecture that duplicated the real stage/import flow

Durable findings:
- benchmark prediction generation now reuses the shared stage import session in `cookimport/staging/import_session.py`
- authoritative benchmark scoring should come from the processed stage-backed `stage_block_predictions.json` plus the same extracted block text used by normal import outputs
- canonical line-role artifacts are still useful diagnostics, but they are not the primary benchmark source of truth

Anti-loop note:
- if benchmark/import behavior diverges, check for duplicate session ownership before patching prompt packs, diagnostic projections, or score interpretation

## 2026-03-15 to 2026-03-16 refactor closure notes

### 2026-03-15_23.40.19 phase1 observability cutover surface

Problem captured:
- runtime stage meaning was being reconstructed separately by stage storage, prompt export, and benchmark bundle tooling
- raw LLM directory naming was still acting like the most authoritative stage description

Durable decisions:
- run-level semantic stage observability is the shared contract for prompt export and bundle/render surfaces
- new reviewer-facing and doc-facing stage descriptions should come from semantic stage rows, not pass-slot labels or local path guessing
- old pass-slot or raw-path naming may survive only as narrow historical read compatibility

### 2026-03-16_00.08.23 and 2026-03-16_10.40.00 label-first authority hard cut

Problem captured:
- Phase 2 still had one candidate-first escape hatch: if authoritative regrouping produced zero recipes, the stage session restored importer-owned results
- Stage 7 existed, but stage-backed tables/chunks and some Label Studio accounting still read `ConversionResult.non_recipe_blocks` as live authority

Durable decisions:
- stage-backed paths stay on the authoritative label-first result even when regrouping disagrees with importer candidates
- that mismatch now writes `group_recipe_spans/<workbook_slug>/authority_mismatch.json` instead of silently restoring candidate-first ownership
- Stage 7 rows are the live source for non-recipe tables, chunks, knowledge counts, and benchmark evidence
- `ConversionResult.non_recipe_blocks` remains compatibility cache data only after Stage 7 work is complete

Anti-loop note:
- if a fix proposal needs candidate-first fallback or `non_recipe_blocks` as a live decision boundary, it is undoing the refactor

### 2026-03-16_00.35.04 and 2026-03-16_10.40.00 single-correction recipe contract

Problem captured:
- the canonical Phase 3 runtime had landed, but docs/help/rendering still advertised 3-pass or merged-repair names as if they were current product truth

Durable decisions:
- public write-time recipe pipeline id is `codex-farm-single-correction-v1`
- the recipe Codex path is one correction stage plus deterministic final draft rebuild from explicit ingredient-step mappings
- legacy ids remain read-time aliases only; new user-facing docs and reviewer surfaces should not present them as primary values

Anti-loop note:
- if a new doc or UI change reintroduces `codex-farm-3pass-v1` or `codex-farm-2stage-repair-v1` as live options, treat that as naming drift, not product complexity

### 2026-03-16_09.03.14, 2026-03-16_12.10.00, and 2026-03-16_14.09.27 trust/escalation boundary

Problem captured:
- confidence/trust was easy to misread as either fully authoritative or fully obsolete after the label-first and Stage 7 cutovers
- the write surface was wider than the decision surface, so stale score fields could linger in stage artifacts, prediction-run artifacts, and reviewer packets even after the core runtime stopped depending on them

Durable decisions:
- the only live control-path use of mixed line-role confidence was the Codex escalation gate in `cookimport/parsing/canonical_line_roles.py`; recipe grouping and Stage 7 ownership were already label-driven
- the migration touched `label_source_of_truth.py`, `staging/import_session.py`, `labelstudio/ingest.py`, benchmark follow-up exports, and the external-AI cutdown path together
- the final current contract is reason-only on the label-first seam:
  - authoritative labeled rows keep labels, provenance, and `escalation_reasons`
  - scalar `confidence`, `trust_score`, and `escalation_score` are gone from current line-role artifacts
- reviewer/export surfaces changed in lockstep:
  - `analysis.line_role_escalation` replaced `analysis.line_role_trust`
  - `analysis.explicit_escalation_changed_lines_packet` replaced the old low-trust packet
- recipe grouping and Stage 7 ownership still ignore scalar trust/confidence and use final labels as authority
- `decided_by`, `reason_tags`, and explicit `escalation_reasons` remain the active decision-trace fields on current line-role outputs

Anti-loop note:
- do not reintroduce scalar trust/confidence fields into runtime or reviewer outputs just because archived bundles still need narrow compatibility reads

### 2026-03-16_09.45.00 refactor gap review outcome

Problem captured:
- after Phases 1-4 landed, the remaining drift was mostly stale docs/help/readers rather than missing core runtime behavior

Durable decisions:
- treat surviving legacy names and compatibility readers as cleanup targets, not evidence that the old architecture is still co-primary
- keep historical read compatibility narrow and explicit; do not let it masquerade as current write-time contract

Still-relevant examples:
- `cookimport/bench/followup_bundle.py` still reads `knowledge_manifest.json` for archived bundles

### 2026-03-16_10.53.31 and 2026-03-16_12.02.26 burn-the-boats cleanup

Problem captured:
- dead pass-slot recipe code and reviewer-facing legacy topology were still making the refactor look unfinished even though the main runtime had already moved on

Durable decisions:
- unreachable pass1/pass2/pass3 recipe orchestrator code is deleted; current runtime teaches one single-correction recipe path only
- current docs/help/rendering should present `codex-farm-single-correction-v1` and the semantic recipe trio, not legacy 3-pass or merged-repair ids as live product truth
- external-review benchmark surfaces now use semantic stage rows, `recipe_manifest.json` stage states, and `recipe_correction_audit` diagnostics as their primary recipe contract
- new prompt exports and sampled artifacts now write semantic stage metadata and stage-named files instead of `task1` / `task4` / `task5` names
- benchmark eval alias artifacts such as `missed_gold_spans.jsonl` and `false_positive_preds.jsonl` are retired for new runs
- any remaining historical compatibility read should stay isolated to archived local artifacts and must not leak back into new reviewer-facing output

Anti-loop note:
- if a fix proposal reintroduces pass-slot names as current runtime truth, it is undoing the cleanup rather than extending the architecture

### 2026-03-16_10.53.31, 2026-03-16_11.01.54, 2026-03-16_13.47.23, and 2026-03-16_13.54.32 remaining cleanup map

Problem captured:
- once the live stage path was on the new architecture, the remaining drift was scattered across hidden knobs, helper tooling, fixtures, and analytics/history fallbacks rather than one obvious runtime module

Durable decisions:
- the biggest remaining old-world seam is tooling and hidden defaults, not the stage runtime core
- the last easy deletions were mostly outside the runtime core:
  - hidden `pass1`/`pass2`/`pass3` and selective-retry CLI/run-setting knobs
  - prompt-artifact tests and benchmark helper fixtures that still hand-built `chunking/schemaorg/final` trees
  - checked-in old recipe pack files under `llm_pipelines/` after transport/tests moved to `recipe.correction.compact.v1`, `recipe.knowledge.compact.v1`, and `recipe.tags.v1`
- the remaining cleanup clusters are:
  - label-first bridge naming and compatibility caches
  - hidden parser/runtime defaults still called `legacy`
  - prompt/bundle tooling that serializes old pass-slot names
  - benchmark alias writers
  - analytics/history readers that synthesize current data from deprecated fields or CSV locations
- the safest execution order is:
  - remove runtime bridge naming first
  - collapse hidden defaults and scheduler knobs next
  - delete prompt/benchmark aliases after that
  - cut analytics/history fallbacks last with docs/tests in the same pass
- analytics/history support was intentionally preserved as the one explicit historical exception during the purge; do not treat that exception as a reason to keep reviving other compatibility branches
- historical logs, plans, and archived reports may still mention removed pipeline ids. Keep that material as history, but do not copy those names back into live docs, tests, or reviewer surfaces.
- validation from this sweep was representative, not exhaustive. For maximum certainty, the full project test suite still needs to run after destructive cleanup passes.

Anti-loop note:
- if a cleanup proposal starts by patching analytics readers or archived docs before deleting the remaining live seam, it is starting at the wrong end
