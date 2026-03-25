# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

a note to AI editors: please do not include code/file references here. it is confusing and not helpful to read (unless you are highlighting something about that file specifically, but each time you mention code doesn't need a "citation" to that file)

## Start of a run

Every `cookimport stage` run starts by creating a new timestamped output folder and deciding how much parallel work to use.

The run settings also lock in the big behavior choices up front: how many workers to use, how source jobs should be planned, whether line-role Codex review is on, whether recipe Codex is on, whether knowledge Codex is on, how ingredient parsing should behave, whether markdown sidecars should be written, and similar knobs that affect the whole run.

Then the importer registry looks at each input file and picks the importer that seems most appropriate for that source type.

Some importers are record-first. They start from rows, fields, or explicit exported recipe objects and try to preserve those records while still turning them into the shared source model.

Other importers are block-first. They start from pages, spine items, paragraphs, headings, or other document fragments and turn the source into one long ordered stream of canonical source blocks.

The important business rule here is that all of those importers now converge on the same kind of result. They all produce a conversion bundle with:

- canonical source blocks
- optional source-support proposals
- raw artifacts
- a report

Importers may carry source-native proposals in `source_support`, but that support is non-authoritative. For stage-backed flows, importers are source normalizers: they publish canonical source blocks, raw artifacts, and support data, and the shared stage later owns recipe and outside-recipe authority.

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

Every source now runs through planned source jobs. For many inputs that plan contains one whole-source job. For larger PDFs or EPUBs it may contain multiple ranged jobs. Either way, those jobs only do the early conversion work. Afterward the program merges the job results back into one whole-book bundle, fixes indexes and recipe IDs, rebuilds the full text view, and only then runs the shared semantic session.

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
- does this line belong inside the accepted recipe structure or outside it
- if it is outside the recipe structure, should it stay alive for later Codex knowledge review

The deterministic pass is important even when LLMs are available. It gives the system a reproducible first pass, creates artifact trails, and establishes the structural baseline that the later Codex step can review.

If line-role Codex review is enabled, `label_llm_correct` is the normal fuzzy review pass over those labels. Repo code still validates shape, ownership, and consistency before installing the corrected result, but the semantic judgment is meant to come from Codex here.

After labeling, `group_recipe_spans` groups accepted lines into recipe spans.

This is the main authority handoff in the system. The accepted grouped spans are the authoritative recipe boundaries for the rest of the run.

A grouped span usually needs a title anchor to count as a real recipe. Structured-looking text without a convincing title can still be rejected as a pseudo-recipe.

That title-anchor rule exists because cookbook sources often contain recipe-shaped junk: tables of contents, index-like blocks, sidebars, ingredient-like shopping notes, or small structured fragments that look recipe-ish but are not actually real recipes.

So `recipe-boundary` is not just grouping. It is also a rejection stage. It rejects titleless pseudo-recipes, weak spans, and other false positives instead of treating every structured cluster as a valid recipe. Rejected material stays on the outside-recipe side of the book rather than becoming a final recipe.

If `group_recipe_spans` ends up with zero accepted recipes, the program stays on that label-first result and records the mismatch as an authority problem.

That is a strong business decision. The program surfaces the mismatch instead of reviving some different authority story later in the run.

By the end of `recipe-boundary`, the program knows:

- which spans count as real recipes
- which blocks belong to those recipes
- which lines stay outside recipes
- which normalized recipe/non-recipe labels should drive later stages

## `recipe-refine`

Once accepted recipe spans exist, the program assembles one recipe object for each accepted span.

`recipe-boundary` decides which lines and blocks belong to a recipe. `recipe-refine` then turns that accepted span into actual recipe structure.

Now the recipe side becomes a semantic shaping problem.

The system works through the common recipe business logic:

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

This is where the program turns the accepted recipe span into one coherent recipe representation. The label stage has already done the ownership and line-role work; this stage does the recipe assembly and normalization work that turns those labeled spans into recipe data.

If recipe Codex is enabled, this is the stage that runs it. The public recipe pipeline name is `codex-recipe-shard-v1`.

That Codex step is a refinement pass, not the final writer.

Its job is to improve recipe semantics inside the boundaries already accepted by `recipe-boundary`. In practice it is looking at the stage-owned recipe payload generated from those accepted spans, not reopening recipe ownership. It can help with things like cleaner recipe structure, better note placement, better ingredient-step links, and tag suggestions.

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

After recipe ownership is settled, everything outside the accepted recipe spans goes into `nonrecipe-route`.

This stage is mainly a routing and bookkeeping step over the outside-recipe side of the book.

It is not supposed to be the final fuzzy judge of meaning. Its main job is to carry forward the rows that should stay alive for Codex knowledge review, separate them from the obviously useless junk that can be excluded immediately, and record the status needed by the later knowledge stage.

Some material becomes final immediately here: navigation, publishing junk, endorsements, page furniture, and similar noise can be excluded right away as final `other`.

That matters because cookbook sources are full of outside-recipe text that is not equally valuable. Some of it is clearly worthless for downstream use. Some of it might be useful cooking knowledge. Some of it is ambiguous and should not be finalized too early.

The important subtle rule is that `nonrecipe-route` can exclude obvious junk, but it is not the final authority on the harder semantic question of whether a surviving outside-recipe passage is real cooking knowledge. In the normal product path, that fuzzy decision belongs to Codex.

That is why the run now has a seed-routing artifact and a separate final-authority artifact instead of pretending those are the same thing.

By the end of `nonrecipe-route`, the program has two routed outcomes plus the metadata needed for the next stage:

- excluded rows that are done forever
- one category-neutral review queue containing every surviving row that is still alive for later Codex judgment
- routing metadata that explains why those rows survived or were excluded

This stage also matters because later chunk generation, table extraction, Label Studio knowledge counts, and benchmark evidence are not supposed to revive importer leftovers or old side lanes. They are supposed to follow the stage-owned outside-recipe path.

## `knowledge-final`

`knowledge-final` is the last authority step for outside-recipe meaning.

If knowledge review is off, the program keeps the routed review queue artifact and moves on. In that mode, only the upstream obvious-junk exclusions have final outside-recipe authority; the surviving reviewable rows stay provisional rather than magically becoming final semantic truth.

If knowledge review is on, the public knowledge pipeline name is `codex-knowledge-shard-v1`.

Before that reviewer sees anything, the program packages the surviving review-eligible outside-recipe text into the bounded local units that the knowledge runtime uses for review, rather than asking for one giant whole-book judgment at once.

There is one important extra rule here. Not every review-eligible piece automatically gets sent to the LLM. Inside `knowledge-final`, the program can take a conservative deterministic fast path for a chunk that looks clearly non-useful: strong negative utility cues, no positive utility cues, no strong knowledge cue, and no borderline signal. When that happens, the program does not claim it found subtle knowledge deterministically. It does the opposite. It says this chunk looks obviously like final `other`, skips the LLM call, and records that as a repo-owned final decision. So this shortcut is a cheap obvious-not-knowledge filter, not a cheap way to declare real knowledge.

That bounded packaging matters for business logic, not just token control. The point is to give Codex grounded local material to review and eventually turn into better knowledge outputs. The knowledge side still looks unfinished compared with the recipe side, especially around topic grouping and tagging.

The reviewer returns semantic decisions plus the supporting snippets and records used by the runtime. Those decisions are then validated and promoted back into the stage-owned authority model.

Those worker decisions refine the routed review queue into the final outside-recipe authority.

So the final `knowledge` blocks are not whatever the importer found, and not whatever the early line labels happened to suggest. They are whatever survives `knowledge-final`.

This is the place where the system makes its final semantic claim about outside-recipe prose:

- this passage is real cooking knowledge
- this passage is just other outside-recipe material
- this passage was excluded earlier and never came back into play

In artifact terms, `08_nonrecipe_seed_routing.json` is the deterministic `nonrecipe-route` view (legacy Stage 7 routing), `09_nonrecipe_authority.json` is the final machine-readable truth, and `09_nonrecipe_review_status.json` explains what was reviewed, skipped, changed, or left unresolved. The routing artifact keeps queue and exclusion facts, not the final semantic answer.

If optional reviewer-facing knowledge snippets are written, they are evidence artifacts, not the authority surface themselves.

## Tables, chunks, sections, and other late outputs

Once the core authority decisions are done, the program can safely build the downstream artifacts that depend on them.

Sections come from the finalized recipe side.

Chunks come from final outside-recipe authority only. That is a deliberate business rule. If no final outside-recipe rows survive, the correct answer is no chunks, not a fallback to some older importer-side guess.

Table extraction also follows the authoritative staged view instead of acting like a parallel semantic universe. The knowledge side still clearly has more future work in it than the recipe side.

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

# Hidden Layers

- Importer output is provisional. The real recipe authority seam is `recipe-boundary`, especially `label_det`, optional `label_llm_correct`, and `group_recipe_spans`.

- The deterministic label-first path still runs even when `llm_recipe_pipeline=off` and `llm_knowledge_pipeline=off`.

- Outside-recipe text now lives in two real runtime states: Stage 7 routing in `08_nonrecipe_seed_routing.json` and final reviewed authority in `09_nonrecipe_authority.json`.

- `ConversionResult.non_recipe_blocks` is a downstream cache that gets repopulated only from final outside-recipe authority after the stage session has already decided what is truly final.

- `codex-recipe-shard-v1` and `codex-knowledge-shard-v1` are refinement/review layers over repo-owned deterministic scaffolding, not direct final-output writers.

- Split PDF/EPUB debugging is different from single-file debugging because the semantic pipeline only starts after the source jobs are merged back into one whole-book result.

# Design Smells Worth Investigating

- `execute_stage_import_session_from_result()` still feels like a god-function. The five-stage runtime is clearer than the old story, but too much pipeline truth is still composed in one place.

- The authority story is cleaner now, but ownership still moves several times: importer -> `recipe-boundary` -> `nonrecipe-route` -> `knowledge-final`.

- Chunk outputs now correctly depend on final outside-recipe authority. If a run has no surviving final outside-recipe rows, chunk generation should stay empty instead of reviving any older fallback idea.

- The artifact names are better than before but still slightly misleading. `08_nonrecipe_seed_routing.json` sounds more final than it really is, and you need the `nonrecipe-route` / `knowledge-final` split in your head before `09_nonrecipe_review_status.json` makes immediate sense.
