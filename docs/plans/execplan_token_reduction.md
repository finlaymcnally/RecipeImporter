---
summary: "ExecPlan for reducing Codex prompt tokens with compact pass2/pass3 assets, compact line-role prompts, and a unified prompt-budget summary."
read_when:
  - When reducing Codex prompt tokens
  - When updating prompt-budget reporting or the token-reduction rollout plan
---

# Reduce Codex Prompt Tokens Using Repo-Native Compact Prompt Assets and a Unified Prompt Budget Report

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, a contributor can run a Codex-backed benchmark in this repository and inspect one durable prompt-budget artifact that reports token usage for `pass1`, `pass2`, `pass3`, and `line_role` together. The same benchmark should then spend materially fewer prompt tokens because the pass2 payload will stop repeating recipe evidence in multiple forms, the line-role prompt will stop repeating field names on every row, and pass3 will stop resending ingredient and instruction content twice through both `schemaorg_recipe` and extractive lists.

The user-visible result is concrete. A Codex benchmark run for `data/input/DinnerFor2CUTDOWN.epub` or `data/input/SaltFatAcidHeatCUTDOWN.epub` should leave behind `prediction-run/prompt_budget_summary.json`, the benchmark packaging/reporting surfaces should show `line_role` as a first-class pass instead of an invisible side total, and the compact configuration should show lower prompt-token totals than the legacy configuration without changing routing rules, model family, thresholds, or output schemas.

This plan is intentionally scoped to prompt-size reduction and prompt-budget observability. It must not change recipe-routing policy, confidence thresholds, label sets, extraction semantics, or model choice except where a rollout path is needed to compare legacy and compact prompt formats safely.

## Progress

- [x] (2026-03-05_23.01.00) Read `docs/PLANS.md`, `docs/07-bench/07-bench_README.md`, `docs/10-llm/10-llm_README.md`, `docs/AGENTS.md`, and the existing `docs/plans/OGplan/execplan_token_reduction.md`.
- [x] (2026-03-05_23.01.00) Inspected the real prompt-producing code in `cookimport/llm/codex_farm_orchestrator.py`, `cookimport/llm/codex_farm_contracts.py`, `llm_pipelines/prompts/recipe.schemaorg.v1.prompt.md`, `llm_pipelines/prompts/recipe.final.v1.prompt.md`, `cookimport/llm/canonical_line_role_prompt.py`, and `cookimport/parsing/canonical_line_roles.py`.
- [x] (2026-03-05_23.01.00) Confirmed that the original plan's line-role telemetry gap is already fixed in the current tree: line-role usage is written to `prediction-run/line-role-pipeline/telemetry_summary.json` and threaded through prediction manifests and analytics readers.
- [x] (2026-03-05_23.01.00) Confirmed that recipe prompt changes in this repo must happen through `llm_pipelines` prompt assets plus `RunSettings` pipeline ids, not through ad hoc Python prompt-builder functions for pass2 and pass3.
- [x] (2026-03-05_23.01.00) Confirmed the remaining compaction targets in local code: pass2 still serializes `canonical_text`, `blocks`, `normalized_evidence_text`, `normalized_evidence_lines`, and `normalization_stats` together; line-role still serializes one verbose JSON object per target row; pass3 no longer sends raw block windows but still sends duplicated ingredient/instruction content through `schemaorg_recipe` plus extractive arrays.
- [x] (2026-03-05_23.01.00) Rewrote this ExecPlan for the local codebase, replacing stale implementation assumptions with repo-native files, rollout seams, tests, and validation commands.
- [x] (2026-03-05_23.09.25) Added required docs front matter and normalized plan timestamps to the repository's `YYYY-MM-DD_HH.MM.SS` format so `docs:list` can index this file cleanly.
- [x] (2026-03-05_23.51.27) Added `cookimport/llm/prompt_budget.py`, wrote `prediction-run/prompt_budget_summary.json` from `cookimport/labelstudio/ingest.py`, and updated benchmark runtime fallback logic so `line_role` appears in merged per-pass prompt budgets.
- [x] (2026-03-05_23.51.27) Added compact pass2 assets (`recipe.schemaorg.compact.v1`) plus compact bundle construction in `cookimport/llm/codex_farm_orchestrator.py` and `cookimport/llm/codex_farm_contracts.py`.
- [x] (2026-03-05_23.51.27) Added compact line-role target serialization in `cookimport/llm/canonical_line_role_prompt.py` plus the local `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1` selector in `cookimport/parsing/canonical_line_roles.py`.
- [x] (2026-03-05_23.51.27) Added compact pass3 assets (`recipe.final.compact.v1`) plus compact bundle construction that drops duplicated `recipeIngredient` and `recipeInstructions` content from the pass3 payload.
- [ ] Run focused tests plus legacy-vs-compact benchmark replays for `DinnerFor2CUTDOWN.epub` and `SaltFatAcidHeatCUTDOWN.epub`, then update this plan with measured deltas. Completed so far: direct impacted unit tests pass. Remaining: real benchmark replays were not run in this turn.

