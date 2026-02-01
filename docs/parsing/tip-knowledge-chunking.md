# Implement knowledge chunking with highlight-based tip mining

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repo root; this plan must be maintained in accordance with it. &#x20;

## Purpose / Big Picture

Today, `cookimport` extracts “tips” as small spans, which has good precision on tip-shaped sentences but is recall-limited and frequently clips the surrounding explanation, emits orphan aphorisms, and leaks front-matter blurbs into the output.  &#x20;

After this change, `cookimport stage …` will additionally produce “knowledge chunks”: longer, coherent, cookbook-structure-respecting sections of non-recipe text. Each knowledge chunk will:

- be labeled as `knowledge`, `narrative`, or `noise` (so blurbs/jacket copy do not pollute knowledge extraction),
- include provenance back to the original block stream,
- include “highlights” (the existing tip miner output) and a “tip density” score, but the chunk boundary is not decided by punctuation or one-sentence “tips”.
  This implements the recommended strategy: chunk first, mine highlights inside chunks, and distill from the whole chunk (optionally via the existing mocked LLM layer).  &#x20;

You will know it is working by staging a cookbook and finding new output artifacts (e.g. `chunks.md` and `c{index}.json`) where:

- front-matter blurbs like “This beautiful, approachable book…” are classified as `narrative`/`noise`, not `knowledge`,&#x20;
- clipped “tips” are no longer emitted as the unit of output; instead, they appear as highlights inside a larger coherent chunk that contains the missing explanation,&#x20;
- headings like “USING SALT” group the following material into a single section chunk rather than many disconnected tips. &#x20;

## Progress

- [x] (2026-01-31) Baseline: run `cookimport stage` on a representative cookbook and save current `tips.md` + tip JSON outputs for comparison.

- [x] (2026-01-31) Add chunk data model(s) and writer output folder + human-readable `chunks.md`.
  - Added `ChunkLane`, `ChunkBoundaryReason`, `ChunkHighlight`, `KnowledgeChunk` models to `core/models.py`
  - Added `write_chunk_outputs()` to `staging/writer.py`
  - Output: `chunks/<workbook>/c{index}.json` and `chunks.md`

- [x] (2026-01-31) Implement deterministic heading-driven chunker (section chunks) that operates on the existing block stream.
  - Created `cookimport/parsing/chunks.py` with `chunk_non_recipe_blocks()` function
  - Uses ALL CAPS, colon-terminated, and title-case heading detection
  - Maintains section path stack for nested headings
  - Handles stop headings (INDEX, ACKNOWLEDGMENTS, etc.)

- [x] (2026-01-31) Implement lane assignment (`knowledge`/`narrative`/`noise`) including a front-matter/blurb filter.
  - `assign_lanes()` scores chunks based on knowledge/narrative/noise signals
  - Knowledge: imperatives, modals, mechanisms, diagnostics, temps/times
  - Narrative: first-person, anecdotes, opinions
  - Noise: praise adjectives, book/marketing language, quote-only content

- [x] (2026-01-31) Integrate existing tip miner as "highlights" inside each knowledge chunk; compute tip density and aggregate tags.
  - `extract_highlights()` runs tip miner on knowledge chunks
  - Computes `tip_density` (highlights per 1000 chars)
  - Aggregates tags from all highlights

- [x] (2026-01-31) Add boundary refinements (hard/medium/soft), callout chunking (TIP/NOTE/Variation boxes), and max/min chunk sizing.
  - `ChunkingProfile` configures min/max chars, heading levels, stop headings
  - Callout prefixes (TIP:, NOTE:, etc.) create boundaries
  - Format mode changes (prose ↔ bullets) trigger soft boundaries
  - `merge_small_chunks()` combines undersized chunks

- [x] (2026-01-31) Add tests (unit + small fixture) proving the three failure modes are mitigated; ensure legacy tip extraction still works.
  - Created `tests/test_chunks.py` with 18 tests covering:
    - Heading detection and section paths
    - Lane assignment for knowledge/narrative/noise
    - Highlight extraction and tag aggregation
    - Chunk merging and boundary reasons
  - All 172 tests pass (including existing tests)

