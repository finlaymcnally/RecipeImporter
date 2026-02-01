# In-Depth Report: Tip and Knowledge Extraction Pipeline

This report provides a comprehensive architectural and procedural overview of the tip and knowledge extraction pipeline in the `cookimport` project. It is intended to serve as a standalone reference for understanding how "kitchen wisdom" is harvested from unstructured cookbook data.

---

## 1. Project Context

`cookimport` is a multi-format ingestion engine designed to transform cookbooks (PDF, EPUB, Excel, Text) into structured Recipe Drafts (JSON-LD). The **Tip Extraction Pipeline** is a specialized sub-system within `cookimport` that focuses on identifying non-recipe content—advice, techniques, and general knowledge—that often lives in the "margins" of a cookbook.

---

## 2. Technical Stack and Dependencies

The pipeline is built in Python and relies on several key technologies:
- **Pydantic**: Used for structured data models (`TipCandidate`, `TopicCandidate`).
- **spaCy**: Optionally used for advanced NLP, specifically for high-precision imperative verb detection in instructions and tips.
- **docTR / OCR**: When processing scanned PDFs, the system relies on OCR-generated text blocks which are then "atomized" for tip extraction.
- **Regex**: Extensive use of pattern matching for signal detection and span identification.

---

## 3. Operational Entrypoint

The pipeline is typically triggered as part of the `stage` command, which can be run via the interactive `C3imp` menu or directly:
```bash
python -m cookimport.cli stage <input_file>
```
During staging, the system identifies recipes and standalone text blocks. Any text not identified as a recipe component (ingredients/instructions) is passed to the Tip Extraction Pipeline.

---

## 4. Core Components

### 4.1 Data Models (`cookimport/core/models.py`)
- **`TipCandidate`**: Represents an extracted piece of advice. Includes `scope` (`general`, `recipe_specific`, or `not_tip`), `text`, `generality_score`, and `tags`.
- **`TopicCandidate`**: Represents informational content that doesn't qualify as a tip (e.g., "All About Olive Oil").
- **`TipTags`**: A structured set of categories (meats, vegetables, techniques, etc.) used for tagging.

### 4.2 Extraction Logic (`cookimport/parsing/tips.py`)
This is the heart of the pipeline. It handles the transformation of raw text into structured `TipCandidate` objects. It uses a `TipParsingProfile` to define patterns and anchors.

### 4.3 Signal Detection (`cookimport/parsing/signals.py`)
Provides heuristic-based features used to score the "tipness" of a text block:
- `has_imperative_verb`: Identifies action-oriented advice ("Whisk until smooth").
- `is_ingredient_likely`: Helps exclude ingredient lists from being classified as tips.
- `is_instruction_likely`: Distinguishes between recipe steps and general advice.

### 4.4 Taxonomy (`cookimport/parsing/tip_taxonomy.py`)
A dictionary-based mapping of terms (e.g., "cast iron", "sear", "brisket") used to automatically tag tips with categories like `tools`, `techniques`, or `ingredients`.

---

## 5. The Extraction Process

### 5.1 Input Sources
Tips are extracted from two primary contexts:
1.  **Recipe Context**: Scanning `description` or `notes` fields of a parsed recipe.
2.  **Standalone Context**: Scanning cookbook sections specifically dedicated to tips, variations, or general knowledge (e.g., a "Test Kitchen Tips" sidebar).

### 5.2 Atomization (`cookimport/parsing/atoms.py`)
Raw text is first broken down into "atoms":
- **Paragraphs**: Split by double newlines.
- **List Items**: Identified via bullet or number patterns.
- **Headers**: Identified by length, casing, and trailing colons.

Atoms preserve context (`context_prev`, `context_next`), which is critical for "Repair" operations if an advice span is split across sentences.

### 5.3 Span Extraction and Repair
The system identifies "spans" of text that might be tips using prefixes ("TIP:", "NOTE:") or advice anchors ("Make sure", "Always"). If a tip seems incomplete (e.g., ends without punctuation), the pipeline "repairs" it by merging with neighboring atoms.

---

## 6. Classification and Judgment (`_judge_tip`)

The system determines the `scope` and `confidence` of a candidate using two primary metrics:

### 6.1 Tipness Score
A score from 0.0 to 1.0 based on:
- **Positive Signals**: Imperative verbs, modal verbs (should, must), diagnostic cues ("you'll know it's done when"), benefit cues ("makes it crispier").
- **Negative Signals**: Narrative cues ("I remember when"), yield/time metadata, or high overlap with recipe ingredients.

### 6.2 Generality Score
Determines if the advice is "General" (applies to many recipes) or "Recipe Specific".
- **General**: "Toast spices in a dry pan to release oils."
- **Recipe Specific**: "This version of the soup is better with more salt."
- **Logic**: The score decreases if the text explicitly mentions "this recipe" or overlaps significantly with the title of the recipe it was found in.

---

## 7. Output and Persistence (`cookimport/staging/writer.py`)

Results are written to `data/output/<timestamp>/tips/<workbook_stem>/`:
- **`t{index}.json`**: Individual JSON files for each classified tip.
- **`tips.md`**: A human-readable summary of all tips, grouped by source block and annotated with `t{index}` IDs and anchor tags for traceability.
- **`topic_candidates.json/md`**: Informational snippets that didn't meet the tip threshold but contain valuable context (Topics).

---

## 8. Tuning and Evaluation

The pipeline is tuned via `ParsingOverrides` (defined in mapping files or `.overrides.yaml` sidecars):
- **Custom Patterns**: Adding book-specific tip headers or prefixes.
- **Golden Sets**: Extracted tips are exported to **Label Studio** for manual verification. This "Golden Set" is used to calculate precision/recall and tune the `_judge_tip` heuristics.
