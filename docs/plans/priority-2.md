# Priority 2: Shared section detection across importers (with pluggable backends)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes a PLANS.md that defines the ExecPlan format and workflow rules. Before implementing, locate it from repo root (for example with `git ls-files | rg -n "(^|/)PLANS\.md$"`), open it, and follow it to the letter. If the repo path is `docs/PLANS.md` (as suggested by the docs index), treat that as the source of truth; if the repo has a root `PLANS.md`, use that.

## Purpose / Big Picture

After this change, every importer that produces a block stream (EPUB, PDF, Text/DOCX, and any future HTML-ish importer) can run the same deterministic “section detector” to locate:

- ingredient sections (including multiple component sections like “For the frosting:”),
- instruction sections (including multiple component sections),
- optional notes/variants/nutrition sections.

The user-visible win is that section extraction becomes consistent and benchmarkable across sources: the same recipe content imported from EPUB vs PDF vs TXT yields the same section structure, and component headers like “For the glaze:” never cause false recipe splits.

This plan also incorporates all Priority-2-related tooling mentioned in `BIG PICTURE UPGRADES.md` as additional, selectable options (not replacements). Concretely, the system will support multiple section-detection and upstream-extraction backends so benchmarks can sweep combinations without deleting existing paths.

## Progress

- [x] (2026-02-25 23:59Z) Wrote this ExecPlan for Priority 2 shared section detection, including explicit integration points and optional backend options.
- [ ] Baseline: run current test suite (or targeted suites) and record green baseline output in this plan.
- [ ] Add new `cookimport/parsing/section_detector.py` contract (types + interface) and a deterministic heuristic implementation (`heuristic_v1`) with focused unit tests.
- [ ] Add a compatibility adapter so existing `cookimport/parsing/sections.py` can call the new detector (without breaking current call sites).
- [ ] Add run-config knob(s) to select section detector backend; thread it through CLI → worker → importer.
- [ ] Wire shared section detection into Text importer (`cookimport/plugins/text.py`) as a selectable option, preserving existing behavior as `legacy`.
- [ ] Wire shared section detection into EPUB importer (`cookimport/plugins/epub.py`) candidate field extraction as a selectable option, preserving existing behavior as `legacy`.
- [ ] Wire shared section detection into PDF importer (`cookimport/plugins/pdf.py`) candidate field extraction as a selectable option, preserving existing behavior as `legacy`.
- [ ] Add `transitions`-powered FSM backend (`fsm_v1`) as an additional selectable detector backend.
- [ ] Add `datasketch`-powered repeating-header/footer suppressor as an optional preprocessing stage for PDF block streams (selectable, not default).
- [ ] Add schema-first optional lane for HTML-ish inputs using `extruct`, `pyld`, `scrape-schema-recipe`, and `recipe-scrapers` as selectable backends (either via a new HTML importer plugin or via an optional branch inside Text importer).
- [ ] Add optional HTML boilerplate-removal backends (`trafilatura`, `readability-lxml`, `jusText`, `BoilerPy3`, `goose3`, `newspaper3k`) that can feed the shared section detector (selectable).
- [ ] Add optional PDF structure recovery extraction backends (`pdfplumber`, `pdftotree`, `pdf2htmlEX`, `LayoutParser`, `Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU`) that can feed the shared section detector (selectable).
- [ ] Add optional sequence-labeling backends (`python-crfsuite`, `sklearn-crfsuite`, `Chaine`, `skweak`) as selectable “label-then-span” section detector options (kept experimental and opt-in).
- [ ] Update and/or add tests that assert section outputs and “For the X” behavior across EPUB/PDF/Text fixtures.
- [ ] Run validation commands again; record results; write Outcomes & Retrospective.

## Surprises & Discoveries

(Keep this section updated during implementation.)

- Observation: (none yet)
  Evidence: (add command output, test failure snippets, or minimal repros)

## Decision Log

(Record decisions as they are made; initial decisions are captured here to avoid ambiguity for the implementer.)

- Decision: Implement a new module `cookimport/parsing/section_detector.py` and keep `cookimport/parsing/sections.py` as a compatibility layer that can delegate to the new module.
  Rationale: Existing downstream code already depends on `sections.py` (notably step-ingredient linking and staging header stripping). A compatibility layer avoids a flag day and keeps benchmarks able to compare “legacy vs new” cleanly.
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Ship multiple selectable backends (legacy, heuristic_v1, fsm_v1, plus experimental CRF/weak-labeling/schema options) behind run-config knobs.
  Rationale: The user explicitly wants new libraries to become new options (not replacements) to benchmark permutations.
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Make `heuristic_v1` the default *only if* it matches/strictly improves behavior on current fixture tests; otherwise keep default as `legacy` and require explicit opt-in.
  Rationale: This minimizes regressions while still enabling benchmarking. The decision should be revisited after the new tests/fixtures are in place.
  Date/Author: 2026-02-25 / ChatGPT

