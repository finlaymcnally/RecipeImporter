---
summary: "Parsing architecture/build/fix-attempt log used to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on parsing behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need historical architecture versions, build attempts, and known failed paths before trying another change
---

# Parsing Log: Architecture, Builds, and Fix Attempts

This log keeps only history that still matters to current parsing code. Removed features, task-file migration bookkeeping, and stale pre-implementation notes were intentionally retired.

## Timeline

### 2026-01-30 to 2026-01-31: step-linking duplication and split handling

Problem:

- Ingredient lines were getting duplicated across multiple steps when only one assignment was intended.

What stuck:

- `assign_ingredient_lines_to_steps(...)` uses a two-phase global resolver.
- Earliest strong `use` step wins when several steps mention the same ingredient.
- Multi-step assignment is allowed only behind strong split language (`half`, `remaining`, `reserved`, and similar cues).
- Split copies take a small confidence penalty for review triage.

Still true:

- The dangerous area is not the first exact/semantic/fuzzy match pass. Most surprising regressions come from post-resolution passes such as `all ingredients`, section-group aliasing, or collective-term fallback.

### 2026-02-10: chunk lane taxonomy alignment

Problem:

- Older artifacts still used `NARRATIVE`, but downstream annotation/review flows had moved to `knowledge` vs `noise`.

What stuck:

- Current chunk routing is effectively binary: `knowledge` or `noise`.
- older `ChunkLane.NARRATIVE` is kept only for transition and is treated as noise in reporting.

Still true:

- Mixed old/new artifacts can look inconsistent even when runtime behavior is correct.

### 2026-02-16 to 2026-02-19: EPUB extraction stabilization

Problem:

- BR-collapsed HTML, soft hyphens, list flattening, nav/pagebreak noise, and unstructured HTML quirks were cascading into bad parsing input.

What stuck:

- `epub_html_normalize.py` does deterministic pre-normalization before unstructured HTML partitioning.
- `unstructured_adapter.py` preserves more block structure and performs deterministic multiline splitting with provenance.
- `epub_postprocess.py` is the shared cleanup pass for HTML-style extractor outputs (`beautifulsoup`, `unstructured`, `markdown`).
- `epub_health.py` emits warning-oriented health metrics instead of blocking extraction.
- Unstructured parser `v2` still needs the transition wrapper for normal EPUB XHTML shape.

Anti-loop note:

- If EPUB output is malformed, fix extractor structure first. Do not stack more downstream segmentation hacks on already-collapsed blocks.

### 2026-02-25: section-aware step linking and multi-component recipes

Problem:

- Multi-component recipes (`For the gravy`, `For the meat`, and similar headers) were hard to link correctly, especially when ingredient names repeated.

What stuck:

- `section_detector.py` is the shared deterministic section detector.
- `sections.py` remains the public boundary and delegates to the shared detector.
- Step linking can bias near ties toward same-section steps when section context is provided.
- Fallback passes (`all ingredients`, collective terms) also scope by section when multiple sections exist.
- Duplicate ingredient lines are tracked internally by original line index rather than text alone.

Still true:

- If duplicate ingredient text collapses to the wrong step, inspect section context and index-based identity before retuning alias scoring.

### 2026-02-25: tables and chunk consolidation

Problem:

- Non-recipe knowledge tables were getting flattened into prose or fragmented into adjacent near-duplicate chunks.

What stuck:

- `tables.py` does deterministic table detection/annotation and writes `table_hint` metadata onto non-recipe blocks.
- `epub_table_rows.py` preserves explicit row/cell structure for EPUB sources when extractor data allows it.
- Chunking keeps table runs atomic and forces table-bearing chunks into the `knowledge` lane.
- `KnowledgeChunk.block_ids` stay sequence-relative for downstream bundle builders.
- Adjacent chunk consolidation uses `provenance.absolute_block_range`, not `block_ids`, to test true source adjacency.
- Table chunks never merge with non-table chunks.

Anti-loop note:

- If chunk adjacency looks wrong, do not reinterpret `block_ids` as absolute source indices. Use `absolute_block_range`.

### 2026-02-27: ingredient parser hardening

Problem:

- Hidden missing-unit defaults and parser repair behavior were causing silent semantic drift.

What stuck:

- Default missing-unit behavior is explicit: `ingredient_missing_unit_policy=null`.
- transition mode remains available as `legacy_medium`.
- Optional normalizers/backends stay opt-in and soft-failable.
- Packaging hints can be hoisted into notes via `ingredient_packaging_mode=regex_v1`.

Still true:

- If one-word headers like `Garnish` regress after parser changes, inspect section-header heuristics before blaming the parser backend.

### 2026-02-27: fallback instruction step segmentation

Problem:

- Raw importer instruction blobs caused draft, JSON-LD, and section artifacts to drift on step boundaries.

What stuck:

- Fallback segmentation is a staging-side safety net, not an importer rewrite.
- Policy surface is deterministic: `instruction_step_segmentation_policy=off|auto|always`.
- Backends are `heuristic_v1` by default and `pysbd_v1` when available.
- The same effective instruction shaping is used by draft-v1, JSON-LD, and section outputs.

Anti-loop note:

- If only one output surface drifts, inspect the shared shaping path before changing sentence-split regexes.

### 2026-02-27: time/temperature/yield upgrades

Problem:

- Instruction time/temperature extraction and yield handling were too baseline-only and inconsistent across stage/benchmark flows.

What stuck:

- `instruction_parser.py` now supports `p6_*` selectors for time backend, time rollup strategy, temperature backend, temperature unit conversion, and oven-like classification.
- `yield_extraction.py` centralizes yield selection/parsing with `p6_yield_mode=legacy_v1|scored_v1`.
- Staging emits richer step metadata plus recipe-level `max_oven_temp_f` when derivable.
- P6 debug data remains opt-in sidecar output, not embedded in final draft JSON.
- Stage, benchmark, and Label Studio prediction generation all thread the same `p6_*` run-config surface.

Anti-loop note:

- If P6 settings appear set but behavior does not change, inspect run-config forwarding through CLI, ingest, and manifest surfaces before changing parser code.

### 2026-02-28: deterministic pattern flags

Problem:

- TOC-like noise, duplicate title-intro structures, and overlap duplicates needed one shared deterministic implementation.

What stuck:

- `pattern_flags.py` is the shared detection and action boundary for EPUB/PDF candidate cleanup.
- Rejected pattern-heavy candidates remain preserved as non-recipe blocks.
- Scoring penalties are deterministic and stable.
- first-stage `pattern_hints` remain advisory-only and default-off.

Still true:

- If candidate suppression feels too aggressive, inspect diagnostics and penalty reasons before retuning constants.

### 2026-03-03 to 2026-03-04: canonical line-role hardening

Problem:

- Canonical line-role labeling had deterministic misses around title/note handling, quantity-fragment atomization, subsection headings, and codex latency.

What stuck:

- `recipe_block_atomizer.py` uses boundary-first splitting, then yield-tail splitting, then general quantity-run splitting.
- Title-like rows keep a deterministic `RECIPE_TITLE` path.
- Note-like prose is handled before generic instruction fallback.
- Yield splitting intentionally avoids bare `serving` prose.
- `canonical_line_roles.py` uses rule-first labeling with optional codex fallback behind `line_role_pipeline=codex-line-role-v1`.
- Codex fallback now uses bounded concurrency, retry/backoff, deterministic merge order, and on-disk cache reuse.
- Ingest owns the shared inflight-default policy for codex line-role work.

Anti-loop note:

- For slow codex line-role runs with low CPU, optimize concurrency, retries, or cache reuse before local parser micro-optimizations.

### 2026-03-06: line-role telemetry/export matching

Problem:

- `joined_line_table.jsonl` could disagree with `line_role_predictions.jsonl` because of either bad export matching or already-invalid prediction rows.

What stuck:

- Export matching should prefer exact normalized index+text, then exact-text sequence alignment.
- Ambiguous duplicate short texts should stay unmatched rather than inherit the wrong prediction row.
- Current line-role predictions no longer depend on older per-row shortlist plumbing.

Anti-loop note:

- If exported tables disagree with raw predictions, first prove whether the raw prediction rows are already wrong.

### 2026-03-13: EPUB table recovery and Food Lab-style reference pages

Problem:

- Historical runs made it look like table writing was broken, but the deeper issues were extractor flattening and recipe-likeness routing.

What stuck:

- Table recovery is upstream-structure-first, not downstream-guesswork-first.
- When available, extractor-side table HTML/cell structure should be preserved and trusted.
- Narrow reference-title penalties help conversion/reference pages stay in non-recipe flow so table detection can see them.

Anti-loop note:

- If tables disappear, inspect extractor structure and recipe-candidate gating before adding more salvage heuristics to `tables.py`.

### 2026-03-14 to 2026-03-15: canonical ingredient misses are atomizer problems first

Problem:

- Obvious recipe rows in canonical line-role output could still collapse to `OTHER`, and older debugging paths kept blaming the wrong parser modules.

What stuck:

- Canonical line-role ingredient misses are usually rooted in `recipe_block_atomizer.py` heuristics, not `ingredients.py` or `instruction_parser.py`.
- The older stale-shortlist theory is retired for current code; prediction runs rebuild candidates and codex now sees the full label vocabulary.

Anti-loop note:

- When line-role misses obvious recipe lines, debug atomizer heuristics and span ownership first.

