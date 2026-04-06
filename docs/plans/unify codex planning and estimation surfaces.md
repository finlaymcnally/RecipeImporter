---
summary: "ExecPlan for replacing split shard-estimation stories with one authoritative Codex phase-planning artifact and render-accurate estimator."
read_when:
  - When unifying interactive shard planning, prompt preview, live preflight, and post-run Codex cost reporting
  - When fixing knowledge-stage shard oversizing caused by requested shard counts overriding budget-safe packetization
  - When making prompt and shard estimates come from actual rendered payloads instead of rough parallel estimators
---

# Unify Codex Planning And Estimation Surfaces

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, there will be one authoritative planning artifact for each Codex-backed phase. The interactive shard picker, prompt preview, live preflight, and post-run reporting will all read from that same plan instead of rebuilding partial truths in different ways. A user choosing shard counts in interactive mode will see the same survivability recommendations and the same natural packetization pressure that the live runtime sees, and a finished run will show predicted-versus-observed drift against the exact plan that launched it. The operator-selected shard count in the interactive CLI remains authoritative unless an explicit existing sanity clamp fires or the request is structurally invalid; the planner’s job is to explain the consequences clearly, not silently replace the choice with a different live count.

This matters because the current system can know something important in one place and silently drop it in another. The observed April 6, 2026 single-book benchmark for `saltfatacidheatcutdown` proved that failure mode. The knowledge planner recorded a warning that budget-based packetization wanted `24` shards, but the runtime still forced the queue down to the requested `10` shards, and the interactive planner did not surface that warning. The result was oversized classification packets, missing row coverage, repair churn, and a token bill dominated by resumed-session overhead instead of semantic work.

The visible proof after implementation is:

1. The interactive Codex step planner shows the operator request, the survivability recommendation for conservative token/session safety, the budget-native shard count that falls out of packetization, and the launch shard count the runtime will actually use.
2. A prompt preview generated from deterministic prep writes the same phase-plan artifact the live run will use, including warnings and the exact rendered prompt sizes that drove the estimate.
3. Live execution preserves the operator-selected shard count unless an explicit surfaced sanity clamp or a structurally invalid request prevents launch. It does not silently rewrite `5` into `32`, and survivability stays advisory rather than blocking.
4. Post-run artifacts compare observed token usage back to the exact plan that launched, so prediction drift is measurable instead of anecdotal.

## Progress

- [x] (2026-04-06 11:33 America/Toronto) Read `docs/PLANS.md`, `docs/01-architecture/01-architecture_README.md`, `docs/02-cli/02-cli_README.md`, `docs/07-bench/07-bench_README.md`, and `docs/10-llm/10-llm_README.md`.
- [x] (2026-04-06 11:33 America/Toronto) Inspected the current interactive planner in `cookimport/cli_ui/run_settings_flow.py` and `cookimport/cli_support/interactive_flow.py`.
- [x] (2026-04-06 11:33 America/Toronto) Inspected the current prompt-preview and deterministic recommendation path in `cookimport/staging/deterministic_prep.py`, `cookimport/cli_support/bench_single_book.py`, and `cookimport/llm/prompt_preview.py`.
- [x] (2026-04-06 11:33 America/Toronto) Inspected the current knowledge planning and runtime path in `cookimport/llm/codex_farm_knowledge_jobs.py`, `cookimport/llm/knowledge_stage/runtime.py`, and `cookimport/llm/knowledge_stage/workspace_run.py`.
- [x] (2026-04-06 11:33 America/Toronto) Wrote this first-pass ExecPlan.
- [x] (2026-04-06 12:02 America/Toronto) Corrected the plan after product clarification: interactive CLI shard counts are authoritative and must not be silently rewritten upward to budget-native packetization.
- [x] (2026-04-06 12:18 America/Toronto) Corrected the plan again after product clarification: survivability is advisory guidance, not a hard launch gate for risky shard counts.
- [ ] Define and land one canonical phase-plan schema and writer that every Codex-backed surface can read.
- [ ] Move knowledge, recipe, and line-role planning onto that shared plan builder so packetization, survivability, and UI recommendations all describe the same thing.
- [ ] Make estimation render-accurate by counting the actual prompt text and actual structured payload shape that runtime will send.
- [ ] Update interactive planner, preview artifacts, and post-run reporting to show operator request, survivability recommendation, budget-native shards, launch shards, and prediction drift from one shared artifact.
- [ ] Validate the new planner on the April 6, 2026 benchmark case and prove that the knowledge stage truthfully reports requested `10` versus budget-native `24` without silently rewriting the operator’s choice.

