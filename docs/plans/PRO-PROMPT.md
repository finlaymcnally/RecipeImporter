---
summary: "ExecPlan for fixing canonical HOWTO accounting and adding benchmark line-role configuration knobs."
read_when:
  - "When implementing or reviewing the PRO-PROMPT benchmark line-role plan."
---

# Fix canonical line-label evaluation metrics and retarget CodexFarm to atomic line roles

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `PLANS.md` from the repository root.

## Purpose / Big Picture

Today the canonical "one label per line" benchmark is undermined by two issues:

1. The evaluation report can mis-account labels (observed: `HOWTO_SECTION` shows `gold_total=0` / `pred_total=0` even when sampled correct lines include it), which makes per-label deltas and confusion matrices untrustworthy.
2. The visible CodexFarm prompt path is solving a different problem than the benchmark grades. It finds recipe spans and extracts a schema.org `Recipe`, while the benchmark grades canonical line labels like `INGREDIENT_LINE`, `RECIPE_NOTES`, `RECIPE_VARIANT`, `INSTRUCTION_LINE`, and `KNOWLEDGE`. Merged source blocks (yield + ingredients + headings in one block) amplify the mismatch and lead to the dominant confusions seen in the bundles (`OTHER -> KNOWLEDGE`, `INGREDIENT_LINE -> YIELD_LINE`, etc).

After this change, `cookimport` will have a benchmark-targeted path that fixes evaluation accounting and then asks CodexFarm (optionally) to solve the same problem the benchmark grades:

- Mixed recipe blocks are deterministically split into "atomic line candidates".
- Those atomic lines are labeled directly with the benchmark taxonomy (deterministic rules first; Codex only for ambiguous lines; strict JSON parsing/validation; prompt logs saved in run artifacts).
- Both benchmark predictions and optional draft-building consume the same labeled atomic lines so improvements are shared and debuggable.

You will see it working by running:

    cookimport labelstudio-benchmark \
      --source data/input/thefoodlabCUTDOWN.epub \
      --gold-export-dir data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports \
      --llm-recipe-pipeline codex-farm-3pass-v1 \
      --atomic-block-splitter atomic-v1 \
      --line-role-pipeline codex-line-role-v1

and observing:

- per-label totals/confusion matrices include all labels present (including `HOWTO_SECTION` when present),
- reduced `OTHER -> KNOWLEDGE` and `INGREDIENT_LINE -> YIELD_LINE` confusions,
- improved `macro_f1_excluding_other` and `overall_line_accuracy` over vanilla,
- new diagnostics artifacts that explain deltas (predictions, flips, slice metrics, stable cutdowns),
- and (optionally) draft outputs consistent with the same line roles.

## Progress

- [x] (2026-03-03 00:00Z) Captured the two primary problem classes in an ExecPlan: evaluation label accounting errors and CodexFarm task mismatch for canonical line benchmarks.
- [x] (2026-03-03 03:28Z) Reviewed the provided benchmark bundles and prompt log samples; confirmed that the current CodexFarm prompt path is schema extraction oriented, not canonical line labeling, and that merged blocks are a root cause.
- [x] (2026-03-03 03:28Z) Merged the best ideas from `docs/plans/PRO-PROMPT.md` and `docs/plans/PRO-PROMPT2.md` into this single plan; removed the duplicate plan file.
- [ ] Reproduce the current benchmark locally and confirm the evaluation bug (`HOWTO_SECTION` totals incorrectly reported as 0). (completed: synthetic canonical fixture reproduction; remaining: full CUTDOWN benchmark replay)
- [x] (2026-03-02 23:30Z) Milestone 0: Fixed canonical-text HOWTO label accounting and added a regression test that verifies `per_label` + confusion include `HOWTO_SECTION`.
- [x] (2026-03-02 23:30Z) Milestone 1: Added `line_role_pipeline` and `atomic_block_splitter` run settings + CLI flags, propagated them through prediction generation/manifests, and included them in benchmark cutdown summaries.
- [x] (2026-03-02 23:38Z) Milestone 2: Added `cookimport/parsing/recipe_block_atomizer.py` with deterministic boundary-first splitting plus fixture-backed tests for merged blocks, variant lines, inline numbered tails, and ingredient-range vs yield behavior.
- [ ] Milestone 3: Implement deterministic-first canonical line-role classification with optional Codex fallback (strict parsing, prompt logs, tests).
- [ ] Milestone 4: Wire benchmark export and optional draft building to consume the same labeled atomic lines (integration test).
- [ ] Milestone 5: Add paired-run diagnostics, stable cutdown exports, and regression gates; update docs; run acceptance benchmark(s) and record results here.

