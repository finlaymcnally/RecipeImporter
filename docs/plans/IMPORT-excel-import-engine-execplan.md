---
summary: "ExecPlan for the Excel-based staging import engine milestone."
read_when:
  - When implementing the Excel import engine milestone
---

# Excel Import Engine ExecPlan

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

This plan must be maintained in accordance with docs/PLANS.md from the repository root.

## Purpose / Big Picture

After this change, a user can point a local CLI at a folder that contains Excel workbooks and receive RecipeSage JSON-LD files plus a per-workbook report in a stable staging layout. The user will be able to run cookimport inspect on a single workbook to see a layout guess, inferred mapping, and a generated mapping stub file. They will be able to re-run the stage command safely because each recipe output is idempotent and tied to a stable identifier derived from the source file and row. Success is visible by the presence of staging/recipesage_jsonld/<workbook>/<sheet>/r<row>.json files and staging/reports/<workbook>.excel_import_report.json, plus stdout summaries from inspect.

## Progress

- [x] (2026-01-21 15:13Z) Drafted the initial ExecPlan and captured design decisions for the Excel import milestone.
- [x] (2026-01-21 15:28Z) Scaffold the Python package, dependency management, and CLI entrypoints for stage and inspect.
- [x] (2026-01-21 15:28Z) Implement core models, plugin interface/registry, and staging JSON-LD writer utilities.
- [x] (2026-01-21 16:02Z) Implement the Excel importer with detection, inspection, conversion, and reporting.
- [x] (2026-01-21 16:16Z) Add fixture workbooks, golden outputs, tests, and concise documentation notes for the new package.
- [x] (2026-01-21 17:00Z) Add support for combined "Recipe/Ingredients" columns and aggregating multiple tag columns (e.g. Cuisine, Type, Tool).
- [x] (2026-01-21 17:15Z) Update draft writer to include tags and source URL in the recipe notes field to prevent data loss.

## Surprises & Discoveries

- Observation: The environment lacks ensurepip, so `python3 -m venv .venv` fails and pip is unavailable without installing python3-venv.
  Evidence: `/usr/bin/python3: No module named pip` and `ensurepip is not available` during venv creation.
- Observation: System package installs are blocked without elevated permissions, and pip installation is blocked by PEP 668 in the base interpreter.
  Evidence: `apt-get update` failed with permission errors; `get-pip.py --user` failed with externally-managed-environment.
- Observation: Some legacy Excel files use "Recipe/Ingredients" as a combined column header, which wasn't detected by default aliases.
  Evidence: User report showing missing ingredient/instruction data for a "Cookbook cutdown.xlsx" file.

## Decision Log

- Decision: Use Python as a single local package named cookimport with a Typer-based CLI entrypoint named cookimport.
  Rationale: Typer gives readable CLI help and integrates well with type hints and Pydantic models.
  Date/Author: 2026-01-21 / Codex

- Decision: Use pyproject.toml with Pydantic v2, openpyxl, PyYAML, and Rich as dependencies and pytest as a dev dependency, installed via a local venv and pip.
  Rationale: A pyproject keeps dependency metadata in one place and works with standard tooling without introducing new external installers.
  Date/Author: 2026-01-21 / Codex

- Decision: Store provenance under the JSON-LD property recipeimport:provenance and use a URN-based @id derived from file hash, sheet name, and row.
  Rationale: This avoids collisions with RecipeSage fields while providing a stable, deterministic identifier for idempotent output.
  Date/Author: 2026-01-21 / Codex

- Decision: Default to wide-table layout on ambiguous layout detection, but always capture low-confidence flags in the report and mapping stub.
  Rationale: Wide-table is the easiest to correct and provides deterministic output rather than skipping data.
  Date/Author: 2026-01-21 / Codex

- Decision: Use a PEP 621 pyproject with setuptools as the build backend and expose the Typer app via the cookimport script entrypoint.
  Rationale: This keeps packaging standard while ensuring the CLI entrypoint is available without extra wrappers.
  Date/Author: 2026-01-21 / Codex

- Decision: Use workbook stems (not full filenames) for staging folder names while preserving full filenames in provenance metadata.
  Rationale: This keeps staging paths compact and stable while retaining the original filename in the output metadata.
  Date/Author: 2026-01-21 / Codex

