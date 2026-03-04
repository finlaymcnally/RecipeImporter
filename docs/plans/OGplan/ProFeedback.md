---
summary: "ExecPlan that converts ProFeedback into a codebase-grounded follow-up focused on pass3 ROI, line-role diagnostics, and upload-bundle completeness."
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

- [x] (2026-03-03_21.17.00) Audited `docs/PLANS.md`, `docs/07-bench/07-bench_README.md`, `docs/10-llm/10-llm_README.md`, `docs/plans/2026-03-03_20.13.22-codexfarm-soft-gating-runtime-outside-span-precision.md`, and current benchmark artifacts under `data/golden/benchmark-vs-golden/2026-03-03_20.49.14/`.
- [x] (2026-03-03_21.17.00) Confirmed which ProFeedback suggestions are already implemented versus still actionable in code.
- [x] (2026-03-03_21.17.00) Replaced freeform `ProFeedback.md` content with this ExecPlan.
- [ ] Add pass3 utility instrumentation and gated skip-policy prototype for pass2-ok rows in `cookimport/llm/codex_farm_orchestrator.py`.
- [ ] Implement conservative pass3 skip policy for high-confidence deterministic promotions and propagate routing metadata.
- [ ] Surface line-role `candidate_labels` through prediction artifacts and upload-bundle analytics.
- [ ] Generate/fill missing upload-bundle diagnostics (`prompt_warning_aggregate`, `projection_trace`, `wrong_label_full_context`, `preprocess_trace_failures`) when source artifacts are available.
- [ ] Add/extend tests and rerun paired benchmark plus speed regression checks.

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

- Observation: Some remaining quality misses are still deterministic-boundary style errors, not raw model-capability errors.
  Evidence: Latest codex confusion still includes `INSTRUCTION_LINE -> RECIPE_NOTES` (11), `OTHER -> HOWTO_SECTION` (10), `OTHER -> RECIPE_NOTES` (13), and `HOWTO_SECTION -> RECIPE_TITLE` (6).

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

Current outcome: `ProFeedback.md` has been converted from unstructured narrative into an executable, codebase-audited plan.

Remaining outcome target: ship only the still-valuable feedback items and verify they improve runtime/diagnostic usefulness without eroding codex quality gains.

## Context and Orientation

The relevant runtime pieces are:

- `cookimport/llm/codex_farm_orchestrator.py`: pass2 degradation classification and pass3 routing. Right now pass2-degraded soft rows can skip pass3, but pass2-ok rows always route to pass3.
- `cookimport/parsing/canonical_line_roles.py`: canonical line labeling and codex fallback. The prediction model currently stores final labels/confidence but not the per-line candidate-label allowlist in emitted prediction records.
- `cookimport/bench/cutdown_export.py`: joins line-role predictions into benchmark line-level rows. This is where candidate-label metadata can be propagated for downstream analytics.
- `scripts/benchmark_cutdown_for_external_ai.py`: upload-bundle builder. It has helper logic for the diagnostics reviewers requested, but current single-offline outputs still show those statuses as missing in `run_diagnostics`.

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

6. Run paired benchmark with fixed model/effort and collect candidate artifacts.
   - `cookimport labelstudio-benchmark --source-file data/input/SeaAndSmokeCUTDOWN.epub --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl --eval-mode canonical-text --no-upload --no-write-labelstudio-tasks --workers 1 --epub-split-workers 1 --llm-recipe-pipeline codex-farm-3pass-v1 --atomic-block-splitter atomic-v1 --line-role-pipeline codex-line-role-v1 --compare-vanilla --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --eval-output-dir data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_seaandsmoke-profeedback-execplan`

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

## Idempotence and Recovery

All edits are additive and repeatable. Benchmark/speed outputs are timestamped and can be rerun safely with new roots. If skip policy hurts quality, disable only the Milestone 2 routing branch while keeping Milestone 1 instrumentation and diagnostics improvements for continued analysis.

## Artifacts and Notes

Primary evidence artifacts for this plan:

- Baseline upload bundle index:
  - `data/golden/benchmark-vs-golden/2026-03-03_20.49.14/single-offline-benchmark/seaandsmokecutdown/upload_bundle_v1/upload_bundle_index.json`
- Candidate paired rerun root:
  - `data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_seaandsmoke-profeedback-execplan/`
- Speed comparison output:
  - `data/golden/bench/speed/comparisons/<YYYY-MM-DD_HH.MM.SS>/`

## Interfaces and Dependencies

No new third-party dependencies are required.

Expected additive interface changes:

- `llm_manifest.recipes[*]` and `llm_manifest.counts` gain pass3-utility instrumentation fields for pass2-ok routing analysis.
- `line-role-pipeline/line_role_predictions.jsonl` gains `candidate_labels` (and optionally related candidate metadata) without breaking existing consumers.
- Upload-bundle index contracts remain backward compatible but include improved candidate-label and diagnostic-status population when inputs are present.

---

Plan revision note (2026-03-03_21.17.00): Converted `docs/plans/ProFeedback.md` from unstructured feedback text into a full ExecPlan after auditing current code and benchmark artifacts so only still-valuable suggestions remain in scope.
