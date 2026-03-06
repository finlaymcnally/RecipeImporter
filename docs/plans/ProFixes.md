# Unify Codex Execution Policy and Tighten Line-Role Determinism in the Existing CLI Stack

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

The idea behind the original plan is still correct: this repo needs one clear way to describe which Codex-backed surfaces are enabled, one safe way to inspect what an LLM-assisted run would do before spending tokens, and stronger deterministic protection around the line-role path that is currently the biggest quality drag. After this work, a developer should be able to run the existing CLI commands and answer three questions immediately: which profile actually ran, whether Codex execution was blocked/planned/executed, and what the line-role and Codex guardrails accepted or downgraded.

The user-visible result should be built on the commands this repo already exposes, not a new imaginary runner. `cookimport stage`, `cookimport labelstudio-benchmark`, `cookimport bench speed-run`, and `cookimport bench quality-run` should all resolve through the same Codex-policy layer, write consistent run metadata, support a zero-token planning mode for Codex-backed work, and produce guardrail artifacts that explain risky line-role and routing decisions. The quality goal is to preserve the current CodexFarm upside while reducing the known line-role and outside-span regressions through better deterministic preprocessing, better prompt boundaries, and better auditability.

## Progress

- [x] (2026-03-05 23:09 EST) Read `docs/PLANS.md`, `docs/10-llm/10-llm_README.md`, `docs/07-bench/07-bench_README.md`, and `docs/06-label-studio/06-label-studio_README.md`.
- [x] (2026-03-05 23:09 EST) Read the original `docs/plans/OGplan/ProFixes.md` and mapped the real code paths it would affect.
- [x] (2026-03-05 23:09 EST) Verified the repo already has typed run settings, stable config hashes, run manifests, benchmark codex confirmation gates, deterministic-first line-role logic, and line-role do-no-harm arbitration.
- [x] (2026-03-05 23:09 EST) Wrote local seam notes to `docs/understandings/2026-03-05_23.09.39-profixes-local-context-seams.md`.
- [x] (2026-03-05 23:09 EST) Rewrote this ExecPlan so it targets the real modules, commands, and artifacts in this repository.
- [x] (2026-03-05 23:30 EST) Added shared `CodexExecutionPolicy` helpers plus execution-policy metadata and plan-artifact writing in `cookimport/config/codex_decision.py`.
- [x] (2026-03-05 23:30 EST) Added `labelstudio-benchmark --codex-execution-policy plan` plus prediction-run `codex_execution_plan.json` writing in `cookimport/cli.py` and `cookimport/labelstudio/ingest.py`.
- [x] (2026-03-05 23:30 EST) Added focused tests for plan-mode approval boundaries and plan-only pred-run artifacts.
- [x] (2026-03-05 23:56 EST) Extended command-boundary plan mode to `cookimport stage`, `cookimport labelstudio-import`, and the `import` entrypoint; execute-mode approval stays explicit while plan mode writes manifests plus `codex_execution_plan.json` without `--allow-codex`.
- [x] (2026-03-05 23:56 EST) Threaded shared execution-policy metadata through Label Studio import, benchmark helpers, SpeedSuite, and QualitySuite manifests/report summaries.
- [x] (2026-03-05 23:56 EST) Added explicit line-role guardrail mode (`off|preview|enforce`) plus new `guardrail_report.json` / `guardrail_changed_rows.jsonl` artifacts with legacy do-no-harm compatibility sidecars.
- [x] (2026-03-05 23:56 EST) Tightened deterministic fraction handling in `recipe_block_atomizer.py` and `evidence_normalizer.py` so spaced fractions and dual-unit quantities stay intact.
- [x] (2026-03-05 23:56 EST) Added deterministic tests for stage/import plan boundaries, line-role guardrail artifacts, spaced-fraction normalization, dual-unit evidence preservation, and projection artifact plumbing.
- [x] Milestone 1: centralize profile resolution and Codex execution policy across the public CLI surfaces and benchmark helpers.
- [ ] Milestone 2: add plan-versus-execute Codex policy artifacts on top of the existing low-level kill switch and benchmark confirmation behavior (completed: command-boundary plan artifacts for stage/import/benchmark; remaining: live call-site plan artifacts for line-role and recipe pass work).
- [ ] Milestone 3: turn the existing line-role and Codex routing protections into explicit preview/enforce guardrail reporting (completed for line-role prediction + projection manifests; remaining: recipe Codex pass parity if needed later).
- [x] Milestone 4: improve deterministic line-role inputs and prompt boundaries in the existing parsing/LLM modules (completed for the fraction/quantity regressions found in the current code path).
- [x] Milestone 5: update tests and docs so the new policy and artifact contracts are explicit and verifiable.

