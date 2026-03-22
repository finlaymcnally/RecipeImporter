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
- [ ] Create `cookimport/config/run_settings_contracts.py` and move or re-export the contract names and projection helpers there.
- [ ] Make runtime call adapters the default path for stage and benchmark kwargs.
- [ ] Migrate major callers to use the authoritative contract helpers instead of ad hoc payload projection.
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

## Decision Log

- Decision: keep `RunSettings` as the persistence and validation model.
  Rationale: replacing the model would create unnecessary churn. The better move is to make smaller projections and adapters authoritative for normal runtime usage.
  Date/Author: 2026-03-22 / Codex

- Decision: create `cookimport/config/run_settings_contracts.py` as the authoritative home for contract names and projection helpers.
  Rationale: contract logic should be easy to find without opening the entire `RunSettings` field definition file.
  Date/Author: 2026-03-22 / Codex

- Decision: keep temporary re-export shims from `run_settings.py` during migration.
  Rationale: multiple callers already import these helpers. Compatibility shims reduce risk while making the new module the default home.
  Date/Author: 2026-03-22 / Codex

- Decision: promote runtime call adapters to the ordinary path for building stage and benchmark kwargs.
  Rationale: this is the most practical way to make the smaller config surfaces real in code rather than only real in docs.
  Date/Author: 2026-03-22 / Codex

- Decision: keep `run_settings_contracts.py` model-agnostic.
  Rationale: the contracts module should own contract names, field-name groupings, and generic projection helpers, but it should not import `RunSettings` directly because that would blur the boundary and risk circular imports with adapter and model code.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

No code has changed yet. The current outcome is a dedicated execution plan for making config layering real in code without rewriting the underlying persistence model.

The key insight from planning is that the repo already did much of the conceptual work. The remaining effort is to move callers, tests, and docs onto that conceptual shape.

## Context and Orientation

`RunSettings` in [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) is the canonical Pydantic model for saved and normalized per-run settings. It currently contains a very broad field set spanning workers, extraction, parsing, web schema behavior, OCR, LLM settings, benchmark-related settings, and internal tuning baggage. That breadth is acceptable for storage and validation, but it is too wide to be the main interface every runtime caller thinks about.

The repo already exposes several important concepts that this plan should formalize:

1. Contract names such as `full`, `product`, `operator`, `benchmark_lab`, and `internal`.
2. Projection logic through `project_run_config_payload(...)`.
3. Stage and benchmark runtime call builders in [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py).
4. Interactive top-tier profile logic in [cookimport/cli_ui/run_settings_flow.py](/home/mcnal/projects/recipeimport/cookimport/cli_ui/run_settings_flow.py), which already treats the everyday surface as much smaller than the raw model.

The problem is discoverability and authority. A newcomer still has to open `run_settings.py` to understand where the real contracts live, and too many callers still behave like payload projection is incidental instead of foundational.

The new target files for this plan are:

- `cookimport/config/run_settings_contracts.py`
- `cookimport/config/run_settings_adapters.py`

The authoritative responsibilities should be:

- `run_settings.py`: the full `RunSettings` model, field definitions, normalization, and compatibility shims.
- `run_settings_contracts.py`: contract names, field-name groupings, summary ordering, contract normalization, and generic projection helpers that operate on explicit field-name sequences rather than importing `RunSettings`.
- `run_settings_adapters.py`: runtime call builders that turn a `RunSettings` instance into stage or benchmark call kwargs.

The desired effect is progressive disclosure. A contributor deciding “which settings matter for this runtime surface?” should open `run_settings_contracts.py` or `run_settings_adapters.py`, not scan two thousand lines of field definitions first.

The key boundary rule is this: `run_settings_contracts.py` must not import `RunSettings`. Any helper that needs `RunSettings.model_fields` specifically should either stay in `run_settings.py` as a thin wrapper or accept the ordered field names as an explicit argument from the caller.

## Milestones

### Milestone 1: Create the contracts module and move the contract helpers there

