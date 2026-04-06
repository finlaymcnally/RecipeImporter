---
summary: "ExecPlan for making repair and recovery budgets, decisions, telemetry, and docs explicit across recipe, line-role, and knowledge transports."
read_when:
  - When consolidating same-session repair, fresh-session retry, fresh-worker replacement, or watchdog retry behavior across Codex-backed stages
  - When reconciling `docs/reports/repair-analysis.md` against the code
  - When changing repair/recovery reporting in recipe, line-role, or knowledge runtime artifacts
---

# Unify Codex Repair And Recovery Policy

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

This plan builds on two earlier checked-in ExecPlans: `docs/plans/2026-04-04_23.33.14 - taskfile worker runtime simplification and de-bloating.md` and `docs/plans/2026-04-06_11.14.02 - single-turn knowledge grouping per shard.md`. The first already identified retry and session-state machinery as an unfinished shared-runtime extraction. The second already simplified one major knowledge-stage fanout that made repair accounting harder to reason about. This document is the narrower follow-on that turns the remaining scattered repair and recovery rules into one explicit contract without flattening the real stage differences.

## Purpose / Big Picture

After this change, a user will be able to answer three concrete questions from one code-verified story instead of reverse-engineering several stage-local loops.

The first question is, “what kinds of another try does this stage allow?” The answer must clearly distinguish answer repair from worker recovery. The second question is, “how many of each are allowed for this stage and transport?” The answer must come from one declarative policy surface instead of scattered hard-coded constants and nearly duplicated helper functions. The third question is, “what actually happened in this run?” The answer must be visible in existing runtime summaries and telemetry without opening half a dozen stage-local artifacts.

This matters because the current runtime already has the right philosophical boundary, but the implementation is still split across several owners. Recipe, line-role, and knowledge each preserve slightly different repair and recovery behavior, and those differences are correct. What is missing is one explicit policy layer and one shared vocabulary. Today the repo can do the right thing and still be hard to reason about. After this change, the behavior stays fail-closed and stage-specific, but the rules, budgets, and outcomes become inspectable and intentionally designed.

The visible proof after implementation is:

1. Focused fake-Codex tests still show the same stage outcomes: recipe keeps one same-session repair rewrite plus bounded recovery, line-role keeps one structured repair follow-up on the inline path and one bounded recovery story on the taskfile path, and knowledge keeps its multi-step classification or grouping behavior without silently changing semantic authority.
2. Stage summaries and telemetry make the contract legible. A reader can see the allowed policy budget and the spent counts for repair rewrites, structured repair follow-ups, fresh-session retries, fresh-worker replacements, and watchdog retries.
3. `docs/10-llm/10-llm_README.md` becomes the durable source of truth for this contract, while `docs/reports/repair-analysis.md` becomes historical context rather than an unverified parallel spec.

## Progress

- [x] (2026-04-06 11:19 America/Toronto) Read `docs/PLANS.md`, `docs/reports/repair-analysis.md`, `docs/10-llm/10-llm_README.md`, and `docs/01-architecture/01-architecture_README.md`.
- [x] (2026-04-06 11:19 America/Toronto) Inspected the current owner seams for repair and recovery in `cookimport/llm/recipe_stage/worker_io.py`, `cookimport/llm/recipe_stage_shared.py`, `cookimport/parsing/canonical_line_roles/runtime_recovery.py`, `cookimport/parsing/canonical_line_roles/runtime_workers.py`, `cookimport/llm/knowledge_stage/workspace_run.py`, `cookimport/llm/knowledge_stage/recovery.py`, `cookimport/llm/knowledge_stage/reporting.py`, and `cookimport/llm/task_file_guardrails.py`.
- [x] (2026-04-06 11:19 America/Toronto) Re-read the earlier taskfile-runtime and knowledge-grouping ExecPlans to avoid duplicating already-planned work and to scope this plan as the missing repair/recovery contract slice.
- [x] (2026-04-06 11:19 America/Toronto) Wrote this first-pass ExecPlan.
- [ ] Add one shared repair/recovery policy module under `cookimport/llm/` that declares budgets, follow-up kinds, and reason-taxonomy helpers for all active Codex stages and transports.
- [ ] Migrate recipe, line-role, and knowledge to consume that shared policy surface for gating decisions instead of using stage-local magic numbers and duplicated helper logic.
- [ ] Standardize runtime telemetry and stage summaries so they report both allowed budgets and actual spent counts for repair and recovery.
- [ ] Update durable docs in `docs/10-llm/10-llm_README.md` and stage owner READMEs so the shared vocabulary and per-stage matrix are code-verified and easy to find.
- [ ] Add focused tests that prove the shared policy is the single source of truth and that each stage still preserves its intended follow-up behavior.

