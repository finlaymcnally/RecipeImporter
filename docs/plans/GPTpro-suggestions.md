Yes. I’d keep your overall five-stage shape, but I’d change the **contract** of the K/O path so the long-running Codex worker is spending its effort on the one judgment that actually matters.

Your own plain-English doc already gives you the right backbone: `nonrecipe-route` is supposed to build the outside-recipe review queue, and `knowledge-final` is supposed to be the **final semantic owner** of reviewable outside-recipe prose. It also says `knowledge-final` currently does two repo-owned passes: first classify owned rows as `knowledge` or `other`, then group only the kept `knowledge` rows. 

The redesign I’d implement is:

## 1) Move final K/O authority later, but keep the same stage topology

Do **not** ask `recipe-boundary` / line-role to make strong final `KNOWLEDGE` calls for outside-recipe prose.

For outside-recipe material, I’d narrow the upstream contract to:

* `exclude_final_other`
* `send_to_knowledge_review`
* plus any clearly structural outside labels you truly need for later processing

That is, upstream can still kill obvious junk with high confidence, but it should stop pretending it already knows the final K/O answer for ambiguous prose.

Why I think this is the right move: in the current benchmark slice, almost all scored lines are outside active recipe spans, and the net improvement/regression is entirely attributed to `line_role`; the dominant residual errors are still `KNOWLEDGE -> OTHER` and `OTHER -> KNOWLEDGE`, and `KNOWLEDGE` is the worst-recall label. That is a strong signal that early stages are still exerting too much semantic force over the very boundary that later stages are supposed to own.   

The important nuance is this: I am **not** saying “skip non-recipe semantics.” I’m saying “make one stage the actual owner.”

## 2) Keep few long-running workers, but change the unit of work inside each shard

Your current design of “few workers, bigger chunk, long-running session” is fine. I would keep it.

But each worker should not make one blurry judgment over a giant contiguous prose shard. Instead, repo code should pre-split each shard into **micro-segments** before the worker starts labeling.

A micro-segment should be something like:

* 4–20 contiguous lines
* with heading context above
* maybe one preceding and following segment for context
* stable line ids / atomic ids
* upstream hints only as hints, not as hard labels

So the worker still owns a large shard and stays in one session, but it processes that shard as a sequence of small semantic windows.

That solves a big failure mode of long-running prose review: the model forms a local “this section is mostly knowledge” or “mostly memoir” threshold and then smears it across nearby mixed content.

Repo-owned artifact example:

`09_review_segments.jsonl`

Each row might look like:

```json
{
  "segment_id": "ks0027.seg014",
  "line_ids": [1014, 1015, 1016],
  "heading_context": ["Cooking Lessons", "Menus"],
  "prev_text": "...",
  "segment_text": "...",
  "next_text": "...",
  "upstream_flags": ["outside_recipe", "reviewable"],
  "provisional_surface_labels": ["OTHER", "OTHER", "OTHER"]
}
```

## 3) Make `knowledge-final` a three-phase worker loop, not a raw two-pass classify-then-group loop

Right now the doc says pass 1 classifies rows as `knowledge` or `other`, then pass 2 groups kept `knowledge` rows. I’d keep that spirit, but insert a semantic repair pass in the middle. 

### Phase A: keep/drop only

The worker labels each micro-segment line-by-line, but every `knowledge` keep must include two extra fields:

* `reason_code`
* `transferable_claim`

So a kept row is not just “knowledge.” It is “knowledge because it contains a reusable cooking rule / mechanism / definition / ingredient property / diagnostic.”

Example draft output:

```json
{
  "segment_id": "ks0027.seg014",
  "line_decisions": [
    {
      "line_id": 1015,
      "label": "KNOWLEDGE",
      "reason_code": "mechanism",
      "confidence": 0.82,
      "anchor_line_ids": [1015],
      "transferable_claim": "Menu planning works by locking one component and balancing the others around it."
    }
  ]
}
```

For `OTHER`, require a **drop reason** too:

* `memoir_scene_setting`
* `endorsement_marketing`
* `chapter_taxonomy`
* `decorative_heading`
* `front_matter`
* `publishing_legal`
* `page_furniture`
* `inspiration_without_transferable_claim`
* `anecdote_example_without_rule`

These are internal reasons, not public labels. They give the checker something semantic to inspect.

### Phase B: semantic audit and targeted patching

This is the key change.

Right now your loop is very good at structural validation. I’d add a repo-owned semantic checker that reads the draft labels and writes a file of suspicious cases only.

`09_knowledge_semantic_flags.jsonl`

Flag patterns like:

* first-person anecdote marked `KNOWLEDGE`
* praise / endorsement / quoted blurb marked `KNOWLEDGE`
* decorative heading marked `KNOWLEDGE`
* `KNOWLEDGE` row with no transferable claim
* long mixed segment with both narrative and technical content but only one blanket label
* low-confidence keep/drop decisions
* isolated single-line `KNOWLEDGE` sandwiched between obvious memoir
* repeated identical reason codes across a long run, suggesting threshold smear

Then the same long-running worker reads the flags and patches **only the flagged segments**.

This keeps the Codex-agent feel you want:

* it reads files,
* runs checks,
* fixes its own work,
* stays in one context window,
* but now the loop is improving semantics, not just schema compliance.

### Phase C: group only frozen knowledge rows

Only after labels are frozen do you run grouping.

That part of your current design is good. Keep it. The doc already says the group pass should only see kept knowledge rows. 

The important thing is to avoid letting grouping contaminate keep/drop. A worker that is simultaneously thinking “how do I organize this elegantly?” will over-keep borderline prose because it wants a coherent group.

