---
summary: "Master ExecPlan for splitting the shard-runtime refactor into one foundation plan, three phase cutover plans, and one final observability/removal plan."
read_when:
  - "When coordinating the shard-runtime refactor across multiple smaller ExecPlans."
  - "When deciding which shard-runtime child plans can run in sequence versus in parallel."
  - "When you need the high-level dependency map for the shard-v1 cutover."
---

# Coordinate The Shard Runtime Refactor Across Child ExecPlans

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, the repo will no longer rely on one giant implementation plan for the shard-runtime refactor. Instead, a novice can follow one master plan that explains the dependency graph, then execute five smaller plans with clear ownership boundaries. This matters because the work is large but not monolithic: one shared runtime has to land first, three phase cutovers can mostly proceed independently after that, and one final cutover has to update the operator-facing review and benchmark surfaces.

The user-visible result is organizational rather than runtime behavior. A contributor will be able to open `docs/plans/`, pick the exact shard-runtime slice they are implementing, and know whether that slice can be built alone, in sequence, or in parallel with another slice. The original long plan remains checked in as the archival record of how the refactor was first framed.

## Progress

- [x] (2026-03-17_11.49.08) Re-read `docs/PLANS.md` and the original shard-runtime ExecPlan before deciding whether to split the work.
- [x] (2026-03-17_11.49.08) Wrote `docs/understandings/2026-03-17_11.49.08-shard-runtime-plan-splits-into-spine-phases-and-cutover.md` to capture the dependency graph discovered during review.
- [x] (2026-03-17_11.55.00) Decided to keep `docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md` untouched as the archival record.
- [x] (2026-03-17_11.55.00) Added this master ExecPlan plus five child ExecPlans in `docs/plans/`.
- [x] (2026-03-17_12.18.01) Completed the foundation runtime/config milestone from `docs/plans/02-shard-runtime-foundation-runtime-and-config.md`.
- [x] (2026-03-17_12.18.01) Updated this master plan to reflect that the three phase cutover plans are now unblocked on shared runtime contracts.
- [x] (2026-03-17_12.38.37) Completed the knowledge cutover plan from `docs/plans/05-shard-runtime-knowledge-phase-cutover.md`.
- [x] (2026-03-17_12.40.02) Completed the recipe cutover plan from `docs/plans/04-shard-runtime-recipe-phase-cutover.md`.
- [x] (2026-03-17_12.41.48) Completed the line-role cutover plan from `docs/plans/03-shard-runtime-line-role-phase-cutover.md`.
- [x] (2026-03-17_12.59.54) Tightened the landed knowledge slice by removing the dead direct `knowledge/out` ingest helper and aligning the docs with proposal-validated runtime authority.
- [x] (2026-03-17_13.23.02) Completed the observability/removal child plan from `docs/plans/06-shard-runtime-observability-and-legacy-cutover.md`.
- [x] (2026-03-17_13.39.45) Updated this master plan to reflect a full code-side shard-runtime cutover, including removal of the last legacy pipeline-id normalization seam on active run-setting inputs, with only the human-run live benchmark remaining outside the agent shell.

## Surprises & Discoveries

- Observation: the original long plan already had the right decomposition hidden inside it. Its milestones were not arbitrary; they naturally separated into one runtime spine, three phase migrations, and one cross-cutting observability/removal pass.
  Evidence: `docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md` has Milestone 1 for the shared runtime, Milestones 2 through 4 for line-role, recipe, and knowledge, and Milestone 5 for preview, prompt exports, upload bundles, and legacy removal.

- Observation: only part of the work is safely parallelizable. The runtime and interface work is the dependency spine, while the downstream benchmark and review surfaces need stable telemetry and artifact schemas before they can be finished cleanly.
  Evidence: the original plan’s `Interfaces and Dependencies` section defines shared runtime types in `cookimport/llm/phase_worker_runtime.py` and shared telemetry seams in `cookimport/llm/prompt_preview.py`, `cookimport/llm/prompt_artifacts.py`, and `cookimport/bench/upload_bundle_v1_*`.

- Observation: freezing shard-v1 ids in the foundation plan still required a central normalization pass because many current review/export surfaces were written against the old ids.
  Evidence: `docs/understandings/2026-03-17_12.18.01-foundation-needs-central-pipeline-id-normalization-before-phase-cutovers.md`.

