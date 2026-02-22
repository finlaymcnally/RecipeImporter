---
summary: "ExecPlan for integrating a 3-pass codex-farm workflow into cookimport stage (recipeimport side only)."
read_when:
  - When implementing the recipeimport ↔ codex-farm integration (job bundles, 3-pass orchestration, applying outputs)
  - When wiring new pipeline options into stage + pred-run (runConfig, history, dashboards, parity tests)
  - When debugging LLM artifacts and provenance in staged runs
---

# ExecPlan: RecipeImport — 3-pass codex-farm integration for recipe chunking + schema.org + final drafts

IT IS INCREDIBLY IMPORTANT TO NOTE THAT YOU MUST NOT RUN THE CODEX FARM INTEGRAITON. BUILD THIS BUT DO NOT TEST IT "LIVE" BY ACTUALLY SUMMONING CODEX INSTANCES UNTIL I HAVE HAD A TIME TO THINK ABOUT HOW I WANT TO MANAGE TOKEN USE. DO NOT TEST THIS IN A WAY THAT CAUSES THE CODEX FARM PROGRAM TO USE TOKENS PLEASE!!!

This ExecPlan is a living document. The sections **Progress**, **Surprises & Discoveries**, **Decision Log**, and **Outcomes & Retrospective** must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root.


## Purpose / Big Picture


After this change, `cookimport stage ...` can optionally run a **3-pass “codex-farm” workflow** to materially improve recipe parsing accuracy:

1. Pass 1: refine recipe chunk boundaries (ensure the recipe chunk includes the right text and excludes unrelated text).
2. Pass 2: generate an authoritative schema.org `Recipe` JSON-LD from the refined chunk.
3. Pass 3: generate the final `RecipeDraftV1` output (your “cookbook3” final format) and include a mapping that proves ingredient ↔ step linkage integrity.

When this feature is enabled, cookimport will call codex-farm **three times** (one per pass), using a file-bundle interface: cookimport writes input JSON bundles to disk, codex-farm processes a directory and writes validated JSON outputs, then cookimport reads/validates/applies them.

Default behavior remains deterministic and unchanged: **LLM codex-farm integration is OFF unless explicitly enabled**.

A user can see the feature working by:

- Running `cookimport stage` with the new LLM/codex-farm option enabled and observing:
  - codex-farm is invoked three times for that file,
  - new raw artifacts are created under `data/output/<ts>/raw/llm/<workbook_slug>/...`,
  - intermediate drafts (`intermediate drafts/<workbook_slug>/r{index}.jsonld`) are written from pass 2 outputs,
  - final drafts (`final drafts/<workbook_slug>/r{index}.json`) are written from pass 3 outputs,
  - per-file report includes an `llmCodexFarm` section (counts, failures, paths, timings).

- Running the same input twice (LLM OFF vs LLM ON) and comparing the staged outputs and (optionally) golden-set eval outcomes.


## Definitions (plain language)


Codex-farm:

- A local CLI tool (external dependency) that runs LLM tasks over files in a directory, enforces a strict JSON Schema output contract, and supports retries/resume internally. In this plan, cookimport treats it as a black box.

Pipeline pack:

- A directory layout that contains pipeline definitions, prompts, and JSON schemas for codex-farm to load. In this repo, we will keep a “recipe pipeline pack” under `llm_pipelines/` and point codex-farm at it via the `CODEX_FARM_ROOT` environment variable.

Job bundle:

- A single JSON input file written by cookimport that contains everything the model needs for one task (for example: blocks around a candidate recipe chunk and metadata like recipe_id).

Pass:

- One codex-farm pipeline invocation over a directory of job bundles. We run three passes and feed the outputs of earlier passes into the inputs of later passes.

Recipe chunk / boundaries:

- The contiguous span of blocks/lines that should be considered “the recipe” (title + ingredients + steps + relevant notes), excluding unrelated content like page headers, other recipes, or index entries.

Intermediate draft:

- The schema.org `Recipe` JSON-LD output (`intermediate drafts/.../*.jsonld`) that cookimport already writes in deterministic mode.

Final draft:

- The final `RecipeDraftV1` JSON output (`final drafts/.../*.json`) that cookimport already writes in deterministic mode.


## Scope and non-goals


