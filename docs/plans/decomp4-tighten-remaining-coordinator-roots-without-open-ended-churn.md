---
summary: "ExecPlan for the remaining optional coordinator-root tightening work after decomp3, bounded so the repo does not slide back into an endless decomposition campaign."
read_when:
  - When decomp3 is complete and the remaining question is whether the still-large coordinator roots are worth another bounded shrink pass
  - When deciding how to tighten `bench_all_method.py`, `canonical_line_roles/runtime.py`, and `benchmark_cutdown_for_external_ai.py` without reopening open-ended refactor churn
  - When you need a concrete post-decomp3 execution contract before moving on to the separate AI-friendliness guardrails plan
---

# Tighten The Remaining Coordinator Roots Without Restarting Open-Ended Decomposition

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

This plan intentionally builds on the checked-in context in [docs/plans/decomp1-large-file-decomposition-roadmap.md](/home/mcnal/projects/recipeimport/docs/plans/decomp1-large-file-decomposition-roadmap.md), [docs/plans/decomp2-finish-owner-module-decomposition.md](/home/mcnal/projects/recipeimport/docs/plans/decomp2-finish-owner-module-decomposition.md), and [docs/plans/decomp3-complete-remaining-decomposition-end-to-end.md](/home/mcnal/projects/recipeimport/docs/plans/decomp3-complete-remaining-decomposition-end-to-end.md), but it repeats the essential current state here so a new contributor can execute it without replaying the prior chat.

## Operator Intent (Verbatim)

The following is the operator's exact stated intent for this change.

> more work to do though right? make a decomp4 plan plese

## Operator Intent (Structured)

The operator believes the decomposition campaign still has meaningful remaining work even after decomp3, and wants that residual work turned into a concrete bounded ExecPlan instead of a vague “maybe later” note. The operator is not asking for another whole-repo cleanup program. The operator wants an honest plan for the remaining coordinator roots that are still obviously large enough to slow safe local edits, while keeping the scope narrow enough that this does not become another endless decomposition season.

The plan therefore needs to answer three questions clearly. First, which roots still merit more shrink work right now. Second, which roots are now “good enough” and should be left alone unless a very clean seam appears. Third, how to prove the final state so the repo can then move on to the separate post-decomposition AI-friendliness guardrails work without ambiguity.

## Purpose / Big Picture

After this change, the remaining coordinator roots that still dominate cold-start navigation should stop being the next obvious bottlenecks. A contributor should be able to open the all-method benchmark root, the line-role runtime root, and the external-AI wrapper and mostly see orchestration that delegates into named owners, not another thousand-plus lines of durable helper logic embedded in place.

The user-visible proof is straightforward. The remaining target roots become materially smaller, their newly extracted owners live beside them with clear responsibility names, the local subsystem READMEs and decomposition plans describe the new seams, and the repo-preferred domain proofs stay green from `.venv`. The end state of this plan is not “zero large files.” The end state is that the remaining large files are large only because they are genuine coordinators, not because the next clean owner split was postponed.

## Progress

