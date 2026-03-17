---
summary: "Foundation ExecPlan for the shard-runtime refactor: shared worker runtime, manifests, config knobs, runner audit mode, and synthetic validation."
read_when:
  - "When implementing the shared shard-worker runtime before any phase-specific cutover."
  - "When freezing the runtime interfaces that line-role, recipe, and knowledge will all consume."
  - "When deciding what has to land before the three phase plans can safely run in parallel."
---

# Build The Shared Shard Runtime Foundation

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, RecipeImport will have one reusable runtime for bounded phase workers over explicit shards. Contributors will no longer need to invent phase-specific mini-runtimes for line-role, recipe, and knowledge work. The new runtime will build manifests, assign shards to workers, materialize clean workspaces, launch Codex through the existing RecipeImport runner seam, collect proposed outputs, validate them, and emit telemetry suitable for later preview and benchmark surfaces.

The user-visible behavior after this plan is complete is still mostly internal. A human will be able to run focused synthetic tests and see that a fake phase now executes through the new runtime, writes inspectable runtime artifacts, and preserves the dedicated RecipeImport Codex-home behavior. No real stage cutover happens in this plan; it creates the substrate that the later phase plans consume.

## Progress

- [x] (2026-03-17_11.55.01) Derived this child plan from the original shard-runtime ExecPlan while keeping the original file untouched.
- [x] (2026-03-17_12.18.01) Added shared runtime types and execution flow in `cookimport/llm/phase_worker_runtime.py`.
- [x] (2026-03-17_12.18.01) Extended `cookimport/llm/codex_farm_runner.py` with a bounded-worker audit mode via `runtime_audit_mode="structured_loop_agentic_v1"`.
- [x] (2026-03-17_12.18.01) Added shard-runtime config knobs and centralized legacy-id normalization in `cookimport/config/run_settings.py`, plus the small routing updates needed for normalized ids to keep working in current seams.
- [x] (2026-03-17_12.18.01) Added synthetic runtime tests that prove manifests, worker assignment, sandbox rules, proposal collection, validation hooks, and Codex-home injection.
- [x] (2026-03-17_12.18.01) Froze the shared interfaces that the three phase cutover plans will consume.

## Surprises & Discoveries

- Observation: the original design challenge is not prompt packing. The missing piece is a genuine runtime abstraction that separates shard ownership from worker lifetime.
  Evidence: `docs/reports/1 - refactor-shard-agents.md` distinguishes a shard as an ownership unit and a worker as a bounded execution context.

- Observation: Codex-home isolation is already solved at the runner layer and should not be reimplemented inside the new runtime.
  Evidence: `cookimport/llm/RECIPE_CODEX_HOME.md` and the original shard-runtime plan both describe runner-owned `CODEX_HOME` and `CODEX_FARM_CODEX_HOME_RECIPE` handling.

- Observation: the repo still contains many old literal pipeline ids outside the immediate runtime spine, so the foundation milestone needed central normalization before the real cutovers could safely change every downstream wording/export surface.
  Evidence: `docs/understandings/2026-03-17_12.18.01-foundation-needs-central-pipeline-id-normalization-before-phase-cutovers.md` captures the spread across CLI, observability, and review surfaces.

## Decision Log

- Decision: this foundation plan should not cut over any real phase by itself.
  Rationale: phase migrations can only stay narrow and parallelizable if the foundation plan stops at shared runtime, shared settings, and synthetic proof.
  Date/Author: 2026-03-17 / Codex

- Decision: synthetic tests are mandatory before any real phase migration starts.
  Rationale: the later phase plans should be debugging phase logic, not discovering whether the base runtime can write manifests or preserve environment handling.
  Date/Author: 2026-03-17 / Codex

- Decision: the runtime should own workspace materialization and result collection, while each phase provides its own shard planner, validation rules, and promotion hooks.
  Rationale: that is the cleanest split between shared infrastructure and phase-specific policy.
  Date/Author: 2026-03-17 / Codex

- Decision: keep `run_settings_adapters.py` unchanged for the new worker/shard/turn knobs during the foundation milestone.
  Rationale: the current stage and benchmark command surfaces do not consume those knobs yet, and forwarding unused kwargs now would create fake integration instead of a stable substrate. The later phase cutover plans should wire them where they become live inputs.
  Date/Author: 2026-03-17 / Codex

- Decision: normalize old recipe/knowledge/line-role pipeline ids centrally now, but leave the broader wording/export cleanup to the later observability/removal plan.
  Rationale: that freezes the shared ids and unblocks later phase work without forcing a large cross-cutting copy/export rewrite before the runtime exists.
  Date/Author: 2026-03-17 / Codex

## Outcomes & Retrospective

