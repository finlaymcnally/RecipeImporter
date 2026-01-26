---
summary: "ExecPlan for extracting tip/knowledge snippets alongside recipes and exporting t*.json outputs."
read_when:
  - When implementing tip/knowledge extraction in the staging pipeline
---

# Add tip/knowledge extraction outputs

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

The file `docs/PLANS.md` in the repository root defines the required ExecPlan format and workflow. This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, running `cookimport stage <input>` will export not only recipes, but also tip/knowledge snippets as standalone JSON files named `t{index}.json`. Tips are non-instruction guidance such as “remove eggs from the pan just before they finish cooking” or “salt in layers while cooking.” Each tip JSON includes the text, provenance, a stable id, a scope classification (general vs recipe-specific), and tag guesses (recipe name, meats, vegetables, herbs, spices, dairy, grains, legumes, fruits, sweeteners, oils/fats, techniques, tools) so reviewers can index or filter them. “Why this recipe works” (and similar) should be treated as recipe-specific notes rather than general tips; those should not be exported as general tips. The output can be verified by staging a sample input and observing a new `tips/` output folder containing `t*.json` alongside existing `r*.json` recipe outputs.

## Progress

- [x] (2026-01-24 00:00Z) Read current pipeline docs, importer logic, and output writer to identify where non-instruction text is currently captured.
- [x] (2026-01-24 00:40Z) Implement tip/knowledge models, extraction logic, and tagging heuristics.
- [x] (2026-01-24 00:45Z) Integrate tip extraction into importers and output writer with `t*.json` files.
- [x] (2026-01-24 00:55Z) Update documentation and add tests/fixtures to validate tip extraction and tagging.
- [x] (2026-01-24 01:10Z) Run tests (pytest passes).
- [x] (2026-01-24 01:25Z) Add scope classification and skip recipe-specific notes from general tip export.
- [x] (2026-01-24 01:35Z) Append recipe-specific notes into DraftV1 `recipe.notes`.
- [x] (2026-01-24 18:30Z) Move tip extraction to block-first parsing with span repair, standalone/dependent classification, and generality scoring.
- [x] (2026-01-24 18:40Z) Persist tip candidate taxonomy (`general`, `recipe_specific`, `not_tip`) and add `standalone`/`generalityScore` metadata.

## Surprises & Discoveries

- Observation: PDF/EPUB importers already split non-instruction text into a `description` field; any blocks outside recipe ranges are currently dropped.
  Evidence: `cookimport/plugins/pdf.py` and `cookimport/plugins/epub.py` collect `description` and ignore blocks not in a candidate range.
- Observation: Excel/docx-table parsing merges “Notes/Tips” sections into `description`, so tips are available but not yet explicit.
  Evidence: `_extract_sections_from_blob` in `cookimport/plugins/excel.py` stores notes in `description`.
- Observation: Tip detection needs to allow imperative verbs when explicit tip cues (“Tip:”, “best”, “if/when”) are present; otherwise many tips are filtered as instructions.
  Evidence: `cookimport/parsing/tips.py` now gates instruction-like filtering on presence of tip cues.

## Decision Log

- Decision: Add a new `TipCandidate` model and store extracted tips in `ConversionResult.tips` so tips travel through the same staging pipeline as recipes.
  Rationale: Keeps tips tied to provenance, allows a single writer/CLI to emit all outputs per run, and avoids ad-hoc side channels.
  Date/Author: 2026-01-24 / Codex
- Decision: Create a new `tips/` output folder under each staging run and write `t{index}.json` files to avoid collisions with `r{index}.json` recipe outputs.
  Rationale: User requirement and keeps outputs parallel to existing recipe artifacts without changing recipe filenames.
  Date/Author: 2026-01-24 / Codex
- Decision: Implement a deterministic tagger v1 using lexicon matching (meats/vegetables/techniques/tools) plus recipe-name canonicalization, with an optional LLM-based refinement hook left for later.
  Rationale: Works offline and keeps the pipeline deterministic; LLM refinement can be added without blocking the initial feature.
  Date/Author: 2026-01-24 / Codex
- Decision: Expand tag categories to include herbs, spices, dairy, grains, legumes, fruits, sweeteners, and oils/fats.
  Rationale: Improves coverage of common cooking tips without adding external dependencies; taxonomy expansion remains deterministic.
  Date/Author: 2026-01-24 / Codex
- Decision: Classify tips as `general` or `recipe_specific` and exclude recipe-specific notes (for example “Why this recipe works”) from the general tips export.
  Rationale: Keeps the general tip/knowledge bank reusable across recipes while preserving recipe-specific context inside recipe descriptions.
  Date/Author: 2026-01-24 / Codex