- Observation: the knowledge slice did not need a brand-new Codex pack id underneath the public shard-v1 setting in order to land the real runtime cutover.
  Evidence: `docs/understandings/2026-03-17_12.38.37-knowledge-shard-cutover-can-keep-compact-pack-under-runtime.md` records that the live runtime now owns shard manifests, worker execution, proposal validation, and promotion while older prompt/debug readers still bridge through compatibility `knowledge/{in,out}` files.

- Observation: the recipe slice followed the same durable pattern as knowledge: runtime truth can move to shard-worker execution without forcing every older per-item read surface to become the runtime authority in the same patch.
  Evidence: `docs/understandings/2026-03-17_12.40.02-recipe-shard-cutover-needs-separate-runtime-and-promoted-artifacts.md` records that the recipe cutover now writes shard manifests, worker telemetry, and proposals under `recipe_phase_runtime/` while keeping promoted per-recipe compatibility artifacts under `recipe_correction/{in,out}` and `recipe_correction_audit/`.

- Observation: line-role needed the same separation, but with one extra twist: the shared runtime had to support raw prompt-text inputs while the old prompt artifact files stayed alive for reviewer/export tooling.
  Evidence: `docs/understandings/2026-03-17_12.41.48-line-role-shard-cutover-needs-raw-prompt-inputs-but-keeps-prompt-artifacts.md` records the added `input_text` seam in `ShardManifestEntryV1` plus the compatibility `line-role-pipeline/prompts/*` writes kept by `canonical_line_roles.py`.

- Observation: the final observability pass did not need to delete prompt reviewer files to finish the cutover; it only needed to make those files honest about shard ownership.
  Evidence: `docs/understandings/2026-03-17_13.23.02-preview-and-prompt-artifacts-can-stay-reviewer-friendly-while-shard-owned.md`.

## Decision Log

- Decision: keep the original long shard-runtime ExecPlan intact and create new plans around it rather than rewriting history.
  Rationale: the original file is still useful design evidence, and the user explicitly asked to preserve it as the record.
  Date/Author: 2026-03-17 / Codex

- Decision: use one master plan plus five child plans instead of trying to make six equal peers.
  Rationale: the work has one clear dependency graph. A master plan is the right place to explain sequencing, handoff rules, and parallelism constraints without bloating every child plan.
  Date/Author: 2026-03-17 / Codex

- Decision: sequence the work as foundation first, then the three phase cutovers, then the observability/removal cutover.
  Rationale: that matches the existing architecture and minimizes merge conflicts and schema churn.
  Date/Author: 2026-03-17 / Codex

- Decision: treat the three phase cutovers as mostly parallelizable only after the foundation plan has landed or its interfaces are frozen.
  Rationale: line-role, recipe, and knowledge live in separate modules, but they all depend on the same manifest, worker-runtime, runner-audit, and promotion contracts.
  Date/Author: 2026-03-17 / Codex

- Decision: treat the broader wording/export cleanup for old pipeline ids as part of the observability/removal plan, not the foundation milestone.
  Rationale: the runtime spine is now stable, but cross-cutting preview/benchmark/review surfaces still need their own coordinated pass.
  Date/Author: 2026-03-17 / Codex

- Decision: allow a child phase plan to keep the current compact pack id underneath a shard-v1 public setting when that preserves a stable bridge to the later observability pass.
  Rationale: the architectural goal is bounded shard ownership and replayable runtime artifacts, not a second unnecessary pack rewrite in the same patch. The knowledge cutover proved that runtime truth and read-side cleanup can be sequenced cleanly.
  Date/Author: 2026-03-17 / Codex

- Decision: allow the recipe phase to preserve promoted per-recipe compatibility artifacts even after live execution moves to shard-worker runtime artifacts.
  Rationale: that keeps the runtime cutover narrow and replayable while deferring the broader prompt/export/upload-bundle cleanup to the explicit observability/removal plan.
  Date/Author: 2026-03-17 / Codex

- Decision: treat the observability/removal plan as complete only once active run-setting inputs also reject the retired pipeline ids.
  Rationale: burn-the-boats is an input-contract decision as well as a default/help/docs decision; accepting the old ids still teaches the obsolete runtime surface.
  Date/Author: 2026-03-17 / Codex

## Outcomes & Retrospective

The split is complete as documentation and as code-side implementation. All five child plans have now landed: the shared runtime/config foundation, knowledge cutover, recipe cutover, line-role cutover, and the final observability/removal pass.

