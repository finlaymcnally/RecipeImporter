---
summary: "ExecPlan for making run-setting projections and runtime call contracts authoritative without replacing RunSettings as the persistence model."
read_when:
  - "When refactoring config layering around RunSettings, projection helpers, and runtime call adapters."
  - "When deciding which config surfaces are operator-facing, benchmark-lab, or internal."
---

# Make run-setting contracts and runtime call adapters authoritative

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

RecipeImport already knows that its true config surface is smaller than the raw [RunSettings](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) model. The code and docs already distinguish product, operator, benchmark-lab, and internal settings. The problem is that this split is not yet the dominant way callers interact with config. Too many places still behave as if the whole `RunSettings` model is the ordinary interface.

After this change, `RunSettings` should remain the persistence and validation model, but the repo’s day-to-day runtime call surfaces should go through smaller, explicit contract helpers. The visible proof is that command modules, speed/quality runners, Label Studio flows, and summaries build runtime kwargs through authoritative contract helpers instead of ad hoc field selection, and the docs teach the smaller config surfaces as the real mental model.

This plan is standalone. It does not depend on a parent ExecPlan. It replaces the config-layering part of the earlier umbrella plan with one self-contained implementation path.

## Progress

- [x] (2026-03-22 16:57 EDT) Re-ran `bin/docs-list` and read `docs/PLANS.md`, `docs/reports/2026-03-13-run-settings-surface-audit.md`, `docs/02-cli/02-cli_README.md`, `docs/01-architecture/01-architecture_README.md`, and `docs/reports/ai-readiness-improvement-report.md`.
- [x] (2026-03-22 16:59 EDT) Inspected the current config seams in [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py), [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py), [cookimport/cli_ui/run_settings_flow.py](/home/mcnal/projects/recipeimport/cookimport/cli_ui/run_settings_flow.py), [cookimport/bench/speed_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/speed_runner.py), [cookimport/bench/quality_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/quality_runner.py), and [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py).
- [x] (2026-03-22 17:00 EDT) Authored this standalone run-settings contracts ExecPlan in `docs/plans/`.
- [x] (2026-03-22 17:30 EDT) Tightened the extraction boundary after re-checking live imports, adapter usage, and the current tests that already lock adapter signatures.
- [x] (2026-03-22 19:05 EDT) Reworked the plan into a cutover migration: new contracts owner, updated imports, and no lingering compatibility re-exports once the refactor is complete.
- [x] (2026-03-23 17:16 EDT) Re-audited the live tree and confirmed [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py) is now documented as the canonical mapping layer in [cookimport/config/README.md](/home/mcnal/projects/recipeimport/cookimport/config/README.md) and [cookimport/config/CONVENTIONS.md](/home/mcnal/projects/recipeimport/cookimport/config/CONVENTIONS.md).
- [x] (2026-03-23 17:16 EDT) Verified adapter-driven runtime assembly is already the normal path in [cookimport/entrypoint.py](/home/mcnal/projects/recipeimport/cookimport/entrypoint.py), [cookimport/bench/speed_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/speed_runner.py), and several CLI helper paths in [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py).
- [ ] Create `cookimport/config/run_settings_contracts.py` and move the contract names and projection helpers there as the only import home.
- [ ] Finish migrating the remaining high-traffic callers so adapters and contract helpers are the ordinary path everywhere they should be (completed: entrypoint, speed suite, and several CLI benchmark/stage helpers; remaining: summary-heavy and config-projection-heavy callers such as leaderboard, interactive summaries, and quality-run reporting paths).
- [ ] Migrate major callers that still hand-project payloads to the authoritative contract helpers instead of ad hoc field selection.
- [ ] Add narrow tests proving product, operator, benchmark-lab, and internal boundaries.
- [ ] Update CLI and architecture docs so they teach the smaller config surfaces first.

## Surprises & Discoveries