## Outcomes & Retrospective

(Write entries as milestones complete.)

- Outcome: (pending)
  Notes: (pending)

## Context and Orientation

### What “blocks” are in this repo

A “block” is the pipeline’s deterministic unit of text produced by importers (EPUB/PDF/Text). Blocks are enriched by shared parsing modules with signals such as “looks like an ingredient line” or “looks like a heading”. Importers then assemble `RecipeCandidate` objects from blocks; staging converts candidates to intermediate schema.org JSON-LD and final cookbook outputs.

Key repo areas (paths from repo root; confirm exact paths in your working tree):

- Importers (plugins): `cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`, `cookimport/plugins/text.py`
- Shared parsing primitives: `cookimport/parsing/signals.py`, `cookimport/parsing/patterns.py`, `cookimport/parsing/block_roles.py`, `cookimport/parsing/cleaning.py`
- Existing section extraction (currently downstream-biased): `cookimport/parsing/sections.py`
- Staging and section outputs: `cookimport/staging/jsonld.py` (HowToSection emission + header stripping), `cookimport/staging/writer.py` (writes `sections/...` artifacts)

From the consolidated docs, `cookimport/parsing/sections.py` already extracts ingredient/instruction headers conservatively and is used to provide section context to step-ingredient linking.:contentReference[oaicite:4]{index=4} However, Priority 2 is specifically about making section detection explicit and shared across importers (rather than scattered per importer).:contentReference[oaicite:5]{index=5}

### What Priority 2 requires (canonical requirements)

The Priority 2 requirement is to build a single deterministic function that takes a block stream (or text lines) and returns section spans for ingredients/instructions/notes, treating “sub-recipe headers” like “For the frosting:” as section headers, not recipe boundaries. The heuristics should reuse existing primitives: block roles, heading flags, unstructured category, regex patterns, and optional spaCy enrichment, with a configurable lexicon via ParsingOverrides.:contentReference[oaicite:6]{index=6}

### Why this plan mentions a lot of libraries

`BIG PICTURE UPGRADES.md` explicitly associates Priority 2 with several optional libraries/programs. The user wants every such tool to be incorporated as a new selectable option, even where similar functionality already exists. This plan therefore defines a backend/option architecture so you can benchmark:

- section detector algorithm choices (legacy vs heuristic vs FSM vs ML/semi-supervised),
- upstream extraction choices (especially for PDF and HTML-ish sources),
- and optional preprocessing/noise suppression (e.g., repeating headers).

## Plan of Work

This plan is organized into milestones. Each milestone is independently verifiable and leaves the repo in a working state.

### Milestone 0: Baseline + orientation in the actual working tree

Goal: confirm where the real code lives and capture a green baseline before changes.

Work:

1. From repo root, locate the key modules called out above:

   - `cookimport/plugins/epub.py`
   - `cookimport/plugins/pdf.py`
   - `cookimport/plugins/text.py`
   - `cookimport/parsing/sections.py`
   - `cookimport/parsing/signals.py`
   - `cookimport/parsing/patterns.py`
   - `cookimport/staging/jsonld.py`
   - `cookimport/staging/writer.py`

   If any path differs, record the differences in `Surprises & Discoveries` and update this ExecPlan so a novice can follow it.

2. Run the project’s standard test command (likely `pytest`, but confirm from repo docs). Record the output summary here.

Acceptance:

- You can point at the exact files in the working tree.
- Tests are green; the baseline output is captured.

### Milestone 1: Add a shared section detector contract + `heuristic_v1` implementation

Goal: create a new shared module that can accept a stream of blocks (or text lines) and produce explicit section spans.

End state:

- New file: `cookimport/parsing/section_detector.py`
- New test file(s): `tests/parsing/test_section_detector.py` (and/or additional fixture-based tests)
- A deterministic detector backend `heuristic_v1` that is independent of importer specifics.

Design: output should be spans over block indices, not “copied strings”. A span is an index range in the block list, because everything downstream (provenance, labeling, debug artifacts) already speaks in block indices.

Concrete additions:

1. Create `cookimport/parsing/section_detector.py` with:

   - An enum `SectionKind` with at least: `INGREDIENTS`, `INSTRUCTIONS`, `NOTES`, `NUTRITION`, `VARIANTS`, `OTHER`.
   - A dataclass `SectionSpan` with:
     - `kind: SectionKind`
     - `key: str` (normalized key such as `frosting`, used to align ingredient and instruction sections)
     - `name: str` (display name such as “For the frosting” or “Ingredients”)
     - `header_block_index: int | None` (index of the header line if present)
     - `start_block_index: int` (inclusive)
     - `end_block_index: int` (exclusive)
     - `confidence: float` (0..1, deterministic)
     - `debug: dict[str, object]` (optional, only populated when debug mode is on)
   - A dataclass `DetectedSections` with:
     - `spans: list[SectionSpan]` (in source order)
     - convenience properties or methods to get ingredient spans/instruction spans, and to map `block_index -> section_key` (or `None`).