## Surprises & Discoveries

- Observation: The current knowledge planner already computes budget-based row partitions, then discards them when `knowledge_prompt_target_count` is set.
  Evidence: `cookimport/llm/codex_farm_knowledge_jobs.py` first calls `_partition_rows_by_budget(...)`, stores `packet_count_before_partition`, and then calls `_repartition_rows_to_target_count(...)` when the operator requested a shard count. The April 6, 2026 run artifact recorded the warning: `knowledge_prompt_target_count is using the requested final shard count of 10; packet-budget planning would have split the queue into 24 shards.`

- Observation: The interactive planner is not a completely separate estimator, but it is a separate reporting surface that drops the most important warning.
  Evidence: the benchmark interactive flow calls `_build_single_book_interactive_shard_recommendations(...)` in `cookimport/cli_support/bench_single_book.py`, which runs `build_shard_recommendations_from_prep_bundle(...)`. That path goes through prompt preview and preserves survivability summaries, but the row model in `cookimport/cli_ui/run_settings_flow.py` only renders `minimum_safe_shard_count`, `binding_limit`, and compact averages. It does not render budget-native shard count or planner warnings.

- Observation: Current estimates are mixing real rendered prompt counts with rough text-only proxies.
  Evidence: the prompt-preview planner stores exact prompt character counts for preview rows in `cookimport/llm/prompt_preview.py`, but the knowledge job builder still uses `_estimate_row_input_chars(...)`, `_estimate_pass1_input_chars(...)`, and `_estimate_pass2_input_chars(...)`, which do not count the full rendered instruction wrapper, ontology payload, or exact JSON response shape.

- Observation: The April 6, 2026 knowledge classification packets were far larger than the configured input budget implied.
  Evidence: the run’s `classification_initial_prompt.txt` files were roughly `60k-82k` characters each while the configured `knowledge_packet_input_char_budget` was `18000`. Several initial responses omitted owned rows entirely, for example `100 -> 92`, `100 -> 98`, `99 -> 72`, and `99 -> 97`, and one shard returned `99` rows with local indices `0..98` that matched none of the owned block indices.

- Observation: `invalid_category` is overloading two different failures.
  Evidence: `cookimport/llm/knowledge_stage/task_file_contracts.py` uses `invalid_category` both for truly illegal category values and for unanswered units whose default `category` remains `null`. That made omitted rows look like a semantic-label problem when they were really a coverage-contract problem.

## Decision Log

- Decision: In the interactive CLI, requested shard count remains an operator-authoritative runtime contract unless an explicit surfaced sanity clamp or structurally invalid request prevents launch.
  Rationale: The product requirement is that choosing `1/1/1` yields `1/1/1` and choosing `5/5/5` does not secretly launch `5/5/32`. The unified planner must make low-shard risk obvious, but it must not silently replace the user’s answer with a different shard topology.
  Date/Author: 2026-04-06 / Codex

- Decision: The canonical phase plan will distinguish at least four counts: `requested_shards`, `survivability_recommended_shards`, `budget_native_shards`, and `launch_shards`.
  Rationale: The current single-number story mixes operator intent, conservative safety guidance, packetization quality, and actual launched topology. Those are different facts and need to be visible separately in the UI and artifacts.
  Date/Author: 2026-04-06 / Codex

- Decision: Survivability warnings stay advisory for launchable shard counts and do not become automatic runtime blockers.
  Rationale: The operator wants the ability to choose a risky shard count knowingly. The planner should surface likely failure modes such as oversized prompts, repair churn, or token blowups, but should not paternalistically refuse to run unless the request is actually invalid or impossible to construct.
  Date/Author: 2026-04-06 / Codex

- Decision: Render-accurate estimation wins over rough text-length proxies wherever the runtime can already construct the actual prompt.
  Rationale: The repo already has prompt renderers for preview and runtime. Counting anything smaller than the real prompt body is guaranteed to drift, and that drift is especially harmful when the estimate is used for shard sizing.
  Date/Author: 2026-04-06 / Codex

