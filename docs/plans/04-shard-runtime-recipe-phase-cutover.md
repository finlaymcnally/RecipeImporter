---
summary: "ExecPlan for migrating `recipe_llm_correct_and_link` from one-recipe Codex calls to the shared shard-worker runtime under `codex-recipe-shard-v1`."
read_when:
  - "When replacing recipe correction and linkage execution with shard workers."
  - "When implementing bounded multi-recipe shards over deterministic intermediate recipe objects."
  - "When one contributor is assigned only the recipe slice of the shard-runtime refactor."
---

# Migrate Recipe Correction And Linkage To Shard Workers

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, `recipe_llm_correct_and_link` will stop paying for one fresh Codex execution per recipe-shaped task. The deterministic recipe-preparation stages will remain exactly where they are, but the optional Codex-backed correction stage will package nearby recipes into explicit shards and let one bounded worker process several shards under one instruction context.

The visible behavior after this plan is complete is that the staged recipe pipeline still yields one corrected result and one linkage payload per `recipe_id`, and `build_final_recipe` still remains deterministic. What changes is only the execution model and runtime observability beneath that existing contract.

## Progress

- [x] (2026-03-17_11.55.03) Derived this child plan from the original shard-runtime ExecPlan while keeping the original untouched.
- [x] (2026-03-17_12.18.01) Confirmed that the foundation plan had already landed and that the shared runtime plus shard-v1 run-setting interfaces were frozen.
- [x] (2026-03-17_12.40.02) Replaced the one-recipe-per-call execution path in `cookimport/llm/codex_farm_orchestrator.py` with contiguous multi-recipe shard planning and shared-runtime execution.
- [x] (2026-03-17_12.40.02) Preserved deterministic `group_recipe_spans`, `build_intermediate_det`, and deterministic final assembly as the authority boundaries around the recipe worker runtime.
- [x] (2026-03-17_12.40.02) Enforced exact-once `recipe_id` ownership through shard-output validation and promoted schema-valid per-recipe corrected structures plus linkage payloads back into the existing stage contract.
- [x] (2026-03-17_12.40.02) Added focused tests for recipe shard planning, promotion, runtime artifacts, pipeline-pack assets, and deterministic final-assembly compatibility.

## Surprises & Discoveries

- Observation: several current recipe prompts are weak even before the runtime refactor because they contain very little evidence.
  Evidence: the original shard-runtime plan recorded many recipe prompts with only two or three evidence rows, which suggests grouping and ownership quality matter as much as session reuse.

- Observation: the recipe phase is more constrained than line-role because it must preserve provenance and linkage data for deterministic final assembly.
  Evidence: `build_final_recipe` remains deterministic and therefore depends on stable corrected intermediate structures plus linkage payloads, not free-form direct mutation by the worker.

- Observation: the clean cutover shape is to keep shard-worker runtime artifacts separate from the promoted per-recipe artifacts that older readers still consume.
  Evidence: `docs/understandings/2026-03-17_12.40.02-recipe-shard-cutover-needs-separate-runtime-and-promoted-artifacts.md` records that `recipe_phase_runtime/` can hold shard manifests, worker telemetry, and proposals while `recipe_correction/{in,out}` and `recipe_correction_audit/` keep the per-recipe promoted/debug bridge stable.

## Decision Log

- Decision: this plan keeps `group_recipe_spans` and `build_intermediate_det` fully deterministic and treats them as immutable upstream prep.
  Rationale: the shard-runtime refactor changes execution strategy, not the authority boundary between labels, recipe grouping, deterministic intermediate building, and final assembly.
  Date/Author: 2026-03-17 / Codex

- Decision: recipe shards should be bounded multi-recipe groups in local recipe order rather than arbitrary prompt-sized packing.
  Rationale: local grouping amortizes repeated guidance while preserving replayable ownership and stable provenance references.
  Date/Author: 2026-03-17 / Codex

- Decision: inline recipe tagging continues to ride on the recipe-correction contract.
  Rationale: re-splitting tagging into a separate subsystem would expand the scope and undo the current product shape.
  Date/Author: 2026-03-17 / Codex

