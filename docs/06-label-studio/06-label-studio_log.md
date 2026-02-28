---
summary: "Label Studio architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on Label Studio behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, builds, and failed fix attempts before trying another change
---

# Label Studio Log: Architecture, Builds, and Fix Attempts

Use this log when debugging starts looping. It is intentionally compact and keeps only durable, still-relevant history.

## 1) High-Signal Timeline

### 2026-02-10: freeform span workflow became the primary contract

- Introduced `freeform-spans` task scope and segment-based tasking.
- Standardized freeform labels and offset-preserving text handling.
- Established span export artifacts + freeform eval path.

### 2026-02-11: hardening and observability pass

- Added explicit write-consent gate for Label Studio writes.
- Expanded import/benchmark progress reporting.
- Fixed split-job merge reindex behavior to avoid false zero-match evaluations.
- Added freeform eval diagnostics and source-match override path.

### 2026-02-15: interactive UX simplification

- Interactive import became direct upload flow (no second confirmation).
- Interactive import standardized on overwrite semantics.
- Interactive export moved to credential-first + project-picker flow with manual fallback.

### 2026-02-22: prelabel contract stabilization

- Interactive prelabel mode mapping aligned with CLI flags.
- Default Codex subprocess path standardized on `codex exec -` with plain-command fallback on TTY errors.
- Added task-level progress counters (`task X/Y`) with shared callback plumbing.
- Finalized taxonomy normalization and compatibility aliases.

### 2026-02-23: prelabel reliability and throughput

- Added bounded parallel prelabel workers with deterministic result ordering.
- Split task payload into focus rows (offset-authoritative) vs prompt-only context rows.
- Raised default prelabel timeout to 300s.
- Made progress callback failures non-fatal.
- Added rate-limit stop behavior (first 429 stops new provider calls).
- Added reasoning-token usage accounting where provided by Codex usage payloads.

### 2026-02-24: quality guardrails

- Added model-compatible thinking-effort filtering in interactive menus.
- Added quote repair for span mode when quote text is valid but block index is wrong.
- Kept empty `[]` span output as valid "no spans" result.
- Persisted recipe-header diagnostics in export summaries.

### 2026-02-25: freeform-only migration boundary finalized

- Removed legacy scope execution branches from import/export/eval runtime paths.
- Kept legacy scope inference only for UX tagging and explicit rejection messaging.
- Moved shared archive helpers to scope-neutral `cookimport/labelstudio/archive.py`.

## 2) Current Non-Negotiable Contracts

- Runtime scope is `freeform-spans`.
- Export rejects legacy-scoped (`pipeline`, `canonical-blocks`) projects/manifests/payloads.
- Deterministic IDs (`segment_id`, `span_id`) remain core to resume/idempotence and auditability.
- Prelabel supports both `block` and `span` granularity, with strict offset/text integrity.
- Split-job merges must keep global block-index rebasing.
- Benchmark eval is dual-mode (`stage-blocks` + `canonical-text`) and both paths remain active runtime contracts.
- Prediction-record replay/generation (`--predictions-in`, `--predictions-out`) is a supported benchmark contract, not debug-only tooling.

## 3) Known Bad Loops To Avoid

- Do not reintroduce legacy scope options/prompts as active execution branches.
- Do not treat prompt-only filtering as enough for focus scoping; parser/runtime enforcement is required.
- Do not classify empty span output (`[]`) as automatic provider failure.
- Do not assume callback/spinner failures indicate conversion/import failure.
- Do not diagnose benchmark mismatch before checking source-identity constraints.

### 2026-02-27_19.44.58 labelstudio docs prune scope map

Problem captured:
- Label Studio docs had blended active freeform contracts with retired branch history.

Durable decisions:
- Keep freeform runtime contracts, deterministic ID/resume behavior, and prelabel runtime details.
- Keep explicit retired notes for removed scope execution branches and decorate flow, but do not document them as active behavior.

### 2026-02-27_19.50.37 labelstudio docs coverage audit

Problem captured:
- Module + artifact coverage in docs was incomplete for current runtime paths.

Durable decisions:
- Include missing runtime modules and benchmark dependencies in README code maps.
- Document prediction-record replay/generation contracts and canonical-text extra diagnostics.
- Keep manifest and analytics-history side effects visible in command contract docs.