- [x] (2026-04-04 18:15 America/Toronto) Read `docs/PLANS.md`, `docs/plans/decomp1-large-file-decomposition-roadmap.md`, `docs/plans/decomp2-finish-owner-module-decomposition.md`, and `docs/plans/decomp3-complete-remaining-decomposition-end-to-end.md` after decomp3 was completed.
- [x] (2026-04-04 18:15 America/Toronto) Measured the post-decomp3 residual pressure points that motivate this plan: `cookimport/cli_support/bench_all_method.py` is `4697` lines, `cookimport/parsing/canonical_line_roles/runtime.py` is `4417`, `scripts/benchmark_cutdown_for_external_ai.py` is `11045`, and `cookimport/llm/codex_exec_runner.py` is `2068`.
- [x] (2026-04-04 18:15 America/Toronto) Confirmed from current root entrypoints that the biggest remaining shrink candidates are still concentrated in three places: benchmark coordinators, line-role assignment/direct-worker orchestration, and the external-AI upload-bundle block.
- [x] (2026-04-04 18:15 America/Toronto) Wrote the initial bounded decomp4 ExecPlan. Implementation has not started yet.
- [x] (2026-04-04 20:30 America/Toronto) Tightened the remaining line-role runtime bands by moving the taskfile-assignment, structured-assignment, direct-worker orchestration, runner-payload aggregation, and telemetry-summary family into `cookimport/parsing/canonical_line_roles/runtime_workers.py`, leaving `runtime.py` as a much smaller coordinator/root-wrapper seam.
- [x] (2026-04-04 20:30 America/Toronto) Tightened the remaining all-method coordinator bands by moving the global-queue/per-source benchmark coordinators into `cookimport/cli_support/bench_all_method_runtime.py` and the interactive benchmark flow into `cookimport/cli_support/bench_all_method_interactive.py`, leaving `bench_all_method.py` as the import-stable wrapper/root surface.
- [x] (2026-04-04 20:30 America/Toronto) Tightened the remaining external-AI upload-bundle bands by moving stage-report projection/per-label metrics into `cookimport/bench/external_ai_cutdown/stage_reports.py`, runtime-inventory reconstruction/fallback logic into `cookimport/bench/external_ai_cutdown/runtime_inventory.py`, and regression/triage sampling plus run-diagnostic status derivation into `cookimport/bench/external_ai_cutdown/regression_sampling.py`.
- [x] (2026-04-04 20:30 America/Toronto) Reassessed `cookimport/llm/codex_exec_runner.py` after the higher-value roots were addressed and left it untouched because no comparably clean low-blast-radius seam remained once the other roots were shrunk.
- [x] (2026-04-04 20:30 America/Toronto) Updated the affected local README files plus decomp1, decomp3, and this plan so the post-decomp4 ownership story is clear in-repo.
- [x] (2026-04-04 21:32 America/Toronto) Ran the focused proof slices plus the repo-preferred changed-domain proofs from the project-local `.venv`: the parsing-focused pytest slice passed, the bench-focused pytest slice passed, the external-AI upload-bundle pytest slice passed, `./scripts/test-suite.sh domain parsing` finished `245 passed, 172 deselected`, and `./scripts/test-suite.sh domain bench` finished `337 passed`.

## Surprises & Discoveries

- Observation: decomp3 genuinely closed the prior campaign, but it did not eliminate the next three largest coordinator bottlenecks.
  Evidence: post-decomp3 `wc -l` still reports `4697`, `4417`, and `11045` lines for the all-method root, line-role runtime root, and external-AI wrapper.

- Observation: `cookimport/llm/codex_exec_runner.py` is now in a different category from the other three roots.
  Evidence: the runner is down to `2068` lines, while the next roots are `4697`, `4417`, and `11045`. The current root entrypoints show mostly one class plus a modest helper surface, not another obviously dominant unresolved helper band.

- Observation: the line-role runtime still contains three especially visible residual owner seams even after `runtime_taskfile.py` and `runtime_watchdog.py` landed.
  Evidence: the current root still contains `_run_line_role_taskfile_assignment_v1(...)`, `_run_line_role_structured_assignment_v1(...)`, and `_run_line_role_direct_workers_v1(...)` as large embedded bodies.

- Observation: the all-method benchmark root is now bottlenecked by coordinator-sized functions rather than miscellaneous helper clutter.
  Evidence: the current root entrypoint list shows the remaining giant bands concentrated in `_run_all_method_benchmark_global_queue(...)`, `_run_all_method_benchmark(...)`, `_run_all_method_benchmark_multi_source(...)`, and `_interactive_all_method_benchmark(...)`.