- Decision: The first implementation will keep one shared planner artifact and adapter seams, not one giant cross-stage rewrite in a single file.
  Rationale: recipe, line-role, and knowledge have different prompt builders and work-unit definitions, but they still need one common artifact schema and one common reporting story. A shared planner core with stage-specific adapters keeps the change large but survivable.
  Date/Author: 2026-04-06 / Codex

## Outcomes & Retrospective

- Outcome: Not started yet. This initial ExecPlan captures the current split-planner problem, the concrete April 6, 2026 failure evidence, and the intended unified design.
  Remaining work: implement the shared phase-plan artifact, migrate stage planners, update UI/reporting consumers, and validate the new behavior against the benchmark case that exposed the issue.
  Lesson: shard planning cannot be treated as a cosmetic UI hint. In this repo it is a runtime contract that directly controls token cost, correctness pressure, and repair churn.

## Context and Orientation

This repository has several Codex-facing planning surfaces that currently talk about shard counts and prompt budgets, but they do not all describe the same thing.

`cookimport/cli_ui/run_settings_flow.py` owns the interactive Codex step planner. It renders one row per Codex-backed surface and currently shows a short note built from survivability summaries and prompt-preview averages. The user sees labels such as the main binding limit, average prompt size, average session size, and average work per shard.

`cookimport/cli_support/interactive_flow.py` and `cookimport/cli_support/bench_single_book.py` own the interactive benchmark setup path. In single-book benchmark mode they resolve deterministic prep first, then build interactive shard recommendations by calling `build_shard_recommendations_from_prep_bundle(...)`.

`cookimport/staging/deterministic_prep.py` bridges deterministic prep to prompt preview. Its `build_shard_recommendations_from_prep_bundle(...)` function writes prompt-preview artifacts from a deterministic processed run, then projects summary fields such as `minimum_safe_shard_count` and `binding_limit` back into the interactive row model.

`cookimport/llm/prompt_preview.py` owns the zero-token prompt preview path. It builds preview rows for recipe, knowledge, and line-role using each stage’s current input builder and prompt renderer, then annotates those rows with survivability summaries. This file already knows the exact rendered prompt text for preview rows, but it is not the single authority for live planning.

`cookimport/llm/shard_survivability.py` owns the current deterministic token/session safety preflight. It takes shard-level token estimates and answers the question “what shard count would this phase conservatively recommend so it stays inside prompt, output, session-peak, and work-unit caps?” This is the current owner of `minimum_safe_shard_count`, which this plan will reframe as advisory guidance rather than a launch gate.

`cookimport/llm/codex_farm_knowledge_jobs.py` owns the current knowledge packet builder. This file is the most important evidence for the present bug. It first partitions review rows by configured packet budgets, but when the operator requested a final shard count it repartitions the whole queue into that requested count, even when the budget-based partitioner wanted many more packets. That is how the April 6, 2026 knowledge classification phase ended up with ten shards of roughly one hundred blocks each.

`cookimport/llm/knowledge_stage/runtime.py` owns live knowledge execution. It calls `build_knowledge_jobs(...)`, writes a survivability report, and launches the inline-JSON worker runtime in `cookimport/llm/knowledge_stage/workspace_run.py`.

`cookimport/llm/knowledge_stage/workspace_run.py` owns the current inline-JSON knowledge call loop. It persists the initial classification call, optional classification repairs, grouping calls, and grouping repairs under one structured session. This is where resumed-session token reuse amplified the cost of oversized packets.

`cookimport/llm/prompt_budget_runtime.py` and the benchmark artifacts such as `prompt_budget_summary.json` own post-run cost summaries. These report totals after the fact, but they do not currently point back to one canonical phase plan artifact that explains why the runtime chose a given shard topology.

The core term used in this plan is a “phase plan.” A phase plan is a deterministic JSON artifact that describes how one Codex-backed stage will be partitioned before launch. It contains the operator request, the real launched shard topology, the rendered prompt sizes that informed the estimate, the safety and quality constraints that influenced the recommendations, and the warnings a human should see before paying for the run.

## Plan of Work

