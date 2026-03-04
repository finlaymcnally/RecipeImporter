---
summary: "Working ExecPlan for ProFeedback follow-up focused on pass3 ROI, candidate-label diagnostics, and upload-bundle completeness."
read_when:
  - "When planning the next codex-farm quality/runtime iteration after 2026-03-03_20.49.14."
  - "When deciding which ProFeedback suggestions are still actionable vs already implemented."
---

# Rebaseline ProFeedback into codebase-grounded codex follow-up milestones

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `docs/PLANS.md` from the repository root.

This plan builds on already-shipped work in `docs/plans/2026-03-03_20.13.22-codexfarm-soft-gating-runtime-outside-span-precision.md`. It intentionally excludes suggestions that are already implemented there.

## Purpose / Big Picture

The original `ProFeedback.md` was a useful narrative, but it was not executable and some recommendations were already outdated. After this plan is implemented, the next iteration work will be focused on real remaining gaps: reducing expensive low-payoff pass3 calls, exposing missing line-role candidate-label diagnostics, and ensuring upload bundles include the diagnostic artifacts that feedback reviewers actually need.

A novice should be able to verify success by running one paired SeaAndSmoke benchmark and checking three observable outcomes: pass3 token/runtime share decreases without losing codex quality gains, `candidate_label_signal.available` becomes true in the upload bundle, and run diagnostics for codex stop reporting the known missing artifact statuses.

Scope guard: this plan is benchmark/evaluation-only and must not enable codex-farm or other LLM parsing paths as defaults for ingestion/data-import flows.

## Progress

- [x] (2026-03-03_21.25.37) Rebuilt this plan as the active working copy, revalidated `docs/PLANS.md` requirements, and confirmed benchmark/LLM/doc context links still match current code paths.
- [x] (2026-03-03_21.17.00) Audited `docs/PLANS.md`, `docs/07-bench/07-bench_README.md`, `docs/10-llm/10-llm_README.md`, `docs/plans/2026-03-03_20.13.22-codexfarm-soft-gating-runtime-outside-span-precision.md`, and current benchmark artifacts under `data/golden/benchmark-vs-golden/2026-03-03_20.49.14/`.
- [x] (2026-03-03_21.17.00) Confirmed which ProFeedback suggestions are already implemented versus still actionable in code.
- [x] (2026-03-03_21.17.00) Replaced freeform `ProFeedback.md` content with this ExecPlan.
- [x] (2026-03-03_21.43.38) Added pass2-ok pass3 utility instrumentation in `cookimport/llm/codex_farm_orchestrator.py` and persisted per-recipe/count-level fields in `llm_manifest`.
- [x] (2026-03-03_21.43.38) Implemented conservative pass2-ok deterministic promotion policy behind `COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK`, with explicit routing reasons/policies.
- [x] (2026-03-03_21.43.38) Surfaced line-role `candidate_labels` in prediction rows and propagated candidate-label metadata through `cookimport/bench/cutdown_export.py`.
- [x] (2026-03-03_21.43.38) Verified upload-bundle diagnostic completion path writes codex statuses when derivation inputs exist; added fixture coverage in `tests/bench/test_benchmark_cutdown_for_external_ai.py`.
- [x] (2026-03-03_22.13.25) Collected Milestone 5 evidence: reran codex + vanilla SeaAndSmoke benchmarks, verified candidate-label and run-diagnostic acceptance in fresh upload bundles, and completed speed-discover/run/compare with PASS verdict.

## Surprises & Discoveries

- Observation: A major part of the original feedback is already implemented.
  Evidence: `cookimport/llm/codex_farm_orchestrator.py` now has `pass2_degradation_severity`, `pass2_promotion_policy`, `pass3_execution_mode`, and `pass3_routing_reason`, including selective deterministic promotion for soft-degraded rows.

- Observation: Upload bundle now includes many fields that the original feedback said were missing.
  Evidence: `scripts/benchmark_cutdown_for_external_ai.py` already implements `prompt_warning_aggregate`, `projection_trace`, `wrong_label_full_context`, `preprocess_trace_failures`, `practical_f1`, `cost_signal`, and `candidate_label_signal` reporting paths.

- Observation: The latest paired run still has strong runtime concentration in pass3 despite prior routing improvements.
  Evidence: `2026-03-03_20.49.14/.../upload_bundle_index.json` call runtime summary shows `total_tokens=1,354,019`, `pass3 total_tokens=842,348`, and `pass3 avg_duration_ms=7726.067`.

