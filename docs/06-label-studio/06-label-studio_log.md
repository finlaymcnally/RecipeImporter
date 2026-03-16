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
- Prelabel command/model resolution was standardized around explicit option -> env override -> default.
- Added task-level progress counters (`task X/Y`) with shared callback plumbing.
- Finalized taxonomy normalization and compatibility aliases.

### 2026-02-23: prelabel reliability and throughput

- Added bounded parallel prelabel workers with deterministic result ordering.
- Split task payload into focus rows (offset-authoritative) vs prompt-only context rows.
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

### 2026-03-02: benchmark compare became an active contract

- `labelstudio-benchmark compare` became a supported action, not ad hoc analysis.
- Compare accepts both all-method report roots and direct `eval_report.json` inputs.
- Compare outputs standardized on `comparison.json` + `comparison.md` plus terminal gate tables.

### 2026-03-05: Codex preview boundary was locked down

- Plan-only benchmark/import previews remain command-boundary features.
- Deterministic extraction/planning may run, but task generation, upload, benchmark eval, and live Codex work stay skipped.

### 2026-03-15: prelabel backend identity cleanup

- Freeform prelabel backend identity was standardized on `codex-farm`.
- Retired `codex-cli` aliases were removed from active policy/runtime handling.

## 2) Current Non-Negotiable Contracts

- Runtime scope is `freeform-spans`.
- Export rejects legacy-scoped (`pipeline`, `canonical-blocks`) projects/manifests/payloads.
- Deterministic IDs (`segment_id`, `span_id`) remain core to resume/idempotence and auditability.
- Prelabel supports both `block` and `span` granularity, with strict offset/text integrity.
- Prelabel provider identity is `codex-farm`.
- Split-job merges must keep global block-index rebasing.
- Benchmark eval is dual-mode (`stage-blocks` + `canonical-text`) and both paths remain active runtime contracts.
- Prediction-record replay/generation (`--predictions-in`, `--predictions-out`) is a supported benchmark contract, not debug-only tooling.
- Benchmark compare is an active contract for both all-method report roots and single `eval_report.json` inputs.
- Plan-only previews write manifests plus `codex_execution_plan.json` and stop before task generation/upload/eval/live Codex work.

## 3) Known Bad Loops To Avoid

- Do not reintroduce legacy scope options/prompts as active execution branches.
- Do not treat prompt-only filtering as enough for focus scoping; parser/runtime enforcement is required.
- Do not classify empty span output (`[]`) as automatic provider failure.
- Do not assume callback/spinner failures indicate conversion/import failure.
- Do not diagnose benchmark mismatch before checking source-identity constraints.
- Do not change scorers because a reused project is missing a code label; check project `label_config` freshness first.
- Do not treat plan-only previews as if downstream task/eval artifacts should exist.
- Do not reintroduce retired prelabel backend aliases (`codex-cli`, direct `codex exec`) into active runtime paths.

## 4) Still-Relevant Historical Gotchas

- `labelstudio-export` writes explicit spans only; unlabeled regions are implicit and benchmark scorers treat them as `OTHER`.
- Overlapping exported spans are preserved; stage-block and canonical-text scorers treat touched blocks/lines as multi-label gold.
- `HOWTO_SECTION` is intentionally UI-visible/exported, but freeform eval and stage-block scoring remap it to ingredient/instruction context while canonical-text scoring keeps it explicit.
- Adding a freeform label is multi-surface work: UI/export normalization, freeform eval, stage-block allowed labels, and both benchmark scorers must all agree.