In scope:

- Add a new optional “LLM recipe pipeline” run setting / CLI option that enables this 3-pass codex-farm workflow.
- Implement the recipeimport-side orchestration:
  - build job bundles for pass 1/2/3,
  - invoke codex-farm three times,
  - read and validate outputs,
  - apply boundary changes to recipe candidates and recompute `nonRecipeBlocks`,
  - override intermediate and final outputs with pass 2/3 results.
- Ensure this run setting is wired into both:
  - `cookimport stage` (import path),
  - prediction-run generation flows used for Label Studio benchmark/eval (pred-run path),
  in accordance with the repository’s “new pipeline option contract”.
- Add tests that demonstrate the new behavior without requiring codex-farm to be installed (use a fake runner).

Explicit non-goals (for this ExecPlan):

- Implementing codex-farm itself, its CLI, its SQLite task DB, or its worker logic.
- Designing prompts or the content of the recipe pipelines (that is handled in the “codex-farm side” ExecPlan).
- Fully reworking tip/topic extraction to be LLM-driven. Tips/topics remain deterministic for now.
- Adding new dashboards/visualizations beyond ensuring runConfig & history wiring remains correct.


## Repository orientation (what exists today)


This repo already has a staged architecture:

- Importers (EPUB/PDF/etc.) extract a linear block stream, segment recipe candidates, extract tips/topics, and capture “non-recipe blocks”.
- `cli_worker.stage_one_file(...)` runs chunking over `nonRecipeBlocks` (preferred) and then writers emit:
  - schema.org intermediate drafts under `intermediate drafts/<workbook_slug>/r{index}.jsonld`,
  - final drafts under `final drafts/<workbook_slug>/r{index}.json`,
  - tips/topics/chunks/raw/report.

For large EPUB/PDF, there is split-job behavior:

- worker jobs convert page/spine ranges and emit mergeable results,
- the main process merges, rebases IDs/order, merges raw artifacts, then writes once,
- chunk generation happens after merge on the unified non-recipe stream.

This ExecPlan integrates at the “shared post-import stage path” (after conversion and before writing), and must also integrate into the split-job merge path so that the final unified outputs reflect LLM boundary corrections.


## User-facing interface and behavior


### New CLI / run settings


Add a new run setting that can be toggled from both:

- non-interactive CLI flags (e.g. `cookimport stage ... --llm-recipe-pipeline codex-farm-3pass-v1`), and
- interactive run settings UI.

Recommended run settings fields:

- `llm_recipe_pipeline: Literal["off","codex-farm-3pass-v1"]` (default: `"off"`)
- `codex_farm_cmd: str` (default: `"codex-farm"`)
- `codex_farm_root: str | None` (default: `None`, meaning “use repo_root/llm_pipelines”)
- `codex_farm_context_blocks: int` (default: 30; number of blocks before/after candidate for pass 1 bundles)
- `codex_farm_failure_mode: Literal["fail","fallback"]` (default: `"fail"` for missing binary / pipeline-pack problems; internal per-recipe parse failures fall back to deterministic even if this is `"fail"`)

The plan below describes exactly where these fields must be threaded so runConfig + history stay consistent.

### New artifacts written to disk


When enabled, cookimport writes “LLM artifacts” under the run’s raw directory so they are captured by outputStats as `rawArtifacts`:

- `data/output/<ts>/raw/llm/<workbook_slug>/pass1_chunking/in/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass1_chunking/out/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass2_schemaorg/in/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass2_schemaorg/out/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass3_final/in/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/pass3_final/out/*.json`
- `data/output/<ts>/raw/llm/<workbook_slug>/llm_manifest.json` (summary of what was run/applied, counts, pipeline IDs, timing)

Intermediate and final drafts are still written to the canonical output locations; the difference is that the writer uses LLM outputs as overrides.

### Deterministic fallback rules


The feature is opt-in and should be safe:

- If LLM pipeline is OFF: code must not create LLM artifacts and must not invoke codex-farm.
- If LLM pipeline is ON but `codex-farm` binary is missing or cannot run: fail the run with a clear error and how to disable the option.
- If codex-farm runs but one recipe’s output file is missing or fails parsing:
  - keep the run going,
  - for that recipe, fall back to deterministic intermediate/final generation,
  - record the failure in `llm_manifest.json` and the per-file conversion report.