## Surprises & Discoveries

- Observation: there is no single small orchestrator to modify.
  Evidence: the effective runtime contract is spread across `cookimport/config/run_settings.py`, `cookimport/config/run_settings_adapters.py`, `cookimport/config/codex_decision.py`, `cookimport/cli.py`, `cookimport/entrypoint.py`, and `cookimport/labelstudio/ingest.py`.

- Observation: the repo already has a canonical typed settings object and stable hash helpers.
  Evidence: `RunSettings` in `cookimport/config/run_settings.py` already exposes `to_run_config_dict()`, `summary()`, and `stable_hash()`, and benchmark/prediction manifests already write config hashes and config summaries.

- Observation: human-approval ideas are already partially implemented, but only in some surfaces.
  Evidence: `cookimport/config/codex_decision.py` has `resolve_codex_command_decision(...)`, `cookimport/llm/codex_exec.py` has the `COOKIMPORT_ALLOW_LLM` kill switch, and `cookimport bench speed-run` / `cookimport bench quality-run` already require `I_HAVE_EXPLICIT_USER_CONFIRMATION` for `--include-codex-farm`.

- Observation: line-role guardrails are not greenfield work.
  Evidence: `cookimport/parsing/canonical_line_roles.py` already does deterministic-first labeling, selective Codex escalation, outside-span sanitization, and source-level `do_no_harm` downgrade with persisted diagnostics under `line-role-pipeline/`.

- Observation: the highest-value deterministic fix targets are already isolated.
  Evidence: `cookimport/parsing/recipe_block_atomizer.py` owns `atomic-v1` splitting, `cookimport/llm/evidence_normalizer.py` owns additive pass2 normalization, `cookimport/parsing/canonical_line_roles.py` owns line-role heuristics and Codex escalation, and `cookimport/llm/canonical_line_role_prompt.py` owns the fallback prompt contract.

- Observation: the original “one preset system” framing is too simple for this repo.
  Evidence: the codebase already has three distinct decision layers that must agree: interactive top-tier profile selection in `cookimport/cli_ui/run_settings_flow.py`, paired benchmark contract helpers in `cookimport/config/codex_decision.py` and `cookimport/cli.py`, and runtime/analytics Codex surface classification in `cookimport/analytics/benchmark_semantics.py`.

- Observation: zero-token benchmark preview cannot reuse the normal prediction bundle path unchanged.
  Evidence: `_build_prediction_bundle_from_import_result(...)` assumes `stage_block_predictions.json` and `extracted_archive.json` exist, so plan mode needs an earlier `labelstudio-benchmark` return after writing plan/manifests.

- Observation: guardrail-mode normalization can silently collapse to enforce mode if enum values are not flattened before string comparison.
  Evidence: `RunSettings.line_role_guardrail_mode` is an enum-backed field, so the helper in `cookimport/parsing/canonical_line_roles.py` had to read `.value` explicitly to keep `preview` from behaving like `enforce`.

## Decision Log

- Decision: keep `RunSettings` as the canonical settings schema and build the plan on top of it instead of introducing a parallel `ResolvedRunConfig` stack.
  Rationale: the repo already depends on `RunSettings` for UI defaults, hashing, manifests, and benchmark helpers. Adding a second config system would increase, not reduce, split-brain behavior.
  Date/Author: 2026-03-05 / Codex