### 2026-03-15: parsing docs cleanup

What changed:

- The README was trimmed back to current runtime behavior and active contracts.
- This log was reduced to still-live feature history and anti-loop notes.
- Source-file migration history from old `docs/tasks` and `docs/understandings` was removed here because it was contradicting current code and obscuring the useful parts.

### 2026-03-16: canonical line-role shared prompt seam and fast env guard

Problem:

- line-role prompt trimming was easy to land in one caller and accidentally desynchronize live Codex runs from prompt preview
- the single-offline Codex benchmark path also exposed that a tiny env/helper seam could crash before the broader slow suite caught it

What stuck:

- outside-recipe neighbor blanking belongs in the shared prompt-construction path, not in preview-only rendering
- live canonical line-role runs and `cf-debug preview-prompts` should keep rebuilding from the same serializer/builder seam
- `_resolve_line_role_codex_max_inflight()` now has a direct fast regression anchor in `tests/parsing/test_canonical_line_role_env.py`

Anti-loop note:

- if preview prompt counts improve but live line-role cost or behavior does not, the change probably landed in the wrong seam

### 2026-03-16: label-first atomizer span hints and reason-only line-role seam

Problem:

- label-first authoritative reuse briefly atomized every archive block as if it were outside a recipe span
- that caused canonical line-role safety rules to erase legitimate recipe structure before regrouping could recover it
- the same refactor window also made it easy to leave old confidence/trust score fields on line-role artifacts even after runtime decisions had moved to explicit escalation reasons

What stuck:

- `_atomize_archive_blocks(...)` still needs provisional recipe-span hints derived from existing recipe provenance (`start_block` / `end_block`, with line-index fallback) before authoritative regrouping runs
- forcing `within_recipe_span=False` for all blocks is a known bad path; on `saltfatacidheatcutdown` it collapsed counts from the healthy shape (`RECIPE_TITLE=27`, `INSTRUCTION_LINE=64`, `HOWTO_SECTION=28`) down to `RECIPE_TITLE=4`, `INSTRUCTION_LINE=35`, `HOWTO_SECTION=0`
- current line-role artifacts are reason-only:
  - keep labels, provenance, `decided_by`, `reason_tags`, and `escalation_reasons`
  - do not keep scalar `confidence`, `trust_score`, or `escalation_score`
- stage, Label Studio, and reviewer/export surfaces are expected to consume the same reason-only contract; re-adding score fields downstream is a stale-consumer bug, not missing parser output

Anti-loop note:

- if label-first canonical output suddenly turns recipe structure into `OTHER`, debug atomizer span hints before retuning label heuristics or benchmark scorer math
- if a proposed reviewer/export fix adds score fields back, it is fighting the current runtime contract

## Things We Know Are Still Bad

- Text-only ingredient identity is still risky when identical ingredient lines are intentionally duplicated.
- Collective fallback terms (`spices`, `herbs`, `seasonings`) can still attach to the wrong step in multi-component recipes.
- Time rollups are still heuristic around overlapping or optional durations.
- Tip/chunk lane decisions are still heuristic around narrative-advice hybrids.
- Flattened reference prose can still defeat deterministic table extraction if structure is already gone upstream.
- Canonical line-role quality still depends heavily on atomizer heuristics, especially for short quantity-led lines and compact heading-like rows.

## Fast Debug Checks

### Step linking

- Inspect `debug=True` output in `assign_ingredient_lines_to_steps(...)`.
- Check whether a bad assignment came from the initial scorer or a post-resolution pass.
- If the recipe is multi-section, verify section keys are present before changing alias heuristics.

### EPUB parsing

- Compare raw extractor output, postprocessed blocks, and extraction-health warnings before changing downstream parsing code.
- If using unstructured HTML `v2`, verify the transition wrapper path is still active.

### Tables and chunks

- Check whether the source blocks still preserve row structure.
- Verify blocks reached `non_recipe_blocks` at all before debugging `tables.py`.
- For merge issues, inspect `provenance.absolute_block_range` and `provenance.table_ids`.

### P6 parsing

- Verify `p6_*` selectors are present in run config, ingest signatures, and manifests.
- If `max_oven_temp_f` disappears unexpectedly, inspect local negative-hint logic near the matched temperature.

### Canonical line roles

- Start in `recipe_block_atomizer.py` for candidate-shape problems.
- Use `canonical_line_roles.py` only after confirming the candidate itself is reasonable.
- For codex latency, inspect inflight limits, retries, and cache hits before changing heuristics.

### Docs coverage

- When updating parsing docs, compare:
  1. `cookimport/parsing/*.py`
  2. repo call sites importing those modules
  3. the README module and call-site lists

