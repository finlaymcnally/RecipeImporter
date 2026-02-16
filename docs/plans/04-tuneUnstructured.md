# ExecPlan Tune Unstructured for EPUBs

## Goal

Improve EPUB ingestion quality by using `unstructured` in a way that preserves the structure recipe parsing needs (titles, ingredient lines, instruction steps, section headers), without adding brittle “magic” or forcing downstream stages to compensate for poor upstream extraction.

This plan assumes:
- `epub_extractor=unstructured` is already wired into `cookimport/plugins/epub.py`.
- `cookimport/parsing/unstructured_adapter.py::partition_html_to_blocks(...)` exists and already emits `unstructured_elements.jsonl` diagnostics.
- The rest of the pipeline work (signals, segmentation improvements, eval harness, etc.) is happening elsewhere as you described.

## Why EPUBs fail even after adding Unstructured

EPUB HTML in the wild often encodes “one item per line” using `<br>` inside a single `<p>` (or uses CSS classes instead of semantic tags). Unstructured’s HTML partitioning is intentionally browser-like about whitespace normalization, which can collapse line breaks you actually need (especially `<br>`-driven lists).

So “best way for EPUBs” usually means:
- Pre-normalize EPUB spine HTML into more semantic/partitionable structures before feeding it to Unstructured.
- Pass the right partitioning options for HTML and explicitly capture metadata you’ll need later.
- Add regression fixtures for the specific EPUB failure modes (BR-lists, nested lists, faux headings).

## Acceptance Criteria

A. On a small canary set of representative EPUB chapters (real or synthetic fixtures):
- BR-separated ingredient lists become multiple blocks (not one mega-block).
- List items remain one per block (nested lists don’t squash into a single element).
- Recipe titles and subheaders become headings with sensible levels.

B. Diagnostics become more actionable:
- For any block, you can trace back to: spine_index, element_index, stable_key, category, category_depth, parent_id, and key “why” metadata (especially emphasis).

C. No silent fallbacks:
- If `epub_extractor=unstructured`, errors are loud and surfaced; optional fallbacks must be explicit and logged.

## Plan of Work

### Milestone 0 — Lock a “known-bad” EPUB pattern into fixtures

You need at least one reproducible case where the current unstructured path fails, otherwise “tuning” is guesswork.

Work:
- Create a synthetic HTML fixture that mimics common EPUB cookbook patterns:
  - Ingredients in a single `<p>` separated by `<br/>`
  - Instructions in a single `<p>` separated by `<br/>` or numbered lines
  - Faux headings stored as `<p class="title-ish">...</p>` or bold spans
  - Optional: nested list case

Add these fixtures to tests (no copyrighted EPUB needed):
- `tests/fixtures/epub_html/br_ingredients.xhtml`
- `tests/fixtures/epub_html/br_instructions.xhtml`
- `tests/fixtures/epub_html/nested_list.xhtml`
- `tests/fixtures/epub_html/faux_heading.xhtml`

Validation:
- Add a “current behavior” test that demonstrates the failure (marked xfail if you need a red test first).
- Confirm you can run the adapter directly in tests without staging a full EPUB.

### Milestone 1 — Add explicit Unstructured HTML options wiring

The goal is to make Unstructured behavior a controlled input, not an implicit default that changes when the dependency changes.

Work:
1) Add settings and env vars (names are suggestions; match your Settings conventions):
- `epub_unstructured_html_parser_version`: `"v1" | "v2"` (default to current behavior initially)
- `epub_unstructured_skip_headers_footers`: bool (default False)
- `epub_unstructured_preprocess_mode`: `"none" | "br_split_v1" | "semantic_v1"` (default `"none"` initially)

2) Thread these options from:
- `Settings` / `cookimport.json`
- env vars (e.g., `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`, `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`)
- into the EPUB importer’s call site where it invokes `partition_html_to_blocks(...)`.

3) In `partition_html_to_blocks(...)`, accept an optional options object:
- `partition_html_to_blocks(html, spine_index, source_location_id, *, options: UnstructuredHtmlOptions | None = None)`

4) Ensure conversion report metadata includes the chosen values as primitives (pickle-safe):
- `unstructured_version` as string
- `unstructured_html_parser_version`
- `unstructured_preprocess_mode`

Validation:
- Unit test: options propagate to diagnostics metadata (write them to the sidecar meta json or the report).
- No behavior change yet if defaults are “current”.

### Milestone 2 — Implement EPUB HTML pre-normalization for BR-based lists

This is the “EPUB cheatcode” for Unstructured: feed it HTML that actually contains separable blocks.

Work:
1) Create a new module:
- `cookimport/parsing/epub_html_normalize.py`

2) Implement:
- `normalize_epub_html_for_unstructured(html: str, *, mode: str) -> str`

Mode: `br_split_v1` (first, smallest win)
- Parse with BeautifulSoup (already in your stack).
- For each block-ish tag (`p`, `div`, maybe `li`) that contains `<br>`:
  - Split its contents on `<br>` boundaries into multiple sibling tags of the same name.
  - Treat consecutive `<br><br>` as “blank line” and drop empty segments.
  - Keep original attributes if safe (class/id), but avoid duplicating IDs (strip `id` on split siblings).
- Remove empty tags created by splits.
- Wrap fragments into `<html><body>...</body></html>` if needed so partitioning is consistent.

Important invariants:
- Deterministic: same input HTML => same normalized output.
- Idempotent: applying normalization twice yields the same HTML (or at least an equivalent tree).

3) Wire into EPUB unstructured path in `cookimport/plugins/epub.py`:
- When extractor is unstructured:
  - `html_norm = normalize_epub_html_for_unstructured(html_raw, mode=settings.epub_unstructured_preprocess_mode)`
  - Partition `html_norm` (not the raw HTML).

