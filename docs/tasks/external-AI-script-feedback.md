---
summary: "ExecPlan to finalize one high-signal external-AI cutdown artifact contract with full-failure context exports and deterministic packaging behavior."
read_when:
  - "When changing scripts/benchmark_cutdown_for_external_ai.py output artifacts, manifest semantics, or sampling policy."
  - "When improving codex-vs-vanilla diagnosis quality per token for external review packages."
---

# ExecPlan: Finalize External-AI Cutdown Diagnostic Contract

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, an external reviewer should be able to answer two concrete questions from a single package without requesting extra artifacts: "Where did Codex and vanilla disagree?" and "What preprocessing or prompt context likely caused those disagreements?" The package stays machine-readable first, keeps token-heavy artifacts bounded, and avoids duplicate representations of the same signal.

The current cutdown already covers most high-value diagnosis surfaces, but it still lacks an unsampled failure export and a first-class preprocess trace for failing lines. Those missing pieces force reviewers to rely on sampled rows or ad hoc reruns when they need deep root-cause analysis.

## Progress

- [x] 2026-03-02_23.54.21 - Merged overlapping feedback drafts into one initial ExecPlan direction.
- [x] 2026-03-02_23.54.21 - Audited current `scripts/benchmark_cutdown_for_external_ai.py` artifacts and confirmed most high-signal outputs already exist.
- [x] 2026-03-02_23.59.34 - Reworked this ExecPlan to be implementation-ready: explicit helper/function touchpoints, artifact schemas, fallback semantics, and deterministic packaging rules.
- [x] 2026-03-03_10.40.00 - Implemented additive per-run full-failure exports in `scripts/benchmark_cutdown_for_external_ai.py` (`wrong_label_lines.with_context.full.jsonl.gz`, `preprocess_trace_failures.jsonl.gz`) with deterministic gzip writes (`mtime=0`) and explicit fallback statuses.
- [x] 2026-03-03_10.40.00 - Added regression tests in `tests/bench/test_benchmark_cutdown_for_external_ai.py` for new exports, fallback statuses, process-manifest nested path inclusion, and repeated-run gzip byte stability.
- [x] 2026-03-03_10.40.00 - Updated operator-facing docs (`scripts/README.md`, `docs/07-bench/07-bench_README.md`) and added implementation understanding notes for the finalized contract.

## Surprises & Discoveries

- Observation: The script already emits the main causality contract expected by external reviewers (`full_prompt_log.jsonl`, `changed_lines.codex_vs_vanilla.jsonl`, `per_recipe_or_per_span_breakdown.json`, `targeted_prompt_cases.md`, `prompt_warning_aggregate.json`, `projection_trace.codex_to_benchmark.json`).
  Evidence: constants and writes in `_build_run_cutdown(...)`, `_build_pair_diagnostics(...)`, and `_build_comparison_summary(...)`.

- Observation: `wrong_label_lines.sample.jsonl` and `missed_gold_lines.sample.jsonl` are sampled-only outputs; no compressed full-failure companion exists today.
  Evidence: `LINE_LEVEL_SAMPLED_JSONL_INPUTS` is written via `_write_jsonl_sample(...)`, and there is no `*.jsonl.gz` emission path.

- Observation: The right place to source preprocess context is the benchmark run's linked prediction run (`run_manifest.artifacts.pred_run_dir`) plus prediction-run artifacts (`extracted_archive.json`, pass input payloads).
  Evidence: `_resolve_prediction_run_dir(...)` and prediction-run manifest contracts in `cookimport/labelstudio/ingest.py`.

- Observation: Default gzip writing is not deterministic unless mtime is controlled.
  Evidence: Python gzip headers include timestamp metadata unless explicitly pinned.

- Observation: Preprocess trace rows can still be materially useful when one side of context is missing at the row level (for example missing archive block for a specific line), even if run-level dependencies are present.
  Evidence: New `trace_status` values in `preprocess_trace_failures.jsonl.gz` rows differentiate joined vs partial context while run-level `sample_counts` keep contract-level status.

## Decision Log

- Decision: Keep `full_prompt_log.jsonl` as the canonical prompt artifact and keep `codexfarm_prompt_log.dedup.txt` as convenience-only.
  Rationale: Full logs are needed for causality; sampled text remains useful for fast skims.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Keep `changed_lines.codex_vs_vanilla.jsonl` as the single canonical disagreement artifact.
  Rationale: It is the highest-signal codex-vs-baseline delta view and already aligns with benchmark objective scoring.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Add two per-run additive exports: `preprocess_trace_failures.jsonl.gz` and `wrong_label_lines.with_context.full.jsonl.gz`.
  Rationale: These close the remaining diagnosis gaps without replacing existing stable artifacts.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Make gzip outputs deterministic (`mtime=0`) and schema-stable.
  Rationale: Repeated cutdowns should be byte-stable enough for regression checks and safe diffing.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Missing upstream artifacts must produce explicit status rows in `need_to_know_summary.json` `sample_counts`, not hard failures.
  Rationale: Old benchmark runs must still package successfully.
  Date/Author: 2026-03-02 / Assistant.

