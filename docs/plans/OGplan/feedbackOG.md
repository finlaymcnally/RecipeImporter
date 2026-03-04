---
summary: "ExecPlan to convert feedback findings into deterministic line-role hardening, selective escalation, and upload-bundle starter-pack improvements."
read_when:
  - "When implementing the OG feedback recommendations in docs/plans/OGplan/feedback.md."
  - "When improving codex-vs-vanilla benchmark triage artifacts without using CSV starter outputs."
---

# Execute OG feedback as deterministic line-role and upload-bundle hardening

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `docs/PLANS.md` from the repository root.

## Purpose / Big Picture

The original `feedback.md` captured useful benchmark guidance, but it was freeform and not executable. After this plan is implemented, a single operator should be able to run one paired canonical-text benchmark and observe three concrete outcomes: fewer deterministic line-role boundary errors (especially `YIELD_LINE`, header confusion, and ingredient fragments), better pass3 cost control through selective escalation (instead of broad model escalation), and a starter pack that is first-pass triage friendly without CSV artifacts.

User-visible proof lives in the benchmark artifacts under `data/golden/benchmark-vs-golden/<timestamp>/...`: improved confusion families in `eval_report.json`, explicit selective-routing/runtime evidence in manifests/upload bundles, and starter-pack files that are JSON/JSONL/Markdown only.

Scope guard: this plan is benchmark and diagnostics work only. It must not enable LLM parsing/cleaning as default behavior for ingestion/data import flows.

## Progress

- [x] (2026-03-03_23.20.00) Replaced freeform feedback narrative with a self-contained ExecPlan structure aligned to `docs/PLANS.md`.
- [x] (2026-03-03_23.20.00) Re-read `docs/PLANS.md`, `docs/07-bench/07-bench_README.md`, and `docs/10-llm/10-llm_README.md`; confirmed current seams for line-role gates, pass3 routing, and upload-bundle starter artifacts.
- [ ] Establish baseline evidence snapshot for the next implementation cycle (paired metrics, confusion families, pass3 token share, starter-pack artifact inventory).
- [ ] Implement deterministic line-role gate refinements for yield/header/ingredient narrative-boundary cases with tests.
- [ ] Tighten selective escalation/routing policy and pass3 context controls with manifest/runtime evidence.
- [ ] Replace starter-pack triage CSV with non-CSV artifact format and add requested triage/blame surfaces.
- [ ] Re-run benchmark + speed checks; update docs and this plan with final outcomes.

## Surprises & Discoveries

- Observation: Several feedback recommendations from earlier rounds are already partially implemented.
  Evidence: `cookimport/parsing/canonical_line_roles.py` already emits `candidate_labels`, and `cookimport/llm/codex_farm_orchestrator.py` already records `pass3_utility_signal` and routing fields.

- Observation: Starter pack still writes a CSV triage artifact, which conflicts with current operator preference.
  Evidence: `scripts/benchmark_cutdown_for_external_ai.py` defines `STARTER_PACK_TRIAGE_FILE_NAME = "01_recipe_triage.csv"` and writes it via `csv.DictWriter`.

- Observation: Upload-bundle existing-output readers are already built to parse starter-pack CSV, so format migration must include compatibility handling.
  Evidence: `_upload_bundle_load_csv_rows(...)` and `_upload_bundle_build_context(...)` currently ingest starter triage from the CSV path.

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

## Outcomes & Retrospective

Initial state only. This plan now provides an executable path from feedback narrative to implementation milestones. Final retrospective must summarize measured quality deltas, pass3 runtime/token impact, starter-pack artifact changes, and any remaining gaps.

## Context and Orientation

This plan touches three connected surfaces.

First is deterministic line-role behavior in `cookimport/parsing/canonical_line_roles.py`. In this repository, a "line role" is the label assigned to each canonical text line (for example `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `RECIPE_TITLE`, `RECIPE_NOTES`, `OTHER`). This is where yield/header/title/ingredient boundary rules and candidate-label allowlists are determined.

Second is codex pass routing in `cookimport/llm/codex_farm_orchestrator.py`. A "pass3 routing policy" is the rule that decides whether a recipe gets a pass3 LLM call or deterministic promotion/fallback. This is where pass3 utility signals, routing reasons, and pass-level token/runtime counters are emitted.

Third is benchmark packaging in `scripts/benchmark_cutdown_for_external_ai.py`. "Starter pack" means the compact triage artifact set under `starter_pack_v1/`. "Upload bundle" means the consolidated three-file bundle under `upload_bundle_v1/`. The script currently writes and re-ingests starter triage as CSV, and this plan migrates that contract to non-CSV artifacts while keeping bundle completeness.

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


