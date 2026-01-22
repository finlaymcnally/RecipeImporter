---
summary: "High-level plan for importing recipes into a standardized staging format."
read_when:
  - When planning the import pipeline or staging formats
---

Import engine

I'm making a cookbook database project. I will be using a specific recipe data structure for ingredients/steps, which is already decided and we can get into later about how we'll transform recipes into that structure. For now, I need to start thinking about the best way to import recipes, as I have a variety of sources, places they'll come from: 
A.	epubs of ebook cookbooks I've bought 
B.	PDFs of cookbooks ive bought, 
C.	OCRd Pictures/scans of cookbooks (I will OCR) I've bought 
D.	Text files ive saved or written
E.	Excel sheets of recipes 
F.	Paprika recipe manager has a secured data file format 
What's the best way to pull each of these sources together into one type of data structure/format, and then what will the best way to then bulk change all the recipes to my specific database format? I'm happy to use whatever tools or services or whatever to get this done. Happy to pay for some AI tokens to do this

I would like at the end one tool (GUI, command line, I don’t care. This is for personal utility only) that you point at a folder and it can 1) suck up any of the input types and attempt to output intermediate stage JSON-LD, then 2) suck in any of the intermediate stage JSON-LD in that folder and output final DB format (tbd) from them

There are hundreds of cookbooks , and 100s of other file formats too. I have 1000s of bookmarks I’ll eventually need to get to. This needs to work at scale and work smoothly.

AI use
I think my token volume (~40mil in and 40m out in total) is such that I need to use something like Gemini 3 flash which will be like $100 vs trying to grind locally on my 9070xt, but we’ll see once I get into the import process.



Plan - recipe data input project into personal recipe database project
(a source type) → specific source type converter → RecipeSage JSON-LD format→ transformer → final DB format
1) Various input files
A.	epubs and other file formats of ebook cookbooks
B.	PDFs of cookbooks ive bought, I will OCR in advance 
C.	Text files ive saved or written
D.	Excel sheets of recipes 
E.	Paprika recipe manager has a secured data file format 
F.	RecipeSage data file format (this is going to the base of my intermediate format, but my branch may evolve depending on information requirements)
G.	I may build a web scraping tool if RecipeSage/Paprika don’t work how I’d like them to, but we’ll look into that later as I would rather not.

2) Per-source conversion into a Staging Layer
In this stage, every source is converted into a consistent set of recipe candidates. The goal is to preserve whatever structure we can (headings, page/layout cues, lists) while turning messy real-world content into clearly labeled blocks—title/headnotes, ingredient section(s), instruction steps, and basic metadata (yield/servings, times, etc.).
We start with deterministic cleanup and straightforward segmentation rules, and only escalate to LLM-assisted structure recovery when the source is ambiguous (mixed headnotes + ingredients + steps, multi-column layouts, inconsistent formatting). Any model output must be constrained to a schema and validated so downstream steps can treat everything uniformly.
Target intermediate / staging format: RecipeSage JSON-LD (we have a complete example with every field populated).

LLMs are often useful for structure recovery when the source is messy: OCR text that mixes headnotes + ingredients + steps, multi-column layouts, cookbook pages where the “ingredients” aren’t clearly separated – will only do this if my OCR options fail, lets assume this is solved for now
Deterministic helps here too, but mostly for:
•	basic cleanup (hyphenation fixes, whitespace, page headers/footers removal)
•	common regex extraction (e.g., “Serves 4”, “Yield: 2 loaves”)
LLM assist here is for:
•	segmenting a page/chunk into fields (name vs ingredients vs instructions)
•	pulling out times/servings when phrasing is weird
•	detecting ingredient section headers
Output of this stage: valid RecipeSage JSON-LD 

Consider using local/self run Unstructured.io