## Surprises & Discoveries

- Observation: recipe and line-role taskfile fresh-session retry policy are almost the same code, but they live in different owners and therefore drift risk is already real.
  Evidence: `cookimport/llm/recipe_stage/worker_io.py::_should_attempt_recipe_fresh_session_retry(...)` and `cookimport/parsing/canonical_line_roles/runtime_recovery.py::_should_attempt_line_role_fresh_session_retry(...)` both gate on the same concepts: budget left, not already completed, not `repair_exhausted`, not a hard boundary failure, clean session exit, and preserved useful progress.

- Observation: knowledge already has two distinct repair surfaces, not one.
  Evidence: `cookimport/llm/knowledge_stage/workspace_run.py` performs same-session taskfile repair during classification and grouping, while later in the same file and in `cookimport/llm/knowledge_stage/recovery.py` the runtime can still attempt one explicit packet-style repair when a final shard output exists but is not promotable.

- Observation: the current runtime vocabulary still mixes mechanism and intent.
  Evidence: names such as `repair_required`, `repair_packet_exhausted`, `fresh_session_retry`, `fresh_session_recovery`, `watchdog_retry`, and `fresh_worker_replacement` are all present, but they are spread across stage-local status payloads and are not generated from one shared reason model.

- Observation: structured inline behavior is already bounded, but those bounds are encoded as isolated stage-local literals.
  Evidence: `cookimport/llm/knowledge_stage/workspace_run.py` sets `_STRUCTURED_KNOWLEDGE_MAX_REPAIR_FOLLOWUPS = 3`, while `cookimport/parsing/canonical_line_roles/runtime_workers.py` hard-wires a single `repair_packet_01.json` flow for inline line-role.

- Observation: the repo already has the right telemetry seam for this change, so this plan should extend reporting rather than invent new artifact families.
  Evidence: `cookimport/llm/task_file_guardrails.py` already emits worker-session guardrails, `cookimport/llm/knowledge_stage/reporting.py` already rolls up repair packet counts, and recipe plus line-role stage summaries already expose repair-attempt rollups and follow-up status.

- Observation: this plan should not try to force one monolithic generic runtime loop as its first move.
  Evidence: the remaining differences are real, not accidental. Knowledge has semantic steps, line-role has a thin inline path plus watchdog behavior, and recipe still keeps a helper-driven taskfile contract. The missing piece is a shared policy layer and shared reporting vocabulary, not immediate total runtime unification.

## Decision Log

- Decision: Keep the distinction between answer repair and worker recovery explicit in code, docs, and telemetry.
  Rationale: `docs/reports/repair-analysis.md` is correct about the core mental model. Repair means the answer exists but failed deterministic validation. Recovery means the worker session itself failed to finish cleanly enough. Mixing those surfaces makes budgets and outcomes impossible to reason about.
  Date/Author: 2026-04-06 / Codex

- Decision: Centralize policy declarations before attempting a larger shared execution-loop rewrite.
  Rationale: the repo already has stage-specific loops that work. The immediate risk is that budgets, reason codes, and reporting drift apart. A declarative policy layer is a smaller, safer slice and a likely prerequisite for any deeper shared-runtime extraction later.
  Date/Author: 2026-04-06 / Codex

- Decision: Preserve stage-specific differences instead of flattening them into one global retry count.
  Rationale: knowledge genuinely has separate classification and grouping steps, recipe is still taskfile-only, and line-role inline repair is intentionally stingier than knowledge inline repair. The right abstraction is a shared vocabulary plus per-stage and per-step policy rows, not “one retry setting to rule them all.”
  Date/Author: 2026-04-06 / Codex

