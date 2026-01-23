# my thoughts prior to building out importers

the next step is to build the epub/pdf/text/paprika/recipesage importers.

# BEST PRACTICES:

## “already in”

**Normalize everything into one intermediate shape** before recipe
detection/extraction. Your DocPack + blocks.jsonl idea is exactly that,
and it’s a great foundation for plugging in future sources without
rewriting downstream logic.

**Keep extraction deterministic first, then escalate** only when
confidence is low. Your “heuristics first, LLM later” decision is the
right default for predictability + debugging.

**Treat “confidence + reasons” as a first-class output**, not just an
internal score. You’re already planning candidate confidence/reasons;
that becomes the backbone for UI review (“needs attention”) and future
tuning. Confidence scoring is good.

**Design for resuming + idempotence** (cache work products; stable IDs).
You’re already planning rerunnable outputs + a resume-friendly work dir.

**Treat import as a pipeline with artifacts**: keep *raw → normalized →
candidates → parsed → emitted* outputs, and always write a
per-source/per-file report (warnings + confidence + what strategy was
used). You’re already planning this (raw/normalized artifacts + per-file
report + split decisions/confidence)

**Deterministic first, “AI” only when you must**: do simple, explainable
heuristics for section detection/splitting and only escalate when it’s
genuinely ambiguous (and validate the schema on the way back). That’s
exactly the right stance

**Idempotence + provenance everywhere**: stable IDs, content hashes, and
storing source offsets/URLs makes re-imports safe and makes debugging
possible months later. You already call out stable @id + offsets +
recovery artifacts

**Progressive enhancement**: start by reliably extracting *title +
ingredients + instructions* (strings), then add “nice to have”
enrichment (times, yield, ingredient quantity parsing) behind flags.
Your plan explicitly delays quantity parsing—good move

**Make “inspection” a first-class UX**: a command that prints split
mode, detected sections, and confidence (before writing anything)
prevents most frustration. You’ve got acceptance criteria pointing that
way

## “to do”

**Safe archive extraction** (EPUB is a ZIP): protect against path
traversal (“Zip Slip”) and zip bombs. Don’t extractall() blindly;
validate each member path and enforce size limits.

**Text normalization layer** *before* features/heuristics: Unicode
cleanup, whitespace normalization, de-hyphenation (PDF-ish), and
consistent newlines. This prevents lots of “why didn’t the regex match?”
headaches. ftfy is handy for real-world mojibake.

**Patch/override system**: even with great heuristics, you’ll want
“family-proof” edits. Store small override files (e.g., “in this book,
headings at level 3 are titles”, or “treat ‘Sauce’ as ingredient
subheader”). Apply these as a final transform so you can fix one
cookbook without changing global logic.

# Redundant work across the 3 plans

**1) “Feature”/signal logic is duplicated (or will be, unless
centralized)**

Both the EPUB and PDF plans rely on the same core signals (quantity/unit
patterns for ingredients; imperative-verb / step signals for
instructions; section labels; confidence scoring) for candidate
detection and extraction. EPUB even calls out that feature computation
should live in a shared module for reuse across PDF + text.  
If you don’t centralize this, you’ll end up re-implementing similar
regexes and heuristics in each importer (EPUB candidate detection
signals ; PDF candidate detection signals ; text parsing/metadata regex
).

**2) Candidate detection + field extraction pipelines overlap heavily
(especially EPUB vs PDF)**

EPUB: “scan blocks → candidates → extract
title/ingredients/instructions/metadata”  
PDF: “ordered blocks → candidates → extract
title/headnote/ingredients/instructions/metadata”  
They’re structurally the same once you have an ordered block stream; the
redundant work is writing two parallel implementations of
\_detect_candidates and \_extract_fields (or equivalent) instead of
sharing a single “block-stream recipe detector” used by both. (PDF’s
unique work is extraction + reading order reconstruction; EPUB’s unique
work is DocPack generation.)

**3) LLM escalation scaffolding is repeated in all three**

All three plans include “LLM escalation for low-confidence cases +
Pydantic validation”:

- Text

- EPUB

- PDF  
  That’s a good candidate for a shared utility: prompt templates +
  schema models + retry/validation policy.

**4) Output/report/idempotence patterns are repeated**

Each plan defines stable IDs and intermediate artifacts for resumption:

- EPUB stable @id + DocPack/work dir

- PDF stable @id + work/pages artifacts

