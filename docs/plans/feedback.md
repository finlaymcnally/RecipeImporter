---
summary: "ExecPlan to convert feedback findings into deterministic line-role hardening, selective escalation, and upload-bundle starter-pack improvements."
read_when:
  - "When implementing the OG feedback recommendations documented in docs/plans/OGplan/feedbackOG.md."
  - "When improving codex-vs-vanilla benchmark triage artifacts without using CSV starter outputs."
---

# Execute OG feedback as deterministic line-role and upload-bundle hardening

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `docs/PLANS.md` from the repository root.

## Purpose / Big Picture

The original OG feedback notes captured useful benchmark guidance, but they were not organized as a reliable execution workflow. After this plan is implemented, a single operator should be able to run one paired canonical-text benchmark and observe three concrete outcomes: fewer deterministic line-role boundary errors (especially `YIELD_LINE`, header confusion, and ingredient fragments), better pass3 cost control through selective escalation (instead of broad model escalation), and a starter pack that is first-pass triage friendly without CSV artifacts.

User-visible proof lives in the benchmark artifacts under `data/golden/benchmark-vs-golden/<timestamp>/...`: improved confusion families in `eval_report.json`, explicit selective-routing/runtime evidence in manifests/upload bundles, and starter-pack files that are JSON/JSONL/Markdown only.

Scope guard: this plan is benchmark and diagnostics work only. It must not enable LLM parsing/cleaning as default behavior for ingestion/data import flows.

## Progress

- [x] (2026-03-03_23.20.00) Replaced freeform feedback narrative with a self-contained ExecPlan structure aligned to `docs/PLANS.md`.
- [x] (2026-03-03_23.20.00) Re-read `docs/PLANS.md`, `docs/07-bench/07-bench_README.md`, and `docs/10-llm/10-llm_README.md`; confirmed current seams for line-role gates, pass3 routing, and upload-bundle starter artifacts.
- [x] (2026-03-03_23.40.12) Captured Milestone 1 baseline evidence in `docs/understandings/2026-03-03_23.40.12-feedback-exec-baseline.md` (fresh vanilla run, codex auth-failed attempt, paired successful codex reference, confusion-family counts, pass3 token-share/runtime, starter-pack inventory).
- [x] (2026-03-03_23.37.00) Verified deterministic line-role guardrails and selective pass3 routing seams are already active in current code and protected by passing targeted tests (`tests/parsing/test_canonical_line_roles.py`, `tests/llm/test_codex_farm_orchestrator.py`).
- [x] (2026-03-03_23.39.00) Replaced starter-pack CSV-first triage contract with JSONL-first artifacts, added first-class blame/config/low-confidence/baseline-parity files, and retained legacy CSV compatibility loading for existing outputs.
- [x] (2026-03-04_00.14.57) Re-ran benchmark and speed validation: fresh vanilla benchmark (`2026-03-04_00.08.07_feedbackexec_vanilla`), fresh codex benchmark path (`2026-03-04_00.10.29_feedbackexec_codex_fallback` with `--codex-farm-failure-mode fallback`), and full speed-discover/run/run/compare flow (`2026-03-04_00.09.35_feedbackexec_suite.json`, runs `2026-03-04_00.09.49` vs `2026-03-04_00.09.59`, compare `2026-03-04_00.10.12` PASS).

## Surprises & Discoveries

- Observation: Several feedback recommendations from earlier rounds are already partially implemented.
  Evidence: `cookimport/parsing/canonical_line_roles.py` already emits `candidate_labels`, and `cookimport/llm/codex_farm_orchestrator.py` already records `pass3_utility_signal` and routing fields.

- Observation: Starter-pack triage was CSV-first before this execution pass; this was the primary Milestone-4 contract gap.
  Evidence: pre-change `scripts/benchmark_cutdown_for_external_ai.py` set `STARTER_PACK_TRIAGE_FILE_NAME = "01_recipe_triage.csv"` and wrote it via `csv.DictWriter`; current code now writes `01_recipe_triage.jsonl`.