- Decision: target the real public command surface (`cookimport stage`, `cookimport labelstudio-benchmark`, `cookimport bench speed-run`, `cookimport bench quality-run`) instead of inventing a new `run --preset ...` command.
  Rationale: those are the commands users and tests already exercise, and they are where the policy drift currently shows up.
  Date/Author: 2026-03-05 / Codex

- Decision: evolve existing safety rails into a central execution-policy layer rather than replacing them wholesale.
  Rationale: the repo already has a low-level LLM kill switch, benchmark confirmation tokens, and Codex decision helpers. The missing part is consistency and artifact visibility, not raw safety primitives.
  Date/Author: 2026-03-05 / Codex

- Decision: treat the current line-role `do_no_harm` path, pass1 eligibility gate, transport audit, and pass3 routing metadata as the seed of the guardrail system.
  Rationale: these behaviors already solve the same class of problem the original plan wanted to address, and they already write useful diagnostics. The right move is to parameterize and unify them, not to start from zero.
  Date/Author: 2026-03-05 / Codex

- Decision: preserve existing repo language around `vanilla`, `codexfarm`, and `ai_assistance_profile` rather than collapsing everything into one new preset taxonomy.
  Rationale: tests, dashboards, and existing docs already distinguish paired benchmark identity from actual Codex surface facts. The implementation should centralize those facts, not erase the distinction.
  Date/Author: 2026-03-05 / Codex

- Decision: make the first shipped plan-mode surface `labelstudio-benchmark --no-upload --codex-execution-policy plan`, and have it stop before extraction/eval/upload while still writing pred-run and benchmark manifests.
  Rationale: this is the smallest real command boundary that can produce an inspectable zero-token artifact without having to fake normal prediction outputs that downstream benchmark code expects.
  Date/Author: 2026-03-05 / Codex

- Decision: keep legacy `do_no_harm_*` artifact names as compatibility sidecars while promoting `guardrail_report.json` and `guardrail_changed_rows.jsonl` as the new explicit contract.
  Rationale: benchmark/projection/debug readers already know the legacy filenames, so the safe migration path is additive naming rather than an abrupt rename.
  Date/Author: 2026-03-05 / Codex

## Outcomes & Retrospective

The practical public-command slice is now landed. `cookimport/config/codex_decision.py` is the shared execution-policy layer, `cookimport stage`, `cookimport labelstudio-import`, `cookimport labelstudio-benchmark`, and the `import` entrypoint can all write a zero-token `codex_execution_plan.json`, and SpeedSuite/QualitySuite now record the same execution-policy facts in their manifest/report payloads.

The line-role guardrail work is also landed for the current prediction path. `line_role_guardrail_mode=off|preview|enforce` is part of `RunSettings`, prediction runs/projected artifacts now expose `guardrail_report.json` and `guardrail_changed_rows.jsonl`, and deterministic fraction handling was tightened so known `1 / 2` and dual-unit regressions no longer fragment the input boundary before line-role or pass2 evidence assembly.

The remaining gap is narrower than before but real: the plan artifact still stops at the command boundary rather than enumerating concrete live line-role batches or recipe CodexFarm pass work, and the new explicit guardrail mode has not been generalized onto recipe-pass routing artifacts.

## Context and Orientation

This repository already has a strong typed-settings core. `cookimport/config/run_settings.py` defines `RunSettings`, which is the canonical per-run settings model used by UI flows, manifests, and analytics. `RunSettings.to_run_config_dict()` produces the JSON-safe settings payload that downstream code writes into manifests. `RunSettings.stable_hash()` computes a stable hash from that settings payload. Any implementation in this plan must reuse that model unless there is a concrete reason not to.

There are currently multiple ways those settings get turned into behavior. `cookimport/config/run_settings_adapters.py` maps `RunSettings` into kwargs for `cookimport/cli.py` commands. `cookimport/entrypoint.py` loads global settings and then calls `stage(...)`. `cookimport/cli_ui/run_settings_flow.py` builds interactive top-tier profile choices such as `codexfarm` and `vanilla`. `cookimport/config/codex_decision.py` already contains explicit profile and benchmark-contract helpers such as `apply_top_tier_profile_contract(...)`, `apply_benchmark_baseline_contract(...)`, `apply_benchmark_codex_contract_from_baseline(...)`, and `resolve_codex_command_decision(...)`.