The decomposition proved correct. The runtime spine landed first, then knowledge, recipe, and line-role moved execution onto explicit shard-worker runtime artifacts, and the final cross-cutting pass finished preview, prompt exports, upload-bundle context, active CLI/default cleanup, and strict shard-v1-only run-setting inputs without another schema rewrite underneath them. Only the explicitly human-run live benchmark remains outside the agent shell.

## Context and Orientation

The shard-runtime refactor preserves the current stage pipeline and changes only how the Codex-backed work is executed. The three affected Codex-backed stages are `label_llm_correct`, `recipe_llm_correct_and_link`, and `extract_knowledge_optional`. They currently live in different parts of the repository:

- `cookimport/parsing/canonical_line_roles.py` for line-role correction
- `cookimport/llm/codex_farm_orchestrator.py` for recipe correction and linkage
- `cookimport/llm/codex_farm_knowledge_orchestrator.py` and related knowledge files for knowledge refinement

All three phases will depend on the same new shared runtime in `cookimport/llm/phase_worker_runtime.py` and the same runner seam in `cookimport/llm/codex_farm_runner.py`. The operator-facing evidence surfaces that must be updated at the end of the migration are `cookimport/llm/prompt_preview.py`, benchmark `prompts/` exports, and `upload_bundle_v1`.

This master plan coordinates these six plan files:

- archival source plan: `docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md`
- master coordination plan: `docs/plans/01-shard-runtime-master-execplan.md`
- foundation plan: `docs/plans/02-shard-runtime-foundation-runtime-and-config.md`
- line-role plan: `docs/plans/03-shard-runtime-line-role-phase-cutover.md`
- recipe plan: `docs/plans/04-shard-runtime-recipe-phase-cutover.md`
- knowledge plan: `docs/plans/05-shard-runtime-knowledge-phase-cutover.md`
- observability/removal plan: `docs/plans/06-shard-runtime-observability-and-legacy-cutover.md`

The dependency graph is simple. The foundation plan has landed and frozen the shared interfaces. The line-role, recipe, and knowledge plans have all landed. The final observability/removal plan should now finish after consuming the stabilized phase telemetry and runtime artifacts without introducing another round of schema churn underneath preview, prompt exports, or upload bundles.

## Milestones

### Milestone 1: Establish the shared runtime spine

At the end of this milestone, contributors have a stable foundation plan to follow. That plan owns the worker runtime, manifests, config knobs, runner audit mode, sandbox rules, and fake-phase tests. Nothing in this milestone changes the semantic stage model yet. The point is to create the new execution substrate once, in one place, before any phase-specific migration starts.

Acceptance for this milestone is that a contributor can complete `docs/plans/02-shard-runtime-foundation-runtime-and-config.md` and come away with stable interfaces that the three phase plans can consume without inventing their own runtime variants.

### Milestone 2: Migrate the three phase implementations

At the end of this milestone, the three Codex-backed phase families each have their own dedicated child plan. The line-role plan migrates `label_llm_correct`. The recipe plan migrates `recipe_llm_correct_and_link`. The knowledge plan migrates `extract_knowledge_optional`. These three slices may be implemented in parallel once the foundation types and hooks are fixed.

Acceptance for this milestone is that a contributor can pick exactly one child plan, work inside its owned modules and tests, and not need to reverse-engineer the rest of the refactor.

### Milestone 3: Update the human-facing evidence surfaces and retire the old runtime

At the end of this milestone, preview, benchmark prompt exports, upload bundles, CLI defaults, and legacy-id handling all describe the shard-worker model accurately. This plan is cross-cutting on purpose because these surfaces should stay aligned with each other.

Acceptance for this milestone is completion of `docs/plans/06-shard-runtime-observability-and-legacy-cutover.md` after the phase outputs and telemetry schemas are stable.

## Plan of Work

Treat this master plan as the entrypoint, not the implementation checklist. A contributor should first read this file, then the original archival plan, then the child plan they intend to execute. If the work is being distributed across multiple agents, assign exact file ownership by child plan and avoid mixing runtime-spine edits with phase-specific edits in the same worker unless the runtime interfaces are still unsettled.