## Surprises & Discoveries

- Observation: the original plan's first milestone is stale in this repository state.
  Evidence: `cookimport/parsing/canonical_line_roles.py` now calls `run_codex_json_prompt(..., track_usage=True)`, writes `line-role-pipeline/telemetry_summary.json`, and `cookimport/labelstudio/ingest.py` already threads `line_role_pipeline_telemetry_path` into prediction manifests.

- Observation: pass2 and pass3 prompts are not hand-built in Python here.
  Evidence: `cookimport/llm/codex_farm_orchestrator.py` writes JSON bundle files, while the actual prompt text comes from `llm_pipelines/pipelines/recipe.schemaorg.v1.json`, `llm_pipelines/prompts/recipe.schemaorg.v1.prompt.md`, `llm_pipelines/pipelines/recipe.final.v1.json`, and `llm_pipelines/prompts/recipe.final.v1.prompt.md`.

- Observation: the local repo already has a built-in rollout seam for recipe prompt variants.
  Evidence: `RunSettings` exposes `codex_farm_pipeline_pass2` and `codex_farm_pipeline_pass3`, and `codex_farm_orchestrator.py` resolves those ids before calling the external `codex-farm` runner.

- Observation: pass2 still contains obvious prompt duplication in the current code, not just in uploaded external artifacts.
  Evidence: `Pass2SchemaOrgInput` in `cookimport/llm/codex_farm_contracts.py` still contains `canonical_text`, `blocks`, `normalized_evidence_text`, `normalized_evidence_lines`, and `normalization_stats`, and `cookimport/llm/codex_farm_orchestrator.py` populates all of them for every pass2 bundle.

- Observation: pass3 is locally different from the old plan, but it is still a likely token hotspot.
  Evidence: `Pass3FinalDraftInput` now contains only `schemaorg_recipe`, `extracted_ingredients`, and `extracted_instructions`, so the old "drop raw block windows" step is obsolete, but `docs/reports/codex_activity_detailed_line_items.csv` still shows many `recipe.final.v1` runs dominating total tokens, which means pass3 must be re-measured and compacted based on the current input shape rather than the old one.

- Observation: benchmark packaging/reporting still treats line-role as second-class even though line-role telemetry exists.
  Evidence: `scripts/benchmark_cutdown_for_external_ai.py` can backfill pass totals from prediction-run telemetry, but `_upload_bundle_build_call_runtime_inventory_from_prediction_manifest(...)` only iterates `pass1`, `pass2`, and `pass3`, so `line_role` does not appear as a pass bucket in the same summary.

- Observation: the current line-role compaction target is mechanically clear and already covered by direct prompt tests.
  Evidence: `cookimport/llm/canonical_line_role_prompt.py` still writes one JSON object per target row, and `tests/parsing/test_canonical_line_roles.py` already contains direct prompt-shape assertions that can be extended for compact-vs-legacy comparisons.

- Observation: one existing orchestrator eligibility test is already red in the current worktree and is not caused by the token-reduction slice.
  Evidence: `pytest tests/llm/test_codex_farm_orchestrator.py::test_orchestrator_pass1_eligibility_gate_clamps_to_heuristic_bounds` currently fails with `eligibility_action == "proceed"` instead of `"clamp"` even when run alone after the compact-payload changes pass their own tests.

## Decision Log