## Surprises & Discoveries

- Observation: The evaluation report shows `HOWTO_SECTION` with `gold_total=0` and `pred_total=0` even though sampled "correct label lines" include `gold_label: HOWTO_SECTION, pred_label: HOWTO_SECTION`.
  Evidence: Exported benchmark bundles contain both (a) per-label totals that zero out HOWTO_SECTION and (b) sampled correct lines with HOWTO_SECTION matches.

- Observation: The provided CodexFarm prompt log is not a canonical line labeler. It emits `is_recipe`, span boundaries, and a schema.org `Recipe` with `recipeIngredient` and `recipeInstructions`.
  Evidence: Sampled pass outputs include `"@type":"Recipe"` payloads.

- Observation: The input blocks reaching CodexFarm are already malformed for canonical line labeling: one source block can contain yield text, every ingredient, and a method heading.
  Evidence: The sampled hollandaise case includes `MAKES ABOUT 1 CUP ... Kosher salt TO MAKE HOLLANDAISE ...` in one block.

- Observation: Current CodexFarm gains are concentrated in broad `KNOWLEDGE` recall while labels that matter for recipe structure remain flat, with dominant confusions like `OTHER -> KNOWLEDGE` and `INGREDIENT_LINE -> YIELD_LINE`.
  Evidence: Provided benchmark confusion summaries.

- Observation: Cutdown exports can be internally inconsistent (the same example can appear with mismatched IDs/labels across multiple sampled files), which blocks forensics.
  Evidence: Earlier bundles show mismatches across `aligned_prediction_blocks` and `correct_label_lines`.

- Observation: The repo baseline is not fully green even before this change.
  Evidence: `AI_Context.md` records failures concentrated in missing importer fixtures and error-path handling; they are out of scope for this plan.

- Observation: Prompt logging is not always present in exported packages, which slows iteration.
  Evidence: Some exports omit `codexfarm_prompt_log.dedup.txt`.

- Observation: Canonical evaluator label accounting was unintentionally affected by shared stage-label loading behavior that remapped `HOWTO_SECTION` before metrics.
  Evidence: `evaluate_canonical_text` called `load_stage_block_labels(...)` without disabling HOWTO remap, so predicted HOWTO totals collapsed even when stage predictions explicitly contained HOWTO labels.

## Decision Log

- Decision: Fix evaluation label accounting before optimizing any model/pipeline behavior.
  Rationale: If per-label totals/confusion matrices are wrong, improvements cannot be measured or trusted.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Add a new `line_role_pipeline` setting (and `atomic_block_splitter`) instead of overloading `llm_recipe_pipeline`.
  Rationale: `llm_recipe_pipeline` describes recipe extraction behavior. Canonical line labeling is a different task with a different prompt schema, output contract, and acceptance criteria. Keeping them separate prevents confusion in manifests, comparisons, and prompt logs.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Split mixed recipe blocks before any LLM call.
  Rationale: Asking an LLM to infer hidden line boundaries inside a single merged block is a core cause of benchmark mismatch. Deterministic atomization gives both rules and the LLM a tractable unit.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Keep the existing recipe extraction passes in parallel during rollout.
  Rationale: The pass1-pass3 flow may remain useful for staging outputs. Parallel paths make the change reversible and make attribution of failures clearer.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Treat `KNOWLEDGE` as a tightly controlled label, especially inside active recipe spans.
  Rationale: The evidence shows `KNOWLEDGE` functioning as a junk drawer. Inside recipe spans, bias toward structure labels (title/variant/note/yield/ingredient/heading/instruction/time/other) and only allow `KNOWLEDGE` when the line is truly prose and neighbors support it.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Make prompt logs and benchmark diagnostics part of the contract, not optional.
  Rationale: Better labeling without better forensics still leaves benchmark deltas hard to trust and hard to debug.
  Date/Author: 2026-03-03 / assistant (GPT-5.2 Pro)