## 4) Stop deterministic fallback from deciding semantic rows

Your plain-English note explicitly says rejected Codex labels in line-role fall back to deterministic baseline after validation. That is reasonable for many structural labels. It is a bad default for ambiguous semantic prose. 

So I’d split fallback policy in two:

* **structural rows**: deterministic fallback is fine
* **reviewable outside-recipe semantic rows**: no silent fallback to a final K/O answer

For reviewable semantic rows, use this instead:

* valid and accepted → freeze
* structurally invalid → repair
* semantically flagged → targeted re-ask
* still unresolved after patch loop → mark `semantic_unresolved`
* then one final conservative owner decides

That final conservative owner can still emit `OTHER` if needed for a closed-world output, but crucially that happens at the **knowledge-final owner stage**, not upstream.

This addresses a real current pressure point: the benchmark slice shows 695 explicit escalations, with 547 `deterministic_unresolved` and 350 `knowledge_review_excluded`. That is exactly the kind of profile where fallback mechanics can start acting like hidden semantics. 

## 5) Make the prompt benchmark-specific and much narrower

I would make the semantic prompt shorter, sharper, and more contrastive.

The core rule should be:

> Mark `KNOWLEDGE` only when the passage contains a transferable cooking claim that a reader could reuse later without depending on the surrounding memoir, praise, or book-structure context.

Then define the positive buckets:

* mechanism / causality
* definition / distinction
* ingredient property
* general technique principle
* diagnostic heuristic
* transferable planning principle

And the negative buckets:

* memoir / scene setting
* endorsements / blurbs
* chapter taxonomy / menu lists / further reading
* decorative headings
* inspiration / vibe without reusable claim
* narrative examples whose useful point is not explicit enough to stand alone

The strongest prompt examples should come from your own hard boundary cases, not generic cookbook prose. Your benchmark is clearly dominated by that K/O boundary, and the current confusion matrix shows the bidirectional failure plainly. 

## 6) Add an “anchor claim” requirement for every kept knowledge decision

This is probably the single highest-value change.

If the worker keeps something as `KNOWLEDGE`, it must point to the exact sentence or line span that carries the reusable claim.

No anchor, no keep.

That alone forces the worker away from:

* “this whole passage feels useful”
* and toward
* “this exact statement is the reusable cooking fact/principle”

It also gives you:

* better debugging,
* better semantic audit scripts,
* cleaner downstream knowledge grouping,
* and better reviewer-facing artifacts.

You already have a knowledge-group / snippet concept in the current system; this just moves the anchoring earlier and makes it part of the keep/drop contract. 

## 7) Narrow what counts as “obvious junk exclusion”

I would keep `nonrecipe-route`, but make its irreversible exclusions **narrower and more boring**.

Safe final exclusions:

* copyright / legal
* index
* page furniture
* publisher promos
* boilerplate navigation

Much less safe as irreversible exclusions:

* chapter headings
* menus
* “further reading”
* narrative blocks that may contain one reusable claim
* mixed technical/memoir prose

Why: your product promise is that outside-recipe prose matters. If you care about not losing useful information, then any exclusion category with nontrivial semantic ambiguity should probably stay reviewable and reach `knowledge-final`. The pipeline note already positions `knowledge-final` as the final semantic owner, so let it own the hard rows. 

## 8) Keep the same worker philosophy, but make the loop look like this

This is the concrete file-based loop I’d use.

### Repo writes

* `08_nonrecipe_seed_routing.json`
* `09_review_segments.jsonl`
* `09_worker_instructions.md`
* `09_label_schema.json`

### Worker pass 1 writes

* `09_knowledge_labels.draft.jsonl`

### Repo semantic checker writes

* `09_knowledge_semantic_flags.jsonl`

### Worker patch pass writes

* `09_knowledge_labels.patched.jsonl`

### Repo freeze step writes

* `09_knowledge_labels.final.jsonl`
* `09_nonrecipe_authority.json`

### Worker group pass writes

* `09_nonrecipe_knowledge_groups.json`

That keeps the Codex interaction style intact:

* long session,
* file IO,
* self-check,
* repair,
* multi-step reasoning,
* no fanout swarm.

## 9) Why this should help both quality and spend

I know spend is secondary, but this design should help both.

Right now the bundle says this benchmark slice is dominated by outside-span lines, all net movement is attributed to `line_role`, and the worst label recall is `KNOWLEDGE`. That means you are spending a lot of effort in places that are still not giving the final semantic owner a clean shot.  

This redesign cuts waste by:

* letting upstream stages be coarser and cheaper,
* reserving semantic effort for reviewable rows,
* making repair loops target only flagged cases,
* and ensuring grouping only happens after freeze.

So even if you do not optimize tokens yet, the extra tokens are now buying semantic resolution rather than protocol churn.

## 10) If I were implementing just one version first

I would do the smallest viable version of this:

1. Keep all current stages.
2. Change outside-recipe upstream outputs to mostly `exclude_final_other` vs `reviewable`.
3. In `knowledge-final`, require `reason_code + transferable_claim + anchor_line_ids` for every `KNOWLEDGE` keep.
4. Add one repo script: `check_knowledge_semantics.py`.
5. Patch only flagged rows.
6. Group after freeze.

That is the smallest redesign that still changes the actual failure mode.

The most important sentence in all of this is:

**Make `knowledge-final` the true owner of ambiguous outside-recipe semantics, and make every upstream step either routing or evidence-prep, not premature judgment.**

That stays inside your preferred architecture, and it fits the pipeline story in your plain-English doc. 

If you want, next I can turn this into a concrete spec with exact JSONL schemas and validator rules for the new K/O worker loop.