- [ ] (2026-01-31) (Optional) Add "distill chunk" path using the existing mocked LLM layer, with caching and a CLI flag to enable.

## Surprises & Discoveries

* Observation: Topic candidates from conversion don't preserve original block structure, so we convert them to blocks for chunking.
  Evidence: Created `chunks_from_topic_candidates()` bridge function to convert TopicCandidate → Block → KnowledgeChunk.

* Observation: Stop sections (INDEX, ACKNOWLEDGMENTS) need to skip ALL following blocks until next major heading, not just the heading itself.
  Evidence: Added `in_stop_section` flag to track and skip content within stop sections.

* Observation: The chunking integrates cleanly with existing architecture by running after conversion and populating `result.chunks`.
  Evidence: Salt Fat Acid Heat EPUB: 466 chunks (424 knowledge, 37 narrative, 5 noise), 224 highlights extracted.

## Decision Log

- Decision: Keep the existing tip miner, but demote it to highlights inside chunk outputs; do not remove legacy `tips.md` initially.
  Rationale: This preserves current functionality while enabling the new “coherent chunk → distill” pipeline; it matches the recommended hybrid approach.&#x20;
  Date/Author: 2026-01-31 / assistant
- Decision: Boundaries are structure-first (headings/sections), not punctuation-first.
  Rationale: Prevents clipped spans and orphan aphorisms; cookbook structure is a stronger signal than sentence shape. &#x20;
- Decision: Add explicit `narrative` and `noise` lanes and route blurbs/front matter away from knowledge extraction.
  Rationale: The current output includes jacket-copy-like praise blurbs; they should be excluded from knowledge distillation. &#x20;
- Decision: Prefer deterministic chunking; only add LLM refinement behind a flag and with caching.
  Rationale: Stable, debuggable output is required for tuning and regression testing; LLM can improve quality but must not be required for baseline correctness.&#x20;

## Outcomes & Retrospective

### First End-to-End Success (2026-01-31)

Tested on `saltfatacidheat.epub`:
- **466 total chunks** generated with proper boundaries
- **Lane classification working**: 424 knowledge, 37 narrative, 5 noise
- **224 highlights** extracted from knowledge chunks

#### Failure Mode #1: Praise blurbs routed to noise ✓
```
### c0 🔇 NOISE
**(untitled)**
"This beautiful, approachable book not only teaches you how to cook..."
—Alice Waters
```

#### Failure Mode #2: Headings group content coherently ✓
```
### c3 📚 KNOWLEDGE
**SALT**
Section: SALT > Using Salt
Blocks: [24..35] (12 blocks)
```
The SALT section now groups 12 blocks together rather than emitting disconnected tips.

#### Failure Mode #3: Aphorisms become highlights, not standalone ✓
Short tip-like content appears inside larger knowledge chunks as highlights with `selfContained` flag, not as the primary unit of output.

### Files Added/Modified
- `cookimport/core/models.py`: Added ChunkLane, ChunkBoundaryReason, ChunkHighlight, KnowledgeChunk models
- `cookimport/parsing/chunks.py`: New module with chunking pipeline
- `cookimport/staging/writer.py`: Added write_chunk_outputs()
- `cookimport/cli.py`: Integrated chunk generation into stage command
- `tests/test_chunks.py`: 18 unit tests for chunking functionality

## Context and Orientation

`cookimport` is a multi-format ingestion engine (PDF/EPUB/Excel/Text/etc.) that stages recipes into structured outputs and also extracts standalone “Kitchen Tips” and topics. &#x20;

For unstructured sources, the system uses a linear stream of `Block` objects (paragraphs/headings/list items) enriched with “signals” like `is_heading`, `heading_level`, `is_instruction_likely`, and `is_ingredient_likely`.&#x20;
Tip extraction currently:

- atomizes text into “atoms” (paragraph/list/header) and preserves neighbor context for repair,&#x20;
- extracts candidate spans via prefixes/anchors (e.g. “TIP:”, “Make sure…”) and repairs incomplete spans by merging neighbors,&#x20;
- judges candidates with a tipness score (imperatives, modals, benefit cues vs narrative cues and recipe overlap) and a generality score,&#x20;
- tags tips via a taxonomy mapping (tools/techniques/ingredients),&#x20;
- writes results to `data/output/<timestamp>/tips/<workbook_stem>/` including `t{index}.json` and `tips.md`.&#x20;