- Decision: When formula cells have no cached value, fall back to the formula string from the non-read-only workbook for inspection/conversion.
  Rationale: This preserves intent in cases where data-only extraction returns nulls.
  Date/Author: 2026-01-21 / Codex

- Decision: Prefer tall/relational layout detection when the canonical recipe/section/value columns are present by boosting its score above the wide-table header score.
  Rationale: Tall sheets otherwise appear ambiguous and default to wide-table, which fragments recipes.
  Date/Author: 2026-01-21 / Codex
  
- Decision: Map "Recipe/Ingredients" to the ingredients field by default, and aggregate "Cuisine", "Type", and "Tool" columns into the tags field.
  Rationale: Better to capture combined data in one field than miss it entirely; metadata columns are best preserved as tags.
  Date/Author: 2026-01-21 / Codex

## Outcomes & Retrospective

Completed the Excel staging CLI and importer with mapping-aware inspection/conversion, staging outputs, and report generation. Added fixtures, goldens, and pytest coverage for wide, template, and tall layouts, with a generator script for reproducible Excel files. Remaining gap is only environment-dependent setup; the core feature set matches the milestone acceptance criteria.

## Context and Orientation

The repository currently contains documentation and Node tooling for listing docs, but no Python package or CLI implementation. This plan introduces a new Python package named cookimport at the repository root and adds tests and fixtures under tests/.

Key terms used in this plan are defined here. A RecipeCandidate is the internal, source-agnostic representation of one extracted recipe, holding title, ingredients list, instructions list, optional metadata, and provenance. A Mapping is the structured configuration that tells the Excel importer which layout to assume, where headers or cells are, how to split ingredient and instruction fields, and how to override inferred mappings. A ConversionReport is a per-workbook JSON file that summarizes what was extracted, what was skipped, and any warnings or errors. RecipeSage JSON-LD is a JSON-LD representation of a recipe that follows the Recipe schema used by RecipeSage; for this milestone it includes @context, @type, @id, name, recipeIngredient, recipeInstructions, and optional fields like description, recipeYield, keywords, and url. Provenance is a namespaced JSON object embedded in output that records file path, workbook, sheet, row index, headers, raw row values, and import metadata. Layouts refer to the three Excel structures the importer must detect: wide-table (one row per recipe with headers), template (one recipe per sheet with fixed cells or named ranges), and tall/relational (recipes spanning multiple rows grouped by keys or block boundaries).

The CLI is expected to expose two commands for the first milestone. The stage command scans a folder, detects Excel workbooks, and writes staging outputs. The inspect command operates on a single workbook, prints a summary, and writes a mapping stub file.

## Plan of Work

Milestone 1 establishes the project scaffolding, CLI, and core models. Create pyproject.toml, a cookimport package with __init__.py, a CLI module, and a small README note in cookimport/ explaining the package layout. Implement the plugin registry and the shared data models in cookimport/core/models.py using Pydantic, including RecipeCandidate, MappingConfig, SheetMapping, WorkbookInspection, ConversionReport, and ConversionResult types. Also add a minimal JSON-LD emitter module in cookimport/staging/jsonld.py that converts a RecipeCandidate into a JSON-LD dict, and an output writer in cookimport/staging/writer.py that handles stable file layout and idempotent IDs. The stage and inspect commands should exist but may only call stubbed importer methods at the end of this milestone. Define CLI arguments so stage accepts --out and an optional --mapping path, and so inspect accepts --out and an optional --write-mapping flag to control where mapping stubs are written. Acceptance for this milestone is a runnable CLI that shows help output and a documented package layout note in cookimport/README.md.

Milestone 2 implements the Excel importer end to end. Create cookimport/plugins/excel.py that loads workbooks via openpyxl, implements detect, inspect, and convert, and registers itself in the plugin registry. Implement layout detection by scanning the first 30 rows per sheet to score candidate header rows, then score layout signals for wide-table, template, and tall/relational layouts. Use a normalized header alias map to auto-map columns to canonical fields, and allow MappingConfig to override layout choice, header row, column aliases, and cell/range addresses. For template sheets, use named ranges when present and fall back to configured cell addresses. For tall/relational layouts, group rows by a key column or by blank-row block boundaries and assemble ingredient and instruction lists by type markers. Normalize cell text for whitespace and line endings, split ingredients and instructions into lists based on configured delimiters, and strip bullet and numeric prefixes while retaining order. Every recipe emitted must include a provenance object with original headers and raw cell strings, and each output must be validated for minimum fields before writing. The convert method must return a ConversionReport that includes counts, warnings, low-confidence flags, and a sample of parsed recipes. The inspect command should output a summary to stdout and write a mapping stub file with inferred layout and column mapping. The stage command should resolve mapping by first using --mapping when provided, then looking for a sidecar mapping file next to the workbook with a .mapping.yaml or .mapping.json suffix, and finally looking under <out>/mappings/<workbook>.mapping.yaml before falling back to inferred mapping. Acceptance for this milestone is a successful run of cookimport inspect on a fixture workbook that prints sheet layout guesses and writes a mapping stub, and cookimport stage that produces JSON-LD files and a report in the required staging layout.