The public command surface is in `cookimport/cli.py`. For this plan, the important commands are `stage`, `labelstudio-benchmark`, `bench speed-run`, and `bench quality-run`. `labelstudio-benchmark` is the single-run benchmark primitive. It ultimately routes prediction-run generation through `cookimport/labelstudio/ingest.py`, where `generate_pred_run_artifacts(...)` builds `RunSettings`, computes a run config hash, writes artifacts, and persists run manifests. This matters because a large part of the original plan talked about a generic pipeline orchestrator, but in this repo the benchmark primitive already serves as the practical orchestration seam.

The recipe CodexFarm path lives primarily in `cookimport/llm/codex_farm_orchestrator.py`. That module coordinates pass1 chunking, pass2 schema extraction, pass3 final drafting, pass1 eligibility gates, evidence normalization, transport audits, routing/fallback decisions, and `llm_manifest.json` writing. The low-level Codex CLI kill switch is in `cookimport/llm/codex_exec.py`, which refuses to run unless `COOKIMPORT_ALLOW_LLM=1`. That is a safety brake, not a user-intent explanation layer.

The canonical line-role path lives in `cookimport/parsing/recipe_block_atomizer.py`, `cookimport/parsing/canonical_line_roles.py`, `cookimport/llm/canonical_line_role_prompt.py`, and `cookimport/labelstudio/canonical_line_projection.py`. `recipe_block_atomizer.py` owns `atomic-v1` splitting. `canonical_line_roles.py` owns deterministic heuristics, selective Codex escalation, outside-span sanitization, caching, telemetry, and the current `do_no_harm` downgrade artifacts. Any plan to “fix line-role regressions” has to start there, not in a brand-new package.

Run manifests are defined in `cookimport/runs/manifest.py`. They already provide the stable place to persist run identity, run config, artifacts, and notes. The revised plan should store additional execution-policy and guardrail facts in those manifests rather than inventing a second top-level reporting mechanism.

Three terms of art matter throughout this plan.

A “top-tier profile” is the interactive profile family selected in `cookimport/cli_ui/run_settings_flow.py`, currently `codexfarm` or `vanilla`. A “benchmark variant contract” is the paired deterministic-versus-codex payload transformation used by offline benchmark helpers. An “AI assistance profile” is the runtime/analytics classification of which Codex-backed surfaces were actually enabled, for example deterministic, line-role-only, recipe-only, or full-stack. These three ideas are related but not identical. A successful implementation keeps them consistent and makes the distinctions visible.

Another important term is “guardrail.” In this repo, a guardrail is not abstract policy prose. It is a deterministic rule or threshold that can reject, downgrade, or explain risky output. Today the line-role `do_no_harm` downgrade, pass1 eligibility scoring, transport mismatch audits, and pass3 routing decisions are already concrete guardrails. This plan expands and unifies those, then makes their behavior configurable and explicit.

## Plan of Work

### Milestone 1: Centralize profile resolution and execution policy on top of `RunSettings`

The first milestone is to stop the current split-brain behavior where the same conceptual run can pick up Codex posture from multiple different places. The implementation should keep `RunSettings` as the canonical settings object and add one shared resolution layer, either in `cookimport/config/codex_decision.py` or a closely related new config module, that answers four questions together: which top-tier or benchmark contract was requested, which Codex-backed surfaces are enabled, whether live Codex execution is blocked/planned/executed, and how that choice should be written into the run manifest.

This milestone should remove duplicated contract helpers from `cookimport/cli.py` and make the CLI, interactive flow, entrypoint flow, and benchmark helpers all call the same contract code. The current `_all_method_apply_baseline_contract(...)` and `_all_method_apply_codex_contract_from_baseline(...)` logic in `cookimport/cli.py` should move behind the shared config helper layer or become thin wrappers over `cookimport/config/codex_decision.py`. The interactive top-tier chooser in `cookimport/cli_ui/run_settings_flow.py` should keep its user-facing language, but the actual payload transformation should come from the same shared contract code used by benchmarks.