- Observation: the external-AI wrapper is no longer one monolith, but the remaining upload-bundle family still dominates the file.
  Evidence: the current entrypoint scan shows the script below line `2400` is still overwhelmingly `def _upload_bundle_*` functions, including stage-report projection, runtime-inventory fallback/merge, scorecard and ablation summaries, regression casebook sampling, and top-regression packet assembly.

- Observation: there is already a separate post-decomposition plan for AI-friendliness guardrails, so decomp4 should not absorb that work.
  Evidence: `docs/plans/2026-04-04_11.58.45_post-decomposition-ai-friendliness-guardrails.md` already exists and is explicitly framed as the next bounded follow-up after decomposition is complete.

- Observation: the late-wrapper pattern was still the safest decomp4 tool for both parsing and the external-AI script, but the script owners needed a root-module resolver rather than a normal direct import to stay safe when the wrapper runs as `__main__`.
  Evidence: `runtime_workers.py` can import the package root directly, while the new external-AI owner modules resolve either `scripts.benchmark_cutdown_for_external_ai` or `__main__` from `sys.modules` so the wrapper can still run as a script without importing a second copy of itself.

- Observation: `codex_exec_runner.py` stopped being the real pressure point once the other three roots were shrunk.
  Evidence: after the decomp4 cuts the tracked roots are `bench_all_method.py=473`, `runtime.py=1375`, `benchmark_cutdown_for_external_ai.py=8543`, and `codex_exec_runner.py=2068`; the remaining direct-exec root is now a much smaller and less urgent coordinator than the external-AI wrapper.

## Decision Log

- Decision: bound decomp4 to the three clearly oversized residual roots first, and treat direct-exec reassessment as optional.
  Rationale: the line counts and current entrypoint shapes show a large gap between the three still-dominant roots and `codex_exec_runner.py`. This keeps the plan honest about where the real remaining value lives.
  Date/Author: 2026-04-04 / Codex

- Decision: front-load line-role and all-method before spending most of the budget on the external-AI wrapper again.
  Rationale: decomp3 already proved that the external-AI wrapper can absorb many turns safely. Decomp4 should avoid letting the largest file consume all remaining attention while the other still-painful coordinator roots stay mostly untouched.
  Date/Author: 2026-04-04 / Codex

- Decision: preserve import-stable and monkeypatch-stable root seams, but keep pushing durable logic behind thin root wrappers or explicit call-time hook resolution.
  Rationale: this repository’s tests still depend on stable root-level seams in several domains. The decomposition goal is not to break those seams; it is to make them thin and explicit.
  Date/Author: 2026-04-04 / Codex

- Decision: do not invent generic utility buckets during this pass.
  Rationale: the earlier waves already established sibling owner-package structure in `cookimport/cli_support/`, `cookimport/parsing/canonical_line_roles/`, and `cookimport/bench/external_ai_cutdown/`. Decomp4 should continue that ownership story instead of diluting it with `utils.py` or `helpers.py`.
  Date/Author: 2026-04-04 / Codex

- Decision: treat line-count reduction as a practical guide, not as the only acceptance signal.
  Rationale: some roots should remain moderately large. Acceptance is that the roots read like real coordinators and the moved logic tells an obvious owner story. Material shrink is expected, but tiny-file fetishism is not the goal.
  Date/Author: 2026-04-04 / Codex

- Decision: after decomp4, remaining follow-up work should move to the separate post-decomposition AI-friendliness guardrails plan instead of creating decomp5 by reflex.
  Rationale: the operator asked whether more decomposition work remains, not for an endless numbered plan series. This plan should be the last decomposition-first follow-through unless a genuinely new structural pain appears later.
  Date/Author: 2026-04-04 / Codex

- Decision: leave `codex_exec_runner.py` alone in decomp4.
  Rationale: once the parsing, bench, and external-AI roots were tightened, the direct-exec root no longer had an equally clean high-value seam. Forcing one more split there would have reopened churn instead of closing the campaign.
  Date/Author: 2026-04-04 / Codex