## 2026-03-16 titleless structured fragments, knowledge recall, and stub preservation

Problem:
- titleless pseudo-recipes were still surviving because outside-span structured lines could justify each other
- deterministic outside-recipe `KNOWLEDGE` recall was too conservative on explanatory cooking prose
- the first empty-shell veto over-corrected and dropped real title-plus-yield recipes

What stuck:
- outside-span `INGREDIENT_LINE` / `INSTRUCTION_LINE` must require anchor evidence, not just nearby structured neighbors
- first-person prose should not become `RECIPE_NOTES` unless it also reads like advice/editorial note text
- explanatory cooking-science prose and compact domain headings need a deterministic path into outside-recipe `KNOWLEDGE`
- reject only title-only shells with no ingredients, no instructions, and no yield/time metadata; keep title-plus-yield/time stubs

Evidence worth keeping:
- on `saltfatacidheatcutdown`, the first broader veto dropped the run from `31` recipes to `25`; rejected true positives included `Torn Croutons` and `Tomato Vinaigrette`
- on the same source, recipe-correction task inflation came from `175` grouped spans, including `140` with no title block and `104` single-block spans
- the later deterministic title pass improved the worst-book canonical title metrics without reopening the pseudo-recipe explosion:
  - `thefoodlabcutdown`: `0.387 / 0.197 / 0.261` -> `0.600 / 0.295 / 0.396`
  - `roastchickenandotherstoriescutdown`: `1.000 / 0.149 / 0.260` -> `1.000 / 0.224 / 0.366`
  - `dinnerfor2cutdown`: `1.000 / 0.167 / 0.286` -> `1.000 / 0.200 / 0.333`
  - `amatteroftastecutdown`: `0.842 / 0.525 / 0.647` -> `0.826 / 0.623 / 0.710`

Anti-loop note:
- if benchmark or import task counts explode, inspect grouping and outside-span label anchors before blaming Codex orchestration
- if title recall work starts promoting TOC rows, generic technique headings, or `How to ...` headings again, the bug is usually that outside-span title support was widened too far, not that grouping got stricter

## 2026-03-17 recipe-span gating can fail before line-role starts

Problem:
- canonical benchmark structure misses kept looking like line-role prompt or model failures even when the bad inside/outside recipe decision had already happened upstream

What stuck:
- `label_source_of_truth.py` seeds `within_recipe_span` from existing `conversion_result.recipes[*].provenance.location` before canonical line-role correction runs
- if obvious ingredient or instruction rows are already outside accepted recipe spans, treat importer boundary detection and grouping as the first debugging seam
- benchmark structure gaps on books like `saltfatacidheatcutdown` are often recipe-span acceptance failures first, not "Codex could not read the recipe"

Evidence worth keeping:
- on the 2026-03-17 `saltfatacidheatcutdown` run, almost every missed `INGREDIENT_LINE` / `INSTRUCTION_LINE` row was already outside recipe spans before final line-role scoring
- the first persisted bad decision on `Bright Cabbage Slaw` happened when method blocks were absent from the provenance-backed recipe ranges, so those lines were already `outside_recipe_span` in `label_det`

Anti-loop note:
- if structure labels collapse to `OTHER` or `KNOWLEDGE`, inspect span ownership before retuning line-role prompts or swapping models

## 2026-03-17 post-Codex line-role rollback layers were removed

Problem:
- canonical line-role could predict better structure labels and then lose them to deterministic rollback layers after Codex returned

What stuck:
- validated Codex labels should not be downgraded by outside-span structured-label vetoes, ownership arbitration against the deterministic baseline, or the old run-level do-no-harm fallback
- current overrides are limited to invalid-shape sanitizers plus exact owned-row validation

Anti-loop note:
- if a future fix proposal wants to restore broad outside-span or run-level rollback logic, it is more likely to recreate the old false-negative behavior than to add safety

## 2026-03-17 EPUB singleton-ingredient boundary trap

Problem:
- EPUB candidate boundary detection could truncate a real recipe when a short singleton ingredient looked title-like enough to satisfy the "new recipe starts here" heuristic

What stuck:
- `cookimport/plugins/epub.py` boundary debugging should start with `_is_title_candidate(...)` plus `_has_ingredient_run(...)` on the exact failing block window
- unquantified singleton ingredients such as `Salt` are a known false-title shape
- if a recipe title and ingredient run are in-span but the first instructions fall just outside, fix boundary detection before touching line-role prompts

Evidence worth keeping:
- the 2026-03-17 `Bright Cabbage Slaw` failure ended at block `1124` because `Salt` looked title-like and there was another ingredient run after it, so the method paragraphs at `1128+` never entered the seed candidate

Anti-loop note:
- do not stack downstream span or line-role heuristics on top of a still-truncated EPUB candidate