- Decision: Switch tip extraction to block-first parsing with span repair, then judge tip-ness and generality on repaired spans.
  Rationale: Prevents chopped sentences and narrative fragments from becoming tips while keeping callout blocks intact.
  Date/Author: 2026-01-24 / Codex
- Decision: Track `standalone` and `not_tip` classifications on tip candidates, while only exporting standalone general tips to `tips/`.
  Rationale: Keeps output high precision while preserving taxonomy labels for evaluation and future UI filters.
  Date/Author: 2026-01-24 / Codex

## Outcomes & Retrospective

Implementation is complete and verified by test coverage. The pipeline now emits tip JSON outputs and tags, with unit tests covering extraction, tagging, and tip writer outputs. A manual CLI stage run should now show `tips/` outputs alongside recipes.
Recipe-specific notes (for example “Why this recipe works”) are now classified and excluded from the general tip export.
Those recipe-specific notes are appended to DraftV1 `recipe.notes` so they remain attached to their recipe.
Tip extraction now starts from paragraph/callout blocks, repairs dependent fragments with adjacent context, and labels tips with `standalone` and `generalityScore` metadata.
Recipe-sourced tips default to `recipe_specific` unless they read as strongly general, so the exported tips are primarily drawn from non-recipe text.

## Context and Orientation

The staging pipeline lives in the Python package `cookimport/`. The CLI entrypoint is `cookimport/cli.py`, which runs importers and writes outputs via `cookimport/staging/writer.py`. Importers (`cookimport/plugins/*.py`) return a `ConversionResult` containing `RecipeCandidate` objects. Those candidates are serialized to RecipeSage JSON-LD (`cookimport/staging/jsonld.py`) and DraftV1 (`cookimport/staging/draft_v1.py`). Output folders are created under `data/output/{timestamp}/` with `intermediate drafts/`, `final drafts/`, and `reports/` subfolders.

A “tip/knowledge snippet” is a short piece of guidance that is not a direct step-by-step instruction. Tips can appear in recipe headnotes or notes, or as standalone chapter text. For this plan we will treat tips as text snippets extracted from non-instruction content plus any lines explicitly labeled as tips/notes. Tips will be stored as structured JSON with tags to enable indexing. A “recipe-specific note” is guidance that only makes sense within a single recipe (for example, “Why this recipe works”). Recipe-specific notes should remain attached to the recipe context and should not be exported as general tips.

Key files to modify:

- `cookimport/core/models.py` for new models (`TipCandidate`, optional `TipTags`) and extending `ConversionResult` and `ConversionReport`.
- `cookimport/parsing/` for tip detection/tagging helpers.
- `cookimport/plugins/{pdf,epub,text,excel}.py` for tip extraction hooks and tip provenance.
- `cookimport/staging/writer.py` for new `write_tip_outputs()` and stable id handling.
- `cookimport/cli.py` to call the new writer and include `tips/` output folder.
- Documentation: `docs/brief update.md`, `docs/IMPORTANT CONVENTIONS.md`, `cookimport/README.md`, `cookimport/staging/README.md`, plus a short parsing note.

## Plan of Work

Create a `TipCandidate` model that mirrors `RecipeCandidate` in structure for provenance and identifiers but focuses on a `text` snippet, a `scope` (general or recipe-specific), and a `tags` payload. The tags payload should carry separate lists for `recipes` (canonicalized recipe names), `meats`, `vegetables`, `herbs`, `spices`, `dairy`, `grains`, `legumes`, `fruits`, `sweeteners`, `oils_fats`, `techniques`, and `tools`, plus an optional `other` list for freeform tags. Add a `source_recipe_id` field so tips extracted from a recipe can be linked back to a specific candidate.

Implement a parsing module (for example `cookimport/parsing/tips.py`) that provides deterministic tip detection, tagging, and scope classification. This module should expose a function that takes raw text plus optional recipe context and returns `TipCandidate` objects with `scope` set to either `general` or `recipe_specific`. Add explicit phrase and header detectors for “why this recipe works,” “why it works,” “test kitchen note,” or similar cookbook-specific note headings. These should default to `recipe_specific`. Use case-insensitive whole-word matching for taxonomy terms. Canonicalize recipe names by stripping possessives and common marketing adjectives (e.g., “Mom’s”, “Best”, “Quick”, “Easy”) so “Mom’s Favorite Scrambled Eggs” yields “scrambled eggs”. Use the recipe context to supplement tags (for example, if the recipe ingredient list includes “bacon”, tag the tip with `meats: ["bacon"]`).

