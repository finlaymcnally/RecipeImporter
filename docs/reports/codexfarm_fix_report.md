# CodexFarm Fix Report

## Purpose

This report is for the coding AI working inside the codebase. You can inspect implementation details directly; this document is meant to give you the **right diagnosis frame**, the **highest-leverage fixes**, and the **acceptance criteria** that should govern the code changes.

Per user instruction, **ignore the known rejected/pending pass case as a root-cause target for now**. It still appears in the exported artifacts, so do not overfit the system to that one until the separate fix is landed.

---

## Executive summary

CodexFarm is a **real but modest net improvement** on the comparable pairs in this bundle. Across the 3 config-compatible CodexFarm-vs-Vanilla pairs, the run set shows **31 fixed error lines, 10 new error lines, and 21 fewer net errors overall**. The biggest win is **SeaAndSmoke** (+0.021849 overall line accuracy; +0.052941 macro F1 excluding OTHER). The other two comparable books improve only slightly.

Evidence:
- `upload_bundle_overview.md` L103-L118
- `upload_bundle_index.json` L18240-L18358

### What this means

Do **not** frame this as “the LLM is bad” or “the LLM is the whole answer.” The benchmark says something more specific:

1. The system is already extracting value from CodexFarm.
2. The gains are being partially canceled by a few concentrated failure modes.
3. The next win is more likely to come from **better control logic and validation** than from a blanket “use a bigger model everywhere” change.

The current system looks like a **hybrid pipeline with weak arbitration**: a strong lever exists, but it is not yet bounded by the right deterministic rules.

---

## What the benchmark actually says

### 1) The biggest behavior change is in the line-role stage

The stage-separated comparison shows very asymmetric label behavior:

- `RECIPE_TITLE` F1 improves from **0.2857 -> 0.6984**.
- `INSTRUCTION_LINE` F1 improves from **0.1224 -> 0.5833**.
- `RECIPE_VARIANT` and `KNOWLEDGE` also gain from near-zero baselines.
- But `RECIPE_NOTES` collapses from **0.6909 -> 0.0120**.
- `TIME_LINE` collapses from **1.0 -> 0.0**.
- `INGREDIENT_LINE` drops slightly from **0.9501 -> 0.9302**.

Evidence:
- `upload_bundle_index.json` L7838-L8135
- `upload_bundle_index.json` L2396-L2414

### 2) Title promotion is one of the clearest new-error families

The strongest confusion shifts show the model promoting non-title content into titles/variants:

- `OTHER -> RECIPE_TITLE`: +7
- `KNOWLEDGE -> RECIPE_TITLE`: +5
- `RECIPE_TITLE -> RECIPE_VARIANT`: +4

The changed-line packets show examples such as:
- `STICKY BUNS` outside any active recipe span
- `QUICK TOMATO SOUP WITH GRILLED CHEESE` outside any active recipe span
- `Boiling Water Under Cover` after `EXPERIMENT:`
- `SCRAMBLED EGGS, TWO WAYS` inside an active span but semantically functioning as a section/transition title
- `CORN CHOWDER` after the end of another recipe’s instruction stream
- `SUMMER FLOWERS FROM THE FARM` after recipe instructions, followed by narrative prose

Evidence:
- `upload_bundle_index.json` L7984-L8018
- `upload_bundle_index.json` L8043-L8073
- `upload_bundle_index.json` L15937-L16020
- `upload_bundle_index.json` L16036-L16062

### 3) Outside-span contamination is real and cross-book

All 3 books show outside-span signal. In particular:

- `thefoodlabCUTDOWN.epub`: 971 outside-span wrong lines vs 31 changed lines
- `saltfatacidheatCUTDOWN.epub`: 603 outside-span wrong lines vs 3 changed lines
- `SeaAndSmokeCUTDOWN.epub`: 27 outside-span wrong lines vs 17 changed lines

This does **not** mean all errors come from outside-span text, but it does mean the model is seeing enough noisy context that boundary mistakes can dominate localized decisions.

Evidence:
- `upload_bundle_overview.md` L74-L80
- `upload_bundle_index.json` L18429-L18482

### 4) Recovery/routing is a large source of net gain, but also brittle