- Decision: Include new nested per-run gzip artifact paths in root `process_manifest.json` `included_files`.
  Rationale: Root-level manifest consumers need one deterministic inventory without scanning run subfolders.
  Date/Author: 2026-03-03 / Assistant.

## Outcomes & Retrospective

Implementation is complete and validated. Cutdown now emits deterministic full-failure gzip exports, reports explicit fallback statuses when trace dependencies are missing, and includes nested artifact paths in root manifests. Regression coverage now verifies file emission, fallback status behavior, root manifest inclusion, and repeated-run byte stability for both new gzip files.

## Context and Orientation

Primary implementation file:

- `scripts/benchmark_cutdown_for_external_ai.py`

Primary regression test file:

- `tests/bench/test_benchmark_cutdown_for_external_ai.py`

Relevant doc surfaces:

- `scripts/README.md`
- `docs/07-bench/07-bench_README.md`

Current output contract that remains in place:

- Root: `comparison_summary.json`, `run_index.json`, `process_manifest.json`, `changed_lines.codex_vs_vanilla.jsonl`, `per_recipe_or_per_span_breakdown.json`, `targeted_prompt_cases.md`, `label_policy_adjudication_notes.md`.
- Per-run: `need_to_know_summary.json`, sampled line-level files, conditional alignment samples, `full_prompt_log.jsonl` (when available/reconstructed), and codex-only prompt diagnostics.

Key data sources for the new exports:

- `wrong_label_lines.jsonl` in each benchmark run directory (failure anchor rows).
- canonical text lines from eval artifacts already consumed by `_build_line_prediction_view(...)`.
- full prompt rows from `full_prompt_log.jsonl` where available.
- prediction-run path from `run_manifest.artifacts.pred_run_dir` (or `prediction-run` fallback), with prediction-run artifacts such as `extracted_archive.json`.

Terms used in this plan:

- Preprocess failure trace: per failing line, a compact record that ties wrong-label evidence to nearby raw/preprocessed source text and pass-call context when available.
- Full-failure export: unsampled wrong-label rows with line context and provenance IDs, compressed as JSONL GZIP for size control.

## Plan of Work

### Milestone 1: Lock artifact names, statuses, and manifest semantics

Update constants and summary bookkeeping in `scripts/benchmark_cutdown_for_external_ai.py` so the contract is explicit and testable. Add constants for:

- `preprocess_trace_failures.jsonl.gz`
- `wrong_label_lines.with_context.full.jsonl.gz`

Extend per-run `sample_counts` to include deterministic status payloads for both files (`written`, `missing_prediction_run`, `missing_extracted_archive`, `missing_full_prompt_log`, `not_applicable` as appropriate). Ensure `need_to_know_summary.json` `included_files` and root `process_manifest.json` `included_files` include these files when written.

### Milestone 2: Implement full-failure export helpers

Add focused helpers in `scripts/benchmark_cutdown_for_external_ai.py` near existing JSONL helper utilities:

- deterministic gzip writer helper for JSONL rows (use stdlib `gzip` and `mtime=0`),
- wrong-label full-context row builder that augments every wrong label row with `previous_line/current_line/next_line`, run IDs, source key metadata, and recipe/span annotations already derivable from existing line-view logic,
- preprocess-trace row builder that attempts to join failing line rows with pass-call and extracted-archive context.

Reuse existing loaders where possible (`_resolve_prediction_run_dir(...)`, `_iter_jsonl(...)`, `_build_line_prediction_view(...)`, `_build_recipe_spans_from_full_prompt_rows(...)`) rather than creating a parallel parsing stack.

### Milestone 3: Wire helpers into `_build_run_cutdown(...)`

Integrate helper calls after sampled line-level files are produced and after prompt diagnostics are computed, so all required context is in memory. Required behavior:

- always attempt `wrong_label_lines.with_context.full.jsonl.gz` when `wrong_label_lines.jsonl` exists;
- attempt `preprocess_trace_failures.jsonl.gz` only when failure rows exist, using prediction-run artifacts and prompt rows when available;
- never fail package generation when supporting artifacts are missing; write status-only metadata in `sample_counts`.

### Milestone 4: Add regression tests

In `tests/bench/test_benchmark_cutdown_for_external_ai.py`, add tests that cover:

- new gzip artifacts appear and decode to expected rows for a synthetic codex-enabled run,
- graceful status behavior when prediction-run or extracted archive artifacts are absent,
- process manifest includes new files when present,
- repeated run with identical fixtures produces deterministic gzip payload bytes.

### Milestone 5: Update docs