Integrate tip extraction into each importer at the point where recipe candidates are created. For text and excel/docx-table importers, extract tips from `description` (and any explicit `Notes/Tips` sections) and attach `source_recipe_id` for tips derived from the candidate. For PDF and EPUB importers, extract tips from two sources: (1) within each candidate’s `description` text, and (2) standalone blocks not covered by any recipe candidate range. Standalone tips should be linked to provenance only (page number, block index) and not to a recipe id. Recipe-specific notes should be kept in recipe descriptions but not exported as general tips.

Extend `ConversionResult` with a `tips: list[TipCandidate]` field and `ConversionReport` with `totalTips` plus a `tipSamples` list of small previews. Update `cookimport/staging/writer.py` to add `write_tip_outputs(results, out_dir)` and to generate stable ids for tips (e.g., `urn:recipeimport:tip:{file_hash}:{sheet_slug}:t{index}`) similar to recipes. The writer should only emit `scope == "general"` tips to the `tips/` output folder by default, so recipe-specific notes do not pollute the general tip bank. The CLI should create a new output folder, for example `out/{timestamp}/tips/{workbook_slug}/`, and write `t*.json` files there. The writer should keep the existing `r*.json` naming unchanged.

Update documentation and add a tiny folder note where the new logic lives. Add a short `cookimport/parsing/README.md` note (or append to an existing parsing note) explaining how tip detection and tagging work. Update `docs/brief update.md` and `docs/IMPORTANT CONVENTIONS.md` to include the new output folder, naming, and data flow. Update `cookimport/README.md` and `cookimport/staging/README.md` to mention tips output. Ensure the new docs have proper front matter in `/docs` as required by `docs/docs-list.md`.

Add tests to validate tip extraction and tagging. Unit tests should cover: (1) tip detection from description lines, (2) tip detection from standalone blocks, (3) tag extraction for meats/vegetables/techniques/tools, and (4) recipe-name canonicalization. Add a small integration-style test for the writer to ensure `t*.json` outputs are written alongside recipes.

## Concrete Steps

Work in the repository root `/home/mcnal/projects/recipeimport`.

1) Add new models and tag structures in `cookimport/core/models.py` and extend `ConversionResult`/`ConversionReport`.
2) Implement `cookimport/parsing/tips.py` (and optionally `cookimport/parsing/tip_taxonomy.py`) with detection and tagging functions.
3) Update importers to extract tips and populate `ConversionResult.tips`.
4) Add `write_tip_outputs()` in `cookimport/staging/writer.py` and call it from `cookimport/cli.py`.
5) Update docs: `docs/brief update.md`, `docs/IMPORTANT CONVENTIONS.md`, `cookimport/README.md`, `cookimport/staging/README.md`, and a short parsing note.
6) Add tests under `tests/` for tip extraction and writer output. Create minimal fixtures as needed.
7) Run tests in a local virtual environment.

Commands (expected to be run from repo root):

    python -m venv .venv
    . .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e .[dev]
    pytest
    npm run docs:list

## Validation and Acceptance

Behavioral acceptance:

- After running `cookimport stage <input-folder> --out data/output`, a new folder `data/output/{timestamp}/tips/{workbook_slug}/` exists.
- The tips folder contains `t0.json`, `t1.json`, etc. with fields: `id`, `text`, `tags`, `provenance`, and optional `source_recipe_id`.
- Tips derived from recipe headnotes/notes include `source_recipe_id` and a canonicalized `recipes` tag (e.g., `"scrambled eggs"` instead of `"Mom's Favorite Scrambled Eggs"`).
- Standalone tips outside recipes include provenance (page number or line range) but no recipe id.
- “Why this recipe works” blocks are classified as recipe-specific and are not exported as general tips.

Test acceptance:

- `pytest` passes and includes new tests that fail before the change and pass after.
- A small golden test (or snapshot) confirms `write_tip_outputs()` names files `t*.json` and does not affect `r*.json` naming.

## Idempotence and Recovery

All steps are additive and safe to rerun. Re-running `cookimport stage` should produce a fresh timestamped output folder; no destructive changes are made. If tip extraction produces false positives, the feature can be disabled by short-circuiting tip extraction in importers without affecting recipe output.

## Artifacts and Notes

Expected output structure (example):

    data/output/2026-01-24-130000/
      intermediate drafts/{workbook_slug}/r0.jsonld
      final drafts/{workbook_slug}/r0.json
      tips/{workbook_slug}/t0.json
      reports/{workbook_slug}.excel_import_report.json

