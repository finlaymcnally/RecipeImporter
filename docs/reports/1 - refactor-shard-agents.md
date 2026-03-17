---
summary: "Refactor spec for moving Codex-backed import work from prompt-per-bundle fan-out to bounded phase workers over explicit shards."
read_when:
  - "When deciding whether the shard refactor changes pipeline stages or only the Codex execution model."
  - "When translating old CodexFarm prompt bundles into phase-local workers and shard-owned outputs."
---

# Refactor Spec: Shard Workers Over the Existing Stage Pipeline

## Purpose

Keep the current label-first staged importer. Change the Codex runtime.

The goal is to stop paying for a fresh Codex session for every recipe, label bundle, or knowledge chunk, while keeping deterministic preparation, deterministic promotion, and stage-backed artifacts as the system of record.

The target shape is:

- same major stage boundaries
- same deterministic ownership of prep, validation, and promotion
- same stage-backed outputs
- fewer fresh Codex sessions
- explicit shard ownership inside each Codex-backed phase

The runtime change is:

**from:** many stateless prompt executions per recipe or bundle

**to:** a small number of bounded phase workers that process multiple explicit shards

## Operating Model

The importer should keep its current high-level flow:

1. deterministic ingestion and segmentation
2. deterministic-first labeling
3. deterministic grouping and intermediate building
4. Codex-backed correction at the main reasoning seams
5. deterministic validation, assembly, and writing

The key runtime concepts are:

### Shard

A shard is an ownership unit.

Examples:

- a contiguous line-label review window
- a bounded multi-recipe correction group
- a bounded outside-recipe knowledge region

Each shard should have:

- a stable `shard_id`
- explicit owned IDs
- explicit evidence references
- a strict output contract
- exact coverage rules

### Worker

A worker is a bounded Codex execution context dedicated to one phase.

One worker may process several shards in sequence during the same phase.

That distinction matters:

- `shard_count` measures review units
- `worker_count` and `fresh_agent_count` measure fresh Codex sessions
- cost, wall time, and drift depend on both

### Phase

The three Codex-backed phases should remain:

- line labeling
- recipe correction and linkage
- optional knowledge refinement

Each phase gets its own worker pool, workspace root, manifests, telemetry, and promotion report.

## Architectural Rules

### Deterministic code stays in charge

Deterministic code should continue to own:

- shard planning
- stable IDs
- first-pass outputs
- validation
- promotion
- final assembly
- artifact writing
- replay and retry boundaries

Workers reason over bounded evidence and return proposals. They do not become the authority layer.

### Label-first authority stays intact

Recipe ownership should continue to flow from authoritative labels.

That means:

- `group_recipe_spans` stays downstream of labels
- recipe grouping remains deterministic
- knowledge work remains downstream of non-recipe ownership
- the refactor does not reopen importer-vs-stage authority boundaries

### Proposed outputs are the default

Workers should write structured proposed outputs rather than editing authoritative artifacts in place.

Promotion into stage outputs should happen only after deterministic validation.

### Sandboxes are phase-local and task-local

Each worker should run inside a clean sandbox that contains only:

- phase instructions
- assigned shard manifests
- task-relevant evidence files
- schema and output contracts
- minimal adapters needed to write outputs
- a local phase-local `.codex` state

After the phase finishes and outputs are promoted, the working folders can be discarded.

## Phase Shape

## Phase 0: Deterministic Prep

Everything before Codex stays deterministic-first:

- ingest source
- preserve native structure when available
- segment into stable rows or blocks
- build first-pass label, recipe, and knowledge candidates
- emit the evidence each later phase needs

This remains the canonical evidence layer for everything downstream.

## Phase 1: Line Labeling Workers

The line-label phase should operate on explicit contiguous shards built from ordered rows or blocks, deterministic labels, uncertainty flags, and structural hints.

Workers should review only their assigned shards, reuse one instruction context across multiple shard jobs, and return corrected labels only for owned rows.

The deterministic side should validate:

- exact-once row ownership
- full coverage
- schema correctness
- diffability between deterministic and corrected labels

Once validated, corrected labels are promoted into the authoritative stage outputs.

## Phase 2: Recipe Workers

After labeling is promoted, the deterministic side should:

- group recipe spans
- build intermediate recipe objects
- package bounded multi-recipe shards

Recipe workers should process several nearby recipe shards under one instruction context, not one fresh session per recipe.

For each owned `recipe_id`, the worker should return:

- a corrected intermediate recipe object
- linkage or pairing data needed for final assembly
- issue flags where confidence is limited

The intermediate object should remain the main debug artifact. Final recipe assembly should remain deterministic where possible, built from corrected structure plus linkage data rather than another heavy reasoning pass.

