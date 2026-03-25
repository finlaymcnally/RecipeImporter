---
summary: "Plain-English walkthrough of the current stage pipeline from importer selection through final outputs."
read_when:
  - When you want a non-code explanation of how a cookbook moves through the program
  - When updating high-level docs about recipe authority or outside-recipe authority
---

# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

A note to AI editors: keep this as a plain-language product walkthrough. Artifact names are fine when they help explain the product, but constant file-by-file references make this harder to read.

## Start of a run

Every `cookimport stage` run starts by creating a new timestamped output folder and locking in the big behavior choices for that run.

Those settings decide things like:

- how many workers to use
- whether PDF or EPUB source jobs should be split
- whether line-role Codex review is on
- whether recipe Codex is on
- whether knowledge Codex is on
- how ingredient parsing should behave
- whether markdown sidecars should be written

Then the importer registry looks at each input file and picks the importer that best matches that source type.

## What importers are really doing

Importers read the source and preserve as much useful structure as they can for the shared stage pipeline.

Some importers are record-first. They start from rows, fields, or exported recipe objects and preserve that record structure as much as possible.

Some importers are block-first. They start from pages, spine items, paragraphs, headings, or similar document fragments and turn the source into one ordered stream of canonical source blocks.

The important rule is that all of them converge on the same kind of bundle:

- canonical source blocks
- optional source-support proposals
- raw artifacts
- a report

For stage-backed flows, those importers produce the source bundle that feeds the shared recipe-boundary stage, where recipe ownership is decided.

## Split jobs and merge

Large PDFs may be split by page range. Large EPUBs may be split by spine range.

The split covers the early source-conversion work. After that, the run returns to one shared semantic pipeline.

Each job converts its assigned range and returns a partial source model plus raw extraction artifacts. If any job fails, the run stops before the shared semantic session for that source and keeps the temporary job artifacts for debugging.

If all jobs succeed, the program merges them back together in source order. It rebases block indexes, merges support data, rebuilds the whole-book text view, moves raw artifacts into the normal run tree, and only then runs one shared semantic session on the merged whole-book result.

That rule matters: for split sources, semantic authority is decided once on the merged book.

## The real center of the pipeline

After conversion and any split-job merge, the book goes through one shared five-stage runtime:

- `extract`
- `recipe-boundary`
- `recipe-refine`
- `nonrecipe-route`
- `knowledge-final`

That five-stage runtime is the real center of the product. Importer output enters it as the source bundle the later stages shape into final authority.

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

It starts with `label_det`, which creates the deterministic line and block labels. That pass answers practical questions like:

- is this line title-like
- is this line an ingredient line
- is this line an instruction line
- is this line note-like
- does this line belong inside a recipe or outside it
- if it is outside, should it stay alive for later knowledge review

That deterministic pass still matters even when LLM stages are on. It gives the run a reproducible baseline and a clear artifact trail.

If line-role Codex review is enabled, `label_llm_correct` reviews those labels. The safety rule is simple: accepted Codex labels survive after structural validation, and rejected rows fall back to the deterministic baseline with an explicit reason.

After labeling, `group_recipe_spans` groups the accepted recipe lines into candidate spans and decides which of those spans count as real recipes.

An accepted recipe span now needs both:

- a title anchor
- real body proof such as ingredients, instructions, or yield/time structure

That rule exists because cookbook sources are full of recipe-shaped material such as tables of contents, sidebars, shopping lists, and index fragments.

So `recipe-boundary` is both a grouping stage and a rejection stage. It accepts real recipe spans and rejects pseudo-recipes before they can turn into final recipes later.

If the stage accepts zero recipes, that zero is the answer. There is no separate importer recipe count to compare against anymore. The debugging surface is the span artifacts themselves: `recipe_spans.json` shows what was accepted, and `span_decisions.json` shows both accepted spans and rejected pseudo-recipes with reasons.

By the end of `recipe-boundary`, the run knows:

- which spans are real recipes
- which blocks belong to those recipes
- which lines stay outside recipes
- which normalized labels drive the later stages

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

If recipe Codex is enabled, this is the stage that runs it. The public recipe pipeline is `codex-recipe-shard-v1`.

