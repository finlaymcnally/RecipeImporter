---
summary: "ExecPlan to consolidate external-AI cutdown feedback into a single high-signal diagnostic artifact contract."
read_when:
  - "When changing scripts/benchmark_cutdown_for_external_ai.py output artifacts or sampling policy."
  - "When optimizing codex-vs-vanilla benchmark cutdowns for diagnosis-per-token."
---

# ExecPlan: Consolidate External-AI Cutdown Feedback Into One Diagnostic Contract

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, one cutdown package will let an external reviewer explain exactly why Codex and vanilla differ, without wasting tokens on duplicate views of the same errors. The package will remain machine-readable first, with concise convenience summaries second.

Today, the three feedback drafts overlap heavily and disagree on emphasis. This plan merges them into one chosen contract: preserve exact per-call prompt payloads and Codex-vs-vanilla disagreement evidence, add context/provenance where diagnosis still breaks down, and remove redundant sampled artifacts.

## Progress

- [x] 2026-03-02_23.54.21 — Merged the three feedback drafts into one ExecPlan-ready direction and removed duplicate ideas in this document.
- [x] 2026-03-02_23.54.21 — Audited current `scripts/benchmark_cutdown_for_external_ai.py` behavior to mark what is already implemented versus what remains.
- [ ] Implement remaining contract gaps in `scripts/benchmark_cutdown_for_external_ai.py` (preprocess-failure trace export + richer unsampled failure export).
- [ ] Add regression tests for new artifacts and conditional emission behavior.
- [ ] Update benchmark docs to reflect the finalized external-AI package contract.

## Surprises & Discoveries

- Observation: Many high-value feedback items are already implemented in the script, including `full_prompt_log.jsonl`, `changed_lines.codex_vs_vanilla.jsonl`, `per_recipe_or_per_span_breakdown.json`, `prompt_warning_aggregate.json`, `projection_trace.codex_to_benchmark.json`, targeted prompt cases, and label-policy notes.
  Evidence: `scripts/benchmark_cutdown_for_external_ai.py` constants and `_build_run_cutdown(...)` / `_build_pair_diagnostics(...)` / `_build_comparison_summary(...)` paths already emit these files.

- Observation: The cutdown currently keeps sampled line-level error files, but there is no compressed full-failure export that preserves broader context/provenance for deep debugging.
  Evidence: `_write_jsonl_sample(...)` is used for `wrong_label_lines` and `missed_gold_lines`; no `*.jsonl.gz` full-failure artifact is emitted.

- Observation: Alignment artifacts are already optimized for healthy runs (counts-only unless alignment health drops below thresholds).
  Evidence: `_alignment_is_healthy(...)` gates alignment sampling in `_build_run_cutdown(...)`.

## Decision Log

- Decision: Keep `full_prompt_log.jsonl` as the source-of-truth prompt artifact and keep `codexfarm_prompt_log.dedup.txt` as convenience-only.
  Rationale: Full logs are required for prompt-level causality; sampled text logs are still useful for fast skims.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Keep one canonical Codex-vs-vanilla disagreement artifact (`changed_lines.codex_vs_vanilla.jsonl`) with line context and labels.
  Rationale: This is the highest-value causal view and replaces multiple overlapping “wrong/missed/false-positive” interpretations for cross-run comparison.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Keep line-space diagnostics as primary and treat block-space debug artifacts as conditional/secondary.
  Rationale: Canonical scoring is line-based; line-space artifacts map directly to the benchmark objective.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Add preprocess-failure traces as the next required artifact gap.
  Rationale: Feedback consistently shows failures introduced before pass prompting (for example fused yield+ingredient+heading lines), which cannot be diagnosed from prompt text alone.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Prefer machine-readable JSON/JSONL outputs; flattening remains optional.
  Rationale: External AI reviewers and downstream tools get better signal-per-token from structured data than from repeated markdown flattening.
  Date/Author: 2026-03-02 / Assistant.

## Outcomes & Retrospective

This plan rewrite is complete, but implementation is intentionally pending. The main outcome so far is a single resolved contract that future implementation can follow without re-litigating overlapping suggestions.

Expected end-state after implementation:
- external reviewers can explain metric deltas using exact disagreement rows, prompt warnings, and provenance traces;
- package size remains controlled by removing redundant low-signal artifacts;
- diagnosis no longer depends on a handful of sampled prompt/error rows.

## Context and Orientation

Primary implementation target:
- `scripts/benchmark_cutdown_for_external_ai.py`

Current contract anchors:
- root summary artifacts: `comparison_summary.json`, `run_index.json`, `process_manifest.json`
- per-run summary: `need_to_know_summary.json`
- Codex prompt payload: `full_prompt_log.jsonl`
- Codex-vs-vanilla disagreement: `changed_lines.codex_vs_vanilla.jsonl`
- slice diagnostics: `per_recipe_or_per_span_breakdown.json`
- prompt diagnostics: `prompt_warning_aggregate.json`, `targeted_prompt_cases.md`
- projection bridge diagnostics: `projection_trace.codex_to_benchmark.json`

Gaps this plan addresses:
- no first-class preprocess-failure trace artifact showing raw extracted text versus post-preprocess blocks for failing lines;
- no compact full-failure export (`*.jsonl.gz`) for non-sampled deep analysis.

