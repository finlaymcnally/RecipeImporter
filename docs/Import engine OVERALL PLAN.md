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







