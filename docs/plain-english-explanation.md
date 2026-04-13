---
summary: "Plain-English walkthrough for humans of the program"
read_when:
  - Coding agents, DO NOT READ
  - This is a simple explaination for simple humans.
---

# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

This document is written from the intended product perspective: the normal "fully on" workflow is the Codex-backed one. The deterministic-only or "vanilla" path still matters, but mostly as a zero-token baseline, a fallback path, a debugging reference, and a benchmark comparison surface.

It is very important that all LLM steps are explained clearly. What prompt is the LLM given, what info does it get with the prompt, what is it asked to "do" and how are errors handled?

It is very important that all determinstic steps are explained clearly too. Every time data is modified/transformed/gated/released/etc I want to know how it is changed and WHY. Especially in cases where an LLM decision like a tag or a re-formatting is over-ridden (or could be) by deterministic logic. ESPECIALLY in cases where the program is doing "fuzzy" lookups with code and not from LLM thinking.

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
- `recipe_codex_exec_style`: whether recipe-refine uses the default inline JSON path or the older editable `task.json` worker path
- `line_role_codex_exec_style`: whether line-role uses editable `task.json` workers or inline JSON prompts
- `knowledge_codex_exec_style`: whether non-recipe finalize uses editable `task.json` workers or inline JSON prompts
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

After conversion and any split-job merge, the book enters one shared semantic runtime.

There are two useful ways to describe that runtime:

- the big product stages
- the real execution order

The big product stages are still:

- `extract`
- `recipe-boundary`
- `recipe-refine`
- `nonrecipe-route`
- `nonrecipe-finalize`

That five-stage view is still the right high-level mental model.

But for debugging, the real execution order matters more:

1. `extract`
2. early label authority
3. `recipe-boundary`
4. `recipe-refine`
5. `nonrecipe-route`
6. `nonrecipe-finalize`
7. late output writing and benchmark evidence writing

The run also writes stage numbers into `stage_observability.json`.

Those numbers are now meant to be read like honest step slots, not like leftover implementation debris:

- `line_role` = 10
- `label_deterministic` = 20
- `label_refine` = 30
- `recipe_boundary` = 40
- `recipe_build_intermediate` = 50
- `recipe_refine` = 60
- `recipe_build_final` = 70
- `nonrecipe_route` = 80
- `nonrecipe_finalize` = 90
- `write_outputs` = 100

Not every run uses every stage, but when a stage appears, its number should now match the real dependency story in a human-readable way.

That early-label step now branches like this:

- deterministic or vanilla runs always build a deterministic label baseline
- if Codex-backed `line_role` is enabled, it becomes the authoritative label owner before recipe grouping
- if `line_role` is off, the run stays on the deterministic label-first path

One subtle but important detail: `recipe_build_intermediate` and `recipe_build_final` are still real named stages in run observability, but they are part of the late recipe-output build story after recipe authority already exists. They are not an earlier semantic pass that happens before `recipe-refine` or `nonrecipe-route`.

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

This part of the pipeline is label-first, but that does not mean one single magic label pass does everything.

In plain English, the program first does some early structural labeling and only then groups accepted recipe-looking material into recipe spans.

The early structural story is:

- `label_deterministic` always creates the baseline line and block labels
- some deterministic-backed runs may still write a `label_refine` artifact family
- on the current Codex-backed path, the real pre-boundary semantic owner is `line_role`

`label_deterministic` creates the initial deterministic line and block labels. That pass answers practical questions like:

- is this line title-like
- is this line an ingredient line
- is this line an instruction line
- is this line note-like
- does this line belong inside a recipe or outside it
- if it is outside, should it stay alive for later non-recipe review

That deterministic pass still matters even in the intended Codex-backed workflow. It gives the run a reproducible baseline, a bounded review surface, and a clear artifact trail for later validation.

On the current Codex-backed path, `line_role` then reviews those lines in bounded worker sessions before recipe grouping. The worker transport can vary, but repo code still owns shard planning, validation, repair, and final acceptance.