This milestone should also add a small manifest-visible execution-policy payload. It does not need to be a new manifest schema version. It can live inside `run_config` or a dedicated `artifacts` or `notes` field, but it must be machine-readable. At minimum it should record the requested profile family, the benchmark variant when applicable, the resolved `ai_assistance_profile`, the enabled Codex surfaces, and the execution-policy mode that was applied.

At the end of this milestone, the same `RunSettings` payload should be interpreted the same way whether it came from `stage`, `labelstudio-benchmark`, `bench speed-run`, `bench quality-run`, or `entrypoint.py`.

### Milestone 2: Add plan-versus-execute Codex policy artifacts to the existing call sites

The second milestone adapts the original “human-gated LLM calls” idea to the real call sites in this repo. The right place to start is not a fake generic `LLMClient` for the whole pipeline. The real live-Codex boundaries are `cookimport/llm/codex_exec.py` for line-role fallback batches and `cookimport/llm/codex_farm_runner.py` / `cookimport/llm/codex_farm_orchestrator.py` for recipe CodexFarm passes. The implementation should add a shared execution-policy object that these modules receive or can derive from `RunSettings`.

That policy object should support three modes. `blocked` means deterministic-only execution and no plan artifact. `plan` means do not execute live Codex calls, but emit a plan artifact that describes what would have run. `execute` means live calls are allowed, but only when the existing explicit-approval requirements are satisfied. For batch benchmark commands, the existing explicit confirmation token requirement should remain the outer operator-intent gate. For single-run stage and benchmark flows, the plan artifact should be the concrete approval object the user can inspect before rerunning in execute mode.

The plan artifact should match the actual surfaces in this repo. For line-role, planned rows should correspond to Codex batch prompts built from unresolved `AtomicLineCandidate` groups in `cookimport/parsing/canonical_line_roles.py`. For recipe CodexFarm, planned rows should correspond to pass1/pass2/pass3 subprocess work as emitted by `cookimport/llm/codex_farm_orchestrator.py`, keyed by recipe id, pipeline id, and canonicalized input fingerprints. The plan file should include the run settings hash, source hash or input fingerprint, requested model and reasoning effort overrides when present, and enough stable identifiers to detect stale approvals.

In `plan` mode the repo should still do useful deterministic work. The line-role path already has deterministic baseline and fallback behavior, and the recipe CodexFarm path can keep the current deterministic result while recording the skipped Codex work. The output in plan mode does not need to equal the execute-mode output. It only needs to be safe, reproducible, and clear about what was skipped.

The milestone is successful when the existing commands can produce `run_manifest.json` plus a concrete Codex plan artifact without spending tokens, and when `execute` mode can verify that the plan matches the current run before permitting live calls.

### Milestone 3: Turn existing line-role and Codex routing protections into explicit guardrail modes

The third milestone keeps the original guardrail idea but grounds it in the current code. The line-role path already has `do_no_harm` arbitration in `cookimport/parsing/canonical_line_roles.py`. The recipe Codex path already has pass1 eligibility scoring, transport audits, degradation severity, and pass3 routing metadata in `cookimport/llm/codex_farm_orchestrator.py`. The work here is to make those protections explicit, configurable, and consistently reported.

Add a small guardrail mode setting with values `off`, `preview`, and `enforce`. The line-role implementation should treat the current sanitized deterministic output as the preview baseline and the current downgrade behavior as enforce behavior. In preview mode, the run should write the same diagnostics that today only exist when downgrade logic triggers, but it should not mutate the accepted predictions. In enforce mode, it should keep the current downgrade semantics and make the mutations explicit in a stable artifact.

The recipe Codex path should expose the same mode vocabulary for pass1 eligibility clamp/drop, pass2 transport mismatches, degradation severity, and pass3 deterministic skip or fallback. This does not require a giant generic framework on day one. A simple shared artifact writer is enough if the rows are consistent. The important requirement is that a reader can open one guardrail report and answer: what risky conditions were seen, what would have changed in preview mode, what did change in enforce mode, and which module made the call.

The natural artifact location is alongside the existing LLM and line-role artifacts, then linked from `run_manifest.json`. For prediction-run and benchmark flows, the manifest should surface these paths using the same style already used for line-role projection and `llm_manifest.json`.

### Milestone 4: Improve deterministic line-role inputs before asking Codex for help

The fourth milestone addresses the original plan’s strongest quality idea: spend less effort on weak inputs and tighten the deterministic path feeding line-role and recipe Codex. The primary files are `cookimport/parsing/recipe_block_atomizer.py`, `cookimport/llm/evidence_normalizer.py`, `cookimport/parsing/canonical_line_roles.py`, and `cookimport/llm/canonical_line_role_prompt.py`.

In `recipe_block_atomizer.py`, fix fraction handling and punctuation-only splits so `atomic-v1` does not produce junk rows such as bare `/` fragments or break yield lines like “Makes about 1/2 cup” into nonsense pieces. In `evidence_normalizer.py`, normalize fraction spacing and related quantity formatting before additive normalized evidence is assembled for Codex pass2. In `canonical_line_roles.py`, strengthen the deterministic high-confidence rules for ingredient lines, instruction lines, yield lines, compact headings, and outside-span narrative rejection before the unresolved set is escalated to Codex. In `canonical_line_role_prompt.py`, narrow the remaining ambiguity by clarifying `RECIPE_VARIANT` versus section heading and `KNOWLEDGE` versus `RECIPE_NOTES`, using short examples that match the current label taxonomy.

The goal is not to hard-code one cookbook. The goal is to improve the general deterministic evidence boundary so Codex sees fewer malformed or obviously-resolvable cases, and the fallback/downgrade logic has better raw material when it has to act.

### Milestone 5: Prove the new behavior with focused tests and doc updates

The final milestone updates the tests and docs that already define this repo’s user-facing contract. The minimum doc set is `docs/10-llm/10-llm_README.md`, `docs/07-bench/07-bench_README.md`, and `docs/06-label-studio/06-label-studio_README.md`. If command-line flags or profile language change materially, `docs/02-cli/02-cli_README.md` must be updated too.

The test updates should stay narrow and behavior-focused. `tests/llm/test_run_settings.py` and any new config-policy tests should pin the shared resolution semantics. `tests/bench/test_bench_speed_cli.py` and `tests/bench/test_bench_quality_cli.py` should cover the explicit-confirmation and execution-policy behavior. `tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler.py`, `tests/labelstudio/test_labelstudio_ingest_parallel.py`, and `tests/labelstudio/test_canonical_line_projection.py` should cover manifest and line-role artifact plumbing. The line-role deterministic fixes should get focused tests near the parsing/LLM modules they change.

This milestone is complete when a novice can read the docs, run one plan-mode command, inspect the plan and guardrail artifacts, and understand how to rerun the same command with explicit approval to execute Codex-backed work.

## Concrete Steps

All commands below should be run from `/home/mcnal/projects/recipeimport`. Before running tests, activate the project venv and install dev dependencies if needed.

    source .venv/bin/activate
    pip install -e .[dev]

Start implementation by replacing duplicate profile-contract helpers with shared config helpers.

Inspect and update:

    cookimport/config/codex_decision.py
    cookimport/config/run_settings.py
    cookimport/config/run_settings_adapters.py
    cookimport/cli.py
    cookimport/entrypoint.py
    cookimport/cli_ui/run_settings_flow.py

The first proof point should be a small resolution helper or CLI-visible debug output that shows the same policy facts regardless of whether the run is coming from `stage`, `labelstudio-benchmark`, or benchmark batch helpers. If a new `--print-run-settings` or `--print-run-policy` flag is added, wire it through the real commands rather than a private script.

Next, wire a shared execution-policy object into the actual live-Codex call sites:

    cookimport/llm/codex_exec.py
    cookimport/llm/codex_farm_runner.py
    cookimport/llm/codex_farm_orchestrator.py
    cookimport/parsing/canonical_line_roles.py
    cookimport/labelstudio/ingest.py

Add a plan artifact writer that records planned line-role Codex batches and planned CodexFarm pass work. Then make `labelstudio-benchmark --no-upload` the first public command to support the new plan mode because it already writes rich manifests and prediction artifacts offline.

After that, expose guardrail mode in the line-role and recipe-Codex modules, then thread the resulting artifact paths back into the existing run-manifest plumbing in `cookimport/labelstudio/ingest.py` and any stage-manifest writers that need parity.

Finally, tighten the deterministic line-role inputs:

    cookimport/parsing/recipe_block_atomizer.py
    cookimport/llm/evidence_normalizer.py
    cookimport/parsing/canonical_line_roles.py
    cookimport/llm/canonical_line_role_prompt.py

Use focused fixtures and unit tests rather than broad end-to-end runs while iterating on these heuristics.

## Validation and Acceptance

Validation must stay mostly zero-token. The final acceptance run that actually spends tokens is explicitly a later human-triggered step.

The implementation is acceptable only if all of the following are true.

First, profile resolution is centralized enough that the same settings payload leads to the same `ai_assistance_profile`, enabled Codex surfaces, and execution-policy mode across `stage`, `labelstudio-benchmark`, `bench speed-run`, `bench quality-run`, and `entrypoint.py`.

Second, a real public command can run in a zero-token plan mode and produce a stable plan artifact. The easiest command to prove this with is an offline benchmark invocation. A concrete target after implementation should look like:

    source .venv/bin/activate
    python -m cookimport.cli labelstudio-benchmark run \
      --no-upload \
      --eval-mode canonical-text \
      --source-file data/input/SeaAndSmokeCUTDOWN.epub \
      --gold-spans data/golden/pulled-from-labelstudio/seaandsmokecutdown/exports/freeform_span_labels.jsonl \
      --llm-recipe-pipeline codex-farm-3pass-v1 \
      --line-role-pipeline codex-line-role-v1 \
      --atomic-block-splitter atomic-v1 \
      <new execution-policy flags here>

That run should complete without live LLM calls and should write `run_manifest.json` plus the new Codex plan artifact.

Third, explicit execution remains explicit. For benchmark batch flows, `bench speed-run` and `bench quality-run` must still reject Codex execution without their existing positive confirmation token. For single-run flows, execute mode must fail fast unless a matching approval artifact or equivalent explicit policy input is present.

Fourth, guardrail preview mode must be non-mutating and guardrail enforce mode must be auditable. The line-role path should show this most clearly because it already has deterministic baseline and downgrade logic. Preview mode should write the same class of diagnostics without changing accepted predictions. Enforce mode should record every downgrade or fallback that changes the accepted output.

Fifth, deterministic line-role improvements must be proven by focused tests. The minimum behavior to verify is:

- fraction and quantity lines are not broken into punctuation-only atomic rows,
- additive evidence normalization collapses malformed fraction spacing before pass2 evidence is built,
- strong deterministic ingredient/instruction/title-or-note cases are resolved before Codex escalation,
- the unresolved set planned for Codex shrinks for known fixture cases.

The targeted test command after implementation should be a focused subset, not the whole suite:

    source .venv/bin/activate
    pytest \
      tests/llm/test_run_settings.py \
      tests/bench/test_bench_speed_cli.py \
      tests/bench/test_bench_quality_cli.py \
      tests/labelstudio/test_labelstudio_ingest_parallel.py \
      tests/labelstudio/test_canonical_line_projection.py \
      -q

Add narrower new tests for atomizer, line-role heuristics, and plan-artifact validation where they naturally belong.

Later, after the zero-token behavior is stable, a human can run one explicit execute-mode benchmark sample and confirm that the line-role regression footprint shrinks without losing the current CodexFarm routing wins. That live run is out of scope for automated acceptance.

## Idempotence and Recovery

This plan should stay additive and restart-safe.

Manifest extension is the preferred recovery mechanism. Whenever a new plan artifact, execution-policy payload, or guardrail report is written, it should be linked from `run_manifest.json` so reruns and downstream tools can find it without guessing file names.

Plan-mode runs must be safe to repeat. If the inputs and resolved run settings have not changed, rerunning the same command should either reproduce the same plan artifact byte-for-byte or clearly replace it with an equivalent artifact carrying the same stable identity fields.

Execute-mode validation must fail before spending tokens when approval inputs do not match the current run settings hash or source fingerprint. The implementation should prefer early aborts and clear error messages over implicit regeneration.

Guardrail preview mode must never mutate the accepted output. That makes it safe to enable in repeated offline benchmark runs. Guardrail enforce mode can mutate accepted output, but every mutation must be written to a report row that includes enough identifiers to compare reruns.

The deterministic line-role and evidence-normalization changes should be implemented with focused unit tests first so they can be retried safely without rerunning expensive benchmark flows.

## Artifacts and Notes

Useful repo-local search commands that were used to ground this plan:

    npm run docs:list
    rg -n "@.*command|labelstudio_benchmark\\(|bench_speed_run\\(|bench_quality_run\\(" cookimport/cli.py
    rg -n "class RunSettings|stable_hash|summary|build_run_settings" cookimport/config/run_settings.py
    rg -n "resolve_codex_command_decision|apply_benchmark_baseline_contract|apply_top_tier_profile_contract" cookimport/config/codex_decision.py
    rg -n "do_no_harm|outside_span|codex-line-role-v1" cookimport/parsing/canonical_line_roles.py
    rg -n "normalize_pass2_evidence|split_quantity_lines" cookimport/llm/evidence_normalizer.py
    rg -n "run_codex_farm_recipe_pipeline|pass1|pass2|pass3" cookimport/llm/codex_farm_orchestrator.py

The local seam summary for this rewrite lives at:

    docs/understandings/2026-03-05_23.09.39-profixes-local-context-seams.md

Revision note (2026-03-05 23:30 EST): updated this ExecPlan after landing the first execution-policy slice so the document reflects the real shipped `labelstudio-benchmark --codex-execution-policy plan` behavior and the remaining gaps.

Revision note (2026-03-05 23:56 EST): updated this ExecPlan after landing command-boundary plan mode for `stage` and `labelstudio-import`, explicit line-role guardrail reporting, deterministic fraction fixes, and the matching deterministic tests/docs.

One important anti-goal for implementation: do not create a second disconnected configuration stack with new preset files and placeholder orchestrators while `RunSettings`, `codex_decision.py`, and the existing manifest writers continue to exist. That would make the repo harder to reason about and would not solve the actual problem.

## Interfaces and Dependencies

At the end of Milestone 1, there must be one shared config/policy resolution surface that all major commands can call. This can live inside `cookimport/config/codex_decision.py` or a nearby new config module, but it must accept a `RunSettings` or run-config payload and return machine-readable facts about:

- requested profile family,
- benchmark variant when applicable,
- enabled Codex-backed surfaces,
- resolved `ai_assistance_profile`,
- execution-policy mode,
- whether explicit operator approval is still required.

At the end of Milestone 2, the live-Codex call sites in `cookimport/llm/codex_exec.py` and the CodexFarm runner/orchestrator modules must accept or derive that execution policy and produce a stable plan artifact in plan mode. The plan artifact must include stable identity fields tied to the run settings hash and source/input fingerprint.

At the end of Milestone 3, the line-role and recipe-Codex modules must emit guardrail rows using one consistent report shape, even if the implementation uses small helper writers instead of a large abstract framework.

At the end of Milestone 4, the deterministic line-role boundary must still expose the same user-facing labels and existing prompt taxonomies. This plan does not authorize changing the label vocabulary itself. It changes how inputs are normalized, when Codex is asked for help, and how risky results are downgraded or explained.

Plan rewrite note: 2026-03-05 23:09 EST. This file was rewritten after reading the real codebase because the original version assumed placeholder `src/<package>` paths, a generic orchestrator, and a synthetic `run --preset` CLI. The goals stayed the same, but the implementation path was changed to fit the actual `cookimport` architecture.
