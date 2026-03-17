---
summary: "ExecPlan for migrating `label_llm_correct` from prompt batches to the shared shard-worker runtime under `codex-line-role-shard-v1`."
read_when:
  - "When replacing line-role Codex execution with shard workers."
  - "When implementing label shards, ownership validation, and promotion for `label_llm_correct`."
  - "When one contributor is assigned only the line-role slice of the shard-runtime refactor."
---

# Migrate Line-Role Correction To Shard Workers

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, `label_llm_correct` will stop executing as prompt-sized one-shot Codex batches and will instead run through the shared shard-worker runtime under `codex-line-role-shard-v1`. The deterministic label stage remains authoritative for first-pass labeling, but the optional correction phase will now group owned rows into explicit local shards and let one worker process multiple shards in sequence.

The visible behavior after this plan is complete is that line-role correction still produces one final corrected label per owned row and still feeds the existing downstream scorer and stage outputs, but the runtime artifacts will now show shard ownership and worker reuse instead of one fresh Codex execution per batch.

## Progress

- [x] (2026-03-17_11.55.02) Derived this child plan from the original shard-runtime ExecPlan while keeping the original untouched.
- [ ] Confirm that the foundation plan has landed or that its runtime interfaces are frozen.
- [ ] Replace the current prompt-batch execution path in `cookimport/parsing/canonical_line_roles.py` with shard planning and shared-runtime execution.
- [ ] Enforce exact-once row ownership, no edits outside owned rows, and inspectable diffs between deterministic and corrected labels.
- [ ] Preserve the existing `label_llm_correct` promoted artifact shape so downstream deterministic stages remain unchanged.
- [ ] Add focused tests for label shard planning, worker assignment, promotion, and scorer compatibility.

## Surprises & Discoveries

- Observation: line-role improvement is no longer mostly about wrapper overhead. The remaining cost is in repeated row-contract material and repeated fresh sessions.
  Evidence: the original shard-runtime plan records that line-role wrapper overhead was already near zero on the motivating preview root.

- Observation: line-role is the safest first real phase cutover after the foundation plan because its ownership unit is simpler than recipe and knowledge output structures.
  Evidence: each owned row only needs one final label plus optional ambiguity or change flags, while recipe and knowledge both return richer structured payloads.

## Decision Log

- Decision: this plan owns only the line-role phase and should not absorb preview, benchmark prompt-export, or upload-bundle cutover work beyond what is needed to emit stable runtime telemetry.
  Rationale: those review/debug surfaces are cross-cutting and belong in the final observability/removal plan.
  Date/Author: 2026-03-17 / Codex

- Decision: line-role shards should stay contiguous and local in book order.
  Rationale: line labeling depends heavily on nearby context, and contiguous windows produce cleaner ownership and easier replay than arbitrary packing.
  Date/Author: 2026-03-17 / Codex

- Decision: promotion must continue to write the existing `label_llm_correct` stage outputs rather than inventing a second label-correction artifact family.
  Rationale: downstream deterministic grouping and scoring must stay unchanged.
  Date/Author: 2026-03-17 / Codex

## Outcomes & Retrospective

Implementation has not started yet. The expected outcome is that line-role becomes the first real proof that the shared runtime can preserve stage semantics while changing the execution model. The final retrospective should record whether shard sizing by lines or blocks produced the cleanest local ownership and whether retry behavior stayed legible in practice.

## Context and Orientation

The line-role phase lives primarily in `cookimport/parsing/canonical_line_roles.py`. Upstream, `label_det` still produces deterministic labels, reason tags, uncertainty markers, and structural hints. Downstream, `group_recipe_spans` and the rest of the stage pipeline still consume the promoted corrected label artifact. This plan changes only the optional Codex-backed correction step in between.

This plan assumes the shared runtime from `cookimport/llm/phase_worker_runtime.py` already exists, along with the relevant settings in `cookimport/config/run_settings.py` and the bounded-worker audit mode in `cookimport/llm/codex_farm_runner.py`. If those interfaces are not stable yet, stop and finish the foundation plan first.

For this phase, a shard is a contiguous local review window with explicit owned row IDs or block IDs, a bounded neighborhood view, deterministic labels, uncertainty hints, and a strict output schema. A worker is one bounded line-role correction session that may process multiple such shards in sequence.

The main files for this plan are:

- `cookimport/parsing/canonical_line_roles.py`
- any line-role prompt or schema assets used by that module
- `tests/parsing/test_canonical_line_roles.py`
- `tests/llm/test_label_phase_workers.py`

## Milestones

### Milestone 1: Replace prompt batches with explicit label shards

Refactor `cookimport/parsing/canonical_line_roles.py` so the line-role phase plans explicit shards instead of prompt-sized batches. Each shard should declare owned IDs, neighborhood evidence, deterministic labels, uncertainty markers, structural hints, and any parser or rule warnings needed for local review. One worker may process multiple shards in sequence through the shared runtime.

