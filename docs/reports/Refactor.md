# Refactor Spec: Cookbook Importer Pipeline v2

## Purpose

Refactor the cookbook importer into a pipeline with **clear stage boundaries**, **deterministic-first outputs**, and **LLM correction at every important stage**.

The new design should be:

- easy to reason about
- easy to debug
- cheap enough to run at scale
- accurate enough to approach hand-curated quality
- observable enough that every failure can be traced to a specific stage

---

## Core Design Decisions

### 1) Labeling is the primary source of truth
All later grouping and parsing should flow from labels.

That means:

- do **not** make recipe candidates the primary architecture
- do **not** rely on fuzzy "recipe-ish bundle" logic as the main driver
- do use deterministic + LLM-corrected labeling as the canonical foundation

### 2) LLM participates throughout the pipeline
The intended pattern is:

- deterministic stage produces a first draft
- LLM reviews/corrects that draft
- deterministic validation/writer finalizes the result

This pattern should appear at every high-value stage.

### 3) Intermediate and final recipe outputs should be treated as two artifacts, not necessarily two full reasoning stages
Recommendation:

Use **one main LLM recipe-correction call per recipe span** that outputs:

1. a corrected **intermediate recipe object**
2. a **linkage payload** describing ingredient-to-step pairings / final-format deltas

Then build the final recipe object **deterministically** from those two outputs.

This preserves:

- debuggability of the intermediate object
- low token cost
- minimal duplicate LLM work

---

## High-Level Target Flow

1. Extract text and preserve source structure when possible.
2. Split text into normalized blocks/lines.
3. Label all blocks/lines.
   - deterministic first
   - LLM correction second
4. Group labeled recipe blocks into recipe spans.
   - deterministic
5. Build an intermediate recipe object from each recipe span.
   - deterministic first
   - LLM correction second
6. Build the final step-linked recipe object.
   - deterministic from corrected intermediate object + linkage payload
7. Handle non-recipe text.
   - labels should already distinguish `knowledge` vs `other`
   - optional later LLM extraction/tagging for knowledge spans only
8. Write outputs and emit debug artifacts.

---

## What This Refactor Is Trying to Fix

The current implementation appears to have drifted into something like:

- early heuristic recipe candidate creation
- line-role labeling as a separate concern
- an LLM boundary-refinement pass
- a combined recipe-conversion pass that reporting still treats as multiple passes
- a separate knowledge-mining pass over non-recipe chunks
- stale/inaccurate observability around stage naming and behavior

The refactor should replace that with a much cleaner architecture:

**label first -> group second -> parse third -> correct fourth -> write last**

---

# Stage-by-Stage Spec

---

## Stage 0 — Ingest & Structure Preservation

### Goal
Turn an input cookbook file into a normalized source representation while preserving useful native structure where available.

### Input
- EPUB
- PDF
- HTML
- DOCX
- TXT
- structured webpage / export
- any future supported source

### Output
A normalized source document representation with:
- raw text
- source sections/pages/spine references
- native structural hints if present
- provenance metadata

### Requirements
- If the source already contains useful structure, preserve it.
- Do **not** flatten structured recipe data unless necessary.
- Treat flattening as a fallback, not the ideal path.

### Examples of structure to preserve when available
- HTML headings
- list items
- tables
- recipe cards
- JSON-LD / schema markup
- semantic containers
- obvious ingredient/instruction grouping from source markup

### LLM Role
None.

### Notes
This stage should be purely extraction/normalization.

### Current code that already does this or something close
- Importer selection and conversion already live in `cookimport/plugins/registry.py` plus the importer modules under `cookimport/plugins/`.
- EPUB and PDF are the closest match to this stage today. They extract ordered block streams, preserve layout-ish metadata, and write raw `full_text` artifacts that downstream code can trace back to.
- EPUB structure preservation already has good seams in `cookimport/parsing/epub_extractors.py`, `cookimport/parsing/unstructured_adapter.py`, `cookimport/parsing/epub_html_normalize.py`, and `cookimport/parsing/epub_postprocess.py`. Those modules preserve spine/page-ish context, semantic element categories, tables, and some HTML structure hints.
- Web/schema sources already preserve native structured recipe data instead of flattening immediately through `cookimport/plugins/webschema.py` and `cookimport/parsing/schemaorg_ingest.py`.
- Structured importers such as `cookimport/plugins/paprika.py` and `cookimport/plugins/recipesage.py` already behave like “structure-preserved” sources because they map structured exports directly into `RecipeCandidate`.
- Raw artifact persistence in `cookimport/staging/writer.py` and the current `ConversionResult.raw_artifacts` contract already give this stage somewhere to store normalized source payloads.

