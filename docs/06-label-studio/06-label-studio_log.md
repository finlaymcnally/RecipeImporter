---
summary: "Label Studio architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on Label Studio behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, builds, and failed fix attempts before trying another change
---

# Label Studio Log: Architecture, Builds, and Fix Attempts

Use this log when debugging starts looping. It is intentionally compact and keeps only durable, still-relevant history.

## 1) High-Signal Timeline

### 2026-02-10: freeform span workflow became the primary contract

- Introduced `freeform-spans` task scope and segment-based tasking.
- Standardized freeform labels and offset-preserving text handling.
- Established span export artifacts + freeform eval path.

### 2026-02-11: hardening and observability pass

- Added explicit write-consent gate for Label Studio writes.
- Expanded import/benchmark progress reporting.
- Fixed split-job merge reindex behavior to avoid false zero-match evaluations.
- Added freeform eval diagnostics and source-match override path.

### 2026-02-15: interactive UX simplification

- Interactive import became direct upload flow (no second confirmation).
- Interactive import standardized on overwrite semantics.
- Interactive export moved to credential-first + project-picker flow with manual fallback.

### 2026-02-22: prelabel contract stabilization

- Interactive prelabel mode mapping aligned with CLI flags.
- Default Codex subprocess path standardized on `codex exec -` with plain-command fallback on TTY errors.
- Added task-level progress counters (`task X/Y`) with shared callback plumbing.
- Finalized taxonomy normalization and compatibility aliases.

### 2026-02-23: prelabel reliability and throughput

- Added bounded parallel prelabel workers with deterministic result ordering.
- Split task payload into focus rows (offset-authoritative) vs prompt-only context rows.
- Raised default prelabel timeout to 300s.
- Made progress callback failures non-fatal.
- Added rate-limit stop behavior (first 429 stops new provider calls).
- Added reasoning-token usage accounting where provided by Codex usage payloads.

### 2026-02-24: quality guardrails

- Added model-compatible thinking-effort filtering in interactive menus.
- Added quote repair for span mode when quote text is valid but block index is wrong.
- Kept empty `[]` span output as valid "no spans" result.
- Persisted recipe-header diagnostics in export summaries.

### 2026-02-25: freeform-only migration boundary finalized

- Removed legacy scope execution branches from import/export/eval runtime paths.
- Kept legacy scope inference only for UX tagging and explicit rejection messaging.
- Moved shared archive helpers to scope-neutral `cookimport/labelstudio/archive.py`.

## 2) Current Non-Negotiable Contracts

- Runtime scope is `freeform-spans`.
- Export rejects legacy-scoped (`pipeline`, `canonical-blocks`) projects/manifests/payloads.
- Deterministic IDs (`segment_id`, `span_id`) remain core to resume/idempotence and auditability.
- Prelabel supports both `block` and `span` granularity, with strict offset/text integrity.
- Split-job merges must keep global block-index rebasing.
- Benchmark eval is dual-mode (`stage-blocks` + `canonical-text`) and both paths remain active runtime contracts.
- Prediction-record replay/generation (`--predictions-in`, `--predictions-out`) is a supported benchmark contract, not debug-only tooling.

## 3) Known Bad Loops To Avoid

- Do not reintroduce legacy scope options/prompts as active execution branches.
- Do not treat prompt-only filtering as enough for focus scoping; parser/runtime enforcement is required.
- Do not classify empty span output (`[]`) as automatic provider failure.
- Do not assume callback/spinner failures indicate conversion/import failure.
- Do not diagnose benchmark mismatch before checking source-identity constraints.

### 2026-02-27_19.44.58 labelstudio docs prune scope map

Problem captured:
- Label Studio docs had blended active freeform contracts with retired branch history.

Durable decisions:
- Keep freeform runtime contracts, deterministic ID/resume behavior, and prelabel runtime details.
- Keep explicit retired notes for removed scope execution branches and decorate flow, but do not document them as active behavior.

### 2026-02-27_19.50.37 labelstudio docs coverage audit