- Text stable @id + raw/normalized/candidates artifacts  
  Also each produces JSON-LD + a report (e.g., text per-file report ;
  EPUB stage outputs + report ). The “shape” of these reports and the ID
  construction can be centralized so each importer only supplies
  provenance specifics.

# Do any rely on other plans being done first?

**PDF plan explicitly assumes EPUB exists first (at least in
sequencing)**

The PDF plan states the package has Excel and “(after the EPUB plan)
EPUB importers,” implying EPUB is intended to land before PDF.  
This reads more like an intended order than a hard technical dependency,
but it’s still a dependency in practice if you want to share the same
downstream block-stream detection/extraction approach.

**Text plan implicitly assumes EPUB + PDF already exist**

The text plan says the package already has importers for “Excel, EPUB,
and PDF.”  
Again: not a hard dependency, but it suggests this plan was written with
text coming after the other two.

**Shared “block_features” is an explicit cross-plan coupling**

EPUB plan: feature computation should be in
cookimport/parsing/block_features.py “for reuse across PDF and text
importers.”  
So if you follow that architecture, you’ll want to establish those
shared feature helpers early (either as part of EPUB work or as a small
“shared parsing primitives” mini-plan that precedes all three).

# Tools/libraries worth considering (by source)

## EPUB / ebooks

Calibre: ebook-convert as a robust fallback path (you already plan this)
and as a converter for MOBI/AZW3 → HTML/EPUB.

**ebooklib** is common for reading EPUB metadata/spine, but it can have
edge cases; keep your “direct unzip + parse” primary path like you
planned.

**epub-utils** is another option focused on EPUB 2/3
container/package/spine inspection and content access—could simplify
some OPF/container handling if you don’t want to maintain that yourself.

If you ever want “one ingestion API across formats,” **Unstructured**
can partition many document types into typed elements (you can map those
to your Block stream).

## Web pages

**recipe-scrapers**: often the fastest win for importing recipe sites
because it reads schema markup / OpenGraph and normalizes common fields.
THIS SEEMS REALLY GOOD. LOOK INTO IT LATER.

**extruct**: if you’re rolling your own, this pulls embedded JSON-LD /
Microdata / RDFa / OpenGraph out of HTML so you can grab
schema.org/Recipe cleanly when present.

**trafilatura**: helpful when pages don’t have good structured data and
you need “main text” extraction without writing per-site parsers.

**JS-heavy pages**: use **Playwright** to render and then run your usual
HTML → JSON-LD extraction.

**Fallback when there’s no structured recipe**: use an article/content
extractor to cut boilerplate before heuristics:

- **Trafilatura** (strong general-purpose extraction)

- **readability-lxml** (lighter-weight “main body” extraction)

**Best practice for web sources:** cache the raw HTML + extracted
JSON-LD alongside your normalized recipe, so you can re-run parsers
without re-fetching (and you can debug “why did this parse weird?”
later).

<https://pypi.org/project/scrape-schema-recipe/?utm_source=chatgpt.com>

## PDFs and scans

**OCRmyPDF**: easiest way to turn scanned PDFs into
searchable/text-selectable PDFs (adds an OCR text layer; deskew/rotate
options, etc.).

**Unstructured** (optional): can “partition” PDFs into typed layout
elements and can apply OCR when text isn’t available. Caveat: their docs
note multi-column ordering can be tricky in some strategies—so it’s more
of a fallback/assist than a replacement for your custom column
heuristics.

## Plain text / Markdown files

**Frontmatter parsing**: instead of hand-rolling YAML frontmatter,
consider **python-frontmatter** (handles YAML + other formats and gives
you (metadata, content) cleanly).

**Encoding detection**: your plan uses UTF-8 with fallbacks; adding
**charset-normalizer** can reduce “mystery mojibake” and give you better
diagnostics when decoding unknown files.

## Ingredient lines + unit normalization

**ingredient-parser**: parses ingredient sentences into structured
fields (quantity/unit/ingredient/etc.)—useful if you want scaling, unit
conversion, shopping lists, or deduping later. IM USING THIS ALREADY.

**pint**: unit math + conversions (great once ingredients are parsed).

**ingredient-slicer**: lightweight heuristic parser for
quantities/units/food words.

**parse-ingredients**: another pragmatic parser returning
name/unit/quantity/comment-style structure.

## Performance + dedupe

**orjson**: fast JSON serialization (nice for JSONL block streams and
reports).

**RapidFuzz**: fuzzy matching for deduping recipes/titles (“Grandma’s
Pancakes” vs “Grandma Pancakes”), or merging near-duplicates across
sources.