## Implementation plan (milestones)


### Milestone 0 — Baseline and guardrails


Goal: establish a baseline and ensure you can validate changes safely.

Work:

1. Run a baseline stage run with LLM OFF on a small fixture input (an EPUB or PDF fixture in `tests/fixtures/` if present).
2. Identify the key integration points:
   - Where CLI flags become a `RunSettings` instance.
   - Where `cli_worker.stage_one_file` calls the importer, then chunking, then writer.
   - Where split-job merge writes the final results.
3. Add a “no-op safety test”: when `llm_recipe_pipeline == "off"`, no LLM artifacts are created and codex-farm is never invoked.

Proof/acceptance:

- Baseline `pytest -q` passes unchanged.
- New test fails before implementation and passes after: “runner not called when feature disabled”.


### Milestone 1 — RunSettings + CLI plumbing + pipeline-option contract wiring


Goal: introduce new settings in a way that is consistent with the repo’s contract: settings affect both stage and pred-run, and show up in runConfig, runConfigHash, summaries, and history CSVs.

Work:

1. Add fields to `cookimport/config/run_settings.py`:
   - Extend the `RunSettings` model with the new LLM/codex-farm fields listed above.
   - Ensure defaults preserve current behavior (`llm_recipe_pipeline="off"`).
   - Ensure the `summary()` and `run_config_hash()` include the new setting (at least `llm_recipe_pipeline`; avoid dumping absolute paths into summaries unless you already do that elsewhere).

2. Add CLI flags to the non-interactive stage command:
   - Locate where `cookimport stage` arguments are defined (often in `cookimport/cli.py` or `cookimport/cli_worker.py`).
   - Add `--llm-recipe-pipeline` choice flag and pass it into `RunSettings`.
   - Add `--codex-farm-cmd`, `--codex-farm-root`, `--codex-farm-context-blocks` if you want them user-configurable from CLI.

3. Add the setting to the interactive run settings UI:
   - Locate the run settings editor module (in this repo, it exists as interactive flows in `cookimport/cli.py` and helper UI modules).
   - Add a new “LLM” section with a simple toggle/selector.
   - Confirm last-run settings persistence includes these new fields (it is JSON-serialization of RunSettings, so fields will persist automatically once added).

4. Apply the run setting in both required execution paths (contract requirement):
   - Stage path: `cookimport stage` must use the run setting.
   - Pred-run path: locate prediction generation in `cookimport/labelstudio/ingest.py` (e.g., `generate_pred_run_artifacts(...)`) and ensure it constructs and uses the same `RunSettings` fields.
   - Update `cookimport/labelstudio/benchmark.py` if it creates pred-runs internally.

5. Update run history / dashboards / parity test:
   - Update any code that appends history CSV rows so `runConfigSummary`, `runConfigHash`, and `runConfig` include the new setting(s) consistently.
   - Update `cookimport/analytics/dashboard_render.py` if it expects a fixed set of runConfig keys.
   - Update `tests/test_run_manifest_parity.py` so stage and pred-run manifests remain aligned on shared runConfig keys.

Proof/acceptance:

- Running `cookimport stage --help` shows the new flags.
- Interactive `cookimport` mode shows a new option that toggles this feature.
- `pytest -q` passes, including updated run manifest parity tests.
- A stage run report JSON shows `runConfig` includes `llm_recipe_pipeline` and any other chosen keys.


### Milestone 2 — Define job bundle + output models for the 3 passes


Goal: make the interface between cookimport and codex-farm explicit, strict, and easy to validate, without requiring implementers to read the prompt.

Work:

1. Create new models module(s) under `cookimport/llm/` (this repo already has an LLM integration directory, even if mocked):
   - `cookimport/llm/codex_farm_contracts.py` (Pydantic models for input bundles and outputs)
   - `cookimport/llm/codex_farm_ids.py` (helpers for stable filenames/job IDs)

2. Define the pass contracts in code (Pydantic) so recipeimport can parse outputs safely.

Pass 1 input bundle (one file per candidate):

