---
summary: "ExecPlan to harden Codex line-role and pass1 recipe activation with do-no-harm gates, outside-span containment, and ablation-driven validation."
read_when:
  - "When codex line-role turns narrative prose into recipe structure labels."
  - "When saltfatacidheat-style outside-span contamination dominates new errors."
  - "When deciding whether codex line-role should run outside active recipe spans."
---

# Recover CodexFarm safety with line-role and activation do-no-harm gates

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `docs/PLANS.md` from the repository root.

## Purpose / Big Picture

After this work lands, CodexFarm keeps its strong in-recipe gains while reducing the specific failure mode where cookbook prose gets promoted into recipe structure. The user-visible behavior is that benchmark runs stop accepting harmful codex flips by default, especially outside active recipe spans, and produce explicit diagnostics whenever a do-no-harm fallback is triggered.

This plan intentionally focuses only on unresolved feedback themes from `Profeedback.md`: do-no-harm routing, recipe activation strictness, outside-span containment, selective line-role application, and clean lever isolation. It does not duplicate reliability work already captured in `docs/plans/OGplan/2026-03-04_08.40.46-processing-quality-reliability-recovery.md`.

## Scope Guardrails (Intent Lock)

This plan is limited to codex line-role and pass1 recipe-activation safety policy. It excludes report truth fixes, adaptive gold remapping, final-draft alias normalization, and tip/topic segmentation hardening, because those are already covered in the other ExecPlan.

This plan stays deterministic for gating and validation logic. It may continue using existing codex paths, but no new LLM-based parsing/cleaning modes are introduced.

Default operator behavior must remain unchanged: codex paths stay opt-in and disabled unless a run explicitly enables `--line-role-pipeline codex-line-role-v1` and/or `--llm-recipe-pipeline codex-farm-3pass-v1`.

## Progress

- [x] (2026-03-04_09.56.27) Re-read feedback and converted it into an ExecPlan candidate scope.
- [x] (2026-03-04_09.56.27) Audited current implementations in `cookimport/parsing/canonical_line_roles.py`, `cookimport/parsing/recipe_block_atomizer.py`, `cookimport/llm/codex_farm_orchestrator.py`, and `cookimport/cli.py` line-role gates.
- [x] (2026-03-04_09.56.27) Removed/changed feedback items already implemented or conflicting with current architecture; recorded in `Decision Log`.
- [x] (2026-03-04_10.03.19) Tightened milestone policy ambiguity with explicit thresholds/actions and added compare-command acceptance steps.
- [x] (2026-03-04_10.24.10) Implemented Milestone 1: runtime do-no-harm arbitration with deterministic baseline fallback scopes and diagnostics artifacts (`do_no_harm_diagnostics.json`, `do_no_harm_changed_rows.jsonl`).
- [x] (2026-03-04_10.24.10) Implemented Milestone 2: outside-span containment policy (`HOWTO_SECTION` hard-deny, title/variant compact+neighbor evidence, structured-line local-evidence requirements) with reason-tagged downgrades.
- [x] (2026-03-04_10.24.10) Implemented Milestone 3: pass1 eligibility gate (`proceed`/`clamp`/`drop`) and persisted diagnostics in `pass1_recipe_eligibility_diagnostics.json` + llm manifest recipe rows.
- [x] (2026-03-04_11.10.48) Extended Milestone 3 scoring with explicit chapter/page metadata negative evidence (`chapter_page_negative_score`) and manifest-visible score components/reasons.
- [x] (2026-03-04_10.24.10) Implemented Milestone 4: outside-span low-confidence codex escalation disabled by default (inside-span-first policy), with narrow env override for controlled ablations.
- [x] (2026-03-04_10.58.00) Milestone 5 ablation packet executed with deterministic stage-block scoring (`--gold-adaptation-mode off`) and machine-readable summary artifact at `data/output/labelstudio-benchmark/profeedback-2026-03-04_10.41.51/ablation_summary.json`.
- [x] (2026-03-04_11.20.00) Closed compare-step blocker: `labelstudio-benchmark compare` now accepts single-run `eval_report.json` file/directory inputs in addition to all-method multi-source report roots.
- [x] (2026-03-04_10.58.00) Codex auth blocker documented: full-stack codex runs required `--codex-farm-failure-mode fallback` in this environment due `codex-farm` websocket `403 Forbidden` authentication failures.
- [x] (2026-03-04_10.30.20) Added/updated regression tests for do-no-harm arbitration, outside-span policy, pass1 eligibility actions, and line-role artifact path propagation.
- [x] (2026-03-04_10.31.54) Updated docs (`04-parsing`, `10-llm`, `06-label-studio`) and added implementation findings note in `docs/understandings/`.

