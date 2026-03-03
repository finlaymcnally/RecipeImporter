# response 1

Yes. The biggest gap is that the bundle is **good at showing aggregate symptoms**, but **bad at showing exact Codex-vs-vanilla causality**.

Right now the cutdown keeps many overlapping sampled artifacts at 80 rows each, and the Codex prompt log is only a deterministic sample of **3 pairs per pass** across `pass1`, `pass2`, and `pass3`, for 9 sampled pairs total out of 39/39/37 pairable blocks. The root comparison also only shows the aggregate metric delta and a very small config diff (`llm_recipe_pipeline` plus config hash).

What I’d add first:

* **A single `changed_lines.codex_vs_vanilla.jsonl` file.**
  This would be the highest-value artifact by far. For each line where Codex and vanilla differ, include: `line_index`, `recipe_id`, `gold_label`, `vanilla_pred`, `codex_pred`, and a small context window like previous/current/next line. Right now I can see the aggregate delta, but not the *specific flips* that produced it.

* **Per-recipe or per-span breakdowns.**
  I want metrics split by `recipe_id`, and ideally by region like “inside active recipe span” vs “outside active recipe span / knowledge / front matter.” The current comparison is global, but the prompt log shows Codex is operating on recipe bundles, while the eval is canonical line classification, so slice-level behavior matters a lot.

* **A full confusion matrix and a delta confusion matrix.**
  The current cutdown keeps only top confusions/top labels, which is useful for a quick skim but not enough for root-cause work. A delta confusion matrix would immediately show whether Codex mostly converts `INGREDIENT_LINE -> YIELD_LINE` into something else, or just shifts errors into `KNOWLEDGE`. The current process manifest explicitly truncates to `top_confusions: 8` and `top_labels: 6`.

* **Prompt-warning aggregates, not just sampled examples.**
  The sampled prompt log is already telling us something important: some source blocks collapse **yield + ingredients + method heading** into one line, and other blocks collapse **servings + ingredient list** into one evidence line with inferred boundaries. That is extremely diagnostic, but I need counts across the whole run, not just a few examples.

* **A projection trace from Codex output back to benchmark labels.**
  The prompt log shows a pass structure around recipe detection/extraction/draft-building, and one sampled `pass3` output has an empty `ingredient_step_mapping: {}`. That strongly suggests a missing or weak bridge from extracted recipe structure back to canonical line labels. A trace file explaining that bridge would help more than more random samples.

* **Label policy / adjudication notes.**
  A tiny file with the gold-label rules for edge cases like `RECIPE_TITLE` vs `RECIPE_VARIANT`, `RECIPE_NOTES` vs `KNOWLEDGE`, and heading-like instruction lines would help a lot. Right now the samples expose disagreements, but not the labeling standard that resolves them.

What I’d remove or shrink:

* **`correct_label_lines.sample.jsonl`**
  This is low-value for diagnosis. In vanilla it samples 80 rows out of 941 correct candidates, and in Codex it samples 80 out of 1032. Those tokens mostly prove that many easy cases are fine, which is not where the mystery is.

* **Either line-level or block-level error files, not both.**
  Because the eval is `canonical_text_classification`, I would keep the **line-level** artifacts and drop `wrong_label_blocks.sample.jsonl` and `missed_gold_blocks.sample.jsonl`. Right now the cutdown keeps both line and block variants for the same failure families, which is redundant.

* **`false_positive_preds.sample.jsonl` as a separate artifact.**
  I’d merge this into the line-diff file. In practice it overlaps heavily with the wrong-label views, so it is usually more duplication than insight.

* **Most alignment artifacts in healthy runs.**
  On the Codex run, alignment already looks strong: canonical char coverage is about **0.9943** and prediction block match ratio about **0.9970**. Also, `alignment_gaps.sample.jsonl` is zero-row in the cutdown. That means large `aligned_prediction_blocks.sample.jsonl` dumps are probably not where your tokens should go unless a future run has bad coverage.

* **`unmatched_pred_blocks.sample.jsonl` should become counts-only by default.**
  In vanilla it is tiny—5 total rows—and only becomes interesting if unmatched coverage spikes or the unmatched blocks are materially different between runs.

* **Random prompt samples from all three passes.**
  Keep a prompt artifact, but make it **targeted**, not uniform. The current scheme samples 3 from `pass1`, 3 from `pass2`, 3 from `pass3`. I’d rather have 10 handpicked or rule-picked examples tied to dominant confusions or largest Codex-vs-vanilla flips. That would be much higher signal per token.

If you want the best token/insight ratio, I’d package this instead:

* `comparison_summary.json`
* `need_to_know_summary.json` for vanilla
* `need_to_know_summary.json` for codex
* **new:** `changed_lines.codex_vs_vanilla.jsonl`
* **new:** `per_recipe_or_per_span_breakdown.json`
* **new:** `prompt_warning_aggregate.json`
* **new:** `targeted_prompt_cases.md` with ~10 failure-focused examples

