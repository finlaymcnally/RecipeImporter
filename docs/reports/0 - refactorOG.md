---
summary: "Historical refactor spec for cookbook importer pipeline v2."
read_when:
  - DO NOT READ
---

# Refactor Spec: Cookbook Importer Pipeline v2

## Plain-English Pipeline

If you want the current Codex-backed flow in operator language instead of artifact language, this is the simplest accurate version:

1. The program parses the cookbook into one ordered set of atomic lines and other deterministic intermediate structures.
2. The program makes a deterministic first pass over those lines before any Codex-backed review.
3. The line-role Codex surface reviews the whole book line set in one file-backed labeling pass. Operator-wise this is just "label the lines."
4. The program groups the corrected recipe-side lines into coherent recipe spans and recipes. Everything not grouped into recipe spans becomes the non-recipe side.
5. The recipe Codex surface reviews the recipe side in owned recipe shards. It returns corrected recipe payloads plus ingredient-step mapping and raw selected tags.
6. The program deterministically validates and promotes those recipe outputs into the final recipe formats.
7. The knowledge Codex surface reviews the non-recipe side. It does not blindly process every leftover line as raw text; the program first builds eligible non-recipe chunks and skips obvious low-signal noise. Codex then keeps/refines useful cooking knowledge while rejecting blurbs, filler, and other author yapping.
8. The program validates owned output coverage, writes artifacts/reports, and emits the final recipe, knowledge, and debug outputs.

Worker/shard mental model:

- A setting such as `5 / 5 / 5` means the runtime aims for about five owned shards/workers for each enabled surface (`line_role`, `recipe`, `knowledge`), not that five agents free-edit shared files in place.
- The durable contract is "immutable input payload in, structured owned output/proposal out." The runtime then validates exact ownership/coverage and promotes only valid results.
- Recipe tags are part of the recipe correction surface, not a fourth independent Codex phase.
- Freeform prelabel is separate again; it is not part of the recipe/line-role/knowledge trio above.

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
The LLM is **not** just a last-resort bandaid.

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

---

## Stage 2 — Labeling (Deterministic First, LLM Correction Second)

### Goal
Assign semantic labels to every block/line.

### Input
Segmented blocks.

### Output
For each block:
- deterministic label
- LLM-corrected label
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

### Core Principle
This is where raw labeled evidence becomes a coherent recipe representation.

### LLM Role
None in the deterministic builder itself.

### Notes
This stage should do the best possible deterministic job before asking the LLM to help.

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

---

## Non-Recipe Route and Finalization — Non-Recipe Handling / Knowledge Pipeline

### Goal
Handle all non-recipe text cleanly.

### Input
Final corrected labels from Stage 2, plus grouped recipe spans from Stage 3.

### Output
At minimum:
- non-recipe blocks
- knowledge spans
- other spans

Optional:
- extracted reusable knowledge snippets
- tags / metadata
- embeddings-ready records later

### Core Principle
Most `knowledge` vs `other` separation should already be solved by Stage 2 labeling.

### Recommendation
Treat knowledge extraction as **downstream of good labeling**, not as a giant separate whole-book mining task.

### Suggested Design
#### Non-Recipe Route — Classification
Use Stage 2 labels to separate:
- `knowledge`
- `other`

#### Non-Recipe Finalization — Optional extraction/tagging
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
- `label_deterministic`
- `label_refine`
- `recipe_boundary`
- `recipe_build_intermediate`
- `recipe_refine`
- `recipe_build_final`
- `nonrecipe_route`
- `nonrecipe_finalize`
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