## Surprises & Discoveries

- Observation: Several feedback suggestions already exist in code and should not be re-implemented blindly.
  Evidence: `cookimport/llm/codex_farm_orchestrator.py` already rejects low-quality pass3 outputs and applies deterministic fallback (`_pass3_low_quality_reasons`, `_build_pass3_deterministic_fallback_payload`).

- Observation: Prompt-level negative guidance for canonical line-role is already substantial.
  Evidence: `llm_pipelines/prompts/canonical-line-role-v1.prompt.md` already includes narrative-outside-span examples, must-not rules, and strict candidate-label allowlist rules.

- Observation: Outside-span heuristics exist, but codex escalation still has room to over-activate because low-confidence escalation is not span-strict.
  Evidence: `cookimport/parsing/canonical_line_roles.py` uses `_CODEX_LOW_CONFIDENCE_THRESHOLD=0.90` and escalates unresolved/low-confidence candidates without a strict outside-span deny policy.

- Observation: Benchmark-time regression gates exist, but runtime do-no-harm arbitration of codex line-role predictions is still missing.
  Evidence: `cookimport/cli.py::_build_line_role_regression_gate_payload` gates benchmark outputs, but there is no equivalent runtime acceptance gate in `label_atomic_lines`.

- Observation: Existing low-confidence escalation tests assumed outside-span codex escalation was allowed; policy flip required explicit test contract updates.
  Evidence: `tests/parsing/test_canonical_line_roles.py::test_codex_mode_does_not_escalate_low_confidence_candidates_outside_recipe_span` now asserts codex is not called for outside-span low-confidence rows.

- Observation: Full touched-suite run currently fails on a pre-existing benchmark default assertion unrelated to this plan’s code paths.
  Evidence: `tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py::test_labelstudio_benchmark_no_upload_uses_offline_pred_run` expects `atomic_block_splitter=\"off\"` while runtime default is `atomic-v1`.

- Observation: `labelstudio-benchmark compare` does not accept per-run `eval_report.json` artifacts from `labelstudio-benchmark run`.
  Evidence: compare rejects those paths with `Unable to resolve ... all-method benchmark report root`, and resolver code requires `all_method_benchmark_multi_source_report.json` roots.

- Observation: Full codex-farm recipe pipeline is currently blocked by environment auth, independent of parsing gate code.
  Evidence: `codex-farm` run failed with websocket `403 Forbidden` and message `codex auth failed: run \`codex\` once and sign in`.

## Decision Log

- Decision: Keep the original priority order centered on line-role and activation gating, not broad LLM prompt tuning.
  Rationale: The feedback identifies line-role/activation as dominant error sources, and code review confirms prompt-only work would duplicate existing safeguards before closing structural gaps.
  Date/Author: 2026-03-04 / assistant

- Decision: Discard feedback item "treat empty pass3 outputs as invalid when pass2 found structure" as a new milestone.
  Rationale: This behavior is already implemented via pass3 low-quality rejection and deterministic fallback paths.
  Date/Author: 2026-03-04 / assistant

- Decision: Keep "harsher line-role prompt" only as a secondary tuning pass behind deterministic gates.
  Rationale: Prompt already has strong negative rules; highest remaining risk is acceptance policy, not instruction wording.
  Date/Author: 2026-03-04 / assistant

- Decision: Keep "do-not-trust raw confidence" by replacing confidence-only routing with structural risk signals.
  Rationale: Existing confidence thresholding is insufficient for outside-span contamination control.
  Date/Author: 2026-03-04 / assistant

- Decision: Exclude report/remap/draft-normalization/tip-topic tasks from this plan.
  Rationale: They are already covered by `docs/plans/OGplan/2026-03-04_08.40.46-processing-quality-reliability-recovery.md` and would create duplicate execution tracks.
  Date/Author: 2026-03-04 / assistant