## Phase 3: Knowledge Workers

Knowledge work should remain downstream of authoritative labeling and recipe grouping.

The deterministic side should:

- isolate non-recipe regions
- separate likely `knowledge` from obvious `other`
- suppress obvious noise
- package bounded outside-recipe shards

Knowledge workers should process only those bounded shards and return one normalized result per owned `chunk_id` or span, plus evidence suitable for review.

The system should not treat knowledge as a separate whole-book mining architecture.

## Runtime Harness

All three Codex-backed phases should use the same shared runtime pattern.

The harness should:

1. build a phase manifest from deterministic upstream artifacts
2. partition work into bounded shards
3. assign shards to a bounded worker pool
4. materialize per-worker sandboxes
5. run workers with phase-specific instructions
6. collect structured proposals
7. validate proposals deterministically
8. promote only valid outputs
9. persist manifests, telemetry, failures, and promotion reports
10. tear down phase workspaces when the phase is complete

Required runtime properties:

- manifest-driven
- strict I/O schemas
- exact shard ownership
- deterministic promotion
- replay by shard or worker
- bounded worker lifetime
- no cross-phase workspace reuse

## Output Contract

For each Codex-backed phase, persist the runtime artifacts separately from promoted stage artifacts.

At minimum, the runtime should write:

- phase manifest
- shard manifest
- worker assignments
- per-shard proposed outputs
- promotion report
- telemetry
- failures
- per-worker logs or status files

This keeps rollback simple, retries localized, and stage authority legible.

## Sizing And Tuning

Start small and tune empirically.

Reasonable initial guidance:

- 2-6 workers per Codex-backed phase
- 3 Codex-backed phases per book
- shard size and worker count tuned together

The main questions are empirical:

- how many shards a worker can process before drift rises
- what shard size gives the best quality-cost tradeoff
- when resetting workers is cheaper than carrying more context

Those answers should come from real cookbook runs, token telemetry, quality benchmarks, and wall-time measurements.

## Observability And Preview

Reporting should match the actual runtime.

The primary units are:

- `worker_count`
- `fresh_agent_count`
- `shard_count`
- shard size distribution
- shards per worker
- phase-local payload estimates
- live token and turn telemetry from real runs
- validation and promotion outcomes

Prompt text still matters for debugging, but prompt count should not be treated as the primary explanation of cost or throughput.

## Failure Policy

If a worker fails mid-phase, keep already-promoted deterministic outputs, mark failed shards clearly, and rerun only the missing shard work when possible.

If a shard result is invalid, reject promotion for that shard and keep the deterministic baseline for the owned rows, recipes, or chunks.

If a phase completes with mixed success, persist which shards were promoted and which remained deterministic so recovery stays localized.

## Migration Plan

### 1. Make shards first-class

Introduce explicit shard manifests, ownership rules, and coverage validation before changing worker execution.

### 2. Build the shared phase-worker harness

Add the runtime that can assign multiple shard jobs to bounded workers inside phase-local sandboxes.

### 3. Cut line labeling over first

Keep deterministic labeling as the first pass, then replace prompt fan-out with worker-based shard correction.

### 4. Cut recipe correction over next

Retain deterministic intermediate building and final assembly, but move recipe correction and linkage generation into the worker model.

### 5. Localize knowledge work

Restrict knowledge refinement to bounded, label-driven shards where the extra judgment is worth the cost.

### 6. Retire legacy execution assumptions

Remove stale prompt-count reporting, old bundle-centric language, and old active execution paths once the worker model is benchmarked and trusted.

## Success Criteria

The refactor is successful when:

1. The importer still reads like the same staged pipeline.
2. Codex-backed work happens through bounded phase workers, not one fresh execution per tiny task.
3. Shards remain explicit ownership units and workers remain explicit execution units.
4. Each Codex-backed phase runs in clean, phase-local sandboxes with task-relevant files only.
5. Workers write structured proposed outputs instead of mutating authoritative artifacts in place.
6. Deterministic code still owns validation, promotion, and final assembly.
7. Recipe correction can reuse one worker context across multiple nearby recipes.
8. Knowledge refinement is label-driven and bounded rather than whole-book freeform mining.
9. Preview and benchmark outputs describe workers and shards rather than pretending prompt count is the real workload.
10. Failures are recoverable at shard or phase granularity without restarting the whole book unless necessary.

## Bottom Line

Keep the current staged, deterministic-first, label-first importer.

Replace the old high-fan-out Codex execution model with:

- explicit shards
- small bounded worker pools
- clean phase-local sandboxes
- structured proposed outputs
- deterministic validation and promotion

That is the refactor.