Problem captured:
- Module + artifact coverage in docs was incomplete for current runtime paths.

Durable decisions:
- Include missing runtime modules and benchmark dependencies in README code maps.
- Document prediction-record replay/generation contracts and canonical-text extra diagnostics.
- Keep manifest and analytics-history side effects visible in command contract docs.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_20.13.08 labelstudio unlabeled text fallback

Source: `docs/understandings/2026-02-27_20.13.08-labelstudio-unlabeled-text-fallback.md`
Summary: Pulled Label Studio freeform exports only contain explicit spans; unlabeled regions are treated as OTHER during benchmark evaluation.

Details preserved:


# Label Studio Unlabeled Text Fallback

Discovery:

- `labelstudio-export` writes only explicit annotation spans to `exports/freeform_span_labels.jsonl`; unlabeled regions are not emitted as rows.
- In stage-block evaluation, predicted blocks missing a gold row are defaulted to gold label `OTHER`.
- In canonical-text evaluation, lines with no overlapping gold span are also defaulted to `OTHER` by default (`strict_empty_gold_to_other=True`).

### 2026-02-27_20.15.35 labelstudio overlap multilabel behavior

Source: `docs/understandings/2026-02-27_20.15.35-labelstudio-overlap-multilabel-behavior.md`
Summary: Overlapping Label Studio spans are preserved in export; stage/canonical eval treat overlapping coverage as multi-label gold sets.

Details preserved:


# Label Studio Overlap Multi-Label Behavior

Discovery:

- Export keeps every explicit span row; it does not flatten overlaps into one row.
- A single span crossing multiple blocks maps to all touched block indices.
- Stage-block evaluation collapses gold to per-block label sets; a prediction is counted correct if it matches any label in that block's set.
- Per-label precision/recall still penalize the non-chosen labels on multi-labeled blocks, so overall accuracy can look better than per-label/macro F1.

### 2026-02-28_00.16.13 howtosection label scoring paths

Source: `docs/understandings/2026-02-28_00.16.13-howto-section-label-scoring-paths.md`
Summary: Mapped label definition and scorer consumption paths for `HOWTO_SECTION`, including where scoring remap logic must be applied.

Details preserved:


# HowToSection Label Scoring Paths

## Discovery

- Label Studio freeform UI labels come from `cookimport/labelstudio/label_config_freeform.py` (`FREEFORM_LABELS` + `normalize_freeform_label`).
- Freeform eval scoring (`cookimport/labelstudio/eval_freeform.py`) computes metrics directly from normalized labels in `LabeledRange`.
- Benchmark scorers do not reuse freeform eval:
  - stage-block scorer: `cookimport/bench/eval_stage_blocks.py`
  - canonical-text scorer: `cookimport/bench/eval_canonical_text.py`
- Both benchmark scorers derive allowed labels from `cookimport/staging/stage_block_predictions.py:FREEFORM_LABELS`.

## Implication

Adding a new label in UI only is not enough. Without scorer-side handling:
- stage-block benchmark can reject or mis-score gold labels,
- canonical-text benchmark can silently drop or isolate the label,
- freeform eval can count it as its own class instead of structural ingredient/instruction behavior.

## Resolution Pattern

- Keep `HOWTO_SECTION` as an explicit UI/export label.
- During scoring, remap `HOWTO_SECTION` to `INGREDIENT_LINE` or `INSTRUCTION_LINE` via nearby structural context before metrics are computed.

### 2026-02-28_00.50.48 labelstudio export root source identity

Source: `docs/understandings/2026-02-28_00.50.48-labelstudio-export-root-source-identity.md`
Summary: Why pulled-from-labelstudio created sibling folders and how source-aware export root selection fixes it.

Details preserved:

Discovery:

`run_labelstudio_export(...)` previously defaulted destination to `<output_dir>/<project_slug>/exports`.
If Label Studio project titles were deduped/suffixed (`-2`, `-3`), slug also changed (`_2`, `_3`) and created sibling export folders instead of overwriting prior exports for the same source.