- Decision: Make `docs/10-llm/10-llm_README.md` the authoritative documentation target and demote `docs/reports/repair-analysis.md` to historical narrative context.
  Rationale: a report is useful for diagnosis, but the durable contract needs to live in the owning docs section that already claims responsibility for live LLM runtime behavior.
  Date/Author: 2026-04-06 / Codex

- Decision: Extend existing stage summaries and telemetry instead of creating a new standalone repair artifact tree.
  Rationale: the repo already has many artifacts. The operator should be able to answer policy and spent-count questions from the existing stage summary, promotion report, and telemetry files rather than from one more special-case output family.
  Date/Author: 2026-04-06 / Codex

## Outcomes & Retrospective

This section will be updated after implementation and focused validation.

## Context and Orientation

This repository has three live Codex-backed semantic stages that matter for this plan.

Recipe refine is taskfile-only. The worker edits a repo-written `task.json`, the repo validates the edited answer fields, and same-session repair happens by rewriting `task.json` into repair mode. Fresh-session retry and fresh-worker replacement are separate recovery surfaces. The current recipe recovery gates live mainly in `cookimport/llm/recipe_stage/worker_io.py`, while the main worker-session orchestration still lives in `cookimport/llm/recipe_stage_shared.py`.

Canonical line-role supports both taskfile and inline JSON transport. The taskfile path uses the same broad shape as recipe: edit `task.json`, validate, optionally repair, and optionally recover by retrying or replacing the worker. The taskfile recovery rules live in `cookimport/parsing/canonical_line_roles/runtime_recovery.py`, while the actual worker orchestration lives in `cookimport/parsing/canonical_line_roles/runtime_workers.py`. The inline path also lives in `runtime_workers.py`; it sends one structured packet, validates the answer, and currently allows at most one structured repair follow-up for unresolved rows.

Knowledge or nonrecipe finalize is the most layered stage. It has two semantic steps, classification and grouping. In taskfile mode, those steps run in one same-session workflow in `cookimport/llm/knowledge_stage/workspace_run.py`, and each step may rewrite `task.json` into repair mode if validation fails. The same stage can also spend one fresh-session retry, one fresh-worker replacement, and one later packet-style repair attempt when the final shard output exists but still is not promotable. The packet and watchdog logic for that later repair surface lives in `cookimport/llm/knowledge_stage/recovery.py`. Knowledge reporting lives in `cookimport/llm/knowledge_stage/reporting.py`, and legacy packet-state enums still exist in `cookimport/llm/knowledge_runtime_state.py`.

For this plan, a “taskfile repair rewrite” means deterministic repo code narrowing a task file to only the failed units and sending the worker back into the same assignment. A “structured repair follow-up” means deterministic repo code sending another JSON packet or resumed session prompt for only the unresolved surface. A “fresh-session retry” means re-entering the same worker workspace because the first session ended cleanly enough and left useful repo-owned progress behind. A “fresh-worker replacement” means discarding the poisoned worker session and re-running the original repo-authored assignment on a new worker session. A “watchdog retry” means a recovery attempt triggered by worker termination or missing durable output rather than by invalid answer shape.

The current problem is not that the repo lacks repair or recovery. It already has them. The problem is that the contract is encoded in too many places:

- duplicated taskfile recovery predicates in recipe and line-role,
- stage-local hard-coded structured repair budgets in line-role and knowledge,
- mixed terminology across summaries and status files,
- and one report file, `docs/reports/repair-analysis.md`, that explains the system more cleanly than the code exposes it.

The aim of this plan is therefore to make the live code match the clarity of that mental model without pretending the stages are more uniform than they really are.

## Plan of Work

Start by introducing one shared repair and recovery policy owner under `cookimport/llm/`. A good target is a small module or package such as `cookimport/llm/repair_recovery_policy.py` plus, if needed, a companion reporting helper file. This owner must not run the stages. Its job is to declare the vocabulary and budgets that the stages consume. The policy surface should describe, for each stage and transport, which follow-up kinds are allowed, what the budget is for each kind, whether the budget is stage-wide or step-local, and what the canonical reason labels are for spending or skipping that follow-up.

