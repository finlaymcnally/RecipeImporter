---
summary: "High-level architecture, tech stack, and token cost estimation for the cookimport project."
read_when:
  - When planning the overall system structure
  - When evaluating Unstructured.io or LLM token budgets
---

> **ExecPlan Integration Notes (2026-01-24):**
>
> Ideas from this document have been distributed to execplans as follows:
>
> **Added to PROCESS-llm-repair.md:**
> - Token budget awareness (~30-40M tokens for 300 cookbooks)
> - Output strategy options (A: indexing, B: structured JSON, C: verbatim—avoid C)
> - Cost levers: batching, large context windows, caching, confidence thresholds
> - Recommendation to use Option A for identification, Option B for final extraction
>
> **Added to IMPORT-epub-importer-execplan.md:**
> - Unstructured.io as alternative extraction layer
> - `partition_epub()` usage pattern
> - When to consider vs keep current approach
> - Privacy warning about hosted API
>
> **Added to IMPORT-pdf-importer-execplan.md:**
> - Unstructured.io as alternative for tough PDFs/scans
> - Layout/OCR strategy options (fast, hi_res, ocr_only)
> - Integration pattern with partition()
> - Privacy warning about hosted API
>
> **Already covered (no changes needed):**
> - High-level pipeline structure (already in "Import engine OVERALL PLAN.md")
> - Plugin-based architecture (already in Excel/EPUB/PDF execplans)
> - Incremental processing via hashing (already in reporting/provenance plan)
> - Artifact-first design (already in reporting/provenance plan)
> - CLI structure (already implemented)

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
elements = partition_epub(filename="cookbook.epub")  # requires pandoc :contentReference

# elements are typed blocks with metadata (type/text/element_id/metadata) :contentReference
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
