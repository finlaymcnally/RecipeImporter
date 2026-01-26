---
summary: "Spoon-fed guide to tuning tip/knowledge extraction (thresholds, headers, and narrative filtering)."
read_when:
  - When tuning tip/knowledge extraction or investigating narrative tips
---

# Tip/Knowledge Tuning Guide (Spoon-Fed)

This guide tells you exactly where to tweak tip parsing, what each knob does, and how to iterate safely. It focuses on the deterministic (non-LLM) parser in `cookimport/parsing/tips.py`.

## 0) Quick mental model (one minute)

Tip extraction works like this:

1) Text is split into blocks and sentences.
2) Each sentence (or block) gets a **tipness score** based on advice cues, verbs, and headers.
3) Sentences that look tip-like become candidates.
4) Each candidate is classified as **general**, **recipe_specific**, or **not_tip**.
5) Only **general + standalone** tips are written to `data/output/.../tips/...`, along with `tips.md` (a summary list that includes `t{index}` ids, anchor tags, any detected topic headers, and groups tips from the same source block).
6) Topic candidates are written as `topic_candidates.json` and `topic_candidates.md` in the same tips folder; these are raw topic chunks meant for evaluation/LLM prefiltering. See `docs/Tip_Evaluation_Harness.md` for the labeling workflow.

If you see narrative snippets in tips, it means the **tipness or generality gate is too permissive** for standalone blocks.

## 1) Where to tweak (filepaths)

Core behavior lives in:

- `cookimport/parsing/tips.py`
  - Tip detection and classification logic.
  - All thresholds, regexes, and heuristics.

Supporting behavior lives in:

- `cookimport/parsing/patterns.py`
  - Imperative verb list used by `signals.classify_block`.
- `cookimport/parsing/signals.py`
  - Block-level signals (imperative verbs, instruction likelihood, etc.).
- `cookimport/plugins/epub.py`
  - Standalone block extraction for EPUBs (source of many narrative tips).

Overrides (per cookbook) are loaded from:

- `cookimport/cli.py` (uses `.overrides.yaml` or `--overrides`)
- `cookimport/core/models.py` (`ParsingOverrides` schema)

## 2) The “safe knobs” (no code changes)

Use **overrides** to add or strengthen tip cues for a specific cookbook.

### 2.1 Create an overrides file

Create `data/input/thefoodlab.overrides.yaml` (or any name you pass to `--overrides`).

Example:

```
# data/input/thefoodlab.overrides.yaml
name: "thefoodlab"
tipHeaders:
  - "science"
  - "kitchen note"
  - "food lab tip"
  - "troubleshooting"
  - "equipment"
tipPrefixes:
  - "food lab tip"
imperativeVerbs:
  - "rest"
  - "temper"
  - "brown"
```

### 2.2 Run with overrides

```
python -m cookimport stage data/input/thefoodlab.epub --out data/output --overrides data/input/thefoodlab.overrides.yaml
```

**What this does:**
- Adds new “tip header” labels so the parser treats those blocks as tip callouts.
- Adds new imperative verbs so tips with those verbs score higher.

## 3) The “precision knobs” (code changes)

These are the **exact places** to change when output is still narrative.

### 3.1 Raise the minimum length for general tips

File: `cookimport/parsing/tips.py`

```
_MIN_GENERAL_WORDS = 12
```

**If you see short narrative snippets,** increase this to `14` or `16`.

### 3.2 Tighten standalone tip acceptance

File: `cookimport/parsing/tips.py`, inside `_judge_tip`:

```
threshold = 0.45
if source_section == "standalone_block" and tip_prefix_strength is None:
    threshold = 0.55
```

**If you see narrative tips from standalone blocks,** raise `0.55` to `0.65`.

### 3.3 Require stronger advice anchors

File: `cookimport/parsing/tips.py`, function `_explicit_tip_signal`.

Currently, explicit advice is true if **any** of these are present:

- Strong tip header/prefix
- Strong advice modal (`should`, `must`, `important`, etc.)
- Strong imperative (`Salt`, `Rest`, `Preheat`, etc.)
- Permissive guidance (`You can ...`, `Feel free to ...`)
- Diagnostic cue (`you’ll know when...`)
- Benefit cue (`makes it better`, `for best results`, etc.)

If narrative is still leaking, **remove** weaker cues from `_explicit_tip_signal`, like `_BENEFIT_CUE_RE`, so only imperatives and strong advice remain.