After those early label steps, `recipe-boundary` groups the accepted recipe lines into candidate spans and decides which of those spans count as real recipes.

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

This is the first big place where later failures can be baked in.

If a true recipe is rejected here, or if recipe-looking material is left outside recipe ownership, then later stages do not get a clean chance to "fix it back into a recipe" just because the prose looks obvious to a human. From this point on, the later stages are already reasoning over that ownership decision.

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

Only `repaired` promotes into published final recipe authority. `fragmentary` and `not_a_recipe` remain visible in runtime artifacts and decision ledgers as non-promoted outcomes.

One important current rule is that `recipe-refine` cannot silently change block ownership just by changing recipe text or provenance. If it wants to give a block back, it must do that explicitly through divestment. Only blocks that were never recipe-owned, or were later explicitly divested, may enter the non-recipe lane.

That rule is good in principle because it keeps authority boundaries honest. But it also means recipe mistakes can become very visible.

One subtle current nuance is that `fragmentary` does not automatically throw all of its blocks back into non-recipe. A fragmentary recipe can stay recipe-owned but unpublished. Blocks only move back out if the worker explicitly divests them.

When explicit divestment does happen, those blocks are no longer treated as safely recipe-local later on. That is exactly the kind of thing that can make titles, variants, notes, and yield lines look like they "mysteriously" collapsed in a benchmark even though a deterministic recipe-local algorithm would normally classify them just fine.

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

Another important debugging detail lives here:

`nonrecipe-route` happens after recipe ownership has already been settled by `recipe-boundary` plus any explicit `recipe-refine` divestment, and before `nonrecipe-finalize`.

So if recipe-local material has already been kicked out of recipe ownership, it can land in the outside-recipe candidate queue here. At that point the later pipeline is no longer deciding between "recipe note" and "recipe variant." It is deciding between "outside-recipe candidate" and "outside-recipe junk" or later "knowledge" versus "other." That is a very different question.

## `line_role`

This section is easy to misread, so the short version is:

`line_role` is early, not late.

On the current Codex-backed path, `line_role` is the first visible semantic authority stage.

In current run numbering, that means `line_role` should appear as stage 10, before `recipe_boundary` at 40.

In plain English:

- the book is atomized into raw lines
- Codex-backed line-role labels those lines
- repo code validates and normalizes those labels
- `recipe_boundary` groups recipes from that accepted line-role authority

That means recipe-local labels like title, variant, notes, and yield now have a chance to influence recipe ownership before recipe ownership hardens.

The deterministic path still keeps the older label-first story as the vanilla baseline.

Here is an actual example taken from a recent local benchmark run on April 11, 2026 for the `saltfatacidheatcutdown` book.

The real shard was much larger. What I am showing here is the real prompt slice around the `Bright Cabbage Slaw` recipe start:

```text
rows:
- "r40 | 6919 | Bright Cabbage Slaw"
- "r41 | 6920 | Serves 4 generously"
- "r42 | 6921 | I know that some people hate coleslaw. But I've converted even the most fervent among them with this version, which bears no resemblance to the cloying stuff many of us grew up eating. Light and clean, it'll lend crunch and brightness to any plate. Serve the Mexican variation with Beer-Battered Fish and tortillas for delicious fish tacos. Make Classic Southern Slaw to serve alongside Spicy Fried Chicken. And remember, the richer the food you plan to serve with it, the more acidic the slaw should be."
- "r43 | 6922 | 1/2 medium head of red or green cabbage (about 1 1/2 pounds)"
- "r44 | 6923 | 1/2 small red onion, thinly sliced"
- "r45 | 6924 | 1/4 cup lemon juice"
- "r46 | 6925 | Salt"
- "r47 | 6926 | 1/2 cup coarsely chopped parsley leaves"
- "r48 | 6927 | 3 tablespoons red wine vinegar"
- "r49 | 6928 | 6 tablespoons extra-virgin olive oil"
- "r50 | 6929 | Quarter the cabbage through the core. Use a sharp knife to cut the core out at an angle. Thinly slice the cabbage crosswise and place in a colander set inside a large salad bowl. Season with two generous pinches of salt to help draw out water, toss the slices, and set aside."
- "r51 | 6930 | In a small bowl, toss the sliced onion with the lemon juice and let it sit for 20 minutes to macerate (see page 118). Set aside."
- "r52 | 6931 | After 20 minutes, drain any water the cabbage may have given off (it's fine if there's nothing to drain-sometimes cabbage isn't very watery). Place the cabbage in the bowl and add the parsley and the macerated onions (but not their lemony juices, yet). Dress the slaw with the vinegar and olive oil. Toss very well to combine."
- "r53 | 6932 | Taste and adjust, adding the remaining macerating lemon juice and salt as needed. When your palate zings with pleasure, it's ready. Serve chilled or at room temperature."
- "r54 | 6933 | Store leftover slaw covered, in the fridge, for up to two days."
- "r55 | 6934 | Variations"
```