Milestone 3 adds fixtures, golden outputs, and tests. Create fixture Excel files that cover wide-table, template, tall/relational, merged cells, multiline cells, formulas, and whitespace anomalies. Store them under tests/fixtures/ along with golden JSON-LD outputs and report JSON files. Implement pytest tests that load each fixture and compare emitted outputs to goldens, and ensure that inspect produces a mapping stub with expected keys. Acceptance for this milestone is a passing pytest run and documented instructions in cookimport/README.md describing how to run stage and inspect and where outputs appear.

## Concrete Steps

Work from /home/mcnal/projects/recipeimport. Create a virtual environment and install dependencies. Use the following commands and keep outputs brief and focused on success indicators.

  python -m venv .venv
  . .venv/bin/activate
  pip install -U pip
  pip install -e ".[dev]"

If the base image lacks ensurepip, install python3-venv first or use an environment that already provides pip before rerunning the commands above.
When python3-venv cannot be installed, use a venv without pip and bootstrap it manually:

  python3 -m venv --without-pip .venv
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  .venv/bin/python /tmp/get-pip.py

Create or update files as described in the Plan of Work. When generating fixture workbooks, use a small helper script in tests/fixtures/generate_fixtures.py so the binary files can be reproduced. Run it with:

  python tests/fixtures/generate_fixtures.py

Run the CLI help to confirm commands are wired:

  cookimport --help
  cookimport inspect --help
  cookimport stage --help

Run tests after the implementation:

  pytest

## Validation and Acceptance

The change is accepted when the following observable behaviors are verified. Running cookimport inspect tests/fixtures/wide_table.xlsx prints a sheet list, a layout guess, an inferred header row, and a mapping summary, and writes a mapping stub file in staging/mappings/wide_table.mapping.yaml (or a configured output path). Running cookimport stage tests/fixtures --out staging produces JSON-LD files under staging/recipesage_jsonld/<workbook>/<sheet>/r<row>.json and a report at staging/reports/<workbook>.excel_import_report.json. Each output JSON-LD object includes @context, @type "Recipe", @id, name, recipeIngredient, recipeInstructions, and a recipeimport:provenance object with file, sheet, row, headers, and raw row values. The report JSON lists counts, skipped rows, missing field counts, low-confidence sheets, and samples. All pytest tests pass and at least one test fails if the Excel importer or mapping logic is removed.

## Idempotence and Recovery

The stage command must be safe to run multiple times. It should compute stable @id values as urn:recipeimport:excel:<file_hash>:<sheet_slug>:r<row_index> so that reruns rewrite the same output path for the same input row. If output files already exist, overwrite them in place rather than creating duplicates. If conversion fails for one workbook, the CLI should continue to other files and include the error in the report for the failed workbook. Mapping stub generation must be deterministic so rerunning inspect produces the same stub for the same workbook unless the user changes config.

## Artifacts and Notes

Include minimal, focused examples in the repository to aid verification. For example, in tests/fixtures/expected/wide_table/r2.json, the JSON-LD should resemble the following structure (values shown are illustrative, not exhaustive):

  {
    "@context": ["https://schema.org", {"recipeimport": "https://recipeimport.local/ns#"}],
    "@type": "Recipe",
    "@id": "urn:recipeimport:excel:abc123:sheet1:r2",
    "name": "Example Recipe",
    "recipeIngredient": ["1 cup flour", "2 eggs"],
    "recipeInstructions": ["Mix", "Bake"],
    "recipeimport:provenance": {
      "file_path": "...",
      "workbook": "wide_table.xlsx",
      "sheet": "Sheet1",
      "row_index": 2,
      "original_headers": ["Title", "Ingredients", "Instructions"],
      "original_row": {"Title": "Example Recipe", "Ingredients": "1 cup flour\n2 eggs", "Instructions": "Mix\nBake"},
      "import_timestamp": "2026-01-21T15:13:00Z",
      "converter_version": "0.1.0"
    }
  }

