---
summary: "Compact labeling guide for AI agents derived from the live recipe, line-role, and knowledge-stage prompt contracts."
read_when:
  - When labeling cookbook rows or spans with AI
  - When writing or revising labeling prompts for recipe, line-role, or knowledge stages
  - When reviewing borderline recipe-vs-nonrecipe or knowledge-vs-other decisions
---

# AI Agent Labelling Guide

This guide is the durable plain-English summary of the current live prompt contracts for the three LLM-backed labeling stages in `recipeimport`:

- recipe refine
- canonical line-role
- knowledge review
  - pass 1: keep/drop for second-pass review
  - pass 2: grouping and tag grounding

Use this as the semantic contract. The code-level prompt files and task-file contracts remain the exact runtime surface.

## Shared rules across all stages

- The owned row or block text is the primary evidence.
- Nearby context is for disambiguation only. Do not let a strong neighboring row rescue a weak owned row.
- Decide at the smallest grounded unit. Do not batch an entire packet into one semantic call just because adjacent rows look related.
- Be conservative. Narrow positive decisions are better than laundering memoir, framing, headings, or fluff into structured outputs.
- Do not invent missing structure, recipe content, tags, or explanations.
- When a row is mostly connective rhetoric, author voice, praise, navigation, or scene-setting, it usually should not be promoted.

## Stage 1: Recipe Refine

Goal: decide whether a suspicious candidate is a real recipe, a fragmentary recipe, or not a recipe.

Use these statuses:

- `repaired`: the source is clearly a real recipe and supports a grounded corrected title, ingredient list, and step list.
- `fragmentary`: the source still belongs to a recipe, but it is too incomplete to repair into a confident full recipe.
- `not_a_recipe`: the source is clearly not a recipe and should be handed back to nonrecipe handling.

Important boundaries:

- Do not force a non-recipe span into recipe shape.
- Do not invent ingredients, steps, yield, notes, or ingredient-step links.
- Only return ingredient-step mapping when the source clearly supports it.
- Grounded tags come last. Select only obvious recipe tags from the actual source text.
- If you reject as `fragmentary` or `not_a_recipe`, do it honestly instead of padding weak material into a fake finished recipe.

## Stage 2: Canonical Line-Role

Goal: give each owned atomic line one route label.

Allowed labels:

- `RECIPE_TITLE`: a fresh recipe name starting a real recipe.
- `INGREDIENT_LINE`: ingredient items or quantity-unit ingredient rows.
- `INSTRUCTION_LINE`: recipe-local procedural action, even if it includes time.
- `TIME_LINE`: standalone timing or temperature line, not a full instruction sentence.
- `HOWTO_SECTION`: a real recipe-internal subsection heading with nearby ingredients and/or steps.
- `YIELD_LINE`: standalone yield or serving line.
- `RECIPE_VARIANT`: a local alternate-version heading or short alternate-version run inside one parent recipe.
- `RECIPE_NOTES`: recipe-local prose such as storage, make-ahead, leftovers, explanatory notes.
- `NONRECIPE_CANDIDATE`: outside-recipe material that stands on its own as portable cooking knowledge worth later knowledge review.
- `NONRECIPE_EXCLUDE`: outside-recipe fluff, memoir, navigation, praise, framing, front/back matter, decorative headings, or other non-reusable material.

Important distinctions:

- If a line contains real recipe action plus time, prefer `INSTRUCTION_LINE`, not `TIME_LINE`.
- Storage/freezing/refrigeration/make-ahead guidance usually stays `RECIPE_NOTES`, not `INSTRUCTION_LINE`.
- Use `HOWTO_SECTION` only for a real mini-preparation. Do not invent subsection structure from a heading-shaped row alone.
- A named component inside a larger ingredient list is usually still `INGREDIENT_LINE`, not `HOWTO_SECTION`.
- Variant context is local, not sticky. If a fresh title is followed by yield or ingredients, reset to a new `RECIPE_TITLE`.
- Outside recipe, use `NONRECIPE_CANDIDATE` only when the row itself would be worth retrieving later as standalone cooking guidance.
- Outside recipe, memoir, praise, promises, broad encouragement, cookbook thesis, headings without useful body text, and contents-like lists usually stay `NONRECIPE_EXCLUDE`.

## Stage 3 Pass 1: Knowledge Keep/Drop

Goal: decide whether each non-recipe row is worth carrying into second-pass knowledge grouping.

Allowed categories:

- `keep_for_review`: standalone reusable cooking knowledge worth second-pass review.
- `other`: everything else.

Keep a row only when it stands on its own as durable cooking leverage, such as:

- a mechanism or cause-and-effect explanation
- troubleshooting guidance
- substitution advice
- storage or safety rules
- sensory guidance with clear reuse value
- a compact reference fact

Keep it `other` when it is mainly:

- memoir or scene-setting
- praise, endorsement, foreword, manifesto, or book framing
- broad encouragement or teacherly motivation
- navigation or chapter taxonomy
- decorative or conceptual headings
- connective coaching fragments that do not stand alone

Hard rules:

- Headings stay `other` in pass 1, even when they name the nearby concept clearly.
- Do not think about tags in pass 1.
- Do not keep a row just to preserve structure for later grouping.
- If only one row in a mixed run is genuinely reusable, keep only that row.

## Stage 3 Pass 2: Knowledge Grouping And Grounding

Goal: take the kept rows and turn them into contiguous idea groups with grounded tags.

Grouping rules:

- Group only rows that survived pass 1.
- Every kept row must appear in exactly one group.
- Each group must be one contiguous run in reading order.
- Adjacency alone is not enough. Split groups when the topic or tag story changes.
- Give each group a short plain-English `topic_label`.

Grounding rules:

- Use existing ontology tags first when they fit cleanly.
- Proposed tags are allowed only for a real catalog gap.
- If you propose a tag, you must also explain why no existing tag fits and provide a retrieval query.
- Rows that share one group should share one coherent topic and grounding story.
- If two nearby rows need different tags or different explanations, split them into different groups.

Practical bias:

- Prefer a small number of clean groups over one oversized mixed group.
- Prefer existing tags over speculative new ones.
- If a row cannot support a specific grounded tag story, it probably should not have survived pass 1.

## Borderline Cases

- A useful explanatory body under a heading: heading stays low-authority (`other` / not promoted), body carries the knowledge.
- Memoir plus one cooking lesson: keep only the exact row that independently states the lesson.
- Broad coaching like `trust your palate`: usually too vague for knowledge unless the row itself states a concrete reusable rule.
- Short technical rows can still be valuable knowledge if they genuinely help future cooking decisions.

## Short Version

- Promote the narrowest grounded unit.
- Do not let context launder weak material upward.
- Recipe stage repairs real recipes only.
- Line-role separates recipe structure, reusable outside-recipe knowledge candidates, and junk.
- Knowledge pass 1 is conservative binary triage.
- Knowledge pass 2 groups only the kept rows and grounds them to real tags.
