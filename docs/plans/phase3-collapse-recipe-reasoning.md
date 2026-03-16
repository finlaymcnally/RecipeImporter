# Collapse Recipe Reasoning Into One LLM Correction Stage

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

This plan assumes Recommended Migration Strategy Phase 1 and Phase 2 from `docs/plans/Refactor.md` are already implemented in the main stage runtime. In practical terms, that means the stage path already has truthful stage naming, stable block provenance, deterministic block labels, and deterministic recipe-span grouping driven by those labels. Phase 3 starts from grouped recipe spans and does not spend time re-solving labeling or grouping.

## Purpose / Big Picture

After this change, each grouped recipe span should have exactly one recipe-focused LLM correction call. Deterministic code will first build an intermediate recipe object from the labeled span, the LLM will correct that object and emit an ingredient-to-step linkage payload, and deterministic code will then build the final `RecipeDraftV1` output from those two artifacts.

The user-visible proof is simple. A stage run with recipe Codex enabled should no longer create or report a three-pass recipe pipeline. In plan mode it should show one recipe correction stage per recipe span, and in execute mode it should write one recipe-correction raw folder plus a correction audit, while still producing both intermediate JSON-LD outputs and final cookbook outputs.

## Progress

- [x] (2026-03-15_22.21.11) Re-read `docs/PLANS.md` and the relevant migration section in `docs/plans/Refactor.md` before drafting this ExecPlan.
- [x] (2026-03-15_22.21.11) Re-read `docs/10-llm/10-llm_README.md`, `docs/02-cli/02-cli_README.md`, and `cookimport/staging/README.md` to ground the plan in the current LLM, CLI, and writer contracts.
- [x] (2026-03-15_22.21.11) Traced the current recipe LLM seam through `cookimport/llm/codex_farm_orchestrator.py`, `cookimport/llm/codex_farm_contracts.py`, `cookimport/staging/import_session.py`, and `cookimport/staging/draft_v1.py`.
- [x] (2026-03-15_22.21.11) Recorded the key architectural finding in `docs/understandings/2026-03-15_22.21.11-phase3-single-correction-seam.md`.
- [x] (2026-03-15_22.21.11) Wrote this ExecPlan.
- [ ] Introduce the Phase 3 correction contract and deterministic span-to-intermediate builder.
- [ ] Replace the current three-pass and merged-repair recipe orchestration with one canonical recipe-correction stage.
- [ ] Add deterministic final-assembly support for explicit linkage payloads and remove the need for full final-draft LLM overrides.
- [ ] Update run settings, CLI labels, benchmark/Label Studio compatibility shims, and prompt artifacts so the new single-stage naming is the product truth.
- [ ] Add focused tests, run domain validation, and verify plan-mode plus execute-mode behavior on a small real import.

## Surprises & Discoveries

- Observation: the repo already proved that one recipe LLM call can produce both intermediate and final override families.
  Evidence: `cookimport/llm/codex_farm_orchestrator.py::_build_merged_repair_input(...)` plus the merged-repair branch of `run_codex_farm_recipe_pipeline(...)` already populate both `intermediate_overrides_by_recipe_id` and `final_overrides_by_recipe_id` from one LLM output.

- Observation: deterministic final assembly is not real yet, even in the merged-repair branch.
  Evidence: `cookimport/staging/draft_v1.py::recipe_candidate_to_draft_v1(...)` always recomputes step linkage with `assign_ingredient_lines_to_steps(...)` and does not accept an explicit LLM-supplied mapping override.

- Observation: the writer seam is already good enough for this refactor.
  Evidence: `cookimport/staging/import_session.py` threads `schemaorg_overrides_by_recipe_id` and `draft_overrides_by_recipe_id` directly into `cookimport/staging/writer.py`, so Phase 3 can change how those overrides are produced without rewriting the output writers.

- Observation: most of the remaining complexity is semantic naming and compatibility, not raw Codex execution mechanics.
  Evidence: the merged-repair path is already exposed through `codex-farm-2stage-repair-v1`, but manifests, raw folder names, tests, and benchmark artifact readers still describe recipe work through `pass1`, `pass2`, and `pass3` compatibility slots.

## Decision Log