- Decision: Lock first-pass do-no-harm thresholds to explicit constants in Milestone 1.
  Rationale: A threshold-free plan leaves too much implementer discretion and makes benchmark acceptance less reproducible.
  Date/Author: 2026-03-04 / assistant

- Decision: Enforce `HOWTO_SECTION` outside-span as hard-deny in v1, with no exception path.
  Rationale: This is the highest-risk contamination label in current feedback and is easy to verify with deterministic tests.
  Date/Author: 2026-03-04 / assistant

- Decision: Disable outside-span low-confidence codex escalation by default in code for milestone acceptance.
  Rationale: Confidence-only escalation is a known contamination vector; disabling it first is safer than introducing complex exception rules immediately.
  Date/Author: 2026-03-04 / assistant

- Decision: Keep a minimal env override (`COOKIMPORT_LINE_ROLE_OUTSIDE_SPAN_LOW_CONFIDENCE_ESCALATION`) instead of adding broad run-settings surface for outside-span escalation.
  Rationale: Milestone policy requires safe-by-default behavior; one narrow override supports controlled experiments without expanding persistent operator config complexity.
  Date/Author: 2026-03-04 / assistant

- Decision: Implement runtime do-no-harm as post-sanitization arbitration against sanitized deterministic baselines.
  Rationale: Comparing post-sanitization predictions prevents double-counting labels that are already invalidated by deterministic sanitizers and keeps fallback scopes auditable.
  Date/Author: 2026-03-04 / assistant

- Decision: Execute Milestone 5 with `--gold-adaptation-mode off` to avoid adaptive remap ambiguity aborts in stage-block evaluation.
  Rationale: Initial run failed with `ambiguous=285 (max=50)` under adaptive remap auto mode; deterministic stage-block scoring is sufficient for this ablation packet.
  Date/Author: 2026-03-04 / assistant

- Decision: Use `--codex-farm-failure-mode fallback` for full-stack ablation rows in this environment.
  Rationale: Codex auth was unavailable (`403 Forbidden`), and fallback mode preserved command completion plus comparable artifacts while explicitly recording the limitation.
  Date/Author: 2026-03-04 / assistant

## Outcomes & Retrospective

Implemented outcomes:

- Runtime do-no-harm fallback now emits explicit scope decisions (`accept`, `partial_outside_downgrade`, `full_source_fallback`) with threshold/counter payloads in `line-role-pipeline/do_no_harm_diagnostics.json`.
- Outside-span containment now hard-denies `HOWTO_SECTION` and applies evidence-checked downgrades for title/variant/instruction/ingredient promotions, with traceable reason tags and changed-row logs.
- Pass1 recipe activation now has deterministic eligibility scoring and policy-band actions before pass2 (`proceed`, `clamp`, `drop`) with recipe-level manifest visibility plus dedicated diagnostics artifact.
- Selective escalation policy now runs inside-span-first by default; outside-span low-confidence escalation is off unless explicitly overridden.

Remaining gap:

- Full-stack rows in this packet used codex-farm fallback because auth was unavailable; rerun those rows without fallback after codex auth is restored to get true codex-vs-deterministic compare evidence.

## Context and Orientation

The relevant flow spans four modules.

`cookimport/parsing/recipe_block_atomizer.py` creates atomic line candidates and candidate label allowlists, including `within_recipe_span` flags and outside-span tags. `cookimport/parsing/canonical_line_roles.py` applies deterministic labeling, optional codex escalation, and output sanitization. `cookimport/labelstudio/ingest.py` runs this line-role pipeline and writes projection artifacts. `cookimport/llm/codex_farm_orchestrator.py` handles pass1 recipe boundary acceptance and promotion into pass2/pass3.

Definitions used in this plan:

A "recipe span" is an inclusive block range (`start_block_index` to `end_block_index`) considered recipe-active for a candidate recipe.

"Outside-span contamination" means lines outside active recipe spans being labeled as recipe structure (`RECIPE_TITLE`, `RECIPE_VARIANT`, `HOWTO_SECTION`, `INSTRUCTION_LINE`, `INGREDIENT_LINE`) without sufficient structural evidence.

A "do-no-harm gate" is a deterministic acceptance check that compares codex candidate outputs against safer baselines and refuses codex overrides when contamination risk crosses thresholds.

Current gaps to close:

The code has deterministic outside-span heuristics and sanitizers, but codex escalation is still allowed too broadly for low-confidence rows. There is benchmark-time gating, but no runtime codex acceptance gate in canonical line-role labeling. Pass1 boundary acceptance currently trusts `is_recipe` plus bounds integrity, but does not apply a structural evidence floor before pass2 promotion.

## Plan of Work

### Milestone 1: Runtime line-role do-no-harm arbitration

Add a deterministic acceptance stage in `cookimport/parsing/canonical_line_roles.py` after codex predictions are parsed and sanitized. This stage must compare codex-resolved labels against deterministic baseline labels for the same candidates and compute contamination-risk counters, including outside-span recipe-ish flips, outside-span HOWTO/title promotions, and outside-span instruction/ingredient promotions lacking nearby recipe evidence.

To remove ambiguity, implement fixed first-pass thresholds as constants in this milestone (they can be tuned later in follow-up work): partial downgrade when any outside-span `HOWTO_SECTION` promotion occurs, or when outside-span `RECIPE_TITLE`/`RECIPE_VARIANT` promotions are at least 2, or when outside-span `INSTRUCTION_LINE`/`INGREDIENT_LINE` promotions are at least 4. Trigger full-source fallback to deterministic labels when total outside-span recipe-ish promotions are at least 8 or exceed 20% of candidate rows for that source. The first implementation should support two fallback scopes: downgrade only contaminated outside-span rows, or fallback entire source to deterministic labels when contamination is severe. Every fallback decision must produce a diagnostics payload containing counts, thresholds, and selected fallback scope.

Wire diagnostics artifact emission through the existing artifact root (`line-role-pipeline`) so benchmark and local debugging can trace why codex labels were accepted or rejected.

### Milestone 2: Hard outside-span containment and dangerous-label policy

Tighten label policy in `cookimport/parsing/canonical_line_roles.py` and, where needed, `cookimport/parsing/recipe_block_atomizer.py` so outside-span rows cannot be promoted to dangerous recipe-structure labels without explicit evidence. In practice, this means:

Outside active recipe spans, `HOWTO_SECTION` is always denied in this milestone (no exception path in v1). `RECIPE_TITLE` and `RECIPE_VARIANT` require compact-heading shape plus neighboring structural evidence within ±2 lines. `INSTRUCTION_LINE` and `INGREDIENT_LINE` outside spans should require stronger local evidence than today, otherwise resolve to `OTHER` or `KNOWLEDGE`.

Keep the rule deterministic and auditable: each forced downgrade should append reason tags so false positives can be traced.

### Milestone 3: Pass1 recipe-eligibility do-no-harm gate

Add a recipe-eligibility check in `cookimport/llm/codex_farm_orchestrator.py` after pass1 output consumption and before pass2 input generation. This gate should score each accepted pass1 span using deterministic structural evidence from included blocks: ingredient-like presence, instruction-like presence, heading/yield context, prose dominance, and explicit chapter/page heuristic metadata as negative evidence.

Use an explicit first-pass scoring rubric to avoid implementation drift: +2 when ingredient-like evidence is present, +2 when instruction-like evidence is present, +1 when heading/yield context is present, -2 when prose dominance is high, and -2 when chapter/page metadata indicates likely non-recipe context (for example chapter-intro/front-matter/mixed-content tags) under weak structural evidence. When pass1 marks `is_recipe=true` but score is weak, apply deterministic action by band: score >=3 proceeds to pass2, score 1-2 clamps to heuristic bounds before pass2, score <=0 is dropped before pass2. The selected action must be recorded per recipe in diagnostics and manifest rows.

This work hardens activation without changing codex pass contracts.

### Milestone 4: Selective codex escalation policy

Refine `_should_escalate_low_confidence_candidate` in `cookimport/parsing/canonical_line_roles.py` so codex escalation is inside-span-first. Outside-span escalation should be disabled by default or restricted to evidence-qualified rows only. Confidence value alone should not be enough to escalate.

For milestone acceptance, implement outside-span escalation as disabled by default in code (not only by config guidance). Any later exception path must be follow-up work with explicit evidence rules and tests.

Expose minimal run-settings controls only if needed for ablations; avoid adding broad configuration surface area. Default behavior must prioritize safety while preserving codex utility inside active recipe spans.