The newest sample output shows the main issues this plan targets: front-matter blurbs extracted as tips, headings emitted as tips, and short aphorisms without payload. &#x20;

## Plan of Work

Implement a new “Knowledge Chunking” subsystem that runs on the same non-recipe block stream currently sent to tip extraction. The subsystem will produce coherent chunks and then run the existing tip miner inside each knowledge chunk to produce highlights and scoring, rather than treating mined spans as the final output unit.&#x20;

This should be done in small, verifiable milestones:

1. get a minimal chunk artifact written end-to-end,
2. make chunk boundaries respect cookbook structure (headings and callouts),
3. reliably separate knowledge vs narrative/noise,
4. attach highlights and scoring,
5. prove the failure modes are fixed with tests and fixture output diffs,
6. optionally enable LLM distillation over chunks using the existing mocked `cookimport/llm/` layer.

Throughout, preserve provenance and debuggability: every chunk should explain why it started/ended and which source blocks it contains.&#x20;

## Concrete Steps

All commands below are run from the repository root.

0. Optional dependency wiring (no behavior change).

   - Add optional dependencies (extras, or a separate requirements file) for:
     - `pysbd`
     - `spacy`
     - `sentence-transformers`
     - `scikit-learn`
     - `bertopic`
     - `umap-learn`
     - `hdbscan`
   - Ensure all imports are guarded and the default staging pipeline runs without these packages installed.
   - Add explicit CLI/profile flags for each optional feature so behavior is easy to reason about (e.g. `--sentence-splitter=pysbd`, `--topic-similarity=embedding`, `--lane-classifier=...`).

1. Establish baseline behavior and locate the current tip pipeline.

   - Run staging on a known cookbook input:
     python -m cookimport.cli stage data/input/\<your\_file>
     (This is the documented entrypoint; if the repo also exposes a `cookimport stage …` console script, that is acceptable too.) &#x20;
   - Find the most recent output folder in `data/output/…` and open:
     - `tips/<workbook_stem>/tips.md`
     - a handful of `tips/<workbook_stem>/t*.json`
   - Save a copy of the baseline `tips.md` snippet that includes:
     - the praise blurb tip(s),
     - “USING SALT” section,
     - the “pepper inverse” aphorism line,
       so you can compare after chunking. &#x20;

2. Add chunk artifacts (models + writer) without changing chunking logic yet.

   - In `cookimport/core/models.py`, add Pydantic models that are parallel to `TipCandidate`/`TopicCandidate`:
     - `ChunkLane`: enum with values `knowledge`, `narrative`, `noise`.
     - `ChunkBoundaryReason`: string enum; start with a small set: `heading`, `recipe_boundary`, `callout_seed`, `format_mode_change`, `max_chars`, `noise_break`, `end_of_input`.
     - `ChunkHighlight`: stores a reference to a mined tip/highlight and its location within the chunk (at minimum: `text` and `source_block_ids`; optionally offsets if easily available).
     - `ChunkCandidate` (or `KnowledgeChunk`): fields:
       - `id` (stable within output: `c{index}`),
       - `lane`,
       - `title` (derived from heading path),
       - `section_path` (list of headings),
       - `text` (the concatenated chunk text),
       - `block_ids` (source block indices or provenance ids),
       - `aside_block_ids` (optional; blocks inside the chunk classified as narrative-aside even if the overall chunk lane is `knowledge`),
       - `excluded_block_ids_for_distillation` (optional; blocks to omit when building `distill_text`),
       - `distill_text` (optional; the text actually sent to any distiller, derived from chunk blocks minus excluded/aside blocks),
       - `boundary_start_reason` / `boundary_end_reason`,
       - `tags` (aggregate, reuse the existing tag schema where possible),
       - `tip_density` (float or simple counts),
       - `highlights` (list of `ChunkHighlight`),
       - `provenance` (reuse the repo’s existing provenance conventions; do not invent an incompatible format).
         This mirrors how `TipCandidate` is used today.&#x20;
   - In `cookimport/staging/writer.py`, add a new output folder sibling to `tips/`, e.g.:
     - `data/output/<timestamp>/chunks/<workbook_stem>/`
     - `c{index}.json`
     - `chunks.md` (human-readable summary like `tips.md`)
       Preserve the existing `tips/` outputs unchanged in this milestone.&#x20;
   - The initial `chunks.md` format should be optimized for debugging:
     - chunk id, lane, title/section path
     - start/end boundary reasons
     - tip density (even if 0 for now)
     - first \~300–800 chars of chunk text
     - list of included block ids
       Keep it deterministic so diffs are stable.

