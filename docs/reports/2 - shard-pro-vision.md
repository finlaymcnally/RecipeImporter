# High-Level Refactor Plan: Agent-Based Codex Processing for `cookimport`

## Executive Summary

The refactor should preserve `cookimport`’s current deterministic-first, label-first staged architecture, but replace the present high-fan-out Codex execution pattern with a bounded agent runtime.

In practical terms, the system should stop treating Codex like a stateless batch API that launches a fresh execution for each recipe, label bundle, or knowledge chunk. Instead, it should run a small farm of task-specialized shard workers that hold instructions for a bounded phase, process controlled batches inside isolated workspaces, and return proposed outputs as structured artifacts.

This is a refactor of the Codex-backed processing layer, not a rewrite of the product model. Authoritative labels, deterministic grouping, deterministic recipe assembly, replayable staged artifacts, and validation before promotion should remain intact. The operating change is how LLM work is executed, scoped, measured, and recovered.

## Refactor Goal

This refactor should improve the way Codex-backed work is executed without changing the underlying product architecture. The objective is to make the LLM layer cheaper, more scalable, and more operationally legible while preserving deterministic orchestration, authoritative staged artifacts, replayability, and validation before promotion.

## Strategic Objectives

* Reduce repeated prompt and context setup cost across real cookbook runs.
* Lower the number of fresh Codex executions required per book by moving from per-item fan-out to bounded phase workers.
* Reuse task framing and cached context within a controlled shard session without allowing one long-lived agent to become the architecture.
* Keep deterministic orchestration, label-first authority, and stage-backed outputs as the system of record.
* Make failures, retries, and benchmarking correspond to actual shard work rather than proxy prompt counts.

## Current Model vs. Target Model

|Dimension|Current Model|Target Model|
|-|-|-|
|Execution model|Many fresh per-item or per-bundle Codex executions|A smaller number of bounded workers reused within each major phase|
|Instruction loading|Instructions are repeatedly restated|Instructions are initialized once per worker session and amortized across a batch|
|Context scope|Often narrow but expensive to re-open|Still narrow, but reused inside a controlled shard session|
|Workspace model|Execution-oriented, with less emphasis on persistent task sandboxes|Per-task isolated workspaces with local `.codex` state and phase resets|
|Promotion model|LLM results can feel like direct stage output|Workers write proposed artifacts that must pass deterministic validation before promotion|
|Cost model|Dominated by repeated setup overhead|Designed to shift spend toward useful work rather than repeated framing|
|Recovery model|Retry often implies another fresh execution|Retry should operate at the shard or phase-worker level with explicit manifests|
|Observability|Prompt counts can obscure real work|Shard-level telemetry reflects real worker count, workload size, quality, cost, and runtime|

## Architectural Principles

### Deterministic-first remains the governing model

Importers, staging, grouping, validation, and final assembly remain deterministic where they are already deterministic today. LLM work stays limited to bounded judgment seams, not general orchestration.

### Label-first authority remains intact

The current repository already uses label-first staging as the authority boundary for recipe versus non-recipe ownership. That should remain true after the refactor; the new runtime changes how labels are corrected, not what labels mean.

### Agents are bounded phase workers, not global book copilots

The target operating model is a controlled farm of smaller workers that process a limited workload and then stop. The design is explicitly not one huge persistent agent for the whole book.

### Isolation is a first-class control

Each worker should run in a task-specific sandbox with its own local `.codex` state and only the manifests and files required for that task. Sandboxes should be cleared between major Codex phases.

### Agents propose outputs; deterministic code promotes them

Workers should write structured proposed outputs rather than edit live pipeline state in place. Promotion into the next stage happens only after validation.

### Manifest-driven replayability is non-negotiable

Each phase must declare inputs, ownership, outputs, and completion criteria explicitly so partial reruns and localized recovery remain possible.

### Observability must match the runtime

Reporting should describe shard count, fresh-agent count, batch size, validation results, tokens, and wall time for the actual worker model. Prompt-count proxies should not be treated as the primary operational metric.

## Target Operating Model

The refactor should be organized around three major Codex-backed phases that sit inside the existing staged pipeline: line labeling, recipe correction and ingredient-step linking, and optional knowledge refinement. Deterministic code remains responsible for ingest, segmentation, first-pass drafting, grouping, validation, final assembly, and output writing.

Each major Codex phase should run through a wrapper-agent harness built on CodexFarm. The harness should create a small number of phase-appropriate workers, load the task instructions once, assign each worker a bounded manifest-owned shard, and collect structured outputs for deterministic review and promotion.

A reasonable initial operating range is two to six workers per major phase, or roughly six to eighteen total agent instances per book. That should be treated as an initial sizing guideline rather than a hard design rule. Actual batch size, shard size, and worker count should be tuned empirically using cookbook runs, quality benchmarks, token telemetry, and wall-time measurements.

## Target End-to-End Flow

### 1\. Ingest and normalize source material

Preserve useful native structure when it exists. This remains a deterministic extraction and normalization step.

### 2\. Segment into stable evidence units and build deterministic first-pass artifacts

Stable block or line identities, provenance, and deterministic stage outputs remain the evidence layer for everything downstream.

### 3\. Run the line-label phase with bounded workers

Workers review local manifests, deterministic labels, and uncertainty signals and return proposed label corrections only for their owned shard.