Design that policy surface around the real runtime shape instead of around a false generic ideal. A useful policy object should be able to express facts such as “recipe taskfile allows one same-session repair rewrite, one fresh-session retry, and one fresh-worker replacement,” “line-role inline allows one structured repair follow-up plus watchdog retry behavior,” and “knowledge taskfile allows one repair rewrite for classification, one repair rewrite for grouping, one fresh-session retry, one fresh-worker replacement, and one later packet-style repair when final output exists but is still invalid.” The important part is that these rows live in one place and can be rendered into both gating helpers and human-readable reporting.

Once the shared policy exists, migrate the gating logic without over-generalizing the runtime loops. Recipe and line-role taskfile recovery should stop hard-coding their nearly identical retry and replacement predicates in different files. The shared module should expose stage-neutral helpers for “should we spend a fresh-session retry?” and “should we spend a fresh-worker replacement?” that accept stage-owned facts such as useful progress, hard-boundary failure, completion state, and current budget counters. The stage owners still decide how to measure useful progress and what counts as authoritative completion; the shared helper decides the budget and the canonical skip or spend reason.

Then migrate structured repair budgets. In canonical line-role inline mode, replace the implicit single repair packet flow in `cookimport/parsing/canonical_line_roles/runtime_workers.py` with a policy-driven `max_structured_repair_followups` lookup that still resolves to `1` today. In knowledge structured mode, replace `_STRUCTURED_KNOWLEDGE_MAX_REPAIR_FOLLOWUPS = 3` with the same shared policy surface, still resolving to `3` today for classification and grouping. The goal is not to change behavior first. The goal is to move the authority for the number into one explicit policy table.

After the budgets are shared, standardize reporting. Extend existing runner payloads, stage rows, and stage summaries so every stage reports two things separately: the allowed budget and the spent count. For example, a taskfile worker row should be able to tell the reader “fresh-session retry budget = 1, spent = 0” and “fresh-worker replacement budget = 1, spent = 1.” Knowledge stage reporting should keep its packet-economics rollups but add the policy row that explains why `repair_packet_count_total` exists and what the cap was. Line-role and recipe summaries should include the same normalized field names even if the stage-specific values differ.

At the same time, normalize reason vocabulary. Do not break existing public reason codes that current tests or dashboards may already read. Instead, add a small shared normalized layer, something like `followup_kind`, `followup_surface`, `budget_scope`, `policy_reason_code`, and `policy_reason_detail`, and map stage-local reason codes into that shared vocabulary. This is the piece that turns raw details such as `same_session_repair_exhausted`, `hard_boundary_failure`, or `preserved_progress_without_completion` into one comparable cross-stage story.

Then update the durable docs. `docs/10-llm/10-llm_README.md` should gain a small code-verified policy matrix that uses the exact shared vocabulary and budgets. Keep it concise and aligned to the code. Update `cookimport/llm/knowledge_stage/README.md`, `cookimport/parsing/canonical_line_roles/README.md`, and `cookimport/llm/recipe_stage/README.md` so each owner README explains only the stage-specific differences and points back to the shared policy surface for the common terms. Finally, add a short note at the top or bottom of `docs/reports/repair-analysis.md` stating that it is a narrative analysis and that the authoritative live contract now lives in `docs/10-llm/10-llm_README.md` plus the shared policy module.

Finish with tests that prove the shared policy is real authority rather than dead metadata. Add one focused policy test module under `tests/llm/` that asserts the current stage and transport matrix directly. Then update owner tests so they no longer hard-code independent retry counts when those counts should now come from the shared policy. Keep the current stage behavior stable while making the policy source explicit.

## Milestone 1: Freeze The Current Contract In One Policy Table

In this milestone, no user-visible behavior changes yet. The goal is to capture the current live contract in a shared declarative module. At the end of the milestone, a novice can open one file and answer which repair and recovery surfaces each stage and transport currently allows, along with the current budgets.

Acceptance is a focused test module that asserts the shared policy table directly and proves at least these current rows: recipe taskfile, line-role taskfile, line-role inline, knowledge taskfile, and knowledge inline classification or grouping.

## Milestone 2: Move Taskfile Recovery Gating Behind Shared Helpers

