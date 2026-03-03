---
summary: "Code-aligned ExecPlan to repair CodexFarm recipe pass reliability and benchmark outcomes without breaking current runtime contracts."
read_when:
  - "When implementing fixes for codex-farm pass1/pass2/pass3 reliability"
  - "When revising llm_recipe_pipeline values, pass contracts, or codex benchmark acceptance gates"
---

# Repair CodexFarm recipe correction with code-aligned milestones

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

`docs/PLANS.md` is checked into the repository root and this document must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, we should be able to run CodexFarm recipe correction on `SeaAndSmokeCUTDOWN.epub` and distinguish pipeline transport failures from actual model failures, then improve results without regressing default deterministic behavior.

The repaired path should provide machine-readable pass transport evidence, deterministic normalization for common EPUB extraction damage, and measurable benchmark gains on a small dev slice before any full-book promotion decision.

## Policy and Scope Guardrails

Root policy currently says not to turn on CodexFarm/LLM parsing for data import by default. This plan keeps that boundary: no global default flips, no hidden auto-enable path, and no changes that force LLM execution for regular imports.

Any codex-enabled benchmarking or staging in this plan remains explicit opt-in via run settings and command flags.

## Progress

- [x] (2026-03-03 10:19 America/Toronto) Audited current seams: recipe orchestrator, run settings enums/normalizers, benchmark line-role pipeline, and manifest/artifact wiring.
- [x] (2026-03-03 10:23 America/Toronto) Rewrote this ExecPlan to match current code contracts and avoid stale assumptions.
- [x] (2026-03-03 10:36 America/Toronto) Implemented pass1/pass2 transport audit artifacts with recipe-scoped mismatch guards in orchestrator + manifest/report counters.
- [x] (2026-03-03 10:37 America/Toronto) Added deterministic additive evidence normalization (`cookimport/llm/evidence_normalizer.py`) with per-recipe provenance sidecars and pass2 helper fields.
- [x] (2026-03-03 10:38 America/Toronto) Kept benchmark-facing measurement on existing line-role path (no new taxonomy path added in `cookimport/llm`).
- [x] (2026-03-03 10:39 America/Toronto) Added deterministic pass3 fallback from pass2 structured outputs for missing/invalid/low-quality pass3 bundles.
- [x] (2026-03-03 10:40 America/Toronto) Added targeted tests and recorded Sea dev-slice focus IDs (`c0`,`c6`,`c8`,`c9`) for milestone-5 diagnostics.
- [x] (2026-03-03 11:10 America/Toronto) Aligned transport mismatch failure-mode semantics (`fallback` marks recipe pass3 fallback) and switched transport/normalization artifacts to sanitized recipe-id keyed filenames.
- [x] (2026-03-03 12:27 America/Toronto) Recorded milestone-5 benchmark outcomes from latest Sea paired replay artifacts (`2026-03-03_12.12.49`), generated dev-slice (c0/c6/c8/c9) breakdown diagnostics, and captured no-promotion decision.

## Surprises & Discoveries

- Observation: The exact recipe orchestration seam is already explicit and tested. Evidence: `cookimport/llm/codex_farm_orchestrator.py::run_codex_farm_recipe_pipeline(...)` plus `tests/llm/test_codex_farm_orchestrator.py`.

- Observation: `llm_recipe_pipeline` currently only accepts `off|codex-farm-3pass-v1` across `RunSettings`, CLI normalizers, and Label Studio pred-run normalizers. Evidence: `cookimport/config/run_settings.py`, `cookimport/cli.py`, and `cookimport/labelstudio/ingest.py`.

- Observation: Pass1-to-pass2 “selected span” is not a direct raw handoff; pass1 boundaries are clamped and can exclude block IDs before pass2 payload construction. Evidence: `_apply_pass1_midpoint_clamps(...)`, `excluded_block_ids`, and `_included_indices_for_state(...)` in `codex_farm_orchestrator.py`.