- Decision: treat Phase 2 grouped recipe spans as the authoritative input to this plan and remove recipe chunking from the primary LLM recipe pipeline.
  Rationale: this plan exists only because labeling and grouping are assumed complete. Keeping LLM chunking in the main path would reintroduce the architectural problem that earlier phases were meant to remove.
  Date/Author: 2026-03-15 / Codex

- Decision: use `RecipeCandidate` as the corrected intermediate recipe object and `RecipeDraftV1` as the final output object.
  Rationale: these are already the stable writer-facing models in `cookimport/core/models.py`, and reusing them avoids inventing a third recipe representation during the migration.
  Date/Author: 2026-03-15 / Codex

- Decision: introduce one canonical product-facing recipe pipeline name, `codex-farm-single-correction-v1`, and keep `codex-farm-2stage-repair-v1` as a compatibility alias during migration.
  Rationale: Phase 1 requires observability to describe reality. “Merged repair” is a historical implementation detail, while “single correction” describes the target architecture. Keeping the old value as an alias avoids breaking saved settings and benchmark fixtures in one step.
  Date/Author: 2026-03-15 / Codex

- Decision: introduce one canonical pack pipeline id, `recipe.correction.compact.v1`, and normalize `recipe.merged-repair.compact.v1` to it while compatibility support remains.
  Rationale: the pack should advertise the same architecture the product now implements. A compatibility alias is cheaper than forcing every existing test artifact to update at once.
  Date/Author: 2026-03-15 / Codex

- Decision: deterministic final assembly must consume the LLM linkage payload directly rather than collapsing back to heuristic assignment.
  Rationale: without this, Phase 3 would still spend tokens on final-draft generation or would silently ignore the linkage payload that the refactor explicitly wants to preserve.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

No implementation has been performed yet. The main outcome of this planning pass is a concrete migration path that reuses the current merged-repair seam, adds the missing deterministic final-assembly capability, and makes single-stage recipe correction the truthful runtime story instead of a prototype branch.

The biggest remaining risk is compatibility surface area. Recipe LLM execution touches stage runs, benchmark prediction generation, Label Studio normalization, prompt artifact exports, and report readers. This plan keeps that manageable by preserving read-time aliases while making the write path tell the truth immediately.

## Context and Orientation

Phase 3 begins after deterministic label-first grouping already exists. A “recipe span” in this plan means one deterministically grouped set of ordered labeled blocks that represent a single recipe candidate. Each block already has a stable identity, text, label, and provenance. The grouped span is the evidence the LLM may inspect; it is not allowed to rediscover recipe boundaries or relabel the book.

The current stable recipe models already exist in `cookimport/core/models.py`. `RecipeCandidate` is the intermediate schema.org-like recipe object used by stage writers and scoring code. `RecipeDraftV1` is the final cookbook output model. `ConversionResult` carries the active recipes plus report metadata.

The current recipe LLM path lives in `cookimport/llm/codex_farm_orchestrator.py`. Today it supports a legacy three-pass route and a two-stage merged-repair prototype. Contract models for those routes live in `cookimport/llm/codex_farm_contracts.py`. The stage writer seam already exists: `cookimport/staging/import_session.py` collects LLM override payloads and `cookimport/staging/writer.py` writes intermediate JSON-LD and final draft files from either deterministic builders or overrides.

The final-builder gap is in `cookimport/staging/draft_v1.py`. That module deterministically converts a `RecipeCandidate` into `RecipeDraftV1`, including ingredient parsing, instruction segmentation, and ingredient-to-step assignment. Right now it has no way to consume an explicit linkage payload, so the merged-repair prototype works only by writing a complete final-draft override. Phase 3 closes that gap so the final draft becomes deterministic again.

This plan must also update the public naming and compatibility surface. Run setting enums live in `cookimport/config/run_settings.py`. CLI behavior and interactive prompts live in `cookimport/cli.py` and are documented in `docs/02-cli/02-cli_README.md`. Label Studio prediction-run normalization lives in `cookimport/labelstudio/ingest.py`. Prompt-pack assets live under `llm_pipelines/pipelines/`, `llm_pipelines/prompts/`, and `llm_pipelines/schemas/`.