The bundle-level blame summary says:

- `line_role`: net -9 errors
- `routing_or_fallback`: net -14 errors
- `pass3_mapping`: net +2 errors

That means routing/fallback is already doing useful work overall, but it is still introducing new errors in certain cases.

The cleanest brittle failure is `30-MINUTE BLACK BEAN SOUP`:
- `pass2_status = degraded`
- `degradation_reasons = [missing_instructions]`
- `promotion_policy = hard_fallback`
- `pass3_status = fallback`
- final stage also ends in fallback

Evidence:
- `upload_bundle_overview.md` L103-L111
- `upload_bundle_index.json` L3678-L3720

### 5) Pass3 is extremely expensive and not validated tightly enough

Call inventory summary:

- total tokens: **28,664,147**
- total estimated cost: **31.790373**
- pass3 tokens: **19,672,374**
- pass3 estimated cost: **16.283814**
- pass3 average latency: **175,658 ms**
- pass3 token share: **0.6863**

So pass3 accounts for roughly **69% of token volume** in this bundle.

At the same time, the slowest-call packet includes pass3 calls with suspicious outputs like:
- placeholder title: `Untitled Recipe`
- placeholder title based on workbook slug
- `mapping_count = 0` with nonzero `step_count`

Evidence:
- `upload_bundle_index.json` L16100-L16170
- `upload_bundle_index.json` L16326-L16474

### 6) Confidence thresholding is not catching the changed-line failures

The low-confidence changed-lines packet is empty:

- changed lines considered: 51
- matched prediction rows: 0
- row_count: 0
- note: no changed lines intersected low-confidence predictions below 0.90

So a simple “only review low-confidence lines” strategy is not targeting the current problem set.

Evidence:
- `upload_bundle_index.json` L16081-L16099

### 7) Attribution is directionally clear, but not perfectly isolated

Both `line_role_pipeline` and `llm_recipe_pipeline` changed together across the comparable pairs. The ablation rows therefore show the same aggregate deltas for both toggles. Do **not** overclaim exact stage attribution beyond what the stage-separated traces and per-label metrics support.

Evidence:
- `upload_bundle_index.json` L18360-L18428

---

## Diagnosis principles for the coding AI

Use these principles when choosing code changes:

### Principle A: Do not let one model own the entire decision surface

The current results strongly suggest that some labels should remain mostly deterministic unless the LLM has **strong positive evidence**.

### Principle B: Separate boundary decisions from semantic-label decisions

A title detector that is allowed to fire without span/boundary evidence will keep converting prose transitions and section headers into recipes.

### Principle C: Treat “suspicious success” as failure

If a stage returns structurally valid output but semantically impossible output (`mapping_count = 0`, placeholder title, etc.), that is not success. It is a repair trigger.

### Principle D: Prefer selective escalation over blanket model upgrades

The system currently spends too many tokens where logic/validation would be cheaper and safer.

### Principle E: Optimize for benchmark delta per unit of complexity

Do not start with a model swap. Start with the smallest code changes that directly target the measured failure buckets.

---

## Root cause 1: Title/variant over-promotion due to weak structural gating

### Cause hypothesis

The line-role stage appears to overvalue “title-like surface form” (short line, title case, all caps, headline feel) and undervalue stronger contextual evidence that the line is:
- outside any active recipe span,
- a section/transition header,
- an experiment/how-to header,
- or the beginning of narrative prose.

### Observable effect

Non-recipe or transition lines are promoted to `RECIPE_TITLE` or `RECIPE_VARIANT`, especially when they look title-like in isolation.

### Why it matters

This is not a cosmetic mistake. Once a line becomes a title, downstream stages inherit the wrong structure, which distorts extraction, routing, and span assumptions.

### Fix pattern

Implement **title/variant structural guardrails** and a **two-phase decision policy**:

1. **Span/boundary check first**
   - Is the line allowed to start a recipe/variant here?
2. **Semantic label choice second**
   - Only then consider `RECIPE_TITLE` / `RECIPE_VARIANT`.

### Concrete implementation guidance

Create a deterministic function (or equivalent policy layer) that rejects title promotion unless at least one of these is true:

- start-of-recipe boundary evidence exists
- neighboring lines contain recipe evidence (ingredient run, time/yield, imperative steps, title+variant pattern)
- the previous line is a known recipe boundary or section that allows recipe entry

And reject title promotion when any of these is true:

- line is outside active recipe span and followed by long-form prose rather than recipe structure
- previous line is an instruction sentence and current line is acting as a subtopic/transition
- local context matches experiment/how-to/essay framing
- line is a dangling heading that lacks downstream recipe evidence

### Pseudocode sketch

```python
if codex_label in {RECIPE_TITLE, RECIPE_VARIANT}:
    if not has_recipe_boundary_evidence(ctx):
        return baseline_label
    if looks_like_transition_or_essay_header(ctx):
        return baseline_label
    if outside_active_span(ctx) and not has_recipe_followers(ctx):
        return baseline_label
```

### Acceptance criteria

- Outside-span `OTHER -> RECIPE_TITLE` errors drop materially.
- The example lines in the changed-line packet stop promoting to titles.
- `RECIPE_TITLE` gains are preserved on true recipe titles.

### Evidence

- `upload_bundle_index.json` L7984-L8018
- `upload_bundle_index.json` L8043-L8073
- `upload_bundle_index.json` L15937-L16020
- `upload_bundle_index.json` L16036-L16062

---

## Root cause 2: The line-role stage is helping the right labels but harming the wrong ones

### Cause hypothesis

The new line-role pipeline is not uniformly better. It appears to have stronger recall on recipe structure labels (`RECIPE_TITLE`, `INSTRUCTION_LINE`) but very poor calibration on `RECIPE_NOTES` and `TIME_LINE`, and a mild precision loss on `INGREDIENT_LINE`.

This is classic **asymmetric model benefit**: one component is good enough to help some classes and bad enough to hurt others.

### Observable effect

The system wins on recipes with weak baseline title/instruction detection, while regressing on notes/time-heavy or mixed-context content.

### Fix pattern

Add a **label-aware arbitration layer** between Vanilla and CodexFarm outputs.

Initial policy recommendation:

- Prefer **CodexFarm** on:
  - `RECIPE_TITLE`
  - `RECIPE_VARIANT`
  - `INSTRUCTION_LINE`
  - likely `KNOWLEDGE` (with context gates)
- Prefer **Vanilla** on:
  - `TIME_LINE`
  - `RECIPE_NOTES`
- Decide case-by-case on:
  - `INGREDIENT_LINE`
  - `OTHER`

This is not the final policy; it is the right **first control policy** because it directly mirrors the measured label asymmetry.

### Concrete implementation guidance

Build an arbiter with access to:
- baseline label
- CodexFarm label
- local text/context features
- active span status
- optional candidate-label set if available

Do **not** make the arbiter generic at first. Start with explicit high-value disagreement rules.

Example:

```python
def arbitrate(baseline, codex, ctx):
    if baseline == codex:
        return codex

    if baseline == TIME_LINE and codex != TIME_LINE:
        if not strong_non_time_evidence(ctx):
            return baseline

    if baseline == RECIPE_NOTES and codex == INSTRUCTION_LINE:
        if looks_like_note_or_advice(ctx):
            return baseline

    if codex == INSTRUCTION_LINE and looks_like_imperative_step(ctx):
        return codex

    if codex in {RECIPE_TITLE, RECIPE_VARIANT}:
        return apply_title_guardrails(baseline, codex, ctx)

    return codex
```

### Acceptance criteria

- `RECIPE_NOTES` no longer collapses.
- `TIME_LINE` is restored close to baseline performance.
- `INSTRUCTION_LINE` and `RECIPE_TITLE` gains remain mostly intact.

### Evidence

- `upload_bundle_index.json` L7838-L8135
- `upload_bundle_index.json` L2139-L2232
- `upload_bundle_index.json` L2282-L2414

---

## Root cause 3: Pass2 failure handling is too brittle

### Cause hypothesis

The routing logic treats certain pass2 degradations as immediate hard fallbacks, even when a targeted repair attempt could recover usable structure.

### Observable effect

