# Refactor Spec: Cookbook Importer Pipeline v2 (Shard-Agent Runtime)

## Purpose

Refactor the cookbook importer into a pipeline with clear stage boundaries, deterministic-first outputs, and bounded shard-agent correction at the important reasoning seams.

The new design should be:

- easy to reason about
- easy to debug
- cheap enough to run on real books
- accurate enough to approach hand-curated quality
- observable enough that every failure can be traced to a specific stage and shard

This document assumes the Codex-backed runtime is the shard-agent model described in `docs/plans/2026-03-16_21.26.21-replace-codex-prompts-with-shard-agents.md`. It is not a hybrid spec. The prompt-per-bundle CodexFarm pattern is not the target architecture here.

---

## Core Design Decisions

### 1) Labeling is the primary source of truth

All later grouping and parsing should flow from labels.

That means:

- do not make recipe candidates the primary architecture
- do not rely on fuzzy "recipe-ish bundle" logic as the main driver
- do use deterministic plus shard-agent-corrected labeling as the canonical foundation

### 2) Codex-backed reasoning happens through bounded shard agents

The model is not a final-resort bandaid and it is not a pile of unrelated one-shot calls.

The intended pattern is:

- deterministic stage produces a first draft
- shard planner assigns bounded local ownership
- shard agent reviews or corrects only its owned region
- deterministic validation or writer finalizes the result

This pattern should appear at every high-value reasoning seam.

### 3) Deterministic preparation and deterministic merge stay in charge

Shard agents should reason over local evidence, but deterministic code should still:

- build the first draft
- define stable IDs and ownership
- validate coverage
- merge final outputs
- preserve artifacts for debugging

This keeps the pipeline inspectable and restartable.

### 4) Intermediate and final recipe outputs are still two artifacts, but shard agents may own multiple nearby recipes

Recommendation:

Use one shard-agent recipe-correction pass per bounded local recipe shard. Each shard returns, for every owned `recipe_id`:

1. a corrected intermediate recipe object
2. a linkage payload describing ingredient-to-step pairings and final-format deltas

Then build the final recipe object deterministically from those outputs.

This preserves:

- debuggability of the intermediate object
- lower token cost through shared shard context
- minimal duplicate model work
- exact ownership over which shard changed which recipe

---

## High-Level Target Flow

1. Extract text and preserve source structure when possible.
2. Split text into normalized blocks or lines.
3. Label all blocks or lines.
   - deterministic first
   - shard-agent correction second
4. Group labeled recipe blocks into recipe spans.
   - deterministic
5. Build an intermediate recipe object from each recipe span.
   - deterministic first
6. Run shard-agent recipe correction over bounded neighboring recipe spans.
7. Build the final step-linked recipe object.
   - deterministic from corrected intermediate object plus linkage payload
8. Handle non-recipe text.
   - labels should already distinguish `knowledge` vs `other`
   - optional shard-agent refinement runs only on bounded knowledge regions
9. Write outputs, shard manifests, and debug artifacts.
10. Preview and benchmark the shard plan using shard counts, fresh-agent counts, and bounded cost estimates rather than old prompt counts.

---

## What This Refactor Is Trying to Fix

The current implementation drifted into a model that mixed:

- early heuristic recipe candidate creation
- line-role labeling as a separate concern
- one-shot Codex correction bundles
- recipe correction that repeated the same framing on every recipe
- a separate knowledge-mining surface over non-recipe chunks
- stale or misleading observability around stage names and work units

The refactor should replace that with a cleaner architecture:

**label first -> group second -> parse third -> shard-correct fourth -> write last**

The important runtime shift is:

**bounded shard ownership instead of one-shot prompt bundles**

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
- structured webpage or export
- any future supported source

### Output

A normalized source document representation with:

- raw text
- source sections, pages, or spine references
- native structural hints if present
- provenance metadata

### Requirements

- If the source already contains useful structure, preserve it.
- Do not flatten structured recipe data unless necessary.
- Treat flattening as a fallback, not the ideal path.

### Examples of structure to preserve when available

- HTML headings
- list items
- tables
- recipe cards
- JSON-LD or schema markup
- semantic containers
- obvious ingredient or instruction grouping from source markup

### LLM Role

None.

### Notes

This stage should be purely extraction and normalization.

---

## Stage 1 — Block / Line Segmentation

### Goal

Convert the normalized source into stable text units that later stages can label.