4) Diagnostics:
- If diagnostics are enabled, write *both*:
  - `raw_spine_xhtml/{spine_index:04d}.xhtml`
  - `norm_spine_xhtml/{spine_index:04d}.xhtml`
  This is the fastest way to debug why a chapter still fails without rereading the epub container.

Validation:
- Unit tests for normalization:
  - `<p>a<br/>b<br/>c</p>` becomes 3 blocks after partitioning (and thus 3 Blocks).
  - Double application doesn’t keep splitting forever.
- Integration-ish test:
  - Run `partition_html_to_blocks(normalized_html)` and assert one block per ingredient line.

### Milestone 3 — Use Unstructured metadata better in the adapter

Once you’ve got the right “block boundaries”, improve the *signals* you feed downstream.

Work (in `cookimport/parsing/unstructured_adapter.py`):
1) Emphasis-aware font weight
- Unstructured emits `emphasized_text_contents` and `emphasized_text_tags`.
- Compute a simple “mostly-bold” heuristic:
  - If tags include `"b"` (or contain `"b"` in combined tags like `"bi"`)
  - And emphasized_text coverage ratio >= 0.85 of the element text length
  - Then set `Block.font_weight` to your “bold” representation (700 if numeric, `"bold"` if that’s what you use).
- Store raw emphasis metadata in `Block.features` for audit:
  - `unstructured_emphasis_tags`
  - `unstructured_emphasis_contents`

2) List depth and heading depth
- Persist these explicitly in features (even if signals recompute):
  - `unstructured_category_depth`
  - `unstructured_parent_id`
- For `ListItem`, treat `category_depth` as list nesting depth hint.
- For `Title`, continue using `category_depth+1` clamped to 1..6 for `heading_level`.

3) Defensive splitting for squashed list items
Even if upstream Unstructured is “supposed” to handle it, keep a defensive shim:
- If `element.type == ListItem` and `"\n"` is in element.text:
  - Split on newline, create multiple blocks, preserve metadata, increment element_index suffix for stable_key.

4) Make stable keys reflect preprocessing version
If your stable_key is currently `loc:spine:e{index}`, keep that, but add (in metadata/report, not in the key itself) the preprocess mode and html_parser_version so you don’t compare apples to oranges during diffs.

Validation:
- Unit test: a “nested list squashed” input yields multiple ListItem blocks.
- Unit test: a bold-only faux heading line becomes a bold block (even if Unstructured calls it NarrativeText).

### Milestone 4 — Evaluate HTML parser version and choose a default

Unstructured’s `partition_html` supports different parser versions; the right choice for cookbooks depends on whether you prefer more granularity or more merged elements.

Work:
1) Add a small harness command (or reuse your existing debug tooling):
- `cookimport debug-epub-extract <book.epub> --spine 12 --variants`
Variants should run:
- preprocess `none` vs `br_split_v1`
- html parser `v1` vs `v2` (if supported in your pinned version)

2) For each variant, output:
- blocks.jsonl (text + key features)
- unstructured_elements.jsonl
- summary metrics:
  - number of blocks
  - p95 block length
  - count of blocks containing multiple ingredient-like quantities
  - count of “ingredient_line”-classified blocks (if roles exist)

3) Decide defaults:
- If `br_split_v1` is a clear win for ingredients/instructions, flip default from `none` to `br_split_v1`.
- Choose parser v1/v2 based on cookbook-specific wins (not general doc parsing).

Validation:
- Run the harness on at least:
  - 1 EPUB with br-based ingredient formatting
  - 1 EPUB with proper `<ul><li>` ingredient formatting
  - 1 EPUB with heavy front matter / ToC noise

### Milestone 5 — Documentation and guardrails

Work:
- Update your EPUB ingestion docs:
  - explain preprocess modes and when to use them
  - explain what diagnostics artifacts to inspect
- Add troubleshooting:
  - “If ingredients look like one giant paragraph, enable BR splitting.”
- Add a minimal “version lock” note:
  - pin unstructured and record its version per run for reproducibility.

Validation:
- A new dev can follow docs to reproduce an EPUB extraction issue and see raw vs normalized HTML + element diagnostics.

## Progress

- [ ] (2026-02-16T00:00Z) Add synthetic EPUB HTML fixtures that reproduce BR-list and faux-heading patterns.
- [ ] (2026-02-16T00:00Z) Wire explicit unstructured HTML options into Settings, env vars, EPUB importer, and adapter.
- [ ] (2026-02-16T00:00Z) Implement `normalize_epub_html_for_unstructured(..., mode="br_split_v1")` and make it idempotent.
- [ ] (2026-02-16T00:00Z) Persist raw + normalized spine XHTML artifacts when diagnostics are enabled.
- [ ] (2026-02-16T00:00Z) Enhance adapter to use emphasis metadata for bold detection and to defensively split squashed list items.
- [ ] (2026-02-16T00:00Z) Add harness to compare parser versions and preprocess modes on real EPUB canaries.
- [ ] (2026-02-16T00:00Z) Flip defaults based on canary results and update docs.

## Surprises and Discoveries

- None yet. Update this section whenever a real EPUB reveals a new pattern (e.g., CSS-based headings, ingredient tables, multi-column layouts in XHTML, etc.).

## Decision Log

- (2026-02-16) Pre-normalize EPUB HTML before Unstructured rather than trying to “fix it downstream” in segmentation, because block boundaries are the coordinate system everything else depends on.
- (2026-02-16) Keep preprocess improvements behind a mode flag first, then flip defaults only after canary validation.
- (2026-02-16) Treat Unstructured options as explicit settings for reproducibility; record them in run metadata so benchmark/eval artifacts remain interpretable.