In this milestone, recipe and line-role stop owning their own retry-budget predicates. At the end of the milestone, those taskfile surfaces still use their stage-local notions of useful progress and authoritative completion, but fresh-session retry and fresh-worker replacement decisions flow through one shared helper and one shared reason taxonomy.

Acceptance is that the focused recipe and line-role recovery tests still pass, but the budget values and normalized reason labels come from the shared policy module instead of from duplicated stage-local literals.

## Milestone 3: Make Structured Repair Budgets Policy-Driven

In this milestone, inline line-role and structured knowledge stop hiding their repair caps inside owner files. At the end of the milestone, canonical line-role inline repair still performs at most one structured repair follow-up, and knowledge inline classification or grouping still allows the current bounded number of repair follow-ups, but those numbers come from the shared policy module and are visible in reporting.

Acceptance is that the existing inline-runtime tests still pass and the emitted telemetry rows include both the spent repair count and the allowed budget.

## Milestone 4: Normalize Reporting And Stage Summaries

In this milestone, repair and recovery become legible in runtime artifacts. At the end of the milestone, recipe, line-role, and knowledge all expose the same shared follow-up vocabulary in their stage rows and summaries even though the actual counts differ by stage.

Acceptance is that a reader can inspect one representative stage summary or telemetry file per surface and answer three questions without reading code: what follow-up kinds were allowed, what the budget was, and what was actually spent.

## Milestone 5: Update Durable Docs And Demote The Narrative Report

In this milestone, the docs tree catches up to the code. At the end of the milestone, `docs/10-llm/10-llm_README.md` is the authoritative explanation of repair and recovery policy, stage owner READMEs describe only their local differences, and `docs/reports/repair-analysis.md` is clearly marked as narrative context rather than the canonical live contract.

Acceptance is that a new contributor can start from the docs tree, find the owner modules quickly, and see the same policy matrix that the tests enforce.

## Concrete Steps

All commands below are run from `/home/mcnal/projects/recipeimport`.

Prepare the project-local virtual environment if needed:

    test -x .venv/bin/python || python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .[dev]

During the policy extraction, keep the loop narrow and stage-focused:

    . .venv/bin/activate
    pytest tests/llm/test_recipe_phase_workers.py tests/llm/test_recipe_same_session_handoff.py -q
    pytest tests/parsing/test_canonical_line_roles_runtime.py tests/parsing/test_canonical_line_roles_runtime_recovery.py tests/parsing/test_line_role_same_session_handoff.py -q
    pytest tests/llm/test_knowledge_same_session_handoff.py tests/llm/test_knowledge_orchestrator_runtime_leasing.py tests/llm/test_knowledge_grouping_contract.py tests/llm/test_knowledge_phase_workers_packets.py -q

Add one new focused shared-policy test module once the policy file exists:

    . .venv/bin/activate
    pytest tests/llm/test_repair_recovery_policy.py -q

After the focused loops are green, run the normal fast suite:

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

If a current stage-summary fixture exists or a fake-Codex integration test already snapshots stage rows, update it so the new policy-budget fields are asserted explicitly instead of only by indirect totals.

## Validation and Acceptance

The change is correct when all of the following are true:

1. The shared policy module can describe the live current behavior of recipe, line-role, and knowledge without flattening important differences such as knowledge’s per-step budgets or line-role’s transport split.
2. Recipe and line-role taskfile recovery tests still prove one bounded fresh-session retry and one bounded fresh-worker replacement, but the budget and skip or spend reasons come from the shared policy helpers.
3. Inline line-role still performs at most one structured repair follow-up, and inline knowledge still performs its current bounded repair follow-ups, but those caps no longer live as stage-local magic numbers.
4. Stage summaries and telemetry rows expose both allowed budgets and actual spent counts for repair and recovery.
5. `docs/10-llm/10-llm_README.md` matches the code and the tests, and `docs/reports/repair-analysis.md` is no longer an orphan parallel contract.

## Idempotence and Recovery

This refactor should be done additively and safely. Start by introducing shared policy declarations and reporting fields before deleting any stage-local constants or helper functions. When moving a budget or reason label into the shared module, keep the existing stage-local field names alive until the tests and docs prove the replacement is stable.