## Outcomes & Retrospective

This plan is now implemented. The remaining all-method coordinator bands live in `bench_all_method_runtime.py` and `bench_all_method_interactive.py`, the remaining line-role worker/runtime band lives in `runtime_workers.py`, and the dominant remaining external-AI upload-bundle bands live in `stage_reports.py`, `runtime_inventory.py`, and `regression_sampling.py`. The corresponding public roots now read primarily as coordinators and stable wrapper seams instead of giant helper libraries.

The tracked roots ended at `bench_all_method.py=473`, `runtime.py=1375`, `benchmark_cutdown_for_external_ai.py=8543`, and `codex_exec_runner.py=2068`. The external-AI wrapper is still the largest file in the set, but the specific stage-report, runtime-inventory, and regression/triage families that motivated decomp4 are no longer embedded there. The remaining size is now concentrated in later scorecard/breakdown/reporting work rather than the deterministic upload-bundle bands that were the immediate bottleneck.

The practical outcome is that the decomposition campaign should now be considered finished. The remaining roots are not uniformly small, but they are no longer obvious deferred-owner hotspots in the same way, and the focused pytest slices plus repo-preferred `parsing` and `bench` domain proofs are green from `.venv`. The right next follow-up is the already-existing post-decomposition guardrails plan, not another automatic decomposition pass.

## Context and Orientation

This plan starts from the post-decomp3 state. The broad roadmap in [docs/plans/decomp1-large-file-decomposition-roadmap.md](/home/mcnal/projects/recipeimport/docs/plans/decomp1-large-file-decomposition-roadmap.md) established the long arc. The focused cleanup plan in [docs/plans/decomp2-finish-owner-module-decomposition.md](/home/mcnal/projects/recipeimport/docs/plans/decomp2-finish-owner-module-decomposition.md) removed hidden compatibility scaffolding and landed the early owner splits. The completion-oriented plan in [docs/plans/decomp3-complete-remaining-decomposition-end-to-end.md](/home/mcnal/projects/recipeimport/docs/plans/decomp3-complete-remaining-decomposition-end-to-end.md) closed the originally identified remaining wave and left the repo in a green, documented state.

The phrase “coordinator root” matters here. In this repository, a coordinator root is the file that still deserves to be the main entrypoint for a subsystem because it wires together a multi-step workflow and preserves historical test and import seams. A coordinator root should still mostly read as orchestration. It should not keep the next thousand lines of durable helper logic simply because earlier waves stopped at the first safe cut.

The three active roots for decomp4 are:

[cookimport/parsing/canonical_line_roles/runtime.py](/home/mcnal/projects/recipeimport/cookimport/parsing/canonical_line_roles/runtime.py), which still owns the largest line-role taskfile assignment body, the structured-assignment body, and the direct-worker orchestration body even after `runtime_taskfile.py` and `runtime_watchdog.py` were introduced.

[cookimport/cli_support/bench_all_method.py](/home/mcnal/projects/recipeimport/cookimport/cli_support/bench_all_method.py), which still owns the global queue coordinator, the per-source benchmark coordinator, the multi-source coordinator, and the interactive benchmark flow even after scheduler, cache, reporting, quality, targets, variants, and execution owners were extracted.

[scripts/benchmark_cutdown_for_external_ai.py](/home/mcnal/projects/recipeimport/scripts/benchmark_cutdown_for_external_ai.py), which still owns a very large remaining `upload_bundle` family even after the earlier external-AI package owners were introduced. The remaining unresolved bands now cluster around stage-report projection, runtime-inventory reconstruction and fallback merging, triage and casebook sampling, scorecards and ablations, and top-regression packet assembly.

The optional reassessment root is [cookimport/llm/codex_exec_runner.py](/home/mcnal/projects/recipeimport/cookimport/llm/codex_exec_runner.py). It is much smaller than before and may already be “good enough,” but this plan reserves the option to make one last small cut there if a clean seam becomes obvious after the higher-value work is done.