2. Define a protocol/interface:

   - `class SectionDetector(Protocol):`
     - `name: str`
     - `detect(blocks, *, parsing_overrides=None, debug=False) -> DetectedSections`

3. Implement `HeuristicSectionDetectorV1` that follows the Priority 2 heuristics, mapped to your primitives:

   - Header lexicon matching:
     - Normalize a candidate header text by: `strip`, `casefold`, remove trailing punctuation and surrounding colons, collapse whitespace.
     - Match against a controlled vocabulary (ingredients, instructions, notes, method, directions, preparation, variations, nutrition, etc.).
     - Make this vocabulary configurable through `ParsingOverrides` (see Milestone 2).
   - List clustering:
     - Identify contiguous runs of “list-ish” blocks. For unstructured EPUB blocks, use `unstructured_category == "ListItem"` (or the repo’s equivalent). For text/PDF, approximate by “short line with no terminal period” and/or “bullet/number prefix”.
   - Ingredient morphology scoring:
     - Reuse existing regexes from `cookimport/parsing/patterns.py` and existing signals from `cookimport/parsing/signals.py` (ingredient likelihood).
     - Add a single deterministic helper in the detector module: `ingredient_morphology_score(text: str, *, overrides) -> float` that returns 0..1.
     - Score signals for: leading quantities/fractions/ranges, unit tokens, parentheticals, “to taste/as needed/for serving”, commas with prep notes.
   - Instruction morphology scoring:
     - Reuse instruction likelihood signals (and optional spaCy enrichment if already supported in `signals.py`).
     - Use simple deterministic cues: imperative verbs near start, sentence punctuation, step numbering (“1.”, “Step 2”), time/temperature patterns.
   - “For the X” / sub-recipe header handling:
     - Treat “For the X” (and short “For X”) as a subsection header candidate.
     - Decide its kind based on what follows:
       - if followed by a strong ingredient cluster → ingredient subsection
       - if followed by an instruction cluster → instruction subsection
       - else → `OTHER` (keep as literal text; do not treat as a recipe boundary)
     - Normalize key by stripping “for”, “for the”, punctuation, then slugifying (lowercase, collapse spaces, remove stopwords like “the” only at start).

4. Write unit tests in `tests/parsing/test_section_detector.py` that cover:

   - Explicit “Ingredients” and “Instructions” headers.
   - No explicit headers: detector finds ingredient and instruction clusters.
   - Multiple ingredient components with “For the frosting:” subsection.
   - Multiple instruction components with “For the frosting:” (should become instruction subsection if followed by step-like lines).
   - False-positive guard: “For the first time…” (a narrative sentence) must not create a section.

Tests should use a minimal “block” stub compatible with the real Block model. If the repo already has a `Block` dataclass/model, import it. If not, create a tiny local test helper that mimics required attributes (`text`, optional `features`, optional `unstructured_category`, optional `block_role`).

Acceptance:

- Running `pytest -q tests/parsing/test_section_detector.py` passes.
- The detector output spans are stable and deterministic.

### Milestone 2: Integrate ParsingOverrides lexicon + adapter for existing `sections.py`

Goal: make lexicon configurable via existing override mechanisms, and keep backward compatibility.

Work:

1. Locate the `ParsingOverrides` model in the repo.

   - Use: `rg -n "class ParsingOverrides" cookimport` (or equivalent).
   - If `ParsingOverrides` is a Pydantic model, add new optional fields with defaults so old overrides files remain valid.

2. Add the following override fields (names can vary, but be consistent and document in code):

   - `ingredient_section_headings: list[str] = []`
   - `instruction_section_headings: list[str] = []`
   - `note_section_headings: list[str] = []`
   - `variant_section_headings: list[str] = []`
   - `nutrition_section_headings: list[str] = []`
   - `subrecipe_header_prefixes: list[str] = ["for the", "for", "to make"]` (or empty default if you prefer)
   - `section_stopwords: list[str] = []` (optional; for normalizing keys)

   Also include a single derived “effective lexicon” function (in `section_detector.py`) that combines built-in defaults with override additions.

3. Update `cookimport/parsing/sections.py`:

   - Add a new public entry point that delegates to the new detector, for example:
     - `extract_sections_from_blocks(blocks, *, parsing_overrides=None, backend="heuristic_v1", debug=False)`
   - Keep the existing public function(s) and have them call the new one when:
     - backend is `heuristic_v1` OR
     - a new run-config selects it (Milestone 3).
   - Preserve the existing return shapes expected by step-linking; if `sections.py` currently returns a specific structure, add a shim that converts `DetectedSections` into that structure.

   Important: do not remove the old behavior yet. Keep `legacy` path as another backend so benchmarks can compare.

4. Add/adjust tests that currently exercise `cookimport/parsing/sections.py` (the docs mention `tests/parsing/test_recipe_sections.py` and step-linking tests). Ensure they still pass unchanged.