D) Excel sheets
High level:
Treat Excel as already structured.
•	Map columns into candidate fields (title, ingredients, instructions, etc.), but still store the original row as provenance.
•	If one sheet contains multiple recipes, generate one candidate per row/recipe.
Built out:
D) Excel sheets — how I’d actually build the pipeline
The “treat Excel as structured” idea is right, but Excel in the wild comes in a few distinct layouts. The key is: detect layout → extract recipe records → map/normalize fields → emit RecipeSage JSON-LD (+ provenance) → validate.
Below is a concrete, buildable pipeline.
________________________________________
1) Excel converter as a first-class plugin
Implement a source_excel converter that returns a list of RecipeCandidate objects (your staging representation), then a serializer that writes RecipeSage JSON-LD.
Interface
•	detect(file) -> confidence
•	inspect(file) -> workbook summary + inferred mappings + layout guess
•	convert(file, mapping_config) -> [recipesage_jsonld] + report.json
CLI hooks
•	cookimport stage <folder> --out staging/ (auto-detect file types)
•	cookimport inspect <file.xlsx> (prints sheet/layout/mapping guess, writes mapping stub)
________________________________________
2) Support the 3 common Excel layouts (don’t assume “one row = one recipe”)
Layout A — “Wide table” (most common)
One row per recipe; columns like Title | Ingredients | Instructions | Servings | Tags | Source ...
Extraction rule
•	Header row defines columns
•	Each non-empty row = one recipe
Layout B — “One recipe per sheet” (template style)
Cells like:
•	B2 = Title
•	B5:B20 = Ingredients
•	B22:B50 = Steps
Extraction rule
•	Use named ranges if present; else cell-address mapping per sheet template
Layout C — “Tall/relational” (recipes spread across rows)
Examples:
•	A “Recipe” column repeated, with Type = ingredient/instruction
•	Or blocks separated by blank rows / bold “Ingredients” row / “Directions” row
Extraction rule
•	Group rows by a key (recipe name/id) or by block boundaries, then assemble ingredients/steps lists
✅ You can support all three with one converter by doing per-sheet layout detection.
________________________________________
3) Per-sheet layout detection (deterministic)
For each sheet:
Step 1: find the header row (for table-like sheets)
Heuristics:
•	Scan first ~30 rows
•	Score a row as “header” if:
	o	Many string cells, low numeric density
	o	Contains known header aliases (title/ingredients/instructions/etc.)
	o	Next rows look like data (more varied types)
If no good header row → try template/block mode.
Step 2: decide layout
Use a simple scoring model:
Wide table signals
•	Header row found
•	Columns map cleanly to core fields
•	Many subsequent rows non-empty
Tall/relational signals
•	Header row found, but:
	o	“Recipe/Name” column repeats frequently
	o	“Type” column exists (ingredient/instruction)
	o	Many rows per recipe (same name repeated)
Template signals
•	No strong header row
•	Title cell appears near top
•	Contains literal labels (“Ingredients”, “Directions”) in first column
•	Or named ranges exist
If ambiguous, default to wide table (it’s easiest to correct via mapping config).
________________________________________
4) Column mapping: auto + config override (this is where Excel wins)
A) Canonical field set for staging
At minimum for RecipeSage JSON-LD you want:
•	name (title)
•	recipeIngredient (list)
•	recipeInstructions (list of steps or HowToStep objects)
Optional:
•	description/notes
•	recipeYield or servings
•	prepTime, cookTime, totalTime
•	keywords/tags
•	source / url
•	author
•	category/cuisine
B) Auto-map headers by alias table
Normalize header text:
•	lowercase
•	strip punctuation
•	collapse whitespace
Then match against alias sets like:
•	name: title, recipe name, name
•	ingredients: ingredients, ingredient list, ing, components
•	instructions: directions, method, steps, instructions, preparation
•	notes: notes, headnote, description, comment
•	yield: yield, serves, servings, portions, makes
•	prepTime: prep time, preparation time
•	cookTime: cook time
•	totalTime: total time
•	tags: tags, keywords
•	source: source, book, page, url, link
C) Mapping config file (YAML/JSON)
You’ll want a user-editable config because everyone’s spreadsheets differ. Example shape:
excel:
  defaults:
    empty_row_is_skip: true
    ingredients_delimiters: ["\n", ";"]
    instructions_delimiters: ["\n"]
  sheets:
    - match: "Recipes"
      layout: "wide_table"
      header_row: "auto"
      columns:
        name: ["title", "recipe name"]
        ingredients: ["ingredients", "ingredient list"]
        instructions: ["instructions", "directions", "method"]
        yield: ["servings", "yield"]
        tags: ["tags", "keywords"]
        source: ["source", "url", "link"]
    - match: "Template*"
      layout: "template"
      cells:
        name: "B2"
        ingredients_range: "B5:B30"
        instructions_range: "B32:B60"
cookimport inspect file.xlsx should generate this stub automatically with its best guesses.
________________________________________
5) Normalization (turn “cells” into lists the rest of your pipeline can trust)
Ingredients cell → recipeIngredient: [string]
Common cases to handle deterministically:
•	Multiline cell: split on \n
•	Semicolon-delimited: split on ;