## Plan of Work

### Milestone 1: Lock the final artifact contract

Define the final contract in script constants and README generation logic so output expectations are explicit and testable.

Keep as core artifacts:
- `comparison_summary.json`
- per-run `need_to_know_summary.json`
- per-run `full_prompt_log.jsonl`
- root `changed_lines.codex_vs_vanilla.jsonl`
- root `per_recipe_or_per_span_breakdown.json`
- root `targeted_prompt_cases.md`
- per-run `prompt_warning_aggregate.json`
- per-run `projection_trace.codex_to_benchmark.json`
- root `label_policy_adjudication_notes.md`

Add missing high-value artifacts:
- per-run `preprocess_trace_failures.jsonl.gz`
- per-run `wrong_label_with_context.full.jsonl.gz` (or equivalent full-failure export with context + provenance IDs)

Trim or keep conditional:
- keep `wrong_label_lines.sample.jsonl` and `missed_gold_lines.sample.jsonl` for quick scans;
- keep alignment debug samples only when alignment is unhealthy;
- avoid adding any duplicate block-level views when line-level information already encodes the issue.

### Milestone 2: Implement preprocess and provenance failure exports

In `scripts/benchmark_cutdown_for_external_ai.py`, add helpers to collect and write compressed failure-focused traces:
- source/raw text span metadata (where available from benchmark artifacts),
- post-preprocess candidate block text sent to pass calls,
- failing line indices and related recipe/pass identifiers,
- warning flags (for example split-line boundary warnings).

Implementation should degrade gracefully: when an older run lacks source artifacts, emit a status object in `sample_counts` explaining why the trace is unavailable instead of failing package generation.

### Milestone 3: Add tests and documentation updates

Add regression tests that verify:
- required new artifact files appear for eligible runs;
- graceful “missing source trace” behavior for older runs;
- process manifest `included_files` enumerates new root and per-run artifacts;
- existing artifact compatibility is preserved.

Update docs:
- `scripts/README.md` artifact list and flag behavior;
- benchmark docs where the external-AI package contract is described.

## Concrete Steps

All commands run from `/home/mcnal/projects/recipeimport`.

1. Implement script changes in `scripts/benchmark_cutdown_for_external_ai.py`.

2. Run targeted tests in the local venv (create/update tests if missing):

    source .venv/bin/activate && pytest -q tests/bench tests/labelstudio

3. Build a cutdown package from a known benchmark root and inspect outputs:

    source .venv/bin/activate && python scripts/benchmark_cutdown_for_external_ai.py <benchmark_root> --output-dir <cutdown_out> --overwrite --keep-cutdown

4. Validate manifest and artifact presence:

    source .venv/bin/activate && rg "preprocess_trace_failures|wrong_label_with_context|changed_lines.codex_vs_vanilla" <cutdown_out>/process_manifest.json <cutdown_out>/run_index.json

## Validation and Acceptance

Acceptance is met when all statements below are true:

- Each codex-enabled run package contains `full_prompt_log.jsonl` and `prompt_warning_aggregate.json`.
- Root package contains `changed_lines.codex_vs_vanilla.jsonl`, `per_recipe_or_per_span_breakdown.json`, and `targeted_prompt_cases.md`.
- New preprocess/failure exports exist for runs with required source artifacts, and missing-artifact runs report explicit status instead of failing.
- No duplicate block-level artifact families are reintroduced when they do not add diagnosis value beyond line-level files.
- `process_manifest.json` fully enumerates included root/per-run artifacts needed by downstream validators.

## Idempotence and Recovery

The cutdown script must remain idempotent with `--overwrite`: re-running with the same input should regenerate the same artifact contract and deterministic sampled outputs. Source benchmark directories must remain read-only.

If generation fails mid-run, recovery is re-running the same command with `--overwrite`. No manual cleanup should be required beyond deleting the incomplete output folder.

## Artifacts and Notes

Expected disagreement row shape (illustrative):

    {
      "line_index": 412,
      "recipe_id": "recipe_7",
      "span_region": "inside_active_recipe_span",
      "gold_label": "INGREDIENT_LINE",
      "vanilla_pred": "YIELD_LINE",
      "codex_pred": "INGREDIENT_LINE",
      "previous_line": "...",
      "current_line": "...",
      "next_line": "..."
    }

Expected preprocess-failure row shape (illustrative):

    {
      "line_index": 412,
      "recipe_id": "recipe_7",
      "source_block_ids": ["b799"],
      "raw_extracted_text": "...",
      "post_preprocess_block_text": "...",
      "pass": "pass2",
      "warning_buckets": ["split_line_boundary"]
    }

## Interfaces and Dependencies

Script/module boundary:
- keep all logic inside `scripts/benchmark_cutdown_for_external_ai.py` unless code reuse justifies extracting a small helper module.

Artifact schema stability:
- existing core artifact names stay stable;
- new files are additive and must be referenced in `process_manifest.json`;
- summary fields should remain backward-compatible for current consumers.

Compression dependency:
- use Python standard library (`gzip`) only; do not add external package dependencies.

Revision Note (2026-03-02_23.54.21): Rewrote this file from three overlapping feedback dumps into one ExecPlan with deduplicated decisions and a single chosen artifact strategy.