Acceptance:

- Existing tests that reference `cookimport/parsing/sections.py` remain green.
- A small new test demonstrates that `ParsingOverrides` additions influence lexicon matching (for example, adding “What you need” as an ingredient header).

### Milestone 3: Add run-config knobs for section detection backend + thread them through stage/worker/importers

Goal: make backend selection a first-class run setting so the benchmark system can permute it.

Work:

1. Locate the run settings / config model.

   The docs indicate there is a `cookimport/config/` area and that reports include `runConfig` with many knobs. Find the central run settings model used by `cookimport/cli.py` / `cookimport/cli_worker.py`.

2. Add a run setting (global is simplest) such as:

   - `section_detector_backend: str = "legacy"` (initial safe default)
     Allowed values at minimum:
     - `legacy` (current importer-specific logic)
     - `heuristic_v1` (new shared detector)
     - `fsm_v1` (transitions-based backend, Milestone 4)
     - `crf_python_v1` (Milestone 8; optional)
     - `crf_sklearn_v1` (Milestone 8; optional)
     - `skweak_v1` (Milestone 8; optional)
     - `schema_extruct_v1` (Milestone 6; optional)
     - `schema_recipe_scrapers_v1` (Milestone 6; optional)

   Also add an optional setting:
   - `section_detector_debug: bool = False` (when true, write extra artifacts).

3. Expose the knob in the CLI:

   - Add `--section-detector-backend` (or similar) to `cookimport stage` (and anywhere else stage run settings are edited interactively).
   - Ensure it is persisted in `cookimport.json` if your interactive config does so.
   - Ensure it appears in the `ConversionReport.runConfig` output.

4. Thread it into workers/importers:

   - `cookimport/cli.py` builds the worker job config; include the new setting.
   - `cookimport/cli_worker.py` receives run settings; pass to importer convert.
   - Importers can read run settings directly or via `MappingConfig` / `ParsingOverrides`; use the existing pattern in the codebase.

Acceptance:

- Running `cookimport stage --help` shows the new flag.
- A stage run report includes `runConfig.section_detector_backend`.
- A small unit test or CLI test asserts the knob is wired (if the repo has CLI tests; otherwise add a targeted test for run settings serialization).

### Milestone 4: Wire shared section detector into Text/EPUB/PDF importers (as selectable options)

Goal: make section detection shared across importers, but keep current behavior as an option.

End state:

- Text importer can extract sections via:
  - `legacy` (existing text section extraction)
  - `heuristic_v1` (new shared detector)
  - `fsm_v1` (Milestone 5)
- EPUB importer candidate field extraction uses the shared detector when selected.
- PDF importer candidate field extraction uses the shared detector when selected.

Work (Text importer):

1. In `cookimport/plugins/text.py`, find where it currently performs “Section extraction (`Ingredients`, `Instructions`, `Notes`) from text blobs”.

2. Add a branch keyed by `section_detector_backend`:

   - `legacy`: keep current code.
   - `heuristic_v1`: convert text lines into “blocks” (minimal block objects with `text` and a pseudo `unstructured_category` like `ListItem` if line begins with bullet/number). Run:
     - `assign_block_roles(...)` if feasible and consistent with the rest of the codebase, then
     - `HeuristicSectionDetectorV1.detect(...)`.
   - Extract candidate fields by span:
     - ingredients: join lines in ingredient spans, excluding header lines; preserve order.
     - instructions: join lines in instruction spans; preserve order.
     - notes: join lines in note spans.

Work (EPUB importer):

1. In `cookimport/plugins/epub.py`, locate `_extract_fields` (or equivalent) that currently turns a candidate span of blocks into recipe fields.

2. When backend is `heuristic_v1`, call the detector on the candidate span blocks (not the whole book) so spans are relative to candidate start.

3. Use spans to choose which blocks become ingredients/instructions/notes rather than importer-specific heuristics.

4. Ensure the “For the X” boundary protection remains correct: “For the frosting:” inside a recipe should be treated as a subsection header and should not cause a new recipe candidate split. If `_find_recipe_end` already contains a “For the X” fix, keep it; but additionally, ensure that when field extraction sees “For the X” in ingredient span, it is stored as a section header rather than a dropped line.

Work (PDF importer):

1. In `cookimport/plugins/pdf.py`, locate candidate assembly and field extraction.

2. Add the same branch:

   - `legacy`: keep current behavior.
   - `heuristic_v1`: run shared detector on the candidate block span, then extract ingredients/instructions/notes based on spans.

Cross-importer requirement:

- Keep section structure available for downstream staging outputs.

  The repo already emits section artifacts and uses section context for step linking. The simplest way to preserve compatibility is:

  - Store detected spans in a new optional field on `RecipeCandidate` (for example `candidate.detected_sections`), or
  - Store them in a metadata dict attached to candidates (if the model already has an extensible `metadata` field).

  You must confirm the `RecipeCandidate` model location in your working tree (use `rg "class RecipeCandidate" cookimport`). Choose the least disruptive extension (optional field or metadata). Update writers/staging only if needed to read the new section structure.

