# Exec Plan: Refactor Codex Import Processing Around Bounded Phase Workers

## Purpose

Refactor the Codex-backed execution model so the importer keeps its current label-first staged architecture, but stops paying the fixed cost of a fresh Codex session for every small unit of work.

The target design is:

* deterministic-first
* manifest-driven
* phase-scoped
* replayable
* cheaper on real books
* observable at the worker and shard level

This is **not** a wholesale rewrite of the repo’s data model or authority boundaries. The current stage-backed architecture remains in place. The refactor is primarily about **how Codex work is executed and promoted**, not about replacing the existing staged pipeline with a new one.

---

## Non-Negotiable Constraints

1. Preserve the current label-first authority model.

   * Label-first staging remains the source of truth for recipe vs non-recipe ownership.
   * `group_recipe_spans` remains downstream of labels.
   * If authoritative regrouping yields zero recipes, preserve the current authority-mismatch behavior rather than falling back to importer-owned recipe candidates.

2. Preserve the current deterministic stage boundaries.

   * Deterministic stages stay deterministic.
   * Codex-backed stages remain optional correction/refinement stages.
   * Final promotion remains deterministic and schema-validated.

3. Do not invent a second architecture for downstream tools.

   * Label Studio, benchmark, analytics, and downstream review flows must continue to consume staged artifacts.
   * Do not create a parallel Codex-only artifact model.

4. Do not treat “shard” and “agent session” as the same thing.

   * A **shard** is an ownership and validation unit.
   * A **worker** is a Codex execution context.
   * One worker may process multiple shards in one bounded phase session.

5. Prefer proposed outputs over in-place edits.

   * Codex workers write structured proposed outputs.
   * Deterministic code validates and promotes them.
   * Authoritative artifacts are never mutated directly by a worker.

6. Keep workspaces isolated and phase-local.

   * Each worker gets its own sandbox and local `.codex` state.
   * Each phase starts with a clean workspace.
   * Do not expose unrelated repo files or broad project instructions to workers.

---

## Current Pipeline to Preserve

Keep the current semantic stage model and stage names.

1. `label_det`
2. `label_llm_correct`
3. `group_recipe_spans`
4. `build_intermediate_det`
5. `recipe_llm_correct_and_link`
6. `build_final_recipe`
7. `classify_nonrecipe`
8. `extract_knowledge_optional`
9. `write_outputs`

Within that stage model:

* `label_det`, `group_recipe_spans`, `build_intermediate_det`, `build_final_recipe`, `classify_nonrecipe`, and `write_outputs` stay deterministic.
* `label_llm_correct`, `recipe_llm_correct_and_link`, and `extract_knowledge_optional` are the main Codex-backed phase-worker stages.
* Inline recipe tagging continues to ride on the recipe-correction contract; do not reintroduce a separate tagging subsystem.
* Freeform Label Studio and benchmark flows continue to trust staged artifacts, not a separate agent-only path.

---

## Target Runtime Model

### Definitions

#### Phase

A single Codex-backed stage family for one run/workbook, such as:

* `label_llm_correct`
* `recipe_llm_correct_and_link`
* `extract_knowledge_optional`

#### Shard

A bounded logical work unit used for ownership, validation, replay, and observability.

Examples:

* a local contiguous label window
* a nearby-recipe batch
* a contiguous knowledge region

A shard must have:

* a stable `shard_id`
* explicit owned IDs
* explicit evidence references
* a strict output contract
* exact coverage rules

#### Worker

A bounded Codex execution context dedicated to one phase.

A worker:

* is initialized once per phase session
* receives persistent instructions for that phase
* processes one or more assigned shards in sequence
* writes proposed outputs for each shard
* never edits authoritative artifacts in place

### Core Runtime Rule

Use **bounded phase workers over multiple shards**, not one fresh Codex execution per recipe, per label bundle, or per knowledge chunk.

The design goal is:

* fewer fresh Codex sessions
* more reuse of phase instructions
* explicit shard ownership
* deterministic promotion after validation