That Codex pass is a refinement layer inside already-accepted recipe boundaries.

Recipe Codex outcomes are explicit now. A valid task result can be:

- `repaired`
- `fragmentary`
- `not_a_recipe`

Only `repaired` promotes into final recipe authority. `fragmentary` and `not_a_recipe` remain visible in runtime artifacts as non-promoted outcomes.

After the optional Codex pass, repo code still validates the result, normalizes it, builds intermediate `schema.org Recipe JSON`, and then builds the final `cookbook3` output. Even when recipe Codex is on, deterministic repo code still owns the final write path.

This stage is also where the run produces its authoritative recipe payloads for later output writing.

## `nonrecipe-route`

After recipe ownership is settled, everything outside accepted recipe spans moves into `nonrecipe-route`.

This stage handles routing and bookkeeping for outside-recipe material.

Its job is to:

- exclude obvious junk immediately
- keep worthwhile survivors alive for later review
- record why each row survived or was excluded

Some rows become final right here. Navigation, publishing junk, endorsements, page furniture, and similar obvious noise can be excluded immediately as final `other`.

Surviving outside-recipe text then moves into one category-neutral review queue for the later knowledge stage, where the harder semantic judgment happens.

By the end of `nonrecipe-route`, the run has:

- final obvious-junk exclusions
- one review queue of surviving outside-recipe rows
- routing metadata that explains why rows survived or were excluded

This is why the run writes separate routing and final-authority artifacts.

## `knowledge-final`

`knowledge-final` is the final semantic owner of reviewable outside-recipe material.

If knowledge review is off, the run keeps the routing and status artifacts and can still build deterministic late outputs from the surviving outside-recipe block list.

If knowledge review is on, the public knowledge pipeline is `codex-knowledge-shard-v1`.

Before the model sees anything, the program packages the surviving review queue into bounded ordered packets. Repo code owns packet sizing and ordering. The model owns the harder semantic judgment inside each packet.

That means the model decides:

- which reviewed rows are real `knowledge`
- which reviewed rows are just `other`
- which nearby blocks belong together as one related idea group

The reviewed results are then validated and promoted back into the stage-owned authority model.

This is the place where the system makes its final semantic claim about outside-recipe prose:

- this passage is real cooking knowledge
- this passage is just other outside-recipe material
- this passage was excluded earlier and never came back into play

In artifact terms:

- `08_nonrecipe_seed_routing.json` is the deterministic routing view
- `09_nonrecipe_authority.json` is the final machine-readable truth
- `09_nonrecipe_knowledge_groups.json` records the promoted model-authored related-idea groups
- `09_nonrecipe_review_status.json` explains what was reviewed, skipped, changed, or left unresolved

If reviewer-facing knowledge snippets are written, they are evidence artifacts derived from those promoted groups.

## Late outputs

Once recipe and outside-recipe authority are settled, the program can safely build the downstream artifacts that depend on them.

That includes:

- intermediate `schema.org Recipe JSON`
- final `cookbook3` drafts
- sections
- chunks
- tables
- reviewer-facing knowledge artifacts
- raw artifacts
- reports
- benchmark-facing `stage_block_predictions.json`
- run manifest and observability files

Sections come from the finalized recipe side.

Tables and chunks follow the stage-owned outside-recipe result. If no outside-recipe material survives into that late stage-owned view, the correct answer is no such outputs.

`stage_block_predictions.json` matters because it is the run's block-level benchmark evidence after the real authority decisions have already happened.

So the end of the run is: write recipes, write outside-recipe authority, write the downstream artifacts built from those decisions, and write enough observability to explain the run later.

## Easy-to-miss rules

- Importers read the source, preserve structure, and hand the shared stage pipeline the material it needs.
- The deterministic label-first path still runs even when recipe and knowledge LLM stages are both off.
- Accepted recipe spans are the recipe ownership boundary. Later stages refine those recipes into final structured outputs.
- `nonrecipe-route` routes and records. `knowledge-final` decides the final meaning of reviewable outside-recipe rows.
- `ConversionResult.non_recipe_blocks` mirrors the stage-owned outside-recipe result for downstream consumers.
- Split PDF and EPUB jobs do early conversion in pieces, but semantic authority still happens once on the merged whole-book view.