### Milestone 1: Define one authoritative phase-plan artifact

In this milestone, the repo gains one shared module for phase-planning results. Create a new shared planner owner under `cookimport/llm/` that defines a stable schema for one phase plan and one run-level collection of phase plans. The artifact must be precise enough that a future reader can tell the difference between the operator’s request, the packetization the planner wanted naturally, the conservative survivability recommendation, and the shard count that actually launched.

The schema must include, at minimum, the stage key, stage label, requested shard count, survivability-recommended shard count from conservative budgeting, budget-native shard count from natural packetization, launch shard count used by live execution, warnings, invalid-request errors if launch is disallowed, and one row per launch shard. Each shard row must include its owned identifiers, rendered prompt size, estimated output size, estimated peak session size, and a work-unit metric whose label is meaningful for that stage such as `recipes`, `lines`, or `chars`.

The acceptance proof for this milestone is one shared JSON file written by prompt preview for a deterministic sample run, plus a focused unit test that builds a phase plan for a mocked stage and verifies that the artifact records request, natural packetization, survivability guidance, and launched topology separately.

### Milestone 2: Move stage-specific planners behind shared adapters

In this milestone, recipe, line-role, and knowledge each provide a stage-specific adapter to the shared planner instead of inventing independent planning stories. The adapters are responsible for preparing candidate work items and rendering the actual prompt text for a provisional shard. The shared planner is responsible for counting prompt and output budgets, computing conservative survivability guidance, characterizing natural packetization pressure, and assembling the final phase plan artifact.

For knowledge, replace the current `build_knowledge_jobs(...)` override behavior with a two-track contract. First, build the budget-native analysis from actual rendered prompt size and output estimates so the planner can say what packetization it naturally wants. Second, build the launch topology from the operator-selected shard count, subject only to explicit existing sanity clamps and truly invalid launch requests. If the operator requested fewer shards than the natural plan, record that risk as a warning. If the operator requested fewer shards than the survivability recommendation, record a stronger warning with the binding limit and likely failure modes, but still preserve the chosen shard count.

For recipe and line-role, preserve the existing semantics of requested shard count where they remain valid, but still emit the same canonical phase-plan artifact and compute survivability recommendation versus natural packetization through the same shared contract. When any stage applies an upper-bound clamp or reject path, that outcome must be explicit in the phase plan and the interactive UI.

The acceptance proof for this milestone is a set of focused tests that build phase plans for all three stages and show that each stage can now produce one shared artifact shape with stage-specific work-unit labeling and shard rows.

### Milestone 3: Make estimation render-accurate

In this milestone, rough text-only proxies are replaced or sharply reduced. The planner must estimate from the actual rendered prompt text that runtime will send whenever the stage already has a prompt renderer. For inline-JSON knowledge, that means counting the exact prompt body produced by the same structured prompt builder the runtime uses, including instruction wrapper, packet JSON, ontology, and any repair-specific validation feedback. For recipe and line-role, count the exact taskfile or inline prompt text produced by their current prompt builders instead of relying on lightweight proxies.

When exact rendered output cannot be known cheaply, keep conservative deterministic output estimators, but store the method used in the plan artifact so drift is auditable later. The phase plan schema must therefore record an estimator version or method note for prompt, output, and session-peak estimates.

The acceptance proof for this milestone is an updated prompt-preview artifact where knowledge classification shard prompt sizes now match the actual rendered prompt files written for preview, and a test that verifies prompt-counting paths call the same prompt renderer the runtime uses.

### Milestone 4: Update all consumers to read the same artifact

In this milestone, the interactive planner, preview artifacts, live preflight, and post-run reporting all read from the shared phase plan. The interactive planner in `cookimport/cli_ui/run_settings_flow.py` must render both survivability guidance and packetization pressure. Each row should show:

- requested shards
- survivability-recommended shards
- budget-native shards
- launch shards
- the main binding limit for the survivability recommendation
- the planner warning when the operator’s request is below the budget-native count
- any clamp or invalid-request error that would prevent the request from launching as entered

The preview artifact written by `cookimport/llm/prompt_preview.py` must store the same phase plan JSON that live runtime would use. The live knowledge, recipe, and line-role runtimes must persist the plan artifact before worker launch and record the exact `launch_shards` used for execution. Post-run summaries must read that plan artifact and attach predicted-versus-observed deltas to it rather than keeping prediction and actual cost as separate stories.

