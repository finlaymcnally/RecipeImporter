https://chatgpt.com/c/6992a49d-36cc-8329-8b33-0cf9e120ab19

# EPUB extraction quick wins: common bugs, guardrails, and fixes

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `PLANS.md` at the repository root.

## Purpose / Big Picture

Right now the EPUB path is producing low-quality or unstable text streams, which then cascades into “everything struggles”: candidate segmentation can’t find recipe boundaries, ingredient parsing sees mangled lines, step linking can’t match mentions, and any future LLM repair becomes expensive because it is compensating for upstream garbage.

After this work, staging an EPUB (`cookimport stage ...`) should produce a cleaner, more deterministic `Block` stream (the linear list of extracted text units used throughout ingestion), with fewer common EPUB failure modes. The fixes here are intentionally “quick wins”: small, high-leverage changes that improve the text and structure signal before any ML/LLM layer.

You will be able to see this working in three ways:

1) New regression tests that build tiny synthetic EPUBs which reproduce known extraction bugs (and then pass once fixes are in).
2) Improved conversion reports (warnings/errors) and new EPUB-specific health warnings when extraction looks suspicious.
3) A human can open `raw/epub/<source_hash>/full_text...` and see “obviously better” lines: fewer merged bullets, fewer broken words, less TOC/nav noise, and cleaner ingredient-like lines.

## Progress

- [x] (2026-02-16 00:00Z) Drafted ExecPlan for “EPUB-specific extraction bugs and fixes (quick wins)”.
- [ ] Add a minimal EPUB fixture builder for tests (synthetic EPUBs generated in-test; no copyrighted books).
- [ ] Add failing regression tests for the top EPUB bug classes we want to fix (soft hyphens, `<br>` collapsing, bullets, TOC/nav duplication, pagebreak noise, table-ish ingredients, encoding/whitespace).
- [ ] Implement text normalization improvements for EPUB input (in one shared place used by both extractors).
- [ ] Implement structural extraction quick wins (line-splitting, bullet stripping, element filtering) with extractor-agnostic post-processing where possible.
- [ ] Implement EPUB extraction health checks + report warnings (sober “logic check” guardrails).
- [ ] Validate on at least one real EPUB (locally provided by developer) with both extractors (`unstructured` and `legacy`) and record observations.
- [ ] Update internal docs / developer notes on how to debug EPUB extraction with the new artifacts and warnings.

## Surprises & Discoveries

- None yet (plan authored only).

## Decision Log

- Decision: Prefer a shared, extractor-agnostic “EPUB postprocess” pass over duplicating fixes in both the unstructured and legacy extraction paths.
  Rationale: Most EPUB bugs manifest as malformed text/lines after HTML parsing; fixing once reduces drift between extractors and keeps behavior consistent.
  Date/Author: 2026-02-16 / plan author

- Decision: Use synthetic EPUBs in tests rather than checking in real cookbooks.
  Rationale: Avoid licensing issues and keep tests deterministic and minimal.
  Date/Author: 2026-02-16 / plan author

## Outcomes & Retrospective

- Not started yet.

## Context and Orientation

This repository implements a plugin-based ingestion pipeline (`cookimport`) that converts various source formats into structured recipe data.

Key terms as used in this repo:

- EPUB: A ZIP container with metadata (`.opf`) and a “spine” (an ordered list of XHTML/HTML documents representing reading order).
- Spine item: One XHTML/HTML document referenced by the spine. Many cookbooks have one “chapter” per spine item.
- Extractor: The implementation used to turn EPUB HTML into `Block`s.
  - `unstructured` extractor: Uses Unstructured to partition HTML elements, then maps elements → Blocks.
  - `legacy` extractor: Uses existing HTML parsing heuristics to build Blocks directly.
- Block: The pipeline’s low-level unit of extracted content (roughly one paragraph/list item/heading line). Blocks are later enriched with signals and used for segmentation into recipes.

Relevant code areas (paths are repository-relative):

- `cookimport/plugins/epub.py`
  Owns extractor selection (`--epub-extractor` / `C3IMP_EPUB_EXTRACTOR`), spine iteration (ebooklib + zip fallback), and calls into extraction helpers to produce Blocks.