### Input

Normalized source document.

### Output

A sequence of blocks or lines with:

- stable block IDs
- text
- source provenance
- page, spine, or section metadata
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

## Stage 2 — Labeling (Deterministic First, Shard-Agent Correction Second)

### Goal

Assign semantic labels to every block or line.

### Input

Segmented blocks.

### Output

For each block:

- deterministic label
- final corrected label
- optional confidence or uncertainty flags
- optional reason codes
- provenance to original block ID
- shard ownership metadata when a shard agent reviewed it

### Core Principle

This is the source-of-truth stage for what each block is.

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

### Shard Planning

Plan bounded local shards over contiguous line or block neighborhoods.

Each shard should:

- own a non-overlapping local window
- have a stable `shard_id`
- define exactly which block IDs or atomic indexes it may change
- carry deterministic labels, uncertainty markers, and structural hints into the shard workspace

### Shard-Agent Correction Pass

The shard agent reviews the deterministic labels and corrects them only inside its owned window.

#### Recommended shard input

- a local neighborhood of blocks
- deterministic labels
- structural metadata
- uncertainty markers
- optional rule outputs or parser warnings
- explicit ownership list so the agent knows which rows it must return

#### Recommended shard output

A strict normalized response with:

- one final label per owned block
- optional notes on why a correction was made
- confidence or ambiguity flags

### Important Design Rule

The shard agent should correct labeling, not rediscover the whole book from scratch.

### Token Policy

Prefer bounded local review shards, not whole-book prompts and not many tiny one-line calls.

Good:

- review a bounded local window with the current labels and explicit ownership

Bad:

- give the model huge amounts of surrounding book text with no label-first framing
- create overlapping shards that can both mutate the same rows

### Validation

- every block must end with exactly one final label
- label diffs between deterministic and corrected versions must be inspectable
- uncertainty should be surfaced, not hidden
- every reviewed block must be owned by exactly one shard

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
- start and end block IDs
- optional title block ID
- optional notes or variant subspans
- any grouping warnings

### Core Principle

Once labeling is good, grouping should be deterministic.

### Grouping Rules

Recipe spans should be formed from labels, for example:

- start at `recipe_title`
- continue through expected recipe labels
- stop at the next `recipe_title` or strong non-recipe boundary
- allow notes or variants to remain attached if labeling says they belong

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

This is the main debug and validation artifact for recipe structure.

It should capture:

- title
- yield
- times
- ingredient lines or normalized ingredients
- instructions or steps
- notes
- variants
- provenance back to block IDs

### Core Principle

This is where raw labeled evidence becomes a coherent recipe representation.

### LLM Role

None in the deterministic builder itself.

### Notes

This stage should do the best possible deterministic job before asking a shard agent to help.

---

## Stage 5 — Shard-Agent Recipe Correction + Linkage Generation

### Goal

Review deterministic intermediate recipe objects and fix mistakes while also producing the ingredient-step linkage data needed for the final output.

### Input

For one bounded recipe shard:

- the original labeled blocks for each owned recipe span
- the deterministic intermediate recipe object for each owned `recipe_id`
- parser warnings or uncertainty signals
- block provenance
- schema and output contract

### Output

A structured shard response containing, for every owned `recipe_id`:

#### A) Corrected intermediate recipe object

This is the cleaned-up canonical recipe representation.

#### B) Linkage payload

A compact structure describing:

- which ingredients belong to which steps
- any cross-step ingredient reuse
- unresolved or ambiguous ingredient-step relationships
- optional linkage confidence flags

#### C) Validation or issue flags

For example:

- missing instruction details
- ambiguous ingredient references
- likely variant leakage
- suspicious title, yield, or time parsing

### Why this design

The hard reasoning is mostly:

- interpreting the labeled recipe correctly
- cleaning up the intermediate object
- deciding ingredient-step relationships

The final recipe object is mostly a deterministic reshaping of that information.

So the shard agent should do one local reasoning pass and emit:

- corrected recipe structure for every owned recipe
- linkage instructions for every owned recipe

Then deterministic code should assemble the final objects.

### Important Design Rule

Do not spend a separate heavy model call on "intermediate -> final" if the final step is mostly data reshuffling.

### Shard Design Rule

Recipe shards should be conservative.

Good shard grouping:

- nearby recipes in recipe order
- explicit caps on recipe count and payload size
- one shared shard framing with per-recipe owned outputs