The acceptance proof for this milestone is a deterministic single-book preview where the interactive recommendation payload, the saved preview manifest, and the live phase plan all agree on the same requested, survivability-recommended, budget-native, and launch shard counts.

### Milestone 5: Validate against the known failure case

In this milestone, use the `saltfatacidheatcutdown` deterministic prep bundle and the April 6, 2026 benchmark settings to prove that the unified planner catches the exact failure mode that motivated this plan. The planner must report that the knowledge stage naturally wants more than ten shards. The interactive planner must surface that fact. The live runtime must preserve the operator’s chosen ten shards while recording that they are coarser than both the budget-native plan and the conservative survivability recommendation.

The acceptance proof is a before-and-after comparison:

- before: the historical run artifact warning says budget planning wanted `24` shards but execution used `10`
- after: the new phase plan artifact records requested `10`, budget-native `24`, and launch `10`, and the interactive UI renders a warning before launch

This milestone is complete only when the same benchmark settings produce one truthful planning story end to end: the UI, preview artifacts, and live runtime all agree that the operator asked for `10`, the planner naturally wanted `24`, the survivability guidance recommended a higher count, and launch still used `10`.

## Concrete Steps

Run all commands from `/home/mcnal/projects/recipeimport`.

Prepare the local environment if needed:

    test -x .venv/bin/python || python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .[dev]

Capture the current motivating evidence before changing code:

    . .venv/bin/activate
    python - <<'PY'
    import json
    from pathlib import Path
    prompt_budget = Path("data/golden/benchmark-vs-golden/2026-04-06_10.31.48/single-book-benchmark/saltfatacidheatcutdown/codex-exec/prompt_budget_summary.json")
    knowledge_manifest = Path("data/output/2026-04-06_10.31.48/single-book-benchmark/saltfatacidheatcutdown/codex-exec/2026-04-06_10.32.24/raw/llm/saltfatacidheatcutdown/knowledge_manifest.json")
    print(json.loads(prompt_budget.read_text())["by_stage"]["nonrecipe_finalize"]["cost_breakdown"])
    print(json.loads(knowledge_manifest.read_text())["planning_warnings"])
    PY

Expected evidence excerpt:

    {
      "billed_total_tokens": 18851604,
      "cached_input_tokens": 7487488,
      "protocol_overhead_tokens_total": 10903442,
      "semantic_payload_tokens_total": 460674
    }
    [
      "knowledge_prompt_target_count is using the requested final shard count of 10; packet-budget planning would have split the queue into 24 shards."
    ]

During implementation, keep the loop narrow:

    . .venv/bin/activate
    pytest tests/llm -q
    pytest tests/cli -q
    pytest tests/staging -q

Add focused tests for the new shared planner as they are introduced. The expected pattern is that tests fail before the shared phase-plan migration, then pass once the planner and its consumers are updated.

Use prompt preview as the first end-to-end validation tool because it is zero-token and deterministic:

    . .venv/bin/activate
    cf-debug preview-prompts \
      data/output/<deterministic-run-or-prep-run-root> \
      --out /tmp/phase-plan-preview

After the shared planner is wired in, inspect the resulting preview manifest and verify that each phase stores one canonical phase plan with matching requested, survivability-recommended, budget-native, and launch shard counts.

## Validation and Acceptance

Acceptance is based on behavior, not only on code movement.

The change is accepted when all of the following are true:

1. Interactive single-book benchmark planning shows one consistent shard story per Codex surface. When the user chooses a knowledge shard count below the budget-native count or below the survivability recommendation, the row must visibly warn about that risk while still showing the chosen launch count.
2. Prompt preview writes one phase-plan artifact per stage that includes rendered prompt size, requested shards, survivability-recommended shards, budget-native shards, launch shards, and planner warnings.
3. Live runtime writes the same phase-plan artifact before launch and preserves the requested shard count unless an explicit surfaced clamp or invalid request check prevents launch.
4. Post-run reporting attaches observed token usage back to the recorded phase plan and shows prediction drift without inventing a second planning story.
5. The motivating April 6, 2026 knowledge case truthfully reports requested `10` versus natural `24`-packet planning without silently rewriting the user’s answer.