•	Bullets: strip leading - • *

•	Section headers (e.g., “For the sauce”):
	o	Keep as a line, but mark it (optional) as a section header
	o	Or store in structured extension while keeping a readable line
Rule of thumb: preserve text faithfully here; do parsing/quantities later in your “final DB transformer”.
Instructions cell → recipeInstructions: [HowToStep] or [string]
•	Split on newline
•	If numbered (“1.”, “2)”) remove prefix but keep order
•	If a cell contains multiple paragraphs, keep them as separate steps unless it’s clearly one step
Yield/time fields
•	If already numeric/time-like: keep as-is
•	If string: extract common patterns deterministically:
	o	Serves 4, Makes 2 loaves, Yield: 24 cookies
	o	Prep: 15 min, Cook: 1 hr, etc.
(If extraction fails, just store the raw string in notes/metadata and move on.)
________________________________________
6) Provenance: keep the original row verbatim
You called this out and it’s absolutely the right move.
For every emitted recipe candidate, attach provenance like:
•	file_path
•	workbook
•	sheet
•	row_index (and maybe Excel row number)
•	original_headers
•	original_row (a dict of header → raw cell string)
•	import_timestamp
•	converter_version
Where to store it in JSON-LD:
•	Best: a dedicated namespaced extension block (so you never collide with RecipeSage fields)
•	Also useful: add a stable @id derived from (file hash + sheet + row) so re-imports are idempotent.
This makes later debugging and re-transforming painless.
________________________________________
7) Validation + repair loop (fast feedback, no guessing downstream)
Before writing JSON-LD:
•	Validate required minimum:
	o	title present AND (ingredients OR instructions present)
•	Validate types:
	o	ingredients is list
	o	instructions is list
•	Emit a per-file report:
	o	number of recipes found
	o	mapping used
	o	rows skipped + why
	o	fields missing counts
	o	sample of first 3 parsed recipes (for eyeballing)
If a sheet maps poorly:
•	mark it in the report with “low confidence mapping”
•	still emit what you can (with provenance), but flag for user review
This gives you a reliable “import dashboard” even without a GUI.
________________________________________
8) Output strategy (works great with your folder-based tool)
Suggested staging output layout:
•	staging/recipesage_jsonld/<workbook_name>/<sheet_name>/r<row>.json
•	staging/reports/<workbook_name>.excel_import_report.json
So your phase 2 (“transform all JSON-LD to final DB format”) can just glob staging/recipesage_jsonld/**/*.json.
________________________________________
9) Practical implementation notes (so you don’t get burned)
•	Use openpyxl (or pandas + openpyxl) for .xlsx/.xlsm
•	Read with data_only=True when you want cached formula results (otherwise you’ll get the formula text)
•	Treat merged cells carefully:
	o	openpyxl returns value on top-left only; you may need to forward-fill merged regions for table layouts
•	Strip weird whitespace (\xa0) and normalize line endings early
•	For very large sheets:
	o	use openpyxl read_only=True streaming
	o	avoid loading everything into memory if you don’t need to
________________________________________
10) The “LLM escalation” story for Excel (usually minimal)
For Excel specifically, I’d only escalate to an LLM in two cases:
1.	Layout C where blocks are messy and heuristics can’t confidently group rows into a recipe
2.	Ingredients/instructions are smashed together in one cell and need segmentation
Even then, constrain output to a strict schema, and always preserve the raw row/block in provenance.

E) Paprika format
High level:
Don’t fight the secured/internal store—export.
Paprika supports:
•	Paprika Recipe Format (.paprikarecipes) which is a zip containing gzipped JSON per recipe.
•	HTML export where each recipe is an HTML file and includes schema metadata. 
Best choice: export .paprikarecipes → you’re basically done with ingestion because you get one JSON object per recipe.

