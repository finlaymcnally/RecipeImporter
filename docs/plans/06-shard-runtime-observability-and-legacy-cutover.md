---
summary: "ExecPlan for the final shard-runtime cutover: preview, benchmark `prompts/`, `upload_bundle_v1`, CLI/default cleanup, legacy-id removal, and live validation."
read_when:
  - "When updating the human-facing evidence surfaces for the shard-worker runtime."
  - "When removing the old prompt-per-bundle Codex runtime from defaults and active choices."
  - "When preparing the final live benchmark validation for shard-v1 cutover."
---

# Complete The Shard Runtime Cutover And Remove Legacy Runtime Surfaces

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, every human-facing Codex evidence surface in the repo will describe the new shard-worker runtime honestly. Preview will show worker and shard planning rather than prompt counts. Benchmark `prompts/` exports will still exist, but they will map interactions to phase, worker, shard, and owned IDs instead of implying one prompt equals one task. `upload_bundle_v1` will still produce coherent external review packets, but it will render normalized worker/shard telemetry and prompt/debug references. The old prompt-per-bundle runtime ids will no longer appear as active first-class options.

The visible behavior after this plan is complete is that an operator can run worker-centric preview locally, run a live shard-v1 benchmark outside the agent shell, compare it to the baseline, and inspect prompt/debug and upload-bundle evidence without seeing stale prompt-centric mental models anywhere in the active product surface.

## Progress

- [x] (2026-03-17_11.55.05) Derived this child plan from the original shard-runtime ExecPlan while keeping the original untouched.
- [ ] Confirm that the foundation, line-role, recipe, and knowledge child plans have landed or that their runtime artifact schemas are frozen.
- [ ] Update `cookimport/llm/prompt_preview.py` and `cookimport/llm/prompt_budget.py` to describe worker-and-shard plans instead of prompt-centric bundles.
- [ ] Add `cf-debug preview-shard-sweep` and its example config so local shard-setting sweeps are easy to run.
- [ ] Update benchmark `prompts/` export code to preserve reviewer-facing artifacts under the new runtime semantics.
- [ ] Update `upload_bundle_v1` adaptation and rendering so worker/shard telemetry and prompt/debug references stay coherent.
- [ ] Remove old prompt-per-bundle runtime ids from active defaults, choices, and docs, leaving only immediate normalization shims where necessary.
- [ ] Hand off the exact live benchmark commands for final validation outside the agent shell.

## Surprises & Discoveries

- Observation: the shard-v1 cutover is incomplete if only staged outputs change. The main review and debugging surfaces would drift and become misleading.
  Evidence: `docs/understandings/2026-03-17_11.42.56-shard-v1-cutover-must-update-preview-prompts-and-upload-bundle-together.md`.

- Observation: this final plan is cross-cutting by design and should not start too early.
  Evidence: preview, prompt exports, upload bundles, CLI defaults, and live validation all depend on stable runtime artifacts and telemetry from the three phase plans.

## Decision Log

- Decision: this plan owns the final human-facing cutover and legacy removal, not the earlier phase plans.
  Rationale: preview, prompt exports, upload bundles, and defaults are shared surfaces that should move together instead of being edited piecemeal inside each phase migration.
  Date/Author: 2026-03-17 / Codex

- Decision: benchmark `prompts/` exports remain a stable reviewer-facing contract even though their semantics change.
  Rationale: external review and debugging still need those files; the fix is to make them more honest, not to delete them.
  Date/Author: 2026-03-17 / Codex

- Decision: legacy ids may remain readable only as immediate normalization shims during migration.
  Rationale: the end state is burn-the-boats. Old runtime ids must not survive as supported parallel branches.
  Date/Author: 2026-03-17 / Codex

## Outcomes & Retrospective

Implementation has not started yet. The expected outcome is a repo whose active product surfaces all agree about what the shard-worker runtime is. The final retrospective should record whether reviewers and operators found the worker/shard evidence easier to reason about than the old prompt-count proxies and whether any legacy compatibility shims proved unnecessary.

## Context and Orientation

This plan starts after the shared runtime and the three phase migrations are complete or at least stable enough that their runtime artifacts and telemetry schemas will not change underfoot. It owns the operator-facing and reviewer-facing seams that tie those runtime artifacts back into the rest of the product.

The key surfaces are:

- `cookimport/llm/prompt_preview.py` and `cookimport/llm/prompt_budget.py`
- `cookimport/cf_debug_cli.py` for local preview tooling such as `preview-shard-sweep`
- benchmark prompt/debug export code, including `cookimport/llm/prompt_artifacts.py`
- `cookimport/bench/upload_bundle_v1_existing_output.py`
- `cookimport/bench/upload_bundle_v1_render.py`
- settings, CLI, and docs surfaces that still mention old prompt-per-bundle runtime ids