Update documentation to describe the finalized contract and intended usage:

- `scripts/README.md` script bullet for `benchmark_cutdown_for_external_ai.py`,
- `docs/07-bench/07-bench_README.md` external-AI cutdown contract section.

Keep descriptions concise and focused on what is guaranteed versus conditional.

## Concrete Steps

All commands run from `/home/mcnal/projects/recipeimport`.

1. Implement milestones 1-3 in `scripts/benchmark_cutdown_for_external_ai.py`.

2. Run targeted tests in project venv:

    source .venv/bin/activate && pytest tests/bench/test_benchmark_cutdown_for_external_ai.py -q

3. Run bench-domain fast suite for regression confidence:

    source .venv/bin/activate && ./scripts/test-suite.sh domain bench -- -k cutdown

4. Build a cutdown package against a known benchmark root:

    source .venv/bin/activate && python scripts/benchmark_cutdown_for_external_ai.py <benchmark_root> --output-dir <cutdown_out> --overwrite --keep-cutdown

5. Validate artifact and status presence:

    source .venv/bin/activate && rg "preprocess_trace_failures|wrong_label_lines\\.with_context\\.full|full_prompt_log|included_files" <cutdown_out>/process_manifest.json <cutdown_out>/*/need_to_know_summary.json

## Validation and Acceptance

Acceptance is met when all statements below are true:

- Existing core artifacts remain unchanged in name and meaning (`changed_lines.codex_vs_vanilla.jsonl`, `per_recipe_or_per_span_breakdown.json`, `targeted_prompt_cases.md`, `full_prompt_log.jsonl` behavior).
- New per-run gzip exports are written for runs with eligible failure/context data.
- Runs lacking prediction-run context still complete, and `sample_counts` clearly explains why preprocess traces are unavailable.
- `process_manifest.json` and per-run `need_to_know_summary.json` enumerate newly written files.
- New tests fail before implementation and pass after implementation.
- Re-running on identical input yields stable artifact content (including deterministic gzip payloads).

## Idempotence and Recovery

The script remains idempotent under `--overwrite`. Re-running with the same inputs regenerates the same contract and statuses. Source benchmark directories stay read-only.

If generation fails mid-run, recovery is to rerun the same command with `--overwrite`. No manual in-place mutation should be required.

For deterministic gzip behavior, write gzip members with fixed metadata (`mtime=0`) so content comparisons are meaningful between reruns.

## Artifacts and Notes

Expected full-failure row shape (`wrong_label_lines.with_context.full.jsonl.gz`):

    {
      "run_id": "2026-03-02_10.00.00",
      "line_index": 412,
      "recipe_id": "recipe_7",
      "span_region": "inside_active_recipe_span",
      "gold_label": "INGREDIENT_LINE",
      "pred_label": "YIELD_LINE",
      "previous_line": "...",
      "current_line": "...",
      "next_line": "...",
      "source_file": "book.epub",
      "source_key": "source-hash"
    }

Expected preprocess trace row shape (`preprocess_trace_failures.jsonl.gz`):

    {
      "run_id": "2026-03-02_10.00.00",
      "line_index": 412,
      "recipe_id": "recipe_7",
      "raw_block_excerpt": "...",
      "prompt_candidate_block_excerpt": "...",
      "pass": "pass2",
      "warning_buckets": ["split_line_boundary"],
      "trace_status": "joined_with_prompt_and_archive"
    }

## Interfaces and Dependencies

Prescriptive helper interfaces to add in `scripts/benchmark_cutdown_for_external_ai.py`:

    def _write_jsonl_gzip_deterministic(path: Path, rows: list[dict[str, Any]]) -> int:
        ...

    def _build_wrong_label_full_context_rows(
        *,
        run_dir: Path,
        recipe_spans: list[dict[str, Any]],
        excerpt_limit: int,
    ) -> list[dict[str, Any]]:
        ...

    def _build_preprocess_trace_failure_rows(
        *,
        run_dir: Path,
        run_manifest: dict[str, Any],
        full_prompt_rows: list[dict[str, Any]],
        excerpt_limit: int,
    ) -> tuple[list[dict[str, Any]], str]:
        ...

Constraints:

- Keep implementation in the existing script unless a helper module is clearly justified.
- Use Python stdlib only (`gzip`, `json`, existing utilities); no new external dependencies.
- Do not introduce any LLM-based parsing or cleaning behavior.

Revision note (2026-03-02_23.54.21): Initial merge of overlapping feedback into one ExecPlan direction.
Revision note (2026-03-02_23.59.34): Improved plan quality with concrete function-level implementation map, deterministic gzip requirement, explicit fallback statuses, and tighter validation criteria.
Revision note (2026-03-03_10.40.00): Updated living-plan sections after implementation to mark milestones complete, record new manifest/row-level decisions, and capture validation outcomes from new regression tests.