- Observation: Candidate-label diagnostics are still effectively unavailable in current run output.
  Evidence: `analysis.line_role_confidence_or_candidates.candidate_label_signal.available=false` with reason `line-role predictions do not include candidate_labels in this run format`.

- Observation: Codex diagnostic bundle rows still show missing statuses for artifacts reviewers asked for.
  Evidence: `run_diagnostics[run_id=codexfarm]` currently reports `prompt_warning_aggregate_status=missing`, `projection_trace_status=missing`, `wrong_label_full_context_status=missing`, `preprocess_trace_failures_status=missing`.

- Observation: The "all missing" codex diagnostic status was stale artifact state, not current script behavior.
  Evidence: Regenerating `upload_bundle_v1` for the same 2026-03-03_20.49.14 SeaAndSmoke session now reports codex diagnostic statuses as `written`.

- Observation: Some remaining quality misses are still deterministic-boundary style errors, not raw model-capability errors.
  Evidence: Latest codex confusion still includes `INSTRUCTION_LINE -> RECIPE_NOTES` (11), `OTHER -> HOWTO_SECTION` (10), `OTHER -> RECIPE_NOTES` (13), and `HOWTO_SECTION -> RECIPE_TITLE` (6).

- Observation: `labelstudio-benchmark` no longer accepts `--compare-vanilla`; paired evidence now requires separate vanilla/codex runs.
  Evidence: Current CLI rejects `--compare-vanilla` with `No such option`.

- Observation: Pass2-ok deterministic skip policy can materially cut pass3 load without harming quality on SeaAndSmoke.
  Evidence: With `COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK=1`, `pass3_inputs` dropped from `17` to `1`, pass3 token share dropped from `0.5518` to `0.3494`, and quality improved (`accuracy 0.7798 -> 0.7950`, `macro_f1 0.5749 -> 0.5938`).

- Observation: Single-run upload bundles can have empty `call_inventory_runtime` even when codex telemetry exists.
  Evidence: `upload_bundle_index.json` for standalone codex eval roots reports `call_count=0`, while `prediction-run/manifest.json` still carries full `llm_codex_farm.process_runs.*.telemetry_report.summary` token/runtime fields.

## Decision Log

- Decision: Do not re-plan already shipped soft-gating/outside-span features.
  Rationale: Those seams already exist in runtime and are documented; duplicating them would create churn instead of value.
  Date/Author: 2026-03-03 / assistant

- Decision: Prioritize pass3 ROI work over broad line-role policy rewrites.
  Rationale: Current codex quality advantage is clear; biggest open cost is pass3 token/runtime concentration.
  Date/Author: 2026-03-03 / assistant

- Decision: Treat candidate-label surfacing as a first-class milestone.
  Rationale: Feedback requested confidence/candidate visibility, and current run format prevents this despite existing analytics hooks.
  Date/Author: 2026-03-03 / assistant

- Decision: Keep upload-bundle-first packaging instead of introducing a mandatory `starter_pack_v2`.
  Rationale: The codebase has standardized on `upload_bundle_v1` as default; adding another default package now would duplicate artifacts and operator flow.
  Date/Author: 2026-03-03 / assistant

- Decision: Include benchmark speed-regression tooling in validation.
  Rationale: This plan touches runtime behavior, and repo guidance requires `bench speed-discover`, `bench speed-run`, and `bench speed-compare`.
  Date/Author: 2026-03-03 / assistant

## Outcomes & Retrospective

Current outcome: Milestones 1-5 are now complete, including runtime/test/docs changes plus fresh benchmark/speed evidence.

Retrospective outcome: the plan goals were met with concrete artifacts: candidate-label diagnostics are available, codex run diagnostics are fully written when derivation inputs exist, skip-policy ROI is measurable, and speed regression gates pass.

## Context and Orientation

The relevant runtime pieces are:

- `cookimport/llm/codex_farm_orchestrator.py`: pass2 degradation classification and pass3 routing. Pass2-soft rows can skip pass3 via deterministic promotion, and pass2-ok rows now emit utility signals with optional deterministic skip guarded by `COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK`.
- `cookimport/parsing/canonical_line_roles.py`: canonical line labeling and codex fallback. Prediction rows now emit `candidate_labels` allowlists in addition to final label/confidence.
- `cookimport/bench/cutdown_export.py`: joins line-role predictions into benchmark line-level rows and propagates `candidate_labels` + `candidate_label_count` for downstream analytics.
- `scripts/benchmark_cutdown_for_external_ai.py`: upload-bundle builder. Existing-output bundle generation now derives codex diagnostic statuses from source run artifacts (and emits derived payload rows) when `need_to_know_summary.json` is absent.

