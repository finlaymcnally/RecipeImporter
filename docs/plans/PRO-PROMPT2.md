# Retarget CodexFarm to atomic line roles and shared recipe building

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `PLANS.md` from the repository root.

## Purpose / Big Picture

After this change, `cookimport` will have a benchmark path that asks CodexFarm to solve the same problem that the benchmark grades. Today the visible CodexFarm prompt path is finding recipe spans and extracting a schema.org `Recipe`, while the benchmark grades canonical line labels such as `INGREDIENT_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `INSTRUCTION_LINE`, and `KNOWLEDGE`. The result is that CodexFarm can appear to “work” at recipe extraction while barely moving the benchmark that matters.

The new behavior is: mixed recipe blocks are first split into atomic line candidates, then those atomic lines are labeled directly with the benchmark taxonomy, and then both benchmark predictions and optional draft-building logic consume the same labeled lines. A user will be able to run a benchmark command with `--line-role-pipeline codex-line-role-v1 --atomic-block-splitter atomic-v1`, open the run directory under `data/golden/benchmark-vs-golden/<timestamp>/`, and see better line-role metrics, reduced `OTHER -> KNOWLEDGE` and `INGREDIENT_LINE -> YIELD_LINE` confusions, and new diagnostics that explain exactly where CodexFarm helped or hurt.

## Progress

- [x] (2026-03-03 03:28Z) Reviewed the provided benchmark bundles, prompt log samples, AI onboarding summary, and plan requirements. Confirmed that the current CodexFarm prompt path is recipe extraction oriented instead of canonical line labeling.
- [x] (2026-03-03 03:28Z) Chose the primary fix direction: add a separate atomic line-role pipeline instead of stretching `llm_recipe_pipeline` to serve two incompatible goals.
- [ ] (2026-03-03 03:28Z) Add new run settings and CLI flags for `line_role_pipeline` and `atomic_block_splitter`, and record them in manifests and comparison summaries.
- [ ] (2026-03-03 03:28Z) Implement deterministic atomization of mixed recipe blocks into benchmark-sized atomic line candidates.
- [ ] (2026-03-03 03:28Z) Implement deterministic-first canonical line-role classification with optional Codex fallback on ambiguous atomic lines only.
- [ ] (2026-03-03 03:28Z) Wire benchmark export and optional draft building to consume the same labeled atomic lines.
- [ ] (2026-03-03 03:28Z) Add paired-run diagnostics, stable cutdown exports, and regression gates.
- [ ] (2026-03-03 03:28Z) Update docs and run the acceptance benchmark on `thefoodlabCUTDOWN`; if `SeaAndSmokeCUTDOWN` exists locally, run the same gates there before considering the work complete.

## Surprises & Discoveries

- Observation: The provided CodexFarm prompt log is not a canonical labeler. It visibly emits `is_recipe`, `start_block_index`, `end_block_index`, `title`, then a schema.org `Recipe` with `recipeIngredient` and `recipeInstructions`.
  Evidence: The sampled pass1 output for `FOOLPROOF HOLLANDAISE SAUCE` returns `is_recipe: true` and span boundaries; the sampled pass2 output returns `"@type":"Recipe"` with `recipeIngredient` and `recipeInstructions`.

- Observation: The input blocks reaching CodexFarm are already malformed for canonical line labeling because one source block can contain yield text, every ingredient, and a method heading in one string.
  Evidence: The sampled hollandaise case contains `MAKES ABOUT 1 CUP ... Kosher salt TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER` in a single block.

- Observation: Current CodexFarm gains are concentrated in broad `KNOWLEDGE` recall while the labels that matter for recipe structure remain flat.
  Evidence: In the provided `thefoodlabCUTDOWN` run, `INGREDIENT_LINE` recall stays `60/437`, `RECIPE_NOTES` stays `10/59`, and `RECIPE_VARIANT` stays `0/27`, while `OTHER -> KNOWLEDGE` and `INGREDIENT_LINE -> YIELD_LINE` remain dominant confusions.

- Observation: The current cutdown export is not reliable enough for forensic debugging because related sampled files can describe the same underlying example inconsistently.
  Evidence: Earlier sampled bundles showed the same example appearing with mismatched labels across `aligned_prediction_blocks` and `correct_label_lines`, which means sampling must be keyed from one joined source of truth.

- Observation: The repo baseline is not fully green even before this change.
  Evidence: `AI_Context.md` records `450 passed`, `5 failed`, `21 warnings`, with the failures concentrated in missing importer fixtures and importer error-path handling. Those failures are not the target of this ExecPlan and must not be mistaken for new regressions.

## Decision Log

- Decision: Add a new `line_role_pipeline` setting instead of overloading `llm_recipe_pipeline`.
  Rationale: `llm_recipe_pipeline` currently describes recipe extraction behavior. Canonical line labeling is a different task with a different prompt schema, output contract, and acceptance criteria. Keeping them separate prevents future confusion in manifests, comparisons, and prompt logs.
  Date/Author: 2026-03-03 / OpenAI GPT-5.2 Pro

- Decision: Split mixed recipe blocks before any LLM call.
  Rationale: Asking an LLM to infer hidden line boundaries inside a single block is exactly what caused the benchmark mismatch. Deterministic atomization gives both the rules and the LLM a tractable unit of work.
  Date/Author: 2026-03-03 / OpenAI GPT-5.2 Pro

- Decision: Keep the existing recipe extraction passes in parallel during the rollout.
  Rationale: The current pass1-pass3 flow may still be useful for staging outputs. Replacing it outright would blur whether failures come from new labeling logic or from destabilizing extraction. Parallel paths make the change reversible and easier to validate.
  Date/Author: 2026-03-03 / OpenAI GPT-5.2 Pro

- Decision: Treat `KNOWLEDGE` as a tightly controlled label, especially inside active recipe spans.
  Rationale: The benchmark evidence shows `KNOWLEDGE` functioning as a junk drawer. Inside a recipe span, the default posture should be `title`, `variant`, `note`, `yield`, `ingredient`, `how-to heading`, `instruction`, `time`, or `other`. `KNOWLEDGE` should only survive when the line is truly prose and the local neighborhood supports that reading.
  Date/Author: 2026-03-03 / OpenAI GPT-5.2 Pro

- Decision: Fix benchmark artifacts and sampling in the same branch.
  Rationale: Better labeling without better diagnostics will still leave the team unable to trust or debug run-to-run deltas. The instrumentation is part of the product here, not optional polish.
  Date/Author: 2026-03-03 / OpenAI GPT-5.2 Pro

## Outcomes & Retrospective

Initial planning state only. No code has been changed yet. The expected outcome of the completed plan is a benchmark-visible CodexFarm improvement that comes from direct line-role prediction rather than accidental side effects of recipe-object extraction. Completion is not just “code merged”; completion means a human can run the benchmark, inspect the new artifacts, and see that the major confusions discussed in the provided bundles have materially decreased.

## Context and Orientation

`cookimport` is a deterministic-first local pipeline that imports source files, builds structured recipe drafts, and supports Label Studio export and benchmarking. The important existing directories are `cookimport/parsing/` for parsing logic, `cookimport/staging/` for draft shaping and writer logic, `cookimport/labelstudio/` for import/export/eval/prelabel flows, `cookimport/bench/` for offline benchmark tooling, `cookimport/config/` for run settings, and `cookimport/cli.py` for the Typer CLI surface.

This plan uses four terms repeatedly:

A “recipe span” is the contiguous range of source blocks believed to belong to one recipe. The current CodexFarm pass1 output already tries to find these spans.

An “atomic line candidate” is the smallest line-like unit that the benchmark can sensibly label. If one EPUB block says `MAKES ABOUT 1 CUP 3 large egg yolks ... TO MAKE HOLLANDAISE ...`, the atomic candidates should be separate yield, ingredient, and method-heading lines even if the source extractor merged them.

A “canonical line label” is the benchmark taxonomy label assigned to one atomic line, for example `INGREDIENT_LINE` or `RECIPE_NOTES`.

A “projection” is the conversion from atomic line labels into the freeform span artifacts that `labelstudio-benchmark` and `labelstudio-eval` already know how to compare against gold.

The current evidence says the core problem is task mismatch. The benchmark is `canonical_text_classification`, but the visible CodexFarm prompt path is recipe-span and schema extraction. That mismatch is amplified by merged source blocks, which make it impossible to cleanly recover line-level roles after the fact. The result is the exact pattern seen in the bundles: tiny overall gains, flat ingredient recall, flat note recall, zero variant recall, and a large tendency to dump ambiguous lines into `KNOWLEDGE` or `YIELD_LINE`.

The implementation must therefore create one shared source of truth for recipe-adjacent text: atomized lines plus canonical labels. The benchmark path must consume those labels directly, and the draft builder should be able to opt into them so the staging pipeline improves from the same work.

## Plan of Work

### Milestone 1 - Separate the benchmark-targeted line-role pipeline from recipe extraction

At the end of this milestone, the run configuration will make the architecture honest. A benchmark run will be able to say, in plain configuration fields, whether recipe extraction is on, whether atomic splitting is on, and whether direct line-role labeling is on.

Edit `cookimport/config/run_settings.py` to add two new settings with conservative defaults:

    line_role_pipeline: Literal["off", "deterministic-v1", "codex-line-role-v1"] = "off"
    atomic_block_splitter: Literal["off", "atomic-v1"] = "off"

Do not remove or rename `llm_recipe_pipeline`. It remains responsible for the existing recipe extraction passes.

Update the CLI in `cookimport/cli.py` so every command that can produce benchmark or prediction artifacts accepts the new flags. At minimum, `labelstudio-benchmark`, `labelstudio-eval` when predictions are being generated locally, and any relevant `bench run` command should carry them through `RunSettings`.

Find the code that writes `run_manifest.json`, `need_to_know_summary.json`, and `comparison_summary.json`. If those writers are still embedded in `cookimport/cli.py`, extract them into small modules under `cookimport/runs/` or `cookimport/bench/` before adding fields. The new summaries must always report all three knobs separately: `llm_recipe_pipeline`, `atomic_block_splitter`, and `line_role_pipeline`.

Add a small regression test under `tests/bench/` or `tests/labelstudio/` that constructs paired run summaries and verifies that a run with recipe extraction on but line-role labeling off does not claim to be a canonical labeler.

This milestone is complete when a benchmark summary can distinguish “CodexFarm extracted recipes” from “CodexFarm labeled canonical lines.”

### Milestone 2 - Atomize mixed source blocks into benchmark-sized lines

At the end of this milestone, the system will have a deterministic pre-splitter that converts merged EPUB or text blocks into line-like units that map cleanly to the benchmark taxonomy.

Create `cookimport/parsing/recipe_block_atomizer.py`. Define a serializable model named `AtomicLineCandidate` with enough information to explain and replay every split:

    class AtomicLineCandidate(BaseModel):
        recipe_id: str | None
        block_id: str
        block_index: int
        atomic_index: int
        text: str
        within_recipe_span: bool
        candidate_labels: list[str]
        prev_text: str | None = None
        next_text: str | None = None
        rule_tags: list[str] = []

Define the entry point:

    def atomize_blocks(blocks: Sequence[SourceBlock], *, recipe_id: str | None, within_recipe_span: bool) -> list[AtomicLineCandidate]:
        ...

Use deterministic boundary rules first. Reuse existing ingredient and yield heuristics where available instead of re-inventing them. Add explicit split rules for the cases already seen in the bundles:

- `NOTE:` or `NOTE :` starts a note line.
- `MAKES`, `SERVES`, `YIELDS`, and similar yield prefixes start a yield line.
- Numbered step prefixes such as `1.` start instruction lines.
- Uppercase headings such as `TO MAKE HOLLANDAISE...`, `FOR THE JUNIPER VINEGAR`, `FOR SERVING`, and similar method or subsection headings become their own atomic lines.
- Quantity-first ingredient patterns such as `3 tablespoons`, `1/2 cup`, `4 large eggs`, and range patterns such as `4 to 6 chicken leg quarters` become ingredient lines, not yield lines.
- Variant headers in all caps or title case under an existing recipe title become standalone variant candidates.

Create fixture files under `tests/fixtures/canonical_labeling/` that mirror the failure cases from the provided bundles. At minimum include:

- `hollandaise_merged_block.json`
- `omelet_variant_lines.json`
- `braised_chicken_tail_steps.json`
- `ingredient_vs_yield_ranges.json`

Add unit tests in `tests/parsing/test_recipe_block_atomizer.py`. The most important acceptance test is that the hollandaise merged block atomizes into separate candidates for the note line, the yield line, each ingredient line, and the method heading. Another acceptance test must prove that a quantity range like `4 to 6 chicken leg quarters` is never emitted as yield merely because it starts with a number.

This milestone is complete when the atomizer can turn the known broken examples into atomic candidates that a human would consider labelable without extra hidden context.

### Milestone 3 - Add a deterministic-first canonical line-role pipeline with optional Codex fallback

At the end of this milestone, the system will be able to assign benchmark labels directly to atomic lines, using rules first and Codex only for the ambiguous remainder.

Create `cookimport/parsing/canonical_line_roles.py`. Define a serializable prediction model:

    class CanonicalLineRolePrediction(BaseModel):
        block_id: str
        atomic_index: int
        text: str
        label: str
        confidence: float
        decided_by: Literal["rule", "codex", "fallback"]
        reason_tags: list[str] = []

Define the entry point:

    def label_atomic_lines(candidates: Sequence[AtomicLineCandidate], settings: RunSettings) -> list[CanonicalLineRolePrediction]:
        ...

Inside this module, add a rule engine first. The rule engine must make all low-ambiguity decisions without paying for LLM calls. Required rules:

- `NOTE:` lines inside recipe spans become `RECIPE_NOTES`.
- Yield-prefixed lines become `YIELD_LINE`.
- Quantity-first or quantity-range lines with ingredient vocabulary become `INGREDIENT_LINE`.
- Numbered steps and imperative cooking sentences become `INSTRUCTION_LINE` unless they are standalone time metadata.
- `TIME_LINE` is reserved for lines whose primary role is time metadata, not any instruction sentence that merely mentions time.
- Variant headers become `RECIPE_VARIANT`.
- Method headings such as `TO MAKE...`, `FOR SERVING`, `FOR THE ...` become `HOWTO_SECTION` if that label is still part of the gold taxonomy; otherwise map them to the agreed header label in use locally. Confirm the exact gold label list before wiring the final mapping.
- Inside active recipe spans, `KNOWLEDGE` is forbidden unless a candidate is explicitly marked as prose by the atomizer and both neighbors reinforce that reading.

Extract the existing `codex exec -` invocation code from `cookimport/labelstudio/prelabel.py` into a shared helper module named `cookimport/llm/codex_exec.py`. Do not duplicate shelling logic in multiple places.

Create `cookimport/llm/canonical_line_role_prompt.py` with a structured prompt builder for ambiguous lines only. The prompt input must include the previous line, the current line, the next line, whether the current line is inside a recipe span, and an explicit `candidate_labels` allowlist. The prompt output must be strict JSON with one label from the allowlist plus short reason tags. Never ask this prompt to emit a schema.org `Recipe`.

The orchestration order must be:

1. Atomize.
2. Run deterministic rules.
3. Send only unresolved candidates to Codex.
4. Merge the results and record `decided_by` for each line.
5. Apply a final sanitizer that rejects impossible label combinations, especially `KNOWLEDGE` inside recipe spans and `YIELD_LINE` for obvious quantity ingredients.

Add tests in `tests/parsing/test_canonical_line_roles.py` that cover the observed failures directly. Required cases include:

- `NOTE: Cooled hollandaise...` becomes `RECIPE_NOTES`.
- `TO MAKE HOLLANDAISE IN A STANDARD BLENDER OR FOOD PROCESSOR` does not become `KNOWLEDGE`.
- `DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET` becomes `RECIPE_VARIANT`.
- `3 tablespoons whole milk` becomes `INGREDIENT_LINE`, not `YIELD_LINE`.
- `5. Add the heavy cream... about 1 minute...` remains `INSTRUCTION_LINE`, not `TIME_LINE`.
- A knowledge prose paragraph outside the recipe span can still become `KNOWLEDGE`.

This milestone is complete when the fixture suite proves that the previously discussed failure modes are impossible or strongly disfavored in the new pipeline.

### Milestone 4 - Project atomic line roles into benchmark spans and optionally build drafts from the same labels

At the end of this milestone, the benchmark path and the optional staging path will both consume the same line-role predictions.

Create `cookimport/labelstudio/canonical_line_projection.py` if no equivalent module already exists. Define:

    def project_line_roles_to_freeform_spans(predictions: Sequence[CanonicalLineRolePrediction]) -> list[FreeformSpanPrediction]:
        ...

This projection must preserve stable `line_index`, `block_id`, and `atomic_index` metadata so downstream artifacts can be joined back to the original source and to each other.

Wire the benchmark command so that when `line_role_pipeline != "off"`, predictions are generated from atomic line roles instead of from recipe-object extraction side effects. Keep the old path available while the new path is under evaluation, but make the new artifacts unmistakable by writing them under a subdirectory such as `line-role-pipeline/` inside the run root.

Then update `cookimport/staging/draft_v1.py` so it can optionally build recipe fields from labeled atomic lines. This must be an opt-in path controlled by the same run settings. The draft builder should consume the new labels in this order:

- `RECIPE_TITLE` and `RECIPE_VARIANT` for names and variants.
- `RECIPE_NOTES` for description or note capture.
- `YIELD_LINE` for `recipeYield`.
- `INGREDIENT_LINE` for `recipeIngredient`.
- `INSTRUCTION_LINE` and `HOWTO_SECTION` for `recipeInstructions` and subsection organization.

Do not remove the existing pass1-pass3 recipe-object extraction yet. Keep it as a parallel path until the benchmark and sample draft outputs prove that the atomic line-role path is better. Add an integration test that runs a tiny synthetic source through the full path and verifies that benchmark spans and draft fields agree on ingredients, notes, and instructions.

This milestone is complete when one run can generate both benchmark predictions and recipe draft fields from the same labeled atomic lines.

### Milestone 5 - Add diagnostics, stabilize cutdown exports, and install regression gates

At the end of this milestone, the team will be able to explain benchmark deltas instead of guessing.

Create or update a benchmark analysis module under `cookimport/bench/`. If there is no natural existing home, create these modules:

- `cookimport/bench/pairwise_flips.py`
- `cookimport/bench/slice_metrics.py`
- `cookimport/bench/cutdown_export.py`

The run directory for any benchmark executed with `line_role_pipeline != "off"` must emit at least these artifacts:

- `line_role_predictions.jsonl`: one row per atomic line prediction.
- `line_role_flips_vs_baseline.jsonl`: only the lines where baseline and Codex disagree, joined with gold label when present.
- `slice_metrics.json`: metrics for at least `outside_recipe`, `recipe_titles_and_variants`, `recipe_notes_and_yield`, `recipe_ingredients`, and `recipe_instructions`.
- `knowledge_budget.json`: counts of `KNOWLEDGE` predictions inside and outside recipe spans.
- `prompt_eval_alignment.md`: a human-readable explanation of which prompt family produced which artifact family.
- Stable cutdown samples where every sampled row is keyed from one joined line table. The same `sample_id` must be used across all sampled files.

Add tests in `tests/bench/test_cutdown_export_consistency.py` that prove the same sampled line has the same identifiers and text across `wrong_label_lines`, `correct_label_lines`, `aligned_prediction_blocks`, and any new flip reports.

Add metric gates to the benchmark runner. The implementation must fail the gated benchmark run if all of these are not true on `thefoodlabCUTDOWN`:

- `macro_f1_excluding_other` improves by at least `0.05` over the current vanilla baseline.
- `overall_line_accuracy` improves by at least `0.05` over the current vanilla baseline.
- `INGREDIENT_LINE -> YIELD_LINE` confusion count drops by at least `40%` from the current CodexFarm baseline.
- `OTHER -> KNOWLEDGE` confusion count drops by at least `30%` from the current CodexFarm baseline.
- `RECIPE_NOTES` recall exceeds `0.40`.
- `RECIPE_VARIANT` recall exceeds `0.40`.
- `INGREDIENT_LINE` recall exceeds `0.35`.

If `SeaAndSmokeCUTDOWN` exists locally, add a second gate: the new line-role pipeline must not perform worse than vanilla on macro F1 or overall line accuracy there. The point is to prevent a The Food Lab only fix that regresses on another prose-heavy cookbook.

Update `docs/04-parsing/04-parsing_readme.md`, `docs/06-label-studio/06-label-studio_README.md`, and `docs/07-bench/07-bench_README.md` so a new contributor can understand what `atomic_block_splitter` and `line_role_pipeline` do, when to enable them, and how to read the new benchmark artifacts.

This milestone is complete when the benchmark can both prove improvement and explain improvement.

## Concrete Steps

Work from the repository root.

1. Add the new run settings and CLI flags first, before touching behavior. Run the smallest targeted tests immediately after each edit.

    python -m pytest tests/bench -k run_config

2. Add the atomizer models, rules, fixtures, and unit tests.

    python -m pytest tests/parsing/test_recipe_block_atomizer.py

3. Add the line-role rules, shared Codex CLI helper, prompt builder, and line-role tests.

    python -m pytest tests/parsing/test_canonical_line_roles.py

4. Wire the benchmark projection path and the optional draft builder path. Add an integration test that exercises both.

    python -m pytest tests/labelstudio tests/bench -k line_role

5. Add the new diagnostics and stable cutdown sampling.

    python -m pytest tests/bench/test_cutdown_export_consistency.py

6. Run the benchmark locally on the provided book. The command below is the new target contract. If the current CLI cannot express it yet, implement this exact command surface as part of the work.

    cookimport labelstudio-benchmark \
      --source data/input/thefoodlabCUTDOWN.epub \
      --gold-export-dir data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports \
      --llm-recipe-pipeline codex-farm-3pass-v1 \
      --atomic-block-splitter atomic-v1 \
      --line-role-pipeline codex-line-role-v1

    Expected observable output in the terminal should include the run directory and the new artifact names, for example:

      Wrote benchmark run to data/golden/benchmark-vs-golden/2026-03-03_.../
      Wrote line_role_predictions.jsonl
      Wrote slice_metrics.json
      Wrote line_role_flips_vs_baseline.jsonl
      Overall line accuracy: >= 0.45 and trending upward from baseline
      Macro F1 (excluding OTHER): >= 0.34 and trending upward from baseline

7. If `SeaAndSmokeCUTDOWN` is available locally, run the same command with that source and its matching gold export directory. Do not skip this check if the fixture exists; it is the hedge against overfitting.

8. Run the full test suite once at the end.

    python -m pytest

    Because the repo currently has known baseline failures unrelated to this work, success means: all new and modified tests pass, and the total failure count is no worse than the baseline recorded in `AI_Context.md` unless you choose to fix those unrelated importer failures in the same branch.

## Validation and Acceptance

The feature is accepted only when all of the following are true.

A human can point the benchmark command at `thefoodlabCUTDOWN` and see that the run config now separately reports recipe extraction, atomic splitting, and canonical line-role labeling.

The hollandaise merged-block fixture no longer reaches the classifier as one opaque line. Its yield text, ingredient list, and method heading appear as separate atomic candidates, and the resulting labels match the intended benchmark taxonomy.

The major previously discussed errors are visibly fixed in the new artifact set:

- `NOTE: Cooled hollandaise...` is no longer `OTHER`.
- `TO MAKE HOLLANDAISE...` is no longer `KNOWLEDGE`.
- `DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET` is no longer `KNOWLEDGE`.
- `3 tablespoons whole milk` is no longer `YIELD_LINE`.
- `5. Add the heavy cream...` is no longer `TIME_LINE`.

The run directory contains the new diagnostics, and `line_role_flips_vs_baseline.jsonl` makes it easy to inspect only the baseline-versus-Codex disagreements.

The metric gates in Milestone 5 pass on `thefoodlabCUTDOWN`, and if `SeaAndSmokeCUTDOWN` exists locally, the non-regression gate passes there too.

The optional draft builder path, when enabled, produces recipe drafts whose ingredients, notes, yields, and instructions align with the benchmark-visible line roles for the same source.

## Idempotence and Recovery

All new settings must default to `off`, which keeps existing behavior unchanged until the new pipeline is deliberately enabled.

Benchmark runs are already timestamped under `data/golden/benchmark-vs-golden/`, so rerunning commands is safe. Never overwrite old run roots except for explicitly generated cutdown samples inside one run.

If the new line-role path misbehaves during development, disable it by setting `--line-role-pipeline off --atomic-block-splitter off`. The existing recipe extraction path must remain runnable throughout the migration.

Keep the atomizer and line-role logic additive until the benchmark proves the new path is better. Only after the metrics and sample outputs are clearly superior should the old projection shortcuts be retired.

If cutdown export changes produce inconsistent artifacts, roll back only the new sampler module and regenerate the run from the unchanged full predictions. The full prediction artifacts must stay authoritative.

## Artifacts and Notes

Use these short examples to anchor implementation details.

Example atomicization target for the hollandaise case:

    input block text:
      MAKES ABOUT 1 CUP 3 large egg yolks 1 tablespoon lemon juice (from 1 lemon) ... Kosher salt TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER

    desired atomic candidates, in order:
      ABOUT 1 CUP                      -> YIELD_LINE candidate
      3 large egg yolks               -> INGREDIENT_LINE candidate
      1 tablespoon lemon juice...     -> INGREDIENT_LINE candidate
      ...
      Kosher salt                     -> INGREDIENT_LINE candidate
      TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER -> HOWTO_SECTION candidate

Example ambiguous-line Codex prompt payload shape:

    {
      "recipe_id": "urn:recipeimport:...:c0",
      "within_recipe_span": true,
      "prev_text": "Kosher salt",
      "text": "TO MAKE HOLLANDAISE IN A STANDARD BLENDER OR FOOD PROCESSOR",
      "next_text": "1. Add the egg yolks, lemon juice, and hot water...",
      "candidate_labels": ["HOWTO_SECTION", "INSTRUCTION_LINE", "OTHER"],
      "hard_constraints": ["Do not return KNOWLEDGE for this line."]
    }

Example required row shape for the joined diagnostic table used by cutdown export:

    {
      "sample_id": "line-000975",
      "line_index": 975,
      "block_id": "b803",
      "atomic_index": 0,
      "text": "TO MAKE HOLLANDAISE IN A STANDARD BLENDER OR FOOD PROCESSOR",
      "gold_label": "INSTRUCTION_LINE",
      "baseline_label": "OTHER",
      "codex_label": "HOWTO_SECTION"
    }

## Interfaces and Dependencies

Use Pydantic v2 models for new serialized artifact shapes because the repo already relies on Pydantic heavily.

In `cookimport/config/run_settings.py`, add the settings exactly as described in Milestone 1 and thread them through any manifest or hash logic so benchmark comparison can see them.

In `cookimport/parsing/recipe_block_atomizer.py`, define:

    class AtomicLineCandidate(BaseModel):
        recipe_id: str | None
        block_id: str
        block_index: int
        atomic_index: int
        text: str
        within_recipe_span: bool
        candidate_labels: list[str]
        prev_text: str | None = None
        next_text: str | None = None
        rule_tags: list[str] = []

    def atomize_blocks(blocks: Sequence[SourceBlock], *, recipe_id: str | None, within_recipe_span: bool) -> list[AtomicLineCandidate]:
        ...

In `cookimport/parsing/canonical_line_roles.py`, define:

    class CanonicalLineRolePrediction(BaseModel):
        block_id: str
        atomic_index: int
        text: str
        label: str
        confidence: float
        decided_by: Literal["rule", "codex", "fallback"]
        reason_tags: list[str] = []

    def label_atomic_lines(candidates: Sequence[AtomicLineCandidate], settings: RunSettings) -> list[CanonicalLineRolePrediction]:
        ...

In `cookimport/llm/codex_exec.py`, extract a shared helper from the current prelabel implementation:

    def run_codex_json_prompt(*, prompt: str, timeout_seconds: int, log_path: Path | None = None) -> dict[str, Any]:
        ...

In `cookimport/labelstudio/canonical_line_projection.py`, define:

    def project_line_roles_to_freeform_spans(predictions: Sequence[CanonicalLineRolePrediction]) -> list[FreeformSpanPrediction]:
        ...

The line-role prompt must emit only the benchmark label enum, never free text labels. The allowlist passed into the prompt is the contract. If the model returns anything outside the allowlist, the sanitizer must reject it and fall back to deterministic rules plus an error note in the artifact log.

When updating `cookimport/staging/draft_v1.py`, add a clearly named adapter function rather than sprinkling line-role lookups inline. A concrete target name is:

    def build_recipe_fields_from_line_roles(predictions: Sequence[CanonicalLineRolePrediction]) -> DraftRecipeFields:
        ...

That adapter keeps the shared source of truth explicit and makes the migration reversible.

Plan revision note: 2026-03-03 initial draft created from the provided benchmark bundles, prompt-log samples, `AI_Context.md`, and `PLANS.md`. The plan chooses a parallel atomic line-role path because the evidence showed a prompt/eval mismatch rather than a simple model-quality shortfall.