### 4\. Deterministically regroup recipe spans from authoritative labels

Recipe ownership should continue to flow from the authoritative label stage rather than from a separate heuristic-first architecture.

### 5\. Deterministically build intermediate recipe drafts

Intermediate recipe objects remain the main structural debug artifact and the first draft for the recipe phase.

### 6\. Run the recipe phase with bounded workers

Workers review grouped evidence and intermediate drafts for nearby owned recipes, correct the structure, and emit ingredient-step linkage or other final-format deltas needed for deterministic assembly.

### 7\. Deterministically assemble final recipes

Final recipe outputs should be built locally from the corrected intermediate structure and linkage payloads, rather than by spending another heavy model pass on simple reshaping.

### 8\. Separate non-recipe spans and optionally refine knowledge

Knowledge refinement should be downstream of authoritative labels and should run only on spans already classified as knowledge, not as a whole-book mining surface.

### 9\. Validate, promote, and write outputs

Every promoted result should be explainable from the stage artifacts, the owning shard manifest, and the validation report.

## Runtime Controls and Guardrails

* Each worker receives only the files, manifests, and schema needed for its task family.
* Every shard has stable ownership boundaries and exact-once coverage for the items it is allowed to modify.
* Working folders are reset between the three major Codex phases after outputs are returned upstream.
* Fallback or retry behavior is allowed, but only as an explicit exception path tied to validation failure, not as the default architecture.
* Long-lived hidden workspace state should not be relied upon as part of correctness.

## What Changes in This Refactor

* The default LLM operating model moves from many stateless per-item executions to a bounded farm of per-phase workers.
* CodexFarm becomes an execution harness for manifest-owned shard work rather than a thin wrapper around repeated fresh prompts.
* Recipe correction work is consolidated so one recipe-phase reasoning pass can both correct intermediate structure and emit linkage data for deterministic final assembly.
* Knowledge work becomes smaller and more selective: label-driven, bounded, and optional rather than a large separate mining surface.
* Benchmarking and previews shift toward real worker and shard telemetry instead of old prompt-count language.

## What Remains Authoritative

* The repository remains deterministic-first.
* Label-first staging remains the authority boundary for recipe versus non-recipe ownership.
* Intermediate recipe drafts remain a required debug and validation artifact.
* Final recipe objects remain deterministically assembled where possible.
* Strict I/O schemas, evaluation before promotion, replayability, Label Studio reuse, and benchmark reuse remain part of the operating model.

## What Should Be Removed or Simplified

* The old prompt-per-bundle or per-recipe fan-out mental model as the default way to use Codex.
* Any reporting language that equates prompt count with actual shard cost or throughput.
* Unbounded or loosely bounded Codex work that asks the model to rediscover the entire book from scratch.
* Cross-phase workspace bleed or dependence on unrelated project instructions inside a worker sandbox.
* Redundant heavy model passes when deterministic assembly can write the final object from an already-corrected structure.

## Phased Migration Plan

### 1\. Build the wrapper-agent harness and shard observability

Introduce manifest-owned workers, local isolated workspaces, real shard telemetry, and phase-level retry surfaces before broad logic changes.

### 2\. Cut line labeling over to bounded phase workers

Keep deterministic labeling as the first pass, then replace fresh prompt fan-out with worker-based label correction over local shards.

### 3\. Cut recipe correction over to bounded phase workers

Retain deterministic intermediate building and final assembly, but move recipe correction and linkage generation into the worker model.

### 4\. Localize and shrink knowledge processing

Restrict knowledge work to spans already labeled as knowledge, processed through bounded workers only where the additional judgment is worth the cost.

### 5\. Retire legacy execution assumptions

Remove stale prompt-count reporting, old bundle-centric language, and legacy active paths once the new worker model is benchmarked and trusted.

## Success Criteria

* A single page can explain the end-to-end operating model without referring to historical pass numbering or legacy prompt bundles.
* The number of fresh Codex executions per cookbook is materially lower, and the reduction is visible in run telemetry.
* Quality holds or improves for label correction, recipe correction, and optional knowledge refinement at an acceptable cost profile.
* Every promoted result can be traced to a deterministic stage artifact, a worker manifest, and a validation outcome.
* Failures can be isolated and rerun at the shard or phase level rather than forcing a full-book restart.
* Benchmark, analytics, and Label Studio flows continue to consume the same staged artifact model rather than inventing a parallel architecture.
* Worker count, shard size, and batch size can be tuned empirically against real books without changing the fundamental design.

## Out of Scope

* Replacing the deterministic importers or staging model.
* Turning the system into one long-lived autonomous agent.
* Letting workers edit authoritative pipeline state in place without validation.
* Reopening settled authority boundaries between staged artifacts and downstream tools.

## Bottom Line

The correct alignment is to keep the current staged, deterministic-first, label-first architecture, but refactor the Codex layer into a bounded agent system. The winning design is not a giant persistent agent and it is not the old stateless fan-out model. It is a controlled CodexFarm harness of task-specialized workers, each operating inside an isolated sandbox over a manifest-owned batch, writing proposed outputs that deterministic code validates and promotes. That gives the project the lower overhead and better context reuse described in the memo without sacrificing the authority boundaries, replayability, and observability that already exist in the codebase.