Built out:
E) Paprika pipeline (the “actually build it” version)
0) Treat Paprika as a source system and only ingest exports
Paprika already gives you two export surfaces you can rely on:
•	Paprika Recipe Format (.paprikarecipes) = “essentially a zip file containing gzipped JSON files” (one compressed JSON blob per recipe). (Paprika)
•	HTML export = a folder of per-recipe HTML files, and each recipe page includes schema metadata you can parse. (Paprika)
So your importer should accept either (or both) without touching the secured/internal store.
________________________________________
1) Folder-level ingestion contract (how it plugs into your “point at a folder” tool)
Input folder can contain:
•	*.paprikarecipes files
•	Paprika HTML export folders (containing index.html + many recipe .html files) (Paprika Support)
Output (staging) you want to write:
•	staging/recipesage_jsonld/<stable_id>.jsonld
•	staging/raw/paprika/<stable_id>.json (verbatim decompressed JSON for provenance/debug)
•	staging/assets/paprika/<stable_id>/... (optional images if you ingest HTML export)
Reports:
•	reports/paprika_import_report.json (counts, failures, duplicates, missing fields)
This makes Paprika a clean “E) converter” module in your bigger pipeline.
________________________________________
2) Paprika Recipe Format importer (primary path)
2.1 Detect & extract
For each *.paprikarecipes:
1.	Open as ZIP. (Paprika)
2.	For each entry:
	o	Treat file bytes as gzip stream
	o	gunzip → utf-8 text → json.loads()
Paprika explicitly describes the format as zip + individually compressed JSON-per-recipe, so this isn’t reverse-engineering; it’s the intended machine-readable export. (Paprika Support)
2.2 Normalize into an internal “RecipeCandidate”
Before you touch RecipeSage JSON-LD, normalize into a small canonical object (your code’s private interface), e.g.:
•	source_system: "paprika"
•	source_uid: (whatever Paprika provides; otherwise a hash of the JSON)
•	title
•	ingredients_raw: (often a single text block; keep it raw here)
•	directions_raw
•	notes_raw
•	servings/yield_raw
•	times_raw (prep/cook/total if present)
•	source_name, source_url
•	categories/tags (if present)
•	photos: [] (leave empty in this path unless you later confirm they’re embedded)
Why this extra step? It keeps the extractor dumb and stable, and lets you reuse the same downstream structuring logic you’ll need for PDFs/OCR/text anyway.
2.3 Convert to RecipeSage JSON-LD (staging target)
Map RecipeCandidate → RecipeSage JSON-LD:
•	Set a stable @id / identifier based on source_uid (idempotent re-imports)
•	Put raw Paprika fields into:
	o	the appropriate RecipeSage fields when obvious
	o	a sourceMeta / importMeta blob (whatever you choose) for “don’t lose data”
•	Do not LLM anything here by default. Paprika export is already structured enough.
2.4 Validate & write
•	Validate the produced JSON-LD against your “RecipeSage JSON-LD expectations” (schema or custom validator)
•	If validation fails:
	o	still write raw/paprika/<id>.json
	o	write a failure record with error + partial mapping (so you never lose recipes)
________________________________________
3) HTML export importer (secondary path, but very useful)
Paprika’s support docs say HTML export produces per-recipe HTML files and each contains schema metadata. (Paprika Support)
That’s gold because you can parse a standard schema.org Recipe object from each file with minimal heuristics.
3.1 Parse strategy
For each recipe HTML file:
1.	Extract embedded schema (usually JSON-LD script tags, sometimes microdata)
2.	Build RecipeCandidate from schema fields:
	o	ingredients list tends to be cleaner here
	o	yields/times often already normalized