Acceptance:

- Existing importer tests still pass (`tests/test_text_importer.py`, `tests/test_epub_importer.py`, `tests/test_pdf_importer.py`).
- Add at least one new fixture-based test per importer that asserts a “For the frosting:” header is treated as a section header within a recipe and not as a recipe boundary.
- A stage run on a small fixture file writes `sections/<workbook_slug>/r0.sections.json` showing at least two ingredient sections when “For the frosting:” is present.

### Milestone 5: Add `transitions` FSM backend (`fsm_v1`) and expose it as another option

Goal: incorporate the `transitions` library as an alternative algorithm for the same `DetectedSections` output contract.

Background (embedded, no external docs required):

- `transitions` is a small Python library that lets you define a finite state machine (FSM) by listing states and transitions with condition functions.
- Here we use it to make section detection more explicit and inspectable: scanning blocks left-to-right, the FSM decides whether we are currently in “ingredient region”, “instruction region”, etc.

Work:

1. Add optional dependency group to `pyproject.toml` (or the repo’s equivalent):

   - `section_fsm = ["transitions>=..."]`

   Keep it optional so default installs do not pull it in.

2. Implement `FSMSectionDetectorV1` in `cookimport/parsing/section_detector.py` (or a sibling module `cookimport/parsing/section_detector_fsm.py` imported lazily):

   - States: `OUTSIDE`, `IN_INGREDIENTS`, `IN_INSTRUCTIONS`, `IN_NOTES`
   - Track current section key/name while in a state.
   - Transition conditions use the same deterministic helpers as `heuristic_v1`:
     - `is_header_ingredients(block)`
     - `is_header_instructions(block)`
     - `is_subrecipe_header(block)` and then decide which state based on lookahead cluster score
     - `is_ingredient_like(block)`
     - `is_instruction_like(block)`

   The output must still be a list of `SectionSpan` that represent contiguous runs.

3. Add tests:

   - A regression-style test that runs both `heuristic_v1` and `fsm_v1` on the same synthetic block sequence and asserts they produce the same spans (or that differences are explicitly expected and documented).

Acceptance:

- If `transitions` is installed, `section_detector_backend=fsm_v1` works end-to-end in at least one importer.
- If `transitions` is not installed, selecting `fsm_v1` yields a clear, user-friendly error telling the user which optional extra to install.
- Unit tests for `fsm_v1` pass.

### Milestone 6: Schema-first optional lane for HTML-ish sources (extruct / pyld / scrape-schema-recipe / recipe-scrapers)

Goal: incorporate the schema extraction toolchain as additional selectable options, without breaking existing importers.

Important scope note:

- This milestone is required by this ExecPlan because the user asked that all Priority-2-related tools mentioned in `BIG PICTURE UPGRADES.md` be incorporated as options.
- However, this lane is explicitly opt-in and does not change EPUB/PDF/TXT defaults.

Design options (choose one, but record the decision):

- Option A (recommended): Add a new importer plugin, `cookimport/plugins/html.py`, that detects `.html`/`.htm` files.
- Option B: Add an optional branch inside `cookimport/plugins/text.py` to treat HTML files as “text-like” and run schema extraction first.

This plan assumes Option A to keep concerns separated and detection clean.

Work:

1. Add a new importer:

   - `cookimport/plugins/html.py`
   - Implement `detect/inspect/convert` consistent with other importers.

2. In `convert`, support multiple extraction backends selected by run-config:

   - `schema_extruct_v1`:
     - Use `extruct` to extract JSON-LD / microdata / RDFa into Python dicts.
     - Use `pyld` to normalize JSON-LD graphs (expand/flatten) so the “Recipe” object can be found even when nested.
     - Use `scrape-schema-recipe` to map schema.org Recipe fields into:
       - ingredients (`recipeIngredient`)
       - instructions (flatten `HowToStep` / `HowToSection`)
       - yield/time fields if present
     - Create `RecipeCandidate` directly from these fields.
     - Still run the shared section detector on the resulting pseudo-block stream as a validation step (this keeps section scoring consistent for benchmarks).

   - `schema_recipe_scrapers_v1`:
     - Use `recipe-scrapers` as an alternate schema/structured extractor path. Some sites are supported via site-specific rules.
     - Convert the scraper output into `RecipeCandidate`, then validate with shared detector.

3. Fallback behavior:

   - If no valid schema recipe is found or schema is too weak (missing ingredients or instructions), fall back to an HTML-to-text extraction backend (Milestone 7) and then run shared detector (`heuristic_v1` or selected backend) on the resulting block stream.

4. Add minimal HTML fixture(s) under `tests/fixtures/html/` that include:
   - a JSON-LD script with a Recipe object,
   - a “For the frosting:” component in ingredients.

