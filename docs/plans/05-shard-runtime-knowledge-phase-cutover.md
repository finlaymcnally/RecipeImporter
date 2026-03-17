---
summary: "ExecPlan for migrating `extract_knowledge_optional` from compact Codex bundles to the shared shard-worker runtime under `codex-knowledge-shard-v1`."
read_when:
  - "When replacing knowledge extraction execution with shard workers."
  - "When implementing bounded non-recipe knowledge shards over deterministic eligibility and pruning."
  - "When one contributor is assigned only the knowledge slice of the shard-runtime refactor."
---

# Migrate Knowledge Refinement To Shard Workers

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, `extract_knowledge_optional` will stop executing as many compact one-shot Codex bundles and will instead run as bounded workers over explicit knowledge shards under `codex-knowledge-shard-v1`. Deterministic classification and pruning remain in charge of deciding which non-recipe regions are eligible. The worker phase only refines those bounded eligible shards and returns proposed knowledge outputs for deterministic promotion.

The visible behavior after this plan is complete is that knowledge remains optional, stage-backed, and downstream of authoritative labels and non-recipe classification. What changes is the execution model, the replay boundary, and the runtime artifacts beneath that same product contract.

## Progress

- [x] (2026-03-17_11.55.04) Derived this child plan from the original shard-runtime ExecPlan while keeping the original untouched.
- [ ] Confirm that the foundation plan has landed or that its runtime interfaces are frozen.
- [ ] Replace the current bundle-execution path in `cookimport/llm/codex_farm_knowledge_orchestrator.py` and related knowledge job modules with shard planning and shared-runtime execution.
- [ ] Preserve deterministic non-recipe eligibility, pruning, and exclusion of obvious noise.
- [ ] Enforce exact-once ownership for eligible chunk or span IDs and reject off-surface edits.
- [ ] Add focused tests for knowledge shard planning, promotion, and failure fallback behavior.

## Surprises & Discoveries

- Observation: knowledge work must remain bounded by deterministic eligibility instead of drifting back into whole-book mining.
  Evidence: the original shard-runtime plan explicitly keeps `classify_nonrecipe` authoritative and limits the phase to already-eligible knowledge spans or chunks.

- Observation: this phase is especially sensitive to obvious-noise suppression because execution reuse could otherwise make it cheaper to process junk, not smarter to avoid it.
  Evidence: the original plan calls out hard deterministic exclusion of navigation, legal boilerplate, endorsements, marketing copy, signup prompts, and similar noise.

## Decision Log

- Decision: this plan keeps knowledge as a label-driven optional refinement phase rather than a new independent mining pipeline.
  Rationale: the product architecture remains stage-backed and label-first, and the refactor is about runtime shape, not a new knowledge product.
  Date/Author: 2026-03-17 / Codex

- Decision: knowledge shards should follow deterministic non-recipe region grouping and pruning rather than arbitrary packing.
  Rationale: the deterministic side already knows which spans are eligible and which are obvious noise, so the runtime should reuse that authority instead of replacing it.
  Date/Author: 2026-03-17 / Codex

- Decision: if the worker phase fails, deterministic classification artifacts must remain intact and usable.
  Rationale: knowledge is optional, and failure recovery should degrade gracefully without corrupting stage-backed authority.
  Date/Author: 2026-03-17 / Codex

## Outcomes & Retrospective

Implementation has not started yet. The expected outcome is a knowledge phase that still respects deterministic ownership and noise exclusion while replacing one-shot bundle execution with replayable worker/shard boundaries. The final retrospective should record whether contiguous non-recipe regions or grouped region clusters gave the cleanest ownership without regressing quality.

## Context and Orientation

The knowledge cutover sits after deterministic classification. Upstream, `classify_nonrecipe` isolates non-recipe regions, separates likely `knowledge` from obvious `other`, and suppresses obvious noise. Downstream, promoted knowledge artifacts must remain compatible with the current stage-backed reviewer and writer surfaces. This plan changes only the Codex-backed refinement step in `cookimport/llm/codex_farm_knowledge_orchestrator.py` and its related job-planning and ingest modules.

This plan assumes the shared runtime from `cookimport/llm/phase_worker_runtime.py` already exists and that the knowledge worker knobs and pipeline-id routing exist in `cookimport/config/run_settings.py`. If those interfaces are unstable, complete the foundation plan first.

For this phase, a shard is a bounded eligible non-recipe region or group of nearby eligible regions with explicit owned chunk or span IDs, evidence references, deterministic metadata, and a strict output contract. A worker is one bounded knowledge-refinement session that may process multiple such shards in sequence.

The main files for this plan are:

- `cookimport/llm/codex_farm_knowledge_orchestrator.py`
- `cookimport/llm/codex_farm_knowledge_jobs.py`
- related knowledge output ingest or schema modules as needed
- `tests/llm/test_knowledge_job_bundles.py`
- `tests/llm/test_knowledge_output_ingest.py`
- `tests/llm/test_codex_farm_knowledge_orchestrator.py`
- `tests/llm/test_knowledge_phase_workers.py`

## Milestones

### Milestone 1: Replace one-shot knowledge bundles with explicit knowledge shards