Because Phase 2 file names are not guaranteed in the current working tree, this plan defines one local normalization seam inside the recipe LLM path: Phase 3 code must adapt whatever grouped-span artifact exists into a local “prepared recipe correction input” structure before calling Codex. That makes the implementation self-contained even if earlier phase code was named differently.

## Milestones

### Milestone 1: Define the single correction contract and deterministic intermediate builder

At the end of this milestone, the recipe pipeline should have one explicit contract for the only remaining recipe LLM stage. Add a new correction input/output model in `cookimport/llm/codex_farm_contracts.py`, or in a closely related new module if that file becomes too crowded. The input must carry recipe identity, ordered evidence rows, block provenance needed for audits, the deterministic intermediate `RecipeCandidate` payload, and any narrow structural hints that make correction cheaper without turning the LLM into a boundary detector. The output must carry a corrected intermediate recipe payload, an `ingredient_step_mapping`, an optional `ingredient_step_mapping_reason`, and warnings.

In the same milestone, add a deterministic builder module that converts one grouped recipe span into the intermediate `RecipeCandidate`. Use the existing parser and shaping helpers wherever possible instead of inventing a new recipe model. The builder should preserve the grouped span’s block ids and label provenance inside the candidate’s `provenance` so later audits can compare deterministic versus corrected output.

Acceptance for this milestone is that one test can construct a grouped span fixture, build the deterministic intermediate object, serialize a correction input bundle, load a correction output bundle back into validated models, and do all of that without referencing legacy pass2/pass3 contract names.

### Milestone 2: Replace recipe-pass orchestration with one correction stage

At the end of this milestone, the main recipe Codex path in `cookimport/llm/codex_farm_orchestrator.py` should stop planning and executing pass1/pass2/pass3 for the canonical product route. The canonical route should prepare one correction bundle per grouped recipe span, call one pack pipeline, validate one correction output, and record one recipe-correction manifest row.

Reuse as much of the existing merged-repair machinery as possible. The current merged-repair branch already knows how to send deterministic hints, capture one response, write one audit, and populate both override maps. Promote that branch into the canonical route instead of carrying it as a prototype. Remove the chunking/pass2/pass3 worldview from the write path, but keep read-time compatibility shims long enough for older benchmark artifacts and saved settings to remain readable.

Acceptance for this milestone is that plan mode shows exactly one recipe correction stage per recipe and execute mode writes exactly one recipe-correction raw stage for the canonical pipeline value.

### Milestone 3: Make final assembly deterministic and linkage-aware

At the end of this milestone, the final cookbook draft must be produced deterministically from the corrected intermediate recipe plus the LLM linkage payload. Extend `cookimport/staging/draft_v1.py` so the draft builder can accept an explicit `ingredient_step_mapping_override` and optional reason metadata. When an override is present, use it to assign parsed ingredient lines to steps instead of re-solving the linkage heuristically. When no override is present, keep today’s deterministic assignment behavior unchanged.

This milestone is the architectural hinge of Phase 3. The intermediate JSON-LD override should now come from the corrected `RecipeCandidate`, and the final draft should be derived locally from that corrected candidate plus the linkage payload. The recipe LLM should no longer emit a full final draft for the canonical route. If compatibility readers still need a full-draft field during migration, derive it locally before writing compatibility artifacts rather than asking the LLM for it.

Acceptance for this milestone is that a focused test can feed a corrected candidate plus an explicit mapping override into the deterministic builder and observe that the written draft reflects the override instead of the heuristic linker.

### Milestone 4: Align naming, settings, reports, and compatibility layers

At the end of this milestone, every newly written artifact should describe the product truth: one recipe correction stage. Update `cookimport/config/run_settings.py` so `codex-farm-single-correction-v1` is the preferred enum value and `codex-farm-2stage-repair-v1` loads as an alias. Update `cookimport/labelstudio/ingest.py`, `cookimport/cli.py`, and any interactive prompt text so new runs surface the new name while old saved payloads still normalize cleanly.