- Decision: keep the compact pack id `recipe.correction.compact.v1` under the shard-worker runtime rather than inventing a second recipe pack in the same patch.
  Rationale: the runtime cutover required explicit shard ownership, worker reuse, validation, and promotion. Reusing the compact pack kept the prompt/schema migration bounded while the orchestrator moved to the new runtime.
  Date/Author: 2026-03-17 / Codex

- Decision: preserve compatibility per-recipe `recipe_correction/{in,out}` artifacts and `recipe_correction_audit/` outputs even though live execution is now shard-based.
  Rationale: those artifacts are promoted reviewer/debug surfaces, not the runtime authority. Keeping them lets deterministic final assembly and older read-side tooling keep working while shard-worker manifests, telemetry, and proposals move to `recipe_phase_runtime/`.
  Date/Author: 2026-03-17 / Codex

## Outcomes & Retrospective

Implementation is complete for this slice. The recipe phase now keeps the current staged architecture intact while replacing the one-recipe execution model with bounded workers over explicit shards.

The live result is:

- deterministic preparation still owns recipe boundaries and intermediate objects
- contiguous multi-recipe shards are validated through `phase_worker_runtime.py`
- promotion now writes corrected intermediate overrides plus final draft overrides per `recipe_id`
- runtime manifests, assignments, telemetry, failures, and shard proposals live under `recipe_phase_runtime/`
- compatibility per-recipe inputs, outputs, and audits still land under `recipe_correction/{in,out}` plus `recipe_correction_audit/`

The remaining work for the broader refactor is outside this plan: line-role still needs its own cutover, and the final observability/removal pass still needs to rewire prompt-preview, prompt exports, and upload-bundle surfaces around the stabilized runtime artifacts.

## Context and Orientation

The recipe cutover sits in the middle of the stage pipeline. Upstream, `group_recipe_spans` groups recipes from corrected labels and `build_intermediate_det` produces deterministic intermediate recipe objects with provenance and warnings. Downstream, `build_final_recipe` remains deterministic and consumes promoted corrected structures plus linkage payloads. This plan changes only the Codex-backed correction step in `cookimport/llm/codex_farm_orchestrator.py`.

This plan assumes the shared runtime from `cookimport/llm/phase_worker_runtime.py` already exists and that the recipe worker knobs and pipeline-id routing exist in `cookimport/config/run_settings.py`. If those interfaces are unstable, complete the foundation plan first.

For this phase, a shard is a bounded group of owned `recipe_id`s with local recipe-order context, original labeled blocks, grouped-span metadata, deterministic intermediate recipe objects, parser warnings, provenance references, and a strict output contract. A worker is one bounded recipe-correction session that may process multiple recipe shards in sequence.

The main files for this plan are:

- `cookimport/llm/codex_farm_orchestrator.py`
- any recipe prompt or schema assets consumed by that orchestrator
- deterministic stage code only where minor glue changes are necessary to preserve the current contract
- `tests/llm/test_codex_farm_orchestrator.py`
- `tests/llm/test_recipe_phase_workers.py`

## Milestones

### Milestone 1: Replace one-recipe execution with recipe shard planning

Refactor `cookimport/llm/codex_farm_orchestrator.py` so it builds explicit recipe shards from deterministic intermediate recipe objects instead of creating one fresh Codex execution per recipe task. Each shard should declare owned `recipe_id`s, evidence references, provenance references, and payload metrics suitable for worker assignment.

Acceptance for this milestone is a focused test that proves all intended `recipe_id`s are covered exactly once, shard IDs are stable under stable inputs, and one worker can own multiple recipe shards.

### Milestone 2: Validate corrected intermediate outputs and preserve deterministic final assembly

Use the shared runtime to collect corrected intermediate recipe objects and linkage payloads. Validation must enforce exact-once ownership, schema validity, linkage integrity, provenance preservation, and no edits outside owned `recipe_id`s. Promotion must write back into the existing `recipe_llm_correct_and_link` artifact shape so `build_final_recipe` can remain deterministic.

Acceptance for this milestone is a test that shows corrected structures and linkage payloads are promoted into the normal stage outputs and can still drive deterministic final recipe assembly.

### Milestone 3: Prove runtime legibility and tagging continuity

Add focused tests or assertions that show inline tagging still flows through the recipe-correction contract and that runtime artifacts make shard-worker execution legible. This plan does not own final benchmark prompt exports or upload-bundle rendering, but it must emit stable runtime telemetry and prompt/debug references for the later observability plan.

