---
summary: "What each EPUB extractor mode does (`unstructured`, `legacy`, `markitdown`) and when to use each."
read_when:
  - "When choosing an EPUB extractor for a run"
  - "When debugging extractor-specific output differences"
---

# EPUB Extractor Types

`cookimport` supports three EPUB extractor modes via `epub_extractor` (`--epub-extractor` / `C3IMP_EPUB_EXTRACTOR`).

## Important Architecture Clarification

Current behavior is a **single mutually-exclusive extractor choice**, not a two-stage toggle.

- Actual shape today:
  - `EPUB -> [unstructured | legacy | markitdown] -> Block stream -> shared recipe segmentation/extraction`
- Not how it currently works:
  - `EPUB -> optional markitdown pre-pass -> (legacy or unstructured)`

So `markitdown` is its own extractor path, not an on/off preprocessor in front of `legacy`/`unstructured`.

## `unstructured` (default)

What it does:
- Parses each spine HTML document with Unstructured (`partition_html`) through `cookimport/parsing/unstructured_adapter.py`.
- Produces `Block` records with semantic traceability fields like `unstructured_category`, `unstructured_element_index`, and `unstructured_stable_key`.
- Adds shared parsing signals and can emit diagnostics artifact `unstructured_elements.jsonl`.

Block creation logic:
- Entry path: `EpubImporter._extract_docpack_with_ebooklib(...)` or `_extract_docpack_with_zip(...)` with `extractor == "unstructured"`.
- For each included spine document:
  - Decode HTML text.
  - Call `partition_html_to_blocks(html, spine_index, source_location_id)`.
- In `partition_html_to_blocks(...)`:
  - Run `unstructured.partition.html.partition_html(text=html)`.
  - Iterate elements in extracted order.
  - Normalize each element's text (`cleaning.normalize_text`); skip empty text.
  - Build one `Block` per remaining element.
  - Map Unstructured category to `BlockType` (`Table` -> `TABLE`, `Image` -> `IMAGE`, most others -> `TEXT`).
  - Add traceability features (`spine_index`, `unstructured_*`, `source_location_id`).
  - Mark headings when category is `Title` (`is_heading=True`, `heading_level` from `category_depth + 1`, clamped to `1..6`).
  - Mark list items when category is `ListItem`.
- Back in importer code, each block also gets:
  - `extraction_backend=unstructured`
  - shared `signals.enrich_block(...)` features.

Best for:
- Most EPUBs, especially when HTML structure is noisy but still parseable as HTML.
- Runs where richer traceability metadata is important.

Operational notes:
- Supports spine-range split jobs (`start_spine` / `end_spine`).

## `legacy`

What it does:
- Uses BeautifulSoup tag traversal in `cookimport/plugins/epub.py` (`p/div/h1..h6/li/...`) and converts text nodes into blocks.
- Adds heading/list features plus shared parsing signals.

Block creation logic:
- Entry path: `EpubImporter._extract_docpack_with_ebooklib(...)` or `_extract_docpack_with_zip(...)` with `extractor == "legacy"`.
- For each included spine document:
  - Parse HTML bytes with BeautifulSoup (`lxml`, fallback `html.parser`).
  - Call `_parse_soup_to_blocks(soup, spine_index, extraction_backend="legacy")`.
- In `_parse_soup_to_blocks(...)`:
  - Scan block-level tags: `p`, `div`, `h1..h6`, `li`, `td`, `th`, `blockquote`.
  - Skip container tags that contain nested block tags (prevents duplicate parent+child block emission).
  - Normalize leaf tag text; skip empty text.
  - Build one `Block` per remaining leaf tag (`type=TEXT`, `html=str(elem)`).
  - Set `font_weight="bold"` for heading tags or tags containing `strong`/`b`; otherwise `"normal"`.
  - Add `extraction_backend=legacy`, plus `spine_index` when available.
  - Run shared `signals.enrich_block(...)`.
  - Add EPUB tag-derived flags:
    - heading tags -> `is_heading=True`, `heading_level`
    - `li` tags -> `is_list_item=True`.

Best for:
- Simpler fallback behavior when you want minimal dependencies on Unstructured semantics.
- Cases where Unstructured-specific behavior is not desired.

Operational notes:
- Supports spine-range split jobs (`start_spine` / `end_spine`).

## `markitdown`

What it does:
- Converts the whole EPUB to markdown first using MarkItDown (`MarkItDown(enable_plugins=False)`), then parses markdown lines into blocks.
- Adds line-level provenance fields `md_line_start` / `md_line_end` and `extraction_backend=markitdown`.
- Emits raw markdown artifact `markitdown_markdown.md`.

Block creation logic:
- Entry path: `EpubImporter._extract_docpack_markitdown(...)` when `extractor == "markitdown"`.
- Convert full EPUB file to markdown text via `convert_path_to_markdown(path)`.
- Parse markdown with `markdown_to_blocks(markdown_text, source_path, extraction_backend="markitdown")`.
- In `markdown_to_blocks(...)` (line-driven parser):
  - Normalize line endings and iterate lines with 1-based line numbers.
  - Blank line => flush current paragraph buffer into one paragraph block.
  - Heading line (`#`..`######`) => one heading block (`is_heading=True`, `heading_level`, `font_weight="bold"`).
  - Ordered/unordered list line => one list-item block (`is_list_item=True`).
  - Otherwise accumulate into paragraph buffer; consecutive non-empty non-heading/list lines become one paragraph block.
  - Every emitted block includes `extraction_backend`, `md_line_start`, `md_line_end`, and `source_location_id`.
- Back in importer code, each block also gets shared `signals.enrich_block(...)` features.

Best for:
- EPUBs where raw HTML markup is highly irregular and markdown normalization gives cleaner block boundaries.
- Investigations where line-based provenance back to markdown is useful.

Operational notes:
- Whole-book mode only: does **not** support spine-range split jobs.
- Stage and benchmark split planners intentionally disable EPUB splitting when `epub_extractor=markitdown`.

## Shared Join Point After Block Creation

After any extractor finishes building `list[Block]`, the rest of EPUB recipe processing is shared:
- `assign_block_roles(blocks)`
- candidate detection (`_detect_candidates`)
- recipe field extraction (`_extract_fields`)
- standalone tip/topic extraction and non-recipe block collection.

So extractor differences are mostly about block boundaries + block metadata, not separate downstream recipe engines.

## How Recipe Boundaries Are Chosen With `markitdown`

`markitdown` does **not** have a separate recipe-boundary engine. It only changes how EPUB content is turned into `Block`s.

Current flow:
- `EPUB -> markitdown markdown conversion -> markdown-to-blocks -> shared EPUB segmentation heuristics`

What this means in practice:
- Start/end detection is still done by `EpubImporter` candidate logic (`_detect_candidates`, `_backtrack_for_title`, `_find_recipe_end`), the same family of heuristics used after other EPUB block extractors.
- Signals such as `is_yield`, `is_ingredient_header`, and instruction/ingredient likelihood still drive anchor and boundary decisions.
- So `markitdown` can change boundaries **indirectly** (by producing cleaner/different blocks), but it does not run an additional custom boundary pass.

## Quick Selection Guidance

- Start with `unstructured` for general-purpose ingestion and richer semantic metadata.
- Try `legacy` if you want the simpler HTML-tag parser behavior.
- Try `markitdown` when HTML parsing is brittle and markdown conversion yields cleaner recipe structure.