Bad shard grouping:

- one recipe per fresh agent forever
- giant chapter-wide shards with weak ownership

### Fallback Strategy

If needed, a second shard or retry may exist as an exception path only when:

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

If the shard agent already did the reasoning, this stage should be a reliable writer and assembler, not another interpretation stage.

---

## Stage 7 — Non-Recipe Handling / Knowledge Pipeline

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
- tags or metadata
- embeddings-ready records later

### Core Principle

Most `knowledge` vs `other` separation should already be solved by Stage 2 labeling.

### Recommendation

Treat knowledge extraction as downstream of good labeling, not as a giant separate whole-book mining task.

### Suggested Design

#### Stage 7A — Classification

Use Stage 2 labels to separate:

- `knowledge`
- `other`

#### Stage 7B — Optional shard-agent refinement

Only run a bounded shard-agent pass on regions already labeled as `knowledge`.

Each knowledge shard should:

- own a contiguous outside-recipe region or chunk group
- return one normalized result per owned `chunk_id` or span ID
- preserve evidence snippets compatible with downstream reviewer artifacts

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

Optional, scoped, bounded, and label-driven.

### Notes

This stage should get smaller as Stage 2 labeling improves.

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
- shard manifests and telemetry
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
- the shard manifest entry that owned the correction

---

# Recommended Artifact Contract

Suggested artifacts per cookbook run:

- `00_source_normalized.json`
- `01_blocks.jsonl`
- `02_labels_deterministic.jsonl`
- `03_labels_corrected.jsonl`
- `04_recipe_spans.json`
- `05_intermediate_deterministic.json`
- `06_recipe_shard_outputs.json`
- `07_final_recipes.json`
- `08_nonrecipe_spans.json`
- `09_knowledge_outputs.json`
- `10_validation_report.json`
- `11_run_summary.json`

Suggested shard runtime artifacts:

- `raw/llm/<workbook_slug>/line_role_shards_manifest.json`
- `raw/llm/<workbook_slug>/recipe_shards_manifest.json`
- `raw/llm/<workbook_slug>/knowledge_shards_manifest.json`
- `prediction-run/prompt_budget_summary.json`
- `prediction-run/prompt_budget_summary.md`

Optional per-recipe debug packet:

- `debug/<recipe_id>.json`

That per-recipe packet should include everything needed to audit one recipe end-to-end.

---

# Shard-Agent Rules

## General Rule

Every Codex-backed stage should be bounded, evidence-grounded, and ownership-driven.

The model should never be asked to "just figure it all out" from scratch if deterministic code can present:

- a stable local shard
- a first draft
- explicit owned IDs
- a strict output contract

## Good Shard Pattern

Provide:

- shard-local evidence blocks
- deterministic first-pass output
- explicit schema and output contract
- clear ownership boundaries
- one normalized result per owned row, chunk, or recipe

Ask for:

- corrections
- structured outputs
- confidence or ambiguity flags
- no edits outside the owned IDs

## Bad Shard Pattern

Provide:

- huge raw spans
- multiple unrelated objectives in one shard
- overlapping shard ownership
- prompts that classify, regroup, parse, and rewrite everything at once
- exact-looking token accounting that ignores internal turns and compaction

---

# Validation Rules

## Labeling

- every block has exactly one final label
- label changes are diffable
- uncertainty is preserved
- shard ownership is exact-once

## Grouping

- every recipe span is contiguous and reproducible
- every grouped block points to final labels
- no unlabeled grouping logic should silently override labels

## Intermediate Recipe Object

- schema-valid
- provenance attached
- parser warnings preserved

## Final Recipe Object

- deterministically buildable from corrected intermediate plus linkage payload
- unresolved ambiguity should be explicit, not hallucinated away

## Knowledge Outputs

- only derived from spans labeled `knowledge`
- never mined from obvious boilerplate or noise unless explicitly enabled for experimentation

## Shard Runtime

- every shard has a stable ID and bounded scope
- every owned row, chunk, or recipe is covered exactly once
- preview reports shard counts and fresh-agent counts
- live telemetry reports observed turns and token totals from the shard runtime, not fake prompt-count proxies

---

# What to Remove / Simplify from Current Implementation

## Remove as primary architecture

- pre-label heuristic recipe candidates driving the whole flow
- prompt-per-bundle Codex-backed work as the main reasoning model

## Remove ambiguity

