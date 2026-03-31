---
summary: "Code-verified parsing reference focused on current behavior, contracts, and regression-sensitive modules."
read_when:
  - When changing ingredient parsing, instruction metadata extraction, step-ingredient linking, or EPUB recipe segmentation
  - When changing chunk/highlight extraction, knowledge chunking, or chunk lane mapping
  - When reconciling parsing docs against code/tests (use `04-parsing_log.md` for historical attempts)
---

# Parsing: Consolidated System Reference

This file is the source of truth for current parsing behavior.

Historical architecture versions, builds, and fix attempts now live in `docs/04-parsing/04-parsing_log.md`.

## What This Covers

- Ingredient parsing
- Instruction metadata parsing
- Ingredient-to-step linking
- EPUB recipe segmentation rules that affect parsing outcomes
- Internal advice/highlight extraction helpers
- Knowledge chunk generation, lane assignment, and highlight extraction
- Output artifacts and where they are written
- Current limitations / sharp edges

## History and Prior Attempts

- Architecture versions, build notes, and fix attempts: `docs/04-parsing/04-parsing_log.md`
- If debugging starts looping, check the log first before trying a new approach.

## Where The Parsing Code Lives

Core modules:

- `cookimport/parsing/__init__.py` (public parsing utility exports)
- `cookimport/parsing/ingredients.py`
- `cookimport/parsing/instruction_parser.py`
- `cookimport/parsing/yield_extraction.py`
- `cookimport/parsing/step_segmentation.py`
- `cookimport/parsing/step_ingredients.py`
- `cookimport/parsing/section_detector.py`
- `cookimport/parsing/multi_recipe_splitter.py`
- `cookimport/parsing/sections.py`
- `cookimport/parsing/tips.py`
- `cookimport/parsing/atoms.py`
- `cookimport/parsing/chunks.py`
- `cookimport/parsing/tables.py`
- `cookimport/parsing/signals.py`
- `cookimport/parsing/cleaning.py`
- `cookimport/parsing/tip_taxonomy.py`
- `cookimport/parsing/block_roles.py`
- `cookimport/parsing/recipe_block_atomizer.py`
- `cookimport/parsing/canonical_line_roles/`
- `cookimport/parsing/label_source_of_truth.py`
- `cookimport/parsing/recipe_span_grouping.py`
- `cookimport/parsing/markdown_blocks.py`
- `cookimport/parsing/epub_extractors.py`
- `cookimport/parsing/epub_table_rows.py`
- `cookimport/parsing/epub_html_normalize.py`
- `cookimport/parsing/unstructured_adapter.py`
- `cookimport/parsing/markitdown_adapter.py`
- `cookimport/parsing/epub_postprocess.py`
- `cookimport/parsing/epub_health.py`
- `cookimport/parsing/patterns.py`
- `cookimport/parsing/pattern_flags.py`
- `cookimport/parsing/spacy_support.py`

Additional parsing-package helpers used by importer-specific flows:

- `cookimport/parsing/html_schema_extract.py`
- `cookimport/parsing/html_text_extract.py`
- `cookimport/parsing/schemaorg_ingest.py`
- `cookimport/parsing/text_section_extract.py`

Unstructured adapter note:
- `unstructured_adapter.py` now performs deterministic multiline splitting for recipe-like `Title`/`NarrativeText`/`UncategorizedText`/`Text` blocks (in addition to `ListItem` newline splits), preserving provenance with `unstructured_stable_key` suffixes (`.s0`, `.s1`, ...) and `unstructured_split_reason`.