Note: the parser also treats **explanation cues** (e.g., “because”, “in order to”) as advice anchors for long, cooking‑anchored standalone tips. If that inflates output, remove `_EXPLANATION_CUE_RE` from `_explicit_tip_signal`.

### 3.4 Require cooking anchors for standalone tips

File: `cookimport/parsing/tips.py`, function `_has_cooking_anchor` and the standalone gate in `_judge_tip`.

Standalone tips now require at least one cooking anchor (dish/ingredient/technique/tool/cooking method, or a cooking keyword like “cook”/“bake”/“salt”). If science narration still leaks, tighten the anchor regex or add more anchor terms to `tip_taxonomy.py` so only real cooking concepts pass.

### 3.5 Topic chunking (merge adjacent paragraphs)

File: `cookimport/parsing/tips.py`, function `chunk_standalone_blocks`, used by `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`.

Standalone blocks are now merged into **topic chunks** based on header cues and anchor overlap, so short consecutive tips (like cast‑iron care or stand‑mixer checklists) get grouped into longer text before extraction. If you want **more merging**, loosen the anchor overlap break in `chunk_standalone_blocks` or treat more lines as headers via `_is_topic_header`. If you want **less merging**, make the break conditions stricter.

### 3.6 Expand narrative rejection

File: `cookimport/parsing/tips.py`, regexes near the top:

- `_NARRATIVE_RE`
- `_FIRST_PERSON_RE`

Add patterns like:

```
"in my experience", "I’ve found", "I learned", "I used to"
```

Then narrative sentences will be rejected unless paired with explicit advice language.

### 3.7 Penalize narrative harder

File: `cookimport/parsing/tips.py`, function `_tipness_score`:

```
if _is_narrative_like(stripped) and not _STRONG_ADVICE_RE.search(stripped):
    score -= 0.35
```

**If narrative tips still leak**, make the penalty stronger, like `-0.5`.

### 3.8 Expand concept tagging (ingredients/techniques/tools/dishes)

File: `cookimport/parsing/tip_taxonomy.py`

This file controls which words get tagged as dishes, ingredients, techniques, cooking methods, tools, etc. Add or expand terms here if you want tips to attach to more concepts (for example, add `"hamburger"` under dishes or `"debone"` under techniques).

## 4) The “recall knobs” (if you lose too many tips)

If tips almost disappear after tightening:

1) Lower `_MIN_GENERAL_WORDS` back to `10`.
2) Lower the standalone threshold back to `0.55`.
3) Add more tip headers/prefixes in overrides.
4) Expand `_STRONG_IMPERATIVE_RE` to include more verbs.

## 5) EPUB-specific choke point (big impact)

Many narrative tips come from **standalone EPUB blocks**.

File: `cookimport/plugins/epub.py`, function `_extract_standalone_tips`.

It currently sends **every** non-recipe block to the tip parser. If you want a big precision jump, add a **pre-filter** there (for example, only pass blocks with `Tip:` or `Note:` prefixes, or blocks that contain advice cues). That’s the fastest way to reduce narrative leakage in EPUBs.

## 6) Practical tuning recipe (step-by-step)

1) Run a stage pass and check the report:
   - `data/output/<timestamp>/<workbook>.excel_import_report.json`
   - Look at `tipSamples` and `totalNotTips` vs `totalTips`.

2) If tips are narrative:
   - Raise `_MIN_GENERAL_WORDS` to `16`.
   - Raise standalone threshold `0.55 → 0.65`.
   - Add more narrative phrases to `_NARRATIVE_RE`.

3) Re-run `cookimport stage` and compare samples.

4) If too few tips remain:
   - Add tip headers in overrides.
   - Loosen thresholds slightly.

## 7) Quick reference: exact knobs

All in `cookimport/parsing/tips.py`:

- `_MIN_GENERAL_WORDS` (minimum length for general tips)
- `_TIP_ACTION_RE`, `_STRONG_IMPERATIVE_RE` (imperative verbs)
- `_ADVICE_CUE_RE`, `_STRONG_ADVICE_RE`, `_BENEFIT_CUE_RE` (advice/benefit cues)
- `_NARRATIVE_RE`, `_FIRST_PERSON_RE` (narrative filtering)
- `_tipness_score` weights and penalties
- `_judge_tip` thresholds and generality gating
- `_explicit_tip_signal` (what counts as “strong advice”)

## 8) If you want help tuning for this specific book

Tell me:

- 5–10 bad tips that are still leaking (paste the `text` fields).
- 5–10 good tips you wish were included.

I can then tune the regexes + thresholds to target that style of writing.