- Observation: the repo already contains most of the conceptual split this plan wants to formalize.
  Evidence: [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) already defines `RUN_SETTING_CONTRACT_FULL`, `RUN_SETTING_CONTRACT_PRODUCT`, `RUN_SETTING_CONTRACT_OPERATOR`, `RUN_SETTING_CONTRACT_BENCHMARK_LAB`, `RUN_SETTING_CONTRACT_INTERNAL`, and `project_run_config_payload(...)`.

- Observation: the runtime adapters already group stage and benchmark call kwargs by surface.
  Evidence: [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py) already separates `_STAGE_OPERATOR_FIELDS`, `_STAGE_BENCHMARK_LAB_FIELDS`, `_STAGE_INTERNAL_FIELDS`, and fixed-behavior fields, with parallel benchmark groupings.

- Observation: the run-settings problem is not that `RunSettings` is invalid. It is that it is too often treated as the everyday interface.
  Evidence: the run-settings audit report and several call sites still move full payloads around even though interactive flows and adapters already suggest a smaller product contract.

- Observation: one important caller family has already moved to the desired adapter path.
  Evidence: [cookimport/bench/speed_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/speed_runner.py) already uses `build_stage_call_kwargs_from_run_settings(...)` and `build_benchmark_call_kwargs_from_run_settings(...)`, so this plan should focus on the remaining open-coded callers rather than redoing already-good seams.

- Observation: a naive extraction of projection helpers can create a cycle or duplicate truth.
  Evidence: [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) currently derives projection order from `RunSettings.model_fields`, while [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py) imports `RunSettings` from that module. Moving model-aware helpers wholesale without a boundary rule would either force `run_settings_contracts.py` to import `RunSettings` or duplicate field-order truth.

- Observation: the repo has already chosen adapters as the operator-facing runtime seam even though contract constants still live in `run_settings.py`.
  Evidence: [cookimport/config/README.md](/home/mcnal/projects/recipeimport/cookimport/config/README.md) and [cookimport/config/CONVENTIONS.md](/home/mcnal/projects/recipeimport/cookimport/config/CONVENTIONS.md) both teach `run_settings_adapters.py` as the canonical mapping layer, and [cookimport/entrypoint.py](/home/mcnal/projects/recipeimport/cookimport/entrypoint.py) uses those builders directly.

## Decision Log

- Decision: keep `RunSettings` as the persistence and validation model.
  Rationale: replacing the model would create unnecessary churn. The better move is to make smaller projections and adapters authoritative for normal runtime usage.
  Date/Author: 2026-03-22 / Codex

- Decision: create `cookimport/config/run_settings_contracts.py` as the authoritative home for contract names and projection helpers.
  Rationale: contract logic should be easy to find without opening the entire `RunSettings` field definition file.
  Date/Author: 2026-03-22 / Codex

- Decision: complete the migration by updating call sites instead of keeping re-export shims in the final state.
  Rationale: the new contracts module only becomes authoritative if callers actually import it directly and the old home stops pretending to own those helpers.
  Date/Author: 2026-03-22 / Codex

- Decision: promote runtime call adapters to the ordinary path for building stage and benchmark kwargs.
  Rationale: this is the most practical way to make the smaller config surfaces real in code rather than only real in docs.
  Date/Author: 2026-03-22 / Codex

- Decision: keep `run_settings_contracts.py` model-agnostic.
  Rationale: the contracts module should own contract names, field-name groupings, and generic projection helpers, but it should not import `RunSettings` directly because that would blur the boundary and risk circular imports with adapter and model code.
  Date/Author: 2026-03-22 / Codex

- Decision: preserve `run_settings_adapters.py` as the existing owner of runtime kwarg assembly instead of re-solving that field grouping in a second new module.
  Rationale: the adapter seam has already landed socially and technically, so the remaining work is to extract contract/projection helpers and finish caller cleanup, not to re-open adapter ownership.
  Date/Author: 2026-03-23 / Codex

## Outcomes & Retrospective

This plan is now partially landed. The runtime-adapter half of the design is real in the current tree, but the contract/projection half is still concentrated in [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py), and several summary-style callers still rely on direct payload projection rather than a smaller dedicated contracts home.

