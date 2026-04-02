---
summary: "Plain-English walkthrough for humans of the program"
read_when:
  - Coding agents, DO NOT READ
  - This is a simple explaination for simple humans.
---

# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

This document is written from the intended product perspective: the normal "fully on" workflow is the Codex-backed one. The deterministic-only or "vanilla" path still matters, but mostly as a zero-token baseline, a fallback path, a debugging reference, and a benchmark comparison surface.

So when this doc talks about what the program "does," read that as "what the program is trying to do in its real end-state workflow," not "the cheapest possible run with every AI-assisted stage turned off."

A note to AI editors: keep this as a plain-language product walkthrough. Artifact names are fine when they help explain the product, but constant file-by-file references make this harder to read.

## Start of a run

Every `cookimport stage` run starts by creating a new timestamped output folder and locking in the important behavior choices for that run.

In the product's intended "real" workflow, that usually means turning on the Codex-backed review passes and deciding how aggressively to shard them. The safe/off defaults mostly exist so the repo can support zero-token testing, benchmarking, debugging, and explicit execution consent.

The most important settings at the start of a run are:

- `workers`: the overall process parallelism cap for the run
- `pdf_split_workers`: how many worker slots one split PDF is allowed to use
- `epub_split_workers`: how many worker slots one split EPUB is allowed to use
- `pdf_pages_per_job`: how many PDF pages go into one split source-conversion job
- `epub_spine_items_per_job`: how many EPUB spine items go into one split source-conversion job
- `epub_extractor`: which EPUB extraction engine to use
- `pdf_ocr_policy`: whether PDF OCR is off, automatic, or forced on
- `line_role_pipeline`: whether Codex reviews and corrects line/block labels before recipe grouping
- `llm_recipe_pipeline`: whether Codex runs the recipe-refine stage after recipe boundaries are accepted
- `llm_knowledge_pipeline`: whether Codex runs non-recipe finalize on the surviving outside-recipe candidate queue
- `codex_exec_style`: whether line-role and non-recipe finalize use editable `task.json` workers or inline JSON prompts
- `codex_farm_model`: an explicit model override for enabled Codex-backed stages
- `codex_farm_reasoning_effort`: an explicit reasoning override for enabled Codex-backed stages
- `recipe_prompt_target_count`: the requested shard count for recipe-refine workers
- `line_role_prompt_target_count`: the requested shard count for line-role workers
- `knowledge_prompt_target_count`: the requested shard count for non-recipe finalize workers
- `ingredient_text_fix_backend`, `ingredient_pre_normalize_mode`, `ingredient_packaging_mode`, `ingredient_parser_backend`, `ingredient_unit_canonicalizer`, and `ingredient_missing_unit_policy`: the main ingredient-parsing behavior knobs
- `write_markdown`: whether the run writes human-readable markdown sidecars such as `sections.md`, `tables.md`, and `chunks.md`

If a Codex-backed stage is enabled, explicit model overrides win. Otherwise the run uses discovered config or pipeline defaults. The product does not invent a fake hard-coded model id just because the UI could not discover one.

Then the importer registry looks at each input file and picks the importer that best matches that source type.

## What importers are really doing

Importers read the source and preserve as much useful structure as they can for the shared stage pipeline.

There are three practical importer shapes in the current repo.

Some importers are record-first. These are used when the source already has a meaningful row-like or record-like structure, so preserving that structure is more honest than pretending the file started as free-flowing prose.

Current record-first importers are:

- Excel
- text / markdown / DOCX

In plain English, these importers start from things like rows, paragraphs, fields, or small document units and try to keep those units intact as they build canonical source blocks.

That does not mean they avoid blocks. They still end up producing canonical source blocks. The difference is that the importer trusts the source's small native units first, then turns those units into blocks.

Excel is the clearest example: a worksheet row is already a meaningful source unit, so the importer preserves row identity instead of pretending the sheet was one continuous document stream.