### Milestone 5: Ablation evidence and acceptance

Use existing benchmark tooling, not a new framework, to isolate lever impact. Produce a compact ablation packet for at least foodlab and saltfatacidheat using controlled runs that separate:

- no codex/no line-role,
- deterministic line-role only,
- codex line-role only with recipe LLM off,
- full codex stack.

Publish a short machine-readable summary artifact comparing contamination counters and score deltas per configuration. This confirms whether each gate actually improves the targeted failure mode instead of hiding it.

## Concrete Steps

Run all commands from `/home/mcnal/projects/recipeimport` with venv active.

1. Environment bootstrap.
   source .venv/bin/activate
   pip install -e .[dev]

2. Unit tests for outside-span labeling and escalation policy.
   pytest tests/parsing/test_recipe_block_atomizer.py tests/parsing/test_canonical_line_roles.py -q
   Expected: new outside-span deny/evidence tests pass and existing canonical-line tests remain green.

3. Pass1 gating tests.
   pytest tests/llm/test_codex_farm_orchestrator.py tests/llm/test_codex_farm_orchestrator_stage_integration.py -k "pass1 or fallback or degradation" -q
   Expected: pass1 eligibility gate decisions are present in manifest diagnostics and deterministic fallback behavior is preserved.

4. LabelStudio projection and payload contract tests.
   pytest tests/labelstudio/test_canonical_line_projection.py tests/labelstudio/test_labelstudio_benchmark_helpers_eval_payload.py -k "line_role or projection" -q
   Expected: line-role artifact contracts still load and new do-no-harm diagnostics artifacts are referenced correctly.

5. Foodlab ablation run matrix.
   cookimport labelstudio-benchmark run --gold-spans data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports/freeform_span_labels.jsonl --source-file data/input/thefoodlabCUTDOWN.epub --eval-mode stage-blocks --no-upload --llm-recipe-pipeline off --line-role-pipeline off --atomic-block-splitter off
   cookimport labelstudio-benchmark run --gold-spans data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports/freeform_span_labels.jsonl --source-file data/input/thefoodlabCUTDOWN.epub --eval-mode stage-blocks --no-upload --llm-recipe-pipeline off --line-role-pipeline deterministic-v1 --atomic-block-splitter atomic-v1
   cookimport labelstudio-benchmark run --gold-spans data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports/freeform_span_labels.jsonl --source-file data/input/thefoodlabCUTDOWN.epub --eval-mode stage-blocks --no-upload --llm-recipe-pipeline off --line-role-pipeline codex-line-role-v1 --atomic-block-splitter atomic-v1
   cookimport labelstudio-benchmark run --gold-spans data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports/freeform_span_labels.jsonl --source-file data/input/thefoodlabCUTDOWN.epub --eval-mode stage-blocks --no-upload --llm-recipe-pipeline codex-farm-3pass-v1 --line-role-pipeline codex-line-role-v1 --atomic-block-splitter atomic-v1
   Expected: contamination counters and line-role quality metrics can be compared per lever combination.

6. SaltFatAcidHeat confirmation run for outside-span safety.
   cookimport labelstudio-benchmark run --gold-spans data/golden/pulled-from-labelstudio/saltfatacidheatcutdown/exports/freeform_span_labels.jsonl --source-file data/input/SaltFatAcidHeatCUTDOWN.epub --eval-mode stage-blocks --no-upload --llm-recipe-pipeline codex-farm-3pass-v1 --line-role-pipeline codex-line-role-v1 --atomic-block-splitter atomic-v1
   Expected: do-no-harm diagnostics appear and catastrophic prose-activation slices are reduced versus prior baseline packet.

7. Compare deterministic baseline vs codex-gated candidate for both books.
   cookimport labelstudio-benchmark compare --baseline <foodlab_deterministic_run_or_report_path> --candidate <foodlab_codex_gated_run_or_report_path> --compare-out <foodlab_compare_dir> --fail-on-regression
   cookimport labelstudio-benchmark compare --baseline <saltfatacidheat_deterministic_run_or_report_path> --candidate <saltfatacidheat_codex_gated_run_or_report_path> --compare-out <saltfatacidheat_compare_dir> --fail-on-regression
   Expected: compare artifacts contain explicit gate pass/fail plus debug-artifact presence checks; regressions fail closed.