Perform the same cleanup in manifests, report counters, prompt artifact exports, and raw folder naming. New reports should count `recipe_correction_ok`, `recipe_correction_error`, `recipe_correction_fallback`, and `final_assembly_*` states instead of teaching pass2/pass3 as the main truth. Compatibility sections are acceptable where old readers still need them, but they must be marked as compatibility-only and generated from the new neutral representation rather than stored as the canonical state.

Acceptance for this milestone is that a new stage run, prompt-artifact export, and plan-mode manifest all use single-correction naming without breaking the ability to read older `codex-farm-2stage-repair-v1` settings or benchmark roots.

### Milestone 5: Add focused tests, update docs, and validate with a real run

At the end of this milestone, the refactor should be proven in tests and in one observable run. Add or update focused tests in `tests/llm/test_codex_farm_contracts.py`, `tests/llm/test_codex_farm_orchestrator.py`, `tests/llm/test_codex_farm_orchestrator_stage_integration.py`, and `tests/llm/test_writer_overrides.py`. Extend staging tests if needed for linkage-aware deterministic draft construction. Update Label Studio and CLI normalization tests anywhere the preferred pipeline name changes.

Then update docs. `docs/10-llm/10-llm_README.md` must describe the single correction stage as the canonical recipe path. `docs/02-cli/02-cli_README.md` must describe the new pipeline name and any compatibility alias behavior. `cookimport/staging/README.md` must explain that final cookbook drafts can now be derived from a corrected intermediate candidate plus an explicit linkage payload. Add one short note in `cookimport/llm/README.md` or an existing nearby folder note if that folder already has local documentation; keep it brief.

Acceptance for this milestone is a passing targeted test slice, a passing non-slow `llm` and `staging` domain run, and a small stage run whose plan or raw artifacts clearly show one correction stage rather than pass1/pass2/pass3.

## Plan of Work

Start by promoting the architecture that is already half-built instead of introducing a second prototype. The current merged-repair route proves that one LLM call can consume deterministic evidence and produce a recipe-level correction artifact. Replace its minimal canonical-recipe payload with a corrected intermediate `RecipeCandidate` payload, keep the linkage payload, and make that contract the only recipe LLM contract the product writes going forward.

Create a deterministic preparation step before any LLM call. This preparation step should take one grouped recipe span from the Phase 2 runtime, build one `RecipeCandidate`, and package the span evidence plus candidate into a validated correction input bundle. Do not ask the LLM to rediscover bounds, section headers, or labels. The prompt should frame the intermediate candidate as the draft to correct, not as a hint among several competing truths.

Then rework `run_codex_farm_recipe_pipeline(...)` so the canonical route is one-stage. The public helper can keep its name to avoid broad call-site churn, but its internal state model should stop centering on pass1/pass2/pass3. Replace `_RecipeState` fields that exist only for the old three-pass flow with one correction-stage status, one final-assembly status, one structural audit for corrected intermediate output, and one linkage status. Keep a compatibility projection when older benchmark or review tools still need legacy family names.

After the orchestration is one-stage, implement deterministic final assembly. Extend `recipe_candidate_to_draft_v1(...)` or factor out a lower-level helper so it can accept an optional explicit linkage mapping. The deterministic builder should still parse ingredients, normalize units, segment instructions, and emit yield/time metadata exactly as today; the only changed responsibility is how ingredient lines are assigned to steps when the LLM has already supplied a mapping.