- Observation: Upload-bundle existing-output readers were already CSV-aware, so migration needed explicit JSONL-first loading with CSV fallback.
  Evidence: `_upload_bundle_load_recipe_triage_rows(...)` now resolves `01_recipe_triage.jsonl` first and falls back to legacy `01_recipe_triage.csv`.

- Observation: Milestone-4 helper builders for triage packet, net-error blame, config metadata, and low-confidence packets already existed but were only guaranteed via derived upload-bundle payload rows.
  Evidence: helper functions `_upload_bundle_build_triage_packet_rows(...)`, `_upload_bundle_build_net_error_blame_summary(...)`, `_upload_bundle_build_config_version_metadata(...)`, and `_upload_bundle_build_low_confidence_changed_lines_packet(...)` were present before this update.

- Observation: Fresh codex baseline command failed in this environment because codex auth/websocket access was unavailable.
  Evidence: benchmark run `2026-03-03_23.28.30_feedbackexec_codex` failed with pass1 errors and `HTTP 403 Forbidden` websocket/auth messages from codex CLI telemetry.

- Observation: In this cycle, codex-farm pass1 still emitted widespread websocket/auth failures; using `--codex-farm-failure-mode fallback` allowed a fresh codex benchmark root to complete for artifact-level validation, while direct pass-level token/runtime telemetry remained unavailable.
  Evidence: failed run `2026-03-04_00.08.27_feedbackexec_codex` exited on pass1 auth errors; fallback run `2026-03-04_00.10.29_feedbackexec_codex_fallback` completed with upload bundle + line-role diagnostics, and `analysis.call_inventory_runtime.summary` reports `call_count=0`.

## Decision Log

- Decision: Keep this plan focused on deterministic policy and packaging surfaces before any broad model/prompt upgrade.
  Rationale: Current evidence points to boundary/routing issues with strong deterministic levers and better ROI than global escalation.
  Date/Author: 2026-03-03 / assistant

- Decision: Treat CSV removal from starter-pack triage as a first-class requirement in this plan.
  Rationale: Operator workflow explicitly rejects CSV for upload/review flow; this is a usability blocker, not optional polish.
  Date/Author: 2026-03-03 / assistant

- Decision: Require paired benchmark and speed-regression evidence for acceptance.
  Rationale: This plan touches both quality behavior and runtime cost surfaces.
  Date/Author: 2026-03-03 / assistant

- Decision: Use the latest successful same-source codex canonical run as the Milestone-1 codex reference when fresh codex execution fails due auth.
  Rationale: preserves paired baseline evidence continuity while documenting the env/auth blocker explicitly.
  Date/Author: 2026-03-03 / assistant

## Outcomes & Retrospective

Implemented state: starter-pack/upload-bundle contract now ships JSONL-first triage (`01_recipe_triage.jsonl`) plus first-class triage packet, net-error blame summary, config/version metadata, low-confidence changed-lines packet, and baseline-trace parity file; upload-bundle locators/default views resolve these directly, and legacy CSV roots remain readable via compatibility fallback.

Validation completed: targeted parsing/llm/bench suites passed in `.venv`; fresh benchmark roots were produced at `data/golden/benchmark-vs-golden/2026-03-04_00.08.07_feedbackexec_vanilla` and `data/golden/benchmark-vs-golden/2026-03-04_00.10.29_feedbackexec_codex_fallback`; speed regression comparison passed at `data/golden/bench/speed/comparisons/2026-03-04_00.10.12`.

Measured outcomes from fresh roots: overall line accuracy improved from `0.3966` (vanilla) to `0.7849` (codex-fallback root with deterministic fallback safety); macro F1 excluding OTHER improved from `0.3405` to `0.5903`; line-role diagnostics reported zero `TIME_LINE` predictions with active yield sanitization tags (`sanitized_yield_to_instruction`, `sanitized_yield_non_header`).