The important point is that these are not implementation leftovers. They are the primary places humans inspect the runtime. If they stay prompt-centric after shard workers land, the refactor will be much harder to validate and debug.

## Milestones

### Milestone 1: Convert preview and local planning tools to worker/shard semantics

Update `cookimport/llm/prompt_preview.py` and `cookimport/llm/prompt_budget.py` so the shard-v1 surfaces plan phase manifests, shard manifests, and worker assignments instead of counting prompt-shaped bundles. Add `cf-debug preview-shard-sweep` and an example config file, preferably `docs/examples/shard_sweep_examples.json`, so operators can compare several worker/shard parameter sets on an existing run root.

Acceptance for this milestone is a local preview run whose summary reports `phase_name`, `worker_count`, `fresh_agent_count`, `shard_count`, `shards_per_worker`, shard-size distribution, first-turn payload distribution, and conservative or observed cost labels instead of raw prompt counts.

### Milestone 2: Preserve benchmark prompt/debug artifacts under the new runtime

Update the benchmark `prompts/` export path so it still writes reviewer-facing artifacts such as `prompts/full_prompt_log.jsonl`, `prompts/prompt_request_response_log.txt`, `prompts/prompt_type_samples_from_full_prompt_log.md`, and `prompts/thinking_trace_summary.*`, but with row semantics that let a reviewer trace phase, worker, shard, and owned IDs.

Acceptance for this milestone is a focused test showing those files still exist and remain useful for review under the new runtime semantics.

### Milestone 3: Update upload bundles and remove legacy runtime surfaces

Update `upload_bundle_v1` adaptation and rendering so bundle-local prompt/debug references still resolve and worker/shard telemetry is visible through the normalized bundle model. Then remove old prompt-per-bundle runtime ids from active CLI choices, defaults, preview semantics, and docs, leaving only immediate normalization shims where a saved setting still needs to parse.

Acceptance for this milestone is a focused test showing bundle-local evidence still resolves plus a code review of settings and CLI surfaces showing no old runtime ids remain as active first-class choices.

### Milestone 4: Hand off exact live benchmark validation

Prepare the final live benchmark commands for a human to run outside the agent shell using the three shard-v1 pipeline ids and the chosen worker/shard settings. Then document how to compare the candidate run against the baseline and what evidence to inspect.

Acceptance for this milestone is a concrete command set that a human can run and a compare report that makes the worker/shard runtime legible.

## Plan of Work

Begin with preview because it is the cleanest read-only planning surface over the new runtime. Rework `cookimport/llm/prompt_preview.py` and `cookimport/llm/prompt_budget.py` so they derive their summaries from phase manifests, shard manifests, worker assignments, and available live telemetry rather than from prompt-shaped reconstruction. Add `cf-debug preview-shard-sweep` once the underlying planning summary is stable.

Then update benchmark prompt/debug exports. Preserve the existing filenames and the general reviewer-facing contract, but change the internal row semantics so a reviewer can map entries back to phase, worker, shard, and owned IDs. Keep these artifacts bundle-friendly because `upload_bundle_v1` depends on them.

Next update `upload_bundle_v1` adaptation and rendering so the normalized bundle model includes worker/shard telemetry and still links back to prompt/debug artifacts coherently. Only after those surfaces are aligned should you remove old prompt-per-bundle runtime ids from active settings, defaults, CLI choices, preview semantics, and docs.