Key baseline artifact for this plan:

- `data/golden/benchmark-vs-golden/2026-03-03_20.49.14/single-offline-benchmark/seaandsmokecutdown/upload_bundle_v1/upload_bundle_index.json`

This baseline confirms codex quality lift remains strong (`strict_accuracy +0.3496`, `macro_f1_excluding_other +0.1810`) while runtime cost remains the largest open issue.

## Milestones

### Milestone 1: Pass3 utility instrumentation for pass2-ok rows

Add additive instrumentation in `codex_farm_orchestrator.py` that scores likely pass3 utility before pass3 is called for pass2-ok rows. Keep behavior unchanged at first; this is a measurement milestone. Persist per-recipe utility signals to `llm_manifest` so skip-policy design is data-backed.

Acceptance for this milestone: a codex run produces new per-recipe and aggregate utility fields in `llm_manifest`, and tests prove no behavior change when skip policy is disabled.

### Milestone 2: Conservative pass3 skip policy for high-confidence deterministic promotions

Use Milestone 1 signals to introduce an explicit, conservative deterministic promotion branch for selected pass2-ok rows. Keep this policy narrow, audit-friendly, and reversible via settings/env guard. Persist routing reasons so every deterministic skip is explainable in artifacts.

Acceptance for this milestone: pass3 input count and pass3 token share are measurably lower on paired rerun, while codex strict/macro metrics stay within agreed regression bounds.

### Milestone 3: Candidate-label signal availability in line-role artifacts

Propagate line-role candidate-label allowlists into prediction records and joined benchmark rows, then wire upload-bundle analysis to consume them. This turns `candidate_label_signal` from unavailable to usable and unlocks confidence-aware triage without new LLM calls.

Acceptance for this milestone: upload bundle reports `candidate_label_signal.available=true` with non-zero `rows_with_candidate_labels` for codex line-role runs.

### Milestone 4: Upload-bundle diagnostic completeness for codex runs

Make upload-bundle generation fill diagnostic artifacts/statuses when source artifacts already exist in the run root (for example from codex full prompt logs and evaluation rows). Preserve existing behavior for runs where source data is genuinely unavailable.

Acceptance for this milestone: codex row in `run_diagnostics` no longer reports all four requested diagnostics as `missing` when the source run contains enough data to derive them.

### Milestone 5: Validation, docs updates, and comparison evidence

Add/adjust tests in llm/parsing/bench suites, run paired benchmark with fixed codex model/effort, and run required speed baseline-vs-candidate checks. Update docs sections that describe these contracts (`docs/07-bench/07-bench_README.md`, `docs/10-llm/10-llm_README.md`, and any touched module readmes).

Acceptance for this milestone: tests pass, benchmark comparison shows maintained quality, and speed comparison does not fail runtime regression gates.

## Plan of Work

Start with additive instrumentation in orchestrator so skip decisions are based on observed utility rather than guesswork. Once metrics are visible, implement a narrow deterministic skip policy for pass2-ok rows only when deterministic promotion risk is low and evidence quality is high.

In parallel, extend line-role prediction payloads to carry candidate-label metadata. Then wire this metadata through cutdown export and upload-bundle summarizers so the existing `candidate_label_signal` analysis path has real data.

After metadata work, harden upload-bundle diagnostics by deriving missing artifacts from available run data instead of reporting blanket `missing` statuses. Keep behavior explicit when data is unavailable.

Finish by running targeted tests, a paired benchmark rerun, and speed compare. Update living-plan sections and docs as results are collected.

## Concrete Steps

Run from repository root:

1. Confirm current seams and baseline metrics.
   - `rg -n "_should_run_pass3_llm|pass2_degradation_severity|pass3_execution_mode|pass3_routing_reason" cookimport/llm/codex_farm_orchestrator.py`
   - `rg -n "candidate_label_signal|run_diagnostics|prompt_warning_aggregate|projection_trace|wrong_label_full_context|preprocess_trace_failures" scripts/benchmark_cutdown_for_external_ai.py`
   - `jq '.analysis.call_inventory_runtime.summary,.analysis.line_role_confidence_or_candidates.candidate_label_signal,.run_diagnostics' data/golden/benchmark-vs-golden/2026-03-03_20.49.14/single-offline-benchmark/seaandsmokecutdown/upload_bundle_v1/upload_bundle_index.json`

