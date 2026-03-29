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
- whether explicit Codex model or reasoning overrides are set
- how ingredient parsing should behave
- whether markdown sidecars should be written

If an LLM-backed stage is enabled, explicit model overrides win. Otherwise the run uses discovered config or pipeline defaults. The product no longer invents a hard-coded fallback model id just because the UI could not discover one.

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

Those source-support proposals are hints, not authority. For example, the text importer can still suggest candidate recipe regions, but those are truthful source coordinates for later review, not final recipe decisions.

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

If line-role Codex review is enabled, `label_llm_correct` reviews those labels through the worker-local `check-phase` / `install-phase` loop. The safety rule is now simple: same-session repair is the normal path, one bounded LLM watchdog retry is allowed if the worker session is killed for a retryable watchdog reason, and otherwise the shard fails closed with explicit repair artifacts. There is no hidden deterministic row fallback on the live worker path.

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

- exclude rows that the upstream line-label stage already marked as obvious junk
- keep worthwhile survivors alive for later review
- record why each row survived or was excluded

Some rows become final right here. The line-label stage can already mark outside-recipe `OTHER` rows with exclusion reasons such as navigation, front matter, publishing junk, endorsements, copyright/legal text, publisher promos, or page furniture. `nonrecipe-route` does not invent those calls on its own. It honors them and excludes those rows immediately as final `other`.

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

Before the model sees anything, the program partitions the surviving review queue into roughly the requested number of contiguous review shards. Repo code owns shard sizing, ordering, and the exact row ownership for each shard.

Each shard then stays in one worker session through two repo-owned passes:

- Pass 1 classifies every owned row as `knowledge` or `other`
- repo validation freezes accepted rows and only leaves unresolved rows open for fixes
- Pass 2 groups only the kept `knowledge` rows into related idea groups with topic labels

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

- `08_nonrecipe_seed_routing.json` is the deterministic routing view
- `09_nonrecipe_authority.json` is the final machine-readable truth
- `09_nonrecipe_knowledge_groups.json` records the promoted model-authored related-idea groups
- `09_nonrecipe_review_status.json` explains what was reviewed, skipped, changed, or left unresolved

If reviewer-facing knowledge output is written, `knowledge.md` is the readable rendering of those promoted authority decisions and groups. Reviewer-facing snippet ledgers are no longer part of the live contract.

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

Tables and chunks follow a late-output outside-recipe block list, not the strict authority cache blindly.

If knowledge review ran and produced reviewed outside-recipe authority, that late-output list is the authoritative outside-recipe rows.

If knowledge review is off or falls back, that late-output list is instead the surviving review queue from `nonrecipe-route`, so the run can still build useful deterministic tables and chunks without pretending that unreviewed rows are final truth.

`stage_block_predictions.json` matters because it is the run's block-level benchmark evidence after the real authority decisions have already happened.

So the end of the run is: write recipes, write outside-recipe authority, write the downstream artifacts built from those decisions, and write enough observability to explain the run later.