At the end of this milestone, `cookimport/config/run_settings_contracts.py` will exist and own the contract constants, field-name grouping helpers, summary ordering, and generic projection helpers. `run_settings.py` may re-export thin model-aware wrappers temporarily, but the new module becomes the canonical home for contract semantics.

Acceptance is that the code still behaves the same and the new module is the obvious place to look for contract logic.

### Milestone 2: Strengthen runtime call adapters as the ordinary runtime surface

At the end of this milestone, [cookimport/config/run_settings_adapters.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings_adapters.py) will be clearly positioned as the owner of stage and benchmark runtime call assembly. If typed wrapper objects such as `StageCallContract` and `BenchmarkCallContract` improve readability, add them here. If plain dict builders remain cleaner, keep them, but make them the default path.

Acceptance is that stage and benchmark runtime builders are explicit and callers stop rebuilding their own kwargs.

### Milestone 3: Migrate major callers onto the contract helpers

At the end of this milestone, the remaining open-coded runtime callers such as CLI stage paths, Label Studio benchmark/import paths, quality runner, quality leaderboard, and interactive flows should use the authoritative contract helpers. `speed_runner.py` already demonstrates the desired adapter pattern and should be treated as a reference caller, not as migration debt. Temporary compatibility shims may remain, but new logic should not be built on ad hoc projection choices.

Acceptance is that the highest-traffic callers no longer need the full `RunSettings` surface to build runtime kwargs.

### Milestone 4: Add tests for contract boundaries

At the end of this milestone, tests will prove that product, operator, benchmark-lab, and internal contracts stay stable and that stage and benchmark call contracts contain the expected fields. This is how the refactor avoids sliding back into a “full model everywhere” posture.

Acceptance is narrow passing tests that fail specifically when a contract boundary drifts.

### Milestone 5: Update docs to teach the smaller config surfaces

At the end of this milestone, CLI and architecture docs should explain the run-setting split as the normal mental model. Readers should learn that `RunSettings` is the storage model, while projections and adapters are the operational interface.

Acceptance is updated docs plus a clean `bin/docs-list` result for touched docs.

## Plan of Work

Start by creating `cookimport/config/run_settings_contracts.py` and moving the contract constants and helpers there. The minimum set is `RUN_SETTING_CONTRACT_*`, `_normalize_run_setting_contract(...)`, the specific grouping functions such as `product_run_setting_names()`, and generic helpers that accept explicit ordered field-name inputs. Keep re-export shims in `run_settings.py` during migration so existing imports do not all have to change in one patch.

Once the contracts module exists, update `run_settings_adapters.py` to import contract-name groupings from it directly where that improves clarity. Then audit the main call sites. The highest-value ones are the CLI stage and benchmark paths, Label Studio paths, quality runner, quality leaderboard, and interactive settings flow. `speed_runner.py` is already a good example and should mostly need import cleanup at most. Move the remaining callers so they consistently use the contract and adapter helpers rather than assembling runtime payloads in their own local way.

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
2. Re-export from `run_settings.py`.
3. Update `run_settings_adapters.py`.
4. Update remaining open-coded callers.
5. Add tests.
6. Update docs.

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

## Idempotence and Recovery

This refactor is safe to do incrementally. Moving contract helpers into a new module with re-export shims is repeatable and low risk. If a caller breaks after migration, restore or keep the old import path temporarily, but do not abandon the new module as the intended home.

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

`run_settings.py` should remain the home of the full `RunSettings` model and validation logic, plus any thin wrappers that bind generic contract helpers to `RunSettings.model_fields`, plus temporary compatibility re-exports while migration proceeds.

## Revision note

Created on 2026-03-22 as one of three standalone child ExecPlans replacing the earlier umbrella AI-readiness refactor plan. Updated later the same day to make the contracts-module boundary model-agnostic, to treat `speed_runner.py` as an existing good seam rather than migration debt, and to anchor validation on the current adapter/signature tests instead of a purely abstract module split.