Finish by preparing the live benchmark commands and expected inspection points. This repo blocks live Codex benchmark execution inside agent shells, so the final runtime validation must still be handed off for execution outside the agent shell.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport` and activate the local virtual environment:

    source .venv/bin/activate
    pip install -e .[dev]

Read the relevant context:

    sed -n '1,260p' docs/plans/02-shard-runtime-foundation-runtime-and-config.md
    sed -n '1,260p' docs/plans/03-shard-runtime-line-role-phase-cutover.md
    sed -n '1,260p' docs/plans/04-shard-runtime-recipe-phase-cutover.md
    sed -n '1,260p' docs/plans/05-shard-runtime-knowledge-phase-cutover.md

Run the focused tests as the surfaces land:

    source .venv/bin/activate
    pytest tests/llm/test_phase_worker_preview_sweep.py tests/llm/test_prompt_preview.py -q

    source .venv/bin/activate
    pytest tests/bench/test_upload_bundle_v1_existing_output.py tests/bench/test_upload_bundle_v1_render.py -q

After the focused tests pass, run the LLM-domain wrapper:

    source .venv/bin/activate
    ./scripts/test-suite.sh domain llm

Run local preview against the motivating benchmark root:

    source .venv/bin/activate
    cf-debug preview-shard-sweep \
      --run data/golden/benchmark-vs-golden/2026-03-16_20.23.25 \
      --experiment-file docs/examples/shard_sweep_examples.json \
      --out data/golden/benchmark-vs-golden/2026-03-16_20.23.25/shard_sweeps/<timestamp>

Prepare the live benchmark command for a human to run outside the agent shell:

    source .venv/bin/activate
    cookimport labelstudio-benchmark run \
      --source-file data/input/<book>.epub \
      --gold-spans data/golden/pulled-from-labelstudio/<book>/exports/freeform_span_labels.jsonl \
      --eval-mode canonical-text \
      --no-upload \
      --allow-codex \
      --benchmark-codex-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION \
      --atomic-block-splitter atomic-v1 \
      --line-role-pipeline codex-line-role-shard-v1 \
      --llm-knowledge-pipeline codex-knowledge-shard-v1 \
      --llm-recipe-pipeline codex-recipe-shard-v1 \
      --line-role-worker-count <N> \
      --line-role-shard-target-lines <N> \
      --line-role-shard-max-turns <N> \
      --knowledge-worker-count <N> \
      --knowledge-shard-target-chunks <N> \
      --knowledge-shard-max-turns <N> \
      --recipe-worker-count <N> \
      --recipe-shard-target-recipes <N> \
      --recipe-shard-max-turns <N>

Then compare the candidate to the baseline:

    source .venv/bin/activate
    cookimport labelstudio-benchmark compare \
      --baseline <baseline_run_dir> \
      --candidate <candidate_run_dir> \
      --compare-out data/golden/benchmark-vs-golden/<timestamp>/comparisons

## Validation and Acceptance

This plan is accepted when all of the following are true:

- preview describes worker/shard planning rather than prompt counts
- `cf-debug preview-shard-sweep` exists and writes useful comparison summaries
- benchmark `prompts/` exports still exist and remain reviewer-usable under the new semantics
- `upload_bundle_v1` still renders coherent bundle-local prompt/debug and stage-analysis evidence
- old prompt-per-bundle runtime ids are gone from active defaults and choices
- a human has exact shard-v1 live benchmark commands to run outside the agent shell

The overall shard-runtime refactor is accepted only when the live benchmark compare report, runtime manifests, prompt/debug artifacts, and upload bundle all agree about the new worker/shard model.

## Idempotence and Recovery

Preview sweeps, prompt-export generation, and upload-bundle rendering should all be safe to rerun. If a legacy-id normalization shim still needs to remain temporarily, it must normalize immediately and log the upgrade rather than preserving old runtime behavior. If preview, prompt exports, and upload bundles drift apart during implementation, stop and realign them together before removing old runtime surfaces.

## Artifacts and Notes

The final cutover should preserve these benchmark prompt/debug artifacts:

- `prompts/full_prompt_log.jsonl`
- `prompts/prompt_request_response_log.txt`
- `prompts/prompt_type_samples_from_full_prompt_log.md`
- `prompts/thinking_trace_summary.jsonl`
- `prompts/thinking_trace_summary.md`

The final benchmark bundle cutover should explicitly validate:

- `upload_bundle_overview.md`
- `upload_bundle_index.json`
- `upload_bundle_payload.jsonl`

The final preview and runtime summary should include, per phase and per candidate:

- phase name
- shard-v1 pipeline id
- worker count
- fresh-agent count
- shard count
- shards per worker
- shard-size distribution
- first-turn payload distribution
- promotion success and failure counts
- retry counts
- observed live tokens and turns when available
- benchmark quality verdict relative to baseline

## Interfaces and Dependencies

This plan depends on stable runtime artifacts and telemetry from the foundation, line-role, recipe, and knowledge child plans. It should update or preserve at least these surfaces:

- `write_prompt_preview_for_existing_run(...)` in `cookimport/llm/prompt_preview.py`
- worker/shard-centric summaries in `cookimport/llm/prompt_budget.py`
- `preview-shard-sweep` in `cookimport/cf_debug_cli.py`
- benchmark prompt/debug export seams including `cookimport/llm/prompt_artifacts.py`
- `cookimport/bench/upload_bundle_v1_existing_output.py`
- `cookimport/bench/upload_bundle_v1_render.py`

During migration, legacy ids may still parse, but they must normalize immediately to:

- `codex-line-role-shard-v1`
- `codex-recipe-shard-v1`
- `codex-knowledge-shard-v1`

Revision note: this plan was created by splitting the original shard-runtime ExecPlan into a final cross-cutting cutover plan focused on observability, benchmark surfaces, legacy removal, and live validation.