Current behavior after fix:

Default export root is source-aware:
- infer single-source identity from export payload (`source_file`/`source_hash`) with manifest fallback,
- prefer `<output_dir>/<source_file_stem_slug>` when available,
- otherwise reuse existing run roots whose `run_manifest.json` source matches,
- fallback to project slug only when source identity is unavailable.

This keeps repeated pulls for the same source in one folder while preserving explicit `--run-dir` behavior.

## 2026-02-28 docs/tasks consolidation batch (Label Studio split-convert sandbox fallback)

### 2026-02-28_12.20.59 split-convert process-worker denial fallback

Source task file:
- `docs/tasks/2026-02-28_12.20.59-sandbox-parallel-fallbacks-stage-and-labelstudio.md`

Problem captured:
- Label Studio split conversion dropped straight to serial mode when process workers were denied in sandboxed runtimes, causing avoidable throughput loss.

Durable decisions/outcomes:
- Replaced fallback ordering in `cookimport/labelstudio/ingest.py` with `process -> thread -> serial`.
- Reused shared fallback resolver surface (`cookimport/core/executor_fallback.py`) to reduce divergence from stage behavior.
- Added regression tests for process-denied fallback behavior/message contracts.

Anti-loop note:
- If split conversion appears serial, verify whether thread fallback was attempted and failed before treating it as scheduler regression.

## 2026-02-28 migrated understanding ledger (split-convert fallback closure)

### 2026-02-28_13.19.45 stage and Label Studio fallback plan closure + wrapped warning discovery

Source: `docs/understandings/2026-02-28_13.19.45-stage-and-labelstudio-fallback-plan-closure-and-test-wrap.md`

Problem captured:
- Needed confirmation that sandbox fallback plan was implemented in runtime (not only planned), plus stable regression assertions for warning output.

Durable outcomes:
- Runtime fallback wiring exists for both stage and Label Studio split conversion.
- Targeted fallback tests pass after hardening assertion style.
- Assertion contract changed from contiguous-phrase matching to whitespace-normalized matching to tolerate wrapped terminal output.

Anti-loop note:
- If fallback tests fail but warning words are visibly present, normalize whitespace first before assuming behavior regression.

## 2026-03-02 merged understanding ledger (labelstudio benchmark compare contracts and gate hardening)

### 2026-03-02_11.34.28 labelstudio benchmark compare CLI gate table

Source: `docs/understandings/2026-03-02_11.34.28-labelstudio-benchmark-compare-cli-gate-table.md`

Problem captured:
- `labelstudio_benchmark_compare` needed clearer terminal feedback on gate outcomes in addition to artifact files.

Durable outcomes:
- Added ` _format_labelstudio_benchmark_compare_gates_markdown` usage in compare flow so a compact pass/fail gate table prints immediately after verdict.
- Kept existing `comparison.json` and `comparison.md` outputs unchanged.

Anti-loop note:
- If gate failures are hard to reason about, read both terminal table and artifact files from the same compare run before changing compare internals.

### 2026-03-02_11.39.21 RunSettings alias and pred-run manifest preference

Source: `docs/understandings/2026-03-02_11.39.21-run-settings-alias-and-manifest-path-notes.md`

Problem captured:
- Raw benchmark aliases and missing prediction-manifest paths caused inconsistent compare metadata handling.

Durable outcomes:
- `RunSettings.from_dict` now normalizes `codex_farm_recipe_mode` aliases to canonical `extract` / `benchmark`.
- Compare debug artifact discovery now prefers `run_manifest.artifacts.pred_run_dir`, with fallback to `eval_dir/prediction-run`.

Anti-loop note:
- If codex intent appears wrong, inspect canonicalized settings and winner `run_manifest` before changing warning wording.

### 2026-03-02_12.00.00 labelstudio compare mode resolution

Source: `docs/understandings/2026-03-02_12.00.00-labelstudio-benchmark-compare-mode-resolution.md`

Problem captured:
- Compare mode could be ambiguous when explicit metadata was missing and artifact provenance was partial.

