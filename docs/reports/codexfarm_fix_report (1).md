# Report to the coding AI: how to fix the CodexFarm recipe-correction pipeline

## Executive summary

This benchmark does **not** primarily show a weak model. It shows a weak **problem framing and pipeline shape**.

Across the 3 comparable vanilla-vs-CodexFarm pairs, CodexFarm changed only **51 lines total**, with **31 fixes** and **10 new errors**. The per-book gains were tiny in *Salt, Fat, Acid, Heat* (**+0.002046** overall line accuracy) and *The Food Lab* (**+0.002125**), with one meaningful improvement only in *Sea and Smoke* (**+0.021849**). The ablation summary reports average gains of only **+0.008673 overall line accuracy** and **+0.024946 macro-F1 excluding OTHER**. 【16:13†upload_bundle_overview.md†L22-L29】【16:13†upload_bundle_overview.md†L82-L111】【17:17†upload_bundle_index.json†L18360-L18369】

At the same time, pass3 is consuming **19.67M / 28.66M total tokens** (**68.63%** of all tokens) and about **$16.28 / $31.79** estimated spend, yet the bundle’s blame summary says **pass3_mapping is net negative** while the real wins came from **line_role** and **routing_or_fallback**. 【16:13†upload_bundle_overview.md†L103-L111】【17:15†upload_bundle_index.json†L16100-L16172】

That combination means the current system is paying the most for the part that helps least.

The right conclusion is:

> Do not try to “make the model smarter” first.
> First, make the system stop asking the model to solve the wrong problem in the wrong mode on damaged inputs.

---

## What is actually going wrong

### 1. The model is not consistently being used as a clean structured-repair model

The prompt samples show reasoning traces like **“Checking for documentation scripts,” “Checking for documentation list command,”** and **“Trying to run docs list command / Trying bin/docs-list script.”** That is not recipe-repair reasoning. It is an agentic coding/tool-seeking mode leaking into a structured extraction task. 【16:18†prompt_type_samples_from_full_prompt_log.md†L2207-L2232】【16:18†prompt_type_samples_from_full_prompt_log.md†L2760-L2774】

**Cause:** the model is being run in a mode that behaves like a coding assistant rather than a pure structured-output normalizer.

**Effect:** attention gets spent on the runtime harness instead of the recipe object. The model is made to look “dumb” because the system puts it into a dumb posture.

**Fix:** for recipe correction, use a plain structured-output call with tools disabled, strict JSON output, deterministic settings, and a schema that makes invalid/empty outputs impossible to accept silently.

---

### 2. The model is often seeing partial or already-damaged evidence, not a full recipe

One prompt sample gives the extractor exactly one evidence row:

- `8 just-picked medium shiitake mushrooms (about 140 g)`

and explicitly says to use `evidence_rows` as the only authoritative recipe evidence. 【16:18†prompt_type_samples_from_full_prompt_log.md†L2239-L2267】

That is not “here is a recipe JSON, minimally fix the obvious mistakes.” That is “reconstruct something recipe-like from a shard.”

The regression packets show the same structural problem. For **30-MINUTE BLACK BEAN SOUP**, pass2 hard-degraded on `missing_instructions`, pass3 fell back, and the fallback reason is literally `pass2 degraded: missing_instructions`. 【16:14†upload_bundle_index.json†L887-L902】

For **Extra-Cheesy Grilled Cheese Sandwiches**, pass1 had heavy block loss, pass2 still routed into LLM pass3, and pass3 returned `mapping_count: 0` with `empty_mapping: true` while still reporting status `ok`. 【17:17†upload_bundle_index.json†L14956-L14999】

**Cause:** the pipeline is lossy. Upstream slicing, extraction, and bridging can remove or fragment the very evidence the downstream model would need to do the job correctly.

**Effect:** downstream stages are not repairing a recipe; they are trying to infer one from incomplete remnants.

**Fix:**

1. Add a hard **input sufficiency gate** before any LLM repair call.
2. If evidence is too sparse or structurally broken, **do not call the LLM yet**.
3. Either re-window, re-segment, or fall back to deterministic recovery.
4. Prefer one final repair pass over the **full contiguous candidate span + current draft JSON** rather than many narrow passes over degraded projections.

---

### 3. The pipeline gives the LLM ownership over labels that rules already handled better

Your own metrics show that some crisp labels got much worse once CodexFarm got involved:

- `TIME_LINE` F1 fell from **1.0** to **0.0** in the line-role pipeline stage. 【17:17†upload_bundle_index.json†L7838-L7850】
- `RECIPE_NOTES` F1 fell from about **0.6909** to about **0.0120**. 【17:17†upload_bundle_index.json†L7868-L7878】
- `INGREDIENT_LINE` F1 slipped from about **0.9501** to about **0.9302**. 【17:17†upload_bundle_index.json†L8165-L8175】

