https://chatgpt.com/c/6992a3f6-36a0-8328-a2c2-186bc12a7fb5

# Add EPUB inspection and debugging tools (epub-utils + pipeline-aware reports)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this plan in accordance with `docs/PLANS.md` (or `PLANS.md` at the repo root if that is where the ExecPlan rules live in this repository).


## Purpose / Big Picture

Right now, EPUB ingestion failures are expensive because you are “debugging by vibes”: you can’t quickly answer basic questions like “what’s actually in the spine?”, “which chapter contains recipes?”, “did my extractor skip everything because it’s in divs?”, or “is this EPUB malformed?”. That forces you to keep iterating blind on heuristics, and it guarantees you’ll burn LLM tokens later repairing problems that could have been caught earlier.

After this change, you can run a small set of `cookimport epub ...` commands that:

1) Describe the EPUB structure (container, OPF, manifest, spine, TOC) in a human-readable way.
2) Generate a deterministic “debug report” (JSON + friendly preview) that shows what the *pipeline* will see (blocks, features, block roles, and segmentation candidates).
3) Validate the EPUB with EPUBCheck (when available) so you can distinguish “broken book” from “bug in us”.
4) Make it trivial to extract a spine item’s raw XHTML/plain text to inspect the exact bytes your parser is ingesting.

Observable outcome:

- You can run `cookimport epub inspect path/to/book.epub` and immediately see spine order, chapter titles, and red flags (missing nav, empty chapters, unexpected tag distributions).
- You can run `cookimport epub blocks path/to/book.epub` and get a “blocks preview” that matches the block stream used by `cookimport stage`.
- You can run `cookimport epub candidates path/to/book.epub` and see why the EPUB importer did (or did not) detect recipes, with candidate ranges and scores.
- You can run `cookimport epub validate path/to/book.epub` and get EPUBCheck errors/warnings (or a clear instruction that EPUBCheck isn’t installed).


## Progress

- [ ] (2026-02-16) Read and map current EPUB importer + CLI entrypoints (confirm extractor switches, raw artifacts, and split-range behavior).
- [ ] (2026-02-16) Add optional dependency wiring for `epub-utils` (and guard imports so production ingestion does not require it).
- [ ] (2026-02-16) Implement `cookimport epub inspect` with JSON report output.
- [ ] (2026-02-16) Implement `cookimport epub dump` / `cookimport epub unpack` to write spine XHTML/plain text to disk for inspection.
- [ ] (2026-02-16) Implement `cookimport epub blocks` to generate a pipeline-faithful block preview (JSONL + markdown preview).
- [ ] (2026-02-16) Implement `cookimport epub candidates` to print candidate ranges + scores + boundary context.
- [ ] (2026-02-16) Implement `cookimport epub validate` (EPUBCheck integration) with graceful fallback when missing.
- [ ] (2026-02-16) Add tests with a tiny synthetic EPUB fixture that exercises inspect/blocks/candidates without needing any copyrighted content.
- [ ] (2026-02-16) Document the new debug workflow in README or a docs page (“How to debug a bad EPUB in 90 seconds”).


## Surprises & Discoveries

- None yet. Update this section during implementation when you learn something non-obvious (e.g., a frequent malformed pattern, extractor returning empty because of unexpected markup, EPUBCheck false positives, etc.).


## Decision Log

- Decision: Use `epub-utils` as the “structure inspector” when installed, but provide a fallback inspector implemented with `zipfile + lxml/BeautifulSoup`.
  Rationale: `epub-utils` gives fast, spec-oriented visibility (container/OPF/spine/toc/files), but the pipeline must remain usable without debug tooling installed.
  Date/Author: 2026-02-16 / ExecPlan author

- Decision: Keep pipeline-faithful debugging by reusing the exact EPUB block extraction code path used by `cookimport stage`.
  Rationale: Debug tooling that doesn’t match production behavior creates new confusion and wasted time.
  Date/Author: 2026-02-16 / ExecPlan author