Durable outcomes:
- Compare now resolves `codex_farm_mode_source` from explicit mode metadata first, then raw `raw/llm` evidence.
- Inferred mode is marked explicitly; unknown mode now logs warnings and skips strict benchmark-mode debug gates when intent is not clear.

Anti-loop note:
- Before forcing strict compare behavior, verify whether `codex_farm_mode_source` is explicitly resolved or inferred from artifact evidence.

### 2026-03-02_20.44.30 compare gates for benchmark-mode runs

Source: `docs/understandings/2026-03-02_20.44.30-labelstudio-benchmark-compare-mode-and-debug-gates.md`

Problem captured:
- Compare verdict needed source-specific gate requirements tied to benchmark intent and codex pipeline.

Durable outcomes:
- Required debug artifacts (`aligned_prediction_blocks.jsonl`, `llm_manifest_json`, pass-level artifacts) are now gated on both benchmark mode + 3pass pipeline intent.
- Missing required artifacts now fail corresponding `*_debug_artifacts_present` gates and can fail overall compare verdict.

Anti-loop note:
- If a run fails gates unexpectedly, first confirm the winner source was resolved as benchmark+3pass before refactoring artifact checks.

### 2026-03-02_23.40.00 labelstudio compare hardening with raw prompt manifests

Source: `docs/understandings/2026-03-02_23.40.00-labelstudio-benchmark-compare-gate-hardening.md`

Problem captured:
- Earlier compare hardening could still pass with incomplete prompt manifest evidence.

Durable outcomes:
- `prompt_inputs_manifest_txt` and `prompt_outputs_manifest_txt` are now hard-required in strict debug modes when benchmark intent is active.
- Compare now validates raw manifest payload lists, not just manifest filenames, so referenced payload gaps fail fast.

Anti-loop note:
- If a run appears compliant but gates fail, inspect manifest `*_manifest_txt` file entries for missing raw artifacts before changing codex intent heuristics.

## 2026-03-03 migrated understanding ledger (project label-config drift backfill)

### 2026-03-03_00.17.58 Label Studio project config HOWTO_SECTION backfill

Source:
- `docs/understandings/2026-03-03_00.17.58-labelstudio-project-config-howto-section-backfill.md`

Problem captured:
- Existing projects created before new freeform labels were introduced can retain stale UI `label_config` even when runtime label constants are updated.

Durable findings:
- Existing import flow updated label config on project creation path, but reusing an existing project could preserve stale labels.
- Explicit API patch to `/api/projects/<id>` with `build_freeform_label_config()` updated the project label list in place.
- Recorded validation example: project `53` moved from 9 labels to 10 and included `HOWTO_SECTION` after patch.

Anti-loop note:
- When UI labels and code labels disagree, validate project config freshness first; do not immediately assume eval/scorer regression.


## 2026-03-03 migrated understanding ledger (labelstudio eval normalization)


### 2026-03-03_02.36.40 labelstudio-eval-none-default-normalization

Source:
- `docs/understandings/2026-03-03_02.36.40-labelstudio-eval-none-default-normalization.md`

Summary:
- labelstudio-eval metadata override normalization must coalesce None/empty values before pipeline validation.

Preserved notes:

```md
summary: "labelstudio-eval metadata override normalization must coalesce None/empty values before pipeline validation."
read_when:
  - "When editing labelstudio-eval run-config metadata parity fields"
  - "When direct Python calls to cli.labelstudio_eval fail with pipeline value 'None'"
---

# labelstudio-eval None normalization

Discovery:
- `labelstudio_eval(...)` accepted optional metadata override flags, but direct function calls with no override and missing `prediction_run` run-config values failed validation.
- Root cause: `str(pred_run_config.get(...))` turned missing values into literal `'None'`, which failed `_normalize_*_pipeline(...)` validators.

Resolution:
- Coalesce raw values first (`value or "off"`), then stringify and normalize.
- This preserves valid explicit values, accepts direct-call defaults, and keeps manifest parity behavior unchanged when metadata exists.

```