- `cookimport/parsing/unstructured_adapter.py`
  Maps Unstructured elements to `Block` objects; emits `unstructured_elements.jsonl` diagnostics and applies `cleaning.normalize_text()`.
- `cookimport/parsing/cleaning.py`
  Contains `cleaning.normalize_text(...)`, the shared normalization function used during ingestion.
- `cookimport/parsing/signals.py`
  Adds derived features to Blocks (heading flags, ingredient-likeness, instruction-likeness, yield/time detection, etc.).
- `cookimport/parsing/block_roles.py`
  Adds deterministic `block_role` labels that help downstream scoring and chunking.
- `cookimport/core/models.py`
  Defines `Block`, `RecipeCandidate`, `ConversionResult`, and report models.
- Tests currently exist around the unstructured adapter in `tests/test_unstructured_adapter.py` (expand with EPUB bug regression coverage).

Important existing EPUB behavior (from current repo docs):

- The EPUB plugin reads spine in order, supports split ranges (`start_spine`, `end_spine`), and adds `spine_index` to blocks for deterministic merge ordering.
- The unstructured extractor partitions per spine doc (not `partition_epub`), stores `element_id` + `stable_key` for traceability, and emits a `raw/epub/<source_hash>/unstructured_elements.jsonl` diagnostics artifact.
- Unstructured is pinned (tested) to a stable range; do not silently fall back between extractors if errors occur.

This plan assumes the general ingestion pipeline exists and is working end-to-end; we are improving the EPUB extraction “front end” so everything downstream has better inputs.

## Plan of Work

We will treat this as a “sober second thought” pass on EPUB extraction: add guardrails that detect when extraction is clearly broken, and implement a small set of high-impact fixes that address the most common EPUB-specific bugs.

We will do this in four milestones. Each milestone ends with something you can run and observe.

### Milestone 1: Repro harness and regression tests for EPUB extraction bugs

Goal: Create tiny synthetic EPUBs that reproduce common bugs and lock in expectations as tests. These tests should fail before fixes, then pass after fixes.

Work:

- Add a test helper that builds a minimal valid EPUB at runtime in a temp directory. The helper should let the test specify:
  - Spine order (list of XHTML strings + filenames).
  - Optional `nav` doc in manifest/spine (to reproduce TOC duplication issues).
  - Optional table content, `<br>` content, soft-hyphen content, etc.
- Add a dedicated test module, for example:
  - `tests/test_epub_extraction_quickwins.py`
- For each bug class below, add one synthetic EPUB test case and assert on the resulting Blocks:
  - Soft hyphens and invisible characters: `\u00ad` (soft hyphen), NBSP `\u00a0`, zero-width joiners.
  - `<br>` collapsing: ingredient lines separated by `<br/>` inside one `<p>`.
  - Bullet/list marker noise: `• 1 cup sugar` or `– 1 cup sugar` should be normalized so signals can detect quantity.
  - TOC/nav duplication: nav documents and TOC-like sections should not pollute Blocks (either skipped or clearly marked noise).
  - Pagebreak/anchor noise: elements used for page numbers or internal anchors should not become blocks.
  - Table-ish ingredients: `<table><tr><td>1 cup</td><td>sugar</td></tr>...</table>` should produce usable line(s).
  - Encoding/whitespace weirdness: ensure output has normalized spaces and line endings.

Design principle: Prefer testing stable invariants over exact full-block dumps. For example, assert “we got 3 ingredient-like blocks with these normalized texts” rather than requiring an exact count of every heading in the synthetic EPUB.

Proof:

- Running `python -m pytest -k epub_extraction_quickwins` should execute these tests.
- Before implementation, commit the tests in a failing state (or mark expected failures temporarily), then make them pass as fixes land.

### Milestone 2: Shared EPUB text normalization upgrades (quick wins)

Goal: Make the raw text the pipeline sees less “EPUB-weird” without harming other formats.

Work:

- Identify the single shared normalization entry point used for EPUB blocks.
  - The unstructured path already uses `cleaning.normalize_text(...)` (per repo docs).
  - Ensure the legacy path also uses the same normalization (if not, wire it in).