- Decision: Integrate EPUBCheck as an optional validation step, invoked only when the jar (or a docker path) is available.
  Rationale: EPUBs in the wild are often malformed. EPUBCheck lets you quickly separate “book is broken” from “our parser is broken”.
  Date/Author: 2026-02-16 / ExecPlan author


## Outcomes & Retrospective

- Not started. Fill this in after the first successful end-to-end run on a “problem EPUB” you currently struggle with, including what the new tools revealed and what you fixed next.


## Context and Orientation

This repo contains the `cookimport` recipe ingestion pipeline. EPUB ingestion lives in `cookimport/plugins/epub.py`. The pipeline conceptually does:

- “Extraction”: read EPUB spine XHTML in order, convert content into a linear stream of `Block` records.
- “Signals”: annotate each `Block` with features like heading-ness, ingredient-likeliness, yield/time detection, etc.
- “Segmentation”: scan the block stream to detect recipe candidate ranges, then extract `RecipeCandidate` records.

In practice, EPUBs are ZIP archives with:

- `META-INF/container.xml`: points to the “package” file (OPF).
- OPF (`*.opf`): includes metadata, a manifest (all resources), and a spine (reading order).
- Navigation: EPUB2 typically uses `toc.ncx`; EPUB3 typically uses `nav.xhtml`.

The debugging problem: today it’s hard to see (a) what the EPUB’s spine actually is, and (b) what blocks/signals the pipeline actually produced, without dumping internal artifacts manually or guessing.

This plan adds a “debug surface” via CLI commands under `cookimport epub ...` that make the EPUB’s structure and our pipeline’s interpretation visible on demand.

Assumptions about the repo (verify at implementation time):

- The top-level CLI is Typer-based and lives in `cookimport/cli.py` with an `app = typer.Typer(...)`.
- The repo already uses `app.add_typer(...)` to mount sub-CLIs (for example `cookimport/tagging/cli.py`).
- Tests are run with `pytest`.


## Plan of Work

Implement this as a small, isolated “EPUB debug toolbelt” that does not change ingestion outputs by default.

The work splits into three layers:

1) **Structure inspection (EPUB-as-a-book-object):**
   - Use `epub-utils` (Python library) if installed to show container/package/manifest/spine/toc and to fetch raw XHTML or arbitrary files.
   - Provide a fallback that reads `META-INF/container.xml` and OPF via `zipfile` so the command still works without `epub-utils`.

2) **Pipeline inspection (EPUB-as-block-stream):**
   - Reuse the existing EPUB importer extraction code path (including extractor selection: `unstructured` vs `legacy`) to produce blocks exactly as `cookimport stage` would.
   - Write two artifacts:
     - `blocks.jsonl` (one JSON per block with index/type/text/features/role/spine_index/source refs)
     - `blocks_preview.md` (human-readable excerpts with indices + flags)
   - Add “fast stats” so you can see at a glance if extraction failed (e.g., 0 blocks, 0 chars, or 95% of content in unsupported tags).

3) **Segmentation inspection (EPUB-as-recipes):**
   - Reuse the existing `_detect_candidates` logic to output candidate ranges with scores and the surrounding boundary context.
   - This is the fastest way to answer “why didn’t it find recipes?” without opening the whole book.

Finally, add EPUBCheck integration as an optional validator surface. The validator should never be required for tests or normal usage; it should be a “nice when present” tool.

Throughout, keep changes additive and testable, and ensure debug commands are idempotent (they only read the EPUB and write to an output directory you control).


## Concrete Steps

All commands below assume repo root as working directory.

### 1) Locate and understand existing entrypoints

- Find the Typer root app and how subcommands are wired:

    rg -n "typer\\.Typer\\(" cookimport
    rg -n "add_typer\\(" cookimport/cli.py

- Locate EPUB importer and confirm how extraction currently happens and how extractor mode is selected:

    rg -n "class .*Epub" cookimport/plugins/epub.py
    rg -n "C3IMP_EPUB_EXTRACTOR|epub_extractor|--epub-extractor" cookimport/plugins/epub.py cookimport/cli.py