Do not change semantic ownership boundaries while doing this work. Deterministic code must still validate and package evidence, and LLM surfaces must still make the fuzzy semantic call. This plan is about explicit policy and reporting, not about making deterministic code “smarter” about cookbook semantics.

If a migration step exposes a real mismatch between `docs/reports/repair-analysis.md` and the code, the code and owning docs win. Record that mismatch in `Surprises & Discoveries`, update the shared policy table to match the real runtime, and then revise the narrative report note accordingly.

## Artifacts and Notes

Current code evidence that motivates this plan:

    recipe taskfile recovery
    - `cookimport/llm/recipe_stage/worker_io.py`
    - owns `_should_attempt_recipe_fresh_session_retry(...)`
    - owns `_should_attempt_recipe_fresh_worker_replacement(...)`

    line-role taskfile recovery
    - `cookimport/parsing/canonical_line_roles/runtime_recovery.py`
    - owns `_should_attempt_line_role_fresh_session_retry(...)`
    - owns `_should_attempt_line_role_fresh_worker_replacement(...)`

    line-role inline repair
    - `cookimport/parsing/canonical_line_roles/runtime_workers.py`
    - writes one `repair_packet_01.json`
    - currently encodes “one repair follow-up” in the flow itself

    knowledge inline repair
    - `cookimport/llm/knowledge_stage/workspace_run.py`
    - `_STRUCTURED_KNOWLEDGE_MAX_REPAIR_FOLLOWUPS = 3`
    - loops classification and grouping repairs from that constant

    knowledge extra post-taskfile repair
    - `cookimport/llm/knowledge_stage/recovery.py`
    - still owns packet-style repair and watchdog retry helpers after same-session taskfile work is done

Those are exactly the seams this plan should turn into one explicit shared contract.

## Interfaces and Dependencies

Introduce one shared policy owner under `cookimport/llm/` with stable names that stage code can import directly. A good target interface is:

    @dataclass(frozen=True)
    class FollowupBudget:
        kind: str
        surface: str
        max_attempts: int
        scope: str

    @dataclass(frozen=True)
    class StageTransportPolicy:
        stage_key: str
        transport: str
        semantic_step_key: str | None
        allowed_followups: tuple[FollowupBudget, ...]

    def get_stage_transport_policy(
        *,
        stage_key: str,
        transport: str,
        semantic_step_key: str | None = None,
    ) -> StageTransportPolicy: ...

    def should_attempt_fresh_session_retry(
        *,
        policy: StageTransportPolicy,
        current_attempt_count: int,
        completed: bool,
        final_status: str | None,
        hard_boundary_failure: bool,
        completed_successfully: bool,
        useful_progress_preserved: bool,
    ) -> tuple[bool, str]: ...

    def should_attempt_fresh_worker_replacement(
        *,
        policy: StageTransportPolicy,
        current_attempt_count: int,
        completed: bool,
        catastrophic_reason_code: str | None,
        retryable_exception_reason: str | None,
    ) -> tuple[bool, str]: ...

    def build_followup_budget_summary(
        *,
        policy: StageTransportPolicy,
        spent_counts: Mapping[str, int],
    ) -> dict[str, Any]: ...

The stage owners that must consume this surface are:

- `cookimport/llm/recipe_stage/worker_io.py`
- `cookimport/llm/recipe_stage_shared.py`
- `cookimport/parsing/canonical_line_roles/runtime_recovery.py`
- `cookimport/parsing/canonical_line_roles/runtime_workers.py`
- `cookimport/llm/knowledge_stage/workspace_run.py`
- `cookimport/llm/knowledge_stage/recovery.py`
- `cookimport/llm/knowledge_stage/reporting.py`

Keep `cookimport/llm/task_file_guardrails.py` as the home for taskfile-size and session-cap reporting, but extend its summary payloads or compose them with the new follow-up budget summaries rather than inventing a second unrelated guardrail shape.

Revision note (2026-04-06 11:19 America/Toronto): created this ExecPlan after reviewing `docs/reports/repair-analysis.md`, the owning LLM docs, and the current recipe, line-role, and knowledge repair or recovery seams. The purpose of this first revision is to turn that narrative analysis into a code-facing refactor plan with concrete owners, validation, and acceptance criteria.