5. Add tests:

   - `tests/test_html_importer.py`:
     - asserts the HTML importer is selected for `.html`,
     - asserts schema extraction yields a candidate with multiple ingredient sections (including “frosting”),
     - asserts fallback-to-text path works when schema is absent.

Acceptance:

- With the optional deps installed, `cookimport stage path/to/fixture.html --section-detector-backend heuristic_v1 --html-extractor-backend schema_extruct_v1` produces a recipe candidate and section artifacts.
- Without optional deps, selecting schema backends yields clear “install extra” errors.

### Milestone 7: HTML boilerplate-removal backends (trafilatura / readability-lxml / jusText / BoilerPy3 / goose3 / newspaper3k)

Goal: incorporate the HTML extraction tools mentioned as high-ROI for Priority 1–3 as selectable options.

Design:

- Implement a small interface in `cookimport/parsing/html_extractors.py` (or similar) that accepts HTML bytes/str and returns cleaned plain text (or markdown).
- Feed the result into an existing block builder (likely markdown/text line splitting) so the shared section detector can operate.

Work:

1. Add optional dependency group in the build config, for example:

   - `html_extract = ["trafilatura", "readability-lxml", "justext", "boilerpy3", "goose3", "newspaper3k"]`

2. Create a module:

   - `cookimport/parsing/html_cleaners.py`:
     - `clean_html(html: str, backend: str) -> str`

   Backends to implement as options:

   - `trafilatura_v1`
   - `readability_v1`
   - `justext_v1`
   - `boilerpy3_v1`
   - `goose3_v1`
   - `newspaper3k_v1`

   Each backend should:
   - import lazily
   - raise a friendly error if missing
   - be deterministic (no network calls, no randomness)

3. Integrate with the HTML importer from Milestone 6:

   - If schema extraction fails or is disabled, use the selected HTML cleaner backend to get text.
   - Split into blocks (one per line/paragraph).
   - Run `assign_block_roles` / `signals` as appropriate, then shared section detector.

4. Add tests:

   - Smoke tests for at least one backend (choose the simplest in CI context).
   - Use pytest `importorskip` to skip tests if a backend dependency is not installed.

Acceptance:

- Selecting different HTML cleaner backends yields different block shapes but still produces section spans via the shared detector.
- Existing tests remain green.

### Milestone 8: PDF noise suppression + PDF structure recovery backends (datasketch + pdfplumber/pdftotree/pdf2htmlEX/LayoutParser + Docling/PyMuPDF4LLM/Marker/MinerU)

Goal: incorporate Priority-2-related PDF tooling as selectable upstream extraction/preprocessing options.

This milestone is explicitly split into two parts: (A) noise suppression, (B) alternative extractors.

#### 8A: `datasketch` repeating header/footer suppressor (optional preprocessing)

Background (embedded):

- Many PDFs have running headers/footers repeated on each page. These lines can confuse section detection and recipe segmentation.
- `datasketch` provides MinHash/LSH utilities that can detect near-duplicate strings efficiently.

Work:

1. Add optional dependency group:

   - `pdf_dedupe = ["datasketch"]`

2. Implement a preprocessing function:

   - `cookimport/parsing/pdf_noise.py`
   - `suppress_repeating_blocks(blocks, *, min_page_repeat_ratio=0.6, debug=False) -> list[Block]`

   Behavior:

   - Group blocks by page number (PDF blocks already carry page info per docs).
   - Build a signature per block text (normalized: casefold, strip digits that represent page numbers, collapse whitespace).
   - Use MinHash to cluster similar texts.
   - Any cluster that appears on >= `min_page_repeat_ratio` fraction of pages is treated as “repeating noise”.
   - Mark those blocks with a feature flag (or set block_role to `other` / `metadata`) so section detector ignores them.

3. Add a run-config knob:

   - `pdf_repeating_header_suppression: str = "off|datasketch_v1"`

Acceptance:

- On a fixture PDF with repeating headers, enabling `datasketch_v1` reduces those blocks and improves section detection stability.
- Disabling it preserves current behavior.

#### 8B: Alternative PDF extractors (pdfplumber / pdftotree / pdf2htmlEX / LayoutParser / Docling / PyMuPDF4LLM / Marker / MinerU)

Work:

1. Add a “PDF block extractor backend” interface:

   - `cookimport/parsing/pdf_extractors.py`
   - `extract_pdf_blocks(path, *, backend: str, start_page=None, end_page=None, ocr_settings=..., debug=False) -> list[Block]`

2. Implement backends as options (each should be lazy-imported or subprocess-based):

   - Existing backend (keep): `pymupdf_v1` (current behavior)
   - New python-lib backends:
     - `pdfplumber_v1`
     - `pdftotree_v1`
     - `layoutparser_v1`
   - External tool backend:
     - `pdf2htmlex_v1` (shell out to `pdf2htmlEX` if installed; capture stdout/stderr in raw artifacts)
   - “Markdown-first” backends (tooling that converts PDF to markdown):
     - `docling_v1`
     - `pymupdf4llm_v1`
     - `marker_v1`
     - `mineru_v1`