- Required fields:
  - `bundle_version: "1"`
  - `recipe_id: str`
  - `workbook_slug: str`
  - `source_hash: str`
  - `heuristic_start_block_index: int | None` (required-but-nullable)
  - `heuristic_end_block_index: int | None` (required-but-nullable)
  - `blocks_before: list[BlockLite]`
  - `blocks_candidate: list[BlockLite]`
  - `blocks_after: list[BlockLite]`

Where `BlockLite` includes:
  - `index: int` (absolute index in the full block stream for that file)
  - `block_id: str | None` (required-but-nullable; use whatever ID your block model already has)
  - `text: str`
  - Optional-but-present (nullable) provenance fields like `page`, `spine_index`, `heading_level` if available.

Pass 1 output:

- Required fields:
  - `bundle_version: "1"`
  - `recipe_id: str`
  - `is_recipe: bool`
  - `start_block_index: int | None` (null if not recipe)
  - `end_block_index: int | None` (null if not recipe)
  - `title: str | None`
  - `reasoning_tags: list[str]`
  - `excluded_block_ids: list[str]` (can be empty)

Pass 2 input:

- Required:
  - `bundle_version: "1"`
  - `recipe_id`, `workbook_slug`, `source_hash`
  - `canonical_text: str`
  - `blocks: list[BlockLite]` (the included blocks, so the model can cite evidence by block index/id)

Pass 2 output:

- Required:
  - `bundle_version: "1"`
  - `recipe_id: str`
  - `schemaorg_recipe: dict` (JSON object)
  - `extracted_ingredients: list[str]` (verbatim lines)
  - `extracted_instructions: list[str]` (verbatim steps)
  - `field_evidence: dict` (can be `{}` but must be present)
  - `warnings: list[str]` (can be empty)

Pass 3 input:

- Required:
  - `bundle_version: "1"`
  - `recipe_id`, `workbook_slug`, `source_hash`
  - `schemaorg_recipe: dict`
  - `extracted_ingredients: list[str]`
  - `extracted_instructions: list[str]`

Pass 3 output:

- Required:
  - `bundle_version: "1"`
  - `recipe_id: str`
  - `draft_v1: dict` (must validate against `RecipeDraftV1` in `cookimport/core/models.py`)
  - `ingredient_step_mapping: dict` (explicit mapping table; exact shape defined in schema)
  - `warnings: list[str]`

3. Add internal validation helpers (recipeimport-side guardrails):

- Pass 2 guardrails (non-fatal warnings):
  - each `extracted_ingredients[i]` must be found in `canonical_text` (case-insensitive substring or a simple normalized match),
  - each `extracted_instructions[i]` must be found in `canonical_text`.
- Pass 3 guardrails:
  - `draft_v1` must parse as `RecipeDraftV1`.
  - ensure `draft_v1.id` matches the expected `recipe_id` (patch it if necessary, record warning).
  - run the same post-processing invariants you rely on in deterministic mode when possible (for example: if your deterministic staging inserts a prep step for unassigned ingredients, apply the same fix-up to LLM drafts).

Proof/acceptance:

- Unit tests can load and validate example JSON for each pass contract.
- A test demonstrates that malformed outputs (missing required keys) are rejected and cause fallback for that recipe rather than crashing the whole run.


### Milestone 3 — Implement the codex-farm runner (subprocess boundary) + fake runner for tests


Goal: treat codex-farm as a black box and make it injectable so tests do not require codex-farm.

Work:

1. Create `cookimport/llm/codex_farm_runner.py`:

- Define a small interface:

  - `class CodexFarmRunner(Protocol):`
      - `run_pipeline(pipeline_id: str, in_dir: Path, out_dir: Path, env: dict[str,str]) -> None`

- Implement `SubprocessCodexFarmRunner`:
  - Build a subprocess command:
        codex-farm process --pipeline <pipeline_id> --in <in_dir> --out <out_dir>
  - Set environment variables:
    - `CODEX_FARM_ROOT` to the pipeline pack root directory (from run settings; default `<repo_root>/llm_pipelines`).
  - Stream stdout/stderr to logging so failures are visible in console logs.
  - If exit code != 0: raise a clear exception that includes the pipeline_id and out_dir path.

2. Create `cookimport/llm/fake_codex_farm_runner.py` used only in tests:

- It should write deterministic output JSON files for each input JSON file. The outputs should match the Pydantic contracts, and should be “obviously” derived from input (e.g., for pass 1: return the heuristic start/end unchanged and `is_recipe=True`; for pass 2: return a minimal schema.org recipe with name from title; for pass 3: return a minimal valid `RecipeDraftV1` with empty ingredients/steps or a tiny fixture mapping).

3. Add tests for runner orchestration:

- Verify that when the orchestrator is executed, `run_pipeline` is called exactly 3 times, in order, with the expected pipeline IDs.

Proof/acceptance:

- `pytest -q` passes without requiring codex-farm installed.
- When codex-farm is not installed and feature is enabled in a real run, the error message is actionable (“install codex-farm or disable llm_recipe_pipeline”).


### Milestone 4 — Implement the 3-pass orchestrator and integrate it into stage and split-merge flows


Goal: implement “write jobs → run pass1 → generate pass2 jobs → run pass2 → generate pass3 jobs → run pass3 → apply overrides”.

Work:

1. Create `cookimport/llm/codex_farm_orchestrator.py` with a single high-level entrypoint:

- `run_codex_farm_recipe_pipeline(conversion_result, run_settings, run_root, workbook_slug, runner) -> CodexFarmApplyResult`

Where `CodexFarmApplyResult` includes:
  - `updated_conversion_result` (recipes list possibly filtered/reordered; nonRecipeBlocks recomputed when possible)
  - `intermediate_overrides_by_recipe_id: dict[str, dict]` (schema.org objects)
  - `final_overrides_by_recipe_id: dict[str, RecipeDraftV1]`
  - `stats` (counts, failures, timing)
  - `llm_raw_dir` path

2. Decide and hard-code the pipeline IDs used by codex-farm (these must match the pipeline pack):

- Pass 1 pipeline ID: `recipe.chunking.v1`
- Pass 2 pipeline ID: `recipe.schemaorg.v1`
- Pass 3 pipeline ID: `recipe.final.v1`

3. Write job bundles under the run’s raw directory:

- Determine per-file LLM raw root:
    llm_raw_dir = <run_root>/raw/llm/<workbook_slug>/

- Pass 1 directories:
    <llm_raw_dir>/pass1_chunking/in/
    <llm_raw_dir>/pass1_chunking/out/

- Pass 2 directories:
    <llm_raw_dir>/pass2_schemaorg/in/
    <llm_raw_dir>/pass2_schemaorg/out/

- Pass 3 directories:
    <llm_raw_dir>/pass3_final/in/
    <llm_raw_dir>/pass3_final/out/

- Write `<llm_raw_dir>/llm_manifest.json` at end (or update incrementally).

4. Load the full block stream needed for pass 1:

- For EPUB/PDF conversions, importers already record a raw artifact `full_text` containing the extracted blocks JSON.
- Add a helper `load_full_blocks(conversion_result) -> list[Block]` that reads this artifact and returns a list in the same order used by candidate segmentation.
- For split-job merges, ensure that the merged final output also has a `full_text` raw artifact that represents the unified block stream; if it does not today, add it as part of merge (write a merged `full_text` blocks dump to raw artifacts before running pass 1).

5. Pass 1 job generation and application:

- For each `RecipeCandidate` in `conversion_result.recipes`:
  - Determine its heuristic block span (start/end indices) from candidate provenance (start_block/end_block).
  - Slice `context_blocks_before` and `context_blocks_after` from the full block list, using `codex_farm_context_blocks`.
  - Build the Pass 1 input bundle using `blocks_before`, `blocks_candidate`, `blocks_after`.

- Run codex-farm pass 1:
    runner.run_pipeline("recipe.chunking.v1", pass1_in_dir, pass1_out_dir, env)

- Read outputs:
  - For each input file, expect an output file with the same base name.
  - Parse as Pass 1 output model.
  - If `is_recipe=False`, mark the candidate for removal.
  - If `is_recipe=True`, adopt `start_block_index` and `end_block_index`, but enforce safety:
    - clamp to `[0, len(full_blocks)-1]`
    - prevent overlap across candidates by clamping to not cross the midpoint to neighboring heuristic candidates (use the original full candidate list, not just limited list).
    - If clamping changes values, record a warning in llm_manifest.