- stale pass naming or reporting that no longer matches actual behavior
- any observability layer that pretends prompt count is the same thing as shard cost

## Remove redundant model work

- separate heavy reasoning calls for intermediate -> final reshuffling
- repeated per-recipe framing that can live once at the shard level
- full-book knowledge mining when label-driven shard refinement would suffice

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
- `label_shard_correct`
- `group_recipe_spans`
- `build_intermediate_det`
- `recipe_shard_correct_and_link`
- `build_final_recipe`
- `classify_nonrecipe`
- `knowledge_shard_refine_optional`
- `write_outputs`

This alone will make the system far easier to understand.

---

# Failure / Fallback Policy

## If label correction fails

Keep deterministic labels and surface the failure clearly for that shard.

## If recipe grouping fails

Emit an explicit grouping warning and preserve candidate evidence.

## If recipe correction fails

Keep the deterministic intermediate object and mark the owned recipes as uncorrected.

## If linkage is ambiguous

Allow unresolved linkage markers rather than inventing certainty.

## If final assembly fails

Preserve corrected intermediate object and linkage payload so the failure is isolated to assembly.

## If knowledge refinement fails

Keep the deterministic `knowledge` span classification and record the failed shard explicitly.

---

# Recommended Migration Strategy

## Phase 1 — Fix observability and shard runtime first

Before changing too much stage logic:

- add the shared shard-agent runtime
- rename stages clearly
- emit real shard manifests and telemetry
- align reporting with actual shard behavior

## Phase 2 — Make labeling the source of truth and cut over line-role shards

Refactor flow so grouping happens after labeling, and line-role correction is owned by bounded label shards instead of prompt batches.

## Phase 3 — Shrink and localize the knowledge pipeline

Move from broad knowledge mining toward:

- stronger early labels
- shard-owned contiguous knowledge regions
- optional downstream knowledge refinement only on labeled knowledge spans

## Phase 4 — Collapse recipe reasoning into shard-owned recipe correction

Implement:

- deterministic intermediate build
- shard-agent recipe correction plus linkage output
- deterministic final assembly

## Phase 5 — Replace old preview language and remove old active paths

Once architecture is clean:

- preview shard counts instead of prompt counts
- benchmark the shard runtime directly
- remove old one-shot Codex-backed pipeline IDs from active use

---

# Recommended Final Architecture (Short Version)

## Recipe Path

1. extract
2. segment
3. label deterministically
4. shard-correct labels
5. deterministically group recipe spans
6. deterministically build intermediate recipe object
7. shard-correct intermediate objects and output linkage payloads
8. deterministically build final recipe objects
9. write outputs

## Non-Recipe Path

1. take all non-recipe blocks after labeling and grouping
2. classify as `knowledge` vs `other` from labels
3. optionally run bounded shard refinement on `knowledge` only
4. write outputs

## Operational Path

1. preview shard plans from existing processed or benchmark roots
2. measure `fresh_agent_count`, `shard_count`, shard-size distribution, and bounded first-turn payloads
3. run live benchmark comparisons to learn the real quality, token, and wall-time frontier

---

# Final Recommendation on Intermediate vs Final

## Recommended default

Use one shard-agent recipe reasoning pass that outputs, for every owned recipe:

- corrected intermediate recipe object
- linkage payload for final assembly

Then let deterministic code generate the final recipe object.

## Why

This gives you:

- a strong debugging artifact
- lower token cost through shared shard context
- less duplicated model work
- clear stage boundaries
- explicit shard ownership

## Caveat

If the final format later becomes meaningfully more semantic than "intermediate plus pairings", revisit this decision.

But with the current design, one shard-owned reasoning pass plus deterministic assembly is the better default.

---

# Acceptance Criteria

The refactor is successful when:

1. A human can explain the full pipeline in one page.
2. Every stage has one clear job.
3. Every stage has a stable input and output contract.
4. Labels drive grouping.
5. Shard agents correct deterministic outputs instead of replacing the whole architecture.
6. Every reviewed row, chunk, and recipe has exact shard ownership.
7. Intermediate recipe objects are preserved for debugging.
8. Final recipe objects are built deterministically from corrected structure.
9. Knowledge handling is label-driven and shard-scoped.
10. Preview and benchmark reports describe shard work, not old prompt bundles.
11. Reporting matches actual implementation.
12. Any bad final output can be traced back to the exact stage and shard that introduced the error.