The foundation milestone is complete. The repo now has a shared `phase_worker_runtime.py` module, a runner audit path that can mark bounded-worker execution as `structured_loop_agentic_v1`, shard-v1 pipeline ids plus worker/shard/turn knobs in `RunSettings`, and focused tests that prove manifest writing, worker assignment, sandbox routing, proposal validation, and runner-owned Codex-home behavior.

The intentionally deferred work is the real phase cutover and the broad observability/export wording cleanup. The line-role, recipe, and knowledge child plans can now treat the runtime contracts as frozen inputs instead of re-specifying them.

## Context and Orientation

RecipeImport already has three Codex-backed seams, but each seam currently behaves as one or more one-shot structured-output calls. The shared transport seam is `cookimport/llm/codex_farm_runner.py`. The new foundation layer should sit directly above that runner and directly below the phase-specific orchestrators. The likely home for this layer is `cookimport/llm/phase_worker_runtime.py`.

A shard is a bounded ownership unit with explicit owned IDs and a strict output contract. A worker is one bounded Codex execution context that can process multiple shards in sequence during one phase. The runtime foundation must therefore model both concepts explicitly. It also needs to keep runtime artifacts separate from promoted stage artifacts so downstream systems continue to treat staged outputs as authoritative.

The main files for this plan are:

- `cookimport/llm/phase_worker_runtime.py` as the new runtime module
- `cookimport/llm/codex_farm_runner.py` for runner-mode and environment handling
- `cookimport/config/run_settings.py` and `cookimport/config/run_settings_adapters.py` for shared knobs and legacy-id normalization
- `cookimport/cli.py` and `cookimport/cf_debug_cli.py` only where shared settings or routing must be exposed before later plans
- `tests/llm/test_phase_worker_runtime.py` and nearby transport tests for synthetic validation

This plan depends only on the current codebase and the design intent captured in the original archival plan and `docs/reports/1 - refactor-shard-agents.md`. It does not depend on any of the later child plans being implemented first.

## Milestones

### Milestone 1: Define the shared runtime types and artifact model

Create `cookimport/llm/phase_worker_runtime.py` and define the stable manifest and runtime types the later plans will use. At minimum this means a phase manifest, shard manifest entry, worker assignment, shard proposal, and worker execution report. Also define the runtime artifact layout: `phase_manifest.json`, `shard_manifest.jsonl`, `worker_assignments.json`, `promotion_report.json`, `telemetry.json`, `failures.json`, per-worker logs, and per-shard proposed outputs.

Acceptance for this milestone is a unit test that can instantiate these types, write the expected artifacts to a temporary run root, and read them back in a predictable way.

### Milestone 2: Add worker execution orchestration on top of the existing runner

Extend the runtime so it can assign multiple shards to a worker, materialize a phase-local sandbox, invoke the existing Codex runner, collect structured proposed outputs, and return deterministic execution reports. In `cookimport/llm/codex_farm_runner.py`, add a distinct runtime audit mode that proves the new bounded-worker flow is active instead of the old one-shot structured-output path.

Acceptance for this milestone is a synthetic test with a fake worker backend that shows multiple shards assigned to one worker, one worker workspace created, a runner audit mode of `structured_loop_agentic_v1` or equivalent, and proposals collected without mutating authoritative outputs.

### Milestone 3: Wire shared settings and prove environment handling

Add or normalize the shared shard-runtime settings in `cookimport/config/run_settings.py` and related adapters. These include the shard-v1 pipeline ids and worker/shard/turn knobs that later plans will use. Legacy ids may still parse temporarily, but they must normalize immediately to the shard-v1 ids. The runtime tests also need to prove that `CODEX_HOME` and `CODEX_FARM_CODEX_HOME_RECIPE` handling still lives at the runner layer and that explicit env overrides still win.

Acceptance for this milestone is a focused test suite that passes while exercising settings parsing, legacy normalization, runner-owned Codex-home injection, and phase-local sandbox rules.

## Plan of Work

Begin by creating `cookimport/llm/phase_worker_runtime.py` with plain dataclass-based runtime structures and a narrow orchestration entrypoint such as `run_phase_workers_v1(...)`. Do not put phase-specific shard planning logic in this module. Instead, accept callbacks or strategy objects for shard planning, proposal validation, promotion, and telemetry enrichment so the later phase plans can plug in their own rules.

Once the runtime types exist, update `cookimport/llm/codex_farm_runner.py` to add a distinct audit mode for the bounded-worker path and to expose any helper seams the runtime needs. Preserve the existing environment merge logic so the dedicated RecipeImport Codex home is still applied in one place.

Then update `cookimport/config/run_settings.py` so the shared worker knobs exist once, with exact names the later phase plans can rely on. Keep the wiring additive and explicit. Temporary migration compatibility for legacy pipeline ids is acceptable only if the code normalizes them immediately to the shard-v1 ids and records that normalization in runtime metadata or logs. Do not force `run_settings_adapters.py` to pass these knobs through until a later phase plan actually consumes them.

