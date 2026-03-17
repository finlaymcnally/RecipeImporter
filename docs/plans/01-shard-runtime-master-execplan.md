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
- [ ] Keep this master plan aligned as the line-role, recipe, knowledge, and observability/removal child plans land.

## Surprises & Discoveries

- Observation: the original long plan already had the right decomposition hidden inside it. Its milestones were not arbitrary; they naturally separated into one runtime spine, three phase migrations, and one cross-cutting observability/removal pass.
  Evidence: `docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md` has Milestone 1 for the shared runtime, Milestones 2 through 4 for line-role, recipe, and knowledge, and Milestone 5 for preview, prompt exports, upload bundles, and legacy removal.

- Observation: only part of the work is safely parallelizable. The runtime and interface work is the dependency spine, while the downstream benchmark and review surfaces need stable telemetry and artifact schemas before they can be finished cleanly.
  Evidence: the original plan’s `Interfaces and Dependencies` section defines shared runtime types in `cookimport/llm/phase_worker_runtime.py` and shared telemetry seams in `cookimport/llm/prompt_preview.py`, `cookimport/llm/prompt_artifacts.py`, and `cookimport/bench/upload_bundle_v1_*`.

- Observation: freezing shard-v1 ids in the foundation plan still required a central normalization pass because many current review/export surfaces were written against the old ids.
  Evidence: `docs/understandings/2026-03-17_12.18.01-foundation-needs-central-pipeline-id-normalization-before-phase-cutovers.md`.

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

## Outcomes & Retrospective

The split is complete as documentation, and the first implementation child plan is now complete: the shared runtime/config foundation has landed.

The expected outcome remains better execution, not different product behavior. The current state validates the decomposition: the runtime spine landed without forcing the real line-role/recipe/knowledge cutovers into the same patch. The remaining retrospective question is whether the three phase plans stay genuinely independent now that they are unblocked.

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

The dependency graph is simple. The foundation plan has now landed and frozen the shared interfaces. The line-role, recipe, and knowledge plans can now proceed largely independently. The final observability/removal plan should finish after the phase telemetry and runtime artifacts are stable enough that preview, prompt exports, and upload bundles will not churn underneath it.

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