- Decision: Keep HOWTO remap behavior for stage/freeform scoring, but preserve explicit `HOWTO_SECTION` in canonical-text scoring.
  Rationale: Stage/freeform comparability still benefits from structural remap, but canonical line-label accounting should reflect the explicit benchmark label when it is present.
  Date/Author: 2026-03-02 / assistant (GPT-5.2)

## Outcomes & Retrospective

Partial implementation complete. Milestones 0, 1, and 2 are now landed:

- canonical-text evaluation keeps explicit HOWTO labels so per-label totals/confusions report them correctly;
- benchmark run settings now expose `llm_recipe_pipeline`, `atomic_block_splitter`, and `line_role_pipeline` independently in run config/manifests/cutdown summaries.
- deterministic block atomization now produces atomic candidates with candidate labels/rule tags and stable adjacency context.

Remaining work is Milestones 3–5 (line-role prediction path, projection/draft wiring, diagnostics/gates, and acceptance benchmarks).

## Context and Orientation

`cookimport` is a deterministic-first local pipeline that imports source files, builds structured recipe drafts, and supports Label Studio export and benchmarking. The important existing directories are:

- `cookimport/parsing/` for parsing logic
- `cookimport/staging/` for draft shaping and writer logic
- `cookimport/labelstudio/` for import/export/eval/prelabel flows
- `cookimport/bench/` for offline benchmark tooling
- `cookimport/config/` for run settings
- `cookimport/cli.py` for the Typer CLI surface

This plan uses four terms repeatedly:

A "recipe span" is the contiguous range of source blocks believed to belong to one recipe. The current CodexFarm pass1 output already tries to find these spans.

An "atomic line candidate" is the smallest line-like unit that the benchmark can sensibly label. If one EPUB block says `MAKES ABOUT 1 CUP 3 large egg yolks ... TO MAKE HOLLANDAISE ...`, the atomic candidates should be separate yield, ingredient, and method-heading lines even if the source extractor merged them.

A "canonical line label" is the benchmark taxonomy label assigned to one atomic line, for example `INGREDIENT_LINE` or `RECIPE_NOTES`.

A "projection" is the conversion from atomic line labels into the freeform span artifacts that `labelstudio-benchmark` and `labelstudio-eval` already know how to compare against gold.

Testing note: per `tests/AGENTS.md`, new tests must live under the correct `tests/<domain>/` folder and be added to the `tests/conftest.py` marker mapping for that domain.

## Plan of Work

### Milestone 0 - Fix canonical-line evaluation label accounting (all labels, including HOWTO_SECTION)

At the end of this milestone, running `cookimport labelstudio-eval` / `cookimport labelstudio-benchmark` on data that includes `HOWTO_SECTION` will report non-zero totals for that label, and the confusion matrix rows/columns will include it.

Work:

1. Locate the evaluation implementation.

   From the repo root, run:

     rg -n "per_label_metrics|top_confusions|macro_f1|Canonical Text Evaluation" cookimport

   Also search for label strings:

     rg -n "HOWTO_SECTION|RECIPE_TITLE|INSTRUCTION_LINE|KNOWLEDGE" cookimport

   You are looking for the code that iterates over gold/pred labels, builds a confusion matrix, and derives per-label totals.

2. Identify how the label set is chosen.

   The likely bug pattern is: overall accuracy is computed from raw line comparisons, but per-label metrics are computed from a restricted allowlist and `HOWTO_SECTION` is missing (or mapped away).

   Fix the code so per-label metrics are computed over the union of:

   - labels present in gold labels
   - labels present in predicted labels
   - labels declared in the canonical label enum (if one exists)

   Use a stable ordering for deterministic reports.

   If the code intentionally excludes some labels from metrics, make that explicit by emitting both:

   - `scored_label_metrics` (explicit allowlist)
   - `all_label_counts` (always all labels present)

   For this bug, the default scored set should include `HOWTO_SECTION`.

3. Add a regression test.

   Create a new test module under `tests/labelstudio/`, for example:

     tests/labelstudio/test_eval_metrics_label_accounting.py

   Ensure the new file is added to the `labelstudio` marker mapping in `tests/conftest.py` per `tests/AGENTS.md`.

   The test should:

   - construct minimal canonical text with at least 3 lines, including one clear HOWTO_SECTION heading line (for example `FOR THE SAUCE`)
   - construct gold labels and predicted labels that match perfectly
   - call the eval function that returns the metrics object (or a thin wrapper)
   - assert that per-label metrics include HOWTO_SECTION with `gold_total == 1`, `pred_total == 1`, and `tp == 1`
   - assert the confusion matrix includes a row/column for HOWTO_SECTION (or that its equivalent representation includes it)

   Keep the fixture purely synthetic so it can be committed without licensing concerns.