3. Implement the minimal deterministic chunker (heading-driven “section chunks”).

   - Create a new module `cookimport/parsing/chunks.py` with a single entry function, for example:
     def chunk\_non\_recipe\_blocks(blocks: list[Block], \*, profile: ChunkingProfile) -> list[ChunkCandidate]
     Keep it pure (no IO); writer stays in `staging/writer.py`.

   - Implement “section chunk” as the default winner:

     - treat a heading block as a hard boundary and a chunk seed,
     - include “heading + everything until the next peer/parent heading” in the same chunk, not many small chunks,
     - do not let punctuation create boundaries.

   - Add an explicit fallback for weak structure / no headings:

     - detect “heading sparsity” (e.g. no headings for N blocks or >X chars),
     - switch to a micro-chunk mode that splits by medium boundaries + topic continuity heuristics rather than headings,
     - record `boundary_*_reason` as `topic_pivot` or `max_chars` (never “sentence end”).
       Suggested deterministic topic-pivot heuristic (good enough to start):
     - Provide two backends (configurable):
       - `lexical`: TF-IDF / bag-of-words overlap between a rolling window of the last K blocks and the next block.
       - `embedding` (if `sentence-transformers` is installed): SBERT embeddings per block and cosine similarity between adjacent blocks.
     - Split when similarity drops below a threshold **and** at least one medium boundary cue is present (blank line, list-mode change, callout seed, definition-like `:` pattern).
     - Merge when similarity stays high and no hard boundary is crossed.
     - Cache per-block features (TF-IDF vectors or embeddings) keyed by block text hash + model/version so re-runs are cheap and deterministic.



- Use the existing `Block & Signals` architecture:
  - determine heading blocks via existing `is_heading` / `heading_level` signals, and maintain a `section_path` stack as you iterate.&#x20;
- Define a `ChunkingProfile` (similar in spirit to `TipParsingProfile`) that contains:
  - `min_chars`, `max_chars` (start with something like 800 and 6000, but make it configurable),
  - heading levels considered “major” vs “minor” (use repo-specific heading levels; validate with a fixture),
  - a small list of “stop headings” for noise-heavy parts (e.g. INDEX, ACKNOWLEDGMENTS) but only as a default suggestion; keep it overrideable.
  - `sentence_splitter`: `none|pysbd|spacy` (default: `none`), for within-block sentence segmentation.
  - `topic_similarity_backend`: `none|lexical|embedding` (default: `lexical` in heading-sparse fallback; `none` otherwise).
  - `embedding_model_name` + `embedding_cache_dir` (only used when `topic_similarity_backend=embedding`).
  - `similarity_thresholds` (merge/split thresholds) and `window_k` for heading-sparse mode.
  - `lane_classifier_path` (optional; if present and enabled, use it to override/augment heuristic lane scoring).
- Ensure every chunk carries explicit boundary reasons (start and end).