8. Full touched-surface confidence run.
   pytest tests/parsing tests/llm tests/labelstudio -q
   Expected: touched suites pass with no contract regressions.

## Validation and Acceptance

Acceptance is behavior-first.

Runtime do-no-harm gate acceptance:

For codex line-role runs, diagnostics must state whether codex labels were accepted, partially downgraded, or fully reverted. High contamination cases must trigger downgrade/revert deterministically, and threshold fields in diagnostics must match the constant values used by the gate.

Outside-span containment acceptance:

Outside active recipe spans, `HOWTO_SECTION` must not appear at all in v1. Title/variant/instruction promotions outside spans must require documented structural evidence and reason tags.

Pass1 eligibility acceptance:

Pass1-accepted spans with weak structure and high prose dominance must no longer auto-flow into pass2 without a policy decision record. Diagnostics must show score components and chosen action (`proceed`, `clamp`, or `drop`).

Ablation acceptance:

Ablation artifacts must make it possible to attribute score and contamination changes to each lever independently, not only to combined codex profile changes.

Non-overlap acceptance:

No implementation in this plan should duplicate report-truth, adaptive-remap, or final-draft-normalization tasks owned by the companion reliability ExecPlan.

## Idempotence and Recovery

All added gates must be deterministic and rerunnable with the same inputs. Re-running the same benchmark command should produce equivalent gate decisions and diagnostics except for timestamp metadata.

If do-no-harm thresholds are too strict and suppress valid recipe lines, recover by adjusting threshold constants and re-running only affected sources; do not bypass diagnostics. If pass1 eligibility gating is too aggressive, prefer clamping to heuristic bounds over dropping recipes entirely in first rollback step.

If any new gate causes broad regressions, keep artifact payloads and gate reason tags, then disable only the newest gate layer via a temporary policy switch while preserving instrumentation.

## Artifacts and Notes

Required artifact families for this plan:

- `line-role-pipeline/do_no_harm_diagnostics.json` per run or source.
- `line-role-pipeline/do_no_harm_changed_rows.jsonl` containing downgraded/reverted rows with reasons.
- `llm_raw/pass1_recipe_eligibility_diagnostics.json` (or per-recipe JSON files under a dedicated subfolder).
- A short ablation summary under benchmark outputs linking each config to contamination counters and key metrics.

Required documentation update at completion:

- `docs/04-parsing/04-parsing_readme.md` for new line-role gating behavior.
- `docs/10-llm/10-llm_README.md` for pass1 eligibility gate behavior.
- One short findings note in `docs/understandings/` summarizing before/after contamination evidence.

## Interfaces and Dependencies

Target interfaces after implementation:

In `cookimport/parsing/canonical_line_roles.py`, add a deterministic do-no-harm evaluator that receives deterministic predictions, codex-resolved predictions, and candidate context, and returns accepted predictions plus diagnostics.

In `cookimport/llm/codex_farm_orchestrator.py`, add a pass1 eligibility evaluator executed before pass2 input generation, with manifest-safe structured output fields (`eligibility_status`, `eligibility_score_components`, `eligibility_reasons`, and selected action).

In `cookimport/labelstudio/ingest.py`, wire new diagnostics artifacts into run metadata so benchmark helpers can surface them without manual path hunting.

Dependencies remain local and deterministic. No external service or new package is required for gate logic.

Update note (2026-03-04_09.56.27): Converted narrative feedback into a PLANS-compliant ExecPlan, removed already-implemented pass3 fallback work, and narrowed scope to unresolved do-no-harm/activation gaps not covered by the companion reliability ExecPlan.
Update note (2026-03-04_10.03.19): Tightened ambiguous policy language into explicit first-pass thresholds/actions, locked v1 outside-span HOWTO and escalation behavior, and added concrete compare commands so ablation acceptance is verifiable.
Update note (2026-03-04_10.31.54): Marked Milestones 1-4 complete with implemented code/tests/docs evidence, recorded remaining Milestone 5 ablation-run gap, and captured new decisions/surprises from implementation.
Update note (2026-03-04_11.33.00): Synced Milestone 3 rubric text to include chapter/page metadata negative evidence and closed compare-path handling gap by supporting single-run `eval_report.json` inputs in `labelstudio-benchmark compare`.