Acceptance:

- The regression test passes and fails on the pre-fix behavior.
- Running a real benchmark where HOWTO_SECTION exists no longer reports HOWTO_SECTION totals as zero.

### Milestone 1 - Separate the benchmark-targeted line-role pipeline from recipe extraction

At the end of this milestone, the run configuration will make the architecture honest. A benchmark run will be able to say, in plain config fields, whether recipe extraction is on, whether atomic splitting is on, and whether direct line-role labeling is on.

Work:

1. Edit `cookimport/config/run_settings.py` to add two new settings with conservative defaults:

     line_role_pipeline: Literal["off", "deterministic-v1", "codex-line-role-v1"] = "off"
     atomic_block_splitter: Literal["off", "atomic-v1"] = "off"

   Do not remove or rename `llm_recipe_pipeline`. It remains responsible for the existing recipe extraction passes.

2. Update the CLI in `cookimport/cli.py` so every command that can produce benchmark or prediction artifacts accepts and threads through the new flags. At minimum:

   - `labelstudio-benchmark`
   - `labelstudio-eval` when predictions are being generated locally
   - any relevant `bench run` command

3. Find the code that writes `run_manifest.json`, `need_to_know_summary.json`, and `comparison_summary.json`. If those writers are still embedded in `cookimport/cli.py`, extract them into small modules under `cookimport/runs/` or `cookimport/bench/` before adding fields.

   The summaries must always report all three knobs separately:

   - `llm_recipe_pipeline`
   - `atomic_block_splitter`
   - `line_role_pipeline`

4. Add a small regression test under `tests/bench/` or `tests/labelstudio/` that constructs paired run summaries and verifies that a run with recipe extraction on but line-role labeling off does not claim to be a canonical labeler. Add the new test file to the appropriate marker mapping in `tests/conftest.py`.

This milestone is complete when a benchmark summary can distinguish "CodexFarm extracted recipes" from "CodexFarm labeled canonical lines".

### Milestone 2 - Atomize mixed source blocks into benchmark-sized lines

At the end of this milestone, the system will have a deterministic pre-splitter that converts merged EPUB or text blocks into line-like units that map cleanly to the benchmark taxonomy.

Work:

1. Create `cookimport/parsing/recipe_block_atomizer.py`. Define a serializable model named `AtomicLineCandidate` with enough information to explain and replay every split:

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

2. Use deterministic boundary rules first. Reuse existing ingredient/yield heuristics where available instead of re-inventing them. Add explicit split rules for the cases already seen in the bundles:

   - `NOTE:` or `NOTE :` starts a note line
   - `MAKES`, `SERVES`, `YIELDS`, and similar prefixes start a yield line
   - numbered step prefixes such as `1.` start instruction lines
   - uppercase headings such as `TO MAKE HOLLANDAISE...`, `FOR THE JUNIPER VINEGAR`, `FOR SERVING`, and similar headings become their own atomic lines
   - quantity-first ingredient patterns (`3 tablespoons`, `1/2 cup`, `4 large eggs`) and range patterns (`4 to 6 chicken leg quarters`) become ingredient lines, not yield lines
   - variant headers in all caps or title case under an existing recipe title become standalone variant candidates

3. Create fixture files under `tests/fixtures/canonical_labeling/` that mirror the failure cases. At minimum include:

   - `hollandaise_merged_block.json`
   - `omelet_variant_lines.json`
   - `braised_chicken_tail_steps.json`
   - `ingredient_vs_yield_ranges.json`

4. Add unit tests in `tests/parsing/test_recipe_block_atomizer.py` (and update marker mapping if needed). The most important acceptance test is that the hollandaise merged block atomizes into separate candidates for the note line, the yield line, each ingredient line, and the method heading. Another acceptance test must prove that a quantity range like `4 to 6 chicken leg quarters` is never emitted as yield merely because it starts with a number.

This milestone is complete when the atomizer turns the known broken examples into atomic candidates that a human would consider labelable without hidden context.

### Milestone 3 - Add a deterministic-first canonical line-role pipeline with optional Codex fallback