3. For markdown-first backends, reuse existing markdown block parsing:

   - Convert produced markdown → parse into blocks using `cookimport/parsing/markdown_blocks.py` (or equivalent).
   - Ensure provenance includes page hints when available; if not available, record `source_location_id` as “unknown” but keep stable ordering.

4. Integrate into `cookimport/plugins/pdf.py`:

   - Add a run-config knob:
     - `pdf_extractor_backend: str = "pymupdf_v1"` (default)
   - Replace the current inlined extraction logic with a call to `extract_pdf_blocks(...)`, preserving current behavior for the default backend.

5. Tests:

   - Keep existing PDF importer tests for default backend.
   - Add optional smoke tests for at least one alternate backend (likely `pdfplumber_v1`, because it is pip-installable), guarded by `importorskip`.

Acceptance:

- Default PDF behavior is unchanged when `pdf_extractor_backend=pymupdf_v1`.
- At least one alternate backend can be selected and produces a non-empty block stream and a plausible recipe candidate for a fixture PDF.
- The shared section detector works on blocks from any backend.

### Milestone 9: Experimental sequence-labeling and weak supervision backends (python-crfsuite / sklearn-crfsuite / Chaine / skweak)

Goal: incorporate the ML-ish tooling mentioned for Priority 1–3 as additional options, without making them mandatory.

Scope note:

- These backends are marked experimental and off-by-default.
- They exist so benchmark sweeps can include “learned sequence labeler vs heuristic detector”.

Design:

- These backends produce per-block labels, then convert labels → spans.
- Labels should be at least: `ING_HEADER`, `ING_LINE`, `INS_HEADER`, `INS_LINE`, `NOTE_HEADER`, `NOTE_LINE`, `OTHER`.

Work:

1. Add optional dependency groups:

   - `section_crf_python = ["python-crfsuite"]`
   - `section_crf_sklearn = ["sklearn-crfsuite"]`
   - `section_weak = ["skweak"]`
   - `section_chaine = ["chaine"]` (exact package name to be confirmed during implementation; if unavailable, record in Surprises and implement as “not supported” with a friendly error)

2. Add a training script (kept deterministic and offline):

   - `cookimport/training/train_section_crf.py`
   - Inputs:
     - a JSONL export of block-level labels (Label Studio freeform block labels can be mapped to section labels), OR
     - a fixture dataset in `data/training/section_labels.jsonl`
   - Output:
     - a versioned model artifact in `data/models/section_crf_v1.*` (pickle or native format)
     - a small eval report (precision/recall on heldout split) written to `data/models/section_crf_v1_eval.json`

3. Implement inference backends in the section detector interface:

   - `CRFSectionDetectorPythonV1`
   - `CRFSectionDetectorSklearnV1`
   - `SkweakSectionDetectorV1` (weak label aggregation without training, or used to generate pseudo-labels)

4. Conversion to spans:

   - After per-block labels are produced, create spans by grouping contiguous blocks of the same section kind and splitting on headers.
   - Normalize section keys similarly to heuristic backend for “For the X”.

5. Tests:

   - Add a tiny synthetic labeled dataset and a smoke test that trains and then loads a model (mark as slow; run in CI only if configured).
   - Always keep heuristic backend tests as the primary invariant.

Acceptance:

- Selecting `section_detector_backend=crf_python_v1` (or sklearn) works when a model artifact exists, and yields spans on a fixture.
- If model artifact is missing, the system produces a clear error explaining how to train it.
- If dependencies are missing, selection yields a clear “install extra” error.

## Concrete Steps

All commands below assume the working directory is the repository root.

### Baseline

1. Run tests:

   - `pytest -q`

   Record the output summary in `Progress` and/or `Surprises & Discoveries`.

### Implement Milestone 1 (new module + tests)

1. Create new file `cookimport/parsing/section_detector.py`.
2. Add test file `tests/parsing/test_section_detector.py`.
3. Run:

   - `pytest -q tests/parsing/test_section_detector.py`

### Implement Milestones 2–4 (integration + knobs)

1. Locate `ParsingOverrides` model and extend it.
2. Update `cookimport/parsing/sections.py` adapter.
3. Add CLI/run-config knob(s).
4. Wire into importers.
5. Run targeted importer tests:

   - `pytest -q tests/test_text_importer.py`
   - `pytest -q tests/test_epub_importer.py`
   - `pytest -q tests/test_pdf_importer.py`
   - `pytest -q tests/parsing/test_recipe_sections.py`
   - `pytest -q tests/parsing/test_step_ingredient_linking.py`

   Adjust paths if the repo’s test layout differs; record the final list in this plan.

### Optional dependency installs for later milestones

Use editable install with extras, depending on what you are implementing:

- FSM backend:
  - `python -m pip install -e '.[section_fsm]'`