### Expected Operating Shape

Per book, the runtime should generally operate in three major Codex phases:

1. labeling correction
2. recipe correction/linkage
3. optional knowledge refinement

For each phase, start with a small bounded worker pool, typically in the range of **2–6 workers per phase**, then tune empirically.

The critical metric is not just `shard_count`. The system must report both:

* `shard_count`
* `fresh_agent_count`

Those values should not be assumed equal.

---

## Phase Worker Harness

Implement a shared runtime used by all Codex-backed stages.

### Responsibilities

1. Build a phase manifest from deterministic upstream artifacts.
2. Partition phase work into bounded shards.
3. Assign shards to a bounded number of workers.
4. Materialize per-worker sandboxes.
5. Start a worker with phase-specific instructions.
6. Let the worker loop through its assigned shards.
7. Collect structured proposals.
8. Validate proposals deterministically.
9. Promote only valid outputs into the authoritative stage artifacts.
10. Persist telemetry, manifests, and promotion reports.
11. Tear down the sandbox after the phase completes.

### Required Runtime Properties

* manifest-driven
* strict I/O schemas
* exact shard ownership
* deterministic promotion
* replay by shard or worker
* bounded worker lifetime
* no cross-phase workspace reuse

### Required Runtime Artifacts

For each Codex-backed phase, persist runtime artifacts under the existing raw/stage output model.

At minimum, write:

* `phase_manifest.json`
* `shard_manifest.jsonl`
* `worker_assignments.json`
* `promotion_report.json`
* `telemetry.json`
* `failures.json`
* per-worker logs/status files
* per-shard proposed outputs

Keep these runtime artifacts separate from promoted stage artifacts.

---

## Workspace Isolation

### Required Behavior

Each worker must run inside a task-local sandbox that contains only:

* the worker instructions for that phase
* the shard assignment manifest
* the evidence files needed for those shards
* schema definitions and output contracts
* minimal helper code or adapters required for the worker to write outputs
* a local `.codex` directory for that worker only

### Explicit Isolation Rules

* Do not run workers from the repo root.
* Do not expose unrelated code, docs, or agent instruction files.
* Do not allow one phase workspace to persist into the next phase.
* After outputs are collected and promoted, wipe the phase workspace contents.
* Persist only logs, manifests, telemetry, and proposed outputs outside the sandbox.

This isolation is mandatory. The workers should only see files relevant to the task in front of them.

---

## Proposed Output Model

Workers write **proposed outputs**, not in-place edits.

For every shard, the worker should write a structured result bundle that includes:

* shard metadata
* owned IDs
* proposed outputs for those IDs
* issue flags / ambiguity flags
* completion status
* any validator-relevant notes

Promotion rules:

* deterministic code validates the proposal
* schema-invalid proposals are rejected
* ownership violations are rejected
* referential integrity violations are rejected
* only promoted outputs become authoritative stage artifacts

This preserves rollback, replay, and partial recovery.

---

## Stage-by-Stage Refactor

---

## Stage A — `label_det` Stays Deterministic

### Goal

Keep the current deterministic label build intact.

### Requirements

* Do not move label ownership into Codex.
* Keep deterministic labels, uncertainty markers, reason tags, and structural hints as the first-pass artifact.
* Continue using the current label-first staging entrypoint and artifact model.

### Refactor Impact

Only add the metadata needed to plan the optional correction phase cleanly.

That includes:

* explicit uncertainty markers
* parser/rule warnings
* neighborhood hints
* stable block/row ownership metadata for downstream shard planning

---

## Stage B — Refactor `label_llm_correct` Into a Phase-Worker Stage

### Goal

Replace prompt-per-bundle or overly granular label correction calls with a bounded label-correction phase runtime.

### Shard Design

Label shards should be:

* contiguous local windows
* non-overlapping in owned rows/blocks
* sized for local review, not whole-book reinterpretation

A label shard is the ownership unit.
A label worker may process multiple label shards in one session.

### Worker Input

For each assigned shard, provide:

* the owned rows/blocks
* a bounded neighborhood view
* deterministic labels
* uncertainty markers
* structural hints
* any parser/rule warnings
* a strict output schema

### Worker Output

For every owned row/block, return:

* one final label
* optional confidence / ambiguity flag
* optional change note

### Validation Rules

* every owned row/block gets exactly one final label
* no worker may edit rows/blocks outside its owned IDs
* deterministic vs corrected diffs must remain inspectable
* final label coverage must be exact-once

### Promotion

Promote valid worker outputs into the existing `label_llm_correct` artifact structure so downstream stages remain unchanged.

### Explicit Non-Goal

Do not let label workers rediscover the whole book from scratch.
They are correcting deterministic labels inside bounded local ownership windows.

---

## Stage C — Keep `group_recipe_spans` Deterministic and Authoritative

### Goal

Preserve the current deterministic grouping model.

### Requirements

* Group from final corrected labels.
* Do not reintroduce recipe-candidate-first architecture.
* Preserve current authority behavior when regrouping disagrees with importer candidates.
* Keep grouping warnings explicit and persisted.

### Refactor Impact

No new Codex runtime belongs here by default.
This stage should remain deterministic.

---

## Stage D — Keep `build_intermediate_det` Deterministic

### Goal

Preserve the current deterministic intermediate recipe build as the main debug artifact.

### Requirements

* Continue building intermediate recipe objects from grouped labeled spans.
* Preserve provenance back to source block IDs.
* Preserve parser warnings and structural issues.

### Refactor Impact

Only add the metadata needed for efficient recipe-phase worker handoff.

That includes:

* stable `recipe_id`
* recipe-local warnings/ambiguities
* evidence references for original labeled blocks
* deterministic schema versioning for promotion and replay

---

## Stage E — Refactor `recipe_llm_correct_and_link` Into a Phase-Worker Stage

### Goal

Replace per-recipe fresh Codex executions with a bounded recipe phase in which each worker processes multiple recipe shards under one instruction context.

### Core Rule

Keep the existing conceptual contract:

For each owned `recipe_id`, the worker returns:

1. a corrected intermediate recipe object
2. a linkage payload for deterministic final assembly
3. issue/ambiguity flags

### Shard Design

Recipe shards should be:

* local in recipe order
* bounded in recipe count and payload size
* conservative enough to limit drift
* stable and replayable

A recipe shard is the ownership unit.
A recipe worker may process multiple recipe shards in sequence.

### Worker Input

For each assigned shard, provide:

* original labeled blocks for each owned recipe
* grouped recipe span metadata
* deterministic intermediate recipe objects
* parser warnings / ambiguity signals
* provenance references
* schema and output contract

### Worker Output

For every owned `recipe_id`, write:

* corrected intermediate recipe object
* linkage payload
* issue flags
* completion status

### Validation Rules

* every owned `recipe_id` is returned exactly once
* corrected objects are schema-valid
* linkage payloads only reference valid owned recipe structures
* provenance remains intact
* no edits outside owned `recipe_id`s

### Promotion

Promote valid outputs into the existing recipe-correction stage artifacts.
`build_final_recipe` must continue to consume promoted corrected structure plus linkage payloads.

### Explicit Non-Goals

* Do not make one fresh agent the default for every recipe.
* Do not add a second heavy model call for final reshaping when deterministic assembly already exists.
* Do not collapse deterministic and probabilistic responsibilities into one opaque recipe step.

---

## Stage F — Keep `build_final_recipe` Deterministic

### Goal

Preserve deterministic final recipe assembly.

### Requirements

* consume promoted corrected intermediate objects
* consume promoted linkage payloads
* attach ingredients to steps deterministically
* preserve unresolved ambiguities explicitly
* avoid inventing structure the correction stage did not supply

### Refactor Impact

No new Codex runtime belongs here.
This stage remains a deterministic writer/assembler.

---

## Stage G — Keep `classify_nonrecipe` Deterministic and Authoritative

### Goal

Preserve the current deterministic non-recipe ownership boundary.

### Requirements