Acceptance for this milestone is a focused test that proves the planner covers the intended rows exactly once, preserves stable shard IDs under stable inputs, and does not overlap owned rows across shards.

### Milestone 2: Validate and promote corrected labels through the existing stage contract

Use the shared runtime to collect corrected label proposals and validate them deterministically. Validation must enforce exact-once ownership, schema correctness, and no edits outside the shard’s owned rows. Promotion must write back into the existing `label_llm_correct` artifact structure so downstream grouping and scoring stay unchanged.

Acceptance for this milestone is a test that shows corrected labels are promoted into the normal line-role stage outputs and that unauthorized edits outside owned rows are rejected.

### Milestone 3: Prove scorer compatibility and runtime observability

Add focused tests so canonical-text scoring still works against the promoted outputs and the runtime artifacts clearly show shard counts, worker counts, and completed ownership coverage. This plan does not own the final preview/report cutover, but it must emit the telemetry the later observability plan will consume.

Acceptance for this milestone is passing focused tests plus runtime artifacts that make it obvious one worker can process multiple line-role shards.

## Plan of Work

Begin in `cookimport/parsing/canonical_line_roles.py` by finding the current Codex-backed branch for `label_llm_correct` and replacing its prompt-batch planning logic with shard planning. Keep the deterministic prep intact: the new planner should package nearby context and hints, not re-decide which rows exist or which rows are eligible.

Next, wire that planner into the shared runtime. The line-role phase should provide the runtime with shard manifests, a validation function that enforces exact ownership and schema, and a promotion function that writes corrected labels into the existing stage-backed output shape. Keep the runtime-facing payload compact and phase-specific. Do not move prompt-preview or benchmark export logic into this file.

Then add tests. Extend `tests/parsing/test_canonical_line_roles.py` for the deterministic side and add or update `tests/llm/test_label_phase_workers.py` for runtime-facing behavior. The tests should prove exact-once owned-row coverage, no off-shard edits, promotion into the existing artifact contract, and scorer compatibility after the cutover.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport` and activate the local virtual environment:

    source .venv/bin/activate
    pip install -e .[dev]

Read the relevant context:

    sed -n '1,260p' docs/plans/02-shard-runtime-foundation-runtime-and-config.md
    sed -n '1,260p' cookimport/parsing/canonical_line_roles.py

Implement the cutover and run focused tests:

    source .venv/bin/activate
    pytest tests/parsing/test_canonical_line_roles.py tests/llm/test_label_phase_workers.py tests/llm/test_prompt_preview.py -q

The expected outcome is passing tests that demonstrate:

    - contiguous label shards are planned with stable owned rows
    - one worker may process multiple shards
    - corrected labels cover each owned row exactly once
    - invalid off-shard edits are rejected
    - promoted outputs still satisfy the canonical scorer

## Validation and Acceptance

This plan is accepted when a contributor can run the focused tests and observe that line-role correction still produces one corrected result per owned row, the promoted outputs still feed the existing downstream stages, and the runtime artifacts show shard-worker behavior rather than one-shot prompt batches.

Acceptance does not require the final preview or upload-bundle surfaces to be updated yet, but it does require stable runtime telemetry and artifact writing so the observability/removal plan can consume them later.

## Idempotence and Recovery

The shard planner should derive stable shard IDs from stable input order so replay is legible. If a worker fails, the runtime should preserve completed shard proposals and allow retry by shard or worker assignment. If this phase requires changes to the shared runtime interfaces, update the foundation plan in the same pass rather than papering over the mismatch locally.

## Artifacts and Notes

This plan should preserve the existing authoritative promoted label artifacts while adding inspectable runtime artifacts for the line-role phase. The most important proof points are:

- stable label shard ownership
- worker reports showing multiple shard assignments
- validated corrected-label proposals
- promoted `label_llm_correct` outputs compatible with downstream scoring

## Interfaces and Dependencies

This plan depends on the shared interfaces from the foundation plan and should consume at least:

- `line_role_pipeline: Literal["off", "deterministic-v1", "codex-line-role-shard-v1"]`
- `line_role_worker_count: int | None`
- `line_role_shard_target_lines: int | None`
- `line_role_shard_max_turns: int | None`
- `run_phase_workers_v1(...)` from `cookimport/llm/phase_worker_runtime.py`

At the end of this plan, `cookimport/parsing/canonical_line_roles.py` must route the line-role Codex-backed branch through `codex-line-role-shard-v1` and still promote one corrected label result per owned row into the existing stage artifact contract.

Revision note: this plan was created by splitting the original shard-runtime ExecPlan into a narrower line-role implementation plan that can run independently after the shared runtime foundation is stable.