- Update `conversion_result.recipes`:
  - Remove candidates rejected by pass 1.
  - For accepted candidates, update their provenance start/end block indices to the pass 1 result.
  - Sort recipes by updated start index so output `r{index}` ordering matches document order.

- Recompute `conversion_result.nonRecipeBlocks` when possible:
  - Build a boolean mask over full blocks.
  - Mark blocks covered by each accepted recipe span as “recipe”.
  - If pass 1 provides `excluded_block_ids`, unmark those blocks so they become “non-recipe”.
  - Set `conversion_result.nonRecipeBlocks = [blocks[i] for i in range(N) if not recipe_mask[i]]`.
  - If full block stream is not available, do not recompute; record a warning and leave original nonRecipeBlocks unchanged.

6. Pass 2 job generation:

- For each accepted candidate (after pass 1):
  - Determine included blocks (span minus excluded ids).
  - Build `canonical_text` by joining included block texts with `\n`.
  - Build pass 2 input bundle with canonical_text + included blocks list for evidence.

- Run codex-farm pass 2:
    runner.run_pipeline("recipe.schemaorg.v1", pass2_in_dir, pass2_out_dir, env)

- Read and validate pass 2 outputs:
  - Parse output model.
  - Run guardrails: verify extracted ingredient lines and instruction lines appear in canonical_text; record warnings.
  - Store `schemaorg_recipe` in `intermediate_overrides_by_recipe_id`.

7. Pass 3 job generation:

- For each recipe that has a successful pass 2 output:
  - Build pass 3 input bundle with schemaorg_recipe + extracted arrays.

- Run codex-farm pass 3:
    runner.run_pipeline("recipe.final.v1", pass3_in_dir, pass3_out_dir, env)

- Read and validate pass 3 outputs:
  - Parse output model.
  - Validate `draft_v1` against `RecipeDraftV1` model.
  - Apply deterministic post-processing invariants if needed (for example, ensure unassigned ingredient handling matches deterministic pipeline expectations).
  - Store `RecipeDraftV1` in `final_overrides_by_recipe_id`.

8. Write `llm_manifest.json`:

- Include:
  - which pipelines were run (IDs),
  - counts of jobs written and outputs read per pass,
  - per-recipe status (pass1/pass2/pass3 ok vs failed + error message),
  - timing checkpoints (pass1_seconds, pass2_seconds, pass3_seconds),
  - path pointers to in/out directories.

9. Integrate into stage worker path:

- In `cookimport/cli_worker.py` (or wherever `stage_one_file` is defined):
  - After importer.convert() and after applying `--limit`, check `run_settings.llm_recipe_pipeline`.
  - If enabled, call `run_codex_farm_recipe_pipeline(...)`.
  - Replace the in-scope `conversion_result` with the returned `updated_conversion_result`.
  - Pass overrides to writer (next step), and continue chunking/writing.

10. Integrate into split-job merge path:

- Locate the merge-and-write function for split EPUB/PDF jobs (likely in `cookimport/plugins/pdf_jobs.py` / `epub_jobs.py` or an adjacent module).
- After merge produces a unified `ConversionResult` and before chunking/writing:
  - Ensure unified `full_text` blocks artifact exists.
  - Invoke the same orchestrator.
  - Proceed to write outputs once.

Proof/acceptance:

- In a real run (with codex-farm installed and pipelines present):
  - codex-farm is invoked 3 times per file in LLM mode,
  - `raw/llm/<workbook_slug>/...` directories exist and contain input + output JSON,
  - intermediate/final drafts are written and reflect LLM outputs.
- In tests (without codex-farm installed):
  - fake runner is used and orchestrator logic is validated (call order, output consumption, recompute nonRecipeBlocks).


### Milestone 5 — Writer integration: accept overrides for intermediate and final outputs


Goal: ensure that existing output paths remain unchanged, but the content can come from LLM outputs when available.

Work:

1. Identify the writer entrypoint in `cookimport/staging/writer.py` that writes:
  - intermediate drafts,
  - final drafts,
  - tips/topics/chunks,
  - report and outputStats.

2. Extend writer functions to accept optional override maps:

- For schema.org intermediate drafts:
  - Add `schemaorg_overrides_by_recipe_id: dict[str, dict] | None`
  - When writing a recipe:
    - if override exists, write it directly to `intermediate drafts/<workbook>/r{index}.jsonld`
    - otherwise, use the existing deterministic conversion.

- For final drafts:
  - Add `draft_overrides_by_recipe_id: dict[str, RecipeDraftV1] | None`
  - When writing a recipe:
    - if override exists, write it directly to `final drafts/<workbook>/r{index}.json`
    - otherwise, use existing deterministic `recipe_candidate_to_draft_v1(...)`.

3. Ensure outputStats and report remain correct:

- Intermediate/final draft file counts and sizes should still be tracked by existing writer logic, regardless of whether content is deterministic or LLM-based.
- Add an `llmCodexFarm` section to the per-file report that includes:
  - enabled flag,
  - per-pass success counts,
  - failures,
  - llm_raw_dir path,
  - timing.

Proof/acceptance:

- With feature ON and fake runner:
  - writer writes override content.
- With feature OFF:
  - writer behavior unchanged.
- Existing staging output contract tests still pass (paths, counts, etc.).


### Milestone 6 — Pred-run (Label Studio) integration parity


Goal: make sure the same run setting affects the pred-run generation path (so evaluation/benchmarking can compare LLM vs non-LLM runs fairly).

Work:

1. Locate pred-run generation (`cookimport/labelstudio/ingest.py`), typically a function that:
  - loads source(s),
  - runs conversion,
  - generates chunks/spans,
  - writes pred-run artifacts + run manifest.

2. Thread run settings into this path (if not already) and apply the same orchestrator call at the same semantic point:
  - after conversion and limit,
  - before chunking/spans writing.

3. Update run manifest parity tests and any benchmark utilities that assume fixed runConfig keys.

Proof/acceptance:

- A pred-run manifest includes `llm_recipe_pipeline` in runConfig when enabled.
- Tests verifying shared runConfig keys between stage and pred-run pass.


## Validation / Acceptance (human-verifiable)


### End-to-end run (requires codex-farm installed)


From repo root:

1. Ensure pipeline pack exists at `<repo_root>/llm_pipelines/` and contains the required sentinel directories:
    llm_pipelines/
      pipelines/
      prompts/
      schemas/

2. Run stage with LLM mode enabled:

    cookimport stage data/input/<some_book>.epub \
      --output-dir data/output \
      --llm-recipe-pipeline codex-farm-3pass-v1

3. Observe:

- Console logs show 3 codex-farm invocations for that workbook:
  - `recipe.chunking.v1`
  - `recipe.schemaorg.v1`
  - `recipe.final.v1`
- In the output run directory:
  - `raw/llm/<workbook_slug>/pass1_chunking/in/*.json` exists
  - `raw/llm/<workbook_slug>/pass1_chunking/out/*.json` exists
  - `raw/llm/<workbook_slug>/pass2_schemaorg/in/*.json` exists
  - `raw/llm/<workbook_slug>/pass2_schemaorg/out/*.json` exists
  - `raw/llm/<workbook_slug>/pass3_final/in/*.json` exists
  - `raw/llm/<workbook_slug>/pass3_final/out/*.json` exists
  - `raw/llm/<workbook_slug>/llm_manifest.json` exists
- Intermediate drafts and final drafts exist in their usual locations and contain LLM-generated content.

4. Re-run the same command (new timestamp run dir). Confirm the run still succeeds and produces LLM artifacts again.

### Test suite (does not require codex-farm)


From repo root:

    pytest -q

Expected:

- New tests for the fake runner + orchestrator pass.
- Existing staging and labelstudio tests still pass (or are updated to include new runConfig keys without breaking).


## Progress