2. Implement Milestone 1 and 2 in orchestrator with tests.
   - Edit `cookimport/llm/codex_farm_orchestrator.py`.
   - Edit/add tests in `tests/llm/test_codex_farm_orchestrator.py`.

3. Implement Milestone 3 payload propagation.
   - Edit `cookimport/parsing/canonical_line_roles.py`.
   - Edit `cookimport/bench/cutdown_export.py`.
   - Edit/add tests in `tests/parsing/test_canonical_line_roles.py` and `tests/bench/test_benchmark_cutdown_for_external_ai.py`.

4. Implement Milestone 4 diagnostic completeness.
   - Edit `scripts/benchmark_cutdown_for_external_ai.py`.
   - Update/add tests in `tests/bench/test_benchmark_cutdown_for_external_ai.py`.

5. Run targeted tests inside project venv.
   - `. .venv/bin/activate && (python -m pip --version || (curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && python /tmp/get-pip.py))`
   - `. .venv/bin/activate && python -m pip install -e .[dev]`
   - `. .venv/bin/activate && python -m pytest tests/llm/test_codex_farm_orchestrator.py -q`
   - `. .venv/bin/activate && python -m pytest tests/parsing/test_canonical_line_roles.py -q`
   - `. .venv/bin/activate && python -m pytest tests/bench/test_benchmark_cutdown_for_external_ai.py -q`

6. Run paired benchmark evidence with fixed model/effort and collect candidate artifacts.
   - Vanilla run:
     `cookimport labelstudio-benchmark --source-file data/input/SeaAndSmokeCUTDOWN.epub --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl --eval-mode canonical-text --no-upload --no-write-labelstudio-tasks --workers 1 --epub-split-workers 1 --eval-output-dir data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_seaandsmoke-profeedback-vanilla`
   - Codex run (default pass2-ok skip disabled):
     `cookimport labelstudio-benchmark --source-file data/input/SeaAndSmokeCUTDOWN.epub --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl --eval-mode canonical-text --no-upload --no-write-labelstudio-tasks --workers 1 --epub-split-workers 1 --llm-recipe-pipeline codex-farm-3pass-v1 --atomic-block-splitter atomic-v1 --line-role-pipeline codex-line-role-v1 --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --eval-output-dir data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_seaandsmoke-profeedback-codex`
   - Codex ROI run (pass2-ok deterministic skip enabled):
     `COOKIMPORT_CODEX_FARM_PASS3_SKIP_PASS2_OK=1 cookimport labelstudio-benchmark --source-file data/input/SeaAndSmokeCUTDOWN.epub --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl --eval-mode canonical-text --no-upload --no-write-labelstudio-tasks --workers 1 --epub-split-workers 1 --llm-recipe-pipeline codex-farm-3pass-v1 --atomic-block-splitter atomic-v1 --line-role-pipeline codex-line-role-v1 --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --eval-output-dir data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_seaandsmoke-profeedback-codex-pass3skip`

7. Run required speed regression workflow.
   - `cookimport bench speed-discover --gold-root data/golden/pulled-from-labelstudio --input-root data/input --out data/golden/bench/speed/discovered/<YYYY-MM-DD_HH.MM.SS>_profeedback_execplan_suite.json`
   - Baseline run: `cookimport bench speed-run --suite <suite_json> --include-codex-farm --speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --out-dir data/golden/bench/speed/runs`
   - Candidate run: same command after changes.
   - Compare: `cookimport bench speed-compare --baseline <baseline_run_dir> --candidate <candidate_run_dir> --out-dir data/golden/bench/speed/comparisons`

## Validation and Acceptance

All conditions below must be met:

- Quality preservation:
  - Candidate codex run keeps `strict_accuracy` and `macro_f1_excluding_other` within `-0.01` absolute of baseline codex values from `2026-03-03_20.49.14`.
  - Codex remains above vanilla on both metrics in the paired rerun.

- Runtime ROI:
  - `llm_manifest.counts.pass3_inputs` is lower than or equal to baseline with a clear reduction target (preferably lower).
  - Upload bundle call inventory shows reduced pass3 token share versus baseline.