### Greenfield or substantial refactor needed
- There is no single shared “normalized source document” model that every importer returns before recipe detection starts. Most importers still jump straight from extraction into `RecipeCandidate` / `non_recipe_blocks`.
- The current architecture does not make Stage 0 a first-class artifact boundary. To match this plan, we will need one common source-document contract that can hold raw text, ordered units, structural hints, and provenance across all importer families.
- Text, Excel, Paprika, and RecipeSage flows do not currently converge through one block-first normalization layer, so making this stage universal will require new shared plumbing rather than only small edits.

---

## Stage 1 — Block / Line Segmentation

### Goal
Convert the normalized source into stable text units that later stages can label.

### Input
Normalized source document.

### Output
A sequence of blocks/lines with:
- stable block IDs
- text
- source provenance
- page/spine/section metadata
- optional structural hints
- ordering information

### Requirements
- Blocks must be stable and traceable.
- Every downstream artifact must be able to point back to these original block IDs.
- Segmentation should favor meaningful human-readable units, not arbitrary token chunks.

### LLM Role
None.

### Notes
This is the canonical evidence layer. Everything downstream should be traceable back to these blocks.

### Current code that already does this or something close
- EPUB/PDF already produce ordered block-like evidence and preserve indices that later code uses for provenance and split-job rebasing.
- `cookimport/parsing/unstructured_adapter.py` already splits multiline HTML elements into more stable recipe-like units while preserving provenance details such as stable keys and split reasons.
- `cookimport/parsing/recipe_block_atomizer.py` is a useful existing seam for turning larger blocks into smaller human-readable line units with stable `atomic_index`, `block_id`, `block_index`, and neighborhood context.
- Raw `full_text.json` artifacts and split-merge rebasing in `cookimport/cli.py` and `cookimport/staging/pdf_jobs.py` already enforce the idea that downstream stages should be able to point back to a stable ordered block stream.

### Greenfield or substantial refactor needed
- There is no single canonical Stage 1 artifact produced for every importer. Some flows are block-first, some are recipe-record-first, and some are already structured objects.
- Stable block IDs are not yet a repo-wide source-of-truth contract. A lot of current code relies on indices or importer-specific provenance rather than one shared block identity model.
- To make this the true evidence layer, we will need a universal segmented-block artifact that all downstream recipe, knowledge, and debug flows consume instead of importer-specific shapes.

---

## Stage 2 — Labeling (Deterministic First, LLM Correction Second)

### Goal
Assign semantic labels to every block/line.

### Input
Segmented blocks.