- Decision: replace the original global `PROMPT_FORMAT_VERSION` idea with explicit compact pipeline ids for pass2 and pass3.
  Rationale: this repo already has first-class pass pipeline-id settings in `RunSettings`, so a pipeline-id rollout is simpler, more local, and easier to benchmark than introducing a second abstract prompt-version switch for the codex-farm passes.
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: treat line-role telemetry as implemented and move the observability milestone to a unified prompt-budget artifact.
  Rationale: the current gap is no longer "line-role tokens are missing entirely"; it is "there is no single durable prompt-budget report that joins pass1/pass2/pass3 and line_role in one place and one benchmark-facing summary."
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: keep pass2 prompt compaction as the first prompt-shape change.
  Rationale: the current local pass2 payload still repeats recipe evidence in several fields, and those fields are created in one obvious place inside `cookimport/llm/codex_farm_orchestrator.py`.
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: keep line-role compaction in scope, but implement it in the existing Python prompt builder instead of inventing a new benchmark-only wrapper.
  Rationale: line-role prompt text is already assembled in `cookimport/llm/canonical_line_role_prompt.py`, and the existing tests and prompt artifacts already exercise that path directly.
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: keep pass3 in scope, but redefine the local goal as removing duplicated ingredient/instruction content rather than removing raw text blocks.
  Rationale: the repository has already eliminated the raw-text-heavy pass3 payload assumed by the old plan, but pass3 still appears expensive and still repeats content through `schemaorg_recipe` plus extractive arrays.
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: use existing test suites and folders instead of inventing a new `tests/prompt_budget/` tree.
  Rationale: this repo already groups codex-farm tests under `tests/llm/`, line-role tests under `tests/parsing/`, and benchmark packaging tests under `tests/bench/` and `tests/labelstudio/`; the plan should follow the current project structure.
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: rollback must remain one config change away.
  Rationale: for recipe prompts, rollback is selecting the legacy pipeline ids; for line-role, rollback is switching the local prompt-format selector back to `legacy`.
  Date/Author: 2026-03-05_23.01.00 / Codex

- Decision: keep prompt-budget reporting as an additive prediction-run artifact instead of rewriting existing telemetry readers.
  Rationale: `prediction-run/prompt_budget_summary.json` can be generated from the current manifest surfaces with minimal risk, and benchmark packaging can adopt it without disturbing the older telemetry fallbacks used by existing run roots.
  Date/Author: 2026-03-05_23.51.27 / Codex

## Outcomes & Retrospective

Implementation is now partially complete. The repository writes a unified prompt-budget artifact, benchmark telemetry fallback can read `line_role` as a first-class pass, compact pass2 and pass3 pipeline assets exist, and line-role prompt construction can switch to the compact tuple format locally. The focused, directly impacted tests for those slices pass.

The main remaining gap is real benchmark evidence. This turn did not run the paired `DinnerFor2CUTDOWN.epub` and `SaltFatAcidHeatCUTDOWN.epub` legacy-vs-compact replays, so the plan still lacks measured end-to-end token deltas and has not changed any defaults.

Revision note (2026-03-05_23.51.27): updated this ExecPlan after shipping the repo-native prompt-budget artifact plus compact pass2/pass3/line-role implementations, and recorded the remaining validation gap plus the unrelated existing orchestrator eligibility test failure seen during verification.

## Context and Orientation

This repository has two separate prompt-generation mechanisms that matter for token reduction.

The first mechanism is the recipe codex-farm flow in `cookimport/llm/codex_farm_orchestrator.py`. That file does not render prompt prose directly. Instead, it builds strict JSON input bundles using the Pydantic models in `cookimport/llm/codex_farm_contracts.py`, writes those bundles under `prediction-run/raw/llm/...`, and then calls the external `codex-farm` runner with pipeline ids. The actual pass2 and pass3 prompt prose lives in `llm_pipelines/prompts/recipe.schemaorg.v1.prompt.md` and `llm_pipelines/prompts/recipe.final.v1.prompt.md`, and the pipeline definitions that point to those prompt files live in `llm_pipelines/pipelines/recipe.schemaorg.v1.json` and `llm_pipelines/pipelines/recipe.final.v1.json`. Rollout for recipe prompt variants should therefore happen by adding new pipeline assets and selecting them through `RunSettings.codex_farm_pipeline_pass2` and `RunSettings.codex_farm_pipeline_pass3`.