- Diagnostics completeness:
  - Upload bundle reports `candidate_label_signal.available=true` and non-zero candidate rows for codex line-role runs.
  - Codex `run_diagnostics` no longer reports all four requested diagnostics as missing when derivation inputs exist.

- Regression safety:
  - Targeted pytest suites pass in `.venv`.
  - `bench speed-compare` does not fail configured regression gates.

Evidence snapshot (2026-03-03_22.13.25):
- Quality preservation:
  - Codex (skip off): `accuracy=0.7798`, `macro_f1=0.5749`.
  - Codex (skip on): `accuracy=0.7950`, `macro_f1=0.5938` (above skip-off and above baseline codex `2026-03-03_20.49.14`).
  - Vanilla paired run: `accuracy=0.3966`, `macro_f1=0.3405` (codex remains clearly above vanilla).
- Runtime ROI:
  - Skip-off codex run: `pass3_inputs=17`, `pass3_token_share=0.5518`.
  - Skip-on codex run: `pass3_inputs=1`, `pass3_token_share=0.3494`.
- Diagnostics completeness:
  - `candidate_label_signal.available=true` with `rows_with_candidate_labels=699` on codex upload bundles.
  - `run_diagnostics` statuses are all `written` (`prompt_warning_aggregate`, `projection_trace`, `wrong_label_full_context`, `preprocess_trace_failures`) on fresh codex upload bundles.
- Regression safety:
  - speed compare verdict `PASS` at `data/golden/bench/speed/comparisons/2026-03-03_22.09.21/`.

## Idempotence and Recovery

All edits are additive and repeatable. Benchmark/speed outputs are timestamped and can be rerun safely with new roots. If skip policy hurts quality, disable only the Milestone 2 routing branch while keeping Milestone 1 instrumentation and diagnostics improvements for continued analysis.

## Artifacts and Notes

Primary evidence artifacts for this plan:

- Baseline upload bundle index:
  - `data/golden/benchmark-vs-golden/2026-03-03_20.49.14/single-offline-benchmark/seaandsmokecutdown/upload_bundle_v1/upload_bundle_index.json`
- Vanilla paired rerun root:
  - `data/golden/benchmark-vs-golden/2026-03-03_21.55.20_seaandsmoke-profeedback-vanilla/`
- Codex paired rerun root (skip off):
  - `data/golden/benchmark-vs-golden/2026-03-03_22.04.09_seaandsmoke-profeedback-codex2/`
- Codex ROI rerun root (skip on):
  - `data/golden/benchmark-vs-golden/2026-03-03_22.09.35_seaandsmoke-profeedback-codex-pass3skip/`
- Speed suite discovery:
  - `data/golden/bench/speed/discovered/2026-03-03_22.08.36_profeedback_execplan_suite.json`
- Speed baseline/candidate runs:
  - `data/golden/bench/speed/runs/2026-03-03_22.09.01/`
  - `data/golden/bench/speed/runs/2026-03-03_22.09.09/`
- Speed comparison output:
  - `data/golden/bench/speed/comparisons/2026-03-03_22.09.21/`

## Interfaces and Dependencies

No new third-party dependencies are required.

Expected additive interface changes:

- `llm_manifest.recipes[*]` and `llm_manifest.counts` gain pass3-utility instrumentation fields for pass2-ok routing analysis.
- `line-role-pipeline/line_role_predictions.jsonl` gains `candidate_labels` (and optionally related candidate metadata) without breaking existing consumers.
- Upload-bundle index contracts remain backward compatible but include improved candidate-label and diagnostic-status population when inputs are present.

---

Plan revision note (2026-03-03_21.17.00): Converted `docs/plans/ProFeedback.md` from unstructured feedback text into a full ExecPlan after auditing current code and benchmark artifacts so only still-valuable suggestions remain in scope.
Plan revision note (2026-03-03_21.25.37): Rebuilt and revalidated this file as the active working copy, updated summary/progress wording, and confirmed referenced docs/contracts still align with current benchmark and codex-farm surfaces.
Plan revision note (2026-03-03_21.43.38): Implemented runtime/test/docs changes for pass2-ok utility/skip policy, candidate-label propagation, and upload-bundle diagnostic coverage; left benchmark/speed rerun evidence as remaining validation work.
Plan revision note (2026-03-03_22.13.25): Completed benchmark and speed evidence collection, updated acceptance with concrete metrics/artifacts, and refreshed stale benchmark command examples.