Refactor the deterministic job-planning layer so it produces explicit knowledge shards instead of one-shot Codex bundle requests. Preserve current pruning, local grouping, and deterministic exclusion rules, but reinterpret them as shard planning inputs. Each shard should declare owned eligible IDs, evidence refs, deterministic warnings, and payload metrics for worker assignment.

Acceptance for this milestone is a focused test that proves all eligible knowledge IDs are covered exactly once, obvious noise remains excluded, and one worker can own multiple knowledge shards.

### Milestone 2: Validate proposed knowledge outputs and preserve optional-phase fallback behavior

Use the shared runtime to collect proposed knowledge outputs for each owned eligible ID. Validation must reject schema-invalid outputs, ownership violations, and edits outside the eligible knowledge surface. Promotion must write the existing stage-backed knowledge artifacts, and failure handling must leave deterministic classification artifacts intact when knowledge refinement does not complete cleanly.

Acceptance for this milestone is a test that shows valid outputs are promoted, invalid off-surface outputs are rejected, and failure falls back cleanly to the deterministic stage-backed knowledge-prep artifacts.

### Milestone 3: Prove runtime legibility and reviewer-snippet continuity

Add focused tests or assertions that show runtime artifacts clearly represent worker/shard execution and reviewer-facing snippet evidence remains compatible with the current downstream contract. This plan does not own final prompt-export or upload-bundle rendering, but it must emit stable runtime telemetry and prompt/debug references for the later observability plan.

Acceptance for this milestone is passing focused tests plus runtime artifacts showing bounded workers over explicit knowledge shards while preserving stage-backed reviewer evidence.

## Plan of Work

Begin in `cookimport/llm/codex_farm_knowledge_jobs.py` and related planning code by replacing one-shot bundle planning with explicit shard planning. Keep deterministic eligibility, local grouping, and noise suppression as the authority layer. The new planner should package only already-eligible knowledge regions into replayable ownership units.

Next, wire the knowledge planner into the shared runtime from `cookimport/llm/phase_worker_runtime.py`. Provide phase-specific validation that enforces exact ownership and surface bounds, and a promotion step that writes the existing knowledge stage artifacts. Preserve the current reviewer-facing snippet compatibility and fallback behavior when the optional phase fails.

Then add tests across the job planner, orchestrator, output ingest, and phase-worker seams. The tests should prove exact-once eligible-ID coverage, exclusion of obvious noise, promotion of valid outputs, rejection of off-surface edits, and graceful fallback behavior.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport` and activate the local virtual environment:

    source .venv/bin/activate
    pip install -e .[dev]

Read the relevant context:

    sed -n '1,260p' docs/plans/02-shard-runtime-foundation-runtime-and-config.md
    sed -n '1,260p' cookimport/llm/codex_farm_knowledge_orchestrator.py
    sed -n '1,260p' cookimport/llm/codex_farm_knowledge_jobs.py

Implement the cutover and run focused tests:

    source .venv/bin/activate
    pytest tests/llm/test_knowledge_job_bundles.py tests/llm/test_knowledge_output_ingest.py tests/llm/test_codex_farm_knowledge_orchestrator.py tests/llm/test_knowledge_phase_workers.py tests/llm/test_prompt_preview.py -q

The expected outcome is passing tests that demonstrate:

    - eligible knowledge IDs are covered exactly once
    - obvious noise stays excluded deterministically
    - one worker may process multiple knowledge shards
    - off-surface edits are rejected
    - valid outputs promote cleanly while optional-phase failure falls back safely

## Validation and Acceptance

This plan is accepted when a contributor can run the focused tests and observe that knowledge remains optional, label-driven, and stage-backed, while the runtime artifacts now show bounded workers over explicit eligible knowledge shards.

Acceptance does not require the final prompt-preview, prompt-export, or upload-bundle cutover yet, but it does require stable runtime telemetry and artifact writing so the observability/removal plan can consume them later.

## Idempotence and Recovery

Knowledge shard IDs should derive from stable eligible-region ordering so replay stays legible. If a worker fails, completed shard proposals should remain inspectable and retryable without rerunning unrelated regions. Because knowledge is optional, the failure path must preserve deterministic classification artifacts and must not leave downstream consumers dependent on half-promoted worker outputs.

## Artifacts and Notes

This plan should preserve the authoritative promoted knowledge artifacts while adding inspectable runtime artifacts for knowledge shards and workers. The most important proof points are:

- stable eligible knowledge shard ownership
- deterministic exclusion of obvious noise
- worker assignments spanning multiple knowledge shards
- validated proposed knowledge outputs
- safe fallback when the optional phase fails

## Interfaces and Dependencies

This plan depends on the shared interfaces from the foundation plan and should consume at least:

- `llm_knowledge_pipeline: Literal["off", "codex-knowledge-shard-v1"]`
- `knowledge_worker_count: int | None`
- `knowledge_shard_target_chunks: int | None`
- `knowledge_shard_max_turns: int | None`
- `run_phase_workers_v1(...)` from `cookimport/llm/phase_worker_runtime.py`

At the end of this plan, `cookimport/llm/codex_farm_knowledge_orchestrator.py` and related knowledge job modules must route optional knowledge refinement through `codex-knowledge-shard-v1` and still promote one valid result per owned eligible ID into the existing stage-backed contract.

Revision note: this plan was created by splitting the original shard-runtime ExecPlan into a narrower knowledge implementation plan that can run independently after the shared runtime foundation is stable.