The non-negotiable constraints are unchanged from the earlier waves. Do not change runtime semantics intentionally. Do not break monkeypatch-heavy public seams that tests still depend on. Do not run Codex-backed book processing or benchmark generation without explicit approval. Use `.venv` for Python commands and prefer repo-preferred domain proofs for final validation.

## Plan of Work

The first wave tightens the line-role runtime because it still has the clearest residual owner seams and because decomp3 already showed that parsing could be starved by safer external-AI cuts if it is not front-loaded. Open [cookimport/parsing/canonical_line_roles/runtime.py](/home/mcnal/projects/recipeimport/cookimport/parsing/canonical_line_roles/runtime.py) and treat the remaining large bodies as three separate questions. First, where should the taskfile assignment coordinator live now that `runtime_taskfile.py` already owns taskfile payload building and output-expansion helpers. Second, where should the structured-assignment and repair coordinator live now that the root already has a coherent structured-assignment band. Third, where should the direct-worker orchestration band live so the root stops owning worker threading, progress, result aggregation, and status writing directly. Use existing sibling owners when they can absorb a full responsibility without becoming mixed buckets; otherwise add tightly named siblings such as `runtime_structured.py`, `runtime_direct_workers.py`, or `runtime_progress.py`. Preserve root-level wrappers for any helpers or constants that tests still import from `runtime.py`.

The second wave tightens the all-method benchmark root. Open [cookimport/cli_support/bench_all_method.py](/home/mcnal/projects/recipeimport/cookimport/cli_support/bench_all_method.py) and isolate the remaining durable coordinator families. The global queue runtime, the per-source benchmark runtime, and the interactive benchmark flow are now the obvious remaining blocks. Extract by coherent family, not by single helper. A likely shape is one sibling owner for non-interactive benchmark coordination and one sibling owner for the interactive menu-driven benchmark flow, but the file names should follow the final responsibility split you actually find in code. Preserve the `cookimport.cli` and root monkeypatch surfaces through thin wrappers or explicit call-time hook resolution exactly as earlier bench owners already do.

The third wave tightens the external-AI wrapper, but only after the smaller roots above are no longer the primary unresolved pain points. Open [scripts/benchmark_cutdown_for_external_ai.py](/home/mcnal/projects/recipeimport/scripts/benchmark_cutdown_for_external_ai.py) and continue the same owner-package strategy already established under [cookimport/bench/external_ai_cutdown/](/home/mcnal/projects/recipeimport/cookimport/bench/external_ai_cutdown/). The remaining cuts should follow the current dominant bands, not arbitrary file sizes. The strongest candidates are the recipe-label projection plus stage-report family, the runtime-inventory and prompt-budget fallback family, the triage and regression sampling family, and the higher-level scorecard and breakdown family. The script should keep only intentionally stable wrapper names that tests import or monkeypatch directly.

The fourth wave is the reassessment and closure wave. Measure the residual root sizes and read the roots again after the three main waves. If [cookimport/llm/codex_exec_runner.py](/home/mcnal/projects/recipeimport/cookimport/llm/codex_exec_runner.py) still has one obvious low-risk owner seam, take it and rerun the focused direct-exec proof. If it no longer has a clean seam, record that decision explicitly and leave it alone. Then update the relevant README files and the decomposition plans so the final decomp4 ownership story is visible in-repo. The practical goal is that after this wave, the decomposition effort can stop without ambiguity.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Start by refreshing the current planning context and size markers:

    npm run docs:list
    sed -n '1,260p' docs/PLANS.md
    sed -n '1,260p' docs/plans/decomp1-large-file-decomposition-roadmap.md
    sed -n '1,260p' docs/plans/decomp3-complete-remaining-decomposition-end-to-end.md
    wc -l cookimport/cli_support/bench_all_method.py \
         cookimport/llm/codex_exec_runner.py \
         cookimport/parsing/canonical_line_roles/runtime.py \
         scripts/benchmark_cutdown_for_external_ai.py