Concrete validation steps:

- Run focused tests for the shared planner and stage adapters. Expect the new planner tests and updated CLI tests to pass.
- Run prompt preview from a deterministic prep bundle for `saltfatacidheatcutdown` and verify that the knowledge phase plan records requested `10`, budget-native `24`, and launch `10`.
- Run the interactive single-book benchmark planner for the same source and verify that the knowledge row shows the operator request, the survivability recommendation, and the budget-native warning instead of only a single minimum-safe count.
- Run a controlled benchmark or fake-Codex rehearsal and verify that the live knowledge stage plan artifact matches the preview plan for the same settings.

## Idempotence and Recovery

The planner migration should be additive first. New shared plan artifacts and adapters should be introduced before old per-surface summaries are removed. This keeps prompt preview, interactive planning, and live execution debuggable during the migration.

If a stage migration is only partially complete, do not leave that stage with two conflicting sources of truth. The temporary state must still funnel every consumer through one adapter-owned shared artifact, even if some legacy fields are duplicated for compatibility.

The deterministic preview path is the safest retry mechanism. If live planning changes are unclear, regenerate preview artifacts from the same deterministic prep bundle and compare the saved phase-plan JSON instead of rerunning paid Codex work.

## Artifacts and Notes

The most important historical evidence for this plan is the April 6, 2026 benchmark pair:

    data/golden/benchmark-vs-golden/2026-04-06_10.31.48/single-book-benchmark/saltfatacidheatcutdown/codex-exec/prompt_budget_summary.json
    data/output/2026-04-06_10.31.48/single-book-benchmark/saltfatacidheatcutdown/codex-exec/2026-04-06_10.32.24/raw/llm/saltfatacidheatcutdown/knowledge_manifest.json

The first proves that the run spent most of its tokens on the knowledge stage rather than on recipe correction. The second proves that the planner already knew ten shards were too coarse for budget-native packetization.

This plan should create a new durable artifact family under the live and preview roots, preferably alongside existing stage manifests:

    raw/llm/<workbook_slug>/<stage>/phase_plan.json
    raw/llm/<workbook_slug>/<stage>/phase_plan_summary.json

The exact filenames may change during implementation, but the plan artifact must be easy to find from both preview and live stage roots and must be stable enough for benchmark/reporting readers.

## Interfaces and Dependencies

Define one shared planner owner under `cookimport/llm/`. The final name may be `phase_plan.py`, `phase_planning.py`, or a small package, but it must provide:

- a stable phase-plan dataclass or JSON-serializable builder result
- a stage-adapter interface that can:
  - enumerate candidate work items
  - build a provisional shard from contiguous items
  - render the exact prompt text for that shard
  - estimate output/session-peak conservatively when exact output is not available
- one function that takes a stage adapter plus operator request and returns the canonical phase plan

Update these current owners to consume that shared planner:

- `cookimport/llm/codex_farm_knowledge_jobs.py`
- `cookimport/llm/prompt_preview.py`
- `cookimport/staging/deterministic_prep.py`
- `cookimport/cli_ui/run_settings_flow.py`
- `cookimport/llm/knowledge_stage/runtime.py`
- `cookimport/llm/recipe_stage_shared.py`
- `cookimport/parsing/canonical_line_roles/runtime.py` or the current line-role runtime owner
- `cookimport/llm/prompt_budget_runtime.py`

The planner must keep using `cookimport/llm/shard_survivability.py` for conservative token/session guidance, but survivability becomes one consumer of the shared phase plan rather than a sibling story. The planner must also keep using each stage’s existing prompt builder so estimation stays tied to runtime reality.

Revision note: Created this plan on 2026-04-06 because the current repo has split planning surfaces that can disagree silently. The immediate trigger was the April 6, 2026 benchmark where knowledge planning knew budget-native packetization wanted 24 shards but runtime and interactive UI still centered the requested 10-shard story. Updated later the same day to match the actual product contract: interactive shard counts remain authoritative, and the unified planner must warn clearly rather than silently rewriting the user’s chosen counts. Updated again later the same day to make survivability advisory rather than a hard launch gate for risky-but-launchable shard counts.