* `knowledge` vs `other` stays stage-backed and machine-readable
* reviewer-facing snippets remain downstream evidence, not the ownership source of truth
* noise filtering should continue to rely on strong early classification

### Refactor Impact

Only add the metadata needed to plan optional knowledge-phase worker batches cleanly.

---

## Stage H — Refactor `extract_knowledge_optional` Into a Phase-Worker Stage

### Goal

Refactor optional knowledge processing into a bounded label-driven phase instead of broad whole-book mining.

### Eligibility Rule

Only spans already classified as `knowledge` are eligible for this phase.

### Shard Design

Knowledge shards should be:

* contiguous outside-recipe regions or region groups
* bounded in size
* replayable
* explicit in owned IDs

A knowledge shard is the ownership unit.
A knowledge worker may process multiple knowledge shards in one session.

### Worker Input

For each assigned shard, provide:

* the knowledge-classified spans/chunks
* supporting evidence references
* any deterministic metadata or warnings
* the expected output schema

### Worker Output

For every owned span/chunk, return:

* proposed knowledge output
* evidence snippets or evidence references compatible with downstream review artifacts
* issue flags
* completion status

### Hard Rules

Do not run knowledge refinement over obvious noise such as:

* table of contents
* navigation
* legal boilerplate
* front matter
* endorsements
* publisher marketing copy
* signup prompts

### Promotion

Promote only schema-valid, ownership-valid outputs.
If the phase fails, keep deterministic classification artifacts intact.

---

## Manifest and Schema Requirements

Every Codex-backed phase must be manifest-driven.

### Phase Manifest

The phase manifest must declare:

* run ID
* workbook slug
* phase name
* schema version
* input artifact references
* output artifact targets
* worker count
* shard planning parameters
* promotion policy

### Shard Manifest

Each shard entry must declare:

* `shard_id`
* phase name
* owned IDs
* evidence references
* payload size metrics
* retry count
* validator expectations
* output path targets

### Worker Assignment Manifest

Each worker assignment must declare:

* `worker_id`
* assigned `shard_id`s
* workspace root
* instruction bundle version
* lifecycle status

These manifests are required for replay, recovery, and observability.

---

## Observability and Preview

Replace prompt-count-centric reporting with worker- and shard-centric reporting.

### Keep

* existing semantic stage names
* `stage_observability.json`
* run manifests and run summaries
* staged artifact-based benchmark evidence

### Change

Preview, plan mode, and runtime telemetry must report:

* `phase_name`
* `worker_count`
* `fresh_agent_count`
* `shard_count`
* `shards_per_worker`
* shard size distribution
* first-turn payload size distribution
* promotion success/failure counts
* retry counts
* phase wall time
* observed turn counts and token totals when available

### Explicit Rule

Do not use prompt count as a proxy for shard cost or runtime shape.
Report real phase-worker behavior.

---

## Benchmarking and Downstream Compatibility

The refactor must preserve downstream contracts.

### Requirements

* keep stage-backed outputs as the main evidence seam
* keep benchmark and evaluation flows reading staged artifacts
* keep freeform Label Studio flows built on staged artifacts
* do not create a second benchmark or review path tied directly to worker sandboxes

### Allowed Changes

* update preview/reporting language from prompt bundles to worker/shard plans
* add runtime telemetry artifacts used for cost/quality analysis
* add benchmark slices that compare worker counts, shard sizing, and phase cost/quality tradeoffs

---

## Failure and Recovery Policy

### General Rule

Failure should be localized to the phase, worker, or shard that failed.
Do not force a full-book rerun when deterministic upstream artifacts are still valid.

### Required Behavior

If a worker fails mid-phase:

* keep completed shard proposals
* mark incomplete shards explicitly
* allow replay of only failed shards

If a proposal fails validation:

* reject promotion for that shard
* preserve the deterministic upstream artifact
* record the validation failure explicitly

If label correction fails:

* keep deterministic labels
* mark the affected shard unpromoted

If recipe correction fails:

* keep deterministic intermediate objects for affected recipes
* mark those recipes uncorrected
* allow final build to proceed only where valid inputs exist under current policy

If knowledge refinement fails:

* keep deterministic non-recipe classification outputs
* record the failure without corrupting stage ownership

Replayability is a core requirement, not an optional enhancement.

---

## Migration Plan

### Phase 1 — Build the Shared Runtime Without Changing Stage Semantics

Implement the reusable phase-worker harness and workspace isolation model.

Deliverables:

* shared runtime
* manifest schemas
* worker sandbox lifecycle
* proposal/promotion flow
* telemetry and reporting
* feature flags or pipeline selection hooks

Do not change stage authority boundaries in this phase.

### Phase 2 — Cut `label_llm_correct` Over to the New Runtime

Deliverables:

* label shard planner
* label worker instructions
* label proposal schema
* deterministic promotion/validation
* replay support

Keep downstream label consumers unchanged.

### Phase 3 — Cut `recipe_llm_correct_and_link` Over to the New Runtime

Deliverables:

* recipe shard planner
* recipe worker instructions
* corrected intermediate + linkage proposal schema
* deterministic promotion/validation
* replay support

Keep `build_final_recipe` unchanged except for consuming the promoted outputs.

### Phase 4 — Cut `extract_knowledge_optional` Over to the New Runtime

Deliverables:

* knowledge shard planner
* knowledge worker instructions
* proposal schema
* deterministic promotion/validation
* replay support

Keep `classify_nonrecipe` authoritative.

### Phase 5 — Update Preview, Bench, and Telemetry Language

Deliverables:

* worker/shard-aware preview output
* cost/quality telemetry summaries
* reporting that distinguishes `shard_count` from `fresh_agent_count`

### Phase 6 — Remove Old Prompt-Per-Bundle Active Paths

After parity and observability are in place:

* deprecate old per-item/per-bundle Codex execution paths from active use
* keep compatibility shims only where needed for historical reads or controlled fallback

---

## What to Remove or Simplify

Remove from the active architecture:

* treating one shard as one mandatory fresh agent execution
* per-recipe fresh-session correction as the default runtime shape
* prompt-count-centric observability and preview language
* broad whole-book knowledge mining when label-driven knowledge shards suffice
* hidden worker behavior that does not persist inspectable proposals and manifests
* any stage reporting that obscures which worker and shard introduced a change

Do **not** remove:

* the current label-first stage model
* current semantic stage names
* deterministic grouping and assembly stages
* stage-backed downstream artifacts

---

## Acceptance Criteria

The refactor is successful when all of the following are true:

1. The pipeline still follows the current stage-backed, label-first architecture.
2. Codex-backed work runs through bounded phase workers rather than many stateless per-item executions.
3. Shards are explicit ownership units and workers are explicit execution units.
4. One worker can process multiple shards in a single bounded phase session.
5. `fresh_agent_count` is materially lower than `shard_count` on realistic cookbook runs.
6. Workers operate only inside isolated task sandboxes with local `.codex` state.
7. Workers write proposed outputs; deterministic code validates and promotes them.
8. Replay works at least at the failed-shard and failed-worker level.
9. `label_llm_correct`, `recipe_llm_correct_and_link`, and `extract_knowledge_optional` all use the shared runtime.
10. `group_recipe_spans`, `build_intermediate_det`, `build_final_recipe`, and `classify_nonrecipe` remain deterministic and inspectable.
11. Stage observability reports real worker/shard behavior instead of fake prompt proxies.
12. Downstream Label Studio, benchmark, and analytics flows continue to rely on staged artifacts.
13. Any bad output can be traced to the exact phase, worker, shard, and promotion decision that produced it.

---

## Final Instruction to the Coding Agent

Implement this refactor as an **execution-model refactor of the existing staged pipeline**, not as a replacement for the current label-first architecture.

The primary deliverable is a **shared bounded phase-worker runtime** that powers the existing Codex-backed stages while preserving current stage authority, current deterministic boundaries, current staged artifacts, and downstream compatibility.