`30-MINUTE BLACK BEAN SOUP` demonstrates the exact failure shape:
- pass2 finds no instructions,
- marks the stage as degraded,
- forces fallback,
- and never gets a recovery attempt.

### Why it matters

This kind of failure is low-hanging fruit because it is not a hard semantic impossibility. It is a recoverable extraction miss.

### Fix pattern

Replace one-shot hard fallback with a **repair ladder**.

Recommended ladder:

1. Detect specific degradation reason (`missing_instructions`, etc.).
2. Retry pass2 once with a wider or shifted window.
3. Retry once with a more literal extraction mode/prompt.
4. If still broken, do **partial fallback**, preserving any high-confidence upstream structure rather than throwing the whole route away.

### Concrete implementation guidance

Add a degradation policy table:

```python
if 'missing_instructions' in degradation_reasons:
    attempt_repair('wider_context')
    if repaired:
        continue_pipeline()

    attempt_repair('literal_instruction_extraction')
    if repaired:
        continue_pipeline()

    return partial_fallback_preserving_safe_labels()
```

Also, ensure fallback is **localized**:
- preserve known-good line-role labels where possible
- do not reset recipe structure more broadly than necessary

### Acceptance criteria

- The `30-MINUTE BLACK BEAN SOUP` pattern no longer falls directly from pass2 degradation into unrepaired fallback.
- Routing/fallback keeps its net benefits while reducing new-error introductions.

### Evidence

- `upload_bundle_overview.md` L103-L111
- `upload_bundle_index.json` L3678-L3720

---

## Root cause 4: Pass3 needs validation before it needs a bigger model

### Cause hypothesis

Pass3 is being allowed to complete with outputs that are syntactically acceptable but operationally suspicious:
- `mapping_count = 0`
- placeholder title text
- title derived from workbook slug
- nonzero steps with no useful mapping

### Observable effect

The system spends a huge amount of latency and token budget on pass3, but some of the most expensive calls still produce outputs that should have triggered repair logic.

### Why it matters

A blanket pass3 model upgrade is likely to be expensive and only partially effective. Validation should come first, escalation second.

### Fix pattern

Implement a **pass3 validator** that marks outputs as `repair_needed` when any of the following are true:

- `mapping_count == 0`
- placeholder title text is present
- title falls back to workbook slug or generic placeholder
- step count is nonzero but mapping coverage is empty or below threshold
- structured output violates cross-field invariants

Then use **selective escalation**:
- rerun only flagged cases
- preferably with stricter schema / stronger instructions
- optionally with a better model only on those flagged cases

### Concrete implementation guidance

Add explicit outcome classes:
- `ok`
- `repair_needed`
- `fallback_required`

Example:

```python
bad_mapping = (
    mapping_count == 0
    or title_is_placeholder(output)
    or title_uses_workbook_slug(output)
    or (step_count > 0 and mapping_coverage_ratio(output) == 0)
)

if bad_mapping:
    return repair_needed
```

Then:

```python
if pass3_outcome == repair_needed:
    rerun_pass3(strict_schema=True, stronger_guardrails=True)
    if still_bad and case_is_high_value:
        rerun_pass3(model='stronger_model')
```

### Acceptance criteria

- Placeholder-title outputs do not survive as successful pass3 completions.
- `mapping_count = 0` outcomes become rare among final accepted pass3 results.
- Pass3 token spend drops or becomes concentrated on genuinely hard cases.

### Evidence

- `upload_bundle_index.json` L16100-L16170
- `upload_bundle_index.json` L16326-L16474
- `upload_bundle_index.json` L14953-L15022

---

## Root cause 5: The current review trigger should be disagreement-driven, not confidence-driven

### Cause hypothesis

The bad cases are not sitting in the low-confidence tail. They are sitting in **specific disagreement patterns** and **specific structural contexts**.

### Observable effect

The low-confidence changed-lines packet contains zero rows, despite 51 changed lines overall.

### Fix pattern

Trigger verification/review on **risky disagreement types**, not just on low confidence.