- Extend normalization for EPUB realities. Do this either by:
  - Adding a dedicated `normalize_epub_text(text: str) -> str`, called by EPUB code paths, or
  - Extending `normalize_text` with a mode flag (for example `normalize_text(text, mode="epub")`).
  Choose the approach that keeps non-EPUB behavior stable and minimizes surprises.

The normalization must cover, at minimum:

- Remove soft hyphen characters (`\u00ad`) entirely. They frequently appear inside words due to publisher hyphenation and break ingredient parsing (“but\u00adter”).
- Convert NBSP (`\u00a0`) to regular spaces.
- Remove/normalize common invisible Unicode formatting characters that break tokenization (zero-width spaces/joiners).
- Normalize whitespace runs (collapse repeated spaces, normalize newlines).
- Normalize common Unicode fractions and fraction entities to ASCII-friendly forms.
  - Example: “½” → “1/2”, “⅓” → “1/3”.
  - Keep it conservative: do not attempt numeric evaluation here; just normalize representation.
- Normalize “fancy” punctuation that often breaks downstream heuristics:
  - Curly quotes → straight quotes.
  - En/em dashes used as bullets → a consistent leading marker or removed when at line start.

Add unit tests for each normalization rule. Prefer tests directly on the normalization function plus at least one integration test that verifies the normalized result appears in extracted Blocks.

Proof:

- The synthetic EPUB tests around soft hyphens, NBSP, unicode fractions pass.
- A human inspecting `raw/epub/.../full_text...` sees words no longer contain stray soft hyphens.

### Milestone 3: Structural EPUB extraction fixes (line boundaries, bullets, tables, and noise)

Goal: Fix the most common “structure” problems where HTML is technically present but the conversion into Blocks destroys boundaries needed by recipe segmentation.

Work:

1) `<br>` and “multi-line paragraph” splitting

Many EPUBs encode lists (especially ingredients) as a single paragraph with `<br/>` separators. If extraction turns that into one Block, downstream heuristics see a huge blob and fail.

Implement a post-extraction rule (shared for both extractors if possible):

- If a Block’s normalized text contains hard line breaks that came from `<br>` (or a `<br>`-like join), split it into multiple Blocks.
- Preserve provenance fields that support traceability:
  - Keep `spine_index`.
  - For unstructured blocks, preserve `stable_key` and `element_id` where possible; if you must generate new per-split identifiers, do so deterministically (for example append `:line0`, `:line1`).
- Only split when doing so is likely correct:
  - For example, split when there are multiple short lines and at least one line looks ingredient-like (starts with quantity/unit) or list-like.
  - Avoid splitting narrative paragraphs with occasional newline characters.

2) Bullet/list marker cleanup

For `li` items and bullet-prefixed lines, remove the bullet prefix so signals can detect quantities and ingredients.

- Strip common leading bullet markers and dash variants: “•”, “‣”, “–”, “—”, “-” when used as a bullet.
- Keep a safe fallback: only strip at the beginning of the line and only when followed by whitespace.

3) Table extraction (minimal viable)

Recipes sometimes use tables for ingredients (“amount | ingredient”). Quick win approach:

- When a table is encountered by the extractor:
  - Prefer outputting one Block per row, joining cell text with a single space or “ — ”.
  - Alternatively, if Unstructured yields a Table element with already-linearized text, ensure the adapter maps it into Blocks in a way that preserves row-ish boundaries.
- Add at least one synthetic EPUB test that includes a simple two-column table and asserts we get ingredient-like lines.

4) Noise filtering: nav/TOC/pagebreak/footnotes

EPUBs include non-content documents and inline structural fragments that pollute the block stream.

Implement conservative noise suppression:

- At the spine-doc level:
  - Skip known nav documents from extraction if they are present in spine/manifest (the TOC can produce thousands of noisy blocks).
  - If the nav doc must be kept for some reason, ensure it is tagged/typed as non-recipe noise and excluded from candidate segmentation input.
- At the element level:
  - Drop/ignore elements that are clearly not recipe content: `script`, `style`, `noscript`, `svg`.
  - Drop/ignore pagebreak markers:
    - Common patterns: elements with `epub:type="pagebreak"`, `role="doc-pagebreak"`, class names containing “pagebreak”.
  - Optionally suppress footnote backrefs/superscripts if they are standalone blocks and do not carry meaningful text.