The second mechanism is the canonical line-role Codex fallback in `cookimport/llm/canonical_line_role_prompt.py` plus `cookimport/parsing/canonical_line_roles.py`. Here the prompt text is built directly in Python from `AtomicLineCandidate` rows. The current prompt format defines a fixed instruction header and then emits `Targets (JSONL):` followed by one verbose JSON object per target. This is the right local place to introduce a compact row format.

Token telemetry already exists in two different places. Codex-farm recipe passes persist telemetry under `llm_codex_farm.process_runs.pass1|pass2|pass3` in prediction manifests. Line-role persists `prediction-run/line-role-pipeline/telemetry_summary.json`, and `cookimport/labelstudio/ingest.py`, `cookimport/cli.py`, and `cookimport/analytics/dashboard_collect.py` already know how to carry that summary forward. What does not exist yet is one repository-owned prompt-budget artifact that joins these into a single per-pass summary and makes `line_role` visible in the same benchmark-facing report as the recipe passes.

The old plan assumed pass3 still shipped raw block text. That is no longer true. `Pass3FinalDraftInput` currently contains only `schemaorg_recipe`, `extracted_ingredients`, and `extracted_instructions`. Any local pass3 reduction must therefore focus on shrinking duplicated structured content inside that payload, not on deleting raw windows that no longer exist.

## Plan of Work

### Milestone 1: Add one unified prompt-budget artifact for every Codex-backed prediction run

Create a small shared helper module at `cookimport/llm/prompt_budget.py`. It must define one authoritative builder function named `build_prediction_run_prompt_budget_summary(pred_manifest: Mapping[str, Any], pred_run_dir: Path) -> dict[str, Any]` plus one writer function named `write_prediction_run_prompt_budget_summary(pred_run_dir: Path, summary: Mapping[str, Any]) -> Path`.

The summary must normalize the repository's two telemetry sources into one schema with one top-level `by_pass` mapping. That mapping must contain `pass1`, `pass2`, and `pass3` when their codex-farm `telemetry_report.summary` rows exist, and it must contain `line_role` when `prediction-run/line-role-pipeline/telemetry_summary.json` exists. Each pass row must include at least call-or-batch count, `tokens_input`, `tokens_cached_input`, `tokens_output`, `tokens_reasoning`, and `tokens_total`. The file must be written to `prediction-run/prompt_budget_summary.json`.

Wire this helper into `cookimport/labelstudio/ingest.py` immediately after the prediction-run manifest is assembled, so every benchmark or prediction run that already has telemetry automatically writes the prompt-budget summary. Add the artifact path to both the prediction manifest and the benchmark run manifest using the same relative-path style already used for other benchmark artifacts.

Update the reporting side to use this artifact. In `scripts/benchmark_cutdown_for_external_ai.py`, replace the current hard-coded pass loop in `_upload_bundle_build_call_runtime_inventory_from_prediction_manifest(...)` so it prefers `prompt_budget_summary.json` when present and includes `line_role` in `summary.by_pass`. Keep the older telemetry fallback only for older run roots that predate the new artifact. The important user-visible behavior is that benchmark packaging and starter-pack summaries stop showing only recipe passes when line-role was active.

Cover this milestone with tests in existing local suites. Extend `tests/labelstudio/test_labelstudio_benchmark_helpers.py` so a synthetic prediction run with both `llm_codex_farm.process_runs.*` telemetry and `line-role-pipeline/telemetry_summary.json` produces a merged `prompt_budget_summary.json`. Extend `tests/bench/test_benchmark_cutdown_for_external_ai.py` so runtime summaries include `line_role` in `by_pass` when the prompt-budget summary exists. Do not create a new test tree for this.

Milestone 1 is complete when a benchmark run root exposes one durable prompt-budget file that includes `line_role` beside `pass1`, `pass2`, and `pass3`, and the benchmark packaging/reporting path surfaces that same pass list.

### Milestone 2: Compact pass2 by replacing duplicated evidence fields with one compact evidence representation

