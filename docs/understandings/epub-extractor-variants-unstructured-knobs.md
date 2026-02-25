---
summary: "Plain-English guide to EPUB extractor modes (unstructured/legacy/markdown/markitdown) and the unstructured-only knobs (parser, skiphf, pre)."
read_when:
  - "When choosing EPUB extraction settings (`epub_extractor`) for an import"
  - "When reading an all-method benchmark slug that includes `parser`, `skiphf`, or `pre`"
  - "When EPUB results change after tweaking extraction knobs"
---

# What Part Of The Pipeline This Changes

When you import an EPUB, the first step is to turn the book into an **ordered list of small text chunks** called **blocks**.

Everything after that (finding recipe boundaries, pulling out ingredients/instructions, writing outputs) runs on those blocks.

So these settings mainly change:

- where block boundaries land (one big block vs many smaller blocks)
- what metadata each block carries (useful for debugging)
- how easy it is for later steps to recognize headings/lists/tables

## Two words that show up a lot

- **Spine item**: an EPUB is a bundle of many HTML/XHTML files. The *spine* is the book's "table of contents order" for those files (usually chapters/sections).
- **Block**: one extracted piece of text (a paragraph, heading, list line, or table row) plus metadata about where it came from.

# `epub_extractor`: Four Ways To Turn EPUB Into Blocks

Only one extractor runs per import.

## `unstructured` (default)

What it does:

- Runs the Unstructured library on each spine item.
- Unstructured tries to understand structure (titles, list items, tables) instead of only reading raw HTML tags.
- Produces blocks with lots of traceability fields (many `unstructured_*` features, stable keys, and a diagnostics JSONL).

What it is good for:

- General-purpose EPUB imports.
- When you want the richest debugging trail (why a line became a heading, why blocks split/merged).

Downsides:

- Can be slower than the simpler extractors.
- Some books have weird HTML, so you may need to tune `parser`, `skiphf`, and `pre`.

## `legacy`

What it does:

- Uses BeautifulSoup to scan common block-like HTML tags (paragraphs, headings, list items, table cells).
- Emits one block per "leaf" element (it avoids emitting both a container and its nested child blocks).
- Strips obvious bullet prefixes like `- ` and `• `.

What it is good for:

- A simpler, more literal baseline when `unstructured` feels over-processed.
- Speed and predictability (fewer moving parts).

Downsides:

- Less semantic understanding (it mostly follows tags; it does not do header/footer detection).

## `markdown`

What it does:

- Converts each spine item's HTML into Markdown.
- Then parses that Markdown into blocks using simple rules:
  - `# Heading` lines become heading blocks
  - `- list item` / `1. list item` lines become list blocks
  - other text becomes paragraph blocks
- Uses `pandoc` if it is installed; otherwise it falls back to the Python `markdownify` library.

What it is good for:

- EPUBs where the HTML is messy, but the HTML->Markdown conversion produces cleaner structure.
- When you want "line numbers" in the diagnostics (each block knows which markdown lines it came from).

Downsides:

- HTML detail is lost during conversion (it is a "best effort" translation).
- Results can vary depending on whether `pandoc` is available.

## `markitdown`

What it does:

- Converts the whole EPUB file to one big Markdown document using `markitdown` (`MarkItDown(enable_plugins=False)`).
- Then parses that Markdown into blocks (also with line numbers).
- Writes the whole-book Markdown text as a raw artifact (`markitdown_markdown.md`) so you can inspect exactly what the parser saw.

What it is good for:

- Very noisy XHTML where a whole-book Markdown normalization gives cleaner block boundaries.
- Debugging and manual inspection (you get the Markdown file).

Downsides:

- Whole-book only: it cannot be split into parallel spine-range jobs.
- It is not part of the shared HTML cleanup path (`markitdown` blocks do not go through the same post-cleanup as the other HTML-based extractors).

# How Extraction Actually Runs (Step By Step)

This is the "shape" of the pipeline for each extractor.

## For `unstructured`

1. Read each spine item's XHTML/HTML.
2. Apply `pre` (HTML preprocessing) to clean/split the XHTML before Unstructured sees it.
3. Apply `parser` and `skiphf` when calling Unstructured's `partition_html(...)`.
4. Convert Unstructured "elements" into repo Blocks (with many `unstructured_*` traceability fields).
5. Run shared post-extraction cleanup that removes obvious noise blocks and may split multi-line blocks into multiple blocks.

## For `legacy`

1. Read each spine item's XHTML/HTML.
2. Parse tags and emit blocks from "leaf" block-like tags.
3. Run the same shared post-extraction cleanup as `unstructured`.

## For `markdown`

1. Read each spine item's XHTML/HTML.
2. Convert HTML -> Markdown (`pandoc` if present, else `markdownify`).
3. Parse Markdown -> blocks (with `markdown_line_start` / `markdown_line_end`).
4. Run the same shared post-extraction cleanup as `unstructured`.

## For `markitdown`

1. Convert the full EPUB -> one big Markdown string.
2. Parse Markdown -> blocks (with `md_line_start` / `md_line_end`).
3. (No shared HTML post-extraction cleanup step for this path.)

# Unstructured-Only Knobs (`parser`, `skiphf`, `pre`)

These only matter when `epub_extractor=unstructured`.

If you are using `legacy`, `markdown`, or `markitdown`, these knobs do not change anything.

They show up in all-method benchmark slugs like:

- `extractor_unstructured__parser_v2__skiphf_true__pre_br_split_v1`

## `parser`: `v1` or `v2`

This is Unstructured's HTML parser version.

Where it lives:

- Run setting key: `epub_unstructured_html_parser_version`
- CLI: `--epub-unstructured-html-parser-version`
- Env var: `C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION`

What it changes:

- The value is passed into Unstructured as `html_parser_version=...`.
- When you pick `v2`, the code also "shapes" the HTML a bit so the v2 parser behaves more consistently:
  - ensures there is a real `<html>` and `<body>`
  - adds `class="Document"` to the `<body>` when missing

Practical effect:

- Changing `parser` can change how Unstructured splits and labels elements, which changes your block boundaries.

Rule of thumb:

- Start with `v1` (default).
- Try `v2` if `v1` seems to merge too much together or miss obvious structure.

## `skiphf`: `true` or `false`

This tells Unstructured to try to remove repeating headers and footers.

Where it lives:

- Run setting key: `epub_unstructured_skip_headers_footers`
- CLI: `--epub-unstructured-skip-headers-footers` / `--no-epub-unstructured-skip-headers-footers`
- Env var: `C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS`

What it changes:

- Passed into Unstructured as `skip_headers_and_footers=...`.
- It is meant to remove things like:
  - page numbers
  - running chapter titles
  - repeated "copyright" footers

Tradeoff:

- It can remove real content if that content repeats and looks like a header/footer.

Rule of thumb:

- Keep it `false` unless you see obvious repeated junk in the extracted blocks.

## `pre`: `none`, `br_split_v1`, or `semantic_v1`

This is HTML preprocessing that runs before Unstructured sees the spine XHTML.

Where it lives:

- Run setting key: `epub_unstructured_preprocess_mode`
- CLI: `--epub-unstructured-preprocess-mode`
- Env var: `C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE`

Modes:

- `none`: do not modify the HTML.
- `br_split_v1`: parse and normalize the HTML before partitioning:
  - removes obvious noise tags (`script`, `style`, `noscript`, `svg`)
  - drops obvious TOC/nav and pagebreak elements
  - splits `<p>`, `<div>`, and `<li>` tags that contain `<br>` into multiple separate tags
  - removes empty tags created by the split
- `semantic_v1`: currently an alias of `br_split_v1` (same behavior today). It exists so the project can evolve semantic preprocessing later without breaking old configs.

Why this matters:

- Many EPUBs use `<br>` for "one item per line" content (especially ingredients).
- Splitting on `<br>` can help Unstructured output cleaner, more granular blocks.

# Variant Count (Why You See So Many Combinations)

For EPUBs, there are:

- 1 variant each for: `legacy`, `markdown`, `markitdown`
- 12 possible variants for `unstructured`:
  - `parser`: 2 options (`v1`, `v2`)
  - `skiphf`: 2 options (`false`, `true`)
  - `pre`: 3 options (`none`, `br_split_v1`, `semantic_v1`)

So: `2 x 2 x 3 = 12`.

Note: `semantic_v1` and `br_split_v1` behave the same today, but they are kept as separate labels so the project can evolve.

# Performance Note: Splitting/Parallelism

- `unstructured`, `legacy`, and `markdown` can be split into spine-range jobs and run in parallel, then merged.
- `markitdown` cannot be split by spine ranges, so it must run as a single whole-book job.

# Debugging: Where To Look (Raw Artifacts)

When you import an EPUB, the tool writes debug artifacts under:

- `data/output/<run>/raw/epub/<source_hash>/`

Common artifacts (filenames are usually `locationId + extension`):

- `full_text.json`: the final block list used downstream (text + metadata).
- `unstructured`:
  - `unstructured_elements.jsonl` (one row per Unstructured element)
  - `raw_spine_xhtml_0000.xhtml` (raw spine XHTML)
  - `norm_spine_xhtml_0000.xhtml` (the XHTML after `pre` normalization)
- `legacy`: `legacy_elements.jsonl` (one row per emitted HTML element).
- `markdown`: `markdown_blocks.jsonl` (one row per markdown-derived block, with line numbers).
- `markitdown`:
  - `markitdown_markdown.md` (the whole-book Markdown)