3.2 Images
Paprika HTML exports in the wild commonly include an images/ folder alongside recipe files (not guaranteed by the official doc, but common enough to support). (Reddit)
So:
•	If images exist, copy them into staging/assets/paprika/<id>/...
•	Store local asset refs in importMeta so your final DB can decide how to store media
________________________________________
4) Best-practice: “merge mode” when both exports are present
If a folder contains both:
•	something.paprikarecipes
•	Export …/ HTML folder
…you can do a deterministic merge:
Recommended precedence
•	Prefer .paprikarecipes JSON for: notes, categories, ratings, internal fields, canonical text
•	Prefer HTML schema for: structured ingredient arrays, times/yields normalization, photos/assets
How to merge safely
•	Match on source_url + title fuzzy, or on a Paprika UID if it appears in both (if not, do the fuzzy match and log “confidence”)
•	Keep both originals in raw/ so you can audit mismatches later
________________________________________
5) Edge cases you should handle up front
•	Duplicate exports: same recipe appears across multiple .paprikarecipes files → de-dupe by source_uid or hash of normalized fields.
•	Partial recipes: missing ingredients/directions (common for “notes-only” entries) → still import; mark qualityFlags.
•	Scaling: unzip+gunzip is CPU-bound but easy to parallelize; just keep deterministic ordering for stable outputs.
•	Provenance: always write the raw decompressed JSON next to your RecipeSage JSON-LD so debugging never involves re-exporting.
________________________________________
6) What your CLI command might look like
•	cookbook ingest --input /path/to/folder --source paprika
	o	finds *.paprikarecipes + Paprika HTML export folders
	o	writes staging/recipesage_jsonld/*
	o	writes reports/paprika_import_report.json
This makes Paprika the cleanest source type in your whole list: almost entirely deterministic, with optional HTML-schema enrichment.

F) RecipeSage data file format
Should just work, as any changes will be adding more fields

G) Web scraping
Ignore for now

3) Bulk convert Staging → Final – The Transformer
The Transformer takes standardized recipe candidates (RecipeSage JSON-LD) and turns them into final database records using one uniform pipeline.
What this stage is for
•	Canonicalization: make fields consistent across sources (titles, notes, categories/tags, yield/servings, times, etc.).
•	Normalization: clean and normalize text, whitespace, punctuation, and common cookbook conventions.
•	Structuring: convert “mostly-raw” lists (ingredient lines, instruction text) into the structured representation required by the final schema.
•	Quality + repeatability: everything should be validated, versioned, and re-runnable.
Core principles
•	Schema-first: output must conform to the final schema (and include a schema version).
•	Hybrid parsing: use deterministic parsing by default; use LLM assistance only when ambiguity blocks progress.
•	Validation gates: every transformation step produces output that can be checked (types, required fields, ranges, enum values).
•	Traceability forever: keep the original ingredient lines and instruction text, plus provenance back to the source and staging candidate.
High-level flow
1.	Load + validate candidate (RecipeSage JSON-LD) and attach provenance + IDs.
2.	Canonicalize metadata (naming, yield/servings, time fields, tags/categories, notes).
3.	Ingredients
	o	Split into groups when group headers exist.
	o	Parse each ingredient line into structured fields (amount, unit, item, preparation, optionality).
	o	Normalize units and (optionally) compute metric equivalents.
	o	Always retain the original line as a raw/trace field.
4.	Instructions
	o	Split into steps; keep step text intact.
	o	Optionally extract timers/temps/tools when your final schema supports it.
5.	Ambiguity handling (LLM only when needed)
	o	Trigger only for cases the deterministic logic can’t confidently resolve (shorthand, fused sections, irregular phrasing).
	o	Require strict JSON output that matches a constrained schema.
	o	Validate; if invalid, run an automatic repair pass; if still invalid, fall back to minimally-structured storage + a “needs review” flag.
6.	Emit final record (final schema) + keep a link back to the staging candidate.
This is the stage where your final schema decisions get enforced consistently, while keeping enough raw context to re-transform later if you change the schema or parsing rules.



________________________________________
A concrete “do this next” plan
1.	Start with the “easy wins”:
	o	Paprika export .paprikarecipes → staging
	o	Excel → staging
	o	Text files → staging
2.	Pick your OCR/layout tool for books/PDFs and run it once (store outputs). Textract is a common choice for layout-aware extraction. (AWS Documentation)
3.	Build the canonicalization pass to JSON-LD-like recipe objects.
4.	Only then implement the final mapping into your custom ingredient/step structure.



High level structure
The “shape” of the whole thing (holistically)
Think of it as a local data-processing app with a plugin-based import pipeline:
Input folder → detect file types → per-source “extract to blocks” → segment into recipe candidates → emit staging JSON-LD → transform into your final DB format
That’s one cohesive package, but internally it’s a few layers that you can swap without rewriting everything.
What languages + tools you’ll actually use
1) Main language: Python
Python is the sweet spot for:
•	PDFs / layout extraction
•	EPUB/HTML parsing
•	Excel parsing
•	calling LLM APIs
•	CLI tooling
•	quickly iterating on heuristics + validators
You can absolutely do this whole project in Python and stay sane.
Typical Python libs you’ll end up using:
•	CLI: typer (or click)
•	Data validation / schemas: pydantic
•	Logging + nice terminal UX: rich (progress bars, tables)
•	SQLite state DB: built-in sqlite3 (or sqlalchemy if you feel fancy later)
•	PDFs: pymupdf (fitz)
•	EPUB/HTML: beautifulsoup4, lxml, optionally ebooklib
•	Excel: openpyxl (and optionally pandas for convenience)
•	Unstructured (optional): unstructured library or self-hosted container
2) Optional second language (only if you want a UI): TypeScript
If you eventually want a review/correction UI:
•	Backend stays Python (FastAPI)
•	Frontend: TypeScript + React (or even a minimal HTML page if you want to keep it simple)
But you do not need this on day 1.

Can it be command-line only?
Yes. CLI-only is totally reasonable for personal use and for scale—especially because your pipeline naturally produces artifacts (JSON-LD + debug HTML) that you can inspect without a full app.
A great pattern for this kind of project is:
•	CLI does all the work
•	It also generates review artifacts (HTML reports, “needs_review” folders)
•	Only later, if you’re tired of opening files manually, you add a small UI
The “review loop” without building a UI
Instead of a GUI, your tool can generate:
•	reports/book_<id>.html listing each candidate + warnings + previews
•	needs_review/ folder containing the problematic recipes + reasons + source pointers
That gets you 80% of the benefit of a UI with 5% of the effort.

What the package looks like in practice
A) It’ll be a Python package with a single entrypoint command
You’ll run it like:
cookimport ingest ./my_cookbooks --out ./staging
cookimport transform ./staging/recipesage_jsonld --out ./final
cookimport report ./staging --open
B) Internally: a “pipeline engine” + “plugins”
Your codebase will feel like:
•	cookimport/core/
pipeline runner, hashing, caching, artifact registry, validation
•	cookimport/sources/
epub.py, pdf.py, text.py, excel.py, paprika.py, recipesage.py
•	cookimport/staging/
candidate schema + RecipeSage JSON-LD emitter
•	cookimport/transform/
JSON-LD → your final DB schema
•	cookimport/llm/
provider wrappers (Gemini/OpenAI/etc), JSON-schema constrained outputs, caching
This is the key idea: each source plugin outputs the same internal “candidate” object, and everything downstream is identical.

How it works “at scale” (1000s of files) without becoming painful
1)	Incremental processing via hashing + a tiny state DB
You want your tool to be restartable and idempotent:
•	Hash each input file (and optionally each extracted chunk)
•	Store “done/failed/needs_review” + artifact paths in SQLite
•	On re-run: skip anything unchanged
This is what makes “point it at a folder of chaos” actually work.
2)	Parallelism (but controlled)
You’ll do:
•	parallel file-level ingestion (multiple workers)
•	but rate-limit LLM calls (separate queue)
3)	Caching LLM results
If you ever re-run, you do not want to repay tokens for the same messy chunk:
•	cache by (model, prompt_version, input_hash)
4)	Artifact-first design (debuggable forever)
Everything important is written to disk:
•	raw extraction
•	blocks
•	candidates
•	staging JSON-LD
•	final outputs
•	reports
That makes it a “forensic pipeline” instead of a black box.

Distribution 
Python CLI installed locally
You install it once and just run the command.
•	Easiest to build and iterate
•	Best for learning
•	Cross-platform
Good ways to run it:
•	uv or poetry for dependency management
•	pipx install . for “install as a global CLI” without messing your system Python

clean “mental model” 
Your app is basically 3 subsystems:
1)	Ingest subsystem
•	scans folders
•	runs source plugins
•	produces staging JSON-LD + reports
•	records progress in SQLite
2)	Transform subsystem
•	reads staging JSON-LD
•	outputs your final DB records
•	can be rerun anytime without re-ingesting
3)	Review subsystem (optional, can be CLI-generated HTML)
•	surfaces low-confidence items
•	lets you fix or re-run with different settings


Tools
Unstructured.io
Unstructured (the open-source library + optional self-hosted API) is basically a “document → structured blocks” layer. You feed it an EPUB/PDF/image/etc, and it returns a list of typed “elements” (e.g., Title, NarrativeText, ListItem, Table, PageBreak) with metadata (page number, hierarchy, coordinates, section/chapter info, etc.). (docs.unstructured.io)
How “self-run Unstructured” works (your main options)
1)	Run it as a local Python library (simplest for a personal tool)
•	You install unstructured and call partition(...) or partition_epub(...).
•	partition(...) auto-detects file type using libmagic (or falls back to extension) and routes to the right parser. (docs.unstructured.io)
•	Output: a list of Element objects (or dicts) with type, text, element_id, metadata. (docs.unstructured.io)
2)	Run their unstructured-api container locally (nice when deps are annoying)
•	You run a Docker container that exposes an HTTP endpoint; you POST files and get JSON elements back.
•	The repo explicitly supports many doc types (including .epub) and has knobs like strategy, coordinates, OCR languages, etc. (GitHub)
•	This can be convenient because EPUB/PDF/image parsing often pulls in system deps (Tesseract, Poppler, Pandoc, etc.).
3)	Use unstructured-ingest CLI to batch a folder (close to your “point at a folder” wish)
•	It’s literally for batching files and writing structured output to a destination (including local). (docs.unstructured.io)
•	You might still wrap it in your own pipeline, but it’s a good reference implementation for “scan folder → process → emit JSON”.
Does it help your cookbook pipeline?
Yes—as a staging-layer accelerator, not as a “recipe parser.”
What it will help with
•	Uniform “blocks” across formats: EPUB/PDF/images/Word/Excel can all become the same element list abstraction. (docs.unstructured.io)
•	Hierarchy + structure signals you can exploit for recipe boundary detection:
	o	Title vs ListItem vs Table
	o	parent_id and category_depth to infer heading nesting (useful when cookbooks have consistent heading levels) (docs.unstructured.io)
	o	For EPUB specifically, metadata can include section (chapter/TOC section title). (docs.unstructured.io)
•	PDF layout/OCR strategy controls (more relevant to PDFs/scans than EPUB):
	o	fast, hi_res, ocr_only, auto, plus guidance on multi-column ordering tradeoffs and table extraction behavior. (docs.unstructured.io)
What it won’t do (you still need your logic/LLM here)
•	It won’t reliably say “this is a recipe” or split a cookbook into recipes for you.
•	It won’t convert “2 cloves garlic, minced” into your ingredient schema.
•	Think of it as: “give me clean, labeled chunks + metadata so I can do recipe segmentation + extraction.”
For EPUB cookbooks specifically: where Unstructured fits
Unstructured’s partition_epub does: EPUB → HTML (via Pandoc) → partition_html → elements. You need Pandoc installed. (docs.unstructured.io)
That means it can replace a chunk of your “EPUB → HTML → detect headings” work if Pandoc’s HTML output is good enough for your books.
A practical EPUB pipeline using Unstructured looks like:
1.	EPUB → Elements
	o	Use partition_epub() (or unzip/Calibre → HTML, then partition_html() if you want more control over the HTML you feed in). (docs.unstructured.io)
2.	Elements → “recipe candidates”
	o	Use patterns like:
			 a Title element that looks like a recipe name (short-ish, title case, etc.)
			 followed by ListItem runs (often ingredients)
			 followed by NarrativeText / more ListItem (steps)
			 plus anchor cues (“Ingredients”, “Method”, “Directions”) appearing as Title/NarrativeText
	o	Use EPUB section metadata to keep candidates inside a chapter context. (docs.unstructured.io)
3.	Candidate → RecipeSage JSON-LD
	o	Deterministic extraction where possible; escalate to LLM only when the candidate is ambiguous.
Privacy / hosted API gotcha (important for purchased cookbooks)
If you ever consider Unstructured’s free-tier hosted API, they’ve stated they will start collecting/storing uploaded documents for model training/eval, and free-tier usage is capped (they mention 1,000 pages/month). For “don’t leak my paid cookbooks,” stick to local OSS / self-host. (Unstructured)
The open-source components are under Apache-2.0. (GitHub)
Minimal “glue” sketch (local library)
from unstructured.partition.auto import partition
from unstructured.partition.epub import partition_epub

# Generic “any file” ingestion
elements = partition(filename="some_file.epub")  # auto-detects type via libmagic :contentReference[oaicite:14]{index=14}

# Or explicitly for EPUB (gives you more control / clarity)
elements = partition_epub(filename="cookbook.epub")  # requires pandoc :contentReference[oaicite:15]{index=15}

# elements are typed blocks with metadata (type/text/element_id/metadata) :contentReference[oaicite:16]{index=16}
My take for your project
•	Use Unstructured as the “source → candidate blocks” layer especially for PDFs/scans, because layout/OCR/table handling is where DIY pipelines get painful. (docs.unstructured.io)
•	For EPUB, it’s worth testing on ~5 representative cookbooks:
	o	If partition_epub preserves headings/sections well enough, it can simplify your A) path a lot. (docs.unstructured.io)
	o	If it flattens structure too much (Pandoc can vary), keep your Calibre/unzip HTML pipeline and optionally still run partition_html on your extracted HTML for a consistent element schema. (docs.unstructured.io)
If you want, paste (or describe) one “typical” EPUB’s internal structure (TOC depth + whether recipes are one-per-chapter vs multiple-per-chapter), and I’ll outline concrete heuristics for recipe boundary detection on top of Unstructured’s element stream.

Amazon Textstract
If needed for tough PDFs, etc
FERMI
Let’s do this as a Fermi estimate and keep it parameterized so you can swap in your own assumptions.
1)	How much text is 300 cookbooks?
•	Cookbooks: 300
•	Pages each: 250
•	Total pages: 300 × 250 = 75,000 pages
Tokens per page (the big unknown)
Cookbook pages vary a lot (photos/whitespace vs dense instructions). If you’re “less worried about OCR” and you’re mostly extracting the text that is there, a reasonable ballpark:
•	Low density: ~200 tokens/page (lots of photos, short recipes)
•	Typical: ~400 tokens/page
•	High density: ~700 tokens/page (dense layout, lots of text)
So total raw content input tokens:
•	Low: 75,000 × 200 = 15M
•	Typical: 75,000 × 400 = 30M
•	High: 75,000 × 700 = 52.5M
That’s the “you must read this much text” baseline.
2)	Chunking overhead (instructions + schema + separators)
Chunking doesn’t change the raw content tokens much, but it adds repeated overhead per request.
A common setup:
•	Chunk size: ~2,000 input tokens of book text
•	Prompt/schema overhead per call: ~250–600 tokens (instructions + JSON schema + examples)
Number of chunks (typical case):
•	Total content ~30M tokens / 2,000 ≈ 15,000 chunks
Overhead tokens:
•	Low overhead: 15,000 × 250 = 3.75M
•	High overhead: 15,000 × 600 = 9.0M
So typical total input including overhead:
•	30M + (3.75M to 9M) ≈ 34M–39M input tokens
(If your pages are denser/lighter, scale from the raw-content ranges above.)
3)	Output tokens (this is where designs explode)
Output depends on whether you ask the model to repeat full recipe text into JSON, or just emit structured fields + pointers.
Option A — “Indexing only” (cheap output)
Model outputs something like:
•	{type: "recipe"|"tip", title, page_range, confidence, maybe tags}
…and you keep the actual text elsewhere.
Ballpark output:
•	~80–200 tokens per chunk (a few items + metadata)
For ~15,000 chunks:
•	1.2M–3.0M output tokens
Option B — “Full structured recipe JSON” (moderate/heavy output)
If you want full JSON per recipe (title, ingredients, steps, times, yields, etc.), output scales with number of recipes, not pages.
Typical cookbook might have 80–150 recipes (wildly varies). Pick a middle: 120 recipes/book:
•	Total recipes ≈ 300 × 120 = 36,000 recipes
Tokens per recipe JSON:
•	Lean JSON (no verbosity): ~250–450 output tokens/recipe
•	More detailed/normalized fields: ~450–800 tokens/recipe
So recipe output:
•	Low: 36,000 × 250 = 9.0M
•	Typical: 36,000 × 450 = 16.2M
•	High: 36,000 × 800 = 28.8M
Tips add extra. Suppose 30–100 tips/book (again varies). If 60 tips/book → 18,000 tips:
•	~40–120 tokens/tip → 0.7M–2.2M output tokens
So Option B output all-in:
•	~10M to 30M output tokens (typical maybe ~17M–20M)
Option C — “Verbatim text in JSON too” (very heavy output)
If you include full raw text snippets for every extracted item, output can approach the same order as input (because you’re basically asking the model to reprint the book). That can easily push output into 20M–60M+ by itself.
4)	Putting it together (overall totals)
Using the “typical” middle assumptions:
•	Raw content input: ~30M
•	Chunk overhead input: ~4M–9M
•	Output:
	o	Option A (index/pointers): ~1M–3M
	o	Option B (full recipe JSON): ~10M–30M
Overall ballparks
•	Indexing + pointers approach:
~35M–42M input + ~1M–3M output → ~36M–45M tokens total
•	Full structured extraction approach:
~35M–42M input + ~10M–30M output → ~45M–72M tokens total
If your pages are dense (700 tokens/page), shift those totals up by roughly +20M input tokens.
5)	Two quick levers that change the math a lot
1.	Reduce repeated prompt/schema overhead
Process whole cookbooks (or big sections) per call if your model’s context window allows it.
Example: 250 pages × 400 tokens/page ≈ 100k tokens per book — some models can almost fit that in one go, which drops overhead massively (from ~15,000 calls to a few hundred).
2.	Don’t make the model reprint text you already have
Store raw extracted text outside the model output; have the model emit IDs + structured fields. This can turn Option C into Option A/B cost.
________________________________________
If you tell me what your JSON looks like (minimal fields vs full ingredient normalization vs including full instructions verbatim), I can tighten the output estimate to a narrower range.