These are not the kinds of labels that should be handed to an LLM unless the rule system is genuinely weak. `TIME_LINE`, `YIELD_LINE`, many `INGREDIENT_LINE` cases, and a subset of `RECIPE_NOTES` are high-precision syntax/format problems.

**Cause:** the ownership boundary between deterministic parsing and LLM judgment is wrong.

**Effect:** the LLM “helpfully” rewrites or reclassifies cases that a rule-based system already solved with higher precision.

**Fix:** adopt strict ownership boundaries:

- **Deterministic-first:** `TIME_LINE`, `YIELD_LINE`, high-confidence `INGREDIENT_LINE`, section markers, obvious notes, and strong title veto logic.
- **LLM-only:** ambiguous semantic boundaries, noisy narrative-vs-recipe judgment, weakly signaled section grouping, and final minimal repair when enough context exists.

A good rule of thumb:

> If a label is mostly syntax, local format, or strong lexical patterning, the LLM should not own it.
> If a label is mostly semantic and context-sensitive, the LLM may own it.

---

### 4. The model is over-promoting titles and recipe structure out of surrounding prose

The confusion deltas show exactly the failure pattern:

- `OTHER -> RECIPE_TITLE`: **+7**
- `KNOWLEDGE -> RECIPE_TITLE`: **+5**
- `RECIPE_NOTES -> INSTRUCTION_LINE`: **+1** 【17:17†upload_bundle_index.json†L2475-L2518】

And the concrete examples are very revealing:

- `SCRAMBLED EGGS, TWO WAYS` was promoted to `RECIPE_TITLE` even though it appears immediately after a long frying instruction and right before narrative prose. 【17:17†upload_bundle_index.json†L14940-L14949】
- `CORN CHOWDER` was promoted to `RECIPE_TITLE` immediately after grilled-cheese serving instructions, followed by narrative discussion. 【17:17†upload_bundle_index.json†L15012-L15020】
- `SUMMER FLOWERS FROM THE FARM` was promoted to `RECIPE_TITLE` immediately after crab plating instructions, followed by memoir-style prose. 【17:17†upload_bundle_index.json†L15150-L15158】

These are not “model intelligence” failures. They are **context-window and title-veto failures**.

**Cause:** the system rewards local title-like cues without enough structural protection from surrounding prose, section headers, and chapter text.

**Effect:** the LLM creates confident, obvious-feeling errors that are especially frustrating to humans.

**Fix:** build deterministic **title vetoes** and **header rejection** into the structure pipeline.

At minimum, block `RECIPE_TITLE` promotion when:

- the previous line is clearly mid-instruction;
- the next line is long narrative prose;
- the candidate line is embedded inside surrounding memoir/knowledge context;
- the line resembles a section header, not a recipe boundary;
- the active candidate span already has a better-supported title.

---

### 5. The pipeline accepts structurally empty outputs as if they were usable outputs

An `LLM` stage returning `mapping_count = 0` and `empty_mapping = true` should be treated as a **failure**, not a successful pass. But the pipeline currently allows cases like that to flow through as `status: ok`. 【17:17†upload_bundle_index.json†L14956-L14999】

**Cause:** success/failure semantics are too shallow. “Valid JSON returned” is being treated as “useful recipe mapping produced.”

**Effect:** expensive calls can silently do no work while still consuming runtime, tokens, and trust.

**Fix:** define structural success invariants. For example:

- if pass3 is expected to map steps, `mapping_count == 0` is failure unless the recipe truly has zero mappable steps;
- `empty_mapping == true` is failure unless a clearly declared no-op mode was requested;
- missing title + missing steps + missing instructions is failure, not a draft.

The general principle is:

> A stage must be judged by whether it produced the minimum structure needed by the next stage, not by whether it emitted parseable JSON.

---

### 6. The benchmark results say the system is barely improving the part that matters most

For *The Food Lab*, CodexFarm changed **31 lines total**, but **inside the active recipe span it improved nothing at all**: both codex and vanilla were **428 / 686 correct**. The only gain was a tiny cleanup outside the active span (**696 vs 691**). 【17:17†upload_bundle_index.json†L2529-L2554】

At the same time, outside-span contamination is massive in the hard books:

- *The Food Lab*: **971** outside-span wrong lines, **31** changed lines total
- *Salt, Fat, Acid, Heat*: **603** outside-span wrong lines, **3** changed lines total
- *Sea and Smoke*: **27** outside-span wrong lines, **17** changed lines total 【17:10†upload_bundle_index.json†L18433-L18479】

This is why *Sea and Smoke* looks much better: the environment is cleaner, so the current pipeline’s weaknesses hurt less.

**Cause:** the system is not controlling recipe-span contamination well enough before it asks the LLM to reason.