Canonical line-role prompt seam note:
- prompt-volume trims for canonical line-role belong in the shared row-serialization path used by `build_canonical_line_role_prompt(...)`, not in preview-only callers, so live benchmark runs and `cf-debug preview-prompts` stay aligned.
- `codex-line-role-route-v2` now plans one live file-backed `line_role` phase in `canonical_line_roles/`, writes shard/runtime artifacts under `line-role-pipeline/runtime/line_role/`, and still preserves prompt artifact files under `line-role-pipeline/prompts/line_role/` for reviewer/export surfaces.
- line-role direct-exec command resolution is intentionally strict: only real `codex` executables (for example `codex`, `codex exec`, `codex2 e`) or the repo test shim `fake-codex-farm.py` are treated as direct-exec runners. A plain `codex-farm` command is not a valid `codex exec` binary and should fall back to the default direct-exec command instead of being reused verbatim.
- `cookimport/parsing/canonical_line_roles/contracts.py` owns the prediction model plus normalization helpers, `prompt_inputs.py` owns reusable row serialization, `artifacts.py` owns runtime/prompt artifact helpers, `planning.py` owns contiguous shard planning, `policy.py` owns local heuristics, `validation.py` owns shard-ledger checks/promotion gates, `runtime.py` owns live worker orchestration, and `__init__.py` is the package seam.
- the abandoned `recipe_region_gate` / `recipe_structure_label` split is gone from active code and pipeline assets; line-role now means one LLM labeling pass, then deterministic grouping afterward.
- each line-role run now writes one immutable `canonical_line_table.jsonl` before any worker promotion happens. Shard manifests, shard status rows, and final labels all refer back to those stable line ids (`atomic_index` string ids).
- each line-role shard now writes three durable artifacts: the authoritative worker input at `line-role-pipeline/runtime/line_role/workers/*/in/*.json`, the richer local debug copy at `.../debug/*.json`, and one shard-status ledger row in `line-role-pipeline/runtime/line_role/shard_status.jsonl`.
- line-role workers now also get `line-role-pipeline/runtime/line_role/workers/*/hints/*.md`. Those hint sidecars are worker-facing orientation only: shard profile, short static reminders, and a reminder that the worker should label from raw text plus nearby context. The validator still treats `in/*.json` as authoritative.
- line-role direct-exec workers are now `task.json`-first on the happy path. The visible worker session edits only `/units/*/answer` in `task.json`; the worker-visible evidence is raw row text plus stable provenance, not repo-authored deterministic label hints or deterministic reason hints. Repo-owned `assigned_shards.json`, `in/<shard_id>.json`, `debug/<shard_id>.json`, `hints/<shard_id>.md`, and `out/<shard_id>.json` remain supporting context and artifacts outside that contract.
- line-role workers now also run a repo-owned same-session helper after each edit pass. That helper validates the saved `task.json`, rewrites the same file into repair mode once when the edit is structurally wrong, and leaves the stage failed closed if the repair-mode pass is still invalid.
- line-role task-file promotion now treats the original repo-authored task snapshot as the authority for immutable evidence. If the worker saves valid answer labels but also rewrites immutable evidence fields in `task.json`, runtime ignores that evidence drift, extracts only the answer edits, and keeps the original atomic indices/text authoritative.
- accepted Codex shard rows are now first-authority on the live route path. Repo code still validates ownership, completeness, allowed labels, and `exclusion_reason` shape, but it does not compare accepted worker labels to deterministic baseline labels during runtime acceptance.
- the worker `in/*.json` transport is now `{"v":2,"shard_id":...,"context_before_rows":[[atomic_index,current_line], ...],"rows":[[atomic_index,current_line], ...],"context_after_rows":[[atomic_index,current_line], ...]}`. The boundary-context keys are optional and appear only when immediate neighbors exist. It is one ordered contiguous slice of the book, and the live worker-facing payload is intentionally raw-text-first.
- `context_before_rows` and `context_after_rows` are reference-only neighboring rows around the owned shard rows. The live file-backed worker payload now writes one immediate out-of-shard neighbor row on each side when available. Workers may read them for nearby context, but only `rows` is authoritative and labelable.
- shard-mode classification now fails closed when every row has `within_recipe_span=None`: front matter and contents-style title lists are framed as `front_matter_navigation` instead of `recipe_body` unless the shard shows strong local ingredient/step evidence.
- `recipe_block_atomizer.py` now treats `howto_heading` as heading-shape-sensitive instead of prefix-only. Short lines such as `FOR THE SAUCE` or `TO SERVE` can still seed `HOWTO_SECTION`, but long `To make ...` / `To serve ...` sentences stay ordinary variant/procedural prose and must not enter the line-role stage as subsection headings.
- `RECIPE_VARIANT` can now cover short local alternate-version runs: a `Variations` heading or a long named `To make ...` lead can keep the immediately following ingredient rows, explicit-cue instruction rows, and short adjustment lines such as `To add a little heat ...` or `To evoke the flavors ...` inside the same variant subsection, but generic `To make the ...` method steps and following note-only rows stay under their ordinary structural labels.
- EPUB candidate-boundary heuristics are now explicit runtime knobs (`epub_title_backtrack_limit`, `epub_anchor_title_backtrack_limit`, `epub_ingredient_run_window`, `epub_ingredient_header_window`, `epub_title_max_length`) so stage, benchmark, and Label Studio prediction runs can tune importer behavior without code edits.
- the remaining high-value rescue/demotion seams are intentionally narrow and benchmark-derived: Salt Fat canary rows taught that lesson prose, unsupported outside-span title promotions, obvious imperative prep lines, and short `Variation` / `Variations` follow-up lines may need explicit handling, but contents-style headings, generic `To make the ...` method prose, and weak outside-span title guesses must still fail closed. If a fix only works by globally widening `KNOWLEDGE`, `RECIPE_TITLE`, `INSTRUCTION_LINE`, or `RECIPE_VARIANT`, it is probably the wrong fix.
- the local `debug/*.json` copy preserves the old rich object rows for inspection, and preview mirrors the same split under `line-role-pipeline/in/*.json` plus `line-role-pipeline/debug_in/*.json`.
- parent shard proposals are now shard-ledger summaries, not a second hidden task layer. Accepted rows stay authoritative, unresolved rows become repair requests, and the live worker path succeeds only when a clean installed shard ledger validates on the main path or one bounded watchdog retry recovers a retryable killed session. If unresolved rows remain after that, the shard fails closed instead of borrowing deterministic labels.
- the inline compact prompt seam is still separate from the file-backed transport: prompt text uses pipe-delimited `atomic_index|current_line` rows plus `ctx:<atomic_index>|prev=...|line=...|next=...` windows instead of semantic hint codes. Those windows come from explicit ordered-candidate lookup (`build_atomic_index_lookup(...)` plus `get_atomic_line_neighbor_texts(...)`), not hidden fields on `AtomicLineCandidate`.
- line-role planning now defaults to prompt-target control instead of old per-batch mental models: the live and preview paths both aim for `line_role_prompt_target_count=5` unless a caller overrides shard sizing explicitly.
- outside-recipe line-role is routing-only for semantic prose: reusable explanatory prose may land as `NONRECIPE_CANDIDATE`, but contents-style title lists, endorsements, memoir/introduction framing, and isolated topic headings should default to `NONRECIPE_EXCLUDE` unless nearby rows clearly carry reusable lesson prose. Knowledge remains the later stage that decides final `KNOWLEDGE` versus `OTHER`.
- outside-recipe `title_like` and `ingredient_like` rows still need nearby recipe scaffold before they should be treated as recipe structure, but the live Codex route path no longer rejects an accepted worker label back to deterministic baseline at runtime.
- `CanonicalLineRolePrediction` carries optional `exclusion_reason` only on `NONRECIPE_EXCLUDE` rows. The allowed reason codes are for overwhelming obvious junk surfaces such as navigation/front matter, publishing/legal metadata, endorsements, and isolated page furniture.
- the obvious-junk heuristics remain a repo-owned deterministic seam for the rule/baseline path, but the live Codex route path now accepts valid worker labels without runtime semantic veto.
- front-matter navigation exclusion is now a little more aggressive for chapter-taxonomy clusters too: headings like `The Four Elements of Good Cooking`, `SALT`, `What is Salt?`, or `How Salt Works` can be excluded as `navigation` when they sit inside a clear contents/front-matter heading run with no nearby explanatory prose, but the same headings must still fail open when local teaching prose is present.
- parser-owned outside-recipe exclusion now goes through two explicit seams in `cookimport/parsing/canonical_line_roles/policy.py`: `_outside_recipe_knowledge_label_allowed(...)` survives only as a diagnostic/suppression helper for identifying lesson-like prose, while `_outside_recipe_exclusion_reason(...)` is the active coarse-veto seam that marks only obviously useless outside-recipe rows for knowledge pruning.
- lesson-prose prompt posture now explicitly keeps short concept headings such as `Balancing Fat` as `NONRECIPE_CANDIDATE` only when nearby rows clearly carry reusable explanatory prose; lone unsupported question/topic headings such as `What is Heat?` and memoir-only framing such as `Then I fell in love with Johnny...` now default to `NONRECIPE_EXCLUDE`, and short declarative teaching lines can still remain outside-recipe candidates for later knowledge review.
- outside-recipe `INSTRUCTION_LINE` support now looks slightly farther for recipe-local evidence before failing closed. That keeps trailing tail steps such as the Salt Fat crouton cool/store instructions from falling back to `OTHER` when they sit just outside the grouped recipe span, without letting prose-only clusters self-justify as recipe flow.
- line-role policy changes should still be checked against contrast books instead of Salt-Fat-only intuition: `saltfatacidheatcutdown` is the over-structuring and memoir-vs-knowledge canary, `seaandsmokecutdown` is the positive `HOWTO_SECTION` contrast, and `thefoodlabcutdown` is the positive outside-recipe `KNOWLEDGE` contrast.
- heuristic label-mix diagnostics are now telemetry only. The live acceptance path validates ownership, completeness, label legality, and field shape; it does not reject a valid shard because it diverges from deterministic label distribution.
- line-role resume now reuses already-validated `workers/*/out/*.json` shard ledgers and only re-asks missing or invalid shards. The worker prompt for this stage now emphasizes direct reads from the named files, conservative flips, and the repo-written work/feedback loop rather than open-ended semantic relabeling or contrast-example rereads.
- workspace-worker watchdog completion for line-role is now helper-authoritative as well as output-aware: once `_repo_control/line_role_same_session_state.json` reports `completed` and every assigned `workers/*/out/*.json` shard ledger is present/stable, runtime finalizes the session as `completed` or `completed_with_warnings` instead of waiting to reclassify it as a watchdog recovery.
- the line-role workspace watchdog is still warning-only for ordinary helper use, repeated reasoning, and cohort-runtime outliers, but `workspace_final_message_missing_output` is now fallback-only: after a final agent message, runtime starts the 2-second missing-output grace window only when repo-owned same-session completion proof is still absent. If the grace window expires without helper-complete state or durable outputs, runtime records a deterministic `--status` / `--doctor` recovery assessment, then either spends the one shared fresh-session retry budget on the preserved workspace or fails closed with durable rescue metadata.
- shard `status.json` now records the final shard outcome instead of blindly mirroring the raw workspace session state. Recovered watchdog retries or repairs finish as `completed` with recovery reason codes, while `raw_supervision_*` fields preserve the original watchdog evidence for debugging.
- line-role runtime telemetry now also carries `final_proposal_status`, `repair_attempted`, and `repair_status` on workspace rows when a later watchdog retry or same-session repair changes the accepted outcome. Summary counters such as `invalid_output_shard_count`, `missing_output_shard_count`, and `repaired_shard_count` should therefore reflect the final shard result instead of stale first-attempt proposal status.
- low-risk knowledge prompt suppression belongs in parser-owned chunking, not preview-only code. `chunks.py` is the place to route obvious blurbs, navigation, attribution-only fragments, and similar junk to `noise` so live harvest and prompt preview skip the same material.
- `chunks.py` now also exposes narrow utility-profile helpers for the optional knowledge stage. Those helpers may summarize positive/negative utility cues such as cause/effect, troubleshooting, substitutions, storage/safety, framing, memoir, navigation, or true-but-low-utility filler, but they are worker-local hints only: live knowledge validation still checks structure and coverage only and does not let those hints overrule the model.

