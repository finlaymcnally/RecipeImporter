Yep — there *are* projects that focus on pulling **recipe structure out of messy text / OCR**, not just schema.org.

## “Find the recipe bits” in unstructured text (ingredients vs instructions)

These are closer to what you want than classic site scrapers:

* **bees/rbk-nlp** — explicitly “extract recipes from unstructured text”; good place to steal ideas about leveraging the *implicit* structure (ingredients usually before directions, etc.). ([GitHub][1])
* **julianpoy/ingredient-instruction-classifier** — a ready-made model that classifies sentences as **ingredient / instruction / other**, which is basically the core step once you have OCR text lines. ([GitHub][2])
* **kriserickson/recipe-parser** — supervised system that classifies raw-page text segments into **title / ingredients / directions**; even though it’s built for HTML, the “segment classification” approach ports nicely to OCR lines/blocks. ([GitHub][3])
* **schollz/extract_recipe** — “tag-independent” extraction: converts HTML → text, then uses cooking-word density/peaks to find directions + ingredients. The heuristics are worth reading even if you never use the code as-is. ([GitHub][4])

## Ingredient-line parsers (pair these with a section splitter)

You already found a great one; here are a few more strong building blocks:

* **NYT ingredient-phrase-tagger** — CRF model that extracts **qty / unit / name / comments** from messy ingredient phrases (a classic reference implementation). ([GitHub][5])
* **anguswg-ucsb/ingredient-slicer** — lightweight heuristics for quantity/unit/food/prep that’s designed for “unstructured ingredients text”. ([GitHub][6])
* **jlucaspains/sharp-recipe-parser** — practical ingredient *and* instruction parsing (npm package) and tries to avoid regex-heavy approaches. ([GitHub][7])

## Scan/OCR-to-recipe projects (helpful for “grandma recipe scans in bulk”)

These are more end-to-end examples of the workflow you’re doing:

* **grantharper/recipe-ocr** — Tesseract-based pipeline with a **pluggable `RecipeParser` interface**, so you can swap in your own parser implementation. ([GitHub][8])
* **PeterMyer/Byte-RecipeReader** — cookbook-image → OCR → parse ingredients/instructions + an editing step (great for seeing what humans need to correct). ([GitHub][9])
* **tomwhite/ingreedy-js** — focuses on **photos** and uses **layout cues** to find ingredient blocks (super relevant if your scans have columns, boxes, or weird spacing). ([GitHub][10])

## OCR + layout tooling that makes recipe parsing *way* easier

If your scans vary a lot, the biggest win is often **detecting blocks (ingredients vs directions) before parsing**:

* **LayoutParser** — deep-learning layout detection toolkit for document images. ([GitHub][11])
* **docTR** — end-to-end OCR (text detection + recognition). ([GitHub][12])
* **PaddleOCR** — very popular OCR toolkit; useful if Tesseract struggles on certain fonts/layouts. ([GitHub][13])

## Training data (if you want ML later)

* **TASTEset-2.0** — annotated ingredient entities; useful if you eventually train/finetune an ingredient NER/tagger. ([GitHub][14])

---

### A practical combo that works well for “messy scans”

1. **Layout detect** (optional but huge) → 2) **OCR** → 3) **classify each line** (ingredient/instruction/other) → 4) **group into sections** → 5) run an **ingredient parser** on ingredient lines + simple step splitting on instructions.

If you tell me what your scans look like (handwritten? typed index cards? cookbook pages? columns?), I can point you at the best-fitting pipeline among the above and suggest a couple heuristics that usually move accuracy a lot.