4. Add lane assignment and a front-matter/blurb filter.
   - Add lane scoring functions in `cookimport/parsing/signals.py` or a new `cookimport/parsing/lane.py`:

     - `knowledge_score`: imperatives/modals/diagnostic cues/temps-times-quantities/mechanisms (“because/so that/therefore”) (some already exist in tip scoring logic).&#x20;
     - `narrative_score`: first-person voice markers and anecdote cues (some are already “negative signals” in tip judging).&#x20;
     - `noise_score` / `blurb_score`: praise adjectives + “book” + “teaches you” + quote-only patterns, matching the observed blurbs.

   - Optional (high leverage): supervised lane classifier (requires `scikit-learn` and a trained model artifact).

     - Train a lightweight classifier (logistic regression / linear SVM) from Label Studio exports.
     - Features: existing heuristic signals + TF-IDF bag-of-words + optional embedding features.
     - Inference policy: classifier can *override* heuristics only when confidence is high; otherwise fall back to heuristics.

   - Optional (feature enrichment): if `spacy` is installed, add POS/dependency-derived features to lane scoring and self-containedness checks (imperatives, modals, causal clauses).

   - Apply lane assignment at the section/chunk level (not per sentence), so one stray anecdote line does not flip an entire technique section.

   - Make an explicit, consistent choice for “knowledge → anecdote → knowledge” inside one section:

     - default behavior: keep a single `knowledge` chunk if knowledge dominates, but mark the anecdote blocks as `aside_block_ids` and add them to `excluded_block_ids_for_distillation`.
     - distillation (if enabled) must use `distill_text` and ignore aside blocks.
     - if an aside grows beyond a configurable size (e.g. `narrative_aside_split_chars`), optionally split it into a sibling `narrative` chunk that inherits the same `section_path`.

- Explicitly route the sample praise-blurb content to `noise` (or `narrative`, but consistently) and verify it no longer appears under `knowledge`.&#x20;
  - Add “quote gate” and “intro/foreword gating” as heuristics, but do not blanket-drop introductions; treat them as likely narrative and keep them available for inspection.&#x20;

5. Integrate the existing tip miner as highlights and compute tip density.
   - In `cookimport/parsing/tips.py`, add a mode that can accept a pre-bounded chunk of text/blocks and return:

     - highlight spans (existing `TipCandidate` outputs, but marked as highlights),
     - tags (taxonomy-derived),
     - a per-highlight “self-contained” flag if implemented.
       The goal is to reuse the existing miner without reusing its boundary choice.&#x20;

   - Implement a “standalone tip gate” but in the chunk pipeline, not as the main output:

     - if a mined span is single-sentence and lacks action/mechanism/example, do not promote it as a standalone tip; keep it only as a highlight.&#x20;
       This specifically addresses aphorisms like “the inverse isn’t necessarily so.”&#x20;

   - Add deterministic span expansion (within chunk context) for mined highlights that appear clipped:

     - expand forward (and optionally backward) while still inside the same section, until a hard boundary or `max_chars`.
     - stop on heading, recipe boundary, major formatting break, or topic jump heuristic.

   - Add two cheap sanity checks as explicit heuristics (optional but recommended):

     - Sentence splitting backend (enabler): use `pysbd` (preferred for messy OCR) or `spacy` sentence segmentation to evaluate self-containedness and to choose expansion stop points within a block.
     - Minimum standalone length: if a mined highlight is promoted as a standalone tip anywhere (now or later), require `min_standalone_chars` / `min_standalone_tokens`; if below, force expansion first, otherwise demote to highlight-only.
     - Contrastive-marker expansion trigger: if a highlight contains “but/however/except/unless/instead/not necessarily/inverse” (configurable list), force expansion to include the surrounding explanation within the chunk; if expansion is blocked by a hard boundary, keep as highlight-only.



- Compute `tip_density` for each chunk:
  - simplest: `num_highlights / max(1, chunk_chars/1000)` and also store raw counts.
- Aggregate tags at the chunk level by unioning highlight tags, and (optionally) adding tags derived directly from chunk text via the existing taxonomy module.&#x20;

6. Add boundary refinements: hard/medium/soft, callouts, and format-mode changes.

   - Implement the boundary hierarchy:
     - Hard boundaries: major headings, recipe boundaries, obvious non-content blocks (ToC/index/page headers/footers).&#x20;
     - Medium boundaries: subheadings, labeled callouts (“TIP:”, “NOTE:”, “Variation:”, “Troubleshooting:”), and format mode changes (prose → bullets/numbered/definition-like).&#x20;
     - Soft boundaries: paragraph breaks and small asides; do not split chunks on these.&#x20;
   - Add “sidebar chunk” behavior:
     - when a callout is detected, create a separate chunk that “inherits” the parent section title (store it in `section_path` and/or `title`) so distillation has context.&#x20;
   - Add “topic pivot marker” detection as a medium boundary heuristic (“Now that you understand…”, “In the next section…”).&#x20;
   - Enforce min/max chunk size:
     - if a section grows beyond `max_chars`, split at the best medium boundary within the window (fallback: split at paragraph boundary, but record reason `max_chars`).