The mapping stub file should include layout, header row, and field aliases in YAML form. Keep these artifacts short and focused on demonstrating structure rather than exhaustive content.

## Interfaces and Dependencies

Dependencies must include openpyxl for Excel parsing, typer for CLI, pydantic for models and validation, PyYAML for config, and rich for optional terminal formatting. Tests must use pytest. Define the core interface and types as follows and keep names stable so later sources can implement the same contract.

In cookimport/plugins/base.py, define an Importer protocol:

  from pathlib import Path
  from typing import Protocol
  from cookimport.core.models import WorkbookInspection, MappingConfig, ConversionResult

  class Importer(Protocol):
      name: str
      def detect(self, path: Path) -> float: ...
      def inspect(self, path: Path) -> WorkbookInspection: ...
      def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult: ...

In cookimport/plugins/registry.py, define a registry that returns the best importer by confidence and allows explicit selection by name. The stage command should call detect for each file extension candidate and choose the highest-confidence importer.

In cookimport/core/models.py, define Pydantic models with explicit fields and types for RecipeCandidate, MappingConfig, SheetMapping, WorkbookInspection, ConversionReport, and ConversionResult. RecipeCandidate should include name, ingredients, instructions, optional description, recipeYield, times, tags, source, and provenance. ConversionResult should include a list of RecipeCandidate objects plus a ConversionReport. Use Pydantic validators to normalize whitespace and ensure list types.

In cookimport/staging/jsonld.py, implement a function recipe_candidate_to_jsonld(candidate: RecipeCandidate) -> dict that maps fields to RecipeSage JSON-LD, including @context, @type, and @id. In cookimport/staging/writer.py, implement write_jsonld_outputs(results: ConversionResult, out_dir: Path) -> None that writes to the required staging layout using safe, slugified workbook and sheet names.

In cookimport/plugins/excel.py, implement detect to return a high confidence for .xlsx and .xlsm files and 0.0 otherwise. Implement inspect to return a WorkbookInspection containing sheets, inferred layout, header row, inferred mapping, and low-confidence flags. Implement convert to load the workbook with openpyxl using data_only=True, read_only=True for value access, and a non-read_only pass when merged cell ranges or named ranges are required. Normalize text early by replacing non-breaking spaces, trimming whitespace, and normalizing line endings. For merged cells, use the top-left value and forward-fill into the merged region when building row dictionaries.

The MappingConfig format must be serializable to YAML and JSON. It should include defaults for ingredient and instruction delimiters, row skip policy, per-sheet rules by name pattern, optional forced layout, header row override, column aliases for wide-table, and cell or named-range addresses for template sheets. The inspect command should generate a mapping stub with these fields populated for each sheet.

The ConversionReport JSON must contain total recipes, per-sheet counts, skipped rows with reasons, missing field counts, low-confidence mapping flags, a short sample list of parsed recipes, and the mapping used. This report is written to staging/reports/<workbook>.excel_import_report.json.

A placeholder structure_repair function should exist in cookimport/llm/repair.py with a clear docstring stating it is disabled for this milestone and returns None. This makes room for later LLM escalation without altering the pipeline contract.

Plan update note (2026-01-21 15:28Z): Marked milestone-1 scaffolding as complete, split the core-model work from the Excel importer, and recorded the packaging/CLI entrypoint decision after adding the initial package skeleton.
Plan update note (2026-01-21 16:02Z): Completed the Excel importer implementation, added CLI wiring and fixture/test coverage, and documented the local environment limitation that blocked running the generator and tests.
Plan update note (2026-01-21 16:16Z): Bootstrapped a pip-enabled venv using the no-ensurepip workaround, generated fixtures, ran CLI help commands, and verified pytest coverage passes.
Plan update note (2026-01-21 17:00Z): Add support for combined "Recipe/Ingredients" columns and aggregating multiple tag columns (e.g. Cuisine, Type, Tool).



## SOME IDEAS - less relevant now as this has been built
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