Text and markdown are similar in a simpler way: the importer mostly trusts line-level or small-section structure that already exists in the file.

DOCX sits in this bucket in the current repo for practical implementation reasons. The current DOCX path mostly treats the file as extracted paragraphs or table rows. It does not try to recover a rich whole-document flow the way the EPUB importer does.

Some importers are block-first. These are used when the source is really a document stream, not a clean record set, so the importer's job is to recover one ordered archive of document blocks as faithfully as possible.

Current block-first importers are:

- PDF
- EPUB

In plain English, these importers start from things like pages, spine items, paragraphs, headings, and extracted fragments, then turn that document flow into one ordered stream of canonical source blocks.

This is why EPUB is grouped with PDF instead of with DOCX. Even though EPUB is technically a packaged HTML-like format, the repo treats it as a flowing document with spine order, extracted HTML structure, and block ordering that must be recovered first.

So the practical distinction is not "does this source eventually become blocks?" They all do. The distinction is "what does the importer believe the truthful source unit is before canonicalization?"

Some importers are structured-export-first. These are used when the source is already an exported recipe-oriented format with named fields or explicit recipe objects.

Current structured-export-first importers are:

- Paprika
- RecipeSage
- webschema

These importers preserve that exported structure as much as they can, but they still hand off to the shared stage pipeline instead of claiming final recipe authority on their own.

So the choice is not a runtime "mode switch" where the same importer decides to be block-first one day and record-first the next. It is a design choice based on the shape of the source:

- if the source is naturally row-like or field-like, preserve records
- if the source is naturally one flowing document, preserve ordered blocks
- if the source is already a structured recipe export, preserve the recipe objects and fields as long as possible

For that reason, the current DOCX treatment is partly a product choice and partly an implementation choice. If the repo later grows a much richer DOCX document-structure importer, it could make sense to describe DOCX differently. Right now the current implementation is closer to text-like source-unit preservation than to EPUB-style document-flow recovery.

The important rule is that all of them converge on the same kind of bundle:

- canonical source blocks
- optional source-support proposals
- raw artifacts
- a report

Those source-support proposals are hints, not authority. For example, the text importer can still suggest candidate recipe regions, but those are truthful source coordinates for later review, not final recipe decisions.

For normal stage-backed flows, importers are source normalizers. They do not publish final recipe truth or final non-recipe truth.

## Split jobs and merge

Large PDFs may be split by page range. Large EPUBs may be split by spine range.

The split covers the early source-conversion work. After that, the run returns to one shared semantic pipeline.

Each job converts only its assigned range and returns a partial source model plus raw extraction artifacts. If any job fails, the run stops before the shared semantic session for that source and keeps the temporary job artifacts for debugging.

If all jobs succeed, the program merges them back together in source order. It rebases block indexes, merges support data, rebuilds the whole-book text view, moves raw artifacts into the normal run tree, and only then runs one shared semantic session on the merged whole-book result.

That rule matters: for split sources, semantic authority is decided once on the merged book.

## The real center of the pipeline

After conversion and any split-job merge, the book goes through one shared five-stage runtime:

- `extract`
- `recipe-boundary`
- `recipe-refine`
- `nonrecipe-route`
- `nonrecipe-finalize`

That five-stage runtime is the real center of the product. Importer output enters it as a source bundle, and those five stages decide what the final authority will be.

## `extract`

`extract` rebuilds the importer result into one shared internal book shape that the later stages all understand.

This is where the program establishes:

- one canonical ordered block archive
- one atomic line view for line-role decisions
- normalized source-support data
- shared book-level context for later recipe and non-recipe work

The point is simple: every later stage reasons over the same internal coordinates and the same shared book structure.

## `recipe-boundary`

`recipe-boundary` is where recipe ownership becomes authoritative.

This stage is label-first.

It starts with `label_deterministic`, which creates the deterministic line and block labels. That pass answers practical questions like:

- is this line title-like
- is this line an ingredient line
- is this line an instruction line
- is this line note-like
- does this line belong inside a recipe or outside it
- if it is outside, should it stay alive for later non-recipe review

That deterministic pass still matters even in the intended Codex-backed workflow. It gives the run a reproducible baseline, a bounded review surface, and a clear artifact trail for later validation.

In the intended AI-first path, `label_refine` then reviews those labels in bounded worker sessions. The exact worker transport can vary, but repo code still owns shard planning, validation, repair, and final acceptance. There is no hidden live-path fallback where repo code silently swaps invalid worker output back to deterministic rows and pretends nothing happened.

After labeling, `recipe-boundary` groups the accepted recipe lines into candidate spans and decides which of those spans count as real recipes.

An accepted recipe span now needs both:

- a title anchor
- real body proof such as ingredients, instructions, or yield/time structure

That rule exists because cookbook sources are full of recipe-shaped material such as tables of contents, sidebars, shopping lists, and index fragments.

So `recipe-boundary` is both a grouping stage and a rejection stage. It accepts real recipe spans and rejects pseudo-recipes before they can turn into final recipes later.

If the stage accepts zero recipes, that zero is the answer. There is no separate importer recipe count that gets the last word. The debugging surface is the span artifacts themselves: `recipe_spans.json` shows what was accepted, and `span_decisions.json` shows both accepted spans and rejected pseudo-recipes with reasons.

By the end of `recipe-boundary`, the run knows:

- which spans are real recipes
- which blocks belong to those recipes
- which lines stay outside recipes
- which normalized labels drive the later stages

This is also where the run creates the recipe block-ownership contract that later stages must obey.

## `recipe-refine`

Once accepted recipe spans exist, `recipe-refine` turns each one into an actual recipe object.

`recipe-boundary` decides ownership. `recipe-refine` decides recipe shape.

This stage handles the common recipe business logic:

- title normalization
- ingredient parsing
- instruction parsing
- step segmentation
- yield and time extraction
- temperature extraction
- ingredient-to-step linking
- note handling
- variant handling
- tag handling

This is the stage where the main recipe Codex pass runs. The public recipe pipeline is `codex-recipe-shard-v1`.

That Codex pass is a refinement layer inside already-accepted recipe boundaries.

Recipe Codex outcomes are explicit now. A valid task result can be:

- `repaired`
- `fragmentary`
- `not_a_recipe`

Only `repaired` promotes into final recipe authority. `fragmentary` and `not_a_recipe` remain visible in runtime artifacts as non-promoted outcomes.

One important current rule is that `recipe-refine` cannot silently change block ownership just by changing recipe text or provenance. If it wants to give a block back, it must do that explicitly through divestment. Only blocks that were never recipe-owned, or were later explicitly divested, may enter the non-recipe lane.

After the Codex pass, repo code still validates the result, normalizes it, builds authoritative recipe payloads, builds intermediate `schema.org Recipe JSON`, and then builds the final `cookbook3` output. Even in the AI-first workflow, deterministic repo code still owns the final write path.

## `nonrecipe-route`

After recipe ownership is settled, everything that is still outside recipe ownership moves into `nonrecipe-route`.

This stage handles routing and bookkeeping for outside-recipe material.

Its job is to:

- exclude rows that the upstream line-label stage already marked as obvious junk
- keep worthwhile survivors alive for later review
- record why each row survived or was excluded

Some rows become final right here. The line-label stage can already mark outside-recipe rows with exclusion reasons such as navigation, front matter, publishing junk, endorsements, copyright/legal text, publisher promos, or page furniture. `nonrecipe-route` does not invent those calls on its own. It honors them and excludes those rows immediately as final `other`.

Surviving outside-recipe text then moves into one category-neutral candidate queue for the later knowledge stage, where the harder semantic judgment happens.

By the end of `nonrecipe-route`, the run has:

- final obvious-junk exclusions
- one candidate queue of surviving outside-recipe rows
- routing metadata that explains why rows survived or were excluded

This is why the run writes separate routing and final-authority artifacts.

## `nonrecipe-finalize`

`nonrecipe-finalize` is the final semantic owner of reviewable outside-recipe material.

In the intended product workflow, this stage is on. The off path still exists so the repo can do deterministic baselines, zero-token rehearsals, and fallback behavior when needed.

The public knowledge pipeline is `codex-knowledge-candidate-v2`.

Before the model sees anything, repo code partitions the surviving candidate queue into ordered candidate shards and assigns those shards to workers. Repo code owns shard sizing, ordering, block ownership, validation, and promotion back into the final stage result.

The worker-facing transport can vary by run settings. In some runs the worker edits repo-written `task.json` files. In others the worker answers inline JSON prompts. That implementation detail can change, but the authority boundary does not: repo code still decides which blocks are eligible, validates the returned structure, and only promotes accepted answers.

The semantic review is still split into two jobs:

- classification decides, block by block, whether each candidate row is final `knowledge` or final `other`
- grouping runs only on rows already kept as `knowledge` and groups related rows under topic labels

So the model decides:

- which reviewed rows are real `knowledge`
- which reviewed rows are just `other`
- which kept `knowledge` rows belong together as one related idea group

The reviewed results are then validated and promoted back into the stage-owned authority model.

This is the place where the system makes its final semantic claim about outside-recipe prose:

- this passage is real cooking knowledge
- this passage is just other outside-recipe material
- this passage was excluded earlier and never came back into play

In artifact terms:

- `08_nonrecipe_route.json` is the deterministic routing view
- `09_nonrecipe_authority.json` is the final machine-readable truth
- `09_nonrecipe_knowledge_groups.json` records the promoted model-authored related-idea groups
- `09_nonrecipe_finalize_status.json` explains what was reviewed, skipped, changed, or left unresolved

If reviewer-facing knowledge output is written, `knowledge.md` is the readable rendering of those promoted authority decisions and groups.

If this stage is disabled or falls back, the run still keeps the routing and status artifacts and can still build deterministic late outputs from the surviving outside-recipe block list. That is the backup path, not the main product story.

## Late outputs

Once recipe and outside-recipe authority are settled, the program can safely build the downstream artifacts that depend on them.

That includes:

- authoritative recipe payloads
- intermediate `schema.org Recipe JSON`
- final `cookbook3` drafts
- sections
- tables
- deterministic chunks when non-recipe finalize is off
- reviewer-facing knowledge artifacts when non-recipe finalize runs
- raw artifacts
- reports
- benchmark-facing `stage_block_predictions.json`
- run manifest, summary, and observability files

Sections come from the finalized recipe side.

Tables follow the late-output outside-recipe block list. They are always extracted for stage-backed flows.

Deterministic chunks are the fallback late-output lane when non-recipe finalize is off or falls back. In the intended AI-backed workflow, the run writes reviewed knowledge artifacts instead of `chunks/` files.

If non-recipe finalize produced reviewed outside-recipe authority, that late-output list is the authoritative outside-recipe rows.

If non-recipe finalize is off or falls back, that late-output list is instead the surviving candidate queue from `nonrecipe-route`, so the run can still build useful deterministic tables and chunks without pretending that unreviewed rows are final truth.

`stage_block_predictions.json` matters because it is the run's block-level benchmark evidence after the real authority decisions have already happened.

It also follows the stricter current ownership rule: recipe-owned blocks and final non-recipe `knowledge` are not supposed to overlap. If the runtime ever sees both on the same block, that is treated as a bug or invariant violation, not as a normal merge case where one side quietly wins.

So the end of the run is: let the AI-assisted stages make the fuzzy semantic calls, let deterministic repo code validate and package those decisions, write recipe authority, write non-recipe authority, write the downstream artifacts built from those decisions, and write enough observability to explain the run later.