Record key internal functions/methods you will reuse in this plan, especially:
- the function/method that returns the spine-ordered block stream,
- where signals are enriched,
- where block roles are assigned,
- where candidates are detected.

Update this ExecPlan’s `Surprises & Discoveries` if anything differs from assumptions.


### 2) Add optional dependency: epub-utils

Goal: make it possible to import `epub_utils` in debug tooling, without making the production pipeline require it.

- Edit `pyproject.toml` to add `epub-utils` under an optional extra group. Match the repo’s existing style (this repo already uses extras like `[db]` / `[dev]`).

Examples (choose the one matching your project config style):

- If using PEP 621:

    [project.optional-dependencies]
    epubdebug = [
      "epub-utils>=<pin>",
    ]

- If using Poetry:

    [tool.poetry.extras]
    epubdebug = ["epub-utils"]

(Prefer a loose lower bound and let Renovate/lockfile handle exact pins; this is debug tooling.)

- Ensure debug commands handle missing dependency gracefully:

    try:
        from epub_utils import Document as EpubUtilsDocument
    except Exception:
        EpubUtilsDocument = None

So `cookimport epub inspect` still works without epub-utils installed (fallback inspector).


### 3) Add a new Typer sub-CLI: `cookimport epub`

Create a new module:

- `cookimport/epubdebug/cli.py`

Inside it, define:

- `epub_app = typer.Typer(help="EPUB inspection/debugging tools")`

And wire it into the main CLI:

- In `cookimport/cli.py`, add:

    from cookimport.epubdebug.cli import epub_app
    app.add_typer(epub_app, name="epub")

This should mirror the existing pattern used for other sub-CLIs (for example tagging).

Add `--help` coverage:

- `cookimport epub --help` should list subcommands: `inspect`, `dump`, `blocks`, `candidates`, `validate`.


### 4) Implement `cookimport epub inspect`

Create a small “inspection report” model so output can be both human-readable and machine-stable.

New file:

- `cookimport/epubdebug/models.py`

Define Pydantic models:

- `EpubInspectReport`
  - `path` (string)
  - `file_size_bytes` (int)
  - `sha256` (string)
  - `container_rootfile_path` (string | null)
  - `package_path` (string | null)
  - `metadata` (dict with keys like title/creator/language if available)
  - `spine` (list of `EpubSpineItemReport`)
  - `warnings` (list[str])
  - `generated_at` (ISO timestamp)

- `EpubSpineItemReport`
  - `index` (int)
  - `idref` (string | null)
  - `href` (string | null)
  - `media_type` (string | null)
  - `linear` (bool | null)
  - `doc_title` (string | null)
  - `text_chars` (int)
  - `word_count` (int)
  - `top_tags` (list[tuple[str,int]] or dict[str,int] limited to top N)
  - `class_keyword_hits` (dict[str,int]) for keywords like ingredient/instruction/direction/method/recipe

Implementation approach in `cookimport/epubdebug/inspect.py`:

- Compute file hash and size.
- If `epub_utils` is available:
  - Load `Document(path)`
  - Fetch container/package/toc/spine/manifest via its API.
  - For each spine item, fetch XHTML and derive:
    - `doc_title` (HTML <title> or first heading)
    - stripped text -> `text_chars` and `word_count`
    - tag histogram + keyword hits
- Else (fallback):
  - Use `zipfile.ZipFile` to read `META-INF/container.xml`
  - Parse container.xml to locate OPF
  - Parse OPF to read spine order and item hrefs
  - For each href, read XHTML and compute the same derived fields

CLI behavior in `cookimport/epubdebug/cli.py`:

- `cookimport epub inspect PATH --out OUTDIR? --json?`
  - Default: print a readable summary to stdout.
  - If `--out` provided, write `inspect_report.json` into OUTDIR.
  - If `--json` provided, print the JSON report (useful for piping).

Readable summary must include:
- container/package paths
- metadata summary
- spine list with index + href + title + text_chars + red flags
- warnings (missing nav/toc, spine item missing, empty text, parse errors)