Keep the existing legacy path intact, but add a compact path that is selected by pipeline id. Add a new pass2 pipeline asset at `llm_pipelines/pipelines/recipe.schemaorg.compact.v1.json` and a new prompt file at `llm_pipelines/prompts/recipe.schemaorg.compact.v1.prompt.md`. Reuse the existing output schema at `llm_pipelines/schemas/recipe.schemaorg.v1.output.schema.json`.

In `cookimport/llm/codex_farm_contracts.py`, add a compact input model named `Pass2SchemaOrgCompactInput`. It must not contain `canonical_text`, `normalized_evidence_text`, `normalized_evidence_lines`, or `normalization_stats`. Those fields remain useful for local diagnostics and guardrails, but they do not belong in the compact prompt payload. Instead, the compact input should carry one authoritative evidence field named `evidence_rows`, defined as a list of tuples in the order `[block_index, text]`. The prompt template must define that tuple schema once and instruct the model to use only `evidence_rows` as source evidence.

In `cookimport/llm/codex_farm_orchestrator.py`, split pass2 bundle construction into two explicit helpers: `_build_pass2_input_legacy(...) -> Pass2SchemaOrgInput` and `_build_pass2_input_compact(...) -> Pass2SchemaOrgCompactInput`. Use `run_settings.codex_farm_pipeline_pass2` to choose which helper runs. Keep `state.canonical_text` and evidence-normalization artifact writes exactly as they are today for local validation and diagnostics. The compaction change is about prompt payload shape, not about deleting local provenance or changing post-pass2 guardrails.

The new compact pass2 prompt file must preserve the current task semantics: extract a schema.org recipe object plus verbatim ingredient and instruction lists from the provided evidence only. What changes is the evidence serialization. The prompt must define the tuple legend once, avoid re-describing helper-only normalization fields, and keep the output contract identical to the legacy pass2 schema.

Add or extend tests in `tests/llm/test_llm_pipeline_pack_assets.py`, `tests/llm/test_codex_farm_contracts.py`, and `tests/llm/test_codex_farm_orchestrator.py`. These tests must prove all of the following.

- The compact pipeline asset exists and links to the new prompt file and the existing output schema.
- The compact pass2 input path omits `canonical_text`, `normalized_evidence_text`, `normalized_evidence_lines`, and `normalization_stats`.
- The compact pass2 input still includes every evidence line text needed to reproduce the old extraction task.
- Representative compact payloads are materially smaller than legacy payloads. The minimum bar for checked-in fixture comparisons is a 35% reduction in UTF-8 bytes, with token-estimate comparison recorded in the test comments or fixture helper output.

Milestone 2 is complete when pass2 can be switched between legacy and compact by pipeline id alone and the compact path demonstrably removes duplicated evidence fields.

### Milestone 3: Compact line-role target serialization in the existing Python prompt builder

In `cookimport/llm/canonical_line_role_prompt.py`, split target serialization into `serialize_line_role_targets_legacy(...) -> str` and `serialize_line_role_targets_compact(...) -> str`. Keep the existing output format unchanged: the model must still return a JSON array of objects shaped like `{"atomic_index": ..., "label": ...}` so the current parser can remain in place.

The compact input format must define one tuple schema in the prompt header and then emit one JSON array per target row in this order:

    [atomic_index, within_recipe_span_1_or_0, previous_line, current_line, next_line, candidate_labels]

Do not abbreviate labels in the first compact version. The safe gain here comes from removing repeated field names, not from inventing a dictionary layer for labels.

In `cookimport/parsing/canonical_line_roles.py`, add a narrow prompt-format selector named `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT` with allowed values `legacy` and `compact_v1`. Resolve it in one helper function close to prompt construction and pass the selected format into `build_canonical_line_role_prompt(...)`. Default remains `legacy` until the benchmark replay in Milestone 5 passes. This keeps rollback simple without adding another user-facing benchmark setting.

Extend `tests/parsing/test_canonical_line_roles.py`. The new coverage must prove that compact prompts contain the same current-line texts, define the tuple schema exactly once, preserve batching/progress/prompt-log behavior, and reduce serialized prompt size by at least 20% on representative target batches. Update existing direct prompt-shape assertions so they explicitly test legacy format when needed instead of accidentally locking the file to the current default forever.