7. Tests, fixtures, and regression-proofing.

   - Add unit tests under `tests/` for:
     - heading-path stack behavior and section chunking,
     - lane assignment of blurbs and quote-only content,
     - highlight gating (aphorisms become highlights, not standalone),
     - deterministic output ordering and stable ids.
   - Add a small text fixture derived from the sample output patterns:
     - include a praise blurb,
     - include a heading like “USING SALT” with several paragraphs,
     - include an aphorism line and an immediately following explanatory paragraph,
     - include a callout like “TIP:” or “NOTE:”.
       Use it to assert chunk boundaries and lanes match expectations. The sample `tips extract example.md` provides concrete snippets to mirror. &#x20;
   - Ensure legacy `tips.md` generation remains unchanged until you explicitly decide to deprecate it (that decision would be recorded here later).

8. (Optional) Add distillation over chunks via the existing mocked LLM layer.

   - If `cookimport/llm/` already provides an interface (currently mocked), add a new function like:
     distill\_knowledge\_chunk(chunk: ChunkCandidate, \*, highlights: list[ChunkHighlight]) -> DistilledKnowledge
     Keep it behind a CLI flag (e.g. `--distill-chunks`) so core staging stays deterministic and offline-capable.&#x20;

   - Cache distillation results keyed by:

     - input file hash + chunk id + chunk text hash + prompt version,
       so repeated runs are idempotent and cheap.

   - Operationalize “tip density as a cheap prioritizer for LLM time” via an explicit distillation policy:

     - Only distill `knowledge` lane chunks.
     - Sort candidate chunks by `tip_density` descending (tie-breaker: chunk length, then id).
     - Provide two selection modes (configurable):
       - `top_k`: distill the top K chunks by density.
       - `threshold`: distill only chunks with `tip_density >= min_tip_density`.
     - Always emit a small run report (e.g. `distillation_selection.json` or a section in `chunks.md`) listing:
       - which chunks were selected,
       - their densities,
       - why they were selected (mode + parameters).

## Validation and Acceptance

Run:

- `python -m cookimport.cli stage data/input/<cookbook>`&#x20;

Acceptance is met when, in the newest `data/output/<timestamp>/` folder:

1. A new folder exists: `chunks/<workbook_stem>/` containing:

   - `chunks.md`
   - multiple `c{index}.json` files (at least one `knowledge` chunk when the input contains technique sections).

2. `chunks.md` demonstrates structure-first grouping:

   - the “USING SALT” heading produces a single coherent chunk (or a small number of coherent chunks if split by max size), not many tiny outputs.&#x20;

3. Front matter blurbs similar to “This beautiful, approachable book…” appear as `noise` or `narrative`, not `knowledge`.&#x20;

4. Aphorisms like “the inverse isn’t necessarily so” are not emitted as standalone “final knowledge” items; they appear only as highlights inside a larger knowledge chunk that contains nearby context.&#x20;

5. Existing `tips/<workbook_stem>/tips.md` continues to be produced (until explicitly deprecated), so downstream users are not broken.&#x20;

6. Tests pass:

   - run the repo’s standard test command (likely `python -m pytest` if present) and expect all tests pass, including new chunking tests.

7. If distillation is enabled (optional flag), it follows the selection policy:

   - only selected chunks are distilled,
   - selection is explainable and recorded in output artifacts,
   - re-running does not re-distill unchanged chunks (cache hit).

## Idempotence and Recovery

- Staging already writes to a timestamped output directory; the chunking outputs must follow the same convention so re-running stage does not overwrite prior runs.&#x20;
- The chunker must be deterministic given the same input block stream and profile settings:
  - stable ordering,
  - stable `c{index}` numbering,
  - stable `chunks.md` formatting.