- HTML schema + cleaners:
  - `python -m pip install -e '.[html_extract]'`

- PDF alternate extractors + dedupe:
  - `python -m pip install -e '.[pdf_structure,pdf_dedupe]'`

- Experimental CRF/weak-labeling:
  - `python -m pip install -e '.[section_crf_python,section_crf_sklearn,section_weak,section_chaine]'`

If the repo uses a different dependency mechanism, mirror the pattern used for other optional features.

## Validation and Acceptance

This feature is accepted when all of the following are true.

1. Shared section detector exists and is used by importers (when selected):

- For Text, EPUB, and PDF sources, setting `section_detector_backend=heuristic_v1` causes the importer to populate ingredients/instructions/notes using the detector spans, not importer-specific section code.

2. “For the X” is never treated as a recipe boundary:

- Given a fixture with:

  - Ingredients
  - `For the frosting:`
  - more ingredient lines
  - Instructions

  The output must include a single recipe candidate, with at least two ingredient sections (one default, one “frosting”), and must not split into two recipes.

3. Backward compatibility and benchmarking options exist:

- `legacy` behavior remains selectable and yields the prior outputs for existing fixtures.
- New backends (`heuristic_v1`, and later `fsm_v1`) are selectable and can be benchmarked.

4. Optional tooling is incorporated as options (not mandatory):

- If optional dependencies are absent, selecting their backends results in clear error messages, not crashes.
- If optional dependencies are present, the backends execute and produce plausible outputs on at least one fixture.

5. Tests:

- The full relevant test suite is green (at minimum, the importer tests and section/step-linking tests listed above).
- New tests for section detector and “For the X” behavior exist and fail before the change / pass after.

## Idempotence and Recovery

- All code changes are additive-first:
  - Introduce new module and keep old behavior as `legacy`.
  - Integrate via adapters and config flags before deleting anything.
- Installing optional extras is safe to rerun; it does not modify repo state beyond the environment.
- If a new backend causes regressions, you can recover quickly by:
  - switching `section_detector_backend` back to `legacy`,
  - and/or reverting the integration commit while keeping the new module/tests (depending on what is failing).
- Any external-binary integration (e.g., `pdf2htmlEX`, Marker/MinerU) must:
  - check for availability at runtime,
  - fail with a friendly message if missing,
  - never silently change default behavior.

## Artifacts and Notes

During implementation, add one deterministic debug artifact for section detection when `section_detector_debug=true`, for example:

- `raw/<importer>/<source_hash>/<location_id>.sections.debug.json`

This file should include:

- chosen backend name/version,
- input block texts (or stable hashes) with indices,
- detected spans with confidence and header indices,
- any suppression decisions (e.g., datasketch header/footer clusters).

This artifact is intentionally designed for benchmarking and regression triage.

## Interfaces and Dependencies

### New/updated internal interfaces (prescriptive end state)

- `cookimport/parsing/section_detector.py`
  - Owns the canonical “block stream → section spans” logic.
  - Provides multiple backend implementations behind a stable `DetectedSections` contract.

- `cookimport/parsing/sections.py`
  - Remains as a downstream-compatibility facade.
  - Delegates to `section_detector` when configured.

- Importers:
  - `cookimport/plugins/text.py`, `cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`
  - Must accept a run setting that selects `section_detector_backend`.
  - Must preserve `legacy` behavior as an option.

### Incorporated external tools/libraries for Priority 2 (as options)

Section detection backends:

- `transitions` (FSM backend `fsm_v1`)
- `python-crfsuite` / `sklearn-crfsuite` / `Chaine` (sequence labeling backends, experimental)
- `skweak` (weak supervision backend, experimental)

Schema-first lane (HTML-ish inputs):

- `extruct` (extract JSON-LD/microdata/RDFa)
- `pyld` (normalize JSON-LD graphs)
- `scrape-schema-recipe` (schema.org Recipe mapping)
- `recipe-scrapers` (alternate structured extraction)

HTML boilerplate removal (feeds shared detector):

- `trafilatura`
- `readability-lxml`
- `jusText`
- `BoilerPy3`
- `goose3`
- `newspaper3k`

PDF upstream structure recovery / alternative extraction (feeds shared detector):

- `pdfplumber`
- `pdftotree`
- `pdf2htmlEX` (external binary; subprocess wrapper)
- `LayoutParser`
- `Docling`
- `PyMuPDF4LLM`
- `Marker`
- `MinerU`

PDF noise suppression preprocessing:

- `datasketch` (MinHash/LSH repeating header/footer suppression)

All of the above must be implemented as optional, selectable backends. None should replace the current default path unless explicitly configured and validated by fixture/benchmark evidence.

Change note (2026-02-25 23:59Z): Created this ExecPlan to implement Priority 2 “Make section detection explicit and shared across importers” with a shared deterministic detector and explicit backend options for every related tool/library mentioned in BIG PICTURE UPGRADES.md.