Best initial risky disagreements:
- `OTHER <-> RECIPE_TITLE`
- `KNOWLEDGE <-> RECIPE_TITLE`
- `RECIPE_TITLE <-> RECIPE_VARIANT`
- `RECIPE_NOTES <-> INSTRUCTION_LINE`
- `TIME_LINE` disagreements when Vanilla says `TIME_LINE`

### Concrete implementation guidance

This verifier can be deterministic first, LLM-backed second.

1. Check disagreement pattern.
2. Check span status and local context features.
3. Only invoke LLM verifier when deterministic checks cannot resolve.

### Acceptance criteria

- The verifier catches the dominant new-error families without adding large new cost.
- The low-confidence packet remaining empty no longer matters operationally.

### Evidence

- `upload_bundle_index.json` L16081-L16099
- `upload_bundle_index.json` L7984-L8018
- `upload_bundle_index.json` L8043-L8073

---

## Diagnostic priority: audit context/projection instrumentation before trusting every trace metric

Some of the top regression packets show suspicious telemetry patterns such as:
- `selected_block_count > 0`
- `missing_block_count_vs_pass2 > 0`
- `pass2 input_block_count = 0`
- yet pass2 still reports extracted instructions/ingredients

Example packets:
- `EXTRA-CRISPY SUNNY-SIDE-UP EGGS`
- `Extra-Cheesy Grilled Cheese Sandwiches`

This could indicate one of two things:
1. a real context-transfer/projection bug, or
2. a telemetry/reporting mismatch in how block counts are recorded.

Do not assume which one it is without checking code. But **do** audit it, because if the instrumentation is lying, it weakens every later diagnosis; and if it is real, it is a high-leverage deterministic bug.

Evidence:
- `upload_bundle_index.json` L14885-L14929
- `upload_bundle_index.json` L14953-L15000

---

## Recommended implementation order

### First wave: high-leverage, low-risk

1. Add title/variant structural guardrails.
2. Add label-aware arbitration, especially preserving Vanilla for `TIME_LINE` and `RECIPE_NOTES`.
3. Change pass2 degradation handling from hard fallback to repair ladder.
4. Add pass3 validator + repair-needed state.

This wave should deliver most of the likely benchmark gain.

### Second wave: selective LLM upgrades

5. Upgrade pass3 model only for validator-flagged cases.
6. Optionally add a lightweight disagreement verifier for risky label flips.

### Third wave: deeper cleanup

7. Audit context-transfer/projection telemetry.
8. Improve prompt/schema design only after guardrails and validation are in place.

---

## What not to do

### Do not do a blanket “bigger model everywhere” upgrade first

The current benchmark does not justify that as the first move. It is too expensive and insufficiently targeted.

### Do not rely on confidence thresholding as the main defense

The exported low-confidence changed-lines packet says that strategy misses the current failure set.

### Do not let pass3 silently succeed with empty or placeholder outputs

That is the most obvious missing validator.

### Do not treat title detection as purely semantic

It is a structural decision and must be gated by boundary evidence.

### Do not overfit to the known pending/rejected case

That one is already being fixed separately.

---

## Benchmark-facing acceptance checklist

A good patch should satisfy most of the following:

1. Preserve the current gains in `RECIPE_TITLE` and `INSTRUCTION_LINE`.
2. Restore `RECIPE_NOTES` and `TIME_LINE` close to baseline.
3. Reduce `OTHER -> RECIPE_TITLE` promotions, especially outside active spans.
4. Reduce forced fallback on recoverable pass2 degradations.
5. Prevent pass3 placeholder/empty-mapping results from being accepted without repair.
6. Improve net error delta without materially increasing pass3 cost.

If there is a tradeoff, prefer:
- fewer false titles,
- fewer forced fallbacks,
- and cheaper selective LLM use

over small gains from unconstrained pass3 expansion.

---

## Bottom line

The right mental model is:

> **CodexFarm is not failing because it is too weak. It is failing because it is insufficiently constrained and insufficiently validated.**

The next big win is to make the hybrid pipeline behave like a disciplined system:
- deterministic where precision matters,
- LLM-assisted where ambiguity is real,
- validator-enforced where outputs can be deceptively plausible,
- and span-aware everywhere.

That is the path most likely to turn the current modest net gain into a clear one.