At the end of this milestone, the system will assign benchmark labels directly to atomic lines, using rules first and Codex only for the ambiguous remainder.

Work:

1. Create `cookimport/parsing/canonical_line_roles.py`. Define a serializable prediction model:

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

2. Implement the rule engine first. The rule engine must make all low-ambiguity decisions without LLM calls. Required rules:

   - `NOTE:` lines inside recipe spans become `RECIPE_NOTES`
   - yield-prefixed lines become `YIELD_LINE`
   - quantity-first or quantity-range lines with ingredient vocabulary become `INGREDIENT_LINE`
   - numbered steps and imperative cooking sentences become `INSTRUCTION_LINE` unless they are standalone time metadata
   - `TIME_LINE` is reserved for lines whose primary role is time metadata, not any instruction sentence that merely mentions time
   - variant headers become `RECIPE_VARIANT`
   - method headings such as `TO MAKE...`, `FOR SERVING`, `FOR THE ...` become `HOWTO_SECTION` (if that label is in the gold taxonomy; otherwise map to the agreed header label)
   - inside active recipe spans, `KNOWLEDGE` is forbidden unless the candidate is explicitly marked as prose by the atomizer and both neighbors reinforce that reading

3. Extract shared Codex invocation helpers.

   Extract the existing `codex exec -` invocation code from `cookimport/labelstudio/prelabel.py` into `cookimport/llm/codex_exec.py`. Do not duplicate shelling logic in multiple places.

4. Add a structured prompt builder for ambiguous lines only.

   Create `cookimport/llm/canonical_line_role_prompt.py` with a structured prompt builder. The prompt input must include the previous line, the current line, the next line, whether the line is inside a recipe span, and an explicit `candidate_labels` allowlist. The prompt output must be strict JSON and must never attempt schema.org recipe extraction.

   Prompt requirements to embed directly in the prompt text (not just code comments):

   - explicitly enumerate the allowed label set
   - provide a precedence order for tie-breaking, for example:

       RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION > INGREDIENT_LINE > INSTRUCTION_LINE > TIME_LINE > RECIPE_NOTES > KNOWLEDGE > OTHER

   - include negative rules (must-not-do), especially:
     - never label a quantity/unit ingredient line as `KNOWLEDGE`
     - never label an imperative instruction sentence as `KNOWLEDGE`
     - inside recipe spans, `KNOWLEDGE` is a last resort
   - include 6-10 short synthetic few-shot examples matching the known failure modes:
     - `FOR THE MALT COOKIES` -> HOWTO_SECTION
     - `Grapeseed oil` under ingredient context -> INGREDIENT_LINE
     - `SERVES 4` -> YIELD_LINE
     - a 2-3 sentence procedural step -> INSTRUCTION_LINE
     - `NOTE: Cooled hollandaise...` -> RECIPE_NOTES
     - a narrative paragraph outside recipe spans -> KNOWLEDGE (only when allowed by your repo definitions)
   - provide local context: at least previous and next line text
   - use bounded batching (stable ordering, stable formatting); prefer 30-60 target candidates per call

5. Strict output parsing and fallback behavior.

   Validate that every returned label is in the allowlist and that every requested candidate appears exactly once. If the model returns invalid JSON, missing indices, or unknown labels:

   - write the raw response to the prompt log artifacts
   - fall back to deterministic labeling for the affected candidates (or `OTHER` if deterministic is undefined)
   - record a visible parse error count/flag in the run artifacts so it cannot be missed

6. Orchestration order must be:

   1. Atomize.
   2. Run deterministic rules.
   3. Send only unresolved/low-confidence candidates to Codex.
   4. Merge results and record `decided_by`.
   5. Apply a final sanitizer that rejects impossible label combinations, especially `KNOWLEDGE` inside recipe spans and `YIELD_LINE` for obvious ingredients.

7. Prompt logging as a first-class artifact.

   Whenever Codex is called, write prompt artifacts under the run root in a deterministic location. For each call, write:

   - `prompt_<N>.txt`
   - `response_<N>.txt`
   - `parsed_<N>.json`

   Also maintain an append-only compact log (for cutdowns) such as `codex_prompt_log.dedup.txt` keyed by a stable hash.