### Output
For each block:
- deterministic label
- LLM-corrected label (only if LLM decides to make a change, if it doesn't want a label changed it does not output anything related to that block to save output tokens)
- optional confidence / uncertainty flags
- optional reason codes
- provenance to original block ID

### Core Principle
This is the **source-of-truth stage** for what each block is.

### Example label taxonomy
Recipe-related:
- `recipe_title`
- `yield_line`
- `ingredient_line`
- `instruction_line`
- `recipe_note`
- `recipe_variant`
- `time_line`
- `section_heading`

Non-recipe:
- `knowledge`
- `other`

Possible future subtypes:
- `boilerplate`
- `toc`
- `front_matter`
- `endorsement`
- `navigation`
- `chapter_heading`

### Deterministic Pass
Use rules, parsers, formatting cues, lexical cues, and layout hints to produce initial labels.

### LLM Correction Pass
The LLM reviews the deterministic labels and corrects them.

#### Recommended LLM input
- a local neighborhood of blocks
- deterministic labels
- structural metadata
- uncertainty markers
- optional rule outputs / parser warnings

#### Recommended LLM output
A patch-like response:
- corrected labels
- optional notes on why a correction was made
- confidence / uncertainty markers

### Important Design Rule
The LLM should correct labeling, not rediscover the whole book from scratch.

### Token Policy
Prefer local review windows, not whole-book prompts.

Good:
- review 10–40 nearby blocks with current labels

Bad:
- give the model huge amounts of surrounding book text with no label-first framing

### Validation
- every block must end with exactly one final label
- label diffs between deterministic and corrected versions must be inspectable
- uncertainty should be surfaced, not hidden

### Current code that already does this or something close
- Deterministic line-role labeling already exists in `cookimport/parsing/canonical_line_roles.py` and the candidate-prep layer in `cookimport/parsing/recipe_block_atomizer.py`.
- The current label taxonomy is already close to the plan for recipe-local labels: `RECIPE_TITLE`, `RECIPE_VARIANT`, `YIELD_LINE`, `TIME_LINE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `RECIPE_NOTES`, `HOWTO_SECTION`, `KNOWLEDGE`, and `OTHER`.
- Optional LLM correction already exists in the same module via the Codex-backed `codex-line-role-v1` path. It reviews deterministic candidates rather than rediscovering the whole book from scratch.
- `CanonicalLineRolePrediction` already carries a final label, confidence, decision source (`rule` / `codex` / `fallback`), and reason tags.
- Label projection and artifact writing already exist in `cookimport/labelstudio/canonical_line_projection.py`.
- After the stage-backed benchmark unification, canonical line-role now runs after the shared authoritative stage session and stays diagnostics-only instead of mutating the benchmark’s authoritative recipe outputs.

### Greenfield or substantial refactor needed
- This label pipeline is not the main runtime source of truth yet. It still lives mainly in the Label Studio / benchmark diagnostics lane (`cookimport/labelstudio/ingest.py`), and the primary stage/import path still groups recipes before this labeling layer exists.
- Current grouping and recipe extraction do not consume Stage 2 labels as the canonical foundation. They still depend mainly on heuristic candidate detection in importers.
- The repo does not yet emit the exact Stage 2 artifacts described here as a normal first-class run contract (`deterministic labels`, `corrected labels`, inspectable diffs).
- Some of the requested non-recipe subtype coverage (`boilerplate`, `toc`, `front_matter`, `endorsement`, `navigation`, `chapter_heading`) will need new rules and probably new prompt examples.

---

## Stage 3 — Recipe Span Grouping (Deterministic)

### Goal
Group labeled blocks into recipe spans.

### Input
Final corrected labels from Stage 2.

### Output
A list of recipe spans, each containing:
- recipe span ID
- ordered block IDs
- start/end block IDs
- optional title block ID
- optional notes/variant subspans
- any grouping warnings

### Core Principle
Once labeling is good, grouping should be deterministic.

### Grouping Rules
Recipe spans should be formed from labels, for example:
- start at `recipe_title`
- continue through expected recipe labels
- stop at the next `recipe_title` or strong non-recipe boundary
- allow notes/variants to remain attached if labeling says they belong

### LLM Role
None by default.

### Optional LLM Role
Only as a targeted fallback if deterministic grouping produces ambiguity that cannot be resolved from labels.

### Important Design Rule
Recipe grouping should no longer depend on pre-label heuristic recipe candidates as the main architecture.

### Current code that already does this or something close
- Recipe grouping exists today, but mostly as pre-label candidate detection inside importers:
  - EPUB/PDF: `_detect_candidates(...)`, `_apply_multi_recipe_splitter(...)`, and `_extract_fields(...)` in `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`
  - Text: `_split_recipes(...)` and related helpers in `cookimport/plugins/text.py`
- `cookimport/parsing/multi_recipe_splitter.py` is an existing reusable seam for deterministic multi-recipe splitting/refinement.
- `cookimport/labelstudio/ingest.py` already derives recipe ranges from recipe provenance to support the line-role pipeline, so there is some code that converts recipe ownership back into span form.
- `cookimport/llm/non_recipe_spans.py` and `cookimport/llm/codex_farm_knowledge_jobs.py` already work with explicit span objects and half-open span math.

### Greenfield or substantial refactor needed
- There is not yet a deterministic “group spans from labels” stage. Existing grouping starts from heuristic recipe candidates, then later code projects spans from those candidates.
- We will need a new grouping module that consumes final Stage 2 labels directly and emits recipe span objects as a first-class artifact.
- Variant/note attachment rules as part of label-driven grouping are not centralized today; they are spread across importer heuristics and later draft shaping.

---

## Stage 4 — Deterministic Intermediate Recipe Build

### Goal
Convert one grouped recipe span into an intermediate recipe object.

### Input
One recipe span with labeled blocks.

### Output
A deterministic intermediate recipe object.

### Intermediate Object Purpose
This is the main debug/validation artifact for recipe structure.

It should capture:
- title
- yield
- times
- ingredient lines / normalized ingredients
- instructions / steps
- notes
- variants
- provenance back to block IDs
- everything that the recipe structure calls for!

### Core Principle
This is where raw labeled evidence becomes a coherent recipe representation.

### LLM Role
None in the deterministic builder itself.

### Notes
This stage should do the best possible deterministic job before asking the LLM to help.

### Current code that already does this or something close
- The current repo already has a deterministic intermediate representation: `RecipeCandidate` in `cookimport/core/models.py`.
- Importer-specific field extraction into `RecipeCandidate` already exists in modules like `cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`, `cookimport/plugins/text.py`, and `cookimport/parsing/schemaorg_ingest.py`.
- Deterministic normalization/shaping on top of `RecipeCandidate` already exists in:
  - `cookimport/staging/jsonld.py` for intermediate schema.org-style recipe output
  - `cookimport/staging/draft_v1.py` for final cookbook3 output
  - parser helpers such as `ingredients.py`, `instruction_parser.py`, `yield_extraction.py`, `sections.py`, and `step_ingredients.py`
- The merged-repair Codex path already treats `recipe_candidate_to_draft_v1(...)` as a deterministic hint builder, which means this stage’s intended shape is already partially present.

### Greenfield or substantial refactor needed
- Current deterministic recipe building is tightly mixed with importer-specific candidate extraction. There is no standalone “take labeled span -> build intermediate object” module yet.
- Provenance back to block IDs is partial and uneven. Candidates have provenance, but the intermediate object is not yet explicitly a block-grounded audit artifact with field-level label evidence.
- Times, notes, variants, and normalized ingredient/instruction evidence are currently assembled across several modules; they are not yet centralized as one named Stage 4 artifact contract.

---

## Stage 5 — LLM Recipe Correction + Linkage Generation

### Goal
Review the deterministic intermediate recipe object and fix mistakes, while also producing the ingredient-step linkage data needed for the final output.

### Input
For one recipe span:
- original labeled blocks
- deterministic intermediate recipe object
- parser warnings / uncertainty signals
- block provenance
- schema/output contract

### Output
A structured LLM response containing:

#### A) Corrected intermediate recipe object
This should be the cleaned-up canonical recipe representation.

#### B) Linkage payload
A compact structure describing:
- which ingredients belong to which steps
- any cross-step ingredient reuse
- unresolved / ambiguous ingredient-step relationships
- optional linkage confidence flags

#### C) Validation / issue flags
For example:
- missing instruction details
- ambiguous ingredient references
- likely variant leakage
- suspicious title/yield/time parsing

### Why this design
The hard reasoning is mostly:
- interpreting the labeled recipe correctly
- cleaning up the intermediate object
- deciding ingredient-step relationships

The final recipe object is mostly a deterministic reshaping of that information.

So the LLM should do **one reasoning pass** and emit:
- corrected recipe structure
- linkage instructions

Then deterministic code should assemble the final object.

### Important Design Rule
Do **not** spend a separate heavy LLM call on "intermediate -> final" if the final step is mostly data reshuffling.

### Fallback Strategy
If needed, a second LLM call may exist as an exception path only when:
- validation fails badly
- linkage is too ambiguous
- deterministic final assembly cannot proceed

But this should be the exception, not the default architecture.

### Current code that already does this or something close
- The biggest overlap is `cookimport/llm/codex_farm_orchestrator.py`.
- The current 3-pass path already splits the work into:
  - pass1: boundary / chunking
  - pass2: schema.org-like corrected recipe output plus extracted evidence
  - pass3: final-draft output plus ingredient-step mapping
- The newer merged-repair path (`codex-farm-2stage-repair-v1`) is even closer to this stage. It already asks for one canonical corrected recipe plus `ingredient_step_mapping` and `ingredient_step_mapping_reason`.
- Transport audits, evidence normalization, structural audits, and issue flags already exist around this path, so the validation mindset is already present.
- `cookimport/staging/import_session.py` now centralizes the shared post-conversion stage session, so the recipe Codex path is no longer duplicated between normal stage runs and benchmark processed-output generation.

### Greenfield or substantial refactor needed
- The current LLM recipe pipeline is still anchored on heuristic recipe candidates and pass1 span refinement, not on Stage 2 labels + Stage 3 grouped spans.
- The default output contract is still split across pass2 schema.org and pass3 final-draft concepts. The plan wants one primary correction call that returns corrected intermediate data plus linkage data, with “final” assembly moved out of the LLM path.
- There is not yet a clean patch-oriented Stage 5 artifact named around “corrected intermediate object + linkage payload + issue flags” as the canonical repo contract.
- If we want Stage 5 to review labeled blocks directly, we will need new prompt/input builders that package label evidence rather than mostly relying on candidate text spans and current recipe hints.

---

## Stage 6 — Deterministic Final Recipe Assembly

### Goal
Build the final step-linked recipe object from:
- corrected intermediate recipe object
- linkage payload from Stage 5

### Input
- corrected intermediate recipe object
- linkage payload
- deterministic assembly rules

### Output
Final recipe object in app-specific format.

### Core Principle
This should be mostly deterministic.

### Responsibilities
- attach ingredients to relevant steps
- preserve unresolved ambiguities explicitly when needed
- avoid hallucinating missing structure
- produce a clean final representation for downstream use

### Important Design Rule
If the LLM already did the reasoning, this stage should be a reliable writer/assembler, not another interpretation stage.

### Current code that already does this or something close
- `cookimport/staging/draft_v1.py` is already the main deterministic final-shaping module.
- `cookimport/parsing/step_ingredients.py` already contains deterministic ingredient-to-step linking logic, and `recipe_candidate_to_draft_v1(...)` uses it during final shaping.
- The Codex recipe path already has deterministic fallback/finalization behavior, including `_build_pass3_deterministic_fallback_payload(...)` and the merged-repair helpers that derive schema.org / draft payloads from corrected canonical output.
- Writers in `cookimport/staging/writer.py` already treat intermediate and final artifacts as separate persisted outputs.

### Greenfield or substantial refactor needed
- Final assembly is not yet a pure “corrected intermediate + linkage payload -> final object” stage. Today the deterministic final builder still performs substantial parsing/inference itself.
- Ingredient-step attachment is currently driven by deterministic text matching over candidate data, not by a dedicated Stage 5 linkage payload.
- We will need a narrower assembler contract so Stage 6 becomes mostly a writer/reshaper instead of a second parsing stage.

---

## Stage 7 — Non-Recipe Handling / Knowledge Pipeline

### Goal
Handle all text that is not part of any recipe span.

### Input
- final corrected labels from Stage 2
- recipe spans from Stage 3, used only to exclude recipe-owned blocks

### Working set
All blocks not claimed by recipe spans.

### Output
- non-recipe spans
- knowledge spans
- other spans
- optional knowledge snippets / tags

### Core Principle
Most `knowledge` vs `other` separation should already be solved by Stage 2 labeling.

### Recommendation
Treat knowledge extraction as **downstream of good labeling**, not as a giant separate whole-book mining task.

### Suggested Design
#### Stage 7A — Classification
Use Stage 2 labels to separate:
- `knowledge`
- `other`

#### Stage 7B — Optional extraction/tagging
Only run a lightweight LLM pass on spans already labeled as `knowledge` if needed.

### Hard Rules
Do not run knowledge extraction on obvious noise such as:
- table of contents
- signup prompts
- legal boilerplate
- front matter
- endorsements
- navigation
- publisher marketing copy

### LLM Role
Optional, scoped, and label-driven.

### Notes
This stage may become much smaller once Stage 2 labeling is strong enough.

### Current code that already does this or something close
- Importers already preserve non-recipe text as `ConversionResult.non_recipe_blocks`.
- Deterministic downstream handling already exists in `cookimport/parsing/chunks.py`, `cookimport/parsing/tips.py`, and table extraction helpers used from `cookimport/cli_worker.py` / `cookimport/cli.py`.
- Optional LLM knowledge handling already exists in `cookimport/llm/codex_farm_knowledge_orchestrator.py` and `cookimport/llm/codex_farm_knowledge_jobs.py`.
- `cookimport/llm/non_recipe_spans.py` and the pass4 job builder already implement explicit recipe-vs-non-recipe span math.
- The line-role benchmark path already knows how to merge knowledge evidence back into line labels through `cookimport/labelstudio/canonical_line_projection.py`.
- Stage runs and benchmark processed-output generation now share the same post-conversion chunking / pass4 knowledge session through `cookimport/staging/import_session.py`, so this lane is less forked than before.

### Greenfield or substantial refactor needed
- Non-recipe handling is not yet primarily label-driven. Today it is mostly “whatever blocks were not absorbed into importer recipe candidates.”
- The clean Stage 7A split of `knowledge` vs `other` from Stage 2 labels does not exist yet as a core artifact boundary.
- Because Stage 2 is not yet primary, the current knowledge lane still inherits false positives / false negatives from candidate detection and non-recipe residue.
- Hard filtering of obvious noise categories will need stronger Stage 2 taxonomy support plus a small deterministic policy layer built specifically for Stage 7.

---

## Stage 8 — Writers, Exporters, and Debug Artifacts

### Goal
Write final outputs and preserve full traceability.

### Output Types
- final recipes
- intermediate recipes
- label outputs
- recipe spans
- non-recipe knowledge outputs
- debug reports
- validation reports

### Core Principle
Every final output should be explainable from upstream artifacts.

### Required Debuggability
For any final recipe, it should be easy to inspect:
- original blocks
- deterministic labels
- corrected labels
- grouped recipe span
- deterministic intermediate object
- corrected intermediate object
- linkage payload
- final assembled output

### Current code that already does this or something close
- Output writing is already centralized in `cookimport/staging/writer.py`.
- `cookimport/staging/import_session.py` now centralizes the authoritative post-conversion stage session used by normal stage runs, split-merge stage runs, and stage-backed benchmark processed-output generation.
- Run-level traceability already exists via `run_manifest.json` helpers in `cookimport/runs/manifest.py`.
- Stage and prediction runs already persist rich raw/debug artifacts:
  - raw source/full-text artifacts
  - intermediate schema.org outputs
  - final cookbook3 outputs
  - stage block predictions
  - knowledge artifacts
  - LLM raw pass inputs/outputs/manifests under `raw/llm/...`
  - Label Studio manifests and prompt logs in `cookimport/labelstudio/ingest.py`
- The current Codex recipe path already writes transport audits, evidence-normalization logs, merged-repair audits, and recipe guardrail artifacts.
- Benchmarking is now stage-backed: canonical benchmark scoring uses the authoritative stage evidence surface, while `prediction-run/line-role-pipeline/*` remains diagnostics-only.

### Greenfield or substantial refactor needed
- The benchmark/import bifurcation is smaller now, but the artifact contract is still organized around the current architecture, not the refactor’s desired stage names and boundaries.
- There is not yet one per-recipe debug packet that cleanly bundles every upstream artifact named in this plan.
- Stage 2 and Stage 3 artifacts do not yet exist as first-class runtime outputs in the main stage path, so Stage 8 cannot currently expose the full “label first -> group second -> parse third -> correct fourth -> write last” chain.

---

# Recommended Artifact Contract

Suggested artifacts per cookbook run:

- `00_source_normalized.json`
- `01_blocks.jsonl`
- `02_labels_deterministic.jsonl`
- `03_labels_corrected.jsonl`
- `04_recipe_spans.json`
- `05_intermediate_deterministic.json`
- `06_recipe_corrections_llm.json`
- `07_final_recipes.json`
- `08_nonrecipe_spans.json`
- `09_knowledge_outputs.json`
- `10_validation_report.json`
- `11_run_summary.json`

Optional per-recipe debug packet:
- `debug/<recipe_id>.json`

That per-recipe packet should include everything needed to audit one recipe end-to-end.

---

# Prompting Rules

## General Rule
Every LLM stage should be **patch-oriented and evidence-grounded**.

The model should never be asked to "just figure it all out" from scratch if deterministic code can present a structured first draft.

## Good Prompt Pattern
Provide:
- local evidence blocks
- deterministic first-pass output
- explicit schema / output contract
- clear correction task

Ask for:
- corrections
- structured diffs / patches
- confidence / ambiguity flags

## Bad Prompt Pattern
Provide:
- huge raw spans
- multiple unrelated objectives
- poorly separated responsibilities
- prompts that both classify, regroup, parse, and rewrite everything at once

---

# Validation Rules

## Labeling
- every block has exactly one final label
- label changes are diffable
- uncertainty is preserved

## Grouping
- every recipe span is contiguous and reproducible
- every grouped block points to final labels
- no unlabeled grouping logic should silently override labels

## Intermediate Recipe Object
- schema-valid
- provenance attached
- parser warnings preserved

## Final Recipe Object
- deterministically buildable from corrected intermediate + linkage payload
- unresolved ambiguity should be explicit, not hallucinated away

## Knowledge Outputs
- only derived from spans labeled `knowledge`
- never mined from obvious boilerplate/noise unless explicitly enabled for experimentation

---

# What to Remove / Simplify from Current Implementation

## Remove as primary architecture
- pre-label heuristic recipe candidates driving the whole flow

## Remove ambiguity
- stale pass naming / reporting that no longer matches actual behavior
- any observability layer that pretends one stage is two when they are now combined

## Remove redundant LLM work
- separate heavy reasoning calls for intermediate -> final reshuffling
- full-book knowledge mining when label-driven extraction would suffice

## Remove silent magic
- hidden overrides that make it hard to tell which stage actually changed the output
- stage outputs that are not persisted as inspectable artifacts

---

# Recommended Naming Scheme

Avoid generic `pass1`, `pass2`, `pass3`, `pass4` naming in the refactor.

Use names that describe job responsibility:

- `extract`
- `segment`
- `label_det`
- `label_llm_correct`
- `group_recipe_spans`
- `build_intermediate_det`
- `recipe_llm_correct_and_link`
- `build_final_recipe`
- `classify_nonrecipe`
- `extract_knowledge_optional`
- `write_outputs`

This alone will make the system far easier to understand.

---

# Failure / Fallback Policy

## If label correction fails
Keep deterministic labels and surface the failure clearly.

## If recipe grouping fails
Emit an explicit grouping warning and preserve candidate evidence.

## If recipe correction fails
Keep deterministic intermediate object and mark the recipe as uncorrected.

## If linkage is ambiguous
Allow unresolved linkage markers rather than inventing certainty.

## If final assembly fails
Preserve corrected intermediate object and linkage payload so the failure is isolated to the assembly stage.

---

# Recommended Migration Strategy

## Phase 1 — Fix observability first
Before changing too much logic:
- rename stages clearly
- emit real artifacts for each stage
- align reporting with actual implementation

## Phase 2 — Make labeling the source of truth
Refactor flow so grouping happens after labeling, not before.

## Phase 3 — Collapse recipe reasoning into one LLM correction stage
Implement:
- deterministic intermediate build
- single LLM correction + linkage output
- deterministic final assembly

## Phase 4 — Shrink knowledge pipeline
Move from broad knowledge mining toward:
- stronger early labels
- optional downstream knowledge extraction only on labeled knowledge spans

## Phase 5 — Optimize token usage
Once architecture is clean:
- reduce context windows
- focus prompts on local evidence
- run LLM correction only where it adds value
- preserve dev/debug mode vs cheaper production mode if needed

---

# Recommended Final Architecture (Short Version)

## Recipe Path
1. extract
2. segment
3. label deterministically
4. LLM-correct labels
5. deterministically group recipe spans
6. deterministically build intermediate recipe object
7. LLM-correct intermediate object + output linkage payload
8. deterministically build final recipe object
9. write outputs

## Non-Recipe Path
1. take all non-recipe blocks after labeling/grouping
2. classify as `knowledge` vs `other` from labels
3. optionally run lightweight LLM tagging/extraction on `knowledge` only
4. write outputs

---

# Final Recommendation on Intermediate vs Final

## Recommended default
Use **one LLM recipe reasoning call** that outputs:
- corrected intermediate recipe object
- linkage payload for final assembly

Then let deterministic code generate the final recipe object.

## Why
This gives you:
- a strong debugging artifact
- lower token cost
- less duplicated model work
- clear stage boundaries

## Caveat
If the final format later becomes meaningfully more semantic than "intermediate + pairings", revisit this decision.

But with the current design, one reasoning call + deterministic assembly is the better default.

---

# Acceptance Criteria

The refactor is successful when:

1. A human can explain the full pipeline in one page.
2. Every stage has one clear job.
3. Every stage has a stable input/output contract.
4. Labels drive grouping.
5. The LLM corrects deterministic outputs instead of replacing the whole architecture.
6. Intermediate recipe objects are preserved for debugging.
7. Final recipe objects are built deterministically from corrected structure.
8. Knowledge handling is label-driven and scoped.
9. Reporting matches actual implementation.
10. Any bad final output can be traced back to the exact stage that introduced the error.


Post refactor things to check (FM reminder)
uploadBundle , i tried to make it more flexible
PromptLogFolder , i tried to make it more flexible



## Confidence / Trust / Escalation Policy

### Problem
The current deterministic "confidence" score should not be treated as a reliable probability of correctness.

It appears to mix together multiple meanings, such as:
- weak rule match
- fallback routing
- true uncertainty
- disagreement between candidate labels

This makes the current score unsuitable as a primary control signal.

### Policy
The refactor should replace the single confidence score with two separate concepts:

#### 1) Trust score
Represents how likely a label or parsed output is correct.

Used for:
- debugging
- QA prioritization
- calibration measurement
- review ordering

#### 2) Escalation score
Represents how strongly an item should be sent to the LLM for correction.

Used for:
- selective LLM invocation
- context sizing
- prioritizing expensive correction passes

These two scores must not be treated as interchangeable.

### Required Per-Item Decision Metadata
Each block/recipe/span should carry structured decision metadata such as:
- `decided_by`
- `candidate_labels`
- `rule_hits`
- `parser_support`
- `neighbor_agreement`
- `source_structure_support`
- `trust_score`
- `escalation_score`
- `escalation_reasons`

### Important Rule
A single scalar confidence value must not be the primary source of truth for:
- grouping recipe spans
- final recipe acceptance
- knowledge extraction eligibility

Those decisions should instead rely on:
- final labels
- validation checks
- cross-stage consistency
- provenance-aware rules

### Escalation Heuristics
Escalation should be triggered by signals such as:
- fallback-decided labels
- disagreement between candidate labels
- disagreement between deterministic and LLM labels
- parser warnings
- structurally inconsistent recipe spans
- missing required recipe fields
- ambiguous ingredient-step linkage

### Calibration Requirement
Trust scores should be calibrated against a golden set and measured per label type.

Calibration reports should include:
- per-label precision/recall by score band
- reliability curves
- false-positive / false-negative patterns by score band

### Recommended Design Principle
Validation and consistency checks should matter more than raw confidence scores.

Confidence is a supporting signal.
It is not the architecture.