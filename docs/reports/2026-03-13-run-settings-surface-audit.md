---
summary: THIS IS OLD AND OUT OF DATE, KEEPING IT HERE AS A REMINDER TO ME (HUMAN)
read_when:
  - "DO NOT READ, OUT OF DATE"
---

`cookimport/config/run_settings.py` currently defines 78 `RunSettings` fields.

- 75 are user-visible.
- 3 are hidden: `effective_workers`, `mapping_path`, `overrides_path`.

The visible surface is distributed like this:

- `Workers`: 5
- `Extraction`: 12
- `Parsing`: 15
- `WebSchema`: 7
- `Scoring`: 6
- `OCR`: 3
- `LLM`: 25
- `Benchmark`: 1
- `Advanced`: 1

## What the codebase is already telling us

The effective product surface is already much smaller than the raw `RunSettings` schema suggests.

- Interactive flows are not exposing a true “78-setting product.” The main chooser in `cookimport/cli_ui/run_settings_flow.py` is fundamentally selecting a top-tier profile family: `codex-exec` or `vanilla`.
- Those profile families are then normalized by `apply_top_tier_profile_contract(...)` in `cookimport/config/codex_decision.py`.
- Benchmark runs are also normalized through benchmark contract patches (`apply_benchmark_baseline_contract(...)`, `apply_benchmark_variant_contract(...)`), which means many nominal settings are not really meant to be freely combined by humans.
- The docs already admit that some “settings” are effectively frozen:
  - `benchmark_sequence_matcher` is documented as `dmp` only.
  - Markdown EPUB extractors are policy-locked off unless an env var is set.
  - A number of codex pipeline ids are implementation contract names, not human-facing choices.

This is the key smell: the system stores and propagates a large number of knobs for persistence, benchmarking, migration, and experimentation, but that does not mean all of them belong in the user-facing run-config surface.

## Why this matters

The cost of keeping implementation seams as user-facing config is not abstract:

- It creates accidental behavior drift between benchmark runs and real runs.
- It makes manifests harder to read because important decisions are mixed with low-level plumbing.
- It creates “configuration theater”: values that exist in manifests and docs but are not real choices in practice.
- It encourages stale defaults to persist far longer than they should.
- It causes false expectations. Example: `table_extraction=off` in saved Food Lab benchmark runs makes it look like the table feature “failed,” when in reality it never ran.

For a solo project, this matters even more: the config surface should reflect real decisions you want to make repeatedly, not every internal seam the pipeline has ever accumulated.

## Current setting inventory by group

`Workers`

- `workers`
- `pdf_split_workers`
- `epub_split_workers`
- `pdf_pages_per_job`
- `epub_spine_items_per_job`

`Extraction`

- `epub_extractor`
- `epub_unstructured_html_parser_version`
- `epub_unstructured_skip_headers_footers`
- `epub_unstructured_preprocess_mode`
- `table_extraction`
- `section_detector_backend`
- `multi_recipe_splitter`
- `multi_recipe_trace`
- `multi_recipe_min_ingredient_lines`
- `multi_recipe_min_instruction_lines`
- `multi_recipe_for_the_guardrail`
- `pdf_column_gap_ratio`

`Parsing`

- `instruction_step_segmentation_policy`
- `instruction_step_segmenter`
- `ingredient_text_fix_backend`
- `ingredient_pre_normalize_mode`
- `ingredient_packaging_mode`
- `ingredient_parser_backend`
- `ingredient_unit_canonicalizer`
- `ingredient_missing_unit_policy`
- `p6_time_backend`
- `p6_time_total_strategy`
- `p6_temperature_backend`
- `p6_temperature_unit_backend`
- `p6_ovenlike_mode`
- `p6_yield_mode`
- `p6_emit_metadata_debug`

`WebSchema`

- `web_schema_extractor`
- `web_schema_normalizer`
- `web_html_text_extractor`
- `web_schema_policy`
- `web_schema_min_confidence`
- `web_schema_min_ingredients`
- `web_schema_min_instruction_steps`

`Scoring`

- `recipe_scorer_backend`
- `recipe_score_gold_min`
- `recipe_score_silver_min`
- `recipe_score_bronze_min`
- `recipe_score_min_ingredient_lines`
- `recipe_score_min_instruction_lines`

`OCR`

- `ocr_device`
- `pdf_ocr_policy`
- `ocr_batch_size`

`LLM`

- `llm_recipe_pipeline`
- `atomic_block_splitter`
- `line_role_pipeline`
- `line_role_guardrail_mode`
- `llm_knowledge_pipeline`
- `llm_tags_pipeline`
- `codex_farm_recipe_mode`
- `codex_farm_cmd`
- `codex_farm_model`
- `codex_farm_reasoning_effort`
- `codex_farm_root`
- `codex_farm_workspace_root`
- `codex_farm_pass1_pattern_hints_enabled`
- `codex_farm_pipeline_pass1`
- `codex_farm_pipeline_pass2`
- `codex_farm_pipeline_pass3`
- `codex_farm_pass3_skip_pass2_ok`
- `codex_farm_benchmark_selective_retry_enabled`
- `codex_farm_benchmark_selective_retry_max_attempts`
- `codex_farm_pipeline_knowledge`
- `codex_farm_pipeline_pass5_tags`
- `codex_farm_context_blocks`
- `codex_farm_knowledge_context_blocks`
- `tag_catalog_json`
- `codex_farm_failure_mode`

`Benchmark`

- `benchmark_sequence_matcher`

`Advanced`

- `warm_models`

## Recommended split: hardcode, hide/internal, keep user-facing

The most useful framing is not “delete half the settings immediately.” It is:

1. Which settings should become fixed product behavior now?
2. Which settings should remain internal/persistable for benchmarking or debugging, but not be treated as top-level user choices?
3. Which settings are real product-level choices worth keeping visible?

### Bucket 1: hardcode as product behavior

These are the clearest cases where the setting behaves like a leftover rollout seam or debug switch rather than a durable user choice.

- `table_extraction`
- `section_detector_backend`
- `instruction_step_segmentation_policy`
- `instruction_step_segmenter`
- `benchmark_sequence_matcher`
- `multi_recipe_trace`
- `p6_emit_metadata_debug`
- `codex_farm_pipeline_pass1`
- `codex_farm_pipeline_pass2`
- `codex_farm_pipeline_pass3`
- `codex_farm_pipeline_knowledge`
- `codex_farm_pipeline_pass5_tags`
- `codex_farm_pass1_pattern_hints_enabled`
- `codex_farm_pass3_skip_pass2_ok`
- `codex_farm_benchmark_selective_retry_enabled`
- `codex_farm_benchmark_selective_retry_max_attempts`

Rationale:

- These are not “which product behavior do I want today?” knobs.
- They mostly represent current implementation identity, internal rollout transition seams, or narrow troubleshooting seams.
- Several of them are effectively single-choice already.
- Keeping them visible causes benchmark/config drift for no real operator benefit.

### Bucket 2: keep internal and persistable, but remove from the everyday user-facing surface

These are real tuning controls, but they read more like lab controls than product controls. They may still matter for experimentation, benchmark comparisons, regression isolation, or future archaeology.

- `multi_recipe_splitter`
- `multi_recipe_min_ingredient_lines`
- `multi_recipe_min_instruction_lines`
- `multi_recipe_for_the_guardrail`
- `ingredient_text_fix_backend`
- `ingredient_pre_normalize_mode`
- `ingredient_packaging_mode`
- `ingredient_parser_backend`
- `ingredient_unit_canonicalizer`
- `ingredient_missing_unit_policy`
- `p6_time_backend`
- `p6_time_total_strategy`
- `p6_temperature_backend`
- `p6_temperature_unit_backend`
- `p6_ovenlike_mode`
- `p6_yield_mode`
- `recipe_scorer_backend`
- `recipe_score_gold_min`
- `recipe_score_silver_min`
- `recipe_score_bronze_min`
- `recipe_score_min_ingredient_lines`
- `recipe_score_min_instruction_lines`
- `pdf_column_gap_ratio`
- `line_role_guardrail_mode`
- `codex_farm_failure_mode`
- `ocr_device`
- `ocr_batch_size`

Rationale:

- These are valid engineering controls.
- They are not good default operator choices for normal stage/import/benchmark use.
- They are best treated as internal defaults, profile internals, hidden advanced flags, or benchmark-only override surfaces.

### Bucket 3: keep user-facing