Important: never dump full chapter text by default; keep stdout concise and point to `dump` for raw content.


### 5) Implement `cookimport epub dump` (targeted extraction to disk)

Goal: make it effortless to “look at the exact bytes”.

Add subcommand:

- `cookimport epub dump PATH --spine-index N --format xhtml|plain --out OUTDIR --open?`

Behavior:

- Reads the requested spine item XHTML bytes and writes:
  - `spine_{N:04d}.xhtml` (format=xhtml)
  - or `spine_{N:04d}.txt` (format=plain)
- Also write a tiny `dump_meta.json` describing what was written (href/idref/title, counts).
- If `--open` is provided:
  - On macOS: `open <file>`
  - On Linux: `xdg-open <file>`
  - If not supported, print the path and do nothing.

Also add convenience:

- `cookimport epub unpack PATH --out OUTDIR [--only-spine]`

This unzips the EPUB into OUTDIR, optionally only extracting:
- OPF, container.xml, nav/toc, and spine XHTML docs.

This is the “no excuses” fallback when you need to inspect CSS/images/resources.


### 6) Implement `cookimport epub blocks` (pipeline-faithful block preview)

This is the highest-value command for “stop guessing” because it shows what `cookimport stage` will use.

Add `cookimport/epubdebug/blocks.py` with a single public function:

- `extract_blocks_for_debug(path: Path, *, extractor: str | None, start_spine: int | None, end_spine: int | None) -> list[Block]`

Hard requirement: this function must call the same code path used by the real EPUB importer conversion, not a reimplementation.

If the EPUB importer currently keeps extraction logic private inside `EpubImporter.convert()`, refactor minimally:

- Pull the block extraction into a helper that both `convert()` and debug tooling can call, without changing behavior.
- Keep `start_spine/end_spine` semantics identical (end exclusive).
- Preserve `spine_index` features exactly as production.

CLI:

- `cookimport epub blocks PATH --extractor unstructured|legacy? --start-spine N? --end-spine M? --out OUTDIR`
  - Writes:
    - `blocks.jsonl`
    - `blocks_preview.md`
    - `blocks_stats.json`
  - Prints a short on-screen summary:
    - total blocks
    - total chars
    - counts by block type
    - counts by block_role (if assigned)
    - top warnings (“0 blocks extracted”, “>80% blocks are empty after normalization”, etc.)

`blocks_preview.md` format (example):

- One block per entry, showing:
  - index, spine_index, type, role
  - a compact list of key features (heading_level, is_ingredient_likely, is_instruction_likely, is_yield, etc.)
  - first ~120 chars of text

This preview must be small enough to skim but informative enough to spot systemic issues quickly.


### 7) Implement `cookimport epub candidates` (segmentation debug)

Add `cookimport/epubdebug/candidates.py`:

- `detect_candidates_for_debug(blocks: list[Block]) -> list[CandidateDebug]`

Again: reuse the production candidate detection logic (the same function(s) called by the importer), so results match real staging.

Define a Pydantic model:

- `EpubCandidateReport`
  - `candidates`: list of `CandidateDebug`
  - `warnings`: list[str]
  - `generated_at`: timestamp
  - `extractor`: string used

- `CandidateDebug`
  - `index`: int
  - `start_block`: int
  - `end_block`: int
  - `score`: float
  - `title_guess`: str | null
  - `anchors`: dict[str,bool] (e.g., saw_ingredient_header, saw_instruction_header, saw_yield)
  - `context`: minimal snippets:
    - `start_context`: list[str] (first ~5 block texts)
    - `end_context`: list[str] (last ~5 block texts)

CLI:

- `cookimport epub candidates PATH --extractor ... --start-spine ... --end-spine ... --out OUTDIR`
  - Writes `candidates.json` and `candidates_preview.md`.
  - Prints a concise list of candidates and scores.

The point is to answer questions like:
- “Did we detect candidates at all?”
- “Are candidates getting clipped too early/late?”
- “Are we missing ingredient/instruction headers because extraction didn’t preserve headings?”