8. Add tests in `tests/parsing/test_canonical_line_roles.py` covering the observed failures directly (and update marker mapping if needed). Required cases include:

   - `NOTE: Cooled hollandaise...` becomes `RECIPE_NOTES`
   - `TO MAKE HOLLANDAISE IN A STANDARD BLENDER OR FOOD PROCESSOR` does not become `KNOWLEDGE`
   - `DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET` becomes `RECIPE_VARIANT`
   - `3 tablespoons whole milk` becomes `INGREDIENT_LINE`, not `YIELD_LINE`
   - `5. Add the heavy cream... about 1 minute...` remains `INSTRUCTION_LINE`, not `TIME_LINE`
   - a knowledge prose paragraph outside the recipe span can still become `KNOWLEDGE`

   LLM calls must be mocked/stubbed so tests are stable offline.

This milestone is complete when the fixture suite proves that the previously discussed failure modes are impossible or strongly disfavored in the new pipeline.

### Milestone 4 - Project atomic line roles into benchmark spans and optionally build drafts from the same labels

At the end of this milestone, the benchmark path and the optional staging path will both consume the same line-role predictions.

Work:

1. Create `cookimport/labelstudio/canonical_line_projection.py` if no equivalent module already exists. Define:

     def project_line_roles_to_freeform_spans(predictions: Sequence[CanonicalLineRolePrediction]) -> list[FreeformSpanPrediction]:
         ...

   This projection must preserve stable `line_index`, `block_id`, and `atomic_index` metadata so downstream artifacts can be joined back to the original source and to each other.

2. Wire the benchmark command so that when `line_role_pipeline != "off"`, predictions are generated from atomic line roles instead of from recipe-object extraction side effects. Keep the old path available while the new path is under evaluation, but make the new artifacts unmistakable by writing them under a subdirectory such as `line-role-pipeline/` inside the run root.

3. Update `cookimport/staging/draft_v1.py` so it can optionally build recipe fields from labeled atomic lines. This must be an opt-in path controlled by the same run settings. The draft builder should consume labels in this order:

   - `RECIPE_TITLE` and `RECIPE_VARIANT` for names and variants
   - `RECIPE_NOTES` for note capture
   - `YIELD_LINE` for `recipeYield`
   - `INGREDIENT_LINE` for `recipeIngredient`
   - `INSTRUCTION_LINE` and `HOWTO_SECTION` for `recipeInstructions` and subsection organization

   Do not remove the existing pass1-pass3 recipe-object extraction yet. Keep it as a parallel path until benchmark and draft outputs prove the atomic line-role path is better.

4. Add an integration test that runs a tiny synthetic source through the full path and verifies that benchmark spans and draft fields agree on ingredients, notes, and instructions. Place the test under the appropriate domain folder and update marker mapping.

This milestone is complete when one run can generate both benchmark predictions and recipe draft fields from the same labeled atomic lines.

### Milestone 5 - Add diagnostics, stabilize cutdown exports, and install regression gates

At the end of this milestone, you will be able to explain benchmark deltas instead of guessing.

Work:

1. Create or update benchmark analysis modules under `cookimport/bench/`. If there is no natural existing home, create:

   - `cookimport/bench/pairwise_flips.py`
   - `cookimport/bench/slice_metrics.py`
   - `cookimport/bench/cutdown_export.py`

2. The run directory for any benchmark executed with `line_role_pipeline != "off"` must emit at least these artifacts:

   - `line_role_predictions.jsonl`: one row per atomic line prediction
   - `line_role_flips_vs_baseline.jsonl`: only the lines where baseline and Codex disagree, joined with gold label when present
   - `slice_metrics.json`: metrics for at least `outside_recipe`, `recipe_titles_and_variants`, `recipe_notes_and_yield`, `recipe_ingredients`, and `recipe_instructions`
   - `knowledge_budget.json`: counts of `KNOWLEDGE` predictions inside and outside recipe spans
   - `prompt_eval_alignment.md`: a human-readable explanation of which prompt family produced which artifact family
   - stable cutdown samples where every sampled row is keyed from one joined line table (the same `sample_id` must be used across all sampled files)

3. Add tests in `tests/bench/test_cutdown_export_consistency.py` that prove the same sampled line has the same identifiers and text across `wrong_label_lines`, `correct_label_lines`, `aligned_prediction_blocks`, and any new flip reports. Update marker mapping as required.