Example tip JSON (shape, not exact content):

    {
      "id": "urn:recipeimport:tip:abc123:sheet_slug:t0",
      "text": "Remove scrambled eggs from the pan just before they finish cooking.",
      "tags": {
        "recipes": ["scrambled eggs"],
        "meats": [],
        "vegetables": [],
        "techniques": ["carryover cooking"],
        "tools": ["skillet"],
        "other": []
      },
      "source_recipe_id": "urn:recipeimport:excel:abc123:sheet_slug:r4",
      "provenance": {
        "file_path": "...",
        "location": {"start_line": 120, "end_line": 122}
      }
    }

## Future Enhancements (from Improving_Recipe_Import_Pipeline.md)

The following ideas were extracted from the research document and may be valuable for future iterations:

**Multi-Pass Heuristic Parsing:**
- Consider a multi-pass approach where successive layers of rules refine extraction
- First pass extracts obvious recipes, second pass processes remaining text for tips
- Research shows rule-based multi-pass sieves achieved ~92.6% accuracy on mixed text segmentation

**Lexical Classification Signals:**
- General tips use generic language and avoid referencing the specific dish
- Recipe-specific notes contain "this dish", recipe names, or unique ingredients
- Length as a signal: short notes (1-2 sentences) are often recipe-specific, longer paragraphs explaining "why" are general knowledge
- Explanatory keywords ("because", "in order to", "best way") suggest broader knowledge

**ML-Assisted Classification (Future):**
- Zero-shot classification with BART-large MNLI for tip vs recipe-note vs instruction
- Weak supervision (Snorkel-style) using existing heuristics as labeling functions
- Clustering/topic modeling to discover tip content vs recipe content patterns

**Confidence-Based LLM Escalation:**
- Mark extracted tips with confidence scores
- Low-confidence cases can be reviewed or sent to LLM for final classification
- Keep provenance of which rule/model made each decision for debugging

## Interfaces and Dependencies

Add the following types and functions (names can be adjusted but should remain stable once implemented):

- In `cookimport/core/models.py`, define:

    class TipTags(BaseModel):
        recipes: list[str] = Field(default_factory=list)
        meats: list[str] = Field(default_factory=list)
        vegetables: list[str] = Field(default_factory=list)
        herbs: list[str] = Field(default_factory=list)
        spices: list[str] = Field(default_factory=list)
        dairy: list[str] = Field(default_factory=list)
        grains: list[str] = Field(default_factory=list)
        legumes: list[str] = Field(default_factory=list)
        fruits: list[str] = Field(default_factory=list)
        sweeteners: list[str] = Field(default_factory=list)
        oils_fats: list[str] = Field(default_factory=list)
        techniques: list[str] = Field(default_factory=list)
        tools: list[str] = Field(default_factory=list)
        other: list[str] = Field(default_factory=list)

    class TipCandidate(BaseModel):
        text: str
        scope: Literal["general", "recipe_specific"] = "general"
        tags: TipTags = Field(default_factory=TipTags)
        source_recipe_id: str | None = None
        provenance: dict[str, Any] = Field(default_factory=dict)
        confidence: float | None = None

    class ConversionResult(BaseModel):
        recipes: list[RecipeCandidate] = Field(default_factory=list)
        tips: list[TipCandidate] = Field(default_factory=list)
        report: ConversionReport
        ...

    class ConversionReport(BaseModel):
        total_tips: int = Field(0, alias="totalTips")
        tip_samples: list[dict[str, Any]] = Field(default_factory=list, alias="tipSamples")
        ...

- In `cookimport/parsing/tips.py`, provide:

    def extract_tips(text: str, *, recipe_name: str | None = None, recipe_id: str | None = None, provenance: dict[str, Any] | None = None) -> list[TipCandidate]

    def guess_tags(text: str, *, recipe_name: str | None = None, recipe_ingredients: list[str] | None = None) -> TipTags

    def canonicalize_recipe_name(name: str) -> str

- In `cookimport/staging/writer.py`, define:

    def write_tip_outputs(results: ConversionResult, out_dir: Path) -> None

The tip extractor should depend only on existing standard library modules plus the new taxonomy lists. It must not depend on external services. Any future LLM refinement should be behind an optional flag so the default pipeline stays deterministic.

Change note: Marked tests as complete and updated Outcomes to reflect verification status. Reason: pytest run completed successfully.
Change note: Expanded tag categories and taxonomy coverage. Reason: user requested additional tagging categories.
Change note: Added scope classification for recipe-specific notes (for example “Why this recipe works”) and updated plan to keep general tips reusable. Reason: user requested separating recipe-specific notes from general tips.
Change note: Implemented scope classification and updated extraction/tests to skip recipe-specific notes in the general tip export. Reason: align output with desired tip reusability.
Change note: Added DraftV1 note attachment for recipe-specific tips. Reason: user asked to keep “Why this works” notes with the recipe.