Parsing-adjacent module (not in the default stage recipe-path runtime):

- `cookimport/parsing/classifier.py` (heuristic line classifier retained for focused classifier experiments)

Major call sites:

- Recipe draft conversion: `cookimport/staging/draft_v1.py`
- EPUB segmentation + block signal enrichment: `cookimport/plugins/epub.py`
- PDF importer block signal enrichment: `cookimport/plugins/pdf.py`
- Text importer block signal enrichment: `cookimport/plugins/text.py`
- Excel importer recipe extraction: `cookimport/plugins/excel.py`
- Web/schema.org extraction helpers: `cookimport/plugins/webschema.py`
- Stage/bench orchestration of chunk/table passes: `cookimport/cli.py`, `cookimport/cli_worker.py`
- Label Studio ingest chunk/table orchestration: `cookimport/labelstudio/ingest_flows/prediction_run.py`
- EPUB debug CLI diagnostics path: `cookimport/epubdebug/cli.py`
- JSON-LD section shaping (`HowToSection`, ingredient section metadata): `cookimport/staging/jsonld.py`
- Candidate confidence scoring using parsing signals: `cookimport/core/scoring.py`
- Knowledge-job bundle construction from parser chunks: `cookimport/llm/codex_farm_knowledge_jobs.py`
- Output writing: `cookimport/staging/writer.py`

Label-first recipe-span note:

- `label_source_of_truth.py` plus `recipe_span_grouping.py` are now the parser-owned engine behind the `recipe-boundary` stage wrapper in `cookimport/staging/pipeline_runtime.py`.
- pre-grouping line-role candidates no longer inherit importer recipe provenance. `within_recipe_span` is now `None` until corrected labels are grouped back into spans, and prompt-preview plus Label Studio ingest mirror that same span-free contract.
- `cookimport/parsing/recipe_span_grouping.py` now treats recipe-boundary acceptance as one explicit gate: a span needs both a title-like anchor and recipe-body proof (`INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, or `TIME_LINE`) before it becomes an accepted recipe span.
- rejected pseudo-recipe spans now also normalize their authoritative block labels back to downstream-safe `OTHER`, so the non-recipe route/finalize seam never sees recipe-local labels on non-recipe blocks just because title detection briefly proposed a candidate recipe shell.
- Title-anchored spans can now survive one intervening `OTHER`/`KNOWLEDGE` block when the very next block returns to strong recipe-body structure. This preserves real recipes through a single stray misclassified ingredient/prose block without reviving titleless pseudo-recipes.
- Titleless structured runs remain visible in staging diagnostics as rejected pseudo-recipes, but they are not emitted into `recipe_spans.json` or downstream recipe drafting.
- Title-only shells and title-plus-note junk are rejected during grouping as `rejected_missing_recipe_body`; title-plus-yield/time stubs still survive so short real recipes are not dropped.
- `build_conversion_result_from_label_spans(...)` no longer reopens ordinary recipe acceptance. If an already accepted span somehow projects to no ingredients, no instructions, and no yield/time metadata, the runtime keeps the accepted span and records an explicit invariant warning instead of demoting it semantically.
- Outside importer-held recipe spans, deterministic `INGREDIENT_LINE` and `INSTRUCTION_LINE` labels now require nearby recipe-anchor evidence instead of allowing a small structured cluster to self-justify.
- Deterministic title recall is intentionally broader than it was before March 2026: long mixed-case titles containing `with`, all-caps verb-led headings, and `TITLE -> NOTE: -> recipe body` starts can stay `RECIPE_TITLE` when nearby recipe-start evidence exists.
- Outside-span title rescue and in-span title retention are intentionally different seams. The outside-span path stays strict to avoid TOC/how-to false positives; Codex-emitted outside-span titles now also fall back when local recipe support is missing, while once a span is already accepted, immediate note prose should not eject a real title.
- if obvious ingredients or instructions are already outside recipe, debug atomizer heuristics, deterministic labeling, and later grouping before reintroducing any importer-span hinting. Pre-Codex recipe-span seeding is now treated as a bug, not a fallback seam.
- In EPUBs, a short unquantified singleton ingredient such as `Salt` can still look title-like enough to cut a recipe early in `cookimport/plugins/epub.py`. When a recipe title and ingredients are in-span but the first method paragraphs fall just outside, treat candidate-boundary detection as the first debugging seam.

## End-to-End Data Flow (Current)

### Recipe path

1. The recipe-boundary stage builds `RecipeCandidate` objects from accepted recipe spans after importer source facts have been normalized.
2. `cookimport/staging/draft_v1.py` converts each candidate:
   - optional deterministic fallback step segmentation runs first (`instruction_step_segmentation_policy=off|auto|always`, backend `heuristic_v1|pysbd_v1`)
   - ingredient lines parsed with `parse_ingredient_line`
   - steps parsed with `parse_instruction`
   - yield phrase selection/parsing runs through `derive_yield_fields(...)` (`p6_yield_mode`)
   - ingredient lines linked to steps with `assign_ingredient_lines_to_steps`
3. Unassigned ingredients get inserted into a prep step (`"Gather and prepare ingredients."`) at step 0.
4. Writer emits draft outputs.

### Chunk/highlight path

1. Importers publish canonical `source_blocks` plus optional non-authoritative `source_support`; they do not own outside-recipe truth.
2. The shared stage session builds authoritative outside-recipe ownership from that source model and writes the final non-recipe route/finalize rows back into `ConversionResult.non_recipe_blocks`.
3. When non-recipe finalize is off, stage and processed-ingest paths may still compute deterministic chunks from final non-recipe rows as optional fallback/debug artifacts.
4. When non-recipe finalize is on, the live knowledge LLM path does not consume or regenerate those parser chunks. `cookimport/llm/codex_farm_knowledge_jobs.py` plans ordered candidate packets directly from candidate outside-recipe block rows and leaves semantic grouping to the model.
5. Highlight extraction inside `chunks.py` still reuses the internal advice extractor from `parsing/tips.py`, but those candidates are local deterministic chunk metadata rather than the final knowledge-group authority surface.

## Ingredient Parsing (`cookimport/parsing/ingredients.py`)

### Main behavior

- Uses `ingredient-parser-nlp` (`parse_ingredient(..., string_units=True)`).
- Supports optional run-setting backends/normalizers:
  - `ingredient_parser_backend`: `ingredient_parser_nlp | quantulum3_regex | hybrid_nlp_then_quantulum3`
  - `ingredient_text_fix_backend`: `none | ftfy`
  - `ingredient_pre_normalize_mode`: `aggressive_v1`
  - `ingredient_packaging_mode`: `off | regex_v1`
  - `ingredient_unit_canonicalizer`: `pint`
  - `ingredient_missing_unit_policy`: `null | each | medium`
- Returns normalized dict with `quantity_kind` in:
  - `exact`
  - `approximate`
  - `unquantified`
  - `section_header`

### Important heuristics

- Section headers detected before and after parser call.
- Approximate phrases include `to taste`, `as needed`, `for serving`, `for frying`, and related patterns.
- Quantity ranges use midpoint then `ceil`:
  - `3-4` => `4.0`
  - `2-4` => `3.0`
- Split fractions like `3 / 4` are normalized before parse.

### Non-obvious implementation details

- Default missing-unit policy is now explicit and defaults to `null` (no implicit `"medium"` unit).
- Packaging-mode regex hoist (`ingredient_packaging_mode=regex_v1`) moves package-size hints into `note` for lines like `1 (14-ounce) can tomatoes`.
- Post-parse repair is deterministic: it preserves `raw_text`, repairs invalid quantity/unit/name combinations, and keeps fallback ingredient names instead of dropping lines.
- Approximate repair now also normalizes bogus parser unit reads such as `picoinch` back to `pinch` so phrases like `pinch of salt` land as `quantity_kind=approximate` with the token moved into `note`.
- `warm_ingredient_parser()` exists to pre-load model quietly.

### Tests to read

- `tests/parsing/test_ingredient_parser.py`

## Instruction Metadata Parsing (`cookimport/parsing/instruction_parser.py`)

### Extracted fields per step

- `time_items`: list of detected durations
- `total_time_seconds`: strategy-selected rollup for that step (`sum_all_v1`, `max_v1`, `selective_sum_v1`)
- `temperature_items`: all matched temperatures with normalized unit/value and `is_oven_like` flag
- `temperature`, `temperature_unit`, `temperature_text`: convenience mirror fields for the first matched temperature expression

### Time behavior

- Backends:
  - `regex_v1` (default)
  - `quantulum3_v1` (optional dependency)
  - `hybrid_regex_quantulum3_v1` (regex fallback first)
- Handles seconds/minutes/hours/days and abbreviations (`mins`, `hrs`, `secs`).
- Ranges use midpoint (`20 to 30 minutes` => 25 minutes).
- Strategy notes:
  - `sum_all_v1` keeps the prior full-step aggregation behavior.
  - `max_v1` keeps only longest duration in a step.
  - `selective_sum_v1` skips obvious frequency spans (`every 5 minutes`) and collapses `or` alternatives.

### Temperature behavior

- Backends:
  - `regex_v1` (default)
  - `quantulum3_v1` (optional dependency)
  - `hybrid_regex_quantulum3_v1` (regex fallback first)
- Unit conversion backends:
  - `builtin_v1` (default)
  - `pint_v1` (optional dependency; validation guard)
- Handles `400F`, `350°F`, `375 degrees F`, `220 degrees celsius`.
- Returns all matches in `temperature_items`; the convenience mirror fields keep the first match for single-value consumers.
- Oven-like classification is deterministic (`p6_ovenlike_mode=keywords_v1|off`) and is used by staging to derive recipe-level `max_oven_temp_f`.

### Known limitations

- Regex-first extraction can miss niche phrasing where optional parser backends may perform better.
- Yield unit-name singularization in scored mode is heuristic and intentionally lightweight.

### Tests to read

- `tests/parsing/test_instruction_parser.py`
- `tests/parsing/test_yield_extraction.py`

## Step-Ingredient Linking (`cookimport/parsing/step_ingredients.py`)

## Core algorithm

Two-phase assignment:

1. Candidate collection across all step x ingredient pairs
2. Global resolution per ingredient

Matching order:

1. Exact alias matches
2. Semantic fallback (rule lemmatization + synonym variants)
3. Fuzzy fallback (RapidFuzz) only for still-unmatched ingredients

### Alias generation

- Uses `raw_ingredient_text` and cleaned `raw_text` variants.
- Includes full-token aliases plus head/tail single-token aliases.
- Alias scoring prefers more tokens, longer tokens, and `raw_ingredient_text` source.

### Verb context scoring

- `use` verbs: positive score
- `reference` verbs: negative score
- `split` signals (`half`, `remaining`, `reserved`, etc.) enable multi-step behavior only when strong conditions are met

### Section extraction and context

- `cookimport/parsing/section_detector.py` is the shared deterministic detector used by importers and parser section helpers.
- `cookimport/parsing/sections.py` keeps the historical public API and delegates detection internals to `section_detector.py`.
- Shared detection currently uses the `shared_v1` detector path.
- `sections.py` provides deterministic section extraction for:
  - ingredient headers (for example `For the gravy:`),
  - instruction headers (conservative heuristics; header-like short lines only).
- Section keys are normalized (`For the Gravy:` -> `gravy`) so ingredient/instruction sections align.
- In `assign_ingredient_lines_to_steps(...)`, optional section context can bias ambiguous matches:
  - near-tied candidates prefer same-section steps,
  - repeated ingredient names across components resolve by section when context is available.

### Assignment rules

- Default: one best step per ingredient.
- If multiple `use` candidates exist, earliest use step wins.
- Multi-step assignment allowed only with strong split language and >=2 use/split candidates.
- Max steps per ingredient is capped at 3.

### Fraction handling

- Split phrases (`half`, `third`, `quarter`, `remaining`) can produce step fractions.
- When split applied, step ingredient copy gets confidence penalty (`-0.05`, floored at 0).

### Special passes after global assignment

- `all ingredients` phrases can assign all non-header ingredients to a step.
  - when section context is present and the recipe has multiple sections, this scopes to ingredients in that same section.
- Section-header groups can add grouped ingredients to steps mentioning group aliases.
- Collective-term fallback for unmatched ingredients:
  - categories currently: `spices`, `herbs`, `seasonings`
  - prefers same-section steps when section context exists, then falls back globally

### Critical tradeoffs and known bad behavior

- Collective-term fallback is intentionally conservative but can misassign when the same collective term appears later for a different subcomponent.
- Weak single-token aliases are filtered against strong overlapping tokens in same step, but token-only matching can still be noisy on generic terms.
- Section detection for instructions is intentionally conservative; odd short lines can still be false negatives (left as literal steps) to avoid deleting real instructions.

### Tests to read

- `tests/parsing/test_step_ingredient_linking.py`
- `tests/parsing/test_recipe_sections.py`

## EPUB Segmentation Rules That Matter (`cookimport/plugins/epub.py`)

### Why this belongs in parsing docs

Recipe boundary detection directly controls which text reaches parsing/linking/tip systems.

### Current rules in `_find_recipe_end`

- Stops at strong section boundaries and next recipe starts.
- Keeps `Variation`/`Variations` blocks with current recipe.
- Explicitly keeps subsection headers inside recipe, including:
  - `For the X`
  - short `For X`
- Rejects singleton pantry lines like `Salt` or `Pepper` as next-recipe titles so ingredient runs do not truncate the current recipe before instructions.

### Extraction backend plumbing that affects parsing inputs

- `cookimport/parsing/epub_extractors.py` defines the `beautifulsoup` / `unstructured` / `markdown` backend adapters.
- `cookimport/parsing/markitdown_adapter.py` handles the `markitdown` backend conversion (`EPUB -> markdown`), then `cookimport/parsing/markdown_blocks.py` converts markdown to deterministic `Block` objects.
- `cookimport/parsing/epub_html_normalize.py` pre-normalizes XHTML before unstructured partitioning.
- `cookimport/parsing/unstructured_adapter.py` maps unstructured elements to deterministic blocks + diagnostics metadata.
- `cookimport/parsing/epub_table_rows.py` preserves EPUB `<tr>` rows as structured cell arrays plus visible `|`-delimited row text so downstream table detection does not have to guess column boundaries.
  - BeautifulSoup-based EPUB extraction preserves empty cells instead of collapsing them away.
  - Unstructured-based EPUB extraction expands `metadata.text_as_html` tables into explicit row blocks when that HTML is available, instead of trying to recover columns from already-flattened text.
- `cookimport/parsing/epub_postprocess.py` and `cookimport/parsing/epub_health.py` are shared guardrails after HTML-based extraction.
- `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py` both read `run_settings.section_detector_backend` and can route field extraction through the shared detector when set to `shared_v1`.
- obvious conversion/reference titles now carry a narrow recipe-likeness penalty so Food Lab-style tables can stay in non-recipe flow and reach `tables.py` instead of being trapped as fake recipes.

## Deterministic Pattern Flags (`cookimport/parsing/pattern_flags.py`)

### Scope

- Shared deterministic detector/action helper used by EPUB and PDF importers before candidate extraction and during overlap resolution.

### Current behavior

- Detects TOC-like contiguous clusters and duplicate title-intro flows from block text only (no LLM dependency).
- Returns structured diagnostics (`PatternDiagnostics`) with:
  - `block_flags`
  - cluster summaries/scores
  - duplicate-title pair metadata
  - pre-candidate `excluded_indices`
- Provides action helpers:
  - `apply_candidate_start_trims(...)`
  - `resolve_overlap_duplicate_candidates(...)`
  - `pattern_warning_lines(...)` for stable report warning strings.

### Where outputs are consumed

- EPUB/PDF add `pattern_flags`/`pattern_actions` to candidate provenance location metadata.
- `cookimport/core/scoring.py` applies deterministic penalties from those flags and records reasons in scoring debug output.

### Known historical fix

This was added to stop false recipe splits where component headers like `For the Frangipane` were treated as new recipe starts.

### Tests to read

- `tests/ingestion/test_epub_importer.py`
- `tests/ingestion/test_epub_extraction_quickwins.py`
- `tests/parsing/test_epub_html_normalize.py`
- `tests/ingestion/test_unstructured_adapter.py`
- `tests/parsing/test_markdown_blocks.py`

## Shared Multi-Recipe Splitter (`cookimport/parsing/multi_recipe_splitter.py`)

### Scope

- Shared deterministic splitter for one candidate span that may contain multiple recipes.
- Used by Text, EPUB, and PDF importers when `multi_recipe_splitter=rules_v1`.

### Backends

- `off`: passthrough; no split attempt.
- `rules_v1`: title-like boundary detection + section coverage thresholds + local recipe-signal guard.

### Guardrails and thresholds

- `For the X` false-boundary suppression reuses `detect_sections_from_lines(...)` in `section_detector.py` when `multi_recipe_for_the_guardrail` is enabled.
- Coverage thresholds (`multi_recipe_min_ingredient_lines`, `multi_recipe_min_instruction_lines`) use ingredient/instruction signal lines (content and section-header signals) so short recipe units with clear headers remain splittable.
- Optional trace payload records accepted/rejected boundaries and guardrail-blocked indices when `multi_recipe_trace=true`.

### Tests to read

- `tests/parsing/test_multi_recipe_splitter.py`
- `tests/ingestion/test_text_importer.py`
- `tests/ingestion/test_epub_importer.py`
- `tests/ingestion/test_pdf_importer.py`

## Internal Advice/Highlight Extraction (`cookimport/parsing/tips.py`)

### Current role

- The old exported tip/topic lane is gone from stage and Label Studio outputs.
- `parsing/tips.py` remains as an internal helper module for:
  - chunk highlight extraction
  - parser-focused tip/advice tests
  - residual standalone advice heuristics still used by PDF/EPUB helper code paths under test

### Extraction model (current)

- Split text into candidate blocks.
- Extract spans from each block.
- Repair clipped spans using neighboring sentence/block context.
- Judge each span by advice-ness + generality + context.
- Attach taxonomy tags when the span survives.

Gates include:

- advice/action cues
- cooking anchors
- narrative rejection signals
- header/prefix strength (strong vs weak callouts)

### Important boundary

- These helpers no longer feed `ConversionResult.tips`, `tip_candidates`, or `topic_candidates`; those fields were removed.
- When `chunks.py` reuses this extractor, the surviving spans become chunk-local highlights only.

### Tests to read

- `tests/parsing/test_tip_extraction.py`
- `tests/parsing/test_tip_recipe_notes.py`

## Atomization (`cookimport/parsing/atoms.py`)

### What it does

- Splits block text into paragraph/list-item atoms.
- Adds adjacency context (`context_prev`, `context_next`).
- Preserves container metadata (start/end/header).

### Why it matters

- Parser/debug provenance can carry atom context, which remains useful for standalone advice analysis and chunk-highlight debugging.

### Tests to read

- `tests/core/test_atoms.py`

## Recipe Block Atomization (`cookimport/parsing/recipe_block_atomizer.py`)

### What it does

- Splits merged recipe blocks into atomic line candidates for canonical line-label benchmark work.
- Emits serializable `AtomicLineCandidate` rows with deterministic `atomic_index`, single-line metadata, and rule tags. Neighbor text is no longer stored on the candidate itself; prompt/cache callers that need adjacency derive it explicitly from the ordered candidate set.
- `atomic_block_splitter=atomic-v1` enables boundary-first splitting; `atomic_block_splitter=off` keeps one candidate per source block (no sub-line splitting).

### Current rules

- Boundary-first splitting for `NOTE:`, yield prefixes (`MAKES`/`SERVES`/`YIELDS`), method headings (`TO MAKE`, `FOR THE`, `FOR SERVING`), and inline numbered steps.
- Yield-first segments are split so trailing quantity-led ingredient runs become separate candidates.
- Quantity-run splitting now keeps instruction-like prose whole and blocks broken dual-unit fragments (`2 cups/` + `475 g ...`) from being atomized into fake ingredient rows.
- Quantity ranges like `4 to 6 chicken leg quarters` are treated as ingredient-like candidates, not yield.
- Short quantity-led lines (for example `1 fresh bay leaf`, `8 thin slices ...`) now stay ingredient-like with deterministic negative guards for time/instructional fragments.
- Heading-like title rows now emit `RECIPE_TITLE` candidates (`title_like`) before generic fallback labels.
- Note-like prose rows now emit `RECIPE_NOTES` candidates (`note_like_prose`) before instruction heuristics.
- Yield regex intentionally excludes bare `serving` to avoid splitting prose lines like `before serving`.
- Pre-grouping candidates now carry `within_recipe_span=None` by default. The old provenance-backed recipe-range seed is gone; deterministic line-role and Codex review run span-free, and recipe grouping happens only after corrected labels exist.

### Tests to read

- `tests/parsing/test_recipe_block_atomizer.py`

## Canonical Line Roles (`cookimport/parsing/canonical_line_roles/`)

### What it does

- Assigns one canonical benchmark label per `AtomicLineCandidate` using deterministic rules first.
- Supports optional shard-worker labeling over the full ordered candidate set when `line_role_pipeline=codex-line-role-route-v2`; each shard row now carries only `atomic_index` plus raw line text, with neighboring raw-text context rows when available.
- Emits `CanonicalLineRolePrediction` rows with `decided_by` provenance (`rule`, `codex`, `fallback`), reason tags, and explicit `escalation_reasons`.
- Prediction rows carry tri-state `within_recipe_span`: `None` during the pre-grouping line-role pass, then explicit `True`/`False` only after grouped recipe spans are projected back downstream.
- Cache identity and inline prompt context both derive adjacency from explicit ordered-candidate lookup, so `AtomicLineCandidate` itself remains a single-row fact.

### Current safeguards

- Rule-first path handles low-ambiguity cases (`NOTE`, yield, ingredient-like, method headers, variants, and instruction lines).
- The pre-grouping contract is intended-only: no prompt or deterministic rule gets importer recipe ranges up front. Any logic that truly depends on accepted recipe membership must key off explicit `within_recipe_span is True`, not truthy/falsy fallback.
- `HOWTO_SECTION` is now book-optional and high-evidence. `cookimport/parsing/canonical_line_roles/policy.py` computes one book-local availability seam (`absent_or_unproven`, `sparse`, `available`) and shard guidance carries that posture into worker files/prompts.
- Compact all-caps title-like rows are disambiguated to `HOWTO_SECTION` only when neighboring lines indicate an internal component/subsection flow. Isolated headings now fail closed instead of assuming subsection structure.
- `YIELD_LINE` still has strict header validation on the deterministic rule path, but the live Codex route path now treats accepted worker labels as first-authority as long as they satisfy the output contract.
- `TIME_LINE` is still intended for primary time metadata, but the live Codex route path no longer rejects a valid worker label back to deterministic baseline at runtime.
- In the pre-grouping `within_recipe_span=None` state, the live route contract is recipe-local labels plus `NONRECIPE_CANDIDATE` / `NONRECIPE_EXCLUDE`; line-role no longer emits final outside-recipe `KNOWLEDGE` / `OTHER`.
- Short storage/use/serving-note lines such as `Store leftover...`, `Refrigerate leftovers...`, `Cover and refrigerate leftovers...`, and leading `Ideal for ...` suggestions now promote directly to `RECIPE_NOTES`.
- Outside recipe spans, prose now defaults to route labels: `NONRECIPE_CANDIDATE` for material that knowledge should review later, `NONRECIPE_EXCLUDE` only for obvious junk with a valid `exclusion_reason`.
- Final non-recipe authority still arbitrates outside-span `KNOWLEDGE` versus `OTHER` after recipe-local projection; line-role itself stops at candidate/exclude routing.
- `RECIPE_TITLE` now requires supportive near-line context when available (yield boundary, ingredient/instruction flow, or recipe-structure cues) to reduce title-vs-howto/title-vs-narrative confusion; inside accepted recipe spans, immediate note prose is enough to retain the title.
- Short ingredient fragments (for example split quantity/name rows) now get neighbor-aware rescue to `INGREDIENT_LINE` when adjacent ingredient-dominant context supports it.
- Shard ledgers use strict ownership validation with the full global line-role label set available on every row; invalid or missing shard outputs now fail closed for their owned rows, and `shard_status.jsonl` plus `line_role_stage_summary.json` record unresolved-row counts plus `repair_recovered` / `repair_failed` / `invalid_output` shard outcomes.
- Row-level shard validation still belongs to deterministic code: invalid `exclusion_reason` values, wrong ownership, wrong row counts, duplicate rows, and frozen-row rewrites must all be rejected even when the live worker contract is just one editable `task.json`.
- The compact line-role summary now also exposes `attention_summary` so unresolved rows, Codex hard-policy rejections, suspicious shards, and missing/invalid shard counts are easy to spot at run-review time.
- Title-like recovery no longer depends on per-row Codex allowlist expansion; atomizer/deterministic heuristics still influence non-LLM ownership logic.
- Strong deterministic `RECIPE_TITLE` outcomes are held on the rule path without any score-based fallback pressure.
- Outside-recipe-span score-based escalation is gone; shard review sees the whole ordered candidate set, and local neighbor context is attached only for escalated rows rather than only for pre-marked recipe rows.
- Accepted Codex structure labels are no longer compared against deterministic baseline labels during live runtime acceptance. If a worker output is structurally valid and contract-valid, it installs directly; disagreements with deterministic rules are now an offline evaluation concern rather than a runtime veto seam.
- This seam is now reason-only. Current runtime artifacts expose label-driven grouping plus explicit `escalation_reasons` only; scalar `confidence`, `trust_score`, and `escalation_score` fields are no longer part of the contract.
- Reviewer/export surfaces should mirror that same contract. If a downstream bundle or debug packet still wants scalar uncertainty fields, that downstream surface is stale rather than the parsing contract being incomplete.
- Codex fallback batches now run with bounded in-flight concurrency (parser default `4` per book; explicit env override via `COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT`; ingest callers can pass `codex_max_inflight`) and merge back deterministically by atomic index/prompt order.
- Prompt logging internals are thread-safe for concurrent codex batch workers (`prompt_*.txt`, `response_*.txt`, `parsed_*.json`, and dedup log writes).
- Codex call failures now use bounded retry/backoff before fallback (`3` attempts, exponential backoff base `1.5s`).
- Canonical line-role predictions are cached on disk by source hash + run-settings hash + candidate fingerprint; reruns can reuse cache and skip codex calls (`COOKIMPORT_LINE_ROLE_CACHE_ROOT` overrides cache location).
- The shard runtime emits structured stage-progress callbacks for deterministic prep plus shard-worker start/finish states. Deterministic prep reports `row X/Y`, while the live workspace-worker runtime reports `shard X/Y | running N`, and both surfaces also attach configured-worker and queued-work detail for benchmark/import spinners and processing timeseries logs.
- Canonical line-role deterministic labeling now emits `row X/Y` progress callbacks before any Codex shard work starts, so ETA appears during the deterministic pass too.

### Related modules

- `cookimport/llm/canonical_line_role_prompt.py`
- `cookimport/llm/codex_exec_runner.py` (shared direct-exec workspace runner used by the active line-role Codex path)
- `llm_pipelines/prompts/canonical-line-role-v1.prompt.md`

### Tests to read

- `tests/parsing/test_canonical_line_roles.py`

## Knowledge Chunking (`cookimport/parsing/chunks.py`)

### Pipeline

`process_blocks_to_chunks`:

1. `chunk_non_recipe_blocks`
2. `merge_small_chunks`
3. `assign_lanes`
4. `extract_highlights`
5. `consolidate_adjacent_knowledge_chunks` (adjacent same-topic knowledge only)

### Chunk construction

- Heading-driven boundaries first.
- Optional callout boundaries.
- Format-mode boundaries (prose/list shifts).
- Max-char boundary.
- Stop headings (index, acknowledgments, etc.) can be excluded.

### Table-aware behavior

- Table rows in `non_recipe_blocks` are tagged with `features.table_id` + `features.table_row_index` during normal stage/prediction runs.
- `detect_tables_from_non_recipe_blocks(...)` trusts structured EPUB row metadata first, then falls back to visible delimiters / flattening heuristics for older or non-EPUB sources.
- Flattened reference-table salvage is intentionally narrow:
  - target headings are conversions, weights, temperatures, equivalencies, and similar reference sections,
  - salvaged tables should carry lower confidence / notes instead of pretending they were clean structured-table detections.
- `chunk_non_recipe_blocks` treats same-`table_id` runs as atomic for max-char splitting (it does not split in the middle of a detected table).
- Chunks carrying `provenance.table_ids` are forced to `knowledge` lane so table facts are not dropped as noise.
- Table chunks are never merged with non-table chunks, in either `merge_small_chunks` or adjacent-chunk consolidation.

### Adjacent consolidation behavior

- Runs after highlights so heading context + merged tags can be used as topic signals.
- Only considers adjacent `knowledge` chunks.
- Requires contiguous absolute block ranges (`left_end + 1 == right_start`, inclusive-range convention).
- Same-topic rule is conservative: same heading context first; tag-only fallback is allowed only when heading context is missing.
- Chunk-size cap uses the active chunk profile max chars.
- Kill switch: set `COOKIMPORT_CONSOLIDATE_ADJACENT_KNOWLEDGE_CHUNKS=0` to disable this pass for debugging/regression isolation.

### Lane assignment

Current effective lanes:

- `knowledge`
- `noise`

`ChunkLane.NARRATIVE` is an older lane value; reporting treats it as noise.

### Highlight extraction

- Only runs on `knowledge` chunks.
- Reuses tip candidate extractor on chunk text.
- Converts non-`not_tip` candidates into chunk highlights.
- Computes `tip_density` and merged tags.

### Known tradeoffs and bad behavior

- Lane scoring is heuristic; borderline narrative/knowledge chunks will oscillate when heuristics are tuned.
- Default fallback in ambiguous cases tends toward `knowledge`, which can admit low-value chunks.
- Highlight self-containedness requires length/punctuation; short useful cues may be kept but marked non-self-contained.

### Tests to read

- `tests/parsing/test_chunks.py`

## Signals and Cleaning (Support Modules)

## Signals (`cookimport/parsing/signals.py`)

- Lightweight block classifier: ingredient likelihood, instruction likelihood, headers, yield/time flags.
- Supports `ParsingOverrides` for headers, verbs, units.
- Optional spaCy enrichment gated by env var (`COOKIMPORT_SPACY`) or override.
- Regex/header/unit/verb primitives are defined in `cookimport/parsing/patterns.py`.
- spaCy loading + POS feature extraction live in `cookimport/parsing/spacy_support.py`.

### Caveat

Heuristics are intentionally simple; downstream logic should not assume high-precision NLP quality from signals alone.

## Cleaning (`cookimport/parsing/cleaning.py`)

- Mojibake fixups
- Unicode normalization (NFKC)
- Whitespace normalization
- Hyphenation repair across line breaks
- EPUB-specific normalization path (`normalize_epub_text`) removes soft hyphens/zero-width chars and normalizes unicode fractions/punctuation for ingredient detection stability.

## EPUB Postprocess and Health (`cookimport/parsing/epub_postprocess.py`, `cookimport/parsing/epub_health.py`)

- `postprocess_epub_blocks(...)` runs after `beautifulsoup`/`unstructured`/`markdown` extraction to do shared structural cleanup:
  - split BR-collapsed/table/list multi-line blocks into deterministic per-line blocks
  - strip leading bullet markers
  - drop obvious noise blocks (pagebreak markers/nav leftovers)
- `compute_epub_extraction_health(...)` computes extraction sanity metrics and warning keys (`epub_*`) that are attached to EPUB conversion reports.

### Caveat

Mojibake replacements are heuristic and can be lossy in edge encodings.

## Heuristic Classifier (Parsing-Adjacent) (`cookimport/parsing/classifier.py`)

- Provides standalone line-level `ingredient`/`instruction`/`other` classification helpers.
- This module is currently test-scoped and not on the default stage recipe conversion path.
- Useful when debugging/iterating on heuristic classifier behavior outside draft-v1 assignment.

## Output Artifacts and Paths

Timestamp root uses `YYYY-MM-DD_HH.MM.SS`.

Under a run output folder:

- Chunks: `data/output/<timestamp>/chunks/<workbook_stem>/c{index}.json`
- Chunk summary: `data/output/<timestamp>/chunks/<workbook_stem>/chunks.md`
- Tables: `data/output/<timestamp>/tables/<workbook_stem>/tables.jsonl` and `tables.md`

## Practical Change Workflow (Recommended)

1. If progress stalls or repeats, read `docs/04-parsing/04-parsing_log.md` first.
2. For step linking, inspect `debug=True` output (`candidates`, `assignments`, group/all-ingredients annotations).
3. Verify with focused tests:
   - `tests/parsing/test_step_ingredient_linking.py`
   - `tests/parsing/test_ingredient_parser.py`
   - `tests/parsing/test_instruction_parser.py`
   - `tests/parsing/test_chunks.py`
   - `tests/parsing/test_tables.py`
   - `tests/parsing/test_cleaning_epub.py`
   - `tests/parsing/test_epub_html_normalize.py`
   - `tests/parsing/test_markdown_blocks.py`
   - `tests/ingestion/test_epub_importer.py`
   - `tests/ingestion/test_epub_extraction_quickwins.py`
   - `tests/ingestion/test_unstructured_adapter.py`
4. Run end-to-end spot check through `cookimport.cli stage` and inspect generated `chunks.md` and `tables.md` when those lanes are enabled.
5. Keep deterministic behavior as default; new ML/LLM options should remain opt-in with deterministic fallback preserved.

## Quick Reference: Most Sensitive Files

- Step linking logic and regressions: `cookimport/parsing/step_ingredients.py`
- EPUB boundary regressions: `cookimport/plugins/epub.py`
- Advice/highlight scope drift: `cookimport/parsing/tips.py`
- Lane drift and chunk boundary shifts: `cookimport/parsing/chunks.py`
- Output formatting/selection confusion: `cookimport/staging/writer.py`

## Recent Parsing Notes Worth Keeping

- Outside-span structured lines must not self-anchor. A nearby ingredient-like or instruction-like line is not enough evidence by itself; title/yield/howto/variant anchors or importer-held recipe-span context are the safe boundary.
- Span-free pre-grouping means deterministic outside-recipe recovery can no longer rely on importer recipe-span hints. The current safe recovery paths are:
  - explicit cooking-science/explanatory prose even when `within_recipe_span=None`
  - title-case pedagogical/domain headings such as `How Salt Works`
  - short domain-plus-explanation fragments and endorsement-credit lines that clearly read as cookbook knowledge rather than navigation
- Empty-shell rejection must stay narrower than "zero ingredients and zero instructions". Title-plus-yield/time stubs are still real recipes and should survive even when the grouped span body is short or split awkwardly.
- `HOWTO_SECTION` now means recipe-internal subsection structure only, and the whole book may legitimately use zero of them. Keep chapter/topic/book headings and explanatory cookbook section headers out of that label even when the text looks like a heading.
- `INSTRUCTION_LINE` now means recipe-local procedural steps for the current recipe only. Cookbook advice, explanatory prose, and action-verb guidance outside a concrete recipe procedure should stay candidate `OTHER` unless they are obvious junk that should be excluded.
- If line-role prompt work starts drifting, keep the checked-in prompt assets and Python fallback strings aligned; preview/live mismatch here is a documentation/runtime bug, not a scoring nuance.