That would be **more diagnostic than the current bundle while using fewer tokens**.

# response 2
The biggest upgrade would be: **include the exact prompts and richer error context; drop duplicated “same story twice” artifacts.**
Right now the cutdown explicitly caps prompt examples to **3 pairs per pass**, **80 sampled rows**, and **440-char excerpts**, and the CodexFarm prompt file is only a **sampled view** of a larger `prompt_request_response_log.txt`. That is enough to spot patterns, but not enough to audit prompt wording or trace brittle cases reliably.

What would help me diagnose much better:

* **The literal prompt templates for each pass.**
  I want the exact system/instruction text, allowed label/schema instructions, few-shot examples, and any retry/repair prompts. The current bundle only shows sampled prompt I/O pairs from a larger source log, not the full prompt contract.

* **A context-rich error export.**
  Instead of only `line_text_excerpt`, include `prev_line`, `line`, `next_line`, plus `block_id` / `block_index` / source span. Many of your hard cases are ambiguous in isolation, and the current bundle intentionally truncates excerpts to 440 chars and samples only 80 rows.

* **The actual gold label file and label definitions, not just paths to them.**
  Both runs point to `canonical_text.txt` and `canonical_span_labels.jsonl`, but the bundle mostly gives me the paths, not the actual gold labels or the label ontology/precedence rules. That would help a lot for diagnosing title vs variant vs section-header mistakes and any downstream label remapping.

* **Per-line provenance from source block → pass2/pass3 output → final predicted line label.**
  This is the most diagnostic missing link. In the CodexFarm sample, block `b799` is already a fused line containing yield + ingredients + a method heading, and pass2/pass3 preserve that whole fused string as one `recipeIngredient`. That tells me the pipeline is inheriting a lossy input representation. More of that provenance would be extremely valuable.

* **A head-to-head disagreement file for vanilla vs CodexFarm.**
  The root comparison summary is useful, but it only shows deltas and config-hash differences. A file like `disagreement_lines.jsonl` with `gold`, `vanilla_pred`, `codex_pred`, and local context would be much more useful than separately skimming two sampled error files.

* **More targeted prompt examples, not just arbitrary sampled ones.**
  Since prompt pairs are capped, the sampled examples should be chosen from the biggest failure buckets, not random recipe snippets. The current process manifest says only 3 prompt pairs per category are included, so every one of those should hit a known failure mode.

What is lower value and could be trimmed to save tokens:

* **Duplicate line/block artifacts, if they are not materially different.**
  In the vanilla sample counts, `wrong_label_lines` and `wrong_label_blocks` have the same totals, and `missed_gold_lines` / `missed_gold_blocks` do too. If the block file is just another view of the same error rows, I would keep only one of each.

* **Most of `correct_label_lines.sample.jsonl`.**
  A small stratified set of correct examples is useful, but 80 sampled correct rows is not where the tokens buy much. I would keep maybe 3–5 correct examples per label and spend the rest on hard negatives.

* **Alignment artifacts when alignment is clearly fine.**
  In these bundles, `alignment_gaps.sample.jsonl` is empty, and vanilla only has 5 unmatched prediction blocks. Unless you are actively debugging alignment, these can be omitted or reduced to a 1-line summary.

* **Large `aligned_prediction_blocks` samples.**
  They are expensive and mostly useful when alignment is broken. If alignment is healthy, I would keep only unmatched or suspiciously merged blocks, not a broad aligned sample.

* **Repeated metadata in every flattened file.**
  Once the root `comparison_summary` / `process_manifest` are present, the repeated run-level provenance and file lists inside each flattened markdown are much less valuable than extra error context or full prompt text.

If I were optimizing the bundle for **maximum diagnostic value per token**, I would send this:

1. `comparison_summary.json`
2. one per-run summary (`need_to_know_summary.json`)
3. the **full prompt template(s)** or full `prompt_request_response_log.txt`
4. `wrong_label_with_context.jsonl` for 100–200 rows, stratified by confusion bucket
5. filtered `canonical_span_labels.jsonl` for those same rows
6. 10–20 provenance traces showing source block(s) → pass2/pass3 → final line label

That would cut a lot of bulk while making prompt and pipeline failures much easier to diagnose.

# response 3
I’m basing this on the current `vanilla`, `codexfarm`, and benchmark summary dumps.   

The big picture: **the dump is spending tokens on many sampled views, but it still omits the few artifacts that would most improve diagnosis**. Right now every JSONL artifact is capped at **80 sampled rows** with **440-character excerpts**, and the CodexFarm prompt log is only a **sampled** view with **max 3 pairs per category**. The codexfarm dump even says that sampled file came from a larger `prompt_request_response_log.txt`.

## Highest-value additions