Finish with synthetic tests first. Add `tests/llm/test_phase_worker_runtime.py` and extend existing transport tests as needed. Use fake worker execution or a stubbed runner so the test proves manifests, assignments, sandbox shaping, proposal collection, validation hooks, and environment handling without needing real Codex execution.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport` and use the project-local virtual environment:

    source .venv/bin/activate
    pip install -e .[dev]

Read the key context:

    sed -n '1,260p' docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md
    sed -n '1,220p' docs/reports/1\ -\ refactor-shard-agents.md
    sed -n '1,220p' cookimport/llm/RECIPE_CODEX_HOME.md

Implement the shared runtime and run focused tests:

    source .venv/bin/activate
    pytest tests/llm/test_codex_farm_orchestrator_runner_transport.py tests/llm/test_phase_worker_runtime.py tests/llm/test_run_settings.py -q

Sanity-check the directly impacted pre-cutover seams:

    source .venv/bin/activate
    pytest tests/llm/test_codex_farm_orchestrator.py tests/llm/test_codex_farm_knowledge_orchestrator.py tests/parsing/test_canonical_line_roles.py -q

The expected outcome is passing tests that demonstrate:

    - phase manifests and shard manifests are written
    - one worker can own multiple shards
    - proposals are collected separately from promoted outputs
    - the runner reports a bounded-worker audit mode
    - the dedicated RecipeImport Codex home still applies by default

## Validation and Acceptance

This plan is accepted when a newcomer can run the focused runtime tests and observe all of the following without touching any real phase cutover:

- a shared runtime module exists
- runtime artifacts are written under a predictable schema
- worker assignments can span multiple shards
- the runner can distinguish the new runtime from the old one-shot mode
- the runtime uses phase-local sandboxes rather than the repo root
- environment handling still preserves the dedicated RecipeImport Codex home by default

The later phase plans should be able to consume this foundation without editing its interfaces for basic runtime behavior.

## Idempotence and Recovery

All work in this plan should be additive and testable. The synthetic runtime tests should be safe to rerun, and the runtime artifact-writing helpers should be deterministic under stable input order. If the runtime interface proves too broad or phase-specific, narrow it here before any later child plan depends on it. Do not hide unresolved design churn behind compatibility layers in the phase plans.

## Artifacts and Notes

The most important outputs of this plan are shared contracts, not user-facing artifacts. The new runtime should standardize these names and shapes:

- `phase_manifest.json`
- `shard_manifest.jsonl`
- `worker_assignments.json`
- `promotion_report.json`
- `telemetry.json`
- `failures.json`
- per-worker logs and status files
- per-shard proposed outputs

These runtime artifacts must remain separate from promoted stage artifacts.

## Interfaces and Dependencies

At the end of this plan, the following interfaces must exist and be stable enough for later plans to use:

In `cookimport/config/run_settings.py`:

    llm_recipe_pipeline: Literal["off", "codex-recipe-shard-v1"]
    llm_knowledge_pipeline: Literal["off", "codex-knowledge-shard-v1"]
    line_role_pipeline: Literal["off", "deterministic-v1", "codex-line-role-shard-v1"]
    recipe_worker_count: int | None
    recipe_shard_target_recipes: int | None
    recipe_shard_max_turns: int | None
    knowledge_worker_count: int | None
    knowledge_shard_target_chunks: int | None
    knowledge_shard_max_turns: int | None
    line_role_worker_count: int | None
    line_role_shard_target_lines: int | None
    line_role_shard_max_turns: int | None

In `cookimport/llm/phase_worker_runtime.py`:

    @dataclass(frozen=True)
    class PhaseManifestV1: ...

    @dataclass(frozen=True)
    class ShardManifestEntryV1: ...

    @dataclass(frozen=True)
    class WorkerAssignmentV1: ...

    @dataclass(frozen=True)
    class ShardProposalV1: ...

    @dataclass
    class WorkerExecutionReportV1: ...

    def run_phase_workers_v1(...) -> tuple[PhaseManifestV1, list[WorkerExecutionReportV1]]

In `cookimport/llm/codex_farm_runner.py`, the audit payload for the new path must distinguish the bounded-worker runtime from the old one-shot runtime, for example with:

    {
      "mode": "structured_loop_agentic_v1",
      "status": "ok",
      ...
    }

Revision note: this plan was created by splitting the original shard-runtime ExecPlan into smaller implementation plans. It owns only the shared runtime and config foundation so later phase plans can stay narrow.

Revision note (2026-03-17_12.18.01): updated this plan after implementation to mark the foundation milestone complete, record the central pipeline-id normalization discovery, and note that the new worker/shard/turn knobs are frozen in `RunSettings` but not yet forwarded through stage/benchmark adapters until a real phase cutover consumes them.
