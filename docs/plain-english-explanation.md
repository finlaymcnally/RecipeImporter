# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

a note to AI editors: please do not include code/file references here. it is confusing and not helpful to read (unless you are highlighting something about that file specifically, but each time you mention code doesn't need a "citation" to that file)

## Start of a run

Every `cookimport stage` run starts by creating a new timestamped output folder and deciding how much parallel work to use.

Then the importer registry looks at each input file and picks the importer that seems most appropriate for that source type.

Some importers are record-first. They try to read recipes directly from rows, fields, or structured data.

Other importers are block-first. They turn the book into one long ordered stream of canonical source blocks and only then try to find recipe-shaped regions inside that stream.

At this point everything is still provisional. Importers are source normalizers. They are not the final authority on what counts as a recipe or what counts as useful outside-recipe knowledge.

PDF and EPUB inputs have one extra wrinkle: the program may split them into source jobs. Those jobs only do the early conversion work. Afterward the program merges those job results back into one whole-book bundle, fixes indexes and recipe IDs, rebuilds the full text view, and only then runs the shared semantic session.

## The real center of the pipeline

After conversion and any split-job merge, the book goes through one shared five-stage runtime:

- `extract`
- `recipe-boundary`
- `recipe-refine`
- `nonrecipe-route`
- `knowledge-final`

That five-stage session is the real center of the pipeline. Importer output enters it as raw material, not as final truth.

## `extract`

`extract` rebuilds the book into the shared internal shape the later stages expect. It pulls together the canonical source blocks, block archive, and atomic line view so later decisions are based on one consistent representation of the book.

## `recipe-boundary`

`recipe-boundary` is where recipe ownership becomes authoritative.

It starts with `label_det`, which creates the deterministic line-by-line and block-level labels.

If line-role Codex review is enabled, `label_llm_correct` can refine those labels. Even then, the repo-owned validation and cleanup logic is still the final gate on whether those corrections count.

After labeling, `group_recipe_spans` groups accepted lines back into recipe spans. This is the main authority handoff in the system. Importer recipes are not the final truth anymore. The accepted grouped spans are.

A grouped span usually needs a title anchor to count as a real recipe. Structured-looking text without a convincing title can still be rejected as a pseudo-recipe.

If an importer thought there were recipes but `group_recipe_spans` ends up with zero accepted recipes, the program does not quietly fall back to the importer guess. It stays on the label-first result and records that mismatch as an authority problem.

## `recipe-refine`

Once accepted recipe spans exist, the program rebuilds recipe candidates from those spans instead of simply carrying importer candidates forward.

If recipe Codex is enabled, this is the stage that runs it. The public recipe pipeline name is `codex-recipe-shard-v1`.

That Codex step is a refinement pass, not the final writer. Repo code still validates the result, normalizes it, builds the intermediate `schema.org Recipe JSON`, and then builds the final `cookbook3` output.

So even when recipe Codex is on, the final files are still written through deterministic repo-owned staging code.

## `nonrecipe-route`

After recipe ownership is settled, everything outside the accepted recipe spans goes into `nonrecipe-route`. This is the runtime step most people have been informally calling Stage 7.

This stage creates the first real outside-recipe routing map. It decides which outside-recipe rows are obvious junk, which ones are review-eligible, and which simple seed category each row starts in.

Some material becomes final immediately here: navigation, publishing junk, endorsements, page furniture, and similar noise can be excluded right away as final `other`.

The important subtle rule is that `nonrecipe-route` is allowed to route and exclude obvious junk, but it is not the final authority on the harder semantic question of whether a surviving outside-recipe passage is real cooking knowledge.

That is why the run now has a seed-routing artifact and a separate final-authority artifact instead of pretending those are the same thing.

## `knowledge-final`

`knowledge-final` is the last authority step for outside-recipe meaning.

If knowledge review is off, the program keeps the `nonrecipe-route` result and moves on.

If knowledge review is on, the public knowledge pipeline name is `codex-knowledge-shard-v1`.

Before that reviewer sees anything, the program chunks the surviving review-eligible outside-recipe text into local pieces. The reviewer works on those chunks, not on the entire book at once.

Those worker decisions refine the seed routing into the final outside-recipe authority. So the final `knowledge` blocks are not whatever the importer found, and not whatever the early line labels happened to suggest. They are whatever survives `knowledge-final`.

In artifact terms, `08_nonrecipe_seed_routing.json` is the deterministic Stage 7 routing view, `09_nonrecipe_authority.json` is the final machine-readable truth, and `09_nonrecipe_review_status.json` explains what was reviewed, skipped, changed, or left unresolved.

## What gets written at the end

Once recipe and outside-recipe authority are settled, the program writes the finished outputs.

That includes intermediate `schema.org Recipe JSON`, final `cookbook3` drafts, sections, chunks, tables, knowledge outputs, raw artifacts, reports, and benchmark-facing `stage_block_predictions.json`.

Those late outputs are built from the final stage-owned authority surfaces, not from the importer's first guesses.

Finally the run writes manifest and observability files so later tools can inspect what happened.

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