The real model answer for that shard was one giant ordered `labels` array covering the whole shard. This is the exact contiguous slice of that returned array for the rows above:

```json
[
  "RECIPE_TITLE",
  "YIELD_LINE",
  "RECIPE_NOTES",
  "INGREDIENT_LINE",
  "INGREDIENT_LINE",
  "INGREDIENT_LINE",
  "INGREDIENT_LINE",
  "INGREDIENT_LINE",
  "INGREDIENT_LINE",
  "INGREDIENT_LINE",
  "INSTRUCTION_LINE",
  "INSTRUCTION_LINE",
  "INSTRUCTION_LINE",
  "RECIPE_NOTES",
  "RECIPE_VARIANT",
  "RECIPE_VARIANT"
]
```

In plain English, that real benchmark answer is saying:

- `Bright Cabbage Slaw` is a fresh recipe title
- `Serves 4 generously` is the yield line
- the paragraph under the title is recipe-local notes
- the short quantity rows are ingredients
- the long action rows are instructions
- `Variations` starts a recipe-variant run instead of a brand-new recipe

That ordered answer then goes back to deterministic repo code, which checks:

- did the AI return exactly one label for every owned row
- are the labels legal for this stage
- did the answer stay aligned with the row order
- if something is missing or malformed, should the repo ask for a bounded repair pass or fail the shard closed

## `nonrecipe-finalize`

`nonrecipe-finalize` is the final semantic owner of reviewable outside-recipe material.

In the intended product workflow, this stage is on. The off path still exists so the repo can do deterministic baselines, zero-token rehearsals, and fallback behavior when needed.

The public knowledge pipeline is `codex-knowledge-candidate-v2`.

Before the model sees anything, repo code partitions the surviving candidate queue into ordered candidate shards and assigns those shards to workers. Repo code owns shard sizing, ordering, block ownership, validation, and promotion back into the final stage result.

The worker-facing transport can vary by run settings. In some runs the worker edits repo-written `task.json` files. In others the worker answers inline JSON prompts. That implementation detail can change, but the authority boundary does not: repo code still decides which blocks are eligible, validates the returned structure, and only promotes accepted answers.

The semantic review is split into two jobs, and both run whenever this stage is enabled:

- classification decides, block by block, whether each candidate row is worth keeping for deeper review or should just become `other`
- grouping is the second pass that looks only at the kept rows, groups related ideas together, and decides whether each group maps to existing tags or needs proposed new tags

So the model always decides:

- which outside-recipe rows are worth keeping for deeper review
- which outside-recipe rows are just `other`

And when grouping is enabled, it also decides:

- which kept `knowledge` rows belong together as one related idea group
- whether that grouped idea maps to existing tags or needs a proposed new tag

The reviewed results are then validated and promoted back into the stage-owned authority model.

This is the place where the system makes its final semantic claim about outside-recipe prose:

- this passage is real cooking knowledge
- this passage is just other outside-recipe material
- this passage was excluded earlier and never came back into play

In artifact terms:

- `08_nonrecipe_route.json` is the deterministic routing view
- `09_nonrecipe_authority.json` is the final machine-readable truth
- `09_nonrecipe_knowledge_groups.json` records the promoted model-authored related-idea groups when grouping runs, and may be empty when classification ran but grouping stayed off
- `09_nonrecipe_finalize_status.json` explains what was reviewed, skipped, changed, or left unresolved

If reviewer-facing knowledge output is written, `knowledge.md` is the readable rendering of those promoted authority decisions and groups.

This is also where the system can accidentally look "too smart" in the wrong way.

Here is an actual first-pass knowledge example from another recent local benchmark run on April 11, 2026 for the same `saltfatacidheatcutdown` cutdown.

This is the opening of a real classification packet:

```text
rows:
- "r01 | 213 | Whether you've never picked up a knife or you're an accomplished chef, there are only four basic factors that determine how good your food will taste: salt, which enhances flavor; fat, which amplifies flavor and makes appealing textures possible; acid, which brightens and balances; and heat, which ultimately determines the texture of food."
- "r02 | 214 | Have you ever felt lost without a recipe, or envious that some cooks can conjure a meal out of thin air? Salt, Fat, Acid, and Heat will guide you as you choose which ingredients to use, how to cook them, and why last-minute adjustments will ensure that food tastes exactly as it should."
- "r03 | 215 | As you discover the secrets of Salt, Fat, Acid, and Heat, you'll find yourself improvising more and more in the kitchen."
- "r04 | 237 | Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what."
- "r05 | 238 | The idea of making consistently great food had seemed like some inscrutable mystery, but now I had a little mental checklist to think about every time I set foot in a kitchen: Salt, Fat, Acid, Heat."
- "r06 | 239 | But everyone didn't know that. I'd never heard or read it anywhere, and certainly no one had ever explicitly related the idea to me."
- "r07 | 242 | I spent my days off in the hills of Chianti... fresh, if modest, ingredients, when treated with care, can deliver the deepest flavors."
- "r08 | 243 | My pursuit of flavor has continued to lead me around the world..."
```

The real model answer for the full packet was one ordered labels array. This is the exact opening slice:

```json
["other","other","other","other","other","other","keep_for_review","keep_for_review"]
```

That means:

- the first six rows in that real packet were treated as framing, promise, or story setup and dropped as `other`
- the next two rows were treated as reusable cooking knowledge and kept for the second pass

Then the second pass looks only at the kept rows and asks a different question: "which of these rows belong to the same idea, and what tag or proposed tag should represent that idea?"

Here is an actual grouping example from a recent local benchmark run on April 11, 2026. This time I am showing the opening of a larger real packet about salt:

```text
row_facts:
- "r01 | classification=keep_for_review"
- "r02 | classification=keep_for_review"
- "r03 | classification=keep_for_review"
- "r04 | classification=keep_for_review"

rows:
- "r01 | 237 | Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what."
- "r02 | 238 | The idea of making consistently great food had seemed like some inscrutable mystery, but now I had a little mental checklist to think about every time I set foot in a kitchen: Salt, Fat, Acid, Heat."
- "r03 | 262 | Once I developed culinary aspirations... I began to see that there is no better guide in the kitchen than thoughtful tasting, and that nothing is more important to taste thoughtfully for than salt."
- "r04 | 271 | The secret behind that zing! can be explained by some basic chemistry. Salt is a mineral: sodium chloride."
```

The real answer repeated the same grouping story for all 16 kept rows in that packet. This is the exact opening of that real JSON response:

```json
{
  "rows": [
    {
      "row_id": "r01",
      "group_id": "g01",
      "topic_label": "Salt",
      "grounding": {
        "tag_keys": ["salt"],
        "category_keys": ["ingredients"],
        "proposed_tags": [
          {
            "key": "salt",
            "display_name": "Salt",
            "category_key": "ingredients",
            "why_no_existing_tag": "No existing ingredient tag captures the chapter's core focus on salt as a cooking element and flavor driver.",
            "retrieval_query": "salt in cooking flavor, salting to taste, kinds of salt"
          }
        ]
      },
      "why_no_existing_tag": "No existing ingredient tag captures the chapter's core focus on salt as a cooking element and flavor driver.",
      "retrieval_query": "salt in cooking flavor, salting to taste, kinds of salt"
    },
    {
      "row_id": "r02",
      "group_id": "g01",
      "topic_label": "Salt",
      "grounding": {
        "tag_keys": ["salt"],
        "category_keys": ["ingredients"],
        "proposed_tags": [
          {
            "key": "salt",
            "display_name": "Salt",
            "category_key": "ingredients",
            "why_no_existing_tag": "No existing ingredient tag captures the chapter's core focus on salt as a cooking element and flavor driver.",
            "retrieval_query": "salt in cooking flavor, salting to taste, kinds of salt"
          }
        ]
      },
      "why_no_existing_tag": "No existing ingredient tag captures the chapter's core focus on salt as a cooking element and flavor driver.",
      "retrieval_query": "salt in cooking flavor, salting to taste, kinds of salt"
    }
  ]
}
```

In plain English, that second answer says:

- these kept rows are all being grouped into one shared idea, `Salt`
- the model thinks that idea maps to the `salt` tag
- the model also emits a proposed-tag explanation because it thinks the existing tag is not specific enough for the whole passage

One important note: these are real benchmark artifacts, not hand-cleaned examples. That means they show the system honestly, including places where the model may have made a debatable or overly broad tagging choice. For this document, that honesty is useful because it shows what the prompt and raw model answers actually look like in practice.

If the outside-recipe candidate queue is too broad, then memoir, teaching, and motivational prose can show up in the same review packets as real cooking knowledge. The current prompt no longer carries repo-generated candidate-tag shortlists, but it still shows the real ontology and still allows proposed tags for genuine gaps. That means the model can still decide that a passage counts as `knowledge` simply because it contains a cooking lesson, even when the gold set would rather treat that passage as ordinary narrative or front matter.

So when a benchmark shows a big `OTHER -> KNOWLEDGE` promotion pattern, that usually does not mean the text extractor failed. It more often means:

- too much prose survived into the outside-recipe candidate queue
- the review packet framed too many rows as plausibly taggable knowledge
- the model then made an understandable but too-broad semantic choice

If this stage is disabled or falls back, the run still keeps the routing and status artifacts and can still build deterministic late outputs from the surviving outside-recipe block list. That is the backup path, not the main product story.

## Late outputs

Once recipe and outside-recipe authority are settled, the program can safely build the downstream artifacts that depend on them.

When staging maps recipe title, variant, yield, and time fields back to source blocks, it now uses exact-or-unresolved evidence. If repo code cannot ground one of those fields exactly, it records unresolved exact-evidence notes instead of guessing.

That includes:

- authoritative recipe payloads
- recipe authority decisions explaining which recipes were promoted, withheld, fragmentary, or divested
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

## Why This Matters In Practice

If you remember only one debugging rule from this document, make it this:

Do not assume the first stage that looks wrong is the stage that caused the problem.

For example, if a benchmark shows that:

- `RECIPE_VARIANT` collapsed
- storage notes stopped looking like `RECIPE_NOTES`
- dressing titles started getting treated like outside-recipe prose

the tempting story is "line-role failed."

Sometimes that is true. But in the current pipeline the more common deeper question is:

"Were those rows still recipe-owned by the time non-recipe routing and final block scoring happened?"

If the answer is no, then the real source of the problem is usually earlier:

- recipe-boundary grouped the region badly
- recipe-refine marked a real recipe as fragmentary
- recipe authority explicitly divested the blocks
- nonrecipe-route accepted those blocks as outside-recipe survivors

Once that chain has happened, the later non-recipe and scoring stages are no longer deciding on a clean recipe-local surface. They are working from already-damaged ownership context.

That is the main reason the current runtime can sometimes look more complicated than a simple "label the book top to bottom" mental model. The pipeline is making ownership decisions early, semantic decisions later, and benchmark symptoms often appear at the end of that chain rather than at the beginning.