The key implementation lesson so far is that the repo did not need a new abstraction to prove adapter ownership. It needed a smaller second step that moves contract constants and projection helpers out of the model file without undoing the adapter seam that already works.

## Context and Orientation

`RunSettings` in [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) is the canonical Pydantic model for saved and normalized per-run settings. It currently contains a very broad field set spanning workers, extraction, parsing, web schema behavior, OCR, LLM settings, benchmark-related settings, and internal tuning baggage. That breadth is acceptable for storage and validation, but it is too wide to be the main interface every runtime caller thinks about.

The repo already exposes several important concepts that this plan should formalize:

1. Contract names such as `full`, `product`, `operator`, `benchmark_lab`, and `internal`.
2. Projection logic through `project_run_config_payload(...)`.
3. Stage and benchmark runtime call builders in [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py).
4. Interactive top-tier profile logic in [cookimport/cli_ui/run_settings_flow.py](/home/mcnal/projects/recipeimport/cookimport/cli_ui/run_settings_flow.py), which already treats the everyday surface as much smaller than the raw model.

The current state is asymmetric. [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py) is already the canonical mapping from `RunSettings` to concrete stage and benchmark kwargs, and the config docs now say so explicitly. The remaining problem is discoverability and authority for the contract constants and projection helpers themselves. A newcomer still has to open `run_settings.py` to understand where the real contract names live, and too many summary-style callers still behave like payload projection is incidental instead of foundational.

The new target files for this plan are:

- `cookimport/config/run_settings_contracts.py`
- `cookimport/config/run_settings_adapters.py`

The authoritative responsibilities should be:

- `run_settings.py`: the full `RunSettings` model, field definitions, and validation logic.
- `run_settings_contracts.py`: contract names, field-name groupings, summary ordering, contract normalization, and generic projection helpers that operate on explicit field-name sequences rather than importing `RunSettings`.
- `run_settings_adapters.py`: runtime call builders that turn a `RunSettings` instance into stage or benchmark call kwargs.

The desired effect is progressive disclosure. A contributor deciding “which settings matter for this runtime surface?” should open `run_settings_contracts.py` or `run_settings_adapters.py`, not scan two thousand lines of field definitions first.

The key boundary rule is this: `run_settings_contracts.py` must not import `RunSettings`. Any helper that needs `RunSettings.model_fields` specifically should accept the ordered field names as an explicit argument from the caller rather than surviving as a long-lived wrapper in `run_settings.py`.

## Milestones

### Milestone 1: Create the contracts module and move the contract helpers there

At the end of this milestone, `cookimport/config/run_settings_contracts.py` will exist and own the contract constants, field-name grouping helpers, summary ordering, and generic projection helpers. The completed milestone state should update imports to this module rather than leaving re-export aliases in `run_settings.py`.

Acceptance is that the code still behaves the same and the new module is the obvious place to look for contract logic.

### Milestone 2: Strengthen runtime call adapters as the ordinary runtime surface

At the end of this milestone, [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py) will be clearly positioned as the owner of stage and benchmark runtime call assembly. If typed wrapper objects such as `StageCallContract` and `BenchmarkCallContract` improve readability, add them here. If plain dict builders remain cleaner, keep them, but make them the default path.

Acceptance is that stage and benchmark runtime builders are explicit and callers stop rebuilding their own kwargs.

### Milestone 3: Migrate major callers onto the contract helpers

At the end of this milestone, the remaining open-coded runtime callers such as CLI stage paths, Label Studio benchmark/import paths, quality runner, quality leaderboard, and interactive flows should use the authoritative contract helpers. `speed_runner.py` already demonstrates the desired adapter pattern and should be treated as a reference caller, not as migration debt.

Acceptance is that the highest-traffic callers no longer need the full `RunSettings` surface to build runtime kwargs.

### Milestone 4: Add tests for contract boundaries

At the end of this milestone, tests will prove that product, operator, benchmark-lab, and internal contracts stay stable and that stage and benchmark call contracts contain the expected fields. This is how the refactor avoids sliding back into a “full model everywhere” posture.