4. Add metric gates to the benchmark runner (or an explicit "gated" mode). The implementation must fail the gated run if all of these are not true on `thefoodlabCUTDOWN`:

   - `macro_f1_excluding_other` improves by at least `0.05` over the current vanilla baseline
   - `overall_line_accuracy` improves by at least `0.05` over the current vanilla baseline
   - `INGREDIENT_LINE -> YIELD_LINE` confusion count drops by at least `40%` from the current CodexFarm baseline
   - `OTHER -> KNOWLEDGE` confusion count drops by at least `30%` from the current CodexFarm baseline
   - `RECIPE_NOTES` recall exceeds `0.40`
   - `RECIPE_VARIANT` recall exceeds `0.40`
   - `INGREDIENT_LINE` recall exceeds `0.35`

   If `SeaAndSmokeCUTDOWN` exists locally, add a second gate: the new line-role pipeline must not perform worse than vanilla on macro F1 or overall line accuracy there.

5. Update documentation so the new knobs and artifacts are discoverable:

   - `docs/04-parsing/04-parsing_readme.md`
   - `docs/06-label-studio/06-label-studio_README.md`
   - `docs/07-bench/07-bench_README.md`

This milestone is complete when the benchmark can both prove improvement and explain improvement.

## Concrete Steps

Work from the repository root.

1. Reproduce the evaluation issue and land Milestone 0.

     python -m pytest tests/labelstudio -k eval_metrics

2. Add the new run settings and CLI flags (Milestone 1).

     python -m pytest tests/bench -k run_config

3. Add the atomizer models, fixtures, and tests (Milestone 2).

     python -m pytest tests/parsing/test_recipe_block_atomizer.py

4. Add the line-role rules, shared Codex helper, prompt builder, and tests (Milestone 3).

     python -m pytest tests/parsing/test_canonical_line_roles.py

5. Wire the benchmark projection path and the optional draft builder path (Milestone 4).

     python -m pytest tests/labelstudio tests/staging tests/bench -k line_role

6. Add diagnostics, stable cutdown sampling, and gates (Milestone 5).

     python -m pytest tests/bench/test_cutdown_export_consistency.py

7. Run the benchmark locally on the provided book.

     cookimport labelstudio-benchmark \
       --source data/input/thefoodlabCUTDOWN.epub \
       --gold-export-dir data/golden/pulled-from-labelstudio/thefoodlabcutdown/exports \
       --llm-recipe-pipeline codex-farm-3pass-v1 \
       --atomic-block-splitter atomic-v1 \
       --line-role-pipeline codex-line-role-v1

   Expected observable output should include the run directory and new artifact names, for example:

     Wrote benchmark run to data/golden/benchmark-vs-golden/2026-03-03_.../
     Wrote line_role_predictions.jsonl
     Wrote slice_metrics.json
     Wrote line_role_flips_vs_baseline.jsonl

8. If `SeaAndSmokeCUTDOWN` is available locally, run the same command with that source and its matching gold export directory.

9. Run the full test suite once at the end.

     python -m pytest

   Because the repo currently has known baseline failures unrelated to this work, success means: all new and modified tests pass, and the total failure count is no worse than the baseline recorded in `AI_Context.md` unless you choose to fix those unrelated failures in the same branch.

## Validation and Acceptance

The feature is accepted only when all of the following are true.

Evaluation correctness:

- When gold/pred contain `HOWTO_SECTION`, per-label metrics show non-zero totals for `HOWTO_SECTION`.
- Confusion matrices include HOWTO_SECTION rows/cols (or the equivalent representation includes it).
- The Milestone 0 regression test passes.

Architecture honesty:

- A human can point the benchmark command at `thefoodlabCUTDOWN` and see that the run config separately reports recipe extraction, atomic splitting, and canonical line-role labeling.

Atomization works:

- The hollandaise merged-block fixture no longer reaches the classifier as one opaque line. Yield text, ingredient lines, and method headings appear as separate atomic candidates.

Line-role failures are fixed:

- `NOTE: Cooled hollandaise...` is no longer `OTHER`.
- `TO MAKE HOLLANDAISE...` is no longer `KNOWLEDGE`.
- `DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET` is no longer `KNOWLEDGE`.
- `3 tablespoons whole milk` is no longer `YIELD_LINE`.
- `5. Add the heavy cream...` is no longer `TIME_LINE`.

Diagnostics exist and are consistent:

- The run directory contains the new diagnostics.
- Cutdown exports are internally consistent (same `sample_id`/text across sampled files), proven by tests.

Benchmark quality gates pass:

- The metric gates in Milestone 5 pass on `thefoodlabCUTDOWN`.
- If `SeaAndSmokeCUTDOWN` exists locally, the non-regression gate passes there too.

Optional draft builder alignment:

- When enabled, draft fields align with the same labeled atomic lines used for benchmark predictions.

## Idempotence and Recovery

All new settings must default to `off`, keeping existing behavior unchanged until deliberately enabled.

Benchmark runs are timestamped under `data/golden/benchmark-vs-golden/`, so rerunning commands is safe. Never overwrite old run roots except for explicitly generated cutdown samples inside one run.

If the new line-role path misbehaves during development, disable it by setting `--line-role-pipeline off --atomic-block-splitter off`. The existing recipe extraction path must remain runnable throughout the migration.

If an LLM response is unparseable, the pipeline must not crash the run. It should log the raw response, fall back to deterministic labels for that batch, and mark the run artifacts with a visible parse error count.

## Artifacts and Notes

Use these short examples to anchor implementation details.

Example atomicization target for the hollandaise case:

    input block text:
      MAKES ABOUT 1 CUP 3 large egg yolks 1 tablespoon lemon juice ... Kosher salt TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER

    desired atomic candidates, in order:
      ABOUT 1 CUP                      -> YIELD_LINE candidate
      3 large egg yolks               -> INGREDIENT_LINE candidate
      1 tablespoon lemon juice...     -> INGREDIENT_LINE candidate
      ...
      Kosher salt                     -> INGREDIENT_LINE candidate
      TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER -> HOWTO_SECTION candidate

Expected new artifacts per benchmark run (adapt to repo conventions):

- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/line_role_predictions.jsonl`
- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/line_role_flips_vs_baseline.jsonl`
- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/slice_metrics.json`
- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/knowledge_budget.json`
- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/prompts/prompt_0001.txt`
- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/prompts/response_0001.txt`
- `data/golden/benchmark-vs-golden/<timestamp>/line-role-pipeline/prompts/parsed_0001.json`
- `data/golden/benchmark-vs-golden/<timestamp>/eval_report.md`

Before/after excerpt to paste here after running the real benchmark(s):

- overall line accuracy
- macro F1 (excluding OTHER)
- INSTRUCTION_LINE recall (and key confusions)
- KNOWLEDGE pred_total vs gold_total
- HOWTO_SECTION gold_total and pred_total (should be non-zero when present)

## Interfaces and Dependencies

Use Pydantic v2 models for new serialized artifact shapes, Typer for CLI wiring, and existing repo helpers where possible. Avoid adding new heavy dependencies for this iteration.

In `cookimport/config/run_settings.py`, add the settings exactly as described and thread them through any manifest/hash logic so benchmark comparison can see them.

In `cookimport/llm/codex_exec.py`, extract a shared helper from the current prelabel implementation:

    def run_codex_json_prompt(*, prompt: str, timeout_seconds: int, log_path: Path | None = None) -> dict[str, Any]:
        ...

Store prompt text in version-controlled template files (for example `cookimport/llm/prompts/codex_line_role_v1.txt`) so changes are reviewable and tied to a pipeline version.

## Plan change note

(2026-03-03) Merged `docs/plans/PRO-PROMPT.md` and `docs/plans/PRO-PROMPT2.md` into one plan. The merged plan keeps: evaluation label-accounting fixes + regression tests; separate `line_role_pipeline`/`atomic_block_splitter` knobs (instead of overloading recipe extraction); deterministic atomization; deterministic-first line-role labeling with Codex fallback; strict parsing + prompt logging; and benchmark diagnostics/gates. The duplicate plan file was deleted.

(2026-03-02 23:30 America/Toronto) Updated plan after implementation progress: Milestone 0 and Milestone 1 are completed, canonical HOWTO accounting behavior is clarified (stage/freeform remap vs canonical explicit scoring), and docs/manifests/cutdown summaries now include `atomic_block_splitter` + `line_role_pipeline` as first-class run knobs.

(2026-03-02 23:38 America/Toronto) Updated plan after Milestone 2 implementation: added deterministic `recipe_block_atomizer` runtime + fixtures/tests and updated parsing docs/understandings with the boundary-first split-order contract.