If only one contributor is implementing the refactor, follow the child plans in order: foundation, line-role, recipe, knowledge, observability/removal. If multiple contributors are implementing it, finish the foundation plan first, freeze the shared interfaces, then split the three phase plans across separate workers. The observability/removal plan should be held back until the runtime artifacts and phase telemetry are stable enough that it will not need to be rewritten twice.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`.

Read the coordinating documents in this order:

    sed -n '1,260p' docs/PLANS.md
    sed -n '1,320p' docs/plans/01-shard-runtime-master-execplan.md
    sed -n '1,420p' docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md

For single-contributor execution, then read the child plans in sequence:

    sed -n '1,360p' docs/plans/02-shard-runtime-foundation-runtime-and-config.md
    sed -n '1,360p' docs/plans/03-shard-runtime-line-role-phase-cutover.md
    sed -n '1,360p' docs/plans/04-shard-runtime-recipe-phase-cutover.md
    sed -n '1,360p' docs/plans/05-shard-runtime-knowledge-phase-cutover.md
    sed -n '1,360p' docs/plans/06-shard-runtime-observability-and-legacy-cutover.md

For multi-agent execution, assign workers after the foundation interfaces are agreed:

    Agent A: foundation runtime and config
    Agent B: line-role cutover
    Agent C: recipe cutover
    Agent D: knowledge cutover
    Agent E: observability and legacy removal after schemas stabilize

The expected outcome is not terminal output. The proof is that each contributor knows exactly which plan to follow and whether their slice is blocked on another slice.

## Validation and Acceptance

This documentation split is accepted when all six plan files exist, the original long plan remains untouched, and a novice can answer these questions by reading the docs alone:

- which plan lands first
- which plans can run in parallel
- which files each child plan primarily owns
- which plan owns preview, prompt exports, upload bundles, and legacy-id removal

The implementation effort that follows these docs is accepted only when all five child plans are complete and the final live benchmark validation from the observability/removal plan succeeds.

## Idempotence and Recovery

Creating these plans is safe to repeat as long as the original archival plan is left intact. If the child-plan boundaries prove wrong during implementation, revise this master plan and the affected child plans rather than editing the archival original. If implementation finishes one child plan but blocks on another, the master plan should still let a newcomer resume the remaining work without guessing at the intended sequence.

## Artifacts and Notes

The primary reference artifacts for this split are:

- `docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md`
- `docs/reports/1 - refactor-shard-agents.md`
- `docs/understandings/2026-03-17_11.49.08-shard-runtime-plan-splits-into-spine-phases-and-cutover.md`

The child plans are intentionally narrower than the archival original. That is the whole point of the split. They should stay aligned with the original design intent, but they are allowed to be more explicit about ownership, sequencing, and validation for one slice at a time.

## Interfaces and Dependencies

The stable cross-plan dependencies that all child plans must agree on are:

- the shard-v1 pipeline ids: `codex-line-role-shard-v1`, `codex-recipe-shard-v1`, and `codex-knowledge-shard-v1`
- the shared runtime module: `cookimport/llm/phase_worker_runtime.py`
- the runner seam and audit mode in `cookimport/llm/codex_farm_runner.py`
- the worker-runtime artifact family: `phase_manifest.json`, `shard_manifest.jsonl`, `worker_assignments.json`, `promotion_report.json`, `telemetry.json`, `failures.json`, per-worker logs, and per-shard proposals
- the downstream evidence surfaces: `cookimport/llm/prompt_preview.py`, benchmark `prompts/` exports, and `cookimport/bench/upload_bundle_v1_*`

If any child plan needs to change one of these shared contracts, it must update this master plan and the other affected child plans in the same pass.

Revision note: this file was created to split the original long shard-runtime ExecPlan into one master coordination plan and five implementation child plans while preserving the original file as the archival record.

Revision note (2026-03-17_12.18.01): updated this master plan after the foundation milestone landed so the child-plan status now reflects a completed runtime spine and unblocked phase cutover plans.

Revision note (2026-03-17_12.38.37): updated this master plan after the knowledge cutover landed so the progress, discoveries, and retrospective now reflect one completed phase migration in addition to the shared runtime foundation.

Revision note (2026-03-17_12.40.02): updated this master plan after the recipe cutover landed so the progress, discoveries, decisions, and retrospective now reflect two completed phase migrations plus the shared runtime foundation.

Revision note (2026-03-17_12.41.48): updated this master plan after the line-role cutover landed so the progress, discoveries, and retrospective now reflect all three completed phase migrations plus the shared runtime foundation.

Revision note (2026-03-17_12.59.54): tightened the completed knowledge slice by deleting the dead direct `knowledge/out` ingest helper and aligning operator docs with proposal-validated runtime authority.

Revision note (2026-03-17_13.23.02): marked the observability/removal child plan complete after landing worker/shard-centric preview, shard-sweep CLI support, shard-owned prompt export annotations, upload-bundle runtime summaries, active legacy-id cleanup, and focused validation.