- [x] (2026-02-22_14.30.00) Added `RunSettings` codex-farm fields (`llm_recipe_pipeline`, `codex_farm_cmd`, `codex_farm_root`, `codex_farm_context_blocks`, `codex_farm_failure_mode`) and wired stage/benchmark CLI options.
- [x] (2026-02-22_14.31.00) Applied run-setting plumbing across stage + pred-run generation and updated run-manifest parity coverage.
- [x] (2026-02-22_14.26.00) Added strict Pydantic pass contracts (`pass1/pass2/pass3`) and bundle ID helpers under `cookimport/llm/`.
- [x] (2026-02-22_14.26.00) Implemented `SubprocessCodexFarmRunner` + `FakeCodexFarmRunner` and tests for pipeline ordering/missing-binary behavior.
- [x] (2026-02-22_14.30.00) Implemented 3-pass orchestrator including bundle write/read, pass boundary application, non-recipe recompute, override maps, and `llm_manifest.json`.
- [x] (2026-02-22_14.31.00) Integrated orchestrator into single-file stage path and split-merge path, including merged `full_text.json` assembly for split runs.
- [x] (2026-02-22_14.31.00) Extended writer interfaces to support schema.org/final draft override maps and report `llmCodexFarm`.
- [x] (2026-02-22_14.38.00) Verified with targeted tests (no live codex-farm): `tests/test_run_settings.py`, `tests/test_cli_llm_flags.py`, `tests/test_writer_overrides.py`, `tests/test_codex_farm_contracts.py`, `tests/test_codex_farm_orchestrator.py`, `tests/test_run_manifest_parity.py`.
- [ ] (deferred by instruction) Live codex-farm end-to-end run remains intentionally unexecuted to avoid burning tokens before explicit approval.


## Surprises & Discoveries


- Observation: Rich Typer help truncates long option names in default-width tests, which hid full `--llm-recipe-pipeline` in stdout assertions.
  Evidence: `tests/test_cli_llm_flags.py` failed until help invocation forced wider columns (`env={"COLUMNS": "240"}`).
- Observation: Split-merge payloads had rebased recipe/tip/topic indices but no merged full block artifact suitable for pass1 codex-farm context building.
  Evidence: `_merge_split_jobs(...)` now rebuilds `raw/<importer>/<source_hash>/full_text.json` from `.job_parts/.../raw/**/full_text.json` before invoking codex-farm.
- Observation: Per-recipe contract failures should degrade locally (deterministic fallback) while still allowing successful recipes to keep LLM outputs.
  Evidence: `test_orchestrator_recipe_level_failures_fallback_without_crashing` validates pass2 failure isolation and run continuation.


## Decision Log


- Decision: Keep default pipeline deterministic (`llm_recipe_pipeline=off`) and gate codex-farm with explicit opt-in settings only.
  Rationale: Preserves existing behavior and avoids accidental token usage.
  Date/Author: 2026-02-22 / Codex
- Decision: Use fail-fast for subprocess/setup errors by default (`codex_farm_failure_mode=fail`) with explicit `fallback` mode for graceful degradation.
  Rationale: Missing binary/pipeline-pack is usually a configuration error that should be obvious unless caller explicitly requests fallback.
  Date/Author: 2026-02-22 / Codex
- Decision: Apply pass2/pass3 outputs via writer override maps keyed by stable recipe IDs rather than replacing writer paths.
  Rationale: Keeps canonical output layout untouched while allowing LLM payload substitution.
  Date/Author: 2026-02-22 / Codex
- Decision: Execute codex-farm orchestration in both stage single-file path and split-merge path, with merged full-block reconstruction for split jobs.
  Rationale: Avoids stage-vs-split behavioral divergence and keeps pass1 context semantics consistent.
  Date/Author: 2026-02-22 / Codex
- Decision: Do not run live codex-farm in validation for this implementation pass.
  Rationale: Explicit user instruction to avoid token burn until approved.
  Date/Author: 2026-02-22 / Codex


## Outcomes & Retrospective


Implemented the recipeimport-side codex-farm integration end-to-end for code/test/doc wiring: new run settings + CLI exposure, strict pass contracts, subprocess/fake runners, 3-pass orchestration with manifest emission, split-merge compatibility, writer overrides, and report/run-config parity surfaces across stage and pred-run flows.

This materially improves readiness for LLM-assisted recipe correction while keeping deterministic behavior as the default and preserving existing output paths.

Remaining gap is intentional: no live codex-farm run was executed in this pass because token-spend testing was explicitly deferred. When approved, the next step is one controlled end-to-end validation run to verify actual codex-farm subprocess behavior and real output quality.

Revision note (2026-02-22_14.41.28): Updated this ExecPlan from design-only state to implementation-complete status, including concrete test evidence and explicit deferment rationale for live codex-farm execution.
