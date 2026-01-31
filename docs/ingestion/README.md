---
summary: "Format-specific importers: Excel, EPUB, PDF, Text, Paprika, RecipeSage."
read_when:
  - Adding or modifying an importer plugin
  - Debugging extraction issues for a specific format
  - Understanding how source files are converted to RecipeCandidate
---

# Ingestion Pipeline

The ingestion phase extracts content from source files and normalizes to `RecipeCandidate` objects.

## Supported Formats

| Format | Plugin | Status | Key Features |
|--------|--------|--------|--------------|
| Excel (.xlsx) | `excel.py` | Complete | Wide/Tall/Template layout detection |
| EPUB (.epub) | `epub.py` | Complete | Spine extraction, yield-based segmentation |
| PDF (.pdf) | `pdf.py` | Complete | Column clustering, OCR support (docTR) |
| Text (.txt, .md) | `text.py` | Complete | Multi-recipe splitting, YAML frontmatter |
| Word (.docx) | `text.py` | Complete | Table extraction, paragraph parsing |
| Paprika (.paprikarecipes) | `paprika.py` | Complete | ZIP + gzip JSON extraction |
| RecipeSage (.json) | `recipesage.py` | Complete | Pass-through validation |
| Images (.png, .jpg) | `pdf.py` | Planned | Reuses PDF's OCR pipeline |
| Web scraping | - | Deferred | Not currently prioritized |

---

## Excel Importer

**Layouts detected:**
- **Wide**: One recipe per row, columns for name/ingredients/instructions
- **Tall**: One recipe spans multiple rows, key-value pairs
- **Template**: Fixed cells with labels (e.g., "Recipe Name:" in A1, value in B1)

**Key behaviors:**
- Header row detection via column name matching
- Combined column support (e.g., "Recipe" column containing both name and ingredients)
- Merged cell handling
- Mapping stub generation for user customization

**Location:** `cookimport/plugins/excel.py`

---

## EPUB Importer

**Extraction strategy:**
1. Parse EPUB spine (ordered content documents)
2. Convert HTML to `Block` objects (paragraphs, headings, list items)
3. Enrich blocks with signals (is_ingredient, is_instruction, is_yield)
4. Segment into recipe candidates using anchor points

**Segmentation heuristics:**
- **Yield anchoring**: "Serves 4", "Makes 12 cookies" mark recipe starts
- **Ingredient header**: "Ingredients:" section marker
- **Title backtracking**: Look backwards from anchor to find recipe title

**Key discoveries:**
- Section heading boundaries vary by cookbook style
- ATK-style cookbooks need yield-based segmentation
- Variation/Variant sections should stay with parent recipe

**Location:** `cookimport/plugins/epub.py`

---

## PDF Importer

**Extraction strategy:**
1. Extract text with PyMuPDF (line-level with coordinates)
2. Cluster lines into columns based on x-position gaps
3. Sort within columns (top-to-bottom)
4. Apply same Block → Candidate pipeline as EPUB

**Column detection:**
- Gap threshold: typically 50+ points indicates column break
- Falls back to single-column if no clear gaps

**OCR support:**
- Uses docTR (CRNN + ResNet) for scanned pages
- Triggered when text extraction yields minimal content
- Returns lines with bounding boxes and confidence scores

**Key discoveries:**
- PyMuPDF default ordering is "tiled" (left-to-right across page)
- Column clustering essential for multi-column cookbook layouts
- OCR `l` and `I` characters often misread as quantities

**Location:** `cookimport/plugins/pdf.py`, `cookimport/ocr/doctr_engine.py`

---

## Text/Word Importer

**Supported inputs:**
- Plain text (.txt)
- Markdown (.md) with YAML frontmatter
- Word documents (.docx) with tables

**Multi-recipe splitting:**
- Headerless files: split on "Serves" / "Yield" / "Makes" lines
- With headers: split on `#` or `##` headings

**DOCX table handling:**
- Header row maps to recipe fields
- Each subsequent row becomes a recipe
- Supports "Ingredients" and "Instructions" columns

**Key discoveries:**
- Yield/serves lines reliably indicate recipe boundaries in headerless files
- Quantity + ingredient patterns help classify ambiguous lines
- DOCX paragraphs need whitespace normalization

**Location:** `cookimport/plugins/text.py`

---

## Paprika Importer

**Format:** `.paprikarecipes` is a ZIP containing gzip-compressed JSON files.

**Extraction:**
1. Iterate ZIP entries
2. Decompress each entry (gzip)
3. Parse JSON to recipe fields
4. Normalize to RecipeCandidate

**Location:** `cookimport/plugins/paprika.py`

---

## RecipeSage Importer

**Format:** JSON export matching schema.org Recipe (our intermediate format).

**Behavior:** Mostly pass-through with:
- Validation against RecipeCandidate schema
- Provenance injection
- Field normalization

**Location:** `cookimport/plugins/recipesage.py`

---

## Shared Text Processing

All importers use shared utilities (`cookimport/parsing/`):

### Cleaning (`cleaning.py`)
- Unicode NFKC normalization
- Mojibake repair (common encoding issues)
- Whitespace standardization
- Hyphenation repair (split words across lines)

### Signals (`signals.py`)
Block-level feature detection:
- `is_heading`, `heading_level` - Typography signals
- `is_ingredient_header`, `is_instruction_header` - Section markers
- `is_yield`, `is_time` - Metadata phrases
- `starts_with_quantity`, `has_unit` - Ingredient signals
- `is_instruction_likely`, `is_ingredient_likely` - Content classification

### Patterns (`patterns.py`)
Shared regex patterns for:
- Quantity detection (fractions, decimals, ranges)
- Unit recognition (cups, tbsp, oz, etc.)
- Time phrases (minutes, hours)
- Yield phrases (serves, makes, yields)