Because the pipeline values traceability, prefer “do not create Blocks for these” over creating Blocks and later deleting them, unless you also emit a debug artifact that proves what was removed.

Proof:

- The synthetic nav/TOC EPUB test no longer produces a massive TOC-like block stream.
- The `<br>` splitting and bullet cleanup tests pass.
- Ingredient-likeness signals improve on the synthetic fixtures (at least “starts_with_quantity” behaves).

### Milestone 4: EPUB extraction health checks and “logic check” guardrails

Goal: Add a cheap, sober sanity layer that flags when extraction is probably broken, even if the pipeline technically “works”.

Work:

Add an EPUB-specific health check that runs immediately after Blocks are extracted and normalized, before candidate segmentation.

This health check should compute small metrics and emit warnings into the conversion report, such as:

- `epub_empty_block_rate_high`: too many empty/near-empty blocks after normalization.
- `epub_duplicate_block_rate_high`: too many repeated blocks (often indicates nav duplication or looped spine).
- `epub_suspiciously_low_text`: extremely low total extracted characters for a book-sized EPUB (suggests fixed-layout / image-only / DRM / extraction failed).
- `epub_too_many_super_long_blocks`: many blocks above a size threshold (often indicates `<br>` collapse or poor element segmentation).
- `epub_no_ingredient_like_blocks`: zero ingredient-like blocks across a large corpus (strong sign the extractor is not producing list items cleanly).

Implement this as a function in a parsing module (for example `cookimport/parsing/epub_health.py`) and call it from the EPUB importer after extraction for both extractors.

Keep it conservative: warnings should not block conversion by default. If you want a strict mode, implement it as an opt-in env/CLI flag later; for now, warnings are enough.

Optionally (but recommended), emit a small debug artifact alongside other raw artifacts:

- `raw/epub/<source_hash>/epub_extraction_health.json`
  - Contains the computed metrics and the top N repeated normalized lines with counts (helpful for triage).

Proof:

- Running `cookimport stage data/input/problem.epub` produces either no EPUB health warnings (good) or warnings that are obviously helpful and actionable (bad EPUBs).
- The warnings are visible in the conversion report JSON and/or console output.

## Concrete Steps

All commands assume you are in the repository root.

Environment bootstrap (only if needed to get the CLI working):

    python -m venv .venv
    . .venv/bin/activate
    pip install -e ".[dev]"

Run targeted tests while iterating:

    python -m pytest -k epub_extraction_quickwins

Run the CLI on a local EPUB (place one at `data/input/book.epub`):

    cookimport stage data/input/book.epub --epub-extractor unstructured

Then compare legacy behavior for the same file:

    cookimport stage data/input/book.epub --epub-extractor legacy

Inspect artifacts from a run:

- Find the newest run folder under `data/output/<timestamp>/`.
- Open the raw EPUB artifacts under something like:
  - `data/output/<run>/raw/epub/<source_hash>/...`
- For unstructured extractor, confirm diagnostics exist:
  - `.../unstructured_elements.jsonl`
- For both extractors, locate the extracted block dump (often named `full_text` in raw artifacts) and spot-check:
  - ingredient lines are separate
  - words are not broken by soft hyphens
  - nav/TOC is not dominating content

If there is an existing `cookimport inspect` command for EPUB, use it as part of triage; if not, do not add a new command in this plan unless it is needed to validate health checks.

## Validation and Acceptance

This work is accepted when all of the following are true:

1) Tests:
- `python -m pytest -k epub_extraction_quickwins` passes.
- Existing test suite remains green (at minimum, the unstructured adapter tests remain green).

2) Bug-class coverage:
- Each of the bug classes in Milestones 1–3 has at least one regression test that demonstrates the previous failure mode and now passes.

3) Extractor parity:
- The shared normalization and postprocess behavior is applied to both extractors where appropriate.
- Running staging on the same sample EPUB in both modes does not produce wildly different block counts or obvious boundary breakage. Some differences are acceptable, but the quick-win invariants must hold (no soft hyphen words, no TOC spam, ingredients split sensibly).