**Effect:** the LLM spends effort inside a dirty search space and yields low leverage on messy books.

**Fix:** treat **recipe span quality** as the primary upstream problem. The LLM can repair a recipe; it cannot reliably repair a whole cookbook page that still contains recipe-adjacent prose, headers, and neighboring recipes.

---

### 7. Confidence gating alone is not the right lever

The bundle reports **`low_confidence_changed_lines_rows: 0`**. 【16:13†upload_bundle_overview.md†L88-L101】

That means the changed lines that matter were **not** the low-confidence lines.

**Cause:** the bad decisions are often high-confidence structural mistakes.

**Effect:** a simple “fallback when confidence < threshold” strategy will miss the actual failures.

**Fix:** do not rely on confidence gating alone. Add **structural gating**:

- insufficient evidence;
- title veto triggers;
- impossible span shapes;
- empty mapping;
- split-line artifacts;
- mid-sentence truncation;
- too many outside-span cues.

---

## The architectural fix

The cleanest redesign is this:

## New principle: the LLM should repair a recipe, not discover one from rubble

That implies four design rules.

### Rule 1: segmentation and structural validity are upstream responsibilities

Use deterministic logic and explicit guardrails to produce a candidate recipe span that is coherent enough to be worth repairing.

The LLM should not be the first entity to discover that a candidate contains:

- one ingredient row and no instructions,
- prose contamination,
- section headers posing as titles,
- split quantities,
- obvious line-fragment artifacts,
- or a neighboring recipe boundary leak.

### Rule 2: the LLM should operate on the fullest stable representation available

If you already have:

- the contiguous candidate span,
- the block/line indices,
- the draft JSON,
- and the raw evidence rows,

then the repair pass should see **all of them**.

Do not make the LLM reconstruct missing context from a smaller projection if the larger context already exists in memory or on disk.

### Rule 3: deterministic passes should own precise invariants

Rules should own:

- title vetoes,
- time/yield syntax,
- obviously broken line fragments,
- impossible mappings,
- success/failure criteria,
- and fallback routing.

LLMs should own:

- semantic cleanup,
- ambiguous span reconciliation,
- note-vs-instruction disambiguation when context is rich,
- and minimal recipe JSON repair.

### Rule 4: every fallback must be monotonic

A fallback should never erase recoverable information.

If a stage degrades, it should preserve:

- the best-known title,
- raw ingredient lines,
- raw instruction candidates,
- warning metadata,
- and the reason for degradation.

A fallback that collapses to “zero instructions” when imperative sentences still exist is not a safe fallback. It is a destructive one.

---

## Concrete implementation plan

## Phase 1: stop the bleeding

### A. Disable agentic/tool-seeking behavior for recipe correction

For passes involved in recipe extraction/repair:

- use plain structured output,
- disable tools,
- disable file-system or command discovery behavior,
- keep temperature low,
- and require schema-valid JSON.

This alone may produce a surprising gain because it stops the model from behaving like a coding agent during a parsing task. 【16:18†prompt_type_samples_from_full_prompt_log.md†L2207-L2232】【16:18†prompt_type_samples_from_full_prompt_log.md†L2760-L2774】

### B. Treat structurally empty outputs as failures

Add hard checks:

- `mapping_count == 0` when mappings are expected => failure
- `empty_mapping == true` => failure
- no title + no steps + no instructions => failure
- no-op output with warnings => failure or retry

Route these to deterministic retry/re-window or to a single direct repair pass over fuller context. 【17:17†upload_bundle_index.json†L14956-L14999】

### C. Add an input sufficiency gate before every LLM call

Never call the LLM if the evidence looks like:

- one ingredient line only,
- zero instructions with clear instruction-like source text nearby,
- mid-sentence splits,
- high page-layout artifact density,
- missing title + weak recipe anchors,
- or clear neighboring recipe contamination.

Instead, first repair the evidence object or re-segment. 【16:18†prompt_type_samples_from_full_prompt_log.md†L2239-L2267】【16:14†upload_bundle_index.json†L887-L902】

### D. Move crisp labels back to deterministic ownership

Immediately restore deterministic authority for:

- `TIME_LINE`
- `YIELD_LINE`
- high-confidence `INGREDIENT_LINE`
- strong `RECIPE_NOTES` patterns
- section-header / how-to markers

Use the LLM only to override these when there is unusually strong contrary evidence, and log every such override.

### E. Add title veto logic now

Implement a reusable `is_valid_recipe_title_candidate(...)` or equivalent gate that uses nearby context.

The veto should fire when a title-like line is sandwiched between:

- imperative instructions before it and narrative prose after it,
- narrative prose before and after,
- another already-valid recipe span,
- or explicit section-header cues.