- If optional distillation is enabled, it must be cached and keyed so repeated runs reuse results.
- If optional embeddings / classifiers are enabled:
  - cache per-block embeddings (or other expensive features) keyed by block text hash + model name/version,
  - persist enough metadata (model name, thresholds, feature flags) into output artifacts to make runs reproducible,
  - fail gracefully (fall back to lexical heuristics) if optional deps are missing.
- If a heuristic causes unexpected splits or mis-lane assignments, the recovery path is:
  - inspect `chunks.md` (boundary reasons + lanes),
  - add/adjust a profile override (book-specific) rather than hardcoding one-off hacks,
  - add a regression test fixture.

## Artifacts and Notes

As you implement, paste short “before vs after” excerpts (indented) into this section for the three targeted failure modes:

- praise blurb routed to `noise`,
- “USING SALT” grouped coherently,
- aphorism no longer standalone.
  Keep each excerpt under \~30 lines to avoid turning this plan into a data dump.

## Interfaces and Dependencies

### Optional third-party NLP/ML accelerators (behind flags)

These are **optional** dependencies that can materially improve boundary decisions and lane classification. The default pipeline should remain deterministic and should run without them.

- **pySBD (********`pysbd`********)**: robust sentence boundary detection for messy OCR / book typography. Use inside an atom/block for:
  - self-containedness checks (is this highlight a complete thought?),
  - “expand or demote” logic when a highlight is clipped,
  - finding the nearest sensible expansion stop within a block.
- **spaCy (********`spacy`********)**: tokenization + POS/dependency parsing + sentence segmentation. Use to enrich existing heuristics:
  - imperative/modality detection (e.g., should/must),
  - causal/justification markers (because/so that/therefore),
  - robust sentence segmentation as an alternative to pySBD.
- **SentenceTransformers / SBERT (********`sentence-transformers`********)**: embeddings per block/atom to drive semantic cohesion decisions:
  - merge adjacent blocks when similarity stays high,
  - split when similarity drops sharply (especially in heading-sparse regions),
  - detect boilerplate/repeated blocks by clustering or near-duplicate similarity.
- **scikit-learn (********`scikit-learn`********)**: lightweight supervised models for lane classification (knowledge/narrative/noise), trained from a small labeled set exported from Label Studio.
- **BERTopic (********`bertopic`********)**: optional topic discovery / clustering across many chunks (e.g., “salt”, “emulsions”), useful for analysis and for detecting topic shifts that should block merges.
- **UMAP (********`umap-learn`********) + HDBSCAN (********`hdbscan`********)**: optional clustering / dimensionality reduction tooling (often used by BERTopic, also useful standalone).

This plan relies on the existing architecture and modules:

- `cookimport/parsing/signals.py` provides block-level signals like heading detection and instruction/ingredient likelihood.&#x20;
- `cookimport/parsing/tips.py` currently handles span extraction, repair, and judging; we will reuse it to produce highlights inside chunks. &#x20;
- `cookimport/parsing/atoms.py` provides atomization with neighbor context; reuse it if helpful for highlight span expansion.&#x20;
- `cookimport/parsing/tip_taxonomy.py` provides dictionary-based tagging; chunk tags should reuse this schema.&#x20;
- `cookimport/staging/writer.py` writes outputs; extend it to write `chunks/` artifacts.&#x20;
- The repo includes Label Studio integration for evaluation; later, consider adapting it to evaluate “containment recall” for chunking rather than exact-match tip extraction. &#x20;

Keep new code modular:

- `parsing/chunks.py` should contain chunk boundary logic and nothing about IO.
- `parsing/lane.py` (or additions in `signals.py`) should contain lane scoring and blurb/noise detection.
- `staging/writer.py` should format and persist artifacts.
- Models live in `core/models.py` alongside existing `TipCandidate`/`TopicCandidate`.&#x20;

End of initial plan (2026-01-31): created an implementation roadmap that converts tip-mining into a chunk-first pipeline with highlights, lane routing, deterministic boundaries, and regression tests, consistent with `PLANS.md` requirements.&#x20;