Milestone 3 is complete when line-role prompt construction can switch between legacy and compact locally, existing output parsing still works unchanged, and the compact prompt materially reduces prompt bytes for the same target batch.

### Milestone 4: Re-measure pass3 locally and ship a compact pass3 path that removes duplicated structured content

Do not follow the old "remove raw text" idea because the current local pass3 path already removed raw blocks. Instead, measure the actual local duplication first. Use representative pass3-producing fixtures and existing prompt logs to compare how much of the current pass3 payload is repeated between `schemaorg_recipe.recipeIngredient` or `schemaorg_recipe.recipeInstructions` and the explicit `extracted_ingredients` or `extracted_instructions` arrays.

If that measurement shows material duplication, add a new pipeline asset at `llm_pipelines/pipelines/recipe.final.compact.v1.json` and a new prompt file at `llm_pipelines/prompts/recipe.final.compact.v1.prompt.md`. In `cookimport/llm/codex_farm_contracts.py`, add `Pass3FinalDraftCompactInput` with these fields:

- `recipe_id`, `workbook_slug`, and `source_hash`
- `recipe_metadata`, a reduced dict derived from `schemaorg_recipe` that keeps only title and other non-step, non-ingredient metadata needed for final draft construction
- `extracted_ingredients`
- `extracted_instructions`

In `cookimport/llm/codex_farm_orchestrator.py`, add `_build_pass3_input_legacy(...) -> Pass3FinalDraftInput`, `_build_pass3_recipe_metadata(...) -> dict[str, Any]`, and `_build_pass3_input_compact(...) -> Pass3FinalDraftCompactInput`. Choose between them using `run_settings.codex_farm_pipeline_pass3`. The compact prompt must treat `extracted_ingredients` and `extracted_instructions` as the authoritative text sources and use `recipe_metadata` only for non-duplicated context such as title, yield, or other compact metadata that the final draft still needs.

Add tests in `tests/llm/test_codex_farm_contracts.py`, `tests/llm/test_codex_farm_orchestrator.py`, and `tests/llm/test_llm_pipeline_pack_assets.py` to prove that compact pass3 payloads exclude duplicated `recipeIngredient` and `recipeInstructions` content from the serialized schema payload, preserve output-schema compatibility, and reduce representative payload size by at least 15% versus legacy.

Milestone 4 is complete when pass3 can be switched by pipeline id, the compact path removes duplicated structured content instead of raw-text windows, and representative pass3 payloads are measurably smaller.

### Milestone 5: Validate with focused tests, benchmark replays, and an explicit legacy-vs-compact comparison

Run the relevant focused test suites inside the project-local virtual environment.

From the repository root:

    source .venv/bin/activate
    pip install -e .[dev]
    pytest tests/llm/test_llm_pipeline_pack_assets.py tests/llm/test_codex_farm_contracts.py tests/llm/test_codex_farm_orchestrator.py tests/parsing/test_canonical_line_roles.py tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/bench/test_benchmark_cutdown_for_external_ai.py

Then run paired legacy and compact benchmark replays for at least `DinnerFor2CUTDOWN.epub` and `SaltFatAcidHeatCUTDOWN.epub`. Use canonical-text mode and the same model family for both runs. The compact replay must use compact pass2 and pass3 pipeline ids plus `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1`. The legacy replay must use the current legacy ids and `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=legacy`.

Example legacy command shape:

    cookimport labelstudio-benchmark run \
      --gold-spans data/golden/pulled-from-labelstudio/dinnerfor2cutdown/exports/freeform_span_labels.jsonl \
      --source-file data/input/DinnerFor2CUTDOWN.epub \
      --eval-mode canonical-text \
      --no-upload \
      --output-dir data/golden/benchmark-vs-golden \
      --processed-output-dir data/output \
      --llm-recipe-pipeline codex-farm-3pass-v1 \
      --line-role-pipeline codex-line-role-v1 \
      --atomic-block-splitter atomic-v1 \
      --codex-farm-pipeline-pass2 recipe.schemaorg.v1 \
      --codex-farm-pipeline-pass3 recipe.final.v1