Finally, sweep the compatibility surfaces. Update run-setting enums, CLI labels, Label Studio normalization, prompt-pack ids, and prompt artifact exporters. New writes must use the new names immediately. Reads may normalize old names until the test suite and any useful historical artifacts are updated. Keep this compatibility window narrow and explicit so the repo does not drift back into “prototype branch as permanent product contract.”

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`.

Prepare the local environment:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -e .[dev]

If the venv does not contain `pip`, bootstrap it inside `.venv` before running the install command.

Capture a baseline on the current LLM/staging seams before refactoring:

    source .venv/bin/activate
    pytest tests/llm/test_writer_overrides.py -q
    pytest tests/llm/test_codex_farm_contracts.py -q
    pytest tests/llm/test_codex_farm_orchestrator.py -q
    pytest tests/llm/test_codex_farm_orchestrator_stage_integration.py -q

During Milestone 1 and Milestone 3, keep the contract and deterministic-builder loop tight:

    source .venv/bin/activate
    pytest tests/llm/test_codex_farm_contracts.py -q
    pytest tests/llm/test_writer_overrides.py -q

After switching orchestration and naming, rerun the focused LLM slice and the compatibility tests you updated:

    source .venv/bin/activate
    pytest tests/llm/test_codex_farm_orchestrator.py -q
    pytest tests/llm/test_codex_farm_orchestrator_stage_integration.py -q
    pytest tests/labelstudio/test_labelstudio_ingest_parallel.py -q

For broader non-slow validation, use the project wrapper:

    source .venv/bin/activate
    ./scripts/test-suite.sh domain llm
    ./scripts/test-suite.sh domain staging

Verify plan-mode behavior on a small input file after the new canonical pipeline name is wired:

    source .venv/bin/activate
    cookimport stage data/input/<small-file> --llm-recipe-pipeline codex-farm-single-correction-v1 --codex-execution-policy plan

Expected outcome after Milestone 4:

    the written `codex_execution_plan.json` shows one recipe correction stage per recipe span and does not describe a pass1/pass2/pass3 recipe pipeline for the canonical route

If CodexFarm is configured for live execution, run one small end-to-end stage job:

    source .venv/bin/activate
    cookimport stage data/input/<small-file> --llm-recipe-pipeline codex-farm-single-correction-v1

Expected outcome after Milestone 5:

    intermediate JSON-LD and final cookbook outputs are written as before, but the raw LLM folder and manifest show one recipe correction stage plus deterministic final assembly

## Validation and Acceptance

Acceptance is behavioral, not structural.

The contract is correct when one grouped recipe span can be turned into one deterministic intermediate `RecipeCandidate`, one validated correction input bundle, one validated correction output bundle, and then one corrected intermediate object plus one linkage payload without referencing legacy pass2/pass3 model names.

The orchestration is correct when the canonical recipe Codex route plans and executes one stage only. In plan mode, `codex_execution_plan.json` must show one recipe-correction pass per recipe span. In execute mode, the raw artifact tree must contain one canonical correction stage directory, one correction audit per recipe, and no newly written canonical report rows that pretend the product still has three recipe passes.

The final assembly is correct when the same corrected `RecipeCandidate` can produce both intermediate JSON-LD and final `RecipeDraftV1` outputs locally, and when an explicit linkage payload changes step assignment in the final draft exactly as the test fixture expects.

The migration is complete when:

- `tests/llm/test_codex_farm_contracts.py`, `tests/llm/test_writer_overrides.py`, `tests/llm/test_codex_farm_orchestrator.py`, and `tests/llm/test_codex_farm_orchestrator_stage_integration.py` pass.
- the non-slow `llm` and `staging` domain suites pass through `./scripts/test-suite.sh`.
- updated Label Studio normalization tests pass for both the canonical pipeline name and the compatibility alias.
- docs describe one recipe correction stage as the truth for new runs.

## Idempotence and Recovery

This migration should be implemented additively first and subtractively second. Add the new contract, deterministic builder, and linkage-aware final assembly while the old compatibility code still reads old names. Only remove legacy write-path behavior after the new tests pass.

If a partial implementation breaks the canonical route, keep the compatibility alias normalization but route both names back through the last known-good merged-repair path until the deterministic final-assembly milestone is complete. Do not write mixed truth into manifests: if the new route is not ready to tell the truth, keep compatibility writes only in the read path and postpone the write-path switch.

The test and plan-mode steps above are safe to rerun. Raw run output directories should be created under a fresh timestamped output root so failed live runs do not contaminate later verification.

## Artifacts and Notes

The new correction input bundle should look conceptually like this:

    {
      "recipe_id": "urn:recipe:test:toast",
      "workbook_slug": "book",
      "source_hash": "...",
      "evidence_rows": [[1, "Toast"], [2, "1 slice bread"], [3, "Toast the bread."]],
      "intermediate_recipe": {"@type": "Recipe", "name": "Toast", ...},
      "authority_notes": ["authoritative_source=evidence_rows", "secondary_hint=intermediate_recipe"]
    }

The new correction output bundle should look conceptually like this:

    {
      "recipe_id": "urn:recipe:test:toast",
      "corrected_intermediate_recipe": {"@type": "Recipe", "name": "Toast", ...},
      "ingredient_step_mapping": [{"ingredient_index": 0, "step_indexes": [0]}],
      "ingredient_step_mapping_reason": null,
      "warnings": []
    }

The new plan-mode manifest should read like this, not like pass1/pass2/pass3:

    {
      "pipeline": "codex-farm-single-correction-v1",
      "planned_tasks": [
        {
          "recipe_id": "urn:recipe:test:toast",
          "planned_passes": [
            {"stage_kind": "recipe_correction", "pipeline_id": "recipe.correction.compact.v1"}
          ]
        }
      ]
    }

## Interfaces and Dependencies

In `cookimport/llm/codex_farm_contracts.py`, define the new canonical models:

    class RecipeCorrectionInput(BaseModel):
        bundle_version: Literal["1"] = "1"
        recipe_id: str
        workbook_slug: str
        source_hash: str
        evidence_rows: list[tuple[int, str]]
        intermediate_recipe: dict[str, Any]
        authority_notes: list[str] = Field(default_factory=list)

    class RecipeCorrectionOutput(BaseModel):
        bundle_version: Literal["1"] = "1"
        recipe_id: str
        corrected_intermediate_recipe: dict[str, Any]
        ingredient_step_mapping: dict[str, Any]
        ingredient_step_mapping_reason: str | None = None
        warnings: list[str] = Field(default_factory=list)

`corrected_intermediate_recipe` must validate cleanly as `RecipeCandidate`. `ingredient_step_mapping` should keep using the existing strict array-or-object normalization already supported by `_coerce_ingredient_step_mapping_field(...)`.

In `cookimport/llm/codex_farm_orchestrator.py`, keep the public helper but add one prepared-input seam:

    @dataclass
    class PreparedRecipeCorrection:
        recipe: RecipeCandidate
        recipe_id: str
        evidence_rows: list[tuple[int, str]]
        source_hash: str
        provenance_summary: dict[str, Any]

    def prepare_recipe_correction_inputs(
        conversion_result: ConversionResult,
        *,
        workbook_slug: str,
        run_settings: RunSettings,
    ) -> list[PreparedRecipeCorrection]:
        ...

The canonical execution route should then be:

    PreparedRecipeCorrection
      -> RecipeCorrectionInput
      -> CodexFarm `recipe.correction.compact.v1`
      -> RecipeCorrectionOutput
      -> corrected `RecipeCandidate`
      -> deterministic JSON-LD and `RecipeDraftV1`

In `cookimport/staging/draft_v1.py`, extend the deterministic builder:

    def recipe_candidate_to_draft_v1(
        candidate: RecipeCandidate,
        *,
        ingredient_parser_options: Mapping[str, Any] | None = None,
        instruction_step_options: Mapping[str, Any] | None = None,
        ingredient_step_mapping_override: Mapping[int | str, Sequence[int]] | None = None,
        ingredient_step_mapping_reason: str | None = None,
    ) -> dict[str, Any]:
        ...

The override must only change ingredient-to-step assignment. Ingredient parsing, instruction segmentation, yield extraction, time parsing, and temperature parsing should stay on the existing deterministic path.

In `cookimport/config/run_settings.py`, add one canonical enum value and one alias normalization path:

    "off"
    "codex-farm-single-correction-v1"
    "codex-farm-2stage-repair-v1"  # compatibility alias on load only

In `llm_pipelines/`, create the canonical recipe-correction pack assets:

    llm_pipelines/pipelines/recipe.correction.compact.v1.json
    llm_pipelines/prompts/recipe.correction.compact.v1.prompt.md
    llm_pipelines/schemas/recipe.correction.v1.output.schema.json

During migration, `recipe.merged-repair.compact.v1` may remain as an alias that resolves to the same prompt/schema pair, but new planning, manifests, and docs must prefer `recipe.correction.compact.v1`.

Change note: Initial draft created on 2026-03-15 to turn Refactor Phase 3 into a self-contained implementation plan, with the explicit assumption that Phases 1 and 2 already landed and that the remaining work is the single-stage recipe correction plus deterministic final assembly.