This will likely eliminate a large fraction of the “obvious stupid” errors very quickly. 【17:17†upload_bundle_index.json†L14940-L14949】【17:17†upload_bundle_index.json†L15012-L15020】【17:17†upload_bundle_index.json†L15150-L15158】

---

## Phase 2: simplify the architecture

The best medium-term change is to reduce the number of lossy interfaces.

### Preferred design

Keep segmentation separate, but collapse downstream repair into one final pass:

1. Deterministic / guarded segmentation finds candidate span.
2. Deterministic cleanup normalizes obvious transport issues.
3. A single LLM repair pass sees:
   - raw span lines,
   - line indices,
   - current draft JSON,
   - warnings / uncertainty flags,
   - and outputs a minimally corrected recipe object.

This is much closer to the task strong models are good at.

### Less aggressive alternative

If you keep pass2 and pass3 separate, then pass3 must receive:

- the original raw evidence rows,
- the pass2 output,
- pass2 warnings,
- and enough neighboring context to repair pass2 mistakes.

Do **not** let pass3 operate on a narrow projection that hides the original evidence.

---

## Phase 3: make span quality a first-class optimization target

Add explicit metrics for:

- inside-active-span accuracy,
- outside-span contamination,
- title false positives,
- empty-mapping rate,
- fallback rate,
- instruction-drop rate,
- and structurally invalid-success rate.

Your benchmark already shows that *The Food Lab* saw no inside-span improvement despite overall changes. That should be a red warning in CI, not a detail hidden in the packet. 【17:17†upload_bundle_index.json†L2529-L2554】

Good routing decisions should optimize:

1. inside recipe correctness first,
2. destructive-failure avoidance second,
3. outside-span cleanup third,
4. cost and latency after that.

Not the other way around.

---

## Phase 4: tests and benchmark discipline

Build a fixed regression pack from the exact failure archetypes already visible here.

### Must-have regression cases

1. **Title overpromotion from instructions/prose**
   - `SCRAMBLED EGGS, TWO WAYS`
   - `CORN CHOWDER`
   - `SUMMER FLOWERS FROM THE FARM`

2. **Missing-instructions hard degradation**
   - `30-MINUTE BLACK BEAN SOUP`

3. **LLM empty mapping accepted as success**
   - `Extra-Cheesy Grilled Cheese Sandwiches`

4. **Solved labels getting unsolved**
   - `TIME_LINE`
   - `RECIPE_NOTES`
   - `INGREDIENT_LINE`

### Required invariants

Write tests so they fail before and pass after for these properties:

- a title candidate between instructions and prose cannot become `RECIPE_TITLE` without stronger structural support;
- `mapping_count == 0` cannot be `ok` when the recipe has extracted steps;
- `missing_instructions` cannot silently zero out the recipe if imperative instruction evidence still exists nearby;
- deterministic `TIME_LINE` / `YIELD_LINE` recognition cannot be overridden by a weaker LLM guess;
- LLM repair cannot run on clearly insufficient evidence;
- fallback must preserve best-known recoverable fields.

### Required ablations

Run these as separate benchmark switches so you can isolate causality:

1. current system baseline
2. agentic off / structured-output only
3. title veto + crisp-label deterministic overrides
4. empty-mapping hard failure
5. direct final repair pass over full span
6. direct final repair pass + deterministic crisp-label ownership

Do not batch too many changes together without an ablation, or you will not know which fix mattered.

---

## What not to do

Do **not** start by rewriting prompts at random.

Do **not** increase model size or cost until the task shape is repaired.

Do **not** let downstream LLM stages compensate for broken segmentation indefinitely.

Do **not** treat parseable JSON as success.

Do **not** optimize only overall accuracy. Track core recipe-span quality separately.

Do **not** hand the LLM labels that are mostly syntax and already solved by rules.

Do **not** use confidence thresholding as the main guardrail. Your bad changes are not concentrated in the low-confidence bucket. 【16:13†upload_bundle_overview.md†L88-L101】

---

## The simplest statement of the solution

If you remember only one thing, remember this:

> The system should first produce a **valid candidate recipe context** and only then ask the LLM to perform **minimal semantic repair**.

Right now it often does the reverse: it gives the LLM an incomplete or contaminated shard and implicitly asks it to reconstruct recipe structure while also obeying a brittle multi-pass contract.

That is why the results feel much worse than the base models should be.

---

## Final recommendation

If you need one immediate implementation bet, do this first:

1. turn off agentic/tool behavior for recipe passes;
2. add input sufficiency checks;
3. fail hard on `empty_mapping` / `mapping_count == 0`;
4. restore deterministic ownership of `TIME_LINE`, `YIELD_LINE`, high-confidence ingredients, and title-veto logic;
5. add one direct full-span minimal-repair pass.

That path is the highest-probability route to **better accuracy, lower cost, and much more human-sensible behavior**.