* **1) Full prompt/request log for every LLM call.**
  This is the single most valuable addition. Right now the prompt artifact is still only a sample: max 3 pairs per pass/category, 9 sampled pairs total, even though the source full log exists. Without the full rendered request/response for every pass1/pass2/pass3 call, prompt diagnosis stays partly guesswork.

* **2) Preprocessor trace: raw extracted lines before `semantic_v1`, plus the post-preprocess blocks actually sent downstream.**
  The current run config says the pipeline uses `epub_unstructured_preprocess_mode: "semantic_v1"`. The sampled CodexFarm traces show why this matters: pass2 is sometimes receiving a single block that already fuses **yield + ingredients + method heading**, like the hollandaise block containing `MAKES ABOUT 1 CUP ... Kosher salt TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER`. Other pass2 warnings explicitly say serving text and ingredient lists were not line-separated, so boundaries were inferred. That means some ambiguity is upstream of the LLM prompt itself.

* **3) Full provenance for each bad prediction.**
  For each wrong line, I’d want one row with: gold line id, canonical char span, source block ids, pass1 selected span, pass2 `field_evidence`, and the final emitted label. The sampled pass3 outputs already show `ingredient_step_mapping` is `{}`, and even step objects can have empty `ingredient_lines`, which is exactly the kind of provenance failure you’d want to inspect across *all* bad cases, not just 3 examples.

* **4) Unsampled error exports, or at least compressed full exports.**
  The current package is aggressively sampled. In the vanilla dump alone, `wrong_label_lines` has **1412 total rows** but only **80 sampled rows**; `missed_gold_lines` has **868 total** but only **80 sampled**. That is enough for a vibe check, but not enough to reliably spot patterns by recipe family, section type, or label boundary.

* **5) A tiny label glossary / mapping note.**
  The run folders currently list metrics plus sampled error artifacts, but no small schema note explaining borderline labels or any normalization/post-processing rules. Even a 1-page `label_guide.md` would help interpret whether something is a prompt problem, ontology problem, or evaluation-mapping problem.

## Low-value / safe-to-cut items

* **1) `correct_label_lines.sample.jsonl` is low ROI.**
  You already have per-label metrics and counts, so spending 80 rows on “examples that worked” is usually not the best use of tokens. I’d either drop it or shrink it to a tiny curated set of representative wins.

* **2) Keep either the `*_lines` view or the `*_blocks` view, not both.**
  In the current vanilla dump, `wrong_label_lines.sample.jsonl` and `wrong_label_blocks.sample.jsonl` both show **1412 total rows**, and `missed_gold_lines.sample.jsonl` and `missed_gold_blocks.sample.jsonl` both show **868 total rows**. In this flattened package, those pairs look largely redundant.

* **3) Omit `alignment_gaps.sample.jsonl` when it is empty.**
  Both current dumps show **0 rows** there, so emitting an empty section is just overhead.

* **4) Lower the excerpt size and stop flattening everything into giant markdown when the target is an AI reviewer.**
  The manifest says `excerpt_limit` is **440** and `flatten_enabled` is **true**. For diagnosis, raw JSON/JSONL with stable ids is much cheaper than long markdown headings, fences, and repeated excerpts. I’d keep machine-readable files as primary and make flattened markdown optional.

* **5) Once you include the full prompt log, the sampled `codexfarm_prompt_log.dedup.txt` becomes optional.**
  Right now it is useful only because the full log is missing from the package. If the full log is exported, the sampled convenience view should no longer be the main artifact.

* **6) In the AI-facing summary, compress `run_config_snapshot` to a diff.**
  The current `comparison_summary.json` already gives a compact high-value comparison, including the baseline/codex delta and the config differences. That’s a much better token/value ratio than repeating the whole snapshot in long markdown form. Keep the full snapshot in raw JSON if you want, but the flattened external package should mostly show the diff.

## What I would keep

* **`comparison_summary.json`** — very high signal per token. It already tells me the codex-vs-vanilla delta and the meaningful config diff in one place.
* **`need_to_know_summary.json`** — also high value, because it concentrates per-label metrics, counts, and confusion patterns into one file.
* **A small number of curated failure cases** — but curated, not just random 80-row samples.

## Best “external AI” package

If the goal is “give another AI enough to diagnose quickly without burning tokens,” I’d ship:

* `comparison_summary.json`
* `need_to_know_summary.json` for each run
* `full_prompt_log.jsonl.gz`
* `errors_full.jsonl.gz` with one row per wrong prediction and full provenance
* `preprocess_trace_failures.jsonl.gz` with raw-before / semantic_v1-after for failing cases
* `label_guide.md`

And I’d drop:

* flattened mega-markdown by default
* `correct_label_lines.sample.jsonl`
* duplicate `*_lines` + `*_blocks` pairs
* empty `alignment_gaps.sample.jsonl`
* sampled prompt log once full prompt log exists

That would make the package **smaller** and **more diagnostic at the same time**.