These still read like real decisions an operator might intentionally make run to run.

- `workers`
- `pdf_split_workers`
- `epub_split_workers`
- `pdf_pages_per_job`
- `epub_spine_items_per_job`
- `epub_extractor`
- `pdf_ocr_policy`
- `llm_recipe_pipeline`
- `llm_knowledge_pipeline`
- `llm_tags_pipeline`
- `codex_farm_cmd`
- `codex_farm_model`
- `codex_farm_reasoning_effort`
- `codex_farm_root`
- `codex_farm_workspace_root`
- `atomic_block_splitter`
- `line_role_pipeline`
- `tag_catalog_json`
- `warm_models`
- `web_schema_extractor`
- `web_schema_normalizer`
- `web_html_text_extractor`
- `web_schema_policy`
- `web_schema_min_confidence`
- `web_schema_min_ingredients`
- `web_schema_min_instruction_steps`

Even here, not all of these need equal visibility. Some are reasonable CLI flags but may not deserve prominent profile/UI treatment.

## Specific callout: `table_extraction`

`table_extraction` is one of the best examples of a setting that should probably stop being a setting.

Why it does not feel like a real product choice:

- It is additive and deterministic, not a competing strategy.
- The feature does not redefine the product; it enriches it.
- The downside of leaving it off is mostly silent under-featured behavior, not a meaningful alternate mode.
- A solo operator who always wants the better output should not need to remember to enable it.

Why it likely exists:

- It was introduced as a rollout seam.
- It made validation safer while table extraction quality was uncertain.
- It simplified rollback if extractor/table heuristics caused regressions.

Why that rationale looks stale now:

- The feature has docs, tests, writer wiring, chunking integration, and knowledge-stage hint integration.
- Leaving it off by default has already caused confusion in saved benchmark artifacts.
- If the remaining risk is extraction quality on some books, that is better handled by internal safeguards, confidence thresholds, or empty outputs than by making “better behavior” opt-in forever.

Practical recommendation:

- Change the product contract to “table extraction is always on.”
- Keep a hidden/internal escape hatch only if needed for regression isolation.
- Stop advertising `--table-extraction` as a normal user-facing run-profile choice.

## Specific callout: top-tier profiles already imply most of the product

The run-settings surface is especially misleading because the UI/runtime already behaves like the real product is mostly two profiles:

- `codex-exec`
- `vanilla`

That is a strong signal that many of the remaining visible settings are implementation detail leaking past the actual user model.

If the real operator decision is mostly:

- Do I want Codex recipe correction?
- Do I want Codex knowledge extraction?
- Do I want Codex tags?
- Which model/effort should Codex use?
- Which extractor/OCR mode should I use?

…then the config surface should mostly mirror that reality.

## Smells worth treating as config debt

- A setting is documented but practically single-choice.
- A setting’s values are pipeline ids or contract names rather than human decisions.
- A setting exists mainly to preserve benchmark comparability or rollout history.
- A setting is only useful while developing a subsystem, not when using the product.
- A setting creates outputs that most users always want, but ships off by default.
- A setting gets normalized away by profile or benchmark contract patching anyway.

## Suggested cleanup direction

Near-term:

- Hard-default `table_extraction=on`.
- Stop surfacing `benchmark_sequence_matcher` as a user choice.
- Stop surfacing codex pass pipeline ids as ordinary run settings.
- Move debug-style flags like `multi_recipe_trace` and `p6_emit_metadata_debug` out of the normal run-settings surface.

Medium-term:

- Collapse parser-tuning clusters into fixed internal defaults once winners are chosen.
- Keep benchmark-only tuning surfaces separate from everyday stage/import settings.
- Treat top-tier profiles plus a short “operator settings” list as the real product contract.

Long-term:

- Reframe `RunSettings` as a persistence/debug schema, not a promise that every field deserves product-level visibility.
- Maintain a smaller public surface layered on top of it.

## Bottom line

The repo currently stores a broad engineering configuration schema, not a clean product configuration surface.

That is fine internally, but it becomes misleading when all of it is treated as equally real, equally intentional, and equally user-facing.

For this project, the most honest model is:

- a small set of real operator choices,
- a medium set of internal tunables,
- and a non-trivial set of rollout/debug leftovers that should stop pretending to be product settings.