- Observation: Canonical line-role infrastructure already exists and is benchmark-wired. Evidence: `cookimport/parsing/canonical_line_roles.py`, `cookimport/labelstudio/ingest.py`, and line-role projection artifacts under `prediction-run/line-role-pipeline/`.

- Observation: Codex pipeline contract changes must update pipeline/output-schema assets in lockstep because subprocess runner enforces `output_schema_path` parity. Evidence: `cookimport/llm/codex_farm_runner.py` strict schema checks.

- Observation: `_included_indices_for_state(...)` can include indices missing from `full_blocks_by_index`, creating silent pass1/pass2 drift before pass2 input write. Evidence: pass2 payload uses `if idx in full_blocks_by_index` while effective indices are range-derived.

- Observation: Pass3 bundles can be schema-valid but semantically low quality by injecting schema description/headnote prose as step instructions. Evidence: new regression test `test_orchestrator_uses_deterministic_pass3_fallback_for_low_quality_output`.

- Observation: One existing subprocess progress test currently fails independently of this plan work (`task 0/2` callback dedupe assertion). Evidence: `tests/llm/test_codex_farm_orchestrator.py::test_subprocess_runner_emits_progress_callback_from_progress_events`.

## Decision Log

- Decision: Keep all changes additive and opt-in until dev-slice metrics exceed baseline.
  Rationale: Current runtime contract is deterministic-first; promotion must be data-backed.
  Date/Author: 2026-03-03 / OpenAI assistant

- Decision: Treat transport auditing as a first-order fix before prompt/schema tuning.
  Rationale: Without trustworthy pass handoff evidence, downstream tuning is ambiguous.
  Date/Author: 2026-03-03 / OpenAI assistant

- Decision: Reuse existing line-role subsystem for benchmark-facing labels instead of creating a second role pipeline in `cookimport/llm/`.
  Rationale: Existing projection/eval/report contracts already consume that subsystem.
  Date/Author: 2026-03-03 / OpenAI assistant

- Decision: If pass contracts change, update both recipeimport contracts and `llm_pipelines` schema/prompt assets in the same milestone.
  Rationale: Runner-level schema enforcement will otherwise fail hard.
  Date/Author: 2026-03-03 / OpenAI assistant

- Decision: Keep pass2 normalized evidence additive and non-authoritative (`normalized_evidence_*` helper fields), leaving `canonical_text` + `blocks` as source-of-truth.
  Rationale: We need deterministic repair context without mutating raw extracted evidence contract.
  Date/Author: 2026-03-03 / OpenAI assistant

- Decision: Apply pass3 deterministic fallback at recipe scope instead of aborting full run for low-quality pass3 output.
  Rationale: Keeps compatibility with existing recipe-scoped failure handling and preserves deterministic writer path.
  Date/Author: 2026-03-03 / OpenAI assistant

- Decision: Do not promote CodexFarm recipe correction as default based on current Sea milestone-5 evidence.
  Rationale: Latest full replay and dev-slice diagnostics both underperform vanilla baseline on required macro metrics.
  Date/Author: 2026-03-03 / OpenAI assistant

## Outcomes & Retrospective

Runtime implementation for milestones 1/2/4 is complete and additive:

- `run_codex_farm_recipe_pipeline(...)` now writes recipe-level transport audits, mismatch counters, and normalization provenance artifacts.
- pass2 input now includes additive normalized evidence helper fields while preserving authoritative source blocks/canonical text.
- pass3 now has a deterministic fallback path from pass2 structured output when pass3 bundle is missing/invalid/low-quality.
- targeted LLM tests were added and Sea dev-slice focus IDs (`c0`,`c6`,`c8`,`c9`) were recorded in this plan.

Milestone 5 benchmark/promotion outcome is now recorded (no promotion):

- Full Sea paired replay artifact: `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/codex_vs_vanilla_comparison.json`
  - `strict_accuracy`: codex `0.282353` vs vanilla `0.384874` (delta `-0.102521`)
  - `macro_f1_excluding_other`: codex `0.346740` vs vanilla `0.404162` (delta `-0.057421`)
- Dev-slice diagnostics (c0/c6/c8/c9) from latest paired replay:
  - source: `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/2026-03-03_12.12.49_cutdown_md/per_recipe_or_per_span_breakdown.json`
  - aggregate line accuracy: codex `0.287671` vs vanilla `0.410959` (delta `-0.123288`)
  - targeted regressions remain on c6/c8/c9 (c0 neutral).
- Transport mismatches are zero on latest full replay:
  - source: `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/codexfarm/prediction-run/raw/llm/seaandsmokecutdown/llm_manifest.json`
  - `transport_mismatches=0`

## Context and Orientation

Recipe CodexFarm correction runtime seam:

- Orchestration: `cookimport/llm/codex_farm_orchestrator.py::run_codex_farm_recipe_pipeline(...)`
- Contracts: `cookimport/llm/codex_farm_contracts.py` (`Pass1RecipeChunking*`, `Pass2SchemaOrg*`, `Pass3FinalDraft*`)
- Subprocess boundary and schema parity checks: `cookimport/llm/codex_farm_runner.py`
- Invocation points:
  - stage split-merge path: `cookimport/cli.py` (`run_codex_farm_recipe_pipeline(...)` call)
  - stage worker path: `cookimport/cli_worker.py`
  - benchmark pred-run generation: `cookimport/labelstudio/ingest.py`

Final output wiring:

- Schema.org overrides path: `write_intermediate_outputs(..., schemaorg_overrides_by_recipe_id=...)` in `cookimport/staging/writer.py`
- Draft overrides path: `write_draft_outputs(..., draft_overrides_by_recipe_id=...)` in `cookimport/staging/writer.py`
- Deterministic fallback draft builder: `cookimport/staging/draft_v1.py::recipe_candidate_to_draft_v1(...)`

Benchmark-facing line-role seam already in code:

- Labeling: `cookimport/parsing/canonical_line_roles.py::label_atomic_lines(...)`
- Pred-run projection artifacts and manifest pointers: `cookimport/labelstudio/ingest.py`
- Optional draft projection helper: `cookimport/staging/draft_v1.py::apply_line_role_spans_to_recipes(...)`

## Milestones

### Milestone 0 - Confirm baseline and freeze contracts

Record current failing CodexFarm-vs-vanilla benchmark metrics, and capture the exact current pass contracts and pipeline IDs before edits. This milestone is done when this plan includes those paths and symbol names (already captured above) and identifies one reproducible replay command for Sea/Dev slice.

### Milestone 1 - Add transport audit with effective-span semantics

Implement a recipe-scoped transport audit artifact in `cookimport/llm/codex_farm_orchestrator.py` that compares:

- pass1 effective included indices (after midpoint clamp and excluded block IDs), and
- pass2 payload block IDs/count.

Write per-recipe audit JSON under `raw/llm/<workbook_slug>/transport_audit/` and aggregate counts into `llm_manifest.json` and `llm_report`. Add recipe-scoped guard behavior for mismatches (error row + continue/fallback according to existing failure mode), not a process-wide crash.

### Milestone 2 - Add deterministic evidence normalization (additive)

Add `cookimport/llm/evidence_normalizer.py` with narrow deterministic repairs (split quantity-item joins, page-marker folding/dropping, safe heading preservation) and explicit provenance logs.

Pass2 should continue to receive authoritative original blocks. Normalized evidence is additive context only.

If new pass2 fields are required, update in one milestone:

- `cookimport/llm/codex_farm_contracts.py`
- corresponding `llm_pipelines/pipelines/*.json`
- corresponding `llm_pipelines/schemas/*.json`
- corresponding prompts in `llm_pipelines/prompts/*`

### Milestone 3 - Use existing line-role path for benchmark-facing measurement

Do not create a second label taxonomy. Instead, ensure repaired Codex outputs can be evaluated through existing `line_role_pipeline` diagnostics and canonical-text benchmark reports.

If additional bridge logic is required, place it in current projection/eval path modules (Label Studio ingest + parsing/bench helpers) rather than a parallel ad hoc path.

### Milestone 4 - Prototype deterministic finalization fallback

Add an additive orchestrator fallback path that can build final drafts deterministically from structured Codex outputs when pass3 output is low quality, while keeping legacy pass3 behavior intact for compatibility.

This prototype must preserve existing draft contract and avoid injecting description/headnote prose into `steps[].instruction`.

### Milestone 5 - Benchmark and promotion decision

Run a small dev slice (c0/c6/c8/c9) first. Only run full `SeaAndSmokeCUTDOWN` replay after dev slice passes thresholds.

Promotion criteria:

- New path meets or beats deterministic baseline on required macro metrics.
- No transport mismatches on dev slice.
- No targeted regressions (c0 title-only collapse, c9 description-as-instruction, etc.).

Keep old path available for rollback until two clean replays.

## Plan of Work

Start with transport integrity in `cookimport/llm/codex_farm_orchestrator.py` because it is lowest-risk and highest-information.

Then add normalization helper with provenance sidecars. Keep it deterministic and side-effect free.

Only after transport + normalization evidence is solid, adjust pass contract shape if still needed. Any contract changes must include `llm_pipelines` schema/prompt updates and tests in the same commit set.

Use existing line-role pipeline for benchmark diagnostics and acceptance reporting. Avoid introducing a second role labeler path under `cookimport/llm/` unless existing path proves technically blocked.

Defer default/promotion changes until benchmark gates pass.

## Concrete Steps

All commands run from repository root:

    cd /home/mcnal/projects/recipeimport

Environment and tests (project policy):

    source .venv/bin/activate
    pip install -e .[dev]

Seam discovery and verification:

    rg -n "run_codex_farm_recipe_pipeline|Pass2SchemaOrgInput|Pass3FinalDraftOutput" cookimport/llm tests/llm
    rg -n "llm_recipe_pipeline|line_role_pipeline|codex_farm_recipe_mode" cookimport/config cookimport/cli.py cookimport/labelstudio/ingest.py
    rg -n "line-role-pipeline|label_atomic_lines|apply_line_role_spans_to_recipes" cookimport/parsing cookimport/labelstudio cookimport/staging

Targeted regression tests while implementing:

    pytest tests/llm/test_codex_farm_orchestrator.py -q
    pytest tests/llm/test_run_settings.py -q
    pytest tests/llm/test_evidence_normalizer.py -q
    pytest tests/labelstudio -k line_role -q

Implemented-test verification command set used for this change:

    source .venv/bin/activate
    pip install -e .[dev]
    pytest tests/llm/test_evidence_normalizer.py tests/llm/test_codex_farm_orchestrator.py \
      -k "orchestrator_runs_three_passes_and_writes_manifest or orchestrator_transport_mismatch_is_recipe_scoped_error or orchestrator_transport_mismatch_marks_recipe_fallback_in_fallback_mode or orchestrator_writes_evidence_normalization_artifact or orchestrator_uses_deterministic_pass3_fallback_for_low_quality_output or orchestrator_recipe_level_failures_fallback_without_crashing" -q
    pytest tests/llm/test_run_settings.py -q

Known unrelated failing test in full orchestrator file:

    tests/llm/test_codex_farm_orchestrator.py::test_subprocess_runner_emits_progress_callback_from_progress_events

Benchmark replay example (Sea path, offline canonical mode):

    cookimport labelstudio-benchmark \
      --source-file data/input/SeaAndSmokeCUTDOWN.epub \
      --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl \
      --eval-mode canonical-text \
      --no-upload \
      --no-write-labelstudio-tasks

Dev-slice focus IDs for manual review:

    c0, c6, c8, c9

Milestone-5 evidence commands used in this workspace pass:

    python scripts/benchmark_cutdown_for_external_ai.py \
      data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown \
      --output-dir data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/2026-03-03_12.12.49_cutdown_md \
      --overwrite
    jq '{metrics,metadata}' \
      data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/codex_vs_vanilla_comparison.json
    jq '.pairs[0].per_recipe_breakdown[] | select(.recipe_id|test(":c0$|:c6$|:c8$|:c9$"))' \
      data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/2026-03-03_12.12.49_cutdown_md/per_recipe_or_per_span_breakdown.json

## Validation and Acceptance

Transport acceptance:

- Met: zero pass1/pass2 transport mismatches on latest Sea paired replay (`transport_mismatches=0`).
- Met: mismatch visibility path is wired (`transport_audit/*.json` + manifest counters).

Normalization acceptance:

- Met: deterministic tests cover merge/fold/skip behavior and provenance mapping (`tests/llm/test_evidence_normalizer.py`).
- Met: normalization remains additive (authoritative `canonical_text` + `blocks` are unchanged in pass2 input contract).

Draft acceptance:

- Met: targeted test proves pass3 low-quality description/headnote text is rejected and deterministic fallback avoids it.

Benchmark acceptance:

- Not met: Dev slice (c0/c6/c8/c9) does not beat vanilla baseline (`delta_codex_minus_baseline=-0.123288` aggregate).
- Not met: Full Sea replay is below vanilla on both tracked macro metrics (`strict_accuracy`, `macro_f1_excluding_other`).
- Promotion decision: keep CodexFarm recipe correction opt-in only; no default promotion.

## Idempotence and Recovery

All new artifacts are additive under run-specific directories. Reruns should create new timestamped run roots and not mutate old runs.

If a milestone fails, disable candidate path via existing run settings (`llm_recipe_pipeline=off` or legacy codex value), keep artifacts for diagnosis, and continue from last passing milestone.

## Artifacts and Notes

Expected new/updated artifacts for this plan:

- `raw/llm/<workbook_slug>/transport_audit/*.json` (sanitized recipe-id keyed)
- `raw/llm/<workbook_slug>/evidence_normalization/*.json` (sanitized recipe-id keyed)
- `raw/llm/<workbook_slug>/llm_manifest.json` (with added counters)
- `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/codex_vs_vanilla_comparison.json`
- `data/golden/benchmark-vs-golden/2026-03-03_12.12.49/single-offline-benchmark/seaandsmokecutdown/2026-03-03_12.12.49_cutdown_md/per_recipe_or_per_span_breakdown.json`
- benchmark run outputs under `data/golden/benchmark-vs-golden/<timestamp>/...`

Add concise transcripts and before/after metrics here as milestones land.

## Interfaces and Dependencies

Potential new models should be additive and local to `cookimport/llm/` and use Pydantic v2 patterns already in the repo.

Any new `llm_recipe_pipeline` value (for example `codex-farm-3pass-v2`) requires coordinated updates across:

- `cookimport/config/run_settings.py`
- `cookimport/cli.py` normalizers
- `cookimport/labelstudio/ingest.py` normalizers
- UI specs/tests (`tests/llm/test_run_settings.py`, relevant CLI tests)
- docs (`docs/10-llm/10-llm_README.md`, CLI docs as needed)

Dependencies remain within current stack (Typer, Pydantic v2, pytest, existing parsing modules). No new external OCR/LLM libraries are planned.

Revision note: 2026-03-03 - Rewrote plan to match actual runtime seams and policy boundaries: concrete orchestrator symbols, existing line-role subsystem reuse, strict codex schema contract awareness, and additive opt-in rollout constraints.
Revision note: 2026-03-03 - Implemented milestones 1/2/4 in code and tests: transport audits, additive evidence normalization, deterministic pass3 fallback, and dev-slice focus capture (`c0/c6/c8/c9`); benchmark replay milestone still pending.
Revision note: 2026-03-03 - Post-implementation alignment pass: transport mismatch now maps to recipe-level pass3 fallback in fallback mode, transport/normalization artifacts use sanitized recipe-id filenames, and eval context token fields are now backward-compatible for legacy test doubles.
Revision note: 2026-03-03 - Completed milestone-5 evidence capture from latest Sea paired replay artifacts; dev-slice and full-run metrics remain below vanilla, so promotion decision is no-default-promotion (keep opt-in only).