Acceptance for this milestone is passing focused tests plus runtime artifacts that clearly show multiple recipe shards processed under bounded workers while preserving one corrected result per `recipe_id`.

## Plan of Work

Begin in `cookimport/llm/codex_farm_orchestrator.py` by locating the current one-recipe execution unit and replacing it with recipe shard planning. Keep the deterministic upstream prep untouched. The new planner should group nearby recipes into replayable ownership units with explicit provenance and warning data.

Next, wire the recipe planner into the shared runtime. Provide phase-specific validation that enforces exact ownership, schema integrity, provenance preservation, and linkage consistency. The promotion step must continue to write the corrected intermediate structures and linkage payloads into the existing stage contract consumed by `build_final_recipe`.

Then add tests. Extend `tests/llm/test_codex_farm_orchestrator.py` for deterministic orchestration contracts and add or update `tests/llm/test_recipe_phase_workers.py` for shard-worker behavior. The tests should prove coverage, validation, promotion, deterministic final-assembly compatibility, and continuity of the inline tagging contract.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport` and activate the local virtual environment:

    source .venv/bin/activate
    pip install -e .[dev]

Read the relevant context:

    sed -n '1,260p' docs/plans/02-shard-runtime-foundation-runtime-and-config.md
    sed -n '1,260p' cookimport/llm/codex_farm_orchestrator.py

Implement the cutover and run focused tests:

    source .venv/bin/activate
    pytest tests/llm/test_codex_farm_orchestrator.py tests/llm/test_recipe_phase_workers.py tests/llm/test_prompt_preview.py -q

The expected outcome is passing tests that demonstrate:

    - recipe shards cover all intended `recipe_id`s exactly once
    - one worker may process multiple recipe shards
    - corrected intermediate structures remain schema-valid
    - provenance and linkage are preserved
    - promoted outputs still support deterministic final recipe assembly

## Validation and Acceptance

This plan is accepted when a contributor can run the focused tests and observe that recipe correction still yields one corrected result and one linkage payload per `recipe_id`, the downstream deterministic assembly remains intact, and the runtime artifacts show bounded workers over explicit recipe shards.

Acceptance does not require the final prompt-preview, prompt-export, or upload-bundle cutover yet, but it does require that the recipe phase now emits runtime artifacts and telemetry consistent with the shared shard-worker model.

## Idempotence and Recovery

Recipe shard IDs should derive from stable recipe order and stable ownership inputs so replay stays legible. If a worker fails, completed shard proposals should remain inspectable and retryable without rerunning the whole book. If preserving provenance or linkage requires a shared-runtime contract change, update the foundation plan and runtime in the same pass rather than hiding recipe-specific exceptions locally.

## Artifacts and Notes

This plan should preserve the authoritative promoted recipe artifacts while adding inspectable runtime artifacts for recipe shards and workers. The most important proof points are:

- stable recipe shard ownership
- worker assignments spanning multiple recipe shards
- validated corrected intermediate recipe proposals
- preserved linkage payloads and provenance references
- promoted outputs still consumable by deterministic final assembly

## Interfaces and Dependencies

This plan depends on the shared interfaces from the foundation plan and should consume at least:

- `llm_recipe_pipeline: Literal["off", "codex-recipe-shard-v1"]`
- `recipe_worker_count: int | None`
- `recipe_shard_target_recipes: int | None`
- `recipe_shard_max_turns: int | None`
- `run_phase_workers_v1(...)` from `cookimport/llm/phase_worker_runtime.py`

At the end of this plan, `cookimport/llm/codex_farm_orchestrator.py` must route recipe correction through `codex-recipe-shard-v1` and still promote one corrected recipe result plus one linkage payload per `recipe_id` into the existing stage artifact contract.

Revision note: this plan was created by splitting the original shard-runtime ExecPlan into a narrower recipe implementation plan that can run independently after the shared runtime foundation is stable.

Revision note (2026-03-17_12.40.02): updated this plan after implementation to mark the recipe cutover complete, record the separate runtime-vs-promoted-artifacts discovery, and document that the live recipe phase now executes bounded multi-recipe shards through `phase_worker_runtime.py` while preserving the deterministic final-assembly contract.