Acceptance is narrow passing tests that fail specifically when a contract boundary drifts.

### Milestone 5: Update docs to teach the smaller config surfaces

At the end of this milestone, CLI and architecture docs should explain the run-setting split as the normal mental model. Readers should learn that `RunSettings` is the storage model, while projections and adapters are the operational interface.

Acceptance is updated docs plus a clean `bin/docs-list` result for touched docs.

## Plan of Work

Start by creating `cookimport/config/run_settings_contracts.py` and moving the contract constants and helpers there. The minimum set is `RUN_SETTING_CONTRACT_*`, `_normalize_run_setting_contract(...)`, the specific grouping functions such as `product_run_setting_names()`, and generic helpers that accept explicit ordered field-name inputs. Update imports in the same refactor so the new module becomes the direct home rather than a passive sibling.

Once the contracts module exists, update `run_settings_adapters.py` to import contract-name groupings from it directly where that improves clarity, but do not rebuild or relocate the adapter seam itself. Then audit the main call sites. The highest-value ones are the quality runner, quality leaderboard, Label Studio summary/reporting paths, and interactive settings flow. `speed_runner.py`, `entrypoint.py`, and several CLI paths already demonstrate the desired adapter pattern and should mostly need import cleanup at most. Move the remaining callers so they consistently use the contract and adapter helpers rather than assembling runtime payloads in their own local way.

If introducing typed wrapper objects around adapter output improves comprehension, add small dataclasses such as `StageCallContract` and `BenchmarkCallContract`. If that feels like abstraction theater in practice, keep dict-returning helpers. The real requirement is not the wrapper type. The requirement is that runtime call assembly happens in one authoritative place.

Add narrow tests as soon as contract logic moves. Test the projection boundaries directly and test the adapter outputs directly. Extend the existing adapter/signature-sync tests rather than inventing a parallel test style. Then update docs so the new module layout becomes discoverable.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Inspect the current config contract seams:

    rg -n "RUN_SETTING_CONTRACT_|project_run_config_payload|summarize_run_config_payload|product_run_setting_names|ordinary_operator_run_setting_names|benchmark_lab_run_setting_names|internal_run_setting_names" \
      cookimport/config/run_settings.py

    sed -n '1680,1765p' cookimport/config/run_settings.py
    sed -n '1,220p' cookimport/config/run_settings_adapters.py

Inspect major caller surfaces:

    rg -n "project_run_config_payload|build_stage_call_kwargs_from_run_settings|build_benchmark_call_kwargs_from_run_settings|RunSettings.from_dict" \
      cookimport/cli_ui/run_settings_flow.py \
      cookimport/labelstudio/ingest.py \
      cookimport/bench/quality_runner.py \
      cookimport/bench/quality_leaderboard.py

Create the new module with `apply_patch`:

    cookimport/config/run_settings_contracts.py

Migration order:

1. Move contract helpers into the new module.
2. Update `run_settings_adapters.py` imports only where that improves clarity.
3. Update remaining open-coded callers.
4. Add tests.
5. Update docs.

Prepare the environment if needed:

    . .venv/bin/activate
    pip install -e .[dev]

Use narrow diagnostic runs for focused config work:

    . .venv/bin/activate
    pytest tests/cli -k "run_settings or interactive"

    . .venv/bin/activate
    pytest tests/bench -k "quality or speed"

    . .venv/bin/activate
    pytest tests/labelstudio -k "benchmark or import"

Use wrappers for broader routine validation:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain cli

    . .venv/bin/activate
    ./scripts/test-suite.sh domain bench

    . .venv/bin/activate
    ./scripts/test-suite.sh domain labelstudio

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

Refresh docs index after doc updates:

    bin/docs-list

## Validation and Acceptance

Acceptance is that config layering becomes real in code and docs without changing the observable meaning of current runs.

The first acceptance criterion is authority. A contributor should be able to find contract names, field-name groupings, and runtime call assembly in the new dedicated modules without treating `RunSettings` as the only way into the config story.