[1]: https://github.com/bees/rbk-nlp "GitHub - bees/rbk-nlp: extract recipes from unstructured text"
[2]: https://github.com/julianpoy/ingredient-instruction-classifier "GitHub - julianpoy/ingredient-instruction-classifier: A TensorFlow model and tiny express server that can classify text as ingredient, instruction, or other."
[3]: https://github.com/kriserickson/recipe-parser "GitHub - kriserickson/recipe-parser"
[4]: https://github.com/schollz/extract_recipe "GitHub - schollz/extract_recipe: Extract recipes from websites, calculates cooking times, collects nutrition info from USDA database"
[5]: https://github.com/nytimes/ingredient-phrase-tagger "GitHub - nytimes/ingredient-phrase-tagger: Extract structured data from ingredient phrases using conditional random fields"
[6]: https://github.com/anguswg-ucsb/ingredient-slicer "GitHub - anguswg-ucsb/ingredient-slicer: Python  package for extracting quantity, units, and (sometimes) food names from unstructured recipe ingredients"
[7]: https://github.com/jlucaspains/sharp-recipe-parser "GitHub - jlucaspains/sharp-recipe-parser: Recipe ingredient and instructions parser"
[8]: https://github.com/grantharper/recipe-ocr "GitHub - grantharper/recipe-ocr: optical character recognition for recipes"
[9]: https://github.com/PeterMyer/Byte-RecipeReader "GitHub - PeterMyer/Byte-RecipeReader: Program to generate an accurate recipe ingredients, instructions, and nutrition label from a cook book recipe image"
[10]: https://github.com/tomwhite/ingreedy-js "GitHub - tomwhite/ingreedy-js: Ingredient parsing in Javascript"
[11]: https://github.com/Layout-Parser/layout-parser?utm_source=chatgpt.com "Layout-Parser/layout-parser: A Unified Toolkit for Deep ..."
[12]: https://github.com/mindee/doctr?utm_source=chatgpt.com "mindee/doctr: docTR (Document Text Recognition)"
[13]: https://github.com/PaddlePaddle/PaddleOCR?utm_source=chatgpt.com "PaddlePaddle/PaddleOCR"
[14]: https://github.com/taisti/TASTEset-2.0?utm_source=chatgpt.com "taisti/TASTEset-2.0"





Given what you’re building in `cookimport` (multi-source ingestion → intermediate JSON-LD → structured DraftV1, with strict provenance + separate tip extraction)  , I’d lean hardest on **(1) layout + OCR that gives bounding boxes**, then **(2) a “line/segment classifier” to split ingredients vs instructions vs narrative**, and only then the recipe structuring/tips logic.

Below is each tool from my list with a “how useful is this *for your pipeline*” take.

## Tool-by-tool: should you use it?

### bees/rbk-nlp

**Use as an ideas repo, not a drop-in.** It’s explicitly about extracting recipes from unstructured text, so it’s aligned with your goal. ([GitHub][1])
Where it helps you: steal the *approach* (model features, segmentation strategy) for OCR’d cookbook text, especially if you want to graduate from heuristics to ML.

### julianpoy/ingredient-instruction-classifier

**Strong yes.** It classifies sentences into ingredient / instruction / other, which is exactly the “messy text → buckets” step that stabilizes everything downstream. ([GitHub][2])
Where it plugs in: replace/augment your Stage 2 heuristic segmentation (name/description/ingredients/instructions) . Bonus: “other” becomes a natural bucket for **tips/headnotes/narrative** candidates.

##**Yes if you’re willing to label a little data.** It’s a supervised classifier that splits text into title/ingredients/directions (built for HTML, but the technique transfers well to OCR line-blocks). ([GitHub][3])
Why it fits you: you already have Label Studio integrated for benchmarking/ground truth , so you’re set up to train/evaluate a segmenter instead of chasing regex edge cases forever.

### schollz/extract_recipe