4) Guardrails:
- EPUB health check warnings exist and are emitted into the conversion report.
- For a “known bad” synthetic EPUB (or a deliberately broken fixture), the health check produces at least one warning.
- For a normal synthetic EPUB, the health check does not produce false positives.

5) Human sanity check:
- A human can open the extracted blocks artifact for a sample EPUB and agree the output is more recipe-friendly than before (cleaner lines, less obvious noise).

## Idempotence and Recovery

- All changes must be safe to run repeatedly. Synthetic EPUB tests generate their EPUB files in temporary directories and do not modify the repo working tree outside `pytest` temp paths.
- Staging runs should remain deterministic for the same input file and extractor mode (block ordering stable; spine indices stable).
- If a normalization change unexpectedly harms non-EPUB inputs, revert by:
  - Moving EPUB-specific behavior behind an explicit `mode="epub"` parameter, and
  - Leaving the default behavior unchanged for other formats.

## Artifacts and Notes

Expected artifacts for unstructured EPUB runs include:

- `raw/epub/<source_hash>/unstructured_elements.jsonl`
  - Used for regression diffing and debugging element → Block mapping.
- A block dump artifact (often recorded as `full_text`), containing Blocks with at least:
  - text
  - type
  - features including `spine_index`
  - any stable identifiers available (element_id / stable_key)

Add (optional but recommended) artifact:

- `raw/epub/<source_hash>/epub_extraction_health.json`
  - A compact JSON object with computed health metrics and top repeated normalized lines.

When you add new warnings, record the exact warning keys and what they mean in the code comments near the health check implementation. Keep warning strings stable; they become part of “how we triage extraction quality”.

## Interfaces and Dependencies

Do not introduce new external dependencies for these quick wins unless there is a strong justification. Prefer to leverage existing dependencies already in the repo: ebooklib, BeautifulSoup/lxml, and Unstructured (already integrated).

New or updated interfaces (names are prescriptive; adapt only if existing code has a clear established naming convention):

1) In `cookimport/parsing/cleaning.py`:

- Add one of the following patterns:

Option A (preferred when you want minimal impact outside EPUB):

    def normalize_epub_text(text: str) -> str:
        """
        EPUB-specific normalization: soft hyphen removal, NBSP normalization, unicode fraction normalization,
        and conservative punctuation cleanup.
        """

Option B (if `normalize_text` is clearly the single entry point already used everywhere):

    def normalize_text(text: str, *, mode: str = "default") -> str:
        """
        When mode="epub", apply EPUB-specific normalization additions.
        """

2) Add a shared postprocess module (extractor-agnostic):

- `cookimport/parsing/epub_postprocess.py`

    def postprocess_epub_blocks(blocks: list["Block"]) -> list["Block"]:
        """
        Apply EPUB-specific structural fixes:
        - split <br>-collapsed blocks into multiple blocks (with deterministic IDs)
        - strip bullet prefixes
        - drop/skip obvious noise blocks (pagebreak markers, empty blocks after normalization)
        """

This function must be called from `cookimport/plugins/epub.py` after extraction for both extractors.

3) Add a health check module:

- `cookimport/parsing/epub_health.py`

    def compute_epub_extraction_health(blocks: list["Block"]) -> dict:
        """
        Return metrics and warning candidates. The caller decides how to attach warnings to reports.
        """

    def epub_health_warnings(health: dict) -> list[str]:
        """
        Return stable warning keys for the conversion report.
        """

Wire warnings into whatever report structure exists (likely `ConversionReport.warnings`).

4) Tests:

- `tests/test_epub_extraction_quickwins.py`
  - Contains synthetic EPUB builder helper(s) and regression tests for each bug class.

When implementing, keep traceability in mind:

- For blocks produced by unstructured, preserve `stable_key` / `element_id` semantics.
- When splitting one block into multiple, maintain deterministic derived identifiers and keep the original source association discoverable (for example via a new `features["split_from"]` field or consistent stable key suffixing).

---

Plan change log (keep this at the bottom as the plan evolves):

- 2026-02-16: Initial version created to cover “Common EPUB-specific extraction bugs and fixes (quick wins)” with a focus on shared normalization, shared postprocess, regression tests, and extraction health guardrails.