The second acceptance criterion is caller behavior. Remaining open-coded runtime callers should build their kwargs through the authoritative contract and adapter helpers, not through open-coded field selection.

The third acceptance criterion is narrow proof. Tests must show that product, operator, benchmark-lab, and internal surfaces remain stable and that stage and benchmark adapters include the expected fields and omit accidental extras. Existing adapter tests that compare helper output against command signatures should continue to pass.

The fourth acceptance criterion is local regression safety. The touched CLI, bench, and Label Studio domain wrappers must pass, followed by `./scripts/test-suite.sh fast`.

The fifth acceptance criterion is docs. The architecture and CLI docs, plus any relevant config-oriented notes, must describe the smaller config surfaces as the normal way to think about settings.

The sixth acceptance criterion is deletion. `run_settings.py` must no longer re-export the moved contract helpers in the final state; the new module must be the only import home for them.

## Idempotence and Recovery

This refactor is safe to do incrementally, but the completed end state must not keep re-export shims in `run_settings.py`. If a caller breaks after migration, fix that caller or postpone the cutover; do not preserve a dual-home import story.

If introducing typed call-contract wrappers feels too heavy in practice, drop back to dict-returning helpers and document that decision. The plan’s real objective is authoritative contract assembly, not a particular wrapper style.

## Artifacts and Notes

Keep concise evidence snippets here as work proceeds. Examples:

    rg -n "from cookimport.config.run_settings_contracts" cookimport
    # expected: major callers now import contract helpers from the dedicated module

    ./scripts/test-suite.sh domain bench
    ./scripts/test-suite.sh domain labelstudio
    # expected: runtime call builders still produce working behavior

## Interfaces and Dependencies

In `cookimport/config/run_settings_contracts.py`, define and keep authoritative:

    RUN_SETTING_CONTRACT_FULL = "full"
    RUN_SETTING_CONTRACT_PRODUCT = "product"
    RUN_SETTING_CONTRACT_OPERATOR = "operator"
    RUN_SETTING_CONTRACT_BENCHMARK_LAB = "benchmark_lab"
    RUN_SETTING_CONTRACT_INTERNAL = "internal"

    def normalize_run_setting_contract(...) -> str: ...
    def run_setting_names_for_contract(...) -> tuple[str, ...]: ...
    def project_payload_for_contract(
        payload: Mapping[str, Any] | None,
        *,
        allowed_field_names: Sequence[str],
        contract: str | None = None,
        include_internal: bool | None = True,
    ) -> dict[str, Any]: ...
    def summarize_projected_payload(...) -> str: ...
    def product_run_setting_names() -> tuple[str, ...]: ...
    def ordinary_operator_run_setting_names() -> tuple[str, ...]: ...
    def benchmark_lab_run_setting_names() -> tuple[str, ...]: ...
    def internal_run_setting_names() -> tuple[str, ...]: ...

In `cookimport/config/run_settings_adapters.py`, keep authoritative runtime builders such as:

    def build_stage_call_kwargs_from_run_settings(...) -> dict[str, Any]: ...
    def build_benchmark_call_kwargs_from_run_settings(...) -> dict[str, Any]: ...

Optional typed wrappers are acceptable if they genuinely clarify use. They are not required if plain dict builders remain simpler.

`run_settings.py` should remain the home of the full `RunSettings` model and validation logic only. The moved contract helpers should live in `run_settings_contracts.py`, and callers should import them from there directly.

## Revision note

Created on 2026-03-22 as one of three standalone child ExecPlans replacing the earlier umbrella AI-readiness refactor plan. Updated later the same day to make the contracts-module boundary model-agnostic, to treat `speed_runner.py` as an existing good seam rather than migration debt, to anchor validation on the current adapter/signature tests, and then again to a burn-the-boats posture with no final-state re-export shims. Updated on 2026-03-23 after re-auditing the live tree so the plan now reflects that adapter ownership has already landed while the contracts/projection extraction remains outstanding.