**Maybe (mostly for kimming.** It’s “extract recipes from websites…” and includes heuristics around pulling sections + times/nutrition. ([GitHub][4])
Where it helps you: as a fallback/heuristics reference for EPUB/HTML-ish inputs (you already do HTML cleaning for EPUB/Paprika) . For scanned cookbooks, it’s less directly useful.

### NYT ingredient-phrase-tagger

**Skip for now (you said ingredient parsing is solved).** It’s CRF-based tagging for ingre([GitHub][5])
If you ever revisit ingredients: it’s a good “classic” reference, but not your current bottleneck.

### anguswg-ucsb/ingredient-slicer

**Skip for now.** It’s a rules/heuristics ingredient parser. ([GitHub][6])

### jlucaspains/sharp-recipe-parser

**Maybe as a baseline / sanity-check parser, especially for “messy but typed” text.** It parses ingredients + instructions and tries to avoid regex-heavy logic. ([GitHub][7])
Where it helps you: if your pipeline is “buggy”, having a second independent parser can be great for diffing (“why did mine fail but this didn’t?”). Also, anything it confidently classifies as non-recipe could feed your tip/narrative pipeline.

### grantharper/recipe-ocr

**Useful as a reference, not a foundation.** It’s an OCR-to-recipe-import project, but it’s more “example app” than battle-tested extraction engine. ([GitHub][8])
Where it helps you: wiring patterns (batch OCR, storage), not the hard parsing logic.

### PeterMyer/Byte-RecipeReader

**Useful for product thinking (human-in-the-loop), not core parsing.** It’s an image → OCR → parse web app and it highlights the reality that you often need an edit/review step. ([GitHub][9])
Where it helps you: if you want this to work on handwriting, plan for a “review UI” or a lightweight correction pass on low-confidence chunks.

### tomwhite/ingreedy-js

**Skip (ingredient-focused).** It’s primarily ingredient parsing / nutrition use-cases. ([GitHub][10])

### LayoutParser

**Big yes for cookbooks + scans.** It’s specifically for document image layout detection and gives you block bounding boxes and structure. ([GitHub][11])
Why it fits your design goals: it plays super nicely with your “100% traceability/provenance” requirement because you can store coordinates/page regions alongside the extracted text .

### docTR

**Yes if you want an all-local OCR that also gives geometry.** It’s end-to-end OCR (detection + recognition). ([GitHub][12])
Where it fits: scanned PDFs / images of recipes. It can feed LayoutParser-style flows, or you can even start without LayoutParser and still keep word/line boxes for provenance.

### PaddleOCR

**Yes if you want “strong OCR at any cost of complexity.”** It’s widely used and geared toward structured outputs. ([GitHub][13])
Tradeoff: heavier dependency footprint + more knobs. But for old cookb, it can outperform simpler OCR setups.

### TASTEset-2.0

**Only if you decide to train models (later).** It’s an annotated dataset for food entity recognition in ingredients. ([GitHub][14])
For *tips*: it’s not directly a tips dataset, but it’s an example of the kind of annotation you’d want if you train your own “tip vs narrative vs instruction” classifier.

---

## What I’d personally “lean on” (minimum set)

If you want maximum leverage as a solo builder:

1. **LayoutParser** for cookbook/scanned page structure (blocks, reading order) ([GitHub][11])
2. **docTR or PaddleOCR** for OCR with bounding boxes (pick docTR for simpler local; PaddleOCR for stronger/gnarlier docs) ([GitHub][12])
3. **ingredient-instruction-classifier** (or similar) to bucket text lines into ingredient/instruction/other ([GitHub][2])
4. Treat **“other”** as your *tip/headnote/narrative* pool — then run your existing tips taxonomy/heuristics there  (and eventually replace that with a small supervised “tip vs narrative” model using Label Studio ).

That “everything the recipe parser doesn’t pick up = tip candidate” idea is solid — I’d just add one more bucket: **narrative/biography** (cookbooks are full of it), so tips don’t get drowned by stories.

If you want, paste a couple raw OCR outputs (one handwritten scan, one cookbook page) and I’ll show exactly where I’d insert layout/OCR/classification and what the “tip candidate” filtering rules would look like.



[1]: https://github.com/bees/rbk-nlp?utm_source=chatgpt.com "bees/rbk-nlp: extract recipes from unstructured text"
[2]: https://github.com/julianpoy/ingredient-instruction-classifier?utm_source=chatgpt.com "julianpoy/ingredient-instruction-classifier"
[3]: https://github.com/kriserickson/recipe-parser?utm_source=chatgpt.com "kriserickson/recipe-parser"
[4]: https://github.com/schollz/extract_recipe?utm_source=chatgpt.com "schollz/extract_recipe: Extract recipes from websites, ..."
[5]: https://github.com/nytimes/ingredient-phrase-tagger?utm_source=chatgpt.com "nytimes/ingredient-phrase-tagger: Extract structured data ..."
[6]: https://github.com/anguswg-ucsb/ingredient-slicer?utm_source=chatgpt.com "anguswg-ucsb/ingredient-slicer: Python 📦 package for ..."
[7]: https://github.com/jlucaspains/sharp-recipe-parser?utm_source=chatgpt.com "jlucaspains/sharp-recipe-parser: Recipe ingredient and ..."
[8]: https://github.com/grantharper/recipe-ocr?utm_source=chatgpt.com "grantharper/recipe-ocr: optical character recognition for ..."
[9]: https://github.com/PeterMyer/Byte-RecipeReader?utm_source=chatgpt.com "PeterMyer/Byte-RecipeReader"
[10]: https://github.com/tomwhite/ingreedy-js?utm_source=chatgpt.com "tomwhite/ingreedy-js: Ingredient parsing in Javascript"
[11]: https://github.com/Layout-Parser/layout-parser?utm_source=chatgpt.com "Layout-Parser/layout-parser: A Unified Toolkit for Deep ..."
[12]: https://github.com/mindee/doctr?utm_source=chatgpt.com "mindee/doctr: docTR (Document Text Recognition)"
[13]: https://github.com/PaddlePaddle/PaddleOCR?utm_source=chatgpt.com "PaddlePaddle/PaddleOCR"
[14]: https://github.com/taisti/TASTEset-2.0?utm_source=chatgpt.com "taisti/TASTEset-2.0"