### 8) Implement `cookimport epub validate` (EPUBCheck integration)

EPUBCheck is a Java-based validator commonly used in publishing workflows. We treat it as optional.

Implementation strategy:

- Add a folder `tools/epubcheck/` with:
  - `README.md` (very short: what it is and how to install jar)
  - `.gitignore` entry so the jar can be local-only if you prefer
- Add `cookimport/epubdebug/epubcheck.py` with:
  - `find_epubcheck_jar() -> Path | None` (search env var, tools folder, common paths)
  - `run_epubcheck(epub_path, jar_path, *, json_out_path=None) -> EpubcheckResult`

CLI:

- `cookimport epub validate PATH --jar PATH? --out OUTDIR`
  - If jar is missing:
    - Print a clear message explaining how to get it (either download release zip and point to the jar, or install via system package manager if available).
    - Exit with a non-zero code only if `--strict` is provided; otherwise exit 0 (so it’s usable even without validator).
  - If jar exists:
    - Run: `java -jar <jar> <epub>`
    - Capture stdout/stderr
    - Parse basic counts (errors, warnings) from output text (and/or use `--json` if available in the chosen EPUBCheck distribution).
    - Write `epubcheck.json` into OUTDIR with:
      - tool version (best-effort)
      - counts
      - first N messages
      - raw output path (save full output as `epubcheck.txt`)

This command’s job is not to “fix” EPUBs; it’s to quickly tell you whether you’re debugging a broken container/package.


### 9) Tests: synthetic EPUB fixtures

Do not commit real cookbooks.

Add a helper in tests:

- `tests/fixtures/make_epub.py` (or similar)

It should generate a tiny valid EPUB (EPUB3 preferred) into a temp directory by writing a zip with:
- `mimetype` stored first and uncompressed
- `META-INF/container.xml`
- `OEBPS/content.opf`
- `OEBPS/nav.xhtml`
- `OEBPS/chapter1.xhtml` with:
  - headings and paragraphs
  - a fake recipe-like section (“Ingredients”, “Instructions”) so your signals/candidate detection has something to find
- `OEBPS/chapter2.xhtml` with some non-recipe prose

Write tests (pytest) that:

- `cookimport epub inspect` returns 0 and the JSON has:
  - non-empty spine
  - non-empty metadata keys (or safe nulls)
- `cookimport epub blocks` writes `blocks.jsonl` and has >0 blocks
- `cookimport epub candidates` produces at least one candidate (if your current heuristics detect “Ingredients/Instructions” headings)

If validation tests are added, keep them optional/skipped unless EPUBCheck is installed (environment-driven), so CI does not require Java.


### 10) Documentation: “Debug an EPUB in 90 seconds”

Add a short doc page (or README section) explaining the workflow:

1) `cookimport epub inspect book.epub`
2) If structure looks weird, `cookimport epub dump book.epub --spine-index N --format plain --out /tmp/...`
3) If extraction looks wrong, `cookimport epub blocks book.epub --out data/output/...`
4) If segmentation looks wrong, `cookimport epub candidates book.epub --out data/output/...`
5) If you suspect the EPUB is malformed, `cookimport epub validate book.epub --out data/output/...`

Include 1–2 short example transcripts (not full book text).


## Validation and Acceptance

Acceptance is met when the following commands work on (a) a synthetic test EPUB and (b) at least one “real problematic EPUB” you currently struggle with:

1) Structure inspection:

- Run:

    cookimport epub inspect data/input/problem.epub

- Expect:
  - Exit code 0
  - Prints: container/package path, spine count, and a per-spine summary
  - Emits actionable warnings for obvious issues (missing spine items, empty chapters, parse errors)

2) Dumping raw content:

- Run:

    cookimport epub dump data/input/problem.epub --spine-index 3 --format plain --out data/output/_scratch/epub_dump

- Expect:
  - File exists: `data/output/_scratch/epub_dump/spine_0003.txt`
  - `dump_meta.json` exists and matches href/title expectations

3) Pipeline-faithful blocks:

- Run:

    cookimport epub blocks data/input/problem.epub --out data/output/_scratch/epub_blocks

- Expect:
  - `blocks.jsonl` exists and contains block entries with indices and text
  - `blocks_preview.md` exists and is readable
  - The printed summary makes it obvious if the extractor returned “nothing” (0 blocks / 0 chars)

4) Candidate debug:

- Run:

    cookimport epub candidates data/input/problem.epub --out data/output/_scratch/epub_candidates

- Expect:
  - `candidates.json` exists
  - Console output lists candidate ranges and scores
  - If no candidates, report should include the top 2–3 likely reasons (e.g., “no ingredient/instruction headers detected”)

5) Tests:

- Run:

    pytest -q

- Expect:
  - All new tests pass deterministically
  - No new mandatory dependency on Java/EPUBCheck for the test suite


## Idempotence and Recovery

- All commands must be read-only with respect to the input EPUB. They only write into an explicit output directory.
- If `--out` points to an existing directory:
  - Default behavior: refuse and ask for `--force` (to avoid accidental overwrites).
  - With `--force`: overwrite only files created by the command (do not recursively delete arbitrary files).
- If `epub-utils` is not installed:
  - `inspect`, `dump`, and `unpack` must still work via fallback ZIP parsing.
  - The CLI must print a one-line hint: “Install optional epub debug tools: pip install -e '.[epubdebug]'”.
- If EPUBCheck jar is missing:
  - `validate` must still run and explain how to supply `--jar` (and should not crash).


## Artifacts and Notes

Example expected output (shape, not exact):

- `cookimport epub inspect data/input/book.epub`

    EPUB: data/input/book.epub
    Size: 2,103,441 bytes
    SHA256: 7f2c...a91d
    Package: OEBPS/content.opf
    Metadata: title="My Cookbook" creator="Jane Doe" language="en"
    Spine: 12 items
      [0] cover.xhtml  title="Cover"            chars=0     WARN empty
      [1] intro.xhtml  title="Introduction"     chars=4120
      [2] ch1.xhtml    title="Soups"            chars=18422  tags: p=220 li=14 h2=9 div=3
      [3] ch2.xhtml    title="Recipes"          chars=50211  hits: ingredient=18 instruction=22
    Warnings:
      - nav.xhtml missing; using toc.ncx
      - 2 spine docs have near-zero text after stripping; check if content is image-only or script-rendered

- `cookimport epub blocks ...`

    Extractor: unstructured
    Blocks: 3,412
    Total text chars: 81,002
    Block roles: ingredient_line=512 instruction_line=803 recipe_title=112 narrative=1,731
    Wrote:
      - .../blocks.jsonl
      - .../blocks_preview.md
      - .../blocks_stats.json


## Interfaces and Dependencies

New CLI surface:

- `cookimport epub inspect PATH [--out OUTDIR] [--json]`
- `cookimport epub dump PATH --spine-index N [--format xhtml|plain] --out OUTDIR [--open]`
- `cookimport epub unpack PATH --out OUTDIR [--only-spine]`
- `cookimport epub blocks PATH [--extractor unstructured|legacy] [--start-spine N] [--end-spine M] --out OUTDIR`
- `cookimport epub candidates PATH [--extractor ...] [--start-spine ...] [--end-spine ...] --out OUTDIR`
- `cookimport epub validate PATH [--jar PATH] [--out OUTDIR] [--strict]`

External dependencies:

- Optional Python dependency: `epub-utils` (import name `epub_utils`)
  - Used for structure inspection and file access convenience.
  - Must not be required for normal staging.

- Optional external tool: EPUBCheck (Java jar)
  - Invoked via `java -jar`.
  - Must not be required for normal staging or for running the unit test suite.

Internal dependencies (reuse, do not reimplement):

- EPUB importer extraction logic in `cookimport/plugins/epub.py`
- Signal enrichment in `cookimport/parsing/signals.py`
- Block role assignment (wherever `assign_block_roles(...)` lives)
- Candidate detection logic in EPUB importer


---

Plan change notes:

- (none yet)