Example compact command shape:

    COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=compact_v1 \
    cookimport labelstudio-benchmark run \
      --gold-spans data/golden/pulled-from-labelstudio/dinnerfor2cutdown/exports/freeform_span_labels.jsonl \
      --source-file data/input/DinnerFor2CUTDOWN.epub \
      --eval-mode canonical-text \
      --no-upload \
      --output-dir data/golden/benchmark-vs-golden \
      --processed-output-dir data/output \
      --llm-recipe-pipeline codex-farm-3pass-v1 \
      --line-role-pipeline codex-line-role-v1 \
      --atomic-block-splitter atomic-v1 \
      --codex-farm-pipeline-pass2 recipe.schemaorg.compact.v1 \
      --codex-farm-pipeline-pass3 recipe.final.compact.v1

Repeat the same pair for `data/input/SaltFatAcidHeatCUTDOWN.epub`.

Inspect these artifacts after each compact run:

- `prediction-run/prompt_budget_summary.json`
- `prediction-run/manifest.json`
- `run_manifest.json`
- the benchmark packaging/runtime summary artifact path that currently surfaces call runtime totals

Acceptance for the full plan is:

- each compact benchmark run writes `prediction-run/prompt_budget_summary.json` with non-null token totals for every active pass, including `line_role`
- benchmark packaging/reporting shows `line_role` as a pass bucket instead of hiding it outside the pass summary
- pass2 compact fixtures are at least 35% smaller than legacy fixtures in bytes
- line-role compact fixtures are at least 20% smaller than legacy fixtures in bytes
- pass3 compact fixtures are at least 15% smaller than legacy fixtures in bytes
- the combined compact replay for the two-book sample shows a material token reduction versus legacy, with the measured total recorded back into this plan before any default flips

Only after these validations pass may defaults change. For recipe prompts, that means changing the default pass pipeline ids to the compact ids. For line-role, that means changing the default local prompt-format resolver from `legacy` to `compact_v1`.

## Concrete Steps

All commands below are run from `/home/mcnal/projects/recipeimport`.

1. Prepare the environment:

       source .venv/bin/activate
       pip install -e .[dev]

2. Implement Milestone 1 and run focused tests:

       pytest tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/bench/test_benchmark_cutdown_for_external_ai.py

3. Implement Milestones 2 through 4 and run focused tests:

       pytest tests/llm/test_llm_pipeline_pack_assets.py tests/llm/test_codex_farm_contracts.py tests/llm/test_codex_farm_orchestrator.py tests/parsing/test_canonical_line_roles.py

4. Run the full focused suite after all prompt-budget and compaction changes:

       pytest tests/llm/test_llm_pipeline_pack_assets.py tests/llm/test_codex_farm_contracts.py tests/llm/test_codex_farm_orchestrator.py tests/parsing/test_canonical_line_roles.py tests/labelstudio/test_labelstudio_benchmark_helpers.py tests/bench/test_benchmark_cutdown_for_external_ai.py

5. Run the two legacy benchmark replays and save the output roots.

6. Run the two compact benchmark replays and save the output roots.

7. Compare `prediction-run/prompt_budget_summary.json` across legacy and compact runs for the same book and record the deltas in this plan's `Outcomes & Retrospective` section.

8. If desired, build or refresh benchmark cutdown/starter-pack artifacts from the resulting run roots and confirm that their runtime summary includes `line_role`.

## Validation and Acceptance

Validation is both automated and artifact-based.

Automated validation is the focused pytest suite listed above. Those tests must prove that compact assets are wired correctly, compact payload builders omit the intended duplicated fields, and runtime summaries surface `line_role` as a pass bucket.

Artifact validation is done by inspecting real benchmark outputs. For a compact benchmark run, a human should be able to open `prediction-run/prompt_budget_summary.json` and see one summary with `pass1`, `pass2`, `pass3`, and `line_role`. The human should then be able to compare the compact and legacy files for the same book and see that compact prompt totals are lower while the benchmark still emits the same categories of evaluation artifacts as before.

The plan is not complete merely because the code compiles. It is complete only when compact benchmark runs visibly produce the new prompt-budget artifact, benchmark-facing summaries stop hiding line-role from pass totals, and the measured token totals for the two-book replay are lower than legacy.

## Idempotence and Recovery

All changes in this plan are safe to rerun.

Recipe prompt rollback is simple because the compact rollout uses explicit pipeline ids. If a compact recipe prompt misbehaves, switch `--codex-farm-pipeline-pass2` back to `recipe.schemaorg.v1` and `--codex-farm-pipeline-pass3` back to `recipe.final.v1`. No schema migration or artifact rewrite is required.

Line-role rollback is equally simple. Set `COOKIMPORT_LINE_ROLE_PROMPT_FORMAT=legacy` and rerun the benchmark. Because the output parser stays unchanged, rollback affects only prompt input shape.

If benchmark packaging or runtime summary readers encounter an older run root with no `prompt_budget_summary.json`, they must continue to fall back to the existing manifest telemetry readers. This fallback is required so old artifacts remain readable.

## Artifacts and Notes

The most important artifacts produced by this plan are:

- `prediction-run/prompt_budget_summary.json`
- `prediction-run/manifest.json` with a pointer to that summary
- `run_manifest.json` with the same artifact pointer
- compact pipeline asset files under `llm_pipelines/pipelines/`
- compact prompt templates under `llm_pipelines/prompts/`
- line-role prompt artifacts under `prediction-run/line-role-pipeline/prompts/`

Representative evidence that should be copied back into this plan as implementation proceeds:

- one legacy and one compact `prompt_budget_summary.json` excerpt for the same book
- one compact pass2 input JSON example showing the compact `evidence_rows` field
- one compact line-role prompt excerpt showing the tuple schema header and tuple rows
- one compact pass3 input JSON example showing `recipe_metadata` without duplicated `recipeIngredient` and `recipeInstructions`

## Interfaces and Dependencies

The end state of this plan must provide these stable interfaces.

In `cookimport/llm/prompt_budget.py`, define:

    def build_prediction_run_prompt_budget_summary(
        pred_manifest: Mapping[str, Any],
        pred_run_dir: Path,
    ) -> dict[str, Any]:
        ...

    def write_prediction_run_prompt_budget_summary(
        pred_run_dir: Path,
        summary: Mapping[str, Any],
    ) -> Path:
        ...

In `cookimport/llm/codex_farm_contracts.py`, define:

    class Pass2SchemaOrgCompactInput(BaseModel):
        bundle_version: Literal["1"]
        recipe_id: str
        workbook_slug: str
        source_hash: str
        evidence_rows: list[tuple[int, str]]

    class Pass3FinalDraftCompactInput(BaseModel):
        bundle_version: Literal["1"]
        recipe_id: str
        workbook_slug: str
        source_hash: str
        recipe_metadata: dict[str, Any]
        extracted_ingredients: list[str]
        extracted_instructions: list[str]

In `cookimport/llm/canonical_line_role_prompt.py`, define:

    def serialize_line_role_targets_legacy(targets: Sequence[AtomicLineCandidate]) -> str:
        ...

    def serialize_line_role_targets_compact(targets: Sequence[AtomicLineCandidate]) -> str:
        ...

    def build_canonical_line_role_prompt(
        targets: Sequence[AtomicLineCandidate],
        *,
        allowed_labels: Sequence[str] | None = None,
        prompt_format: str = "legacy",
    ) -> str:
        ...

In `cookimport/parsing/canonical_line_roles.py`, define one local resolver:

    def _resolve_line_role_prompt_format() -> str:
        ...

The compact recipe pipeline assets must exist as:

- `llm_pipelines/pipelines/recipe.schemaorg.compact.v1.json`
- `llm_pipelines/prompts/recipe.schemaorg.compact.v1.prompt.md`
- `llm_pipelines/pipelines/recipe.final.compact.v1.json`
- `llm_pipelines/prompts/recipe.final.compact.v1.prompt.md`

The output schemas for pass2 and pass3 must remain the existing ones unless a separate plan explicitly changes output contracts.

## Revision Note

This plan was updated on 2026-03-05_23.09.25 because the current repo expects docs front matter and normalized timestamps. The content still reflects the earlier repo-local rewrite, which replaced stale assumptions with the actual local implementation seams: existing line-role telemetry, `llm_pipelines`-driven recipe prompts, `RunSettings` pipeline-id rollout, and current pass3 duplication shape.