Residual risk: direct codex pass token/runtime share evidence is still constrained by external auth/websocket failures (`HTTP 403 Forbidden`), so upload-bundle runtime summary for the fresh codex-fallback root reports no call telemetry.

## Context and Orientation

This plan touches three connected surfaces.

First is deterministic line-role behavior in `cookimport/parsing/canonical_line_roles.py`. In this repository, a "line role" is the label assigned to each canonical text line (for example `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `RECIPE_TITLE`, `RECIPE_NOTES`, `OTHER`). This is where yield/header/title/ingredient boundary rules and candidate-label allowlists are determined.

Second is codex pass routing in `cookimport/llm/codex_farm_orchestrator.py`. A "pass3 routing policy" is the rule that decides whether a recipe gets a pass3 LLM call or deterministic promotion/fallback. This is where pass3 utility signals, routing reasons, and pass-level token/runtime counters are emitted.

Third is benchmark packaging in `scripts/benchmark_cutdown_for_external_ai.py`. "Starter pack" means the compact triage artifact set under `starter_pack_v1/`. "Upload bundle" means the consolidated three-file bundle under `upload_bundle_v1/`. This plan migrated starter-pack triage to a JSONL-first contract while preserving compatibility loading for legacy CSV roots.

Key tests and safety nets are:

- `tests/parsing/test_canonical_line_roles.py`
- `tests/llm/test_codex_farm_orchestrator.py`
- `tests/bench/test_benchmark_cutdown_for_external_ai.py`
- `tests/bench/test_cutdown_export_consistency.py`

## Milestones

### Milestone 1: Freeze a feedback-aligned baseline snapshot

Before changing behavior, capture one paired baseline (vanilla and codex) with current code and summarize the exact failure families this plan targets: `OTHER/RECIPE_NOTES/KNOWLEDGE` boundary confusion, false-positive `TIME_LINE`, title-vs-howto ambiguity, and ingredient fragment drops. Capture pass3 token-share/runtime and starter-pack artifact inventory in the same snapshot so ROI is measured from one source of truth.

Acceptance for Milestone 1 is a short evidence note under `docs/understandings/` plus references to the baseline run directories and relevant artifact keys.

### Milestone 2: Deterministic line-role guardrails and neighbor rescue

Implement tight deterministic post-classification gates in `canonical_line_roles.py` for the known error families:

- guard `YIELD_LINE` behind strict lexical patterns and short-header shape;
- demote unsupported `TIME_LINE` predictions to the appropriate structural fallback (normally `INSTRUCTION_LINE`);
- constrain `HOWTO_SECTION` and `RECIPE_TITLE` confusion using short-header plus next-line evidence;
- add ingredient-neighbor rescue for short ingredient fragments and split quantity/name patterns when local context is ingredient-dominant;
- add a narrative-zone bias that keeps full-sentence prose in `OTHER` or `RECIPE_NOTES` unless stronger structural evidence exists.

Acceptance for Milestone 2 is passing parsing tests plus measurable reduction in targeted confusion families on a controlled paired rerun.

### Milestone 3: Selective escalation and pass3 context discipline

Use existing candidate-label and low-confidence signals to refine routing policy in `codex_farm_orchestrator.py` so expensive escalation targets the risky minority instead of broad pass3 invocation. Keep routing reasons explicit and auditable in manifests. If pass3 context is still oversized, constrain inputs to recipe-relevant windows and capture before/after pass-level token share.

Acceptance for Milestone 3 is lower pass3 share/runtime versus baseline with no unacceptable quality regression.

### Milestone 4: Starter-pack format and triage-surface upgrade (non-CSV)

Update `benchmark_cutdown_for_external_ai.py` starter-pack artifacts so first-pass triage includes:

- non-CSV triage main table (JSONL preferred),
- one blame-summary artifact that attributes net error deltas by source family (line-role, pass2 extraction, pass3 mapping, routing/fallback),
- explicit config/version metadata at top-level summary,
- low-confidence changed-lines packet as a first-class artifact,
- baseline-trace parity cues for codex and vanilla,
- alias-equivalent artifact dedupe (canonical file plus alias map).

Maintain backward-safe loading for existing outputs while preferring the new non-CSV contract.

Acceptance for Milestone 4 is starter-pack and upload-bundle generation succeeding on fresh output roots with no CSV dependency.

### Milestone 5: Validation, docs, and closeout

Run targeted tests in `.venv`, run paired benchmark evidence, run required speed regression checks, and update docs that describe these contracts. Update this ExecPlan sections (`Progress`, `Surprises & Discoveries`, `Decision Log`, `Outcomes & Retrospective`) so a new operator can continue from this file alone.

Acceptance for Milestone 5 is passing tests, acceptable quality/runtime evidence, and docs that match shipped behavior.

## Plan of Work

Start with baseline capture and evidence ranking, because this narrows changes to specific confusion families and prevents broad rule churn. Then implement deterministic line-role gates and neighbor-based ingredient rescue in one small pass with tests. Next, tune selective escalation and pass3 context only after deterministic behavior stabilizes, so runtime changes are measured against a consistent quality baseline.

After behavior changes, migrate starter-pack triage from CSV to JSONL and add the requested blame/metadata/low-confidence surfaces while retaining upload-bundle compatibility for existing roots. Finish with benchmark and speed validation, then update documentation and this plan with final data.

## Concrete Steps

Run commands from repository root:

    cd /home/mcnal/projects/recipeimport

Prepare `.venv` before test execution:

    . .venv/bin/activate
    python -m pip --version || (curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && python /tmp/get-pip.py)
    python -m pip install -e .[dev]

Baseline inspection and seam confirmation:

    rg -n "YIELD_LINE|HOWTO_SECTION|RECIPE_TITLE|TIME_LINE|ingredient_like|candidate_labels" cookimport/parsing/canonical_line_roles.py
    rg -n "pass3_utility_signal|pass3_routing_reason|pass3_execution_mode|pass3_pass2_ok" cookimport/llm/codex_farm_orchestrator.py
    rg -n "STARTER_PACK_TRIAGE_FILE_NAME|DictWriter|_upload_bundle_load_csv_rows|candidate_label_signal|run_diagnostics" scripts/benchmark_cutdown_for_external_ai.py

Implement milestones 2-4 in these files:

- `cookimport/parsing/canonical_line_roles.py`
- `cookimport/llm/codex_farm_orchestrator.py`
- `scripts/benchmark_cutdown_for_external_ai.py`
- corresponding tests under `tests/parsing/`, `tests/llm/`, and `tests/bench/`.

Run targeted tests:

    . .venv/bin/activate && python -m pytest tests/parsing/test_canonical_line_roles.py -q
    . .venv/bin/activate && python -m pytest tests/llm/test_codex_farm_orchestrator.py -q
    . .venv/bin/activate && python -m pytest tests/bench/test_benchmark_cutdown_for_external_ai.py -q
    . .venv/bin/activate && python -m pytest tests/bench/test_cutdown_export_consistency.py -q

Run paired benchmark evidence (example source from existing feedback workflow):

    cookimport labelstudio-benchmark --source-file data/input/SeaAndSmokeCUTDOWN.epub --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl --eval-mode canonical-text --no-upload --no-write-labelstudio-tasks --workers 1 --epub-split-workers 1 --eval-output-dir data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_feedbackexec_vanilla

    cookimport labelstudio-benchmark --source-file data/input/SeaAndSmokeCUTDOWN.epub --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl --eval-mode canonical-text --no-upload --no-write-labelstudio-tasks --workers 1 --epub-split-workers 1 --llm-recipe-pipeline codex-farm-3pass-v1 --atomic-block-splitter atomic-v1 --line-role-pipeline codex-line-role-v1 --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --eval-output-dir data/golden/benchmark-vs-golden/<YYYY-MM-DD_HH.MM.SS>_feedbackexec_codex

Run required speed-regression flow if runtime behavior changed:

    cookimport bench speed-discover --gold-root data/golden/pulled-from-labelstudio --input-root data/input --out data/golden/bench/speed/discovered/<YYYY-MM-DD_HH.MM.SS>_feedbackexec_suite.json
    cookimport bench speed-run --suite <suite_json> --include-codex-farm --speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --out-dir data/golden/bench/speed/runs
    cookimport bench speed-run --suite <suite_json> --include-codex-farm --speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION --codex-farm-model gpt-5.3-codex-spark --codex-farm-thinking-effort low --out-dir data/golden/bench/speed/runs
    cookimport bench speed-compare --baseline <baseline_run_dir> --candidate <candidate_run_dir> --out-dir data/golden/bench/speed/comparisons

## Validation and Acceptance

The plan is complete only when all conditions hold:

- Quality behavior: targeted confusion families are reduced on the paired rerun (especially false-positive `TIME_LINE`, `OTHER/RECIPE_NOTES/KNOWLEDGE` boundary errors, and title-vs-howto errors) without introducing broad regressions.
- Runtime behavior: pass3 share/runtime is equal or better than baseline for comparable codex runs, with explicit routing evidence in manifests.
- Artifact behavior: starter-pack triage output and upload-bundle ingestion work without CSV dependency for new runs; old roots remain readable.
- Test safety: targeted parsing/llm/bench suites pass in `.venv`.
- Speed safety: if runtime changed, `bench speed-compare` passes configured regression gates.

## Idempotence and Recovery

All commands are safe to rerun when each benchmark output directory uses a fresh timestamp in the required format `YYYY-MM-DD_HH.MM.SS`. If a specific routing or gate tweak hurts quality, disable that narrow change and rerun the same benchmark pair with a new timestamped output directory for direct before/after comparison. Keep older run directories for auditability; do not overwrite or delete prior evidence during active iteration.

## Artifacts and Notes

Primary artifacts to track through this plan are:

- `eval_report.json` and `line-role-pipeline/joined_line_table.jsonl` in benchmark roots for quality/confusion evidence.
- `prediction-run/manifest.json` and upload-bundle `upload_bundle_index.json` for pass-level runtime/token evidence.
- `starter_pack_v1/` inventory and `upload_bundle_v1/*` for packaging/triage contract verification.
- `docs/understandings/<timestamp>-feedback-exec-baseline.md` and later update notes for investigation continuity.

## Interfaces and Dependencies

No new third-party dependency is required.

Expected interface changes are additive and localized:

- deterministic line-role rule helpers and post-label sanitizers in `cookimport/parsing/canonical_line_roles.py`,
- pass3 routing policy thresholds/guards in `cookimport/llm/codex_farm_orchestrator.py`,
- starter-pack artifact naming/writer/loader contracts in `scripts/benchmark_cutdown_for_external_ai.py` plus related tests.

Any renamed starter-pack artifact must include compatibility loading in upload-bundle builders so existing output roots remain usable.

## Revision Note

(2026-03-03_23.20.00) Replaced freeform feedback commentary with a full ExecPlan so implementation can proceed from one self-contained document with milestones, acceptance criteria, and concrete commands.

(2026-03-03_23.20.38) Rebuilt this plan as the canonical `docs/plans/feedback.md` target and corrected stale references that pointed to a non-existent `docs/plans/OGplan/feedback.md` path.

(2026-03-03_23.40.12) Added Milestone-1 baseline evidence links and confusion/runtime inventory notes; documented codex auth failure blocker and fallback codex reference pairing.

(2026-03-03_23.41.00) Marked Milestone-4 contract work implemented: starter-pack JSONL triage, first-class blame/config/low-confidence/parity artifacts, upload-bundle locator updates, legacy CSV compatibility loading, and targeted test validation.

(2026-03-04_00.14.57) Closed Milestone-5 validation with fresh benchmark + speed artifacts, recorded final metrics, and documented codex auth-constrained runtime telemetry caveat for this environment.
