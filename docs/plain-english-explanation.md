# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

a note to AI editors: please do not include code/file references here. it is confusing and not helpful to read (unless you are highlighting something about that file specifically, but each time you mention code doesn't need a "citation" to that file)

## Start of a run

Every `cookimport stage` run starts by creating a new timestamped output folder and deciding how much parallel work to use.

The run settings also lock in the big behavior choices up front: how many workers to use, whether PDF or EPUB inputs may be split into multiple source jobs, whether recipe Codex is on, whether knowledge Codex is on, how ingredient parsing should behave, whether markdown sidecars should be written, and similar knobs that affect the whole run.

Then the importer registry looks at each input file and picks the importer that seems most appropriate for that source type.

Some importers are record-first. They start from rows, fields, or explicit exported recipe objects and try to preserve those records while still turning them into the shared source model.

Other importers are block-first. They start from pages, spine items, paragraphs, headings, or other document fragments and turn the source into one long ordered stream of canonical source blocks.

The important business rule here is that all of those importers now converge on the same kind of result. They all produce a conversion bundle with:

- canonical source blocks
- optional source-support proposals
- raw artifacts
- a report

Some importers may also make early guesses about recipes or non-recipe text, but those guesses are not the final truth. Importers are source normalizers first. The shared stage session later decides what is really a recipe and what is really meaningful outside-recipe knowledge.

## What importers are really doing

Importers are trying to preserve as much useful source structure as they can without claiming too much authority too early.

For spreadsheet-like or exported-recipe sources, that often means keeping row order, sheet identity, and field-level structure intact.

For text-like, EPUB, or PDF sources, that often means preserving the order of headings, paragraphs, list items, table-like fragments, and provenance such as page range or spine range.

The program also keeps raw artifacts from this phase so later debugging can answer basic questions like:

- what text did the importer actually see
- what order did it think the blocks were in
- what diagnostics or warnings did it produce
- what extractor backend or parser path was used

That raw preservation is important because a lot of later business logic assumes the source model is already honest and complete enough to support authoritative regrouping.

PDF and EPUB inputs have one extra wrinkle: the program may split them into source jobs. Those jobs only do the early conversion work. Afterward the program merges those job results back into one whole-book bundle, fixes indexes and recipe IDs, rebuilds the full text view, and only then runs the shared semantic session.

## Split jobs and merge

Large PDFs can be split by page range. Large EPUBs can be split by spine range.

This does not mean the semantic pipeline runs separately on each chunk and then tries to stitch together finished answers. The split jobs are only there to make source conversion manageable and parallel.

Each split job returns a partial source model plus its raw extraction artifacts. Then the main process waits for all jobs for that source file to finish.

If any split job fails, the program stops short of the shared semantic session for that source and preserves the temporary job artifacts for debugging.

If all split jobs succeed, the program merges them in source order. It offsets block indexes, rebases source-support references, rebuilds the whole-book extracted text view, moves raw artifacts into the normal run tree, and only then hands one merged book into the real semantic pipeline.

This is a major business rule: for split sources, semantic authority is decided once on the merged whole-book view, not piecemeal on the individual split jobs.

## The real center of the pipeline

After conversion and any split-job merge, the book goes through one shared five-stage runtime:

- `extract`
- `recipe-boundary`
- `recipe-refine`
- `nonrecipe-route`
- `knowledge-final`

That five-stage session is the real center of the pipeline. Importer output enters it as raw material, not as final truth.

## `extract`

`extract` rebuilds the book into the shared internal shape the later stages expect.

This is where the program turns the importer’s source model into the common internal book representation used by all later authority logic.

That includes:

- the canonical ordered block archive
- the atomic line view used for line-role decisions
- the normalized source-support data
- the basic book-level context needed by recipe and non-recipe stages

The point of `extract` is to make the rest of the pipeline operate on one stable book representation instead of a different ad hoc structure for each importer.

That matters because later stages need to compare nearby lines, understand ordering, recover block spans, and write benchmark/debug artifacts in a consistent coordinate system.

## `recipe-boundary`

`recipe-boundary` is where recipe ownership becomes authoritative.

This stage is intentionally label-first, not importer-first.

It starts with `label_det`, which creates the deterministic line-by-line and block-level labels.

At this point the program is asking practical classification questions like:

- is this line title-like
- is this line an ingredient line
- is this line an instruction line
- is this line note-like
- is this line clearly outside a recipe
- is this line ambiguous enough to need later review

The deterministic pass is important even when LLMs are available. It gives the system a reproducible first pass, creates artifact trails, and establishes a baseline that the later optional Codex step can refine instead of replacing from scratch.

If line-role Codex review is enabled, `label_llm_correct` can refine those labels. Even then, the repo-owned validation and cleanup logic is still the final gate on whether those corrections count.

After labeling, `group_recipe_spans` groups accepted lines back into recipe spans.

This is the main authority handoff in the system. Importer recipes are not the final truth anymore. The accepted grouped spans are.

A grouped span usually needs a title anchor to count as a real recipe. Structured-looking text without a convincing title can still be rejected as a pseudo-recipe.

That title-anchor rule exists because cookbook sources often contain recipe-shaped junk: tables of contents, index-like blocks, sidebars, ingredient-like shopping notes, or small structured fragments that look recipe-ish but are not actually real recipes.

So `recipe-boundary` is not just grouping. It is also a rejection stage. It throws away titleless pseudo-recipes, weak spans, and other false positives instead of treating every structured cluster as a valid recipe.

If an importer thought there were recipes but `group_recipe_spans` ends up with zero accepted recipes, the program does not quietly fall back to the importer guess. It stays on the label-first result and records that mismatch as an authority problem.

That is a strong business decision. The program would rather surface a mismatch than quietly reintroduce early importer authority that the shared stage just rejected.

By the end of `recipe-boundary`, the program knows:

- which spans count as real recipes
- which blocks belong to those recipes
- which lines stay outside recipes
- which normalized recipe/non-recipe labels should drive later stages

## `recipe-refine`

Once accepted recipe spans exist, the program rebuilds recipe candidates from those spans instead of simply carrying importer candidates forward.

This means recipe structure is regenerated after authoritative grouping. The program is no longer trusting the importer’s original recipe objects as the final source of truth.

Now the recipe side becomes a semantic shaping problem.

The system rebuilds recipe candidates and then works through the common recipe business logic:

- title normalization
- ingredient line parsing
- instruction parsing
- instruction step segmentation when needed
- yield extraction
- time extraction
- temperature extraction
- ingredient-to-step linking
- note handling
- variant handling

This is where a lot of the practical cookbook-specific cleanup happens. The program is trying to take source text that may be messy, inconsistent, or only partially structured and turn it into one coherent recipe representation.

If recipe Codex is enabled, this is the stage that runs it. The public recipe pipeline name is `codex-recipe-shard-v1`.

That Codex step is a refinement pass, not the final writer.

Its job is to improve recipe semantics inside the boundaries already accepted by `recipe-boundary`. It can help with things like cleaner recipe structure, better note placement, better ingredient-step links, and tag suggestions, but it is not allowed to reopen recipe ownership.

Tags live inside this same recipe-refine path now. There is no separate tags subsystem anymore. The recipe correction prompt may emit raw selected tags, then deterministic normalization cleans them up and the final recipe stores them as `recipe.tags`.

After the optional Codex refinement, repo code still validates the result, normalizes it, builds the intermediate `schema.org Recipe JSON`, and then builds the final `cookbook3` output.

So even when recipe Codex is on, the final files are still written through deterministic repo-owned staging code.

This stage is also where the recipe side becomes stable enough to write:

- intermediate drafts
- final drafts
- sections
- recipe-authority payloads

Those are not casual exports. They are the program’s normalized statement of what each accepted recipe means.

## `nonrecipe-route`

After recipe ownership is settled, everything outside the accepted recipe spans goes into `nonrecipe-route`. This is the runtime step most people have been informally calling Stage 7.

This stage creates the first real outside-recipe routing map.

Its job is not to perfectly understand all surviving prose. Its job is to do the first ownership split on the outside-recipe world.

It decides:

- which outside-recipe rows are obvious junk
- which rows are clearly final `other`
- which rows are still plausible knowledge candidates
- which rows are review-eligible and should stay in play for later `knowledge-final`

Some material becomes final immediately here: navigation, publishing junk, endorsements, page furniture, and similar noise can be excluded right away as final `other`.

That matters because cookbook sources are full of outside-recipe text that is not equally valuable. Some of it is clearly worthless for downstream use. Some of it might be useful cooking knowledge. Some of it is ambiguous and should not be finalized too early.

So `nonrecipe-route` is trying to be decisive only where the program has strong enough evidence.

The important subtle rule is that `nonrecipe-route` is allowed to route and exclude obvious junk, but it is not the final authority on the harder semantic question of whether a surviving outside-recipe passage is real cooking knowledge.

That is why the run now has a seed-routing artifact and a separate final-authority artifact instead of pretending those are the same thing.

By the end of `nonrecipe-route`, the program has three practical buckets:

- excluded rows that are done forever
- seed-kept rows that are still only provisional
- the review-status setup for whatever has to go through the last semantic gate

This stage also matters because later chunk generation, table extraction, Label Studio knowledge counts, and benchmark evidence are not supposed to revive importer leftovers or old side lanes. They are supposed to follow the stage-owned outside-recipe path.

## `knowledge-final`

`knowledge-final` is the last authority step for outside-recipe meaning.

If knowledge review is off, the program keeps the `nonrecipe-route` result and moves on.

If knowledge review is on, the public knowledge pipeline name is `codex-knowledge-shard-v1`.

Before that reviewer sees anything, the program chunks the surviving review-eligible outside-recipe text into local pieces. The reviewer works on those chunks, not on the entire book at once.

That chunking matters for business logic, not just token control. The program wants the reviewer to judge bounded local passages with grounded context instead of making vague whole-book judgments.

The reviewer returns block-level keep-or-reject style decisions plus grounded evidence. Those decisions are then validated and promoted back into the stage-owned authority model.

Those worker decisions refine the seed routing into the final outside-recipe authority.

So the final `knowledge` blocks are not whatever the importer found, and not whatever the early line labels happened to suggest. They are whatever survives `knowledge-final`.

This is the place where the system makes its final semantic claim about outside-recipe prose:

- this passage is real cooking knowledge
- this passage is just other outside-recipe material
- this passage was excluded earlier and never came back into play

In artifact terms, `08_nonrecipe_seed_routing.json` is the deterministic Stage 7 routing view, `09_nonrecipe_authority.json` is the final machine-readable truth, and `09_nonrecipe_review_status.json` explains what was reviewed, skipped, changed, or left unresolved.

If optional reviewer-facing knowledge snippets are written, they are evidence artifacts, not the authority surface themselves.

## Tables, chunks, sections, and other late outputs

Once the core authority decisions are done, the program can safely build the downstream artifacts that depend on them.

Sections come from the finalized recipe side.

Chunks come from final outside-recipe authority only. That is a deliberate business rule. If no final outside-recipe rows survive, the correct answer is no chunks, not a fallback to some older importer-side guess.

Table extraction also follows the authoritative staged view instead of acting like a parallel semantic universe.

At this point the run may also write reviewer-facing sidecars like markdown summaries, knowledge snippets, and raw debugging artifacts that help explain what happened without changing any final authority decision.

## What gets written at the end

Once recipe and outside-recipe authority are settled, the program writes the finished outputs.

That includes:

- intermediate `schema.org Recipe JSON`
- final `cookbook3` drafts
- sections
- chunks
- tables
- knowledge outputs
- raw artifacts
- reports
- benchmark-facing `stage_block_predictions.json`
- run manifest and observability files

`stage_block_predictions.json` is important because it represents the run’s block-level benchmark evidence near the end of the pipeline, after the real authority decisions have been made.

Those late outputs are built from the final stage-owned authority surfaces, not from the importer's first guesses.

The run also writes the report and observability story that later tools use to inspect what happened:

- what importer was selected
- whether split jobs were used
- which optional LLM stages ran
- where raw artifacts and final outputs were written
- what stage summaries and mismatch warnings were produced

So the end of the run is not just "write recipes." It is "write recipes, write the outside-recipe authority, write the downstream artifacts built from those decisions, and write enough observability to explain the run later."

## The simplest honest summary

The plainest version of the business logic is this:

First the program converts the source into a canonical book model.

Then it decides recipe boundaries authoritatively with a label-first pipeline.

Then it refines the accepted recipes into normalized recipe semantics and final recipe drafts.

Then it routes all remaining outside-recipe text, immediately throws away obvious junk, and optionally sends the harder surviving passages through one last knowledge review stage.

Then it writes every final artifact from those stage-owned decisions instead of from importer guesses.

# Hidden Layers

- Importer output is provisional. The real recipe authority seam is `recipe-boundary`, especially `label_det`, optional `label_llm_correct`, and `group_recipe_spans`.

- The deterministic label-first path still runs even when `llm_recipe_pipeline=off` and `llm_knowledge_pipeline=off`.

- Outside-recipe text now lives in two real runtime states: Stage 7 seed routing in `08_nonrecipe_seed_routing.json` and final reviewed authority in `09_nonrecipe_authority.json`.

- `ConversionResult.non_recipe_blocks` is a downstream cache that gets repopulated after the stage session has already decided outside-recipe authority.

- `codex-recipe-shard-v1` and `codex-knowledge-shard-v1` are refinement/review layers over repo-owned deterministic scaffolding, not direct final-output writers.

- Split PDF/EPUB debugging is different from single-file debugging because the semantic pipeline only starts after the source jobs are merged back into one whole-book result.

# Design Smells Worth Investigating

- `execute_stage_import_session_from_result()` still feels like a god-function. The five-stage runtime is clearer than the old story, but too much pipeline truth is still composed in one place.

- The authority story is cleaner now, but ownership still moves several times: importer -> `recipe-boundary` -> `nonrecipe-route` -> `knowledge-final`.

- Chunk outputs now correctly depend on final outside-recipe authority. If a run has no surviving final outside-recipe rows, chunk generation should stay empty instead of reviving any older fallback idea.

- The artifact names are better than before but still slightly misleading. `08_nonrecipe_seed_routing.json` sounds more final than it really is, and you need the `nonrecipe-route` / `knowledge-final` split in your head before `09_nonrecipe_review_status.json` makes immediate sense.