Use narrow entrypoint scans before editing so each wave names the correct owner family:

    rg -n '^(def|class) ' cookimport/parsing/canonical_line_roles/runtime.py
    rg -n '^(def|class) ' cookimport/cli_support/bench_all_method.py
    rg -n '^(def|class) ' scripts/benchmark_cutdown_for_external_ai.py

After the line-role wave, prove the touched parsing slice first:

    . .venv/bin/activate
    python -m py_compile \
      cookimport/parsing/canonical_line_roles/runtime.py \
      cookimport/parsing/canonical_line_roles/*.py

    . .venv/bin/activate
    pytest \
      tests/parsing/test_canonical_line_roles_runtime.py \
      tests/parsing/test_canonical_line_roles_taskfile.py \
      tests/parsing/test_line_role_same_session_handoff.py \
      tests/llm/test_label_phase_workers.py -q

After the all-method wave, prove the touched bench slice:

    . .venv/bin/activate
    python -m py_compile \
      cookimport/cli_support/bench_all_method.py \
      cookimport/cli_support/*.py

    . .venv/bin/activate
    pytest \
      tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_targets.py \
      tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_run_reports.py \
      tests/labelstudio/test_labelstudio_benchmark_helpers_scheduler_global_queue.py \
      tests/bench/test_bench.py -q

After the external-AI wave, prove the focused external-AI slice:

    . .venv/bin/activate
    python -m py_compile \
      scripts/benchmark_cutdown_for_external_ai.py \
      cookimport/bench/external_ai_cutdown/*.py

    . .venv/bin/activate
    pytest \
      tests/bench/test_benchmark_cutdown_for_external_ai.py \
      tests/bench/test_benchmark_cutdown_for_external_ai_high_level.py \
      tests/bench/test_benchmark_cutdown_for_external_ai_starter_pack.py \
      tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle.py \
      tests/bench/test_benchmark_cutdown_for_external_ai_upload_bundle_runtime.py -q

Only if the closure wave touches direct-exec again, run the focused direct-exec proof:

    . .venv/bin/activate
    python -m py_compile cookimport/llm/codex_exec_runner.py cookimport/llm/*.py

    . .venv/bin/activate
    pytest \
      tests/llm/test_codex_exec_runner.py \
      tests/llm/test_codex_exec_runner_taskfile.py -q

At the end, run the repo-preferred domain proofs for the domains actually touched. The expected default decomp4 closure set is parsing plus bench, and llm only if `cookimport/llm/` changed:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain parsing

    . .venv/bin/activate
    ./scripts/test-suite.sh domain bench

    . .venv/bin/activate
    ./scripts/test-suite.sh domain llm

Finish by re-measuring the same tracked roots:

    wc -l cookimport/cli_support/bench_all_method.py \
         cookimport/llm/codex_exec_runner.py \
         cookimport/parsing/canonical_line_roles/runtime.py \
         scripts/benchmark_cutdown_for_external_ai.py

The expected terminal signal is that the focused suites and the relevant repo-preferred domain runs finish green, and at least the three primary decomp4 roots are smaller than their current `4697`, `4417`, and `11045` line markers.

## Validation and Acceptance

This plan is complete only when all of the following are true.

First, the remaining line-role root no longer directly owns the large taskfile assignment, structured assignment, and direct-worker orchestration bodies in the form they have today. It may still expose thin wrappers for those operations, but the durable logic must live in explicit sibling owners.

Second, the remaining all-method root no longer directly owns the large global-queue, per-source benchmark, and interactive benchmark bodies in the form they have today. The root may still be the public benchmark seam, but the extracted owners must now tell an obvious story about who owns coordination versus who owns menus versus who owns scheduling.

Third, the external-AI wrapper no longer directly owns the largest remaining deterministic upload-bundle helper bands. A future contributor should be able to identify the responsible external-AI owner module for runtime inventory, stage-report projection, and sampling/reporting work without scanning thousands of wrapper lines.

Fourth, the touched local README files and decomposition plans describe the final seams clearly enough that a cold-start contributor can tell where to edit next.

Fifth, the focused pytest slices and the repo-preferred domain proofs for changed domains finish green from `.venv`.

This plan does not require every tracked root to drop below a universal hard line-count threshold. It does require that the roots stop being obvious deferred-owner hotspots. If a root remains moderately large because it truly is the best place for orchestration, record that explicitly in `Decision Log` and `Outcomes & Retrospective`.

## Idempotence and Recovery

This plan should be implemented as additive extraction plus root shrink, exactly like the prior waves. Re-running the plan is safe as long as the executor refreshes the current root sizes and current entrypoint scans first, then updates the living-document sections to match reality before continuing.

If a proposed extraction proves too entangled, do not abandon the wave entirely. Narrow the wave to the largest still-coherent owner family inside the same root, land that smaller extraction, rerun the focused proof, update the plan, and continue. The point of decomp4 is to finish the remaining high-value cuts without pretending every root must be solved in one heroic rewrite.

If the workspace becomes dirty with unrelated changes in the same files, read the nearby edits carefully and continue only if the writes can be made safely without clobbering other work. Do not revert unrelated work.

## Artifacts and Notes

The key size markers that justified decomp4 were:

    bench_all_method.py: start=4697 final=473 reduction=4224
    codex_exec_runner.py: start=2068 final=2068 reduction=0
    runtime.py: start=4417 final=1375 reduction=3042
    benchmark_cutdown_for_external_ai.py: start=11045 final=8543 reduction=2502

The key current residual entrypoint clusters that justify decomp4 are:

    bench_all_method.py:
      _run_all_method_benchmark_global_queue
      _run_all_method_benchmark_multi_source
      _run_all_method_benchmark
      _interactive_all_method_benchmark

    canonical_line_roles/runtime.py:
      _run_line_role_taskfile_assignment_v1
      _run_line_role_structured_assignment_v1
      _run_line_role_direct_workers_v1

    benchmark_cutdown_for_external_ai.py:
      the remaining _upload_bundle_* analysis, projection, runtime-inventory,
      triage-sampling, scorecard, and top-regression packet families

The expected final decomposition posture after this plan is:

    decomp1 = broad roadmap and historical source of truth
    decomp2 = compatibility cleanup and early owner-split closeout
    decomp3 = end-to-end completion of the originally identified remaining wave
    decomp4 = the last bounded coordinator-tightening pass that still clearly pays for itself

After decomp4, the next planned follow-up should be the separate post-decomposition AI-friendliness guardrails plan, not another default decomposition wave.

## Interfaces and Dependencies

Use the existing owner-package boundaries already established by the prior waves. For all-method work, stay under `cookimport/cli_support/`. For line-role work, stay under `cookimport/parsing/canonical_line_roles/`. For external-AI work, stay under `cookimport/bench/external_ai_cutdown/`. For direct-exec work, stay under `cookimport/llm/`.

Root-level wrappers and re-exports remain acceptable where tests or downstream code still import them directly, but those wrappers must stay thin. Preserve explicit call-time hook resolution where monkeypatch-heavy tests still depend on root-level patchability. Do not reintroduce `sys.modules[...]` plus `globals().update(...)` compatibility tricks.

Validation must continue to use the project-local `.venv`. Do not rely on system Python assumptions, and do not run Codex-backed benchmark or book-processing jobs for proof.

Change note (2026-04-04 / Codex): created this plan because the operator explicitly asked whether more decomposition work remained after decomp3 and wanted a concrete `decomp4` plan. This document answers “yes, but only in a bounded way” and is intended to be the last decomposition-first follow-through unless a genuinely new structural pain appears later.
