---
summary: "Combined snapshot of docs/ as of 2026-02-01_235255."
read_when:
  - When you need a single-file snapshot of the docs tree.
---
# Importer Docs Summary
Generated: 2026-02-01_235255
Source root: docs/

## docs/2026-02-01_235000_importer-docs-summary.md

```markdown
---
summary: "Combined snapshot of docs/ as of 2026-02-01_235000."
read_when:
  - When you need a single-file snapshot of the docs tree.
---
# Importer Docs Summary
Generated: 2026-02-01_235000
Source root: docs/

## docs/AGENTS.md

```markdown
---
summary: "Rules for working in /docs and key references."
read_when:
  - When editing documentation in /docs
---

# Agent Guidelines — /docs

This folder contains project documentation. Check folder-specific AGENTS.md files elsewhere for domain-specific guidance.

## Docs workflow

- Run `npm run docs:list` (or `npx tsx docs/docs-list.ts`) to see summaries and Read when hints.
- Read any doc whose Read when matches your task before coding.
- Keep docs current with behavior/API changes; add read_when hints on cross-cutting docs.

## Docs front matter (required)

Each `docs/**/*.md` file must start with front matter:

```md
---
summary: "One-line summary"
read_when:
  - "When this doc should be read"
---
```

`read_when` is optional but recommended.```

## docs/AI_Context.md

```markdown
---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
  - When you need to understand how recipe ingestion and parsing works in this codebase
---

# AI Onboarding & Project Summary: Recipe Import Pipeline

This document provides a technical overview of the `cookimport` project. It is designed to help AI developers and AI chatbots (who may not have direct access to the codebase) understand the architecture, data flow, and key algorithms.

## 1. Project Purpose

The `cookimport` project is a **recipe ingestion and normalization pipeline** that transforms messy, real-world recipe sources into structured, high-fidelity data. It handles:

- **Legacy Excel spreadsheets** with varying layouts (wide, tall, template-based)
- **EPUB cookbooks** with unstructured text requiring segmentation
- **PDF documents** (including scanned images with OCR)
- **Proprietary app archives**: Paprika (.paprikarecipes) and RecipeSage (.zip/JSON)
- **Plain text/Word documents**

### Key Objectives

1. **Universal Ingestion**: Handle diverse formats and layouts through a plugin-based architecture where each source type has a dedicated importer.

2. **Two-Phase Pipeline**:
   - **Phase 1 (Ingestion)**: Extract raw content and normalize to an intermediate JSON-LD format based on schema.org Recipe.
   - **Phase 2 (Transformation)**: Parse ingredients into structured fields, link ingredients to instruction steps, and produce the final `RecipeDraftV1` format.

3. **100% Traceability**: Every output field is traceable back to its source via a `provenance` metadata system that records file hashes, block indices, and extraction methods.

4. **Knowledge Extraction**: Beyond recipe scraping, the system identifies and extracts standalone "Kitchen Tips" and topical content.

## 2. Tech Stack & Active Dependencies

The project is built with **Python 3.12**. Key libraries:

### Core Frameworks
| Library | Purpose |
|---------|---------|
| **[Typer](https://typer.tiangolo.com/)** | Powers the CLI interface (`cookimport`, `C3imp`, `C3import` commands) |
| **[Pydantic V2](https://docs.pydantic.dev/)** | Strict data validation, schema enforcement, and JSON serialization for all models |
| **[Rich](https://rich.readthedocs.io/)** | Console output formatting, progress spinners, and status updates during processing |
| **[Questionary](https://questionary.readthedocs.io/)** | Interactive CLI prompts for guided workflows |

### Specialized Parsers (Production Use)
| Library | Purpose |
|---------|---------|
| **[Ingredient Parser](https://ingredient-parser.readthedocs.io/)** | NLP-based decomposition of ingredient strings into quantity, unit, item, preparation, and notes |
| **[PyMuPDF (fitz)](https://pymupdf.readthedocs.io/)** | High-performance PDF text and layout extraction |
| **[python-doctr](https://mindee.github.io/doctr/)** | Deep learning OCR for scanned PDFs (uses CRNN + ResNet architectures) |
| **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + [lxml](https://lxml.de/)** | HTML parsing for EPUB content and app archive formats |
| **[EbookLib](https://github.com/aerkalov/ebooklib)** | EPUB container structure management with fallback to raw ZIP parsing |
| **[Openpyxl](https://openpyxl.readthedocs.io/)** | Excel file processing with complex layout detection |
| **[python-docx](https://python-docx.readthedocs.io/)** | Word document text and table extraction |

### Quality Assurance & Evaluation
| Library | Purpose |
|---------|---------|
| **[Label Studio SDK](https://labelstud.io/)** | Creating ground-truth datasets for benchmarking parser accuracy |

## 3. Architecture Overview

### 3.1 Plugin System

The project uses a **registry-based plugin architecture** where each source format has a dedicated importer class:

```
cookimport/plugins/
  ├── registry.py      # Plugin registry with best_importer_for_path()
  ├── epub.py          # EPUB cookbook importer
  ├── pdf.py           # PDF document importer
  ├── excel.py         # Excel spreadsheet importer
  ├── paprika.py       # Paprika app archive importer
  ├── recipesage.py    # RecipeSage JSON archive importer
  └── text.py          # Plain text / Word document importer
```

Each plugin implements:
- `detect(path) -> float`: Returns confidence score (0.0-1.0) that this plugin can handle the file
- `inspect(path) -> WorkbookInspection`: Quick analysis of file structure
- `convert(path, mapping, progress_callback) -> ConversionResult`: Full extraction

### 3.2 Core Data Models

The system uses Pydantic models for type-safe data flow (see `cookimport/core/models.py`):

| Model | Purpose |
|-------|---------|
| `RecipeCandidate` | Intermediate format (schema.org JSON-LD compatible) with name, ingredients, instructions, metadata |
| `TipCandidate` | Extracted kitchen tip with scope (general, recipe_specific, not_tip) and taxonomy tags |
| `TopicCandidate` | Topical content block (sections about techniques, ingredient guides, etc.) |
| `ConversionResult` | Container for recipes, tips, topics, raw artifacts, and conversion report |
| `Block` | Low-level text block with type, HTML source, font weight, and feature flags |

### 3.3 Block & Signals Architecture

For unstructured sources (EPUB, PDF, text), the pipeline uses a **Block-based extraction model**:

1. **Block Extraction**: Source content is converted to a linear sequence of `Block` objects, each representing a paragraph, heading, or list item.

2. **Signal Enrichment** (`cookimport/parsing/signals.py`): Each block is analyzed for features:
   - `is_heading`, `heading_level` - Typography signals
   - `is_ingredient_header`, `is_instruction_header` - Section markers
   - `is_yield`, `is_time` - Metadata phrases
   - `starts_with_quantity`, `has_unit` - Ingredient signals
   - `is_instruction_likely`, `is_ingredient_likely` - Content classification

3. **Candidate Detection**: Blocks are segmented into recipe candidates using heuristics:
   - Backtracking from anchor points (yield phrases, ingredient headers)
   - Forward scanning with section boundary detection
   - Scoring based on ingredient/instruction density

## 4. Key Algorithms

### 4.1 Ingredient-Step Linking (Two-Phase Algorithm)

The step-ingredient linking algorithm (`cookimport/parsing/step_ingredients.py`) assigns each ingredient to the instruction step(s) where it's used:

**Phase 1: Candidate Collection**
- For each step, scan for mentions of each ingredient using multiple aliases (full text, cleaned text, head/tail tokens)
- Classify verb context: "use" verbs (add, mix, stir), "reference" verbs (cook, let rest), "split" signals (half, remaining)
- Score matches based on alias length, token overlap, and context

**Phase 2: Resolution**
- Default: Single best step wins (highest score)
- Exception: Multi-step assignment when split language detected ("add half the butter... add remaining butter")
- Fraction calculation for split ingredients (e.g., 0.5 each for "half/remaining" pattern)

This approach handles:
- Section headers grouping ingredients (e.g., "For the Sauce")
- "All ingredients" phrases that assign everything to a step
- Weak match filtering to avoid false positives

### 4.2 Ingredient Parsing

The ingredient parser (`cookimport/parsing/ingredients.py`) wraps the `ingredient-parser-nlp` library:

```python
"3 stalks celery, sliced" -> {
    "quantity_kind": "exact",
    "input_qty": 3.0,
    "raw_unit_text": "stalks",
    "raw_ingredient_text": "celery",
    "preparation": "sliced",
    "is_optional": False,
    "confidence": 0.92
}
```

Special handling for:
- Section headers (e.g., "MARINADE:", "For the Filling")
- Range quantities (e.g., "3-4 cups" -> midpoint rounded up)
- Approximate quantities ("to taste", "as needed")

### 4.3 Variant Extraction

Recipes may contain variant instructions. The system (`cookimport/staging/draft_v1.py`) extracts these:

- Detects "Variation:" or "Variant:" headers
- Separates variant content from main instructions
- Stores variants as a separate array in the recipe output

### 4.4 Tip Classification

Tips are classified by scope (`cookimport/parsing/tips.py`):
- **general**: Standalone kitchen wisdom (reusable across recipes)
- **recipe_specific**: Notes tied to a particular recipe
- **not_tip**: Content that looks like a tip but isn't (copyright notices, ads)

## 5. Data Flow & Processing Stages

### Stage 1: Ingestion (`cookimport stage` command)
1. **Detection**: Plugins score confidence for handling the file
2. **Inspection**: Analyze internal structure (layout, headers, sections)
3. **Extraction**: Convert to `RecipeCandidate` objects with provenance
4. **Raw Artifacts**: Store extracted blocks as JSON for auditing

### Stage 2: Transformation
1. **Ingredient Parsing**: Lines parsed into structured components
2. **Instruction Parsing**: Extract time/temperature metadata
3. **Step Linking**: Assign ingredients to steps
4. **Tip Extraction**: Identify standalone tips and topics

### Stage 3: Output
- **Intermediate Drafts**: JSON-LD format in `{timestamp}/intermediate drafts/`
- **Final Drafts**: RecipeDraftV1 format in `{timestamp}/final drafts/`
- **Tips**: Extracted tips in `{timestamp}/tips/`
- **Reports**: Conversion summary with stats and warnings

## 6. Label Studio Integration

The project includes deep integration with Label Studio for building ground-truth datasets:

### Chunking Strategies
- **Structural Chunks**: Recipe-level units for validating segmentation
- **Atomic Chunks**: Line-level units for validating ingredient parsing

### Workflow
1. `cookimport labelstudio-import`: Upload chunks to Label Studio project
2. Annotate in Label Studio UI
3. `cookimport labelstudio-export`: Export labeled data as JSONL golden set

## 7. Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Excel Ingestion | **Active** | Wide, Tall, and Template layouts |
| App Archives | **Active** | Paprika and RecipeSage support |
| EPUB/PDF/Text | **Active** | Heuristic segmentation with variant extraction |
| OCR (docTR) | **Active** | For scanned PDFs, uses CRNN + ResNet |
| Ingredient Parsing | **Active** | NLP-based with confidence scores |
| Step-Ingredient Linking | **Active** | Two-phase algorithm with split detection |
| Tip Extraction | **Active** | Taxonomy tagging and scope classification |
| Label Studio | **Active** | Benchmarking and dataset export |
| LLM Repair | **Mocked** | Structure exists, calls return mock data |

## 8. Directory Map

```
cookimport/
├── core/           # Engine: Models, Reporting, Registry, Scoring
├── plugins/        # Adapters: Source-specific extraction (Excel, EPUB, etc.)
├── parsing/        # Brains: Ingredient parsing, Tip taxonomy, Step linking
│   ├── ingredients.py      # Ingredient line parsing
│   ├── step_ingredients.py # Two-phase step linking
│   ├── signals.py          # Block feature enrichment
│   ├── tips.py             # Tip extraction and classification
│   └── atoms.py            # Atomic text unit handling
├── staging/        # Output: Writers, JSON-LD, Draft V1
├── labelstudio/    # Benchmarking: Chunking, client, export
├── llm/            # (Mocked) LLM integration layer
└── ocr/            # docTR OCR engine for scanned documents

data/
├── input/          # Place source files here
└── output/         # Generated outputs appear here

tests/              # Comprehensive test suite
```

## 9. CLI Commands

| Command | Purpose |
|---------|---------|
| `cookimport` | Interactive mode with guided prompts |
| `cookimport stage <path>` | Stage recipes from file/folder |
| `cookimport inspect <path>` | Preview file structure and layout |
| `cookimport labelstudio-import` | Upload to Label Studio |
| `cookimport labelstudio-export` | Export labeled data |

Environment variables:
- `C3IMP_LIMIT`: Limit recipes per file (for testing)
- `LABEL_STUDIO_URL`: Label Studio server URL
- `LABEL_STUDIO_API_KEY`: Label Studio API key
```

## docs/IMPORTANT CONVENTIONS.md

```markdown
---
summary: "Project-wide coding and organization conventions for the import tooling."
read_when:
  - Before starting any new implementation
  - When organizing output folders or defining new models
---

# Important Conventions

- The import tooling lives in the Python package `cookimport/`, with the CLI entrypoint exposed as the `cookimport` script via `pyproject.toml`.
- Core shared models are defined in `cookimport/core/models.py`, and staging JSON-LD helpers live in `cookimport/staging/`.
- Staging output folders use workbook stems (no file extension) for `intermediate drafts/<workbook>/...`, `final drafts/<workbook>/...`, and report names, while provenance still records the full filename.
- Outputs are flattened per source file (no sheet subfolders) and named `r{index}.json[ld]` in the order recipes are emitted. Tip snippets are written separately as `tips/{workbook}/t{index}.json` and include `sourceRecipeTitle`, `sourceText`, `scope` (`general`/`recipe_specific`/`not_tip`), `standalone`, `generalityScore`, and tag categories (including `dishes` and `cookingMethods`) when tied to a recipe. Each tips folder also includes `tips.md`, a markdown list of the tip `text` fields grouped by source block, annotated with `t{index}` ids plus anchor tags, and prefixed by any detected topic header line for quick review. Topic candidates captured before tip classification are written as `tips/{workbook}/topic_candidates.json` and `tips/{workbook}/topic_candidates.md`; these are atom-level snippets with container headers and adjacent-atom context recorded under `provenance.atom` and `provenance.location`.
- Stable IDs still derive from provenance (`row_index`/`rowIndex` for Excel, `location.chunk_index` for non-tabular importers).
- Draft V1 ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`) are lowercased on output.
- `ConversionResult.tipCandidates` stores all classified tip candidates (`general`, `recipe_specific`, `not_tip`), while `ConversionResult.tips` contains only standalone general tips for output.
- Recipe-derived tips default to `recipe_specific`; exported tips primarily come from non-recipe text unless a tip reads strongly general.
- Conversion reports include `runTimestamp` (local ISO-8601 time) for when the stage run started.
- Conversion reports include `outputStats` with per-output file counts/bytes (and largest files) to help debug slow writes.
- Raw artifacts are preserved under `staging/raw/<importer>/<source_hash>/<location_id>.<ext>` for auditing (JSON snippets for structured sources, text/blocks for unstructured sources).
- PDF page-range jobs and EPUB spine-range jobs (when a large source is split across workers) write raw artifacts to `staging/.job_parts/<workbook_slug>/job_<index>/raw/...` and the main process merges them back into `staging/raw/` after the merge completes. Temporary `.job_parts` folders may remain only if a merge fails.
- Cookbook-specific parsing overrides live in the `parsingOverrides` section of mapping files or in `*.overrides.yaml` sidecars passed via `cookimport stage --overrides`.
- Label Studio benchmark artifacts are written under `data/output/<timestamp>/labelstudio/<book_slug>/`, including `extracted_archive.json`, `label_studio_tasks.jsonl`, and `exports/golden_set_tip_eval.jsonl` after label export.
```

## docs/PLANS.md

```markdown
---
summary: "ExecPlan requirements, format, and workflow rules."
read_when:
  - When authoring or updating ExecPlans
---

# Codex Execution Plans (ExecPlans):
 
This document describes the requirements for an execution plan ("ExecPlan"), a design document that a coding agent can follow to deliver a working feature or system change. Treat the reader as a complete beginner to this repository: they have only the current working tree and the single ExecPlan file you provide. There is no memory of prior plans and no external context.
 
## How to use ExecPlans and PLANS.md
 
When authoring an executable specification (ExecPlan), follow PLANS.md _to the letter_. If it is not in your context, refresh your memory by reading the entire PLANS.md file. Be thorough in reading (and re-reading) source material to produce an accurate specification. When creating a spec, start from the skeleton and flesh it out as you do your research.
 
When implementing an executable specification (ExecPlan), do not prompt the user for "next steps"; simply proceed to the next milestone. Keep all sections up to date, add or split entries in the list at every stopping point to affirmatively state the progress made and next steps. Resolve ambiguities autonomously, and commit frequently.
 
When discussing an executable specification (ExecPlan), record decisions in a log in the spec for posterity; it should be unambiguously clear why any change to the specification was made. ExecPlans are living documents, and it should always be possible to restart from _only_ the ExecPlan and no other work.
 
When researching a design with challenging requirements or significant unknowns, use milestones to implement proof of concepts, "toy implementations", etc., that allow validating whether the user's proposal is feasible. Read the source code of libraries by finding or acquiring them, research deeply, and include prototypes to guide a fuller implementation.
 
## Requirements
 
NON-NEGOTIABLE REQUIREMENTS:
 
* Every ExecPlan must be fully self-contained. Self-contained means that in its current form it contains all knowledge and instructions needed for a novice to succeed.
* Every ExecPlan is a living document. Contributors are required to revise it as progress is made, as discoveries occur, and as design decisions are finalized. Each revision must remain fully self-contained.
* Every ExecPlan must enable a complete novice to implement the feature end-to-end without prior knowledge of this repo.
* Every ExecPlan must produce a demonstrably working behavior, not merely code changes to "meet a definition".
* Every ExecPlan must define every term of art in plain language or do not use it.
 
Purpose and intent come first. Begin by explaining, in a few sentences, why the work matters from a user's perspective: what someone can do after this change that they could not do before, and how to see it working. Then guide the reader through the exact steps to achieve that outcome, including what to edit, what to run, and what they should observe.
 
The agent executing your plan can list files, read files, search, run the project, and run tests. It does not know any prior context and cannot infer what you meant from earlier milestones. Repeat any assumption you rely on. Do not point to external blogs or docs; if knowledge is required, embed it in the plan itself in your own words. If an ExecPlan builds upon a prior ExecPlan and that file is checked in, incorporate it by reference. If it is not, you must include all relevant context from that plan.
 
## Formatting
 
Format and envelope are simple and strict. Each ExecPlan must be one single fenced code block labeled as `md` that begins and ends with triple backticks. Do not nest additional triple-backtick code fences inside; when you need to show commands, transcripts, diffs, or code, present them as indented blocks within that single fence. Use indentation for clarity rather than code fences inside an ExecPlan to avoid prematurely closing the ExecPlan's code fence. Use two newlines after every heading, use # and ## and so on, and correct syntax for ordered and unordered lists.
 
When writing an ExecPlan to a Markdown (.md) file where the content of the file *is only* the single ExecPlan, you should omit the triple backticks.
 
Write in plain prose. Prefer sentences over lists. Avoid checklists, tables, and long enumerations unless brevity would obscure meaning. Checklists are permitted only in the `Progress` section, where they are mandatory. Narrative sections must remain prose-first.
 
## Guidelines
 
Self-containment and plain language are paramount. If you introduce a phrase that is not ordinary English ("daemon", "middleware", "RPC gateway", "filter graph"), define it immediately and remind the reader how it manifests in this repository (for example, by naming the files or commands where it appears). Do not say "as defined previously" or "according to the architecture doc." Include the needed explanation here, even if you repeat yourself.
 
Avoid common failure modes. Do not rely on undefined jargon. Do not describe "the letter of a feature" so narrowly that the resulting code compiles but does nothing meaningful. Do not outsource key decisions to the reader. When ambiguity exists, resolve it in the plan itself and explain why you chose that path. Err on the side of over-explaining user-visible effects and under-specifying incidental implementation details.
 
Anchor the plan with observable outcomes. State what the user can do after implementation, the commands to run, and the outputs they should see. Acceptance should be phrased as behavior a human can verify ("after starting the server, navigating to [http://localhost:8080/health](http://localhost:8080/health) returns HTTP 200 with body OK") rather than internal attributes ("added a HealthCheck struct"). If a change is internal, explain how its impact can still be demonstrated (for example, by running tests that fail before and pass after, and by showing a scenario that uses the new behavior).
 
Specify repository context explicitly. Name files with full repository-relative paths, name functions and modules precisely, and describe where new files should be created. If touching multiple areas, include a short orientation paragraph that explains how those parts fit together so a novice can navigate confidently. When running commands, show the working directory and exact command line. When outcomes depend on environment, state the assumptions and provide alternatives when reasonable.
 
Be idempotent and safe. Write the steps so they can be run multiple times without causing damage or drift. If a step can fail halfway, include how to retry or adapt. If a migration or destructive operation is necessary, spell out backups or safe fallbacks. Prefer additive, testable changes that can be validated as you go.
 
Validation is not optional. Include instructions to run tests, to start the system if applicable, and to observe it doing something useful. Describe comprehensive testing for any new features or capabilities. Include expected outputs and error messages so a novice can tell success from failure. Where possible, show how to prove that the change is effective beyond compilation (for example, through a small end-to-end scenario, a CLI invocation, or an HTTP request/response transcript). State the exact test commands appropriate to the project’s toolchain and how to interpret their results.
 
Capture evidence. When your steps produce terminal output, short diffs, or logs, include them inside the single fenced block as indented examples. Keep them concise and focused on what proves success. If you need to include a patch, prefer file-scoped diffs or small excerpts that a reader can recreate by following your instructions rather than pasting large blobs.
 
## Milestones
 
Milestones are narrative, not bureaucracy. If you break the work into milestones, introduce each with a brief paragraph that describes the scope, what will exist at the end of the milestone that did not exist before, the commands to run, and the acceptance you expect to observe. Keep it readable as a story: goal, work, result, proof. Progress and milestones are distinct: milestones tell the story, progress tracks granular work. Both must exist. Never abbreviate a milestone merely for the sake of brevity, do not leave out details that could be crucial to a future implementation.
 
Each milestone must be independently verifiable and incrementally implement the overall goal of the execution plan.
 
## Living plans and design decisions
 
* ExecPlans are living documents. As you make key design decisions, update the plan to record both the decision and the thinking behind it. Record all decisions in the `Decision Log` section.
* ExecPlans must contain and maintain a `Progress` section, a `Surprises & Discoveries` section, a `Decision Log`, and an `Outcomes & Retrospective` section. These are not optional.
* When you discover optimizer behavior, performance tradeoffs, unexpected bugs, or inverse/unapply semantics that shaped your approach, capture those observations in the `Surprises & Discoveries` section with short evidence snippets (test output is ideal).
* If you change course mid-implementation, document why in the `Decision Log` and reflect the implications in `Progress`. Plans are guides for the next contributor as much as checklists for you.
* At completion of a major task or the full plan, write an `Outcomes & Retrospective` entry summarizing what was achieved, what remains, and lessons learned.
 
# Prototyping milestones and parallel implementations
 
It is acceptable—-and often encouraged—-to include explicit prototyping milestones when they de-risk a larger change. Examples: adding a low-level operator to a dependency to validate feasibility, or exploring two composition orders while measuring optimizer effects. Keep prototypes additive and testable. Clearly label the scope as “prototyping”; describe how to run and observe results; and state the criteria for promoting or discarding the prototype.
 
Prefer additive code changes followed by subtractions that keep tests passing. Parallel implementations (e.g., keeping an adapter alongside an older path during migration) are fine when they reduce risk or enable tests to continue passing during a large migration. Describe how to validate both paths and how to retire one safely with tests. When working with multiple new libraries or feature areas, consider creating spikes that evaluate the feasibility of these features _independently_ of one another, proving that the external library performs as expected and implements the features we need in isolation.
 
## Skeleton of a Good ExecPlan
 
    # <Short, action-oriented description>
 
    This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
 
    If PLANS.md file is checked into the repo, reference the path to that file here from the repository root and note that this document must be maintained in accordance with PLANS.md.
 
    ## Purpose / Big Picture
 
    Explain in a few sentences what someone gains after this change and how they can see it working. State the user-visible behavior you will enable.
 
    ## Progress
 
    Use a list with checkboxes to summarize granular steps. Every stopping point must be documented here, even if it requires splitting a partially completed task into two (“done” vs. “remaining”). This section must always reflect the actual current state of the work.
 
    - [x] (2025-10-01 13:00Z) Example completed step.
    - [ ] Example incomplete step.
    - [ ] Example partially completed step (completed: X; remaining: Y).
 
    Use timestamps to measure rates of progress.
 
    ## Surprises & Discoveries
 
    Document unexpected behaviors, bugs, optimizations, or insights discovered during implementation. Provide concise evidence.
 
    - Observation: …
      Evidence: …
 
    ## Decision Log
 
    Record every decision made while working on the plan in the format:
 
    - Decision: …
      Rationale: …
      Date/Author: …
 
    ## Outcomes & Retrospective
 
    Summarize outcomes, gaps, and lessons learned at major milestones or at completion. Compare the result against the original purpose.
 
    ## Context and Orientation
 
    Describe the current state relevant to this task as if the reader knows nothing. Name the key files and modules by full path. Define any non-obvious term you will use. Do not refer to prior plans.
 
    ## Plan of Work
 
    Describe, in prose, the sequence of edits and additions. For each edit, name the file and location (function, module) and what to insert or change. Keep it concrete and minimal.
 
    ## Concrete Steps
 
    State the exact commands to run and where to run them (working directory). When a command generates output, show a short expected transcript so the reader can compare. This section must be updated as work proceeds.
 
    ## Validation and Acceptance
 
    Describe how to start or exercise the system and what to observe. Phrase acceptance as behavior, with specific inputs and outputs. If tests are involved, say "run <project’s test command> and expect <N> passed; the new test <name> fails before the change and passes after>".
 
    ## Idempotence and Recovery
 
    If steps can be repeated safely, say so. If a step is risky, provide a safe retry or rollback path. Keep the environment clean after completion.
 
    ## Artifacts and Notes
 
    Include the most important transcripts, diffs, or snippets as indented examples. Keep them concise and focused on what proves success.
 
    ## Interfaces and Dependencies
 
    Be prescriptive. Name the libraries, modules, and services to use and why. Specify the types, traits/interfaces, and function signatures that must exist at the end of the milestone. Prefer stable names and paths such as `crate::module::function` or `package.submodule.Interface`. E.g.:
 
    In crates/foo/planner.rs, define:
 
        pub trait Planner {
            fn plan(&self, observed: &Observed) -> Vec<Action>;
        }
 
If you follow the guidance above, a single, stateless agent -- or a human novice -- can read your ExecPlan from top to bottom and produce a working, observable result. That is the bar: SELF-CONTAINED, SELF-SUFFICIENT, NOVICE-GUIDING, OUTCOME-FOCUSED.
 
When you revise a plan, you must ensure your changes are comprehensively reflected across all sections, including the living document sections, and you must write a note at the bottom of the plan describing the change and the reason why. ExecPlans must describe not just the what but the why for almost everything.
```

## docs/SPEED_UP.md

```markdown
# Accelerate cookimport by scaling CPU concurrency and explicitly optimizing OCR compute

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root.

## Purpose / Big Picture

After this change, a user can run `cookimport stage` on a folder of many files and have `cookimport` automatically use more of the machine: multiple CPU cores will process multiple input files at once, and OCR will explicitly select and use the best available compute device (GPU when present, otherwise CPU). The observable result is that bulk imports complete significantly faster while producing the same staged outputs (intermediate drafts, final drafts, tips, and reports) as before.

A user should be able to verify it is working by running `cookimport stage <folder> --workers 4 --ocr-device auto --ocr-batch-size 8 --warm-models`, observing that multiple files advance concurrently, and seeing log output that states which OCR device is being used (e.g., `cuda`, `mps`, or `cpu`). They should also be able to rerun the same command with `--workers 1 --ocr-device cpu` and observe that the produced recipe drafts are equivalent, but runtime is slower.

## Progress

- [x] (2026-02-01 19:10Z) Establish a baseline: measure wall-clock time for staging a representative folder and capture current logs and outputs for later comparison.
- [x] (2026-02-01 19:15Z) Add a small, always-on timing scaffold to the staging pipeline that reports per-file and per-stage durations in the existing conversion report.
- [x] (2026-02-01 19:30Z) Implement explicit OCR device selection (`auto|cpu|cuda|mps`) and make the selection visible in logs and reports.
- [x] (2026-02-01 19:40Z) Implement OCR batching (process N pages per model call) behind a configurable `--ocr-batch-size` flag and prove outputs are stable.
- [x] (2026-02-01 19:50Z) Implement model warming and per-process caching for OCR and other heavy NLP models to avoid first-file cold start costs.
- [x] (2026-02-01 20:05Z) Implement parallel file processing in `cookimport stage` with a configurable worker count, with safe output writing and an aggregated end-of-run summary.
- [x] (2026-02-01 20:15Z) Add automated tests for device selection logic, batching boundaries, and parallel staging invariants.
- [x] (2026-02-01 20:30Z) Update user-facing docs/help text and add a “performance tuning” note that explains how to pick `--workers` based on RAM and OCR device availability.

## Surprises & Discoveries

- Observation: `multiprocessing` on Linux uses `fork` by default, which triggered `DeprecationWarning` from `torch` because the process was already multi-threaded. For a CLI, this is typically manageable, but `spawn` might be safer for complex environments.
- Observation: `MappingConfig` was being loaded and passed to workers. By adding `ocr_device` and `ocr_batch_size` to `MappingConfig`, we ensured that global CLI overrides are consistently available to all plugins without changing every signature.

## Decision Log

- Decision: Used a separate `cookimport/cli_worker.py` for the parallel worker function.
  Rationale: Avoids circular imports and ensures the function is top-level and picklable for `ProcessPoolExecutor`.
  Date/Author: 2026-02-01 / Gemini

## Outcomes & Retrospective

- (2026-02-01) Parallelism successfully implemented. Baseline tests show timing data is correctly captured in JSON reports.

## Artifacts and Notes

    Sequential (workers=1, ocr=cpu, batch=1): ~8.3s for 3 tests (including setup)
    Parallel (workers=2): Successfully interleaved file processing in tests.
    OCR device: auto-resolves to cpu/cuda/mps correctly.
    Timing data: Now included in every `.report.json` under the "timing" key.

## Context and Orientation

`cookimport` is a Python 3.12 recipe ingestion and normalization pipeline. It supports multiple source formats (Excel, EPUB, PDF, app archives, text/Word) via a registry-based plugin system under `cookimport/plugins/`, where each plugin detects whether it can handle a path and converts it into staged candidates. The primary “bulk import” workflow is `cookimport stage <path>`, which performs Phase 1 ingestion and then downstream transformations to produce intermediate JSON-LD drafts and final `RecipeDraftV1` outputs.

The performance report for this work states that CPU is underutilized because `cookimport` processes files sequentially in a single loop within `cookimport/cli.py`, and that GPU acceleration for OCR is “potentially utilized but unmanaged” because `docTR` relies on PyTorch but the code does not explicitly choose an OCR device. The report proposes four concrete strategies: parallel file processing via multiprocessing, explicit GPU acceleration, batch OCR processing, and model warming/caching. This ExecPlan turns those goals into concrete, testable code changes.

Key files and concepts you will need to locate and read in the repository:

- `cookimport/cli.py`: Defines the Typer CLI and the `stage` command. This is where the sequential loop will be replaced (or wrapped) with a parallel executor and new CLI flags.
- `cookimport/plugins/registry.py` and `cookimport/plugins/*.py`: The plugin registry and importers that stage recipes from different formats. Parallelism will occur at the granularity of “one input file per worker”.
- `cookimport/ocr/doctr_engine.py`: The OCR engine wrapper around `python-doctr` / PyTorch. Device selection, batching, and predictor caching will be implemented here.
- `cookimport/parsing/*`: Ingredient parsing and other NLP routines. Some of these load heavy models (for example spaCy pipelines) and may benefit from per-process caching and optional warming.
- `cookimport/staging/*`: Writers that emit intermediate and final drafts and conversion reports. Parallelism must not cause output collisions or partial writes that leave confusing state behind.

Definitions used in this plan:

- “Worker”: a separate operating-system process used to run Python code in parallel on multiple CPU cores. This is required because Python threads do not parallelize CPU-bound work well due to the Global Interpreter Lock (GIL).
- “ProcessPoolExecutor”: the standard library mechanism (`concurrent.futures.ProcessPoolExecutor`) used to run callables in multiple processes.
- “OCR device”: the PyTorch execution device used for OCR model inference. `cpu` uses the CPU, `cuda` uses an NVIDIA GPU, and `mps` uses Apple Silicon GPU acceleration.
- “Batching”: passing multiple pages (images) to the OCR model in a single call, instead of one page at a time, to reduce overhead and improve throughput.

## Plan of Work

This work is intentionally staged to reduce risk. The order is: first make performance measurable, then make OCR compute deterministic and configurable, then add batching and warming, and only then add parallel file processing. Parallelism multiplies resource use and can amplify existing “hidden” problems; we de-risk it by first stabilizing OCR behavior and reporting.

### Milestone 1: Baseline and observability without output changes

By the end of this milestone you will be able to point to a “before” measurement and a repeatable way to capture “after” measurements, and you will have per-file and per-stage timing information emitted in a structured way.

Work:

- Read `cookimport/cli.py` and identify the full staging flow for a single file and for a folder. Determine where to measure, and whether a “file” is a concrete input path or a discovered set of files from recursion.
- Add a lightweight timing utility (for example a context manager that records monotonic time deltas) in a new module such as `cookimport/core/timing.py` (or a nearby appropriate package).
- Integrate timing into the staging flow so each input file produces a small, structured record including: total time, OCR time (if applicable), parsing time, and output writing time. Prefer writing this into the existing report object if there is one; otherwise write a new JSON file adjacent to the existing conversion report.
- Ensure default behavior remains identical in outputs. This milestone should only add additional report fields or new report artifacts.

Proof:

- Run `cookimport stage` on a small folder and confirm you get the same drafts as before plus the new timing info.

### Milestone 2: Explicit OCR device selection and visibility

By the end of this milestone, OCR will explicitly run on the chosen device, and the chosen device will be visible in logs and in the report.

Work:

- Read `cookimport/ocr/doctr_engine.py` to find how `ocr_predictor` is created and called today.
- Implement a device selection function that supports:
  - `auto`: choose `cuda` if `torch.cuda.is_available()`; otherwise choose `mps` if `torch.backends.mps.is_available()`; otherwise `cpu`.
  - `cpu`, `cuda`, `mps`: explicit selection; if the requested device is not available, fail fast with a clear error message that also prints what is available.
- Add a CLI flag on `cookimport stage` such as `--ocr-device` with those choices, defaulting to `auto`.
- Ensure the OCR predictor is created with the selected device. If the version of `doctr` in this repo accepts a `device` argument, pass it directly. If it does not, move tensors/models appropriately within the engine wrapper and document exactly how you verified it (for example by inspecting the predictor signature in a Python REPL).
- Add logging that prints the chosen device once per run and once per worker (later, when parallelism exists).

Proof:

- Run `cookimport stage` on a scanned PDF input and confirm logs indicate `OCR device: <device>`. Run again with `--ocr-device cpu` and confirm it uses CPU.

### Milestone 3: Batch OCR processing with stable outputs

By the end of this milestone, OCR will process multiple pages per inference call, controlled by `--ocr-batch-size`, and outputs will remain stable.

Work:

- Identify where PDF pages are converted to images (PIL images or arrays) before passing to OCR.
- Modify `doctr_engine.py` so it can accept a list of page images and submit them to the OCR predictor in chunks of size N, where N is `--ocr-batch-size` (default 1 to preserve current behavior until proven).
- Ensure the “page order” is preserved and that downstream text extraction and block reconstruction still aligns with the original page numbers.
- Add guardrails for memory. If a PDF has many pages, do not load all pages into memory at once if current code streams; keep streaming behavior by batching at the point where images exist.

Proof:

- Run `cookimport stage` on a PDF with multiple pages and compare outputs for `--ocr-batch-size 1` vs `--ocr-batch-size 8`. Accept small differences only if they are explained and justified (for example if OCR produces slightly different whitespace); otherwise treat differences as regressions and fix.

### Milestone 4: Model warming and per-process caching

By the end of this milestone, “cold start” delays are reduced. OCR and other heavy models are cached per process and can be proactively warmed at startup with `--warm-models`.

Work:

- In `cookimport/ocr/doctr_engine.py`, implement predictor caching so the predictor is created once per process and reused for subsequent calls. In plain Python this can be done with a module-level singleton or an `functools.lru_cache` keyed by `(device, model_config)`.
- Find other heavy model loads in parsing modules (for example spaCy pipelines used by ingredient parsing). Wrap these loaders similarly so they are created once per process.
- Add a CLI flag `--warm-models` to `cookimport stage` that triggers loading those cached models early, before processing the first file. In a future parallel step, this warming will occur in each worker process at worker startup.
- Ensure warming is optional. Default should keep startup fast for small runs.

Proof:

- Run `cookimport stage` twice on a small sample. On the second run (in the same process), confirm the first-file delay is reduced. For a single run with `--warm-models`, confirm that the warm step happens before file processing and is reported.

### Milestone 5: Parallel file processing in `cookimport stage`

By the end of this milestone, staging a folder can use multiple CPU cores by processing multiple input files concurrently, with safe output semantics and an end-of-run summary.

Work:

- In `cookimport/cli.py`, identify the code path that iterates through multiple files. Replace the sequential loop with a `ProcessPoolExecutor` driven by a “one input file per task” function.
- Define a top-level worker function (must be importable and picklable) such as `cookimport.cli_worker.stage_one_path(path: str, config: StageConfig) -> StageSummary`. This function should:
  - Perform the same staging steps for a single file as the current sequential loop.
  - Write outputs for that file to disk.
  - Return only a small summary (counts, timings, any warnings, path to report), not the full staged objects, to avoid pickling large data.
- Introduce a `StageConfig` data structure that is serializable (simple fields only) and includes: output root directory, OCR device and batch size, warm_models, and any existing CLI options required to make staging deterministic.
- Add CLI flags:
  - `--workers <int|auto>` with default `1` (preserving current behavior).
  - Optionally `--workers auto` computes a safe default using a heuristic derived from the report’s guidance: `min(cpu_count, floor(total_ram_gb / 3))`, but never less than 1. If reliable total RAM cannot be computed without adding dependencies, treat `auto` as “cpu_count” with a prominent warning explaining that RAM may be the limiting factor.
- Ensure safe output writing:
  - If the current staging writes everything into a shared timestamped directory, keep a single run-level output directory, but ensure each input file writes into its own subdirectory (for example by a stable slug of the input filename plus a short hash).
  - Ensure that any shared “summary report” is written only by the parent process after collecting worker summaries, to avoid concurrent writes to the same file.
  - Ensure that partial worker failures do not corrupt other outputs. A failing file should produce a clear error record and the overall run should exit non-zero only if requested (decide and record this policy in the Decision Log).
- Worker initialization and warming:
  - If `ProcessPoolExecutor` supports an `initializer`, use it to call the warm routine when `--warm-models` is enabled. Otherwise, make the worker call a warm-on-first-use function at the start of `stage_one_path`.

Proof:

- Run `cookimport stage data/input --workers 4` and observe that multiple files are being processed concurrently (for example by interleaved per-file log lines, and by system CPU usage). At the end, print a summary like “processed N files, M succeeded, K failed, total time X; average per-file time Y; OCR device Z”.

### Milestone 6: Tests, validation harness, and documentation

By the end of this milestone, changes are protected by tests, and users have clear guidance for tuning.

Work:

- Add unit tests for device selection:
  - Monkeypatch torch availability to simulate CUDA present, MPS present, and neither present.
  - Validate `auto` selection and validate that requesting an unavailable device errors with a clear message.
- Add unit tests for batching behavior:
  - Use small synthetic “page images” or a tiny fixture PDF (if fixtures already exist) and assert that batching yields the same extracted text ordering.
- Add integration tests for parallel staging invariants:
  - Run a small staging set with `--workers 1` and `--workers 2` and confirm that produced outputs (or key report summaries) are equivalent and that no output collisions occur.
- Update CLI help strings and add a short doc file such as `docs/performance.md` (or update an existing docs location) that explains:
  - When to use multiple workers.
  - How to pick a worker count based on available RAM.
  - How OCR device selection works and what `auto` does.
  - How to tune batch size and why larger is not always better (memory tradeoff).

Proof:

- `pytest` passes. A small “benchmark” run demonstrates improvement on a representative dataset and documents the measured numbers in `Artifacts and Notes`.

## Concrete Steps

All commands below are run from the repository root.

1) Locate the current staging loop and OCR engine.

    - `rg -n "def stage\\b|@app\\.command\\(\\)\\s*\\n\\s*def stage" cookimport/cli.py`
    - `rg -n "ProcessPoolExecutor|concurrent\\.futures" -S cookimport`
    - `ls cookimport/ocr && rg -n "doctr|ocr_predictor|torch" cookimport/ocr/doctr_engine.py`

2) Establish a baseline measurement (choose a representative folder of mixed inputs).

    - `time python -m cookimport stage data/input/sample_bulk`

    Save:
    - The produced output directory path.
    - Any existing conversion report file(s).
    - Wall-clock time.

3) Implement Milestone 1 timing scaffold, then rerun baseline and confirm outputs are unchanged aside from the new timing fields/artifacts.

4) Implement Milestones 2–4 in order, rerunning a small scanned PDF case after each step.

5) Implement Milestone 5 parallelism, then test:

    - `time python -m cookimport stage data/input/sample_bulk --workers 1 --ocr-device cpu --ocr-batch-size 1`
    - `time python -m cookimport stage data/input/sample_bulk --workers 4 --ocr-device auto --ocr-batch-size 8 --warm-models`

    Expected observable log lines (exact wording can differ, but the content must exist):

      - “Using workers: 4”
      - “OCR device: cuda” (or `mps` / `cpu`)
      - Per-file start/finish lines including durations
      - End-of-run summary with success/failure counts

6) Add tests and run them.

    - `pytest -q`

## Validation and Acceptance

This work is accepted when all of the following are true:

- Running `cookimport stage <folder> --workers 1` produces the same staged artifacts as before this change (modulo additional timing metadata or new report files that do not change recipe content).
- Running `cookimport stage <folder> --workers 4` completes successfully and demonstrates parallel processing by observable behavior: multiple files progress concurrently and overall wall-clock time is materially reduced on a multi-core machine.
- OCR device selection is explicit and visible:
  - `--ocr-device auto` selects `cuda` when available, otherwise `mps` when available, otherwise `cpu`.
  - Requesting an unavailable device fails fast with a clear error.
- OCR batching is configurable and defaults to the previous behavior (`--ocr-batch-size 1`).
- Model warming is optional and, when enabled, reduces cold-start overhead in a measurable way.
- Automated tests cover device selection logic and protect against basic output collisions in parallel staging.
- The documentation/help text explains the new flags and provides safe tuning guidance, including the RAM tradeoff described in the performance report.

## Idempotence and Recovery

- The changes must be safe to run repeatedly. If output directories are timestamped, multiple runs should naturally not collide. If runs share an output root, each input file must still write to a unique per-file subdirectory to avoid overwrites.
- If a worker crashes or a file fails to parse, the failure must be recorded in a per-file error report and must not corrupt successful outputs from other files.
- If parallelism introduces instability, users must be able to recover by rerunning with `--workers 1`, `--ocr-device cpu`, and `--ocr-batch-size 1`, which should match the pre-change behavior as closely as possible.

## Artifacts and Notes

During implementation, capture the following evidence snippets here:

- Baseline vs improved timing runs (short `time ...` outputs).
- A sample of the end-of-run summary output.
- A short excerpt of the new timing report schema (a few fields only), showing per-file durations and the selected OCR device.

Example (replace with real numbers during implementation):

    Baseline (workers=1, ocr=cpu, batch=1): real 3m12s
    Improved (workers=4, ocr=auto, batch=8, warm): real 1m04s
    OCR device: cuda
    Files: 24 total; 24 succeeded; 0 failed

## Interfaces and Dependencies

New or modified interfaces must be explicit and stable:

- `cookimport/cli.py` (or a new `cookimport/cli_worker.py`) must expose a top-level worker entry point that can be submitted to a `ProcessPoolExecutor`. It must accept only picklable arguments.
- `cookimport/ocr/doctr_engine.py` must expose a clear API that accepts:
  - `device`: one of `cpu|cuda|mps`
  - `batch_size`: positive integer
  - and internally caches the predictor per process for reuse.
- The CLI for `cookimport stage` must add:
  - `--workers`
  - `--ocr-device`
  - `--ocr-batch-size`
  - `--warm-models`
  Each must have a help string that explains what it does and what the default means.
- Avoid adding new third-party dependencies unless absolutely necessary. If you choose to add one (for example for RAM detection), record the decision and rationale in the Decision Log and include exact installation/update steps and why standard library options were insufficient.

```

## docs/architecture/README.md

```markdown
---
summary: "System architecture, pipeline design, and project conventions."
read_when:
  - Starting work on the project
  - Making architectural decisions
  - Understanding output folder structure or naming conventions
---

# Architecture & Conventions

## Pipeline Overview

The cookimport system uses a **two-phase pipeline**:

```
Source Files → [Ingestion] → RecipeCandidate (JSON-LD) → [Transformation] → RecipeDraftV1
                    ↓                                           ↓
              Raw Artifacts                              Step-linked recipes
              Tip Candidates                             Parsed ingredients
              Topic Candidates                           Time/temp metadata
```

### Phase 1: Ingestion
Each source format has a dedicated plugin that:
1. Detects if it can handle the file (confidence score)
2. Inspects internal structure (layouts, headers, sections)
3. Extracts content to `RecipeCandidate` objects (schema.org JSON-LD compatible)
4. Preserves raw artifacts for auditing

### Phase 2: Transformation
Converts intermediate format to final output:
1. Parses ingredient strings into structured components
2. Extracts time/temperature from instruction text
3. Links ingredients to the steps where they're used
4. Classifies and extracts standalone tips

---

## Output Folder Structure

Each run creates a timestamped folder:

```
data/output/{YYYY-MM-DD-HH-MM-SS}/
├── intermediate drafts/{workbook_slug}/   # RecipeSage JSON-LD per recipe
├── final drafts/{workbook_slug}/          # RecipeDraftV1 per recipe
├── tips/{workbook_slug}/                  # Tips and topic candidates
├── chunks/{workbook_slug}/                # Knowledge chunks (optional)
├── raw/{importer}/{source_hash}/          # Raw extracted artifacts
└── {workbook_slug}.excel_import_report.json  # Conversion report
```

---

## Naming Conventions

### File Naming
- Workbook slug: lowercase, alphanumeric + underscores (from source filename)
- Recipe files: `r{index}.json` (0-indexed)
- Tip files: `t{index}.json` (0-indexed)
- Topic files: `topic_{index}.json`

### ID Generation
Stable IDs use URN format: `urn:cookimport:{importer}:{file_hash}:{location_id}`

Example: `urn:cookimport:epub:abc123:c5` (chunk 5 from EPUB with hash abc123)

---

## PDF & EPUB Job Splitting

When `cookimport stage` runs with `--workers > 1`, large PDFs can be split into
page-range jobs (`--pdf-pages-per-job` controls the target pages per job). Each
job parses a slice in parallel, then the main process merges results into a
single workbook output with sequential recipe IDs. During a split run, raw
artifacts are written to a temporary `.job_parts/` folder under the run output
and merged into `raw/` after the merge completes.

Large EPUBs can also be split into spine-range jobs with
`--epub-spine-items-per-job`. Each job parses a subset of spine items, and the
merge step rewrites recipe IDs to a single global sequence.

### Field Normalization
- `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note` → **lowercase**
- Whitespace: normalized (single spaces, max 2 newlines)
- Unicode: NFKC normalized, mojibake repaired

---

## Provenance System

Every output includes provenance for full traceability:

```json
{
  "provenance": {
    "source_file": "cookbook.epub",
    "source_hash": "sha256:abc123...",
    "extraction_method": "heuristic_epub",
    "confidence_score": 0.85,
    "location": {
      "start_block": 42,
      "end_block": 67,
      "chunk_index": 5
    },
    "extracted_at": "2026-01-31T10:30:00Z"
  }
}
```

---

## Plugin Architecture

Importers register with the plugin registry (`cookimport/plugins/registry.py`):

```python
class MyImporter:
    name = "my_format"

    def detect(self, path: Path) -> float:
        """Return confidence 0.0-1.0 that we can handle this file."""

    def inspect(self, path: Path) -> WorkbookInspection:
        """Quick structure analysis without full extraction."""

    def convert(self, path: Path, mapping: MappingConfig | None,
                progress_callback=None) -> ConversionResult:
        """Full extraction to RecipeCandidate objects."""

registry.register(MyImporter())
```

The registry's `best_importer_for_path()` selects the highest-confidence plugin.

---

## Future: LLM & ML Integration

The system follows a **deterministic-first** philosophy:
- Heuristics handle ~90%+ of cases
- LLM escalation only for low-confidence outputs
- ML classification reserved for cases where heuristics systematically fail

Infrastructure exists in `cookimport/llm/` (currently mocked):
- Schema-constrained output (Pydantic models)
- Caching by (model, prompt_version, input_hash)
- Token budget awareness (~30-40M tokens for 300 cookbooks)

ML options documented for future use:
- Zero-shot NLI (BART-large-mnli) for tip classification
- Weak supervision (Snorkel) for labeling function combination
- Supervised DistilBERT for ingredient/instruction segmentation
```

## docs/docs-list.md

```markdown
---
summary: "Docs list script behavior and expected front matter."
read_when:
  - When updating docs list tooling or doc front matter
---

# Docs list script

The docs list script (`docs/docs-list.ts`) prints a summary of every markdown file under `docs/`, skipping hidden entries plus `archive/` and `research/`. Run it with `npm run docs:list` or `npx tsx docs/docs-list.ts`.

## Expected front matter

Each `docs/**/*.md` file must start with:

```md
---
summary: "One-line summary"
read_when:
  - When this doc should be read
---
```

`read_when` is optional and can be a bullet list or an inline array.

## What happens on missing metadata

If a file is missing front matter or a non-empty `summary`, the script still lists it but appends an error label:

- `missing front matter`
- `unterminated front matter`
- `summary key missing`
- `summary is empty`
```

## docs/docs-list.ts

```ts
#!/usr/bin/env tsx
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const docsListFile = fileURLToPath(import.meta.url);
const docsListDir = dirname(docsListFile);
const DOCS_DIR = join(docsListDir, '..', 'docs');

const EXCLUDED_DIRS = new Set(['archive', 'research']);

function compactStrings(values: unknown[]): string[] {
  const result: string[] = [];
  for (const value of values) {
    if (value === null || value === undefined) {
      continue;
    }
    const normalized = String(value).trim();
    if (normalized.length > 0) {
      result.push(normalized);
    }
  }
  return result;
}

function walkMarkdownFiles(dir: string, base: string = dir): string[] {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    if (entry.name.startsWith('.')) {
      continue;
    }
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_DIRS.has(entry.name)) {
        continue;
      }
      files.push(...walkMarkdownFiles(fullPath, base));
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      files.push(relative(base, fullPath));
    }
  }
  return files.sort((a, b) => a.localeCompare(b));
}

function extractMetadata(fullPath: string): {
  summary: string | null;
  readWhen: string[];
  error?: string;
} {
  const content = readFileSync(fullPath, 'utf8');
  if (!content.startsWith('---')) {
    return { summary: null, readWhen: [], error: 'missing front matter' };
  }
  const endIndex = content.indexOf('\n---', 3);
  if (endIndex === -1) {
    return { summary: null, readWhen: [], error: 'unterminated front matter' };
  }
  const frontMatter = content.slice(3, endIndex).trim();
  const lines = frontMatter.split('\n');
  let summaryLine: string | null = null;
  const readWhen: string[] = [];
  let collectingField: 'read_when' | null = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith('summary:')) {
      summaryLine = line;
      collectingField = null;
      continue;
    }
    if (line.startsWith('read_when:')) {
      collectingField = 'read_when';
      const inline = line.slice('read_when:'.length).trim();
      if (inline.startsWith('[') && inline.endsWith(']')) {
        try {
          const parsed = JSON.parse(inline.replace(/'/g, '"')) as unknown;
          if (Array.isArray(parsed)) {
            readWhen.push(...compactStrings(parsed));
          }
        } catch {
          // ignore malformed inline arrays
        }
      }
      continue;
    }
    if (collectingField === 'read_when') {
      if (line.startsWith('- ')) {
        const hint = line.slice(2).trim();
        if (hint) {
          readWhen.push(hint);
        }
      } else if (line === '') {
        continue;
      } else {
        collectingField = null;
      }
    }
  }

  if (!summaryLine) {
    return { summary: null, readWhen, error: 'summary key missing' };
  }
  const summaryValue = summaryLine.slice('summary:'.length).trim();
  const normalized = summaryValue
    .replace(/^['"]|['"]$/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!normalized) {
    return { summary: null, readWhen, error: 'summary is empty' };
  }

  return { summary: normalized, readWhen };
}

console.log('Listing all markdown files in docs folder:');
const markdownFiles = walkMarkdownFiles(DOCS_DIR);
for (const relativePath of markdownFiles) {
  if (relativePath.endsWith('AGENTS.md')) {
    console.log(`${relativePath} - reminder to always read this`);
    continue;
  }
  const fullPath = join(DOCS_DIR, relativePath);
  const { summary, readWhen, error } = extractMetadata(fullPath);
  if (summary) {
    console.log(`${relativePath} - ${summary}`);
    if (readWhen.length > 0) {
      console.log(`  Read when: ${readWhen.join('; ')}`);
    }
  } else {
    const reason = error ? ` - [${error}]` : '';
    console.log(`${relativePath}${reason}`);
  }
}

console.log(
  '\nReminder: keep docs up to date as behavior changes. IF ANY FILES THROW ERRORS, FIX THEM ' +
    'When your task matches any "Read when" hint above ' +
    '(React hooks, cache directives, database work, tests, etc.), ' +
    'read that doc before coding, and suggest new coverage when it is missing.'
);
```

## docs/ingestion/README.md

```markdown
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

**Job splitting:**
- Large EPUBs can be split into spine-range jobs when `cookimport stage` runs
  with `--workers > 1`; tune with `--epub-spine-items-per-job`.

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

**Job splitting:**
- Large PDFs can be split into page-range jobs when `cookimport stage` runs with multiple workers.
- Use `--pdf-pages-per-job` to control the target number of pages per job; results are merged back into a single workbook output.
- OCR and text extraction both honor page ranges, so each job only processes its assigned slice.

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
```

## docs/label-studio/README.md

```markdown
---
summary: "Label Studio integration for benchmarking and golden set creation."
read_when:
  - Setting up Label Studio for evaluation
  - Creating or exporting golden sets
  - Understanding chunking strategies
---

# Label Studio Integration

**Location:** `cookimport/labelstudio/`

Label Studio is used to create ground-truth datasets for validating extraction accuracy.

## Quick Start

### Prerequisites

```bash
# Start Label Studio (Docker)
docker run -it -p 8080:8080 heartexlabs/label-studio:latest

# Set environment variables
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=your_api_key_here
```

### Import Workflow

```bash
# Import a cookbook for labeling
cookimport labelstudio-import path/to/cookbook.epub \
  --project-name "ATK Cookbook Benchmark" \
  --chunk-level both
```

### Export Workflow

```bash
# Export labeled data as golden set
cookimport labelstudio-export \
  --project-name "ATK Cookbook Benchmark" \
  --output-dir data/golden/
```

---

## Chunking Strategies

### Structural Chunks

Recipe-level units for validating segmentation accuracy.

**Use case:** "Did we correctly identify recipe boundaries?"

Each chunk contains:
- Full recipe text (ingredients + instructions)
- Extracted recipe title
- Source location (block indices)

**Labels:** Correct boundary, Over-segmented, Under-segmented, Not a recipe

### Atomic Chunks

Line-level units for validating parsing accuracy.

**Use case:** "Did we correctly parse this ingredient line?"

Each chunk contains:
- Single ingredient or instruction line
- Parsed fields (quantity, unit, item, etc.)
- Confidence score

**Labels:** Correct, Incorrect quantity, Incorrect unit, Incorrect item, etc.

### Chunk Levels

| Level | Description |
|-------|-------------|
| `structural` | Recipe-level chunks only |
| `atomic` | Line-level chunks only |
| `both` | Both structural and atomic chunks |

---

## Labeling Interface

The Label Studio project uses a custom labeling config (`label_config.py`):

### For Structural Chunks
- Boundary correctness (correct/over/under-segmented)
- Recipe vs non-recipe classification
- Title extraction accuracy

### For Atomic Chunks
- Field-by-field correctness
- Quantity kind accuracy
- Section header detection

---

## Golden Set Export

Exported data format (JSONL):

```json
{
  "chunk_id": "urn:cookimport:epub:abc123:c5",
  "chunk_type": "structural",
  "source_file": "cookbook.epub",
  "labels": {
    "boundary": "correct",
    "is_recipe": true,
    "title_correct": true
  },
  "annotator": "user@example.com",
  "annotated_at": "2026-01-31T10:30:00Z"
}
```

---

## Pipeline Routing

The chunking module (`cookimport/labelstudio/chunking.py`) handles:

### Extraction Archive

Raw extracted content stored for reference:
- Block text and indices
- Source location
- Extraction method

### Chunk Generation

```python
# Structural chunks
chunks = chunk_structural(result, archive, source_file, book_id, pipeline, file_hash)

# Atomic chunks
chunks = chunk_atomic(result, archive, source_file, book_id, pipeline, file_hash)
```

### Coverage Tracking

Monitors extraction completeness:
- `extracted_chars`: Total characters from source
- `chunked_chars`: Characters included in chunks
- `warnings`: Coverage gaps or issues

---

## Artifacts

Each import run creates:

```
data/output/{timestamp}/labelstudio/{book_slug}/
├── manifest.json           # Run metadata, chunk IDs, coverage
├── extracted_archive.json  # Raw extracted blocks
├── extracted_text.txt      # Plain text for reference
├── label_studio_tasks.jsonl # Tasks uploaded to Label Studio
├── project.json            # Label Studio project info
└── coverage.json           # Extraction coverage stats
```

---

## Resume Mode

Import supports resuming to add new chunks without duplicating:

```bash
# First import
cookimport labelstudio-import cookbook.epub --project-name "My Project"

# Later: resume with additional chunks
cookimport labelstudio-import cookbook.epub --project-name "My Project"
# Automatically detects existing chunks and only uploads new ones
```

Use `--overwrite` to start fresh (deletes existing project).

---

## Client API

Direct API access for advanced use:

```python
from cookimport.labelstudio.client import LabelStudioClient

client = LabelStudioClient(url, api_key)

# Find or create project
project = client.find_project_by_title("My Project")
if not project:
    project = client.create_project("My Project", label_config_xml)

# Import tasks
client.import_tasks(project["id"], tasks)

# Export annotations
annotations = client.export_annotations(project["id"])
```
```

## docs/parsing/receipe_parsing.md

```markdown
---
summary: "Ingredient parsing, instruction metadata extraction, and text normalization."
read_when:
  - Working on ingredient line parsing
  - Extracting time/temperature from instructions
  - Understanding text preprocessing pipeline
---

# Parsing Pipeline

The parsing phase transforms raw text into structured data.

## Ingredient Parsing

**Location:** `cookimport/parsing/ingredients.py`

**Library:** [ingredient-parser-nlp](https://ingredient-parser.readthedocs.io/) - NLP-based decomposition

### Input/Output Example

```python
parse_ingredient_line("3 stalks celery, sliced")
# Returns:
{
    "quantity_kind": "exact",      # exact | approximate | unquantified | section_header
    "input_qty": 3.0,              # Numeric quantity (float)
    "raw_unit_text": "stalks",     # Unit as written
    "raw_ingredient_text": "celery",  # Ingredient name
    "preparation": "sliced",       # Prep instructions
    "note": None,                  # Additional notes
    "is_optional": False,          # Detected from "(optional)"
    "confidence": 0.92,            # Parser confidence
    "raw_text": "3 stalks celery, sliced"  # Original input
}
```

### Quantity Kinds

| Kind | Description | Example |
|------|-------------|---------|
| `exact` | Numeric quantity present | "2 cups flour" |
| `approximate` | Vague quantity | "salt to taste", "oil for frying" |
| `unquantified` | No quantity detected | "fresh parsley" |
| `section_header` | Ingredient group label | "FOR THE SAUCE:", "Marinade" |

### Section Header Detection

Headers are identified by:
- ALL CAPS single words: "FILLING", "MARINADE"
- "For the X" pattern: "For the Filling"
- Known keywords: garnish, topping, sauce, dressing, crust, glaze, etc.
- No amounts parsed from text

### Range Handling

Ranges like "3-4 cups" → midpoint rounded up (4.0)

### Approximate Phrases

Detected patterns:
- "to taste", "as needed", "as desired"
- "for serving", "for garnish", "for frying"
- "for greasing", "for the pan"

---

## Instruction Metadata Extraction

**Location:** `cookimport/parsing/instruction_parser.py`

Extracts time and temperature from instruction text.

### Time Extraction

```python
parse_instruction("Bake for 25-30 minutes until golden.")
# Returns:
{
    "total_time_seconds": 1650,  # Midpoint of range (27.5 min)
    "temperature": None,
    "temperature_unit": None
}
```

Supported patterns:
- "X minutes", "X hours", "X-Y minutes"
- "1 hour 30 minutes", "1.5 hours"
- Accumulates multiple times in one step

### Temperature Extraction

```python
parse_instruction("Preheat oven to 375°F.")
# Returns:
{
    "total_time_seconds": None,
    "temperature": 375.0,
    "temperature_unit": "F"
}
```

Supported patterns:
- "350°F", "180°C", "350 degrees F"
- Unit conversion available (F↔C)

### Cook Time Aggregation

Total recipe cook time = sum of all step times (when not explicitly provided in source).

---

## Text Normalization

**Location:** `cookimport/parsing/cleaning.py`

### Unicode Normalization
- NFKC normalization (compatibility decomposition + canonical composition)
- Non-breaking spaces → regular spaces

### Mojibake Repair
Common encoding corruption fixes:
- `â€™` → `'` (smart quote)
- `â€"` → `—` (em dash)
- `Ã©` → `é` (accented characters)

### Whitespace Standardization
- Collapse multiple spaces to single space
- Collapse 3+ newlines to 2 newlines
- Strip leading/trailing whitespace

### Hyphenation Repair
Rejoins words split across lines:
- "ingre-\ndients" → "ingredients"
- Handles soft hyphens (U+00AD)

---

## Signal Detection

**Location:** `cookimport/parsing/signals.py`

Enriches `Block` objects with feature flags for downstream processing.

### Available Signals

| Signal | Description |
|--------|-------------|
| `is_heading` | Detected as heading element |
| `heading_level` | 1-6 for h1-h6 |
| `is_ingredient_header` | "Ingredients:", "For the Sauce:" |
| `is_instruction_header` | "Instructions:", "Method:", "Directions:" |
| `is_yield` | "Serves 4", "Makes 12 cookies" |
| `is_time` | "Prep: 15 min", "Cook: 30 min" |
| `starts_with_quantity` | Line starts with number/fraction |
| `has_unit` | Contains unit term (cup, tbsp, oz) |
| `is_ingredient_likely` | High probability ingredient line |
| `is_instruction_likely` | High probability instruction step |

### Override Support

Cookbook-specific overrides via `ParsingOverrides`:
- Custom ingredient headers
- Custom instruction headers
- Additional imperative verbs
- Custom unit terms
```

## docs/parsing/semantic-matching-for-ingredients.md

```markdown
---
summary: "Semantic fallback matching for ingredient-to-step assignment."
read_when:
  - When improving ingredient normalization or semantic matching in step linking
---

# Semantic Matching for Ingredient-to-Step Assignment

## Current behavior (implemented)

- Exact alias matching runs first (raw + cleaned aliases).
- If an ingredient has **no exact matches**, a lightweight **lemmatized** fallback runs.
- "Exact match" here includes head/tail single-token aliases, so semantic/fuzzy only run when **no alias tokens** hit a step.
- Lemmatization is **rule-based** (suffix stripping + a small override map) and adds **no external deps**.
- A **curated synonym map** expands semantic aliases (e.g., scallion ↔ green onion).
- If an ingredient is still unmatched, a **RapidFuzz** fallback runs for near-miss typos.
- Candidates are tagged as `match_kind="semantic"` or `match_kind="fuzzy"` and only considered when exact matches are absent for that ingredient.

## Why it helps

This rescues common morphology gaps without heavy models, e.g.:

- "floured" → "flour"
- "onions" → "onion"
- "chopped" → "chop"
- "scallions" → "green onion"
- "squah" (typo) → "squash" (via fuzzy rescue)

## Where it lives

- `cookimport/parsing/step_ingredients.py`
  - `_lemmatize_token` / `_lemmatize_tokens`
  - `_expand_synonym_variants` / `_add_alias_variants`
  - `_tokenize(..., lemmatize=True)`
  - semantic fallback in `assign_ingredient_lines_to_steps`
  - fuzzy fallback in `assign_ingredient_lines_to_steps`

## Guardrails and tuning knobs

- `_SYNONYM_GROUPS`: curated synonym phrase groups (lemmatized tokens).
- `_FUZZY_MIN_SCORE`: minimum RapidFuzz score for fuzzy candidates (default 85).
- `_GENERIC_FUZZY_TOKENS`: excludes very generic single-word ingredients from fuzzy rescue.

## Future options (not implemented)

- Real lemmatizers (spaCy, NLTK, LemmInflect)
- Embedding fallback for *unassigned* ingredients only, ideally on constrained spans
```

## docs/parsing/tip-knowledge-chunking.md

```markdown
# Implement knowledge chunking with highlight-based tip mining

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repo root; this plan must be maintained in accordance with it. &#x20;

## Purpose / Big Picture

Today, `cookimport` extracts “tips” as small spans, which has good precision on tip-shaped sentences but is recall-limited and frequently clips the surrounding explanation, emits orphan aphorisms, and leaks front-matter blurbs into the output.  &#x20;

After this change, `cookimport stage …` will additionally produce “knowledge chunks”: longer, coherent, cookbook-structure-respecting sections of non-recipe text. Each knowledge chunk will:

- be labeled as `knowledge`, `narrative`, or `noise` (so blurbs/jacket copy do not pollute knowledge extraction),
- include provenance back to the original block stream,
- include “highlights” (the existing tip miner output) and a “tip density” score, but the chunk boundary is not decided by punctuation or one-sentence “tips”.
  This implements the recommended strategy: chunk first, mine highlights inside chunks, and distill from the whole chunk (optionally via the existing mocked LLM layer).  &#x20;

You will know it is working by staging a cookbook and finding new output artifacts (e.g. `chunks.md` and `c{index}.json`) where:

- front-matter blurbs like “This beautiful, approachable book…” are classified as `narrative`/`noise`, not `knowledge`,&#x20;
- clipped “tips” are no longer emitted as the unit of output; instead, they appear as highlights inside a larger coherent chunk that contains the missing explanation,&#x20;
- headings like “USING SALT” group the following material into a single section chunk rather than many disconnected tips. &#x20;

## Progress

- [x] (2026-01-31) Baseline: run `cookimport stage` on a representative cookbook and save current `tips.md` + tip JSON outputs for comparison.

- [x] (2026-01-31) Add chunk data model(s) and writer output folder + human-readable `chunks.md`.
  - Added `ChunkLane`, `ChunkBoundaryReason`, `ChunkHighlight`, `KnowledgeChunk` models to `core/models.py`
  - Added `write_chunk_outputs()` to `staging/writer.py`
  - Output: `chunks/<workbook>/c{index}.json` and `chunks.md`

- [x] (2026-01-31) Implement deterministic heading-driven chunker (section chunks) that operates on the existing block stream.
  - Created `cookimport/parsing/chunks.py` with `chunk_non_recipe_blocks()` function
  - Uses ALL CAPS, colon-terminated, and title-case heading detection
  - Maintains section path stack for nested headings
  - Handles stop headings (INDEX, ACKNOWLEDGMENTS, etc.)

- [x] (2026-01-31) Implement lane assignment (`knowledge`/`narrative`/`noise`) including a front-matter/blurb filter.
  - `assign_lanes()` scores chunks based on knowledge/narrative/noise signals
  - Knowledge: imperatives, modals, mechanisms, diagnostics, temps/times
  - Narrative: first-person, anecdotes, opinions
  - Noise: praise adjectives, book/marketing language, quote-only content

- [x] (2026-01-31) Integrate existing tip miner as "highlights" inside each knowledge chunk; compute tip density and aggregate tags.
  - `extract_highlights()` runs tip miner on knowledge chunks
  - Computes `tip_density` (highlights per 1000 chars)
  - Aggregates tags from all highlights

- [x] (2026-01-31) Add boundary refinements (hard/medium/soft), callout chunking (TIP/NOTE/Variation boxes), and max/min chunk sizing.
  - `ChunkingProfile` configures min/max chars, heading levels, stop headings
  - Callout prefixes (TIP:, NOTE:, etc.) create boundaries
  - Format mode changes (prose ↔ bullets) trigger soft boundaries
  - `merge_small_chunks()` combines undersized chunks

- [x] (2026-01-31) Add tests (unit + small fixture) proving the three failure modes are mitigated; ensure legacy tip extraction still works.
  - Created `tests/test_chunks.py` with 18 tests covering:
    - Heading detection and section paths
    - Lane assignment for knowledge/narrative/noise
    - Highlight extraction and tag aggregation
    - Chunk merging and boundary reasons
  - All 172 tests pass (including existing tests)

- [ ] (2026-01-31) (Optional) Add "distill chunk" path using the existing mocked LLM layer, with caching and a CLI flag to enable.

## Surprises & Discoveries

* Observation: Topic candidates from conversion don't preserve original block structure, so we convert them to blocks for chunking.
  Evidence: Created `chunks_from_topic_candidates()` bridge function to convert TopicCandidate → Block → KnowledgeChunk.

* Observation: Stop sections (INDEX, ACKNOWLEDGMENTS) need to skip ALL following blocks until next major heading, not just the heading itself.
  Evidence: Added `in_stop_section` flag to track and skip content within stop sections.

* Observation: The chunking integrates cleanly with existing architecture by running after conversion and populating `result.chunks`.
  Evidence: Salt Fat Acid Heat EPUB: 466 chunks (424 knowledge, 37 narrative, 5 noise), 224 highlights extracted.

## Decision Log

- Decision: Keep the existing tip miner, but demote it to highlights inside chunk outputs; do not remove legacy `tips.md` initially.
  Rationale: This preserves current functionality while enabling the new “coherent chunk → distill” pipeline; it matches the recommended hybrid approach.&#x20;
  Date/Author: 2026-01-31 / assistant
- Decision: Boundaries are structure-first (headings/sections), not punctuation-first.
  Rationale: Prevents clipped spans and orphan aphorisms; cookbook structure is a stronger signal than sentence shape. &#x20;
- Decision: Add explicit `narrative` and `noise` lanes and route blurbs/front matter away from knowledge extraction.
  Rationale: The current output includes jacket-copy-like praise blurbs; they should be excluded from knowledge distillation. &#x20;
- Decision: Prefer deterministic chunking; only add LLM refinement behind a flag and with caching.
  Rationale: Stable, debuggable output is required for tuning and regression testing; LLM can improve quality but must not be required for baseline correctness.&#x20;

## Outcomes & Retrospective

### First End-to-End Success (2026-01-31)

Tested on `saltfatacidheat.epub`:
- **466 total chunks** generated with proper boundaries
- **Lane classification working**: 424 knowledge, 37 narrative, 5 noise
- **224 highlights** extracted from knowledge chunks

#### Failure Mode #1: Praise blurbs routed to noise ✓
```
### c0 🔇 NOISE
**(untitled)**
"This beautiful, approachable book not only teaches you how to cook..."
—Alice Waters
```

#### Failure Mode #2: Headings group content coherently ✓
```
### c3 📚 KNOWLEDGE
**SALT**
Section: SALT > Using Salt
Blocks: [24..35] (12 blocks)
```
The SALT section now groups 12 blocks together rather than emitting disconnected tips.

#### Failure Mode #3: Aphorisms become highlights, not standalone ✓
Short tip-like content appears inside larger knowledge chunks as highlights with `selfContained` flag, not as the primary unit of output.

### Files Added/Modified
- `cookimport/core/models.py`: Added ChunkLane, ChunkBoundaryReason, ChunkHighlight, KnowledgeChunk models
- `cookimport/parsing/chunks.py`: New module with chunking pipeline
- `cookimport/staging/writer.py`: Added write_chunk_outputs()
- `cookimport/cli.py`: Integrated chunk generation into stage command
- `tests/test_chunks.py`: 18 unit tests for chunking functionality

## Context and Orientation

`cookimport` is a multi-format ingestion engine (PDF/EPUB/Excel/Text/etc.) that stages recipes into structured outputs and also extracts standalone “Kitchen Tips” and topics. &#x20;

For unstructured sources, the system uses a linear stream of `Block` objects (paragraphs/headings/list items) enriched with “signals” like `is_heading`, `heading_level`, `is_instruction_likely`, and `is_ingredient_likely`.&#x20;
Tip extraction currently:

- atomizes text into “atoms” (paragraph/list/header) and preserves neighbor context for repair,&#x20;
- extracts candidate spans via prefixes/anchors (e.g. “TIP:”, “Make sure…”) and repairs incomplete spans by merging neighbors,&#x20;
- judges candidates with a tipness score (imperatives, modals, benefit cues vs narrative cues and recipe overlap) and a generality score,&#x20;
- tags tips via a taxonomy mapping (tools/techniques/ingredients),&#x20;
- writes results to `data/output/<timestamp>/tips/<workbook_stem>/` including `t{index}.json` and `tips.md`.&#x20;

The newest sample output shows the main issues this plan targets: front-matter blurbs extracted as tips, headings emitted as tips, and short aphorisms without payload. &#x20;

## Plan of Work

Implement a new “Knowledge Chunking” subsystem that runs on the same non-recipe block stream currently sent to tip extraction. The subsystem will produce coherent chunks and then run the existing tip miner inside each knowledge chunk to produce highlights and scoring, rather than treating mined spans as the final output unit.&#x20;

This should be done in small, verifiable milestones:

1. get a minimal chunk artifact written end-to-end,
2. make chunk boundaries respect cookbook structure (headings and callouts),
3. reliably separate knowledge vs narrative/noise,
4. attach highlights and scoring,
5. prove the failure modes are fixed with tests and fixture output diffs,
6. optionally enable LLM distillation over chunks using the existing mocked `cookimport/llm/` layer.

Throughout, preserve provenance and debuggability: every chunk should explain why it started/ended and which source blocks it contains.&#x20;

## Concrete Steps

All commands below are run from the repository root.

0. Optional dependency wiring (no behavior change).

   - Add optional dependencies (extras, or a separate requirements file) for:
     - `pysbd`
     - `spacy`
     - `sentence-transformers`
     - `scikit-learn`
     - `bertopic`
     - `umap-learn`
     - `hdbscan`
   - Ensure all imports are guarded and the default staging pipeline runs without these packages installed.
   - Add explicit CLI/profile flags for each optional feature so behavior is easy to reason about (e.g. `--sentence-splitter=pysbd`, `--topic-similarity=embedding`, `--lane-classifier=...`).

1. Establish baseline behavior and locate the current tip pipeline.

   - Run staging on a known cookbook input:
     python -m cookimport.cli stage data/input/\<your\_file>
     (This is the documented entrypoint; if the repo also exposes a `cookimport stage …` console script, that is acceptable too.) &#x20;
   - Find the most recent output folder in `data/output/…` and open:
     - `tips/<workbook_stem>/tips.md`
     - a handful of `tips/<workbook_stem>/t*.json`
   - Save a copy of the baseline `tips.md` snippet that includes:
     - the praise blurb tip(s),
     - “USING SALT” section,
     - the “pepper inverse” aphorism line,
       so you can compare after chunking. &#x20;

2. Add chunk artifacts (models + writer) without changing chunking logic yet.

   - In `cookimport/core/models.py`, add Pydantic models that are parallel to `TipCandidate`/`TopicCandidate`:
     - `ChunkLane`: enum with values `knowledge`, `narrative`, `noise`.
     - `ChunkBoundaryReason`: string enum; start with a small set: `heading`, `recipe_boundary`, `callout_seed`, `format_mode_change`, `max_chars`, `noise_break`, `end_of_input`.
     - `ChunkHighlight`: stores a reference to a mined tip/highlight and its location within the chunk (at minimum: `text` and `source_block_ids`; optionally offsets if easily available).
     - `ChunkCandidate` (or `KnowledgeChunk`): fields:
       - `id` (stable within output: `c{index}`),
       - `lane`,
       - `title` (derived from heading path),
       - `section_path` (list of headings),
       - `text` (the concatenated chunk text),
       - `block_ids` (source block indices or provenance ids),
       - `aside_block_ids` (optional; blocks inside the chunk classified as narrative-aside even if the overall chunk lane is `knowledge`),
       - `excluded_block_ids_for_distillation` (optional; blocks to omit when building `distill_text`),
       - `distill_text` (optional; the text actually sent to any distiller, derived from chunk blocks minus excluded/aside blocks),
       - `boundary_start_reason` / `boundary_end_reason`,
       - `tags` (aggregate, reuse the existing tag schema where possible),
       - `tip_density` (float or simple counts),
       - `highlights` (list of `ChunkHighlight`),
       - `provenance` (reuse the repo’s existing provenance conventions; do not invent an incompatible format).
         This mirrors how `TipCandidate` is used today.&#x20;
   - In `cookimport/staging/writer.py`, add a new output folder sibling to `tips/`, e.g.:
     - `data/output/<timestamp>/chunks/<workbook_stem>/`
     - `c{index}.json`
     - `chunks.md` (human-readable summary like `tips.md`)
       Preserve the existing `tips/` outputs unchanged in this milestone.&#x20;
   - The initial `chunks.md` format should be optimized for debugging:
     - chunk id, lane, title/section path
     - start/end boundary reasons
     - tip density (even if 0 for now)
     - first \~300–800 chars of chunk text
     - list of included block ids
       Keep it deterministic so diffs are stable.

3. Implement the minimal deterministic chunker (heading-driven “section chunks”).

   - Create a new module `cookimport/parsing/chunks.py` with a single entry function, for example:
     def chunk\_non\_recipe\_blocks(blocks: list[Block], \*, profile: ChunkingProfile) -> list[ChunkCandidate]
     Keep it pure (no IO); writer stays in `staging/writer.py`.

   - Implement “section chunk” as the default winner:

     - treat a heading block as a hard boundary and a chunk seed,
     - include “heading + everything until the next peer/parent heading” in the same chunk, not many small chunks,
     - do not let punctuation create boundaries.

   - Add an explicit fallback for weak structure / no headings:

     - detect “heading sparsity” (e.g. no headings for N blocks or >X chars),
     - switch to a micro-chunk mode that splits by medium boundaries + topic continuity heuristics rather than headings,
     - record `boundary_*_reason` as `topic_pivot` or `max_chars` (never “sentence end”).
       Suggested deterministic topic-pivot heuristic (good enough to start):
     - Provide two backends (configurable):
       - `lexical`: TF-IDF / bag-of-words overlap between a rolling window of the last K blocks and the next block.
       - `embedding` (if `sentence-transformers` is installed): SBERT embeddings per block and cosine similarity between adjacent blocks.
     - Split when similarity drops below a threshold **and** at least one medium boundary cue is present (blank line, list-mode change, callout seed, definition-like `:` pattern).
     - Merge when similarity stays high and no hard boundary is crossed.
     - Cache per-block features (TF-IDF vectors or embeddings) keyed by block text hash + model/version so re-runs are cheap and deterministic.



- Use the existing `Block & Signals` architecture:
  - determine heading blocks via existing `is_heading` / `heading_level` signals, and maintain a `section_path` stack as you iterate.&#x20;
- Define a `ChunkingProfile` (similar in spirit to `TipParsingProfile`) that contains:
  - `min_chars`, `max_chars` (start with something like 800 and 6000, but make it configurable),
  - heading levels considered “major” vs “minor” (use repo-specific heading levels; validate with a fixture),
  - a small list of “stop headings” for noise-heavy parts (e.g. INDEX, ACKNOWLEDGMENTS) but only as a default suggestion; keep it overrideable.
  - `sentence_splitter`: `none|pysbd|spacy` (default: `none`), for within-block sentence segmentation.
  - `topic_similarity_backend`: `none|lexical|embedding` (default: `lexical` in heading-sparse fallback; `none` otherwise).
  - `embedding_model_name` + `embedding_cache_dir` (only used when `topic_similarity_backend=embedding`).
  - `similarity_thresholds` (merge/split thresholds) and `window_k` for heading-sparse mode.
  - `lane_classifier_path` (optional; if present and enabled, use it to override/augment heuristic lane scoring).
- Ensure every chunk carries explicit boundary reasons (start and end).

4. Add lane assignment and a front-matter/blurb filter.
   - Add lane scoring functions in `cookimport/parsing/signals.py` or a new `cookimport/parsing/lane.py`:

     - `knowledge_score`: imperatives/modals/diagnostic cues/temps-times-quantities/mechanisms (“because/so that/therefore”) (some already exist in tip scoring logic).&#x20;
     - `narrative_score`: first-person voice markers and anecdote cues (some are already “negative signals” in tip judging).&#x20;
     - `noise_score` / `blurb_score`: praise adjectives + “book” + “teaches you” + quote-only patterns, matching the observed blurbs.

   - Optional (high leverage): supervised lane classifier (requires `scikit-learn` and a trained model artifact).

     - Train a lightweight classifier (logistic regression / linear SVM) from Label Studio exports.
     - Features: existing heuristic signals + TF-IDF bag-of-words + optional embedding features.
     - Inference policy: classifier can *override* heuristics only when confidence is high; otherwise fall back to heuristics.

   - Optional (feature enrichment): if `spacy` is installed, add POS/dependency-derived features to lane scoring and self-containedness checks (imperatives, modals, causal clauses).

   - Apply lane assignment at the section/chunk level (not per sentence), so one stray anecdote line does not flip an entire technique section.

   - Make an explicit, consistent choice for “knowledge → anecdote → knowledge” inside one section:

     - default behavior: keep a single `knowledge` chunk if knowledge dominates, but mark the anecdote blocks as `aside_block_ids` and add them to `excluded_block_ids_for_distillation`.
     - distillation (if enabled) must use `distill_text` and ignore aside blocks.
     - if an aside grows beyond a configurable size (e.g. `narrative_aside_split_chars`), optionally split it into a sibling `narrative` chunk that inherits the same `section_path`.

- Explicitly route the sample praise-blurb content to `noise` (or `narrative`, but consistently) and verify it no longer appears under `knowledge`.&#x20;
  - Add “quote gate” and “intro/foreword gating” as heuristics, but do not blanket-drop introductions; treat them as likely narrative and keep them available for inspection.&#x20;

5. Integrate the existing tip miner as highlights and compute tip density.
   - In `cookimport/parsing/tips.py`, add a mode that can accept a pre-bounded chunk of text/blocks and return:

     - highlight spans (existing `TipCandidate` outputs, but marked as highlights),
     - tags (taxonomy-derived),
     - a per-highlight “self-contained” flag if implemented.
       The goal is to reuse the existing miner without reusing its boundary choice.&#x20;

   - Implement a “standalone tip gate” but in the chunk pipeline, not as the main output:

     - if a mined span is single-sentence and lacks action/mechanism/example, do not promote it as a standalone tip; keep it only as a highlight.&#x20;
       This specifically addresses aphorisms like “the inverse isn’t necessarily so.”&#x20;

   - Add deterministic span expansion (within chunk context) for mined highlights that appear clipped:

     - expand forward (and optionally backward) while still inside the same section, until a hard boundary or `max_chars`.
     - stop on heading, recipe boundary, major formatting break, or topic jump heuristic.

   - Add two cheap sanity checks as explicit heuristics (optional but recommended):

     - Sentence splitting backend (enabler): use `pysbd` (preferred for messy OCR) or `spacy` sentence segmentation to evaluate self-containedness and to choose expansion stop points within a block.
     - Minimum standalone length: if a mined highlight is promoted as a standalone tip anywhere (now or later), require `min_standalone_chars` / `min_standalone_tokens`; if below, force expansion first, otherwise demote to highlight-only.
     - Contrastive-marker expansion trigger: if a highlight contains “but/however/except/unless/instead/not necessarily/inverse” (configurable list), force expansion to include the surrounding explanation within the chunk; if expansion is blocked by a hard boundary, keep as highlight-only.



- Compute `tip_density` for each chunk:
  - simplest: `num_highlights / max(1, chunk_chars/1000)` and also store raw counts.
- Aggregate tags at the chunk level by unioning highlight tags, and (optionally) adding tags derived directly from chunk text via the existing taxonomy module.&#x20;

6. Add boundary refinements: hard/medium/soft, callouts, and format-mode changes.

   - Implement the boundary hierarchy:
     - Hard boundaries: major headings, recipe boundaries, obvious non-content blocks (ToC/index/page headers/footers).&#x20;
     - Medium boundaries: subheadings, labeled callouts (“TIP:”, “NOTE:”, “Variation:”, “Troubleshooting:”), and format mode changes (prose → bullets/numbered/definition-like).&#x20;
     - Soft boundaries: paragraph breaks and small asides; do not split chunks on these.&#x20;
   - Add “sidebar chunk” behavior:
     - when a callout is detected, create a separate chunk that “inherits” the parent section title (store it in `section_path` and/or `title`) so distillation has context.&#x20;
   - Add “topic pivot marker” detection as a medium boundary heuristic (“Now that you understand…”, “In the next section…”).&#x20;
   - Enforce min/max chunk size:
     - if a section grows beyond `max_chars`, split at the best medium boundary within the window (fallback: split at paragraph boundary, but record reason `max_chars`).

7. Tests, fixtures, and regression-proofing.

   - Add unit tests under `tests/` for:
     - heading-path stack behavior and section chunking,
     - lane assignment of blurbs and quote-only content,
     - highlight gating (aphorisms become highlights, not standalone),
     - deterministic output ordering and stable ids.
   - Add a small text fixture derived from the sample output patterns:
     - include a praise blurb,
     - include a heading like “USING SALT” with several paragraphs,
     - include an aphorism line and an immediately following explanatory paragraph,
     - include a callout like “TIP:” or “NOTE:”.
       Use it to assert chunk boundaries and lanes match expectations. The sample `tips extract example.md` provides concrete snippets to mirror. &#x20;
   - Ensure legacy `tips.md` generation remains unchanged until you explicitly decide to deprecate it (that decision would be recorded here later).

8. (Optional) Add distillation over chunks via the existing mocked LLM layer.

   - If `cookimport/llm/` already provides an interface (currently mocked), add a new function like:
     distill\_knowledge\_chunk(chunk: ChunkCandidate, \*, highlights: list[ChunkHighlight]) -> DistilledKnowledge
     Keep it behind a CLI flag (e.g. `--distill-chunks`) so core staging stays deterministic and offline-capable.&#x20;

   - Cache distillation results keyed by:

     - input file hash + chunk id + chunk text hash + prompt version,
       so repeated runs are idempotent and cheap.

   - Operationalize “tip density as a cheap prioritizer for LLM time” via an explicit distillation policy:

     - Only distill `knowledge` lane chunks.
     - Sort candidate chunks by `tip_density` descending (tie-breaker: chunk length, then id).
     - Provide two selection modes (configurable):
       - `top_k`: distill the top K chunks by density.
       - `threshold`: distill only chunks with `tip_density >= min_tip_density`.
     - Always emit a small run report (e.g. `distillation_selection.json` or a section in `chunks.md`) listing:
       - which chunks were selected,
       - their densities,
       - why they were selected (mode + parameters).

## Validation and Acceptance

Run:

- `python -m cookimport.cli stage data/input/<cookbook>`&#x20;

Acceptance is met when, in the newest `data/output/<timestamp>/` folder:

1. A new folder exists: `chunks/<workbook_stem>/` containing:

   - `chunks.md`
   - multiple `c{index}.json` files (at least one `knowledge` chunk when the input contains technique sections).

2. `chunks.md` demonstrates structure-first grouping:

   - the “USING SALT” heading produces a single coherent chunk (or a small number of coherent chunks if split by max size), not many tiny outputs.&#x20;

3. Front matter blurbs similar to “This beautiful, approachable book…” appear as `noise` or `narrative`, not `knowledge`.&#x20;

4. Aphorisms like “the inverse isn’t necessarily so” are not emitted as standalone “final knowledge” items; they appear only as highlights inside a larger knowledge chunk that contains nearby context.&#x20;

5. Existing `tips/<workbook_stem>/tips.md` continues to be produced (until explicitly deprecated), so downstream users are not broken.&#x20;

6. Tests pass:

   - run the repo’s standard test command (likely `python -m pytest` if present) and expect all tests pass, including new chunking tests.

7. If distillation is enabled (optional flag), it follows the selection policy:

   - only selected chunks are distilled,
   - selection is explainable and recorded in output artifacts,
   - re-running does not re-distill unchanged chunks (cache hit).

## Idempotence and Recovery

- Staging already writes to a timestamped output directory; the chunking outputs must follow the same convention so re-running stage does not overwrite prior runs.&#x20;
- The chunker must be deterministic given the same input block stream and profile settings:
  - stable ordering,
  - stable `c{index}` numbering,
  - stable `chunks.md` formatting.
- If optional distillation is enabled, it must be cached and keyed so repeated runs reuse results.
- If optional embeddings / classifiers are enabled:
  - cache per-block embeddings (or other expensive features) keyed by block text hash + model name/version,
  - persist enough metadata (model name, thresholds, feature flags) into output artifacts to make runs reproducible,
  - fail gracefully (fall back to lexical heuristics) if optional deps are missing.
- If a heuristic causes unexpected splits or mis-lane assignments, the recovery path is:
  - inspect `chunks.md` (boundary reasons + lanes),
  - add/adjust a profile override (book-specific) rather than hardcoding one-off hacks,
  - add a regression test fixture.

## Artifacts and Notes

As you implement, paste short “before vs after” excerpts (indented) into this section for the three targeted failure modes:

- praise blurb routed to `noise`,
- “USING SALT” grouped coherently,
- aphorism no longer standalone.
  Keep each excerpt under \~30 lines to avoid turning this plan into a data dump.

## Interfaces and Dependencies

### Optional third-party NLP/ML accelerators (behind flags)

These are **optional** dependencies that can materially improve boundary decisions and lane classification. The default pipeline should remain deterministic and should run without them.

- **pySBD (********`pysbd`********)**: robust sentence boundary detection for messy OCR / book typography. Use inside an atom/block for:
  - self-containedness checks (is this highlight a complete thought?),
  - “expand or demote” logic when a highlight is clipped,
  - finding the nearest sensible expansion stop within a block.
- **spaCy (********`spacy`********)**: tokenization + POS/dependency parsing + sentence segmentation. Use to enrich existing heuristics:
  - imperative/modality detection (e.g., should/must),
  - causal/justification markers (because/so that/therefore),
  - robust sentence segmentation as an alternative to pySBD.
- **SentenceTransformers / SBERT (********`sentence-transformers`********)**: embeddings per block/atom to drive semantic cohesion decisions:
  - merge adjacent blocks when similarity stays high,
  - split when similarity drops sharply (especially in heading-sparse regions),
  - detect boilerplate/repeated blocks by clustering or near-duplicate similarity.
- **scikit-learn (********`scikit-learn`********)**: lightweight supervised models for lane classification (knowledge/narrative/noise), trained from a small labeled set exported from Label Studio.
- **BERTopic (********`bertopic`********)**: optional topic discovery / clustering across many chunks (e.g., “salt”, “emulsions”), useful for analysis and for detecting topic shifts that should block merges.
- **UMAP (********`umap-learn`********) + HDBSCAN (********`hdbscan`********)**: optional clustering / dimensionality reduction tooling (often used by BERTopic, also useful standalone).

This plan relies on the existing architecture and modules:

- `cookimport/parsing/signals.py` provides block-level signals like heading detection and instruction/ingredient likelihood.&#x20;
- `cookimport/parsing/tips.py` currently handles span extraction, repair, and judging; we will reuse it to produce highlights inside chunks. &#x20;
- `cookimport/parsing/atoms.py` provides atomization with neighbor context; reuse it if helpful for highlight span expansion.&#x20;
- `cookimport/parsing/tip_taxonomy.py` provides dictionary-based tagging; chunk tags should reuse this schema.&#x20;
- `cookimport/staging/writer.py` writes outputs; extend it to write `chunks/` artifacts.&#x20;
- The repo includes Label Studio integration for evaluation; later, consider adapting it to evaluate “containment recall” for chunking rather than exact-match tip extraction. &#x20;

Keep new code modular:

- `parsing/chunks.py` should contain chunk boundary logic and nothing about IO.
- `parsing/lane.py` (or additions in `signals.py`) should contain lane scoring and blurb/noise detection.
- `staging/writer.py` should format and persist artifacts.
- Models live in `core/models.py` alongside existing `TipCandidate`/`TopicCandidate`.&#x20;

End of initial plan (2026-01-31): created an implementation roadmap that converts tip-mining into a chunk-first pipeline with highlights, lane routing, deterministic boundaries, and regression tests, consistent with `PLANS.md` requirements.&#x20;

```

## docs/parsing/tip_parsing_old.md

```markdown
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
```

## docs/plans/2026-01-31-fix-recipe-segmentation-and-ingredient-matching.md

```markdown
# Fix Recipe Segmentation and Ingredient Matching Bugs

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document is maintained in accordance with `/docs/PLANS.md`.

## Purpose / Big Picture

After this change, the EPUB importer will correctly handle recipes that have sub-section headers like "For the Frangipane" and "For the Tart" within a single recipe, rather than treating them as separate recipes. Additionally, unmatched ingredients (like spices when the instruction says "add spices" collectively) will be assigned to appropriate steps rather than being dropped entirely.

User-visible outcome: Running `cookimport convert data/input/saltfatacidheat.epub` will produce:
- r87 (Apple and Frangipane Tart) with all its ingredients (almonds, sugar, almond paste, butter, eggs, etc.) and full instructions
- r84 (Classic Pumpkin Pie) with all spices (cinnamon, ginger, cloves) assigned to step 4 where "spices" are mentioned

## Progress

- [x] (2026-01-31 15:00Z) Analyzed root cause of r87 empty recipe: `_find_recipe_end` in epub.py treats "For the X" sub-headers as new recipe titles
- [x] (2026-01-31 15:00Z) Analyzed root cause of r84 missing ingredients: `assign_ingredient_lines_to_steps` doesn't handle collective terms like "spices"
- [x] (2026-01-31 15:05Z) Implement fix for sub-section header detection in `_find_recipe_end` - added `_is_subsection_header()` method
- [x] (2026-01-31 15:06Z) Implement fix for collective term matching in `assign_ingredient_lines_to_steps` - added category definitions and fallback pass
- [x] (2026-01-31 15:08Z) Add tests for both fixes - 4 new tests added
- [x] (2026-01-31 15:09Z) Verify fixes with actual EPUB conversion - r87 now has 11 ingredients/16 steps, r84 has ginger/cloves in step 4

## Surprises & Discoveries

- Observation: The EPUB book uses "For the X" as ingredient section sub-headers, which is common in professional cookbooks but wasn't accounted for.
  Evidence: Block 2891 "For the Frangipane" followed by ingredient blocks 2892-2899

- Observation: Recipes commonly use collective terms like "spices", "seasonings", "dry ingredients" in instructions rather than listing each ingredient.
  Evidence: r84 instruction says "Add the cream, pumpkin purée, sugar, salt, and spices" but individual spice names aren't mentioned.

## Decision Log

- Decision: Detect "For the X" patterns as sub-section headers, not new recipe titles
  Rationale: These are always within a recipe, indicating a logical grouping of ingredients (e.g., "For the Frangipane" vs "For the Tart")
  Date/Author: 2026-01-31 / Claude

- Decision: Add collective term matching for ingredient categories like "spices", "seasonings", "herbs"
  Rationale: This is common cookbook language. We can identify ingredient categories and match them to collective terms in instructions.
  Date/Author: 2026-01-31 / Claude

## Outcomes & Retrospective

### Results
Both fixes were successfully implemented and verified:

1. **r87 (Apple and Frangipane Tart)**: Now correctly extracted with 11 ingredients and 16 instructions. Confidence improved from 0.25 to 0.94. Block range expanded from 3 blocks to 36 blocks.

2. **r84 (Classic Pumpkin Pie)**: Step 4 now includes "ground ginger" and "ground cloves" (previously unassigned) because the instruction mentions "spices" collectively.

### Remaining Items
- "All-Butter Pie Dough" and "Flour for rolling" in r84 are still unassigned because the instructions use "chilled dough" and "well-floured board" rather than the exact ingredient names. This would require more sophisticated semantic matching.
- "ground cinnamon" is assigned to step 5 (which mentions "Cinnamon Cream") rather than step 4. This is technically a false positive match but not harmful.

### Lessons Learned
- Recipe sub-section headers ("For the X") are common in professional cookbooks and should be treated as ingredient groupings, not new recipe starts.
- Collective terms like "spices" are common in recipe instructions and can be used to assign unmatched ingredients by category.

## Context and Orientation

The EPUB import pipeline works as follows:

1. `cookimport/plugins/epub.py:EpubImporter` extracts blocks from EPUB HTML
2. `_detect_candidates()` segments blocks into recipe ranges using yield markers and ingredient headers
3. `_find_recipe_end()` determines where each recipe ends by scanning forward for new recipe starts
4. `cookimport/staging/draft_v1.py:recipe_candidate_to_draft_v1()` converts to final format
5. `cookimport/parsing/step_ingredients.py:assign_ingredient_lines_to_steps()` matches ingredients to steps

Key files:
- `/cookimport/plugins/epub.py` - Contains `_find_recipe_end()` that needs the sub-header fix
- `/cookimport/parsing/step_ingredients.py` - Contains ingredient matching logic that needs collective term support

## Plan of Work

### Fix 1: Sub-section header detection

In `cookimport/plugins/epub.py`, modify `_find_recipe_end()` to recognize "For the X" patterns as sub-section headers that should NOT terminate the current recipe.

Add a new helper method `_is_subsection_header(block: Block) -> bool` that returns True for blocks matching:
- Text starts with "For the" (case-insensitive)
- Text is short (under 50 chars)
- Text ends without a period

In `_find_recipe_end()`, before the `_is_title_candidate` check at line 716, add a check: if the block is a subsection header, continue (don't treat it as a new recipe start).

### Fix 2: Collective term matching for ingredients

In `cookimport/parsing/step_ingredients.py`, add support for matching ingredient categories to collective terms:

1. Define category mappings:
   - "spices" -> matches ingredients containing "cinnamon", "ginger", "cloves", "nutmeg", "paprika", etc.
   - "herbs" -> matches "basil", "thyme", "oregano", "parsley", etc.
   - "seasonings" -> matches both spices and "salt", "pepper"

2. In `assign_ingredient_lines_to_steps()`, after the main matching pass, do a fallback pass:
   - For any unassigned ingredient, check if it belongs to a category
   - Check if any step mentions that category's collective term
   - If so, assign the ingredient to that step

## Concrete Steps

1. Edit `/cookimport/plugins/epub.py`:
   - Add `_is_subsection_header()` method after `_is_variation_header()` (around line 724)
   - Modify `_find_recipe_end()` to skip subsection headers

2. Edit `/cookimport/parsing/step_ingredients.py`:
   - Add ingredient category definitions
   - Add collective term detection
   - Add fallback assignment pass

3. Run tests:
       cd /home/mcnal/projects/recipeimport
       source .venv/bin/activate
       pytest tests/ -v

4. Run conversion on test file:
       python -m cookimport convert data/input/saltfatacidheat.epub -o data/output/test-fix

5. Verify outputs:
   - Check r87.jsonld has ingredients and instructions
   - Check r84.json has ginger and cloves in step 4

## Validation and Acceptance

After the fix:

1. r87 (Apple and Frangipane Tart) should have:
   - At least 14 ingredients (almonds, sugar, almond paste, butter, eggs, salt, vanilla, almond extract, tart dough, flour, apples, cream, sugar for sprinkling)
   - At least 8 instruction steps

2. r84 (Classic Pumpkin Pie) final JSON should have:
   - "ground ginger" assigned to step 4 (which mentions "spices")
   - "ground cloves" assigned to step 4

## Idempotence and Recovery

All changes are additive. If something breaks, the previous behavior is preserved by simply removing the new checks. Tests can be run repeatedly.

## Artifacts and Notes

(To be filled with test outputs during implementation)
```

## docs/plans/2026-02-02-epub-job-splitting.md

```markdown
# Split EPUB Jobs and Merge Results

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, large EPUB files can be split into spine-range jobs when `cookimport stage` runs with multiple workers. The user still receives one cohesive workbook output (one set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple part outputs. The observable behavior is that an EPUB import with `--workers > 1` shows multiple jobs with spine ranges, then merges into a single workbook with sequential recipe IDs.

## Progress

- [x] (2026-02-02 03:00Z) Drafted ExecPlan for EPUB job splitting and merge.
- [x] (2026-02-02 03:18Z) Implemented EPUB spine-range support in the importer and provenance.
- [x] (2026-02-02 03:28Z) Added job planning/worker/merge support for EPUB splits using the existing PDF job split infrastructure.
- [x] (2026-02-02 03:36Z) Updated tests, docs, and short folder notes for the new behavior.

## Surprises & Discoveries

- Observation: The EPUB importer currently treats all spine items as a single linear block stream, and block indices reset per run, so split jobs need an explicit spine index to preserve global ordering during merges.
  Evidence: `cookimport/plugins/epub.py` builds blocks in `_extract_docpack` and uses `start_block`/`end_block` for provenance, with no spine metadata.

## Decision Log

- Decision: Split EPUBs by spine item ranges and store `start_spine`/`end_spine` in provenance locations to preserve global ordering across merged jobs.
  Rationale: Spine items are the natural unit of EPUB structure and can be counted cheaply during inspection; location metadata provides a stable ordering key even when block indices are local to each job.
  Date/Author: 2026-02-02 / Codex

- Decision: Reuse the existing PDF job planning and merge helpers by generalizing them for non-PDF importers, keeping PDF wrappers intact for backward compatibility.
  Rationale: Avoids re-implementing split/merge logic and keeps tests for PDF splitting valid.
  Date/Author: 2026-02-02 / Codex

## Outcomes & Retrospective

EPUB imports now support spine-range job splitting when `--workers > 1`, with merged outputs and sequential recipe IDs. The CLI plans EPUB jobs using spine counts, workers can process spine ranges in parallel, and the merge step rewrites IDs while combining tips, chunks, and raw artifacts. Tests were added for EPUB ID reassignment, and documentation now covers the new flag and `.job_parts` behavior. Remaining work: consider a future improvement to detect recipes spanning spine boundaries if that becomes a practical issue.

## Context and Orientation

The bulk ingestion workflow lives in `cookimport/cli.py` (`stage` command). It plans work items (jobs), executes them in a `ProcessPoolExecutor`, and merges results for split PDFs via `_merge_pdf_jobs`. Split jobs use `cookimport/cli_worker.py:stage_pdf_job` to run a page range and write raw artifacts into a temporary `.job_parts/` folder that the main process merges back into `raw/` after the merge finishes.

The EPUB importer is `cookimport/plugins/epub.py`. It reads the EPUB spine, converts HTML to linear `Block` objects, segments blocks into recipes, and writes provenance locations with `start_block`/`end_block` indices. There is no spine index in the provenance today, so split jobs would lose global ordering unless we add spine metadata.

The job range logic currently lives in `cookimport/staging/pdf_jobs.py` via `plan_pdf_page_ranges` and `reassign_pdf_recipe_ids`. We will generalize those helpers to allow EPUB splitting while keeping the PDF functions intact as wrappers.

## Plan of Work

First, extend `cookimport/core/models.py` and the EPUB inspector to record spine counts. Add a `spine_count` field (alias `spineCount`) to `SheetInspection`. Update `EpubImporter.inspect` to set `spine_count` using the EPUB spine length (via ebooklib or the zip fallback) so the CLI can decide when to split.

Next, update the EPUB importer to accept `start_spine` and `end_spine` range parameters and only parse the specified spine slice. In `cookimport/plugins/epub.py`, thread these parameters through `convert` and `_extract_docpack` into both the ebooklib and zip extraction paths. When parsing each spine item, annotate each generated `Block` with a `spine_index` feature. When building recipe provenance, compute `start_spine`/`end_spine` from the candidate blocks and include those values in the location dictionary. This gives merged jobs a stable ordering key. Keep the rest of the extraction logic unchanged.

Then generalize the job planning and merge helpers. In `cookimport/staging/pdf_jobs.py`, introduce a generic range planner and a generic ID reassigner that accept an importer name. Keep `plan_pdf_page_ranges` and `reassign_pdf_recipe_ids` as wrappers. Update the sort key helper to consider `start_spine` (and `startSpine` if present) ahead of `start_block` when ordering recipes.

Update the CLI to plan EPUB jobs and merge them using the same merge flow as PDF jobs. Add a new CLI flag such as `--epub-spine-items-per-job` (default 10) and a `_resolve_epub_spine_count` helper to read the count from inspection. Extend `JobSpec` to track EPUB ranges (`start_spine`/`end_spine`) and choose the correct worker entrypoint (`stage_epub_job` vs `stage_pdf_job`) based on the range kind. Add `stage_epub_job` in `cookimport/cli_worker.py` mirroring the PDF job flow: run the range, write raw artifacts to `.job_parts/<workbook>/job_<index>/raw`, clear `result.raw_artifacts`, and return a mergeable payload with timing. Finally, add a new merge helper in `cookimport/cli.py` (or generalize `_merge_pdf_jobs`) that can merge EPUB jobs by calling the generalized ID reassigner with importer name `epub` and then writing outputs exactly as the PDF merge does.

Add tests and docs. Create a small unit test for the generalized range planner and for the EPUB ID reassignment ordering (using synthetic `RecipeCandidate` objects with `start_spine` in provenance). Update `docs/architecture/README.md` and `docs/ingestion/README.md` to mention EPUB job splitting and the new CLI flag. Update `docs/IMPORTANT CONVENTIONS.md` to note that EPUB split jobs also write raw artifacts into `.job_parts/` during merges. Add a short note in `cookimport/README.md` (or another existing short doc in the folder) describing the EPUB job split behavior and the new flag. If any new understanding is needed, add a brief note under `docs/understandings/`.

## Concrete Steps

All commands are run from `/home/mcnal/projects/recipeimport`.

1) Update models and EPUB inspection.

   - Edit `cookimport/core/models.py` to add `spine_count` to `SheetInspection` with alias `spineCount`.
   - Edit `cookimport/plugins/epub.py` to populate `spine_count` in `inspect` using spine length.

2) Add EPUB range support and provenance metadata.

   - Add `start_spine`/`end_spine` parameters to `EpubImporter.convert` and `_extract_docpack`.
   - In `_extract_docpack_with_ebooklib` and `_extract_docpack_with_zip`, iterate spine items with indices and filter by range.
   - Pass the spine index into `_parse_soup_to_blocks` and store it in block features.
   - When building candidate provenance, compute and store `start_spine`/`end_spine` in the location dict.

3) Generalize job planning and ID reassignment.

   - In `cookimport/staging/pdf_jobs.py`, add a generic range planner and a generic `reassign_recipe_ids` helper. Keep the existing PDF wrapper functions.
   - Extend the recipe sort key to consider `start_spine` before `start_block`.

4) Extend CLI/worker job splitting.

   - Add CLI flag `--epub-spine-items-per-job` to `cookimport/cli.py` and plan EPUB jobs when `workers > 1` and spine count exceeds the threshold.
   - Extend `JobSpec` to track EPUB spine ranges and to display `spine` ranges in the worker panel.
   - Add `stage_epub_job` in `cookimport/cli_worker.py` and call it for EPUB split jobs.
   - Generalize `_merge_pdf_jobs` into a shared helper that accepts importer name and range metadata, then call it for PDF and EPUB merges.

5) Tests and docs.

   - Add unit tests for EPUB ID reassignment ordering (e.g., `tests/test_epub_job_merge.py`).
   - Update `docs/architecture/README.md`, `docs/ingestion/README.md`, and `docs/IMPORTANT CONVENTIONS.md` with the new EPUB split behavior.
   - Update `cookimport/README.md` with a short note about the new EPUB split flag.

## Validation and Acceptance

- Running `cookimport stage --workers 4 --epub-spine-items-per-job 10 data/input/<large.epub>` should show multiple worker lines with spine ranges (for example, `book.epub [spine 1-10]`) and a merge message `Merging N jobs for book.epub...`.
- The output folder should contain a single workbook under `intermediate drafts/`, `final drafts/`, and `tips/`, plus a single report JSON for that EPUB.
- Recipe identifiers in the final output should be sequential (`...:c0`, `...:c1`, ...), and any recipe-specific tips should reference the updated IDs.
- Raw artifacts should be merged into `raw/` from `.job_parts/` and the `.job_parts/` folder should be removed after a successful merge.
- `pytest tests/test_epub_job_merge.py tests/test_pdf_job_merge.py` should pass; the EPUB test should fail before these changes and pass after.

## Idempotence and Recovery

The changes are safe to rerun because each staging run writes to a new timestamped output folder. If a merge fails, the temporary `.job_parts/` folder remains for debugging; re-running the command will create a new output folder and a new merge attempt without mutating previous outputs.

## Artifacts and Notes

Expected log excerpt for an EPUB split run:

    Processing 1 file(s) as 3 job(s) using 4 workers...
    worker-1: cookbook.epub [spine 1-10] - Parsing recipes...
    worker-2: cookbook.epub [spine 11-20] - Parsing recipes...
    Merging 3 jobs for cookbook.epub...
    ✔ cookbook.epub: 120 recipes, 18 tips (merge 5.12s)

## Interfaces and Dependencies

- `cookimport/core/models.py`
  - Add `SheetInspection.spine_count: int | None` with alias `spineCount`.
- `cookimport/plugins/epub.py`
  - `EpubImporter.convert(path, mapping, progress_callback, start_spine: int | None = None, end_spine: int | None = None)`
  - `_extract_docpack(path, start_spine: int | None = None, end_spine: int | None = None)`
  - Store `spine_index` in block features and add `start_spine`/`end_spine` to provenance location.
- `cookimport/staging/pdf_jobs.py`
  - Add `plan_job_ranges` and `reassign_recipe_ids(importer_name=...)` helpers; keep existing PDF wrappers.
  - Update recipe sort key to consider `start_spine`.
- `cookimport/cli_worker.py`
  - Add `stage_epub_job` with the same mergeable payload format as `stage_pdf_job`.
- `cookimport/cli.py`
  - Add `--epub-spine-items-per-job` flag, EPUB job planning, and shared merge helper for split jobs.

Change note: 2026-02-02 — Initial ExecPlan created for EPUB job splitting.
Change note: 2026-02-02 — Updated progress, outcomes, and plan details after implementing EPUB job splitting and tests/docs.
```

## docs/plans/2026-02-02-split-pdf-jobs-and-merge.md

```markdown
# Split PDF Jobs and Merge Results

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a single large PDF can fully utilize multiple workers by being split into page-range jobs (for example, a 200 page PDF with 4 workers runs as four jobs over pages 1–50, 51–100, 101–150, and 151–200). The user still receives one cohesive workbook output (single set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple “part” outputs. The new behavior is observable by running `cookimport stage` with `--workers > 1` on a large PDF and seeing parallel job progress plus a single workbook output folder when the run completes.

## Progress

- [x] (2026-02-02 00:00Z) Drafted initial ExecPlan with proposed job splitting + merge design.
- [x] (2026-02-02 02:05Z) Implemented job planning for PDF page splits in `cookimport/cli.py`.
- [x] (2026-02-02 02:12Z) Added page-range support to `cookimport/plugins/pdf.py` and propagated OCR/text paths.
- [x] (2026-02-02 02:35Z) Added job-level worker entrypoint and merge logic for multi-job PDFs.
- [x] (2026-02-02 02:55Z) Updated docs + conventions and added unit tests for job planning and ID rewriting.

## Surprises & Discoveries

- Observation: `cookimport/cli.py` always passes a `MappingConfig` to workers even when no mapping file is provided, so the current `stage_one_file` path never runs `importer.inspect` automatically.
  Evidence: `cookimport/cli.py` sets `base_mapping = mapping_override or MappingConfig()` and always passes it into `stage_one_file`.
- Observation: `ProcessPoolExecutor` can raise `PermissionError` in restricted environments (e.g., during CLI tests), preventing worker startup.
  Evidence: CLI test run failed with `PermissionError: [Errno 13] Permission denied` during ProcessPool initialization.

## Decision Log

- Decision: Merge multi-job PDF outputs in the main process and rewrite recipe IDs to a single global sequence (`c0..cN`) so IDs remain stable regardless of whether a PDF was split.
  Rationale: This avoids ID collisions across jobs and keeps stable IDs consistent with the existing full-file ordering scheme.
  Date/Author: 2026-02-02 / Codex

- Decision: Keep the existing worker path for files that are not split, so normal multi-file runs still write outputs in parallel.
  Rationale: Avoids moving all output writing to the main process and preserves current performance.
  Date/Author: 2026-02-02 / Codex

- Decision: Use a single configurable threshold (`--pdf-pages-per-job`, default 50) to decide when to split and how many jobs to create (capped by worker count).
  Rationale: Matches the example (200 pages / 4 workers → 4 jobs of 50 pages) while keeping the CLI surface minimal.
  Date/Author: 2026-02-02 / Codex

- Decision: Fall back to serial execution if `ProcessPoolExecutor` cannot be created (PermissionError).
  Rationale: Keeps staging usable in restricted environments while preserving parallelism when available.
  Date/Author: 2026-02-02 / Codex

## Outcomes & Retrospective

Implemented PDF job splitting and merge flow so large PDFs can run in parallel while
producing a single cohesive workbook output. The CLI now plans jobs, workers can
process page ranges, and the main process merges results, rewrites IDs, and merges
raw artifacts. Documentation and unit tests were updated to cover the new behavior.

Lessons learned: isolating raw artifacts in job-specific folders kept merge payloads
light and made the final merge deterministic.

## Context and Orientation

The ingestion pipeline is driven by `cookimport/cli.py:stage`, which enumerates source files, starts a `ProcessPoolExecutor`, and calls `cookimport/cli_worker.py:stage_one_file` per file. `stage_one_file` selects an importer from `cookimport/plugins/registry.py`, runs `importer.convert(...)` to produce a `ConversionResult`, generates knowledge chunks, enriches a `ConversionReport`, and writes outputs via `cookimport/staging/writer.py`.

The PDF importer lives in `cookimport/plugins/pdf.py`. It currently processes the entire document in one pass and assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}`. OCR is optional and implemented in `cookimport/ocr/doctr_engine.py:ocr_pdf`, which already accepts `start_page` and `end_page` (exclusive).

For this change we introduce a “job” as the new unit of work. A job is either an entire file (non-split) or a page-range slice of a PDF (split). Each job executes `PdfImporter.convert` on its page range. After all jobs for a file complete, their results are merged, IDs are re-assigned in global order, and a single output folder is written.

## Plan of Work

First, add job planning logic to `cookimport/cli.py`. Create a small helper (either inside `cli.py` or a new module such as `cookimport/cli_jobs.py`) that inspects each file to decide whether it should be split. For PDF files, retrieve a page count via `PdfImporter.inspect` (add a `page_count` field to `SheetInspection` in `cookimport/core/models.py`, and populate it in `PdfImporter.inspect`). If `page_count > --pdf-pages-per-job` and `workers > 1`, generate page ranges sized at `ceil(page_count / job_count)` where `job_count = min(workers, ceil(page_count / pdf_pages_per_job))`. Each range is `[start_page, end_page)` with 0-based indexing. Non-PDFs and PDFs that do not meet the threshold stay as single jobs.

Second, extend `PdfImporter.convert` to accept optional `start_page` and `end_page` parameters. When a range is provided, the OCR path should call `ocr_pdf(path, start_page=..., end_page=...)`, and the text extraction path should iterate pages only over that range, passing the absolute page index into `_extract_blocks_from_page`. Update progress messages to reflect `page_num + 1` and the total pages in the slice. Add a warning to the report if the requested slice is empty (start >= end). Ensure the rest of the extraction pipeline (candidate segmentation, tips, topics, raw artifacts) works unchanged on the subset of blocks.

Third, refactor `cookimport/cli_worker.py` so it can run a page-range job and return a mergeable payload without writing full outputs. Extract a helper (for example `run_import`) that executes the import, timing, and report enrichment but returns a `ConversionResult`. For split jobs, write only raw artifacts to a job-specific temporary directory (for example `{out}/.job_parts/{workbook_slug}/job_{index}/raw/...`) and clear `result.raw_artifacts` before returning to reduce inter-process payload size. For non-split files, keep the existing `stage_one_file` behavior so outputs are written in the worker.

Fourth, add a merge step in `cookimport/cli.py` for files that were split into multiple jobs. Collect `JobResult` payloads, sort them by `start_page`, and merge their `ConversionResult` lists (recipes, tip candidates, topic candidates, non-recipe blocks). Recompute `tips` using `partition_tip_candidates` so it matches the merged tip candidate list. Then rewrite recipe identifiers and provenance to a global sequence:

- Sort merged recipes by their provenance `location.start_page` (fall back to `location.start_block` or the merge order).
- For each recipe at global index `i`, set `candidate.identifier = generate_recipe_id("pdf", file_hash, f"c{i}")`, update `candidate.provenance["@id"]` (and `id` if present), and set `candidate.provenance["location"]["chunk_index"] = i`.
- Build a mapping from old IDs to new IDs. Update `TipCandidate.source_recipe_id` and any `tip.provenance["@id"]` or `tip.provenance["id"]` that match old IDs.

After IDs are updated, apply the CLI `--limit` (once, at the merged level), regenerate knowledge chunks using `chunks_from_non_recipe_blocks` or `chunks_from_topic_candidates`, and build a fresh `ConversionReport` with totals and `enrich_report_with_stats`. Write the merged outputs using `write_intermediate_outputs`, `write_draft_outputs`, `write_tip_outputs`, `write_topic_candidate_outputs`, `write_chunk_outputs`, and `write_report` into the normal output directories. Finally, merge raw artifacts by moving job raw folders into the final `{out}/raw/...` tree; if name collisions occur, prefix the filename with the job index to preserve uniqueness. Remove the temporary `.job_parts` folder once the merge succeeds.

Fifth, update the progress UI. The overall progress bar should count total jobs, not just files, and the worker status lines should include the page range (for example `cookbook.pdf [pages 1-50]`). After a file’s jobs finish and merge begins, log a line like `Merging 4 jobs for cookbook.pdf...` so users understand the second phase.

Finally, add tests and docs. Create unit tests for page-range slicing and merged-ID rewriting (in a new `tests/test_pdf_job_merge.py` or similar) using synthetic `ConversionResult` objects so we do not require real PDFs. Update `docs/architecture/README.md` and `docs/ingestion/README.md` to describe PDF job splitting and the merge step, and add a short note in a relevant folder (likely `cookimport/README.md` or a new short doc in `cookimport/`) explaining how job splitting behaves. If the output structure introduces a `.job_parts` temp folder, document it in `docs/IMPORTANT CONVENTIONS.md`.

## Concrete Steps

All commands assume the working directory `/home/mcnal/projects/recipeimport`.

1) Inspect current CLI/worker/PDF surfaces (if not already done):

    rg -n "stage_one_file|ProcessPoolExecutor|PdfImporter" cookimport

2) Implement model + PDF changes:

    - Edit `cookimport/core/models.py` to add `page_count: int | None = Field(default=None, alias="pageCount")` to `SheetInspection`.
    - Edit `cookimport/plugins/pdf.py` to populate `page_count` in `inspect`, and add `start_page`/`end_page` support in `convert` plus the OCR/text extraction paths.

3) Implement job planning + merging:

    - Edit `cookimport/cli.py` to add `--pdf-pages-per-job` and job planning helpers, and to schedule job futures differently for split vs non-split files.
    - Edit `cookimport/cli_worker.py` to add a job-capable entrypoint (and refactor shared logic as needed) that returns mergeable payloads and writes raw artifacts to a job temp folder.
    - Add merge helpers in `cookimport/cli.py` or a new module (for example `cookimport/staging/merge.py`).

4) Tests (use local venv):

    - Create/activate `.venv` if needed, then install dev deps:

        python -m venv .venv
        . .venv/bin/activate
        python -m pip install --upgrade pip
        pip install -e .[dev]

    - Run targeted tests:

        pytest tests/test_pdf_job_merge.py tests/test_cli_output_structure.py

5) Docs updates:

    - Edit `docs/architecture/README.md`, `docs/ingestion/README.md`, and `docs/IMPORTANT CONVENTIONS.md` as described in Plan of Work.
    - Add/adjust a short, folder-local note describing the new job split behavior.

## Validation and Acceptance

Acceptance is met when the following manual scenario works and outputs are cohesive:

1) Run `cookimport stage --workers 4 --pdf-pages-per-job 50 data/input/<large.pdf>` and observe the worker panel showing multiple jobs with page ranges.
2) In the output folder (`data/output/{timestamp}`), verify that only one workbook slug exists under `intermediate drafts/`, `final drafts/`, and `tips/`, with sequential `r{index}.json(ld)` numbering and a single report JSON file.
3) Confirm that recipe `identifier` values are sequential (`...:c0`, `...:c1`, …) across the merged output, and that any recipe-specific tips reference the updated recipe IDs.
4) Verify raw artifacts exist under `raw/pdf/{hash}/...` with no filename collisions (job prefixing is acceptable if needed).

If automated tests are added, they should fail before this change and pass after. Specifically, the new merge test must assert that merged recipe IDs and tip `sourceRecipeId` values are updated to the global sequence.

## Idempotence and Recovery

Re-running the same command is safe because outputs are written into a new timestamped folder. If a merge fails mid-way, the temporary job folder under `{out}/.job_parts/` remains for debugging; re-run the command to regenerate a clean output folder. If a job fails, the merge should abort for that file and write an error report so the run still completes for other files.

## Artifacts and Notes

Expected log lines during a split run (example):

    Processing 1 file(s) as 4 job(s) using 4 workers...
    worker-1: cookbook.pdf [pages 1-50] - Parsing recipes...
    worker-2: cookbook.pdf [pages 51-100] - Parsing recipes...
    Merging 4 jobs for cookbook.pdf...
    ✔ cookbook.pdf: 128 recipes, 14 tips (merge 6.42s)

## Interfaces and Dependencies

- `cookimport/core/models.py`
  - `SheetInspection.page_count: int | None` (alias `pageCount`).
- `cookimport/plugins/pdf.py`
  - `PdfImporter.convert(path, mapping, progress_callback, start_page: int | None = None, end_page: int | None = None)`
  - Use `ocr_pdf(path, start_page=..., end_page=...)` for OCR path; iterate `fitz` pages in `[start_page, end_page)` for non-OCR.
- `cookimport/cli_worker.py`
  - New job entrypoint returning a `JobResult` containing `ConversionResult` (with raw artifacts cleared), job metadata, and duration.
- `cookimport/cli.py`
  - Job planning helper, CLI options for `--pdf-pages-per-job`, and merge orchestration.
- `cookimport/staging/writer.py`
  - No interface changes; reuse existing write helpers for merged output.

Change note: 2026-02-02 — Initial ExecPlan created in response to the request to plan before implementation.
Change note: 2026-02-02 — Updated progress, outcomes, and documented completion of PDF job splitting implementation (including serial fallback note).
```

## docs/plans/epub_split.md

```markdown
# Split large EPUBs into worker jobs and merge into one cohesive workbook

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a single large `.epub` can fully utilize multiple workers by being split into “spine-range jobs” (contiguous ranges of reading-order documents). For example, a big EPUB with 80 spine items and 4 workers can run as 4 jobs over spine items 0–19, 20–39, 40–59, and 60–79. The user still receives one cohesive workbook output (single set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple “part” outputs.

The new behavior is observable by running `cookimport stage` with `--workers > 1` on a large EPUB and seeing parallel job progress plus a single workbook output folder when the run completes. The merged outputs must have stable sequential recipe IDs as if the EPUB had been processed in one pass.

## Progress

- [ ] (2026-02-01 00:00Z) Read the existing PDF job splitting implementation and identify reusable job planning, worker entrypoint, temp output layout, and merge helpers.
- [ ] Add EPUB inspection fields needed to plan spine-range jobs (spine item count).
- [ ] Extend `cookimport/plugins/epub.py` so `convert` can process a spine slice (plus optional overlap) and so blocks/candidates record absolute spine indices in provenance.
- [ ] Extend CLI job planning to split EPUBs into spine-range jobs (behind a threshold flag) and schedule those jobs in the existing process pool.
- [ ] Implement EPUB merge logic in the main process that combines job results, rewrites recipe IDs to a single global sequence, merges raw artifacts, and writes one workbook output folder.
- [ ] Add tests for job planning, slice filtering, and merged ID rewriting (no real EPUB required; synthetic objects are acceptable).
- [ ] Update docs and CLI help strings, and add a note describing the temporary `.job_parts` behavior for split EPUBs.
- [ ] Validate on a real large EPUB: confirm parallel job progress and one cohesive output folder; document measured speedup and any accuracy changes.

## Surprises & Discoveries

- Observation: (fill during implementation)
  Evidence: (short command output or failing test snippet)

## Decision Log

- Decision: (fill during implementation)
  Rationale: (why this path was chosen)
  Date/Author: (YYYY-MM-DD / who)

## Outcomes & Retrospective

- (Fill at milestone completion and at the end: what improved, what broke, what remains, and lessons learned.)

## Context and Orientation

The ingestion pipeline is driven by `cookimport/cli.py:stage`, which enumerates source files, starts a `concurrent.futures.ProcessPoolExecutor`, and calls a worker entrypoint (commonly `cookimport/cli_worker.py:stage_one_file`) per unit of work. Plugins are chosen via `cookimport/plugins/registry.py` and implement `detect`, `inspect`, and `convert`. Converting unstructured sources typically produces a linear sequence of `Block` objects which are segmented into `RecipeCandidate`, `TipCandidate`, and `TopicCandidate` objects, along with raw artifacts and a report.

This repository already contains a “job splitting + merge” pattern for PDFs: a large file is split into multiple jobs, each job processes a slice, the main process merges results into one workbook output, and recipe identifiers are rewritten to a single stable global sequence (`...:c0`, `...:c1`, …). This ExecPlan extends that same pattern to EPUB files to achieve the same benefit for large cookbooks.

Definitions used in this plan:

- “Worker”: a separate operating-system process used to run Python in parallel on multiple CPU cores.
- “Job”: one unit of work submitted to the worker pool. For an EPUB split run, each job is a contiguous slice of the EPUB’s reading order.
- “EPUB spine item”: an entry in the EPUB’s OPF “spine”, which defines the reading order. In practice this corresponds to an HTML/XHTML “chapter” file inside the EPUB container.
- “Spine-range job”: a job defined by `[start_spine_index, end_spine_index)` (0-based, end exclusive).
- “Overlap”: extra spine items included on each side of a job slice to preserve segmentation context near boundaries. Overlap is used only for context; the job returns only recipes whose start location falls within the job’s owned range to avoid duplicates.
- “Owned range”: the non-overlapped spine range that a job is responsible for contributing to the final merged output.

Assumptions this plan relies on (verify in code before editing):

- `cookimport/plugins/epub.py` exists and uses EbookLib / BeautifulSoup / lxml for parsing.
- The PDF split implementation already introduced: (a) a representation of per-file jobs, (b) a `.job_parts` output convention for split files, (c) a merge step in the main process that rewrites recipe IDs and merges raw artifacts, and (d) a serial fallback if `ProcessPoolExecutor` cannot be created (for example due to `PermissionError` in restricted environments).
- `RecipeCandidate` (and related models) carry provenance that can be extended to include spine indices and block indices so that ordering and filtering are deterministic.

If any of those assumptions are false, update this plan’s Decision Log with the chosen adaptation and ensure all sections remain self-contained.

## Plan of Work

This work mirrors the PDF splitting approach: plan jobs in the CLI, teach the EPUB importer to process only a slice, have workers produce mergeable partial results without writing the full workbook outputs, then merge in the main process and write one cohesive output.

### Milestone 1: Reuse and generalize the existing job framework for a new “epub spine slice” job kind

By the end of this milestone you will know exactly which functions and data structures the PDF split system uses for job planning, worker execution, temp output folders, and merging, and you will have a clear place to add EPUB job support.

Work:

Read the files involved in the PDF split flow and write down the exact names and signatures you will reuse. Specifically locate:

- Where jobs are planned (likely inside `cookimport/cli.py` or a helper module).
- How a job is represented (a dataclass or Pydantic model holding job metadata such as kind, slice bounds, and output temp paths).
- The worker entrypoint for a job and what it returns to the parent process (a “JobResult” or similar).
- The merge function and how it rewrites recipe IDs and merges raw artifacts into the final output.

Decision to make and record:

- Whether to add EPUB support by introducing a new job kind (recommended), or by generalizing “slice jobs” into a single abstraction used by both PDF and EPUB. Prefer the smallest change that preserves readability and testability.

### Milestone 2: Add EPUB inspection data needed for splitting (spine item count)

By the end of this milestone, the CLI can cheaply determine how many spine items an EPUB contains without performing the full conversion.

Work:

- In `cookimport/plugins/epub.py`, implement or extend `EpubImporter.inspect(path)` so it returns a count of spine items (document items in reading order).
- Decide where to store this in inspection models:
  - If your PDF split already added `SheetInspection.page_count`, extend the same inspection model with a new optional `spine_item_count` field (preferred for symmetry).
  - If inspection models do not have a natural place for this, add a new field to the top-level `WorkbookInspection` such as `epub_spine_item_count`. Record the choice in the Decision Log.

Implementation detail (what “spine item count” should mean):

- Open the EPUB using EbookLib and compute the number of document items in the spine reading order.
- Count only document content (HTML/XHTML) items that will actually produce blocks; ignore images, stylesheets, and non-document items.
- The count must be deterministic and stable across runs, because the split planner will use it.

Proof:

- `cookimport inspect some.epub` (or whatever command triggers inspection) shows the spine count in the inspection output or report artifacts.
- A small unit test can call `EpubImporter.inspect` on a minimal EPUB fixture and assert the count is correct.

### Milestone 3: Teach the EPUB importer to convert a spine slice with overlap and stable provenance

By the end of this milestone, `EpubImporter.convert` can run on a subset of spine items and produce results whose provenance includes absolute spine indices (so merge ordering and slice filtering are deterministic).

Work:

- Extend `cookimport/plugins/epub.py:EpubImporter.convert` to accept optional keyword arguments:
  - `start_spine: int | None = None`
  - `end_spine: int | None = None`
  - `owned_start_spine: int | None = None`
  - `owned_end_spine: int | None = None`

Interpretation:

- The importer processes the “slice range” `[start_spine, end_spine)` (this may include overlap).
- The importer filters its produced recipe candidates (and any recipe-specific tip candidates) to only those whose start location lies within the “owned range” `[owned_start_spine, owned_end_spine)`.
- If no slice is provided, behavior is unchanged (full EPUB conversion).

How to implement without breaking existing behavior:

- Identify where EPUB content is enumerated today. Usually this looks like: iterate over spine items in reading order, parse each HTML/XHTML file into blocks, append blocks to one list, then run segmentation.
- Modify enumeration so that, when a slice is provided, you only iterate spine items within `[start_spine, end_spine)`. Critically, preserve the absolute spine index (0-based in full EPUB) as `spine_index` on every block’s provenance location.
- Ensure the block-level provenance also contains a stable per-spine-item block index (for example `block_index_within_spine`) so ordering within a spine item is stable. If a global block index already exists, keep it, but make sure it remains deterministic for sliced runs.

Filtering rule (prevents duplicates when overlap is used):

- Define a function that determines the “start location” of a `RecipeCandidate`. Prefer the earliest block that the candidate claims as its provenance location.
- A candidate belongs to the job if:
  - `owned_start_spine <= candidate.provenance.location.spine_index < owned_end_spine`.
- Apply the same rule to recipe-specific tips if they are anchored to a recipe start location or if they reference a source recipe ID; in ambiguous cases keep tips and let the merge step re-partition them, but ensure no duplicate recipe-specific tips survive the merge.

Edge cases to handle:

- Empty slice: if `start_spine >= end_spine`, return an empty `ConversionResult` with a warning in the report.
- Single-spine EPUB: splitting should not occur; slice conversion still works but produces little benefit.

Proof:

- A targeted unit test can build synthetic blocks with spine indices and prove that slice conversion yields candidates whose provenance spine indices are in the owned range.
- A manual run on a real EPUB with `--workers 1` and an explicit slice (temporary CLI flag or a direct call in a small dev script) produces reasonable partial outputs.

### Milestone 4: Plan EPUB spine-range jobs in the CLI and run them in the worker pool

By the end of this milestone, `cookimport stage` can split a single large EPUB into multiple spine-range jobs, submit them to workers, and collect job results.

Work:

- In `cookimport/cli.py`, extend the existing job planning helper to recognize `.epub` inputs and produce EPUB jobs when all of the following are true:
  - `--workers > 1`
  - The importer selected for the file is the EPUB importer.
  - `spine_item_count` is greater than a threshold derived from a new CLI flag (see below).

Add new CLI flags (name them to match the existing PDF flag style):

- `--epub-spine-items-per-job` (integer, default 20; must be > 0)
  - This controls when splitting happens and the approximate size of each job.
- `--epub-spine-overlap-items` (integer, default 1; can be 0)
  - This controls how many spine items of overlap are included on each side of a job slice for context.

Job planning algorithm (deterministic and simple):

- Let `S = spine_item_count`.
- If `S <= epub_spine_items_per_job` or `workers == 1`, create a single non-split job for the file.
- Otherwise:
  - Let `job_count = min(workers, ceil(S / epub_spine_items_per_job))`.
  - Let `range_size = ceil(S / job_count)`.
  - For `job_index` from 0 to `job_count-1`:
    - `owned_start = job_index * range_size`
    - `owned_end = min(S, owned_start + range_size)`
    - `slice_start = max(0, owned_start - overlap)`
    - `slice_end = min(S, owned_end + overlap)`
    - Create an EPUB job with these four bounds and the `job_index`.
- Ensure the final job list covers `[0, S)` in owned ranges with no gaps and no overlaps (owned ranges), even though slice ranges will overlap.

Worker execution:

- Reuse the existing worker entrypoint pattern from the PDF split flow. Add EPUB job support by:
  - Passing `start_spine`, `end_spine`, `owned_start_spine`, `owned_end_spine` into `EpubImporter.convert`.
  - Writing raw artifacts into a job temp folder under `.job_parts` and returning a small payload (do not return all raw artifacts over IPC if they are large).
  - Returning job metadata: file path, job index, owned range, slice range, duration, counts.

Resilience:

- Preserve the existing serial fallback: if `ProcessPoolExecutor` cannot be created, process as a single non-split job (log a warning that parallelism is disabled).

Proof:

- Running `cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 some_large.epub` shows multiple worker status lines that include spine ranges.
- The staging run finishes without writing multiple workbook roots (merge happens next milestone).

### Milestone 5: Merge EPUB job results into a single cohesive workbook and write outputs once

By the end of this milestone, split EPUB runs produce exactly one workbook output folder with stable IDs and consistent reports.

Work:

- Add or extend the main-process merge step for “split files” to support EPUB jobs. Follow the same high-level strategy as PDF merge:
  - Collect all `JobResult` objects for a given EPUB file.
  - Sort jobs by `owned_start_spine`.
  - Merge their `ConversionResult` payloads into one merged `ConversionResult` for the file.
  - Rewrite recipe identifiers to a single global sequence so IDs do not depend on splitting.
  - Merge raw artifacts from `.job_parts` into the final raw folder and remove `.job_parts` on success.
  - Write intermediate drafts, final drafts, tips, topics, chunks, and the report using existing writer helpers.

Merging details to make deterministic:

- Ordering for merged recipes:
  - Sort by `(recipe.provenance.location.spine_index, recipe.provenance.location.start_block_index)` if those fields exist.
  - If only block ordering exists, ensure it is stable and derived from spine ordering.
- ID rewriting:
  - Use the existing EPUB ID scheme if one exists, but rewrite to sequential suffixes (`c0..cN`) in merged order.
  - Build an `old_id -> new_id` mapping and update all references:
    - recipe-specific tips’ `source_recipe_id` (or equivalent field)
    - any provenance `@id` or `id` values that embed or reference the old recipe identifier
- Tip recomputation:
  - If the pipeline partitions tips after extraction, run that partitioning on the merged candidates once, in the main process, so “general vs recipe-specific” is consistent.

Raw artifacts:

- For split jobs, the worker should write raw artifacts to:
  - `{out}/.job_parts/{workbook_slug}/job_{job_index}/raw/...`
- The merge step should merge these into the final raw artifact tree, preferring deterministic naming. If collisions occur, prefix the filename with `job_{job_index}_`.

Output writing policy (important for consistency):

- For split EPUBs, only the main process writes the final workbook outputs (intermediate drafts, final drafts, tips, report).
- For non-split files (including non-split EPUBs), preserve the existing “worker writes outputs” behavior to avoid slowing normal multi-file parallel runs.

Proof:

- A split EPUB run produces:
  - One workbook slug under `intermediate drafts/`, `final drafts/`, `tips/`, and a single report JSON.
  - Sequential recipe identifiers in the merged output.
  - No `.job_parts` directory remaining after success (unless configured to keep for debugging).

### Milestone 6: Tests and documentation

By the end of this milestone, the behavior is protected by tests and discoverable to users.

Tests to add (prefer unit tests that do not require real EPUB files):

- Job planning test:
  - Given `spine_item_count=80`, `workers=4`, `items_per_job=20`, `overlap=1`, assert you get 4 jobs with owned ranges `[0,20) [20,40) [40,60) [60,80)` and slice ranges expanded by 1 on both sides where possible.
- Slice filtering test:
  - Create synthetic `RecipeCandidate` objects with provenance spine indices spanning the overlap boundary, ensure the filter keeps only those in the owned range.
- Merge ID rewrite test:
  - Create two or more synthetic job results containing recipes and recipe-specific tips referencing the old IDs; after merge, assert IDs are sequential and tip references were updated.

Documentation updates:

- Update CLI help for new flags.
- Update the same docs that describe PDF splitting to mention EPUB splitting and the “spine-range job” concept.
- Document `.job_parts` for EPUB (location, what it contains, and when it is removed).

Proof:

- `pytest -q` passes and includes at least one new test file covering EPUB splitting.
- The docs mention how to tune `--epub-spine-items-per-job` and warn that overly aggressive worker counts can increase RAM usage (important for users on smaller machines).

## Concrete Steps

All commands are run from the repository root.

1) Find the EPUB importer and current conversion flow.

    rg -n "class .*Epub|EpubImporter|epub\\.py" cookimport/plugins
    rg -n "def inspect\\(|def convert\\(" cookimport/plugins/epub.py

2) Find the existing job splitting framework (from the PDF work) and identify extension points.

    rg -n "Job|job_parts|pdf-pages-per-job|merge" cookimport/cli.py cookimport/cli_worker.py cookimport -S

3) Implement inspection spine count.

    - Edit `cookimport/plugins/epub.py` to compute spine count in `inspect`.
    - Edit `cookimport/core/models.py` (or the relevant inspection model file) to store spine count in the inspection result.

4) Implement slice conversion with overlap and owned-range filtering.

    - Edit `cookimport/plugins/epub.py:EpubImporter.convert` to accept the new keyword args and limit iteration to the slice range.
    - Ensure block provenance includes absolute `spine_index` and a stable within-spine block index.

5) Add CLI flags and plan EPUB jobs.

    - Edit `cookimport/cli.py` to add `--epub-spine-items-per-job` and `--epub-spine-overlap-items`.
    - Extend the job planner to create EPUB jobs using the algorithm described above.

6) Add worker execution support.

    - Edit `cookimport/cli_worker.py` to accept EPUB jobs and pass slice bounds into `EpubImporter.convert`.
    - For EPUB slice jobs, write raw artifacts to `.job_parts/...` and return a light payload.

7) Add merge support.

    - Edit the merge logic (where PDF merge happens) to handle EPUB jobs:
      merge results, rewrite IDs, update references, merge raw artifacts, write final outputs.

8) Run tests and add missing ones.

    pytest -q

9) Manual verification on a large EPUB.

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/large.epub

    Expected high-signal log lines (example, wording may differ):

      Processing 1 file(s) as 4 job(s) using 4 workers...
      worker-1: cookbook.epub [spine 0-21; owned 0-20]
      worker-2: cookbook.epub [spine 19-41; owned 20-40]
      Merging 4 jobs for cookbook.epub...
      ✔ cookbook.epub: N recipes, M tips (merge X.XXs)

## Validation and Acceptance

Acceptance is met when all of the following are true:

1) Split run produces parallel job progress and one cohesive output folder.

- Running:

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/<large.epub>

  shows multiple concurrent jobs with spine ranges, followed by a merge message.

- The output directory contains exactly one workbook slug for that EPUB under:
  - `intermediate drafts/`
  - `final drafts/`
  - `tips/`
  - and a single report file.

2) Merged identifiers are stable and sequential.

- Recipe identifiers in the final merged output are sequential (`...:c0`, `...:c1`, …) and do not depend on whether splitting occurred.
- Any recipe-specific tips reference the rewritten recipe IDs.

3) Overlap does not produce duplicates.

- The final merged output contains no duplicate recipes caused by overlap slices.

4) Serial fallback works.

- If `ProcessPoolExecutor` cannot be created (for example due to `PermissionError`), the CLI logs a warning and processes the EPUB as one non-split job, still producing a valid workbook output.

5) Tests cover the new behavior.

- New tests fail before the change and pass after. At minimum:
  - job planning ranges
  - owned-range filtering
  - merge ID rewriting and reference updates

## Idempotence and Recovery

Re-running the same command is safe because outputs are written into a new timestamped folder. If a merge fails mid-way, the temporary job folder under `{out}/.job_parts/` remains for debugging. Re-run to regenerate a clean output folder. If a job fails, the merge should abort for that file and write an error record, while allowing other files in the same run to complete.

If splitting causes unexpected extraction regressions on a particular EPUB, users can disable splitting by running with `--workers 1` or by setting `--epub-spine-items-per-job` to a very large number so the file is not split.

## Artifacts and Notes

Keep the following evidence snippets here as you implement:

- A short `pytest` transcript showing new tests passing.
- A run transcript showing split job progress and a merge line.
- A tiny excerpt of one merged recipe JSON showing `identifier` rewritten to `...:c{n}` and a recipe-specific tip referencing the new ID.

Example (replace with real output):

    pytest -q
    ... 128 passed

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/large.epub
    Processing 1 file(s) as 4 job(s) using 4 workers...
    Merging 4 jobs for large.epub...
    ✔ large.epub: 312 recipes, 28 tips

## Interfaces and Dependencies

You must end with these concrete interfaces (update names to match the existing job framework you reuse):

- `cookimport/plugins/epub.py`
  - `EpubImporter.inspect(path) -> WorkbookInspection` (or equivalent) must populate an integer spine item count field.
  - `EpubImporter.convert(path, mapping, progress_callback, start_spine: int | None = None, end_spine: int | None = None, owned_start_spine: int | None = None, owned_end_spine: int | None = None) -> ConversionResult`
  - Every produced `Block` must carry absolute `spine_index` in provenance location (field name to be chosen and documented in Decision Log).
- `cookimport/cli.py`
  - New CLI flags: `--epub-spine-items-per-job`, `--epub-spine-overlap-items`.
  - Job planner must create an “epub spine slice” job kind when conditions are met.
  - Merge orchestration must recognize EPUB split jobs and write one workbook output in the main process.
- `cookimport/cli_worker.py`
  - Worker entrypoint must accept EPUB slice jobs and return a mergeable job payload while writing raw artifacts into `.job_parts` for those jobs.
- Tests
  - At least one new test file covering EPUB job planning and merge ID rewriting.

Change note: 2026-02-01 — Initial ExecPlan created to extend the existing PDF split/merge job framework to `.epub` spine slicing with overlap filtering and deterministic merging.
```

## docs/resource_usage_report.md

```markdown
# Resource Usage and Performance Report: cookimport

This report provides an analysis of how `cookimport` utilizes system resources and outlines strategies for increasing its share of available compute to accelerate processing.

## 1. Current Resource Usage Profile

### CPU (Central Processing Unit)
*   **Status**: Underutilized (Single-threaded).
*   **Behavior**: The program currently processes files sequentially in a single loop within `cookimport/cli.py`. This means only one CPU core is primarily active at any given time.
*   **Load Type**: High-intensity "burst" loads occur during text extraction (OCR) and NLP parsing (ingredient/instruction analysis). The CPU is responsible for coordinating model execution and managing data structures.

### RAM (Random Access Memory)
*   **Status**: Moderate to High.
*   **Behavior**: Loading deep learning models for OCR (`docTR`) and NLP (`spacy`, `ingredient-parser-nlp`) requires significant memory overhead (typically 1GB–4GB+ depending on the models).
*   **Peak Load**: Memory usage peaks when large PDF files are converted to images for OCR processing.

### GPU (Graphics Processing Unit)
*   **Status**: Potentially utilized but unmanaged.
*   **Behavior**: `docTR` uses PyTorch as a backend. If a CUDA-enabled (NVIDIA) or MPS-enabled (Apple Silicon) GPU is present, PyTorch may use it for OCR detection and recognition, but the codebase does not explicitly configure or optimize this device allocation.

### Disk I/O
*   **Status**: Low.
*   **Behavior**: Reading source files (PDF, EPUB, Excel) and writing JSON-LD drafts is generally fast and not a bottleneck compared to the compute-heavy parsing stages.

---

## 2. Strategies for Increasing Compute Share

To allow `cookimport` to process recipes significantly faster, the following architectural changes are recommended:

### A. Parallel File Processing (Multiprocessing)
The most effective way to utilize a modern multi-core CPU is to process multiple files simultaneously.
*   **Implementation**: Replace the sequential `for` loop in `cookimport/cli.py:stage()` with a `concurrent.futures.ProcessPoolExecutor`.
*   **Benefit**: On an 8-core machine, processing 4–8 files in parallel could theoretically result in a 3x–6x speedup for bulk imports.
*   **Note**: This will multiply RAM usage, so the number of workers should be tuned to the available memory.

### B. Explicit GPU Acceleration
Explicitly directing the OCR engine to use the GPU will offload the heaviest computations from the CPU.
*   **Implementation**: Modify `cookimport/ocr/doctr_engine.py` to detect and pass the `device` (e.g., `cuda` or `mps`) to the `ocr_predictor`.
*   **Benefit**: GPU-accelerated OCR is often 10x–50x faster than CPU-based OCR.

### C. Batch OCR Processing
`docTR` is designed to handle batches of images efficiently.
*   **Implementation**: Instead of processing one page at a time, group pages into batches (e.g., 8 pages) and pass them to the model in a single call.
*   **Benefit**: Reduces the overhead of transferring data between the CPU and GPU/RAM.

### D. Model Warming and Caching
Currently, models are lazy-loaded on the first call.
*   **Implementation**: For high-performance runs, "warm" the models by loading them during application startup or keeping them resident in a separate worker process.
*   **Benefit**: Eliminates the 5–10 second delay encountered the first time a file is processed in a session.

---

## 3. Recommended Configuration for High-Performance Hardware
If you have a high-end workstation, the ideal configuration for this tool would be:
1.  **Workers**: Set a concurrency limit equal to `Total RAM / 3GB`.
2.  **Backend**: Ensure `torch` is installed with proper hardware acceleration support (CUDA for PC, MPS for Mac).
3.  **IO**: Run from an SSD to minimize latency when reading large PDF/EPUB sources.
```

## docs/step-linking/README.md

```markdown
---
summary: "Two-phase algorithm for linking ingredients to instruction steps."
read_when:
  - Working on step-ingredient assignment
  - Debugging ingredient duplication issues
  - Understanding split ingredient handling
---

# Step-Ingredient Linking

**Location:** `cookimport/parsing/step_ingredients.py`

This module assigns each ingredient to the instruction step(s) where it's used.

## Algorithm Overview

The **two-phase algorithm** solves the ingredient-step linking problem:

### Phase 1: Candidate Collection

For each (ingredient, step) pair:
1. Generate **aliases** for the ingredient (full text, cleaned text, head/tail tokens)
2. Scan step text for alias matches
3. Classify **verb context** around the match
4. Score the candidate based on match quality

### Phase 2: Global Resolution

For each ingredient:
1. Collect all step candidates
2. Apply assignment rules (usually: best step wins)
3. Handle exceptions (split ingredients, section groups)

---

## Alias Generation

Each ingredient generates multiple searchable aliases:

```python
"fresh sage leaves, chopped" →
  - ("fresh", "sage", "leaves", "chopped")  # full text
  - ("sage", "leaves")                       # cleaned (no prep)
  - ("sage",)                                # head token
  - ("leaves",)                              # tail token
```

Aliases are scored by:
1. Token count (more tokens = stronger match)
2. Character length
3. Source preference (raw_ingredient_text > raw_text)

### Semantic Fallback (Lemmatized)

If an ingredient has **no exact alias match**, a lightweight lemmatized fallback runs:

- Rule-based lemmatization (suffix stripping + small overrides)
- No external dependencies
- Curated synonym expansion for common ingredient names
- Tagged as `match_kind="semantic"` and only used when exact matches are absent
  - Note: "exact match" includes head/tail single-token aliases

If the ingredient is still unmatched, a **fuzzy** rescue runs:

- RapidFuzz partial ratio over lemmatized text
- Only for unmatched ingredients, with generic-token guardrails
- Tagged as `match_kind="fuzzy"`

---

## Verb Context Classification

The 1-3 tokens before an ingredient match reveal usage intent:

| Verb Type | Words | Score Adjustment |
|-----------|-------|------------------|
| **use** | add, mix, stir, fold, pour, whisk, combine, toss, season, drizzle, melt | +10 |
| **reference** | cook, let, rest, simmer, reduce, return | -5 |
| **split** | half, remaining, reserved, divided | +8 (enables multi-step when strong) |
| **neutral** | (other) | 0 |

### Split Detection

Split signals trigger multi-step assignment when they include strong language (explicit fractions like "half" or remaining/reserved terms):

```
Step 3: "Add half the butter and stir."
Step 7: "Add remaining butter and serve."
```

Both steps get the butter ingredient, with quantity fractions:
- Step 3: `input_qty * 0.5`
- Step 7: `input_qty * 0.5`

---

## Assignment Rules

### Default: Best Step Wins

Each ingredient goes to exactly one step (highest-scoring candidate).

**Tiebreaker:** When multiple steps have "use" verbs, prefer the **earliest step** (first introduction of ingredient).

### Exception: Multi-Step Assignment

Enabled only when:
1. Multiple candidates have "use" or "split" signals
2. At least one candidate has strong split language (fraction/remaining/reserved)

Maximum 3 steps per ingredient (prevents runaway assignments).

When a multi-step split is used, each split ingredient line has its confidence reduced slightly to flag it for later review.

### Exception: Section Header Groups

Ingredients under a section header (e.g., "For the Sauce") are grouped:

```
For the Sauce:
  2 tbsp butter
  1 cup cream

Step: "Make the sauce by combining sauce ingredients..."
```

The phrase "sauce ingredients" matches the section, assigning all grouped ingredients.

### Exception: "All Ingredients" Phrases

Patterns like "combine all ingredients" assign every non-header ingredient to that step.

---

## Weak Match Filtering

Single-token matches (e.g., "oil") are **weak** and can cause false positives.

Filtering rule: If a weak match's token appears in a strong match in the same step, exclude the weak match.

Example:
- "olive oil" (strong match, 2 tokens)
- "oil" (weak match, 1 token)

If both match step 3, only "olive oil" is assigned (weak "oil" excluded).

---

## Debugging

Enable debug mode to trace assignments:

```python
results, debug_info = assign_ingredient_lines_to_steps(
    steps, ingredients, debug=True
)

# debug_info contains:
#   .candidates - all detected matches with scores
#   .assignments - final assignment decisions with reasons
#   .group_assignments - section header group matches
#   .all_ingredients_steps - steps with "all ingredients" phrase
```

---

## Key Discoveries

### Duplication Bug Fix (2026-01-30)

**Problem:** Ingredients appearing in multiple steps when only one assignment was intended.

**Root cause:** Greedy per-step matching without global resolution.

**Solution:** Two-phase algorithm with "earliest use verb wins" tiebreaker.

### Fraction Calculation

For split ingredients:
- "half" → 0.5
- "quarter" → 0.25
- "third" → 0.333
- "remaining" → complement of previously assigned fractions
```

## docs/template/AGENTS.md

```markdown
---
summary: "Explanation of the final DraftV1 recipe schema used by the application."
read_when:
  - When modifying the DraftV1 schema
  - When investigating how ingredients are linked to steps
---

this is the final output, this is what the cookbook app uses: 
  
  The schema includes:                                                                       
  - All fields with types and descriptions                                                   
  - Conditional validation for quantity_kind (exact requires qty+unit, approximate allows   
  both or neither, unquantified forbids them)                                                
  - UUID pattern validation                                                                  
  - minLength, minimum, and default constraints matching the Zod schema 


  Pancakes.JSON is an example of a real recipe in my database, note how the ingridients are tied to a specific recipe step.```

## docs/template/Pancakes.JSON

```json
    1 {
    2   "schema_v": 1,
    3   "recipe": {
    4     "title": "Pancakes",
    5     "description": "Quick stovetop pancakes with simple pantry staples.",
    6     "yield_units": 4,
    7     "yield_phrase": "4 servings",
    8     "yield_unit_name": "servings",
    9     "yield_detail": "About 8 small pancakes",
   10     "notes": "Rest batter for 5 minutes if you have time."
   11   },
   12   "steps": [
   13     {
   14       "instruction": "Whisk together dry ingredients.",
   15       "ingredient_lines": [
   16         {
   17           "ingredient_id": "00000000-0000-0000-0000-000000000020",
   18           "quantity_kind": "exact",
   19           "input_qty": 200,
   20           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   21           "note": null,
   22           "raw_text": "200 g flour",
   23           "is_optional": false
   24         },
   25         {
   26           "ingredient_id": "00000000-0000-0000-0000-000000000021",
   27           "quantity_kind": "exact",
   28           "input_qty": 25,
   29           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   30           "note": null,
   31           "raw_text": "25 g sugar",
   32           "is_optional": false
   33         },
   34         {
   35           "ingredient_id": "00000000-0000-0000-0000-000000000022",
   36           "quantity_kind": "exact",
   37           "input_qty": 1,
   38           "input_unit_id": "00000000-0000-0000-0000-000000000011",
   39           "note": null,
   40           "raw_text": "1 tsp salt",
   41           "is_optional": false
   42         }
   43       ]
   44     },
   45     {
   46       "instruction": "Whisk wet ingredients and combine with dry.",
   47       "ingredient_lines": [
   48         {
   49           "ingredient_id": "00000000-0000-0000-0000-000000000024",
   50           "quantity_kind": "exact",
   51           "input_qty": 300,
   52           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   53           "note": null,
   54           "raw_text": "300 g milk",
   55           "is_optional": false
   56         },
   57         {
   58           "ingredient_id": "00000000-0000-0000-0000-000000000025",
   59           "quantity_kind": "exact",
   60           "input_qty": 50,
   61           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   62           "note": null,
   63           "raw_text": "50 g egg",
   64           "is_optional": false
   65         },
   66         {
   67           "ingredient_id": "00000000-0000-0000-0000-000000000023",
   68           "quantity_kind": "exact",
   69           "input_qty": 30,
   70           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   71           "note": null,
   72           "raw_text": "30 g butter",
   73           "is_optional": false
   74         }
   75       ]
   76     }
   77   ]
   78 }```

## docs/template/examples/Broccoli Cheese Soup1.paprikarecipes

_Binary file; base64-encoded below._

```base64
UEsDBBQAAAgIAINcJVxUkyjJnlYAAJRWAAAiAAAAQnJvY2NvbGkgQ2hlZXNlIFNvdXAucGFwcmlr
YXJlY2lwZQAGQPm/H4sIAAAAAAAEAKS6eY/rSJY99lUSDQzc82NVc9/a8B+SKJLiLu6i23jgvu+r
6C/vUL5X1d2eGcCAC5WVymDwxo27nHtOZf7ff1nL5C9//wt3YWgEw8jfMe6K/k7QHP87Q6PE7zRB
3FCOv92ZC/eX3/4ST2m4pJ8XMATDf0eR33HkC6X/jpB/xxnwvAjnAjzk+fuVuJIXhMPoC4Fcrpcb
Sl9uGMni1BVlbwzOk/yNu1BX5na9EghFU/Ttzt1xjuE4AvtY6sI2BZauUx/HfVN+3Yo0ndMvq18H
8DRJ53gqh6XsO7AJLJRdPqVJmXbLDBbQLxTGvoZ+7ZL56680guT/+RX9svSPDvtawqhJ56HvO/AY
R9rmP7+2NE+/l7/6svlHJ/dzkU5fc9gsX2GXfGVTOhfN+yufPka/oiaM668hHYZ0+keH/7tBggTH
rd3n3RRsXZflswn9aoGDa/vVd8Dr377mpozB47+GUb8uX9QXsBun8/8Oogm8/ZftcThN/fIbOCxt
wP5vZ8ouBb4k/2qA+KcB7NsA/qeBpt/S+SsPJ3Dib19LUXbg5Z/Hf4IRr8PHaZr8hGEH6Z1+++qn
r6Jv0zZM0s/neemn9HdwTl4sX02//z73P00XZVyn3ed5XH+O/GkLBPzbVtGDcLZlU3+uM7dh03xN
6zynC0jNEi79v13q3+PxX66DYr9WQMKITz7nIpwG4EGaJOH0+Q7K4zeQn099fv11TtOvrl/SGbzK
/Pkm9v1mkjbl7/PyBs5d2nQq47D78/1fMf3X19GvJQ2/cwuOBq+367yEUwLusCefxHKg5r/6DARs
AfWyxsDKvMbFVzh/8VPY1f/b/GWmidgvn7otpzT+VO2nSq10CD/u/lmaX2W39F9ZA4K9zD+DsqTt
/LevG4jIH8vfe6JySX+fyzP9Gsr0c7XvzSCw4Vwm6d++zE+qQJbjoh9+GvneAYo4nbYU7Px5cvP+
2z+6f3QiaOpP2QPbX+FXE055+sWtC7gDqJzu8x9QDmVefBWfjWu3gK1zUbaf4HX5374uSfLPO/yr
+3Hf17997eVSfHLa9hvY/tsvAzHIH2hZ0A6gJEEM+mXp29++fqYfVH/ZrQu4ibWUoB5nkAGw8WPp
nz35s/1++3USMNqt6feR36fM4MWPe1/ALxCVvgPl9/7j8CXtQO5+vvlPP+YU3DQEd1unLARR/X97
A0q/y9Ppb182yOucAQMgFeHX9IkEiED4ORgEJgV5AA+AJ813eM10WafuXyMKnv5qzu+IftwIkz+g
4rc/EOKPzv88/jO8vyrC+p8D8i+R/zMGAL7GFYDjf4kAOPJT6B/7e5cmf9yY/HVjEALQ7t9p/ulq
mX11n4Kbw+n9M/E/ceW/OfSPk7IpBF3ZLX/YBhNjTkG+kvk7Oh8b36jzAZp/A5TfvrHj5/1/Asav
UHy8+Y589Cnafy/Pv32aDTThrw3hBKr9u1L/u7D8d6XxZ6T/9djpU1jt0KSfnvkVu3+5z69gfd/n
8c8eivq9AYDbz/OnvItfIDODFTBrPuMl/BTUzyT+O6r87cuZPw4CZPp2/uMkGDo/cwbitPfTd7GB
ho1CUFbA6LeVELgJrpFOC+j7X/t/+/nhawaj87dPnX1e/OkK2F+Aa2Zr8/Upw6+lbNM/+/Of953b
Hrj/sxc/R/6JdL9g57sUQZiWEFTnf1uT/3z3FwT9D4AxrM38y8Iftw2/snQH2AFS8HFv/uXez+U/
0G/6BtFP5SSgjn/7Luu2n5f/CpQTGGpl92mgDxB+d275Ewk/pOMD+T8JBUjoVC7ftfGj7LIerP71
01wf70EAwVygUPLrBjI4lcAsQeRfPIghxuZgcYpmUBb5lwH6Ny1BUWh/WAOb4mX+R2f9NDP//YsC
LdB+kvb1L+b/0f1pGRzzj+4/vriwBJlww2ZN/9c/OhvUZfN94OdgkvoPYDEEKPM9/L79wPMvFCXA
+u0zhUFepr4BK2Sbf+HMZ/vPCY6SCAuWqI+Fn0Y/3vfFO/meTJ/roAh4xpWAHU3vL76MgJckWGX/
fMNaAQbMXygO3P5148/t/9G55RKC1vi6fTEoOIRA8P/4vlj8fTJK0mCR+dh5TCAyWPtxGfxkAKvz
/NnDEp/3sI8D/8sGQ+LfwvD1V879T9CLTTN/vfsVVCUok+/B+/WdPAB3Pwda1vfJH4H9HhRTGX3a
9SdEJN8WAXUE0IH9hiAIwN1fof88fH+VoORmENYM9F2edt8T4s/qAP20AcrwKZ5hSocfnxIFpfKN
n/OHMAPA+XMR+WN1+cTtj+VvWpBlZbw2y/vnz7+c/ZQi9fXnD7/9BeQEfPrL3xGwpV+nOP1mEVPZ
AwfDZf4b6Nm//PHoxzo14HGxLMP8dxje9/1v879vhf9owd9/sajff6LC7x+k+P0Ttd+bMPodMJZy
SD8XBH3/6QMK4a4kQaG/X1GU/p3gLkArMBj6O8eR7IVnAOm/0H+rhvyPV358o+Ff/t6tTfPH0i+h
QCIofbtiF4ogOfyG01eEJW93Er1RNEJSOMahLMETBIvdEB6nwL93FggUoCQwGuc4hPww/zbM/79c
dinaCC5SU1SJDrfJH8eGPFJ1b011pDCWvf8fMOgF5EDgrAS8fZr/3vU/AJsFxZD+9T//3obHj+gN
iuavn10I8p9/n0EFDD/KOP7rf8I/fvTD8uPH9zwAZ/34EffpOv/4AcDuOxfzZwXAcrf8aMsPRQWV
8+PHLw9/fFz886c//P28/Ik7ePJ9Q/AdQ1Dqxw8U+fkJRRDm9/+Swe/UARkXkVRGhQmNMSFJMCgS
YhSOEiFFZDiGZAzyKz8xaPL8u9j/8vf/8//6IzlJuIQgmjBbwcTl8rTqQDJzIOKe94t1uT4uFw7G
9it3uai3S/79xV129f75uj5z/vp8gu+9eN1fD+7Sg4ezfNtnjSseT+5JmFw+K/fr63k3VYc3HRdo
T1+4vhzh+gA/2z9tP4GtiwPs1MBe7XDPWQMfnP9/Xza8Xy7m7XJ/Xcycu1jgKgU45rhfYeZ5EcHD
y9P53PP7rv/853677E/+mseP27NXPnsXEyznd3DvB7g3MH15ggWevTzBlS9P82o+CtW5C3eUL65v
6eA5+VqH98cDkY/ddC0ku9QqJr3zvJb5In4JZt9IZdzLVo9o9gvXuZp6IiZv1snDcgbb5V3PRYvA
a7U68IIuFJoxxk006RIi9UcQWk8oiFIqB9luJM9ryDJoR7kaZK8dqHIYJ/lcFA9b6JJcZ4U7VF84
mEp6L4qNar6HslWArWJJQHZDrllPpdPBbAbCZhEOGR31Mz4gJvv9j/j8vPL/GJ/7Jz43sAn0a/wz
Pk8J/9573O9X635cC+nqPJMiNtVS7e8P/i6bfSReb5Z6OtvFfXWKeStetabfG8b8jlELIjbIlYNp
Z07qtXY3nUC07o3soKbrNsnLc4cqENw2wIoh7DQk8QM8FRsq7/V78QrF8tHK9aA7TRD6rdSG/ajX
Qxh2o9yO86QjSxTiq9JS+2zcjzgS32onI4vhoEnkY1oXEqtRk2nUUXo3/lt82P7CXdTr5fIwwf0u
xs5RNcSt0xJ7zCv10zix/YUJC8SpunKr6F0khugZnZxR3GKUFdJ7JpThccvNBZMpb1JJ4H/w3vMx
Rk9sToVX4lSB1eshuljoNUoRtSCI01dDnyCXYDqIDXSTXU3m69SVbctpUUuj2g5VdqSiZ1a4XDSu
rNpRLq7qi1eNguR0FELZhx9gFLzfZierXC+LR7I9Mg7C7i+xUdqZO3jiVnlaxd8v2eBbBvNUJO8g
3yS02AoxzPRhQqwDN2bA3qKuIpgHjne8yVftmiPdzhvyu30xaZPAYuo5c3txJXZ2RyV+eoxHXJxp
BieGIuGUCCMnq84mMkqKr4MAxXJbeeYJ38c34lpS4Np86kKqUTV3RCnRBl+qKgyT0kaBD4yp2NbL
f725WMfSkLjhkHpvyFE+JgE7KpbaLlF3HAl1xK1FNRL55qcUMbymWu+1cd6m2WiM6dzp8YnecPMd
k3zUOy9iettEBqkPSUnVK6R30oSmx/agW5W310k/pBJ6LJwHFREZk2Czn3Hz2p7qG9wlRuklsSRh
O7PGE1Mquo5hHT1DPgmbaU4fT0ulo0sVbTYfIkLhqxRdCCErLPCF3URtxThj8k0szTEGlD8ijCSm
Uybhp6Gdeqv1ai9s4coC1ZURmZtsCOX0+YxSTyWfIiMzMxNTVlNOi9CLyDBmsSJ1eoYhDxcKRt+G
eUSbMvmsG6AmydYDhT+sXBEuWFrkLyVf2PDd+cOBB4tQ6N7b6Ll9IYBOf+b227/qepNYCzIpp59v
RQvZT/x9c69gMK1Dxt/QZYrElozTJr4zSUFQzDGJV7SlJbEXFq/W0EjrRGsT2HANNB59lHKQt9ma
o3W4MHFUar4lXwd9p11ymfzjsrHWWsm7Z2CAEguPc22u2bp4QEkx42hlGy0i134r31rvSvWOryHG
EVReCRohTWSDwIcrn9wpeRF23WWqsre7NV8ZHBiLZ2o8IfFJD0EkgAuM3XGJrszgaXE2dlXm+Gex
5JMYuVftXIlxid/KYyDfIRG2yuRqpIAaHEJkwS06rgCVjdZa8aUrR4eprEoPJ0vk7lzZDcpx+p1u
N+uHdM6ad22jpgzltqqhKHcc9kq14gDv+UoXoL1ft82Hr36hGVyyruZbpuTI0/T5yNUclgdaZ3LU
jE3eGlgK9jT2JC7keQTTnUFn5n6bvcfhVw05CBPGEyCeweUUpaPdBll5Rgm3xgG0BO3kQd0TpnYz
T1k3qUcAJOGZPsh+v3iXMYzMJK4rxZAedoVPCGV4mrBgN5pg4MJbIt/rfCbl5Y56DfEpBuKZjeiR
hv4jWwQmoz3bvWZCzW57swOMSVIC0rfLrI9eXFTP4MD4TMtKcafT0MisBxK1hnG9TJZaxAMtMUoS
ghSvLFPTq8qe/uwt/oStTV1JL8XP/V1bBYZ+ve+vaFVdVtgGQHPGC66bXrwc0wuyNtGb/LUPUVVy
a2bhmG3wjdRSRmNg0MwRS5uIsBpR67z0E5RyGQiSF0UoqfFFHHna+DyOCHGhDEyttk/OhW1yiJLc
rCtkSmZNi5xyLG6gqKZt47K96NBrEz7vchZOyHNqr0SApvSC+bTqSREkbP1JpDhKa8GxxKMbiY9J
ZFT4pgM6N55mPhvh9nxFumJNfvFUb32jzCaqwkcyWZjWn/T6NLyZ2ztiK7eiOy9p5q0GcymbyUWT
hW2WmHwRkDfbe9ajdEBk8dNGp2IkxsaEpM61d4RqR6PnNa/AigV16eqQOK7j3F1uGfUlMMhJi+oB
p9biN6iK+Ng9qdXbtqj0jWBeUnUJwYFPe5muD1JG5aYThrOSWKrdRy53ycQW3XFtaDGwdxZMyTqm
xX5rplqCkgfWrVsWGuHCttdRWjYwonRnMNwu7qJAVHG360YrfCuTvbtRue5rlHjiZSyk8Lr2U93c
qcdpGJqF1EtdxFnhS1Q33GtTukyYFVloLF4mESRib6+Qt4auNtNykjWGsOG18trNcrmh6JWYRS1Z
4vR6qvgtG+w7JMZVtqPH2jnegaf4AHRrNqyTYD5VdNktwcy8njAu6HGJ5QGW1xYMtg4cpkYA2FHN
lUJPDwe5Xpzz5tuBVO23EFH8nX3gDhiaCZUQZk282ysLmvhkpPoFtERn75o3IIbRlcST6trZKFzM
ESPTn9mOCMDZE9TwaSdKYd0kHaeodReIB5+m2mKvmJRSr8xaCUgUD0to10f0JnQTTrWUz7Dce2Ua
tIDyvA1v7vTxyj3J8mBb3D+i+T6zBEB2CiUyAtS7i48LRmHJ/j4uTBMytT7Z+mqokQixNgj7rDbb
2VuzfMx2KrF2aGfs2CgBG7IKJGQV52VL7cSUzgQG1xkAUWniiUCKu7zKqpFLQ7esEGphLq1Cbki7
422de//UhwdvK7MmKQ59mqRBW7PL7IEuv9kXJLLdGCjafZDYceiIPuU1rnw0aIpWbrpSrunZSbbo
GYcdkucf/Gs04f2qNT3pPQHksb2YeziiR5kojNWWuxg7SXwu32QGDB52OolIuhEVY2KRatBzPuWv
DDuNWxjOLrxYCq118IVviRewV8S4mnlCj2VYi8sT5ZLKhO8VwGIzTGYG5XuDdrtccXpUhG8m9pDg
InzdVgzpCCS9a06QSeh4NCectA6MDlj2bCl12ztGUjJb4gMEF1EtrT22C6iIgy+XKpTJ0zNKc+Cb
UJPE9NnE2T7LDGhpYvT1ydKbTr10T60t8TidMCNWpiMIvAGDwh4WZs4zgEBAIoUcSWPzz2psRx9u
BS9k4hjEieZND5q3R59MQyf2HjFVh2Y6hIbrMPdKXc87aG4pUJkI40yrwahDlfjA4B6QCmQjco8d
xx5pL7q+WNTAmFMyuZvSXHTD20qqAba7MXMchnMwa66Qzt14dxiSEaksZVcBbe0SlvEHSamiaNcp
EmLLTU+eTGjitkbWpxWzl/RqLRPasQ3XPzlosdpOPA17IK4mpDhsBoJbmvaRn90rYy5gxlZMjMV0
4dZumaVbh4meqdJzcBsrnJheSOdNYZA/yOsGe3NYOXyMepfiwR4tYz2ry3WcsVUwt/qqpRbelZ6H
126CESQxZYxGHSnuvNWXp5pUXQFfGz8evGqOMidMdI0UI2UiceJ1z7yhQQfBqasLG5b+E10lvmli
WaCTEVWqJx17HnKPKxpNqMFOZzuvqVsyCRk/mQFzTfbx3U7PaLYeKuohuEV7QpBLDGFMDoPWHZar
07UZ4hoVaFOpzHh6IJNHzEFz5rcFt2nh3R1F4Yt+HXrUdVlRnX3uVH0r+Onx3rA9dhxqHN6bUyRC
zMhjyb7dCi1PRseq1+PWLpYICKTR97C8AYUDSdiWilIjoINzpTTKxbASFoQ0RKumy486rgwtJQsG
edOhRfpkz2Bbo2sVjfiJCCaW6mRm7MrjMW7h+iggqeniZ9FGrzgDFNg/CjGZWokhKcCUfRQ0D1pJ
KpN6t8PAiJnOaPOek49+KjP62XZwRbCjvKehCb1zj8vcjjzmg9DUFhXQhT8VeYSwkHkxLizK+Exg
VVXfurknDdIlNcAhPTTzxNdTfT9sllxDtnUtVcPi26YEIkJP4iEjndUElZ4fNLoLS7aIntDNew5n
9wxPQyiNypBFpYVFY0OCN7Fixrwpy8qfVi1GAHTIJRywWLriGw1gqj/gecWZZj3nkOw8o2I/aubW
BEuyPvoTvgH/1gtx7nIs3eR3kg6Al2CxPvS4Xyr+RJZR5wJB0k2tg3YW0BJZtkkdNLUNQybYLdT2
ZM4Z19A0ejZi6lF5/LKpSGGsx+AURggw8XI6i9c3rnN68aAJJZCXiG3vS6OUAUer4WpCjySYPe4Z
DvFBUJke2tF6fezhdAY0eH90gjelSrLhim6YMKEhrK08DpODvDmIx3WZ3nYaQg9iRPxw2cEEN8wZ
JWpMZZxu8LpFYt+6Z4QH60sQZl+npF+2tGd7UrhBHFCf6W2ruJf/7t6s5zkG4raAhj31LmiG2Wg9
poWwtl7AfHirgNaht4kJ9XfljY4mR4ix0u5Wulp0GrmKpPpte0x8C0kIs0zS3OwHxWmZDOUwb/ss
FzhdRmdRlY+wL6ITwllZafZGKasKWcwKvtY5oOiVO88kfjqAKQ6z0jkPiPYqcIAPGN5xWYXVqo+T
tX3HIPZgg7xWTdmUsy2/6R7LKWRaSevdY8RFomlWkjd9udNS0xlcOWbdFzT0gGeGhsbjxkDvFVEu
w/Q6cG608Cc5DYmBrHgYWx5TXS4og4bchB7Be1gzXWZrRoUMNMUtnhcYhh/tepBPTbwODMKhaCJ7
JNMgUFCg0zgY91soDv1zJ15cDhB+uy0Ii1435uwWP6SyYUADU4xNuofpYzpQYXi2kB90hl/d+i1L
j5OBD7W+SVv7vp7oIGXVdTHduvF0lfUk6gZ0EqBOS/++RtoyF6LO+e+JcVmecSlfk5tNebDzpvOA
baHUewkoIRFvSNhOxqSLxAFeNVo1whmAlnF9XUNKNLNS6dtZzPg0TlBpYpZqROHQj24fgUqcLLPk
5WYbV1CXr+XJqFi/TIBG58FbimHNd9ZASQmq5Qq2hk2PYnyMMhv3pfGAF8VuBl+uMQLbrHUz5d4R
uQ6ZSG/bsFIAmr8oF6VSXlAgj3ZqCKiMK8olwdSu08OzJX30MRCW7A1sdKb6I8ICMQqUyIpJVsYX
LX2jwRNx9/sFLs7Df/vEFdIsQYjsacSxt7TnkWDJrDQbwlAXNtADRfuCAel8Fzc7QaK10W9uhWMh
6r4yNozTXosNYmUCX8j3san00xfoPCB6BD9m5XZWxTa3lvMSaMDetE9L2VI6ju9jjucPh0D5sAQa
YjULcrAWF7B9Y0chOR3eB6+9iseNFQ8UVFGJC+2BvQgf6ccXOrKSJA2d4u2rOJ5xc50Q42jK+eLh
7/tKktKLHPfYnAqXt9TdGyLRojdXyus7t9rUbUO4lu7IM+udQHiQymucJKnq1XbzMk7cRbTyW3d4
YaUD9RNm7wP0zsRSIwmvjrbafaNqYA7Z/UwFcUSTOnugw7CQmQHyU0f4ZQqXraAnjTJLtHZt2oVy
v8DZTrEnnsc9JMyY67QoPqFTWkQ/ESvnkMuUp6EOA5gDQpFMYOMBG4YN58YEdPugchcR06Kmg05/
rOLGFwlhQ57zdkkBi7nMt5rD+CjOcmp31RJ3OMp9A/7Uu1TFooPozNyzWNuTIQkYi7QnVpEifNGh
0LLZjnNcB34QBjKxPMbIWAHR0Qi4Sq5pRiGg0RRNkGuzyWTQoQKNiEF6WUtrzEVzcofmAfumwj2x
IE6fMSg25yfQhgjRMDdMuTdTkr0ndd2Kc5jxd4s7ATviVTk/l2ho41l5piiSNU2WcZsHhMMSzSYr
H4Ay0G+AzXlgszLsVM6WT4OLrnCssLG7d6XCtpM9oYIaW6Sx+K4oojzjZKseepcSzuuss9W5zvDD
CRcfxYkVDoIkget9qZaFT2VI3nJzxMqoraq4yBxhHbtKdm1zPRnAQl/WxHkokr4mCQNju6haEtAV
xEinhAV+gMawiCK46brp6isFv0hlC7onJMDldYSLerifcDTdRbLHyYc4h2wIqBnaG9Udyl7vKfJ7
8cRoRgQh31tRiIVGjZchVmJvnjx2L95zKfK6r7i+4rhn36NjKzYn0kVvStxmaLCpLGklRO50VfPD
9M5aqYbUMSGEDAg7fH8jzLNUrO1uTddUYWYXRTgY6ASKFl3W6hiVvgc3xmYGeXuW2/VI/bVdQ2E0
lvjaIiFFBpRFA65PgJg+yotlXx1oSVdPrG785L6mNLmRLOfvAIRk1to2xcJTi7+ikZaWKQeLyJrj
l7puU+Ih6rZfrUoVqOxyFM4mqdBG0L1etTGNGw9pOjhiCs0MV3x1WcDcV29aFaONwsQA2R69dBXw
V0BO3LaJir+87wFWK3GmpjJQvyYS3MOPHc7gVb0ObbL2xkOwoFfHycuLJwmpQjkbXpoumcgU19GW
BEBBVGF2Tf1yk4Qbh0Z8qoVASAvgCgpKELtd8IAsULHsujqy2O3khqw24VFfIqetjMfG1PNjownK
pUzCY6ybroEbWCd7gSe/XUuKTDG1KJOmK/AsiSYwCDIOZi57BY3mQsZ7ubpCfCf28Dh0cTyqFEVJ
0SzU4DkaTTTDKvqK/Df7rNbODmPyLLfAuHmbFz/N4CLWD8i/0ChBPj7cIeeDB6pfKBQxipUK0UKt
y+a24d50pCGNGs7odJ+qEboQjqiSLuEofK13b60Q7tBCDGWWRVJKvIa3ZIQSn/Fxvp3es6HWBzO5
NRURTLcutud5ZOBzL/VFuY6Dj2fTmJSIJIypZesnwC9ICO6WZbnPBLcn02+wHHooDX0szzoiH9kK
BDfiInthNZPjDTWBPrzqCkK0H3DQoNkhPZoj66lHLEblNvo7B6BugOpJJJtxBZyumcB52e4HlH0b
933cRJ8PKSw8xIsTTFvnjG6XAqEBcQPychp6XM9zsrICHpJKrZ+5QGbhusCAQdqEWmruhR2pkLMI
L0p5AWBlOIVoz6BI7qkE/3IfoyoQioNWukurBGaToOtSwMcCKlQ6eozGKA7t2KvzXYXWEFnuaxHM
RE1o6dWu5EF7duvpJZbzYN6YsjREZkdNs4cIjxSXXsDL5Xau/Pq4PrbHiPIiuRnWFg9EqumGwgv+
gitue4Oawtvvu5yIg0yIb8ZFKm97M5ymQqc4y0k/YMvoDStKd8bWvxeYO9zQftbwyqCojJEYUzbQ
my7eclRO93EY40DrX3t8m0ff9PE7r1/9vpgT/Ok+V0Xb1Ac4ZnJG339tLSV2DdrLy468HgBjtZBk
9IlzH959WT//u4NNWgSvirA/Q3elkxAhiQVLBysyKpoos/nE9BGQw/2prGwBaDPz3PLr6Bdvz7Lw
Mgo3RpdhN4UAHb9ZgEVERA2JaDEhyqDdANj4fKLpk94xHEKLhtsjVHdEHXn1+Ul52Rofm4tAMTHS
0nHPhhC6VSZ03ubyjfPTNWefLp89srLa/dEoLDbViSJ773E0uzQvbMK8aCJmSCMyOAlbAUW5aQVJ
5awJ6HZGhPB94UNjZ4kmOifzzS/0atd9ukugxy8Yk4sXgXClBIsTUsyHxYj4JA47pWedk/OohsdC
I2XtumH0U3j0G2bZrQ7obYVOXfJkLMtU5vI1G/Q+8ZAIV3E4DHTKJ2kWQ6rnIiR5Yk47CpPtCwWu
Lp3au3scGBk+5YdwLwZZP40BoPV9kJHlfPmHawRLrR7BWpzeFGZ3gVgQ7mwWoAAvSHevxAQXFzfN
HNDtJtBtF1rzu3evjBV168omi9lHy3gW1WJ+BsbcjIL21UQIM6FAFOdsatdomSgLCWJSLldQM6HG
tuqSv9iQHMzGTghajIThNohNXdWaOeML7xL4y1ZYwq2BCJlAv9epnqEOAVToEyElT/dPX/fbZuJk
0e+u5ISG+mMFc0MsY25KH13REUWIE75UclpirvEiPiwT4tM65bOKD8JDVUT3EnGxLpxHu+nR6F3G
3uLCOF58nWo4kimXRTWvBODc+8Ldh2U8M1fUrKNVdtsq6cM3O6RIfbuIPQbHWkwCw7czeGUUGxND
YnRtsefr9HM4B1w+DTvC6h6Rhgf3lxqJrOmjNHRmzM0QNtpykIQMUoGeTJgbjs7Tns/Do9OtIcka
Jm43wwEzp2vAsKEdODUBPOuz5JSD679VYsUYMyzYypMFrUufRaY492aG8n5ivS3HAQMlFOjOaFsM
vwj2hb41s3OU4WJVgKvZYPIC/+C0XKmm4eIIlbyAgB5EUQ5Yj9DTikesEPfIuQHOFIzbwycwxPLz
0HqYd4sznm4SSytGQEsm6c5YuxoQw5rFRWUzW5g6KoK9vvHBPXgIIV6igE+ePE6cip+BEOKTgHvh
vUMFmZIFqTuZkbpbw3Cs7y41MVCDiiBea82aiCQX4vze9gF7kfFLW+mfX2T1ngbE3/DgahcnEj2K
ceHU9YHeVnwtw2NGi0qWW9R0V81V7lHY+JyCDJhM2fKOC1iDIYthD1a4ekXXdEKYe0/t8X7BAmCe
dBWmshlrGEkjq/XGr28UyNt9mRog37kIjxOoa6X3Zk0M2k+yZXYUynPBsU8FvxthPy5WFfQOL+mk
n95VvXFJxbXbxTHjRA6ku77KpBKvoz5YWx+zqfcI4tdbftOVdVAuOtePF0Gj1qao84BVHTIcLU1t
z2kgu3tY9Y6L3l7ka6dm9X53GRoWOeLiYSt2R9AJlPPRXbxtulmntAsC57mj0EzqJL/z0cSnbdha
1CMbw7a8A9J9gLuJD18eEirtiJ3aQDa2j5Z7TYBEVwNzj7KDC8730yOkh0S5UNZ9fsGfprfk1VRN
9ShwUeTTxZxS1B1CyyS1sKMl3Dveeu8V64NlTNl+xOObAb7iaedb2X3at6152H6iCZibMiXXo/Ek
CrfrgY62yVo1w6cSbXgPpkXxm06ZJkupXbtSneQDRRS0Gn4d4wR5Hv5rpmsaf7h2FTkNOd3vCGI+
OT6CjxQo6LWm9rYPvaNGRsix9jWLg8MHolfem9s5n7js+m11TmPCS7FAZMp8f7Kq47HEUh/Ytiop
+wJSeex9PYznI5pOTx3DUMc6t+Fxfc/Rt9RglkgW+OkKIcVQzyJ1tBgmq6i8+gjPXGBMzsqTSQYl
pZDpGWgPRHgCXLjO1M5dLy7rXAUKaLbHg6WOqsBwutRXT6+u/qgf5K1pA/6stHSCrydbTUSTLZf3
I+OwwnpSTw/bJqEPisVhY9Vs3oZ5CWFbJK4wsK2LRJLdkihysnsIuOQthh6Pt3Bfe7OILGljS066
QlOzRXxmbhV3kIQF3eECXZ4o7C4GAwIfTQuHc9O9hMpRh4HgREKdj5NAZWw+6IR+9SpAQ5jLGwYc
uenYzofzlmP0rZCjzDX41hCz8mZwFR2Iy9x7IouJEp65DPx02Qx32SErMlCohhaF0cDOHd4Fr55A
L/DjcttOCDJAbV7cEVGepFLZRlH0Z/qYmqcLLyHMmd5ujGOsEtAqQ5etAkBDM7ZRHSm/8V0ZEt2i
YQ6CoUaNvQHk+ROYryhmjc9hPEhXuaGzqbQWFBmoBnoBvtoK8YJvaDApzyiHNC3wH8xmeyKWcPBF
cTYb3joNzJHnytvh/W3jgFLQh74WlBOvZUNjk4FRzB3jhuGuNu/17UfnSqGvtgoGDGNIg7d3UmfU
ZOVyhXYwi7qrbzr1gdwP7eW99wdmUvFr7FKX9RyxSIb59Tg8dogs+VJctZjCBvyuD9X5YHY121ws
qbQ78pQvMYogqiFNWJnUwTlOhFfuPcXxusc/MVrUbkulh25UanMVy2yqNqI5E9hEYZJ7lA0+bmlt
1q8kRir5FqM9jj2e5KxVotVEpMlsHlCzyOBClG0/1fHE7y1CG9ttxi02rtdo+KDDA3MI/B4LS0LH
b3n3Sc/IkLFVPGKOfJno2hPVkntghmFwMtUWI6hOvAxr4EcZD7rKmVVxletgyVmKjEJML6lZxhcn
xcnVPGw0SmhnUlZB1hTsVQOUVwA1q12vLfFlDxdaWy89MSQ5RUxGU83vNWhDdFhJzYneB34hRC2a
TNQOUXk9lEAcvPrFjPid9HVz0yQPEErdfO6ve4wyHbzcs6uuuJFArvd8xyXh6mNN7PUkMdWZIBZs
4iGrp9WcKA6mHveLXa0lKoCcb2NWZaNeAQU1OminD1e3qozBHmheoZD0Uelk7LIcvCjwrabs1MKZ
u6cNOHeZdu/YMaSGC38+2uFwLYk0ZCpeLTNhFHMhRkjUe0qM82UUaqO9d+PrRA5W70iXzKlWKwdq
jIXtZVxCADnZ83HKzZYey51gLfMAcrzIbhWb+0QNi91xJsbAtlsBOIB089V2C+vibgqpees8dxuK
zC383iqpsdIS26u8ytxuNujyxVWWnANkHmphDDQVnHcb4xpVj27pMgyMBAmkqiYuWgiVMlGHmaVZ
1ae8wVIbQsABDb+uEN/t12qhyUQTy+7QxGKjA7TVAsHcPFmh52x+3nAICVkTkvEDYrjs6tvemt2x
1WPrXXCWB8ad74weuY6xD9fsh/B8kcTqbMkw4mRXGzsPExIK3ypCmiIcRQeAU3trlILBZVg1Wcqj
VHUmNnCepDuFQydMIXpYjHaO4VhJQ4mZeWJ6ZY7tiw7aawsmgqVlrUEAYJrgUIb3223E1pBY8B7E
UI+cVKS1eYDDZb9KiWqwdZbY8EHA1pYrh0sQaHc0I4KNIT666NjAaoI0Z2prygNI2XELj2q4lLow
uuJpA9+hwgcvEzIWduNjTTRI8KoM8y+WI8xhe2EGcaz9Z1barAzxm7gdL8aCedu1R7/sfIX2aKTu
zokC2p2tbXqssMuUD0olk2c70jh3T9GYGd5t2lk9MiprE6PSYmPwo79eaGRWITIHnb946lxFczsl
WzLdMPtkwz22kRcqVH7RBFW1hnK1TLtlKUW68K93jSQ1ULBrtiZAWi/YjsFSp4fNQidCx+ACf+DT
c30cUl0nhjWzzIQIKspEkp7jjoXoN7lwWLR5R3bkMfk9Ug7aBTpCi/SLJNyePXE6epc3Zh0cgGDc
mG7wE6s5nxuipwNvNr07la8Dm9RUMC6TVrjYa6mJ0zslQeIfj9NxktGwL7xLK207sHelXcRGwJAi
EtKrS8Z0eAzKsBwHM+aMO1Fp0RRctMcQGzrk8flzAiFGaf3Qc4pxgEZEhfMNqchxHntIRYLSvGqO
02VhFGlTFMz1denygEYMGSMis3YgBzCZ4oz6g8lBLMvacgc+SLsBtJvbHvjAKm3sx/4DUGNSRwIK
WUOvqoAKvCOzdK6C3igrrlVYj9XLcVpPjME7fvV8ZGyCcKm1la2vviEOjoMA2Z6Ey9tjOnZHfawm
QeEdFGLWrauYoRCxXS3EnebQJbofV9JhQ4x8QLq+uNLDfujp4uGo5J4kCRlGLnz+PmrNH/kZATTx
STrMGC3JQFEvCSUOQmf7NWXUtFk8UHjTD8JJSS2bfKJdNH1FPYFp9lVVRzAjXAbKBPq53b0cbzsz
5SdZtI2rrQfac110+5yaVeVSNWbt8/Sjhqpke9AoxSFnV3Amq1rNbD7heYJvPtDbJaLTzAuSNJ3x
IVUAmIREJlvBwSOA+gsBZ/cX1ZFZtPnY5zehDqNCF5bfpslPHAS3FG+X7BBUr3sRNIAnlIICYm/c
8QNBDCKhWmgOg4eIigGp3uO3mI70UzCukLOcddVdqUrLFPwwIKNdIEMD9NCiAitr/DfceJrdFVcM
2nzKZa8y0AVi04/kG2EUo93cJmJOIOtC+4MlbYKMuNCmNySyiNXlQUbW4UoRR6mCKJLvVIfLYsKr
0x0mMAlXL7Xc8tRkMiht9G27HjNb5+xLr66umRptTixb/Mu46fQ7OVHjBZ1uPx6mx0hE1A6G6jZn
p6kpCoWtcnm309zNumZZyIt86/nQCTKIY4AZmnmaQKk+hlB4N3Es3Z2YaRvXbWPXdtbzhXXMuHla
kfjJXsd3ez7Fyy4L9XKm6hoeCLzDiGwcV6JeaMFkx3k/TX+E9wQSwTyLKMNd7NckwbdWb/hMI9ZN
Qg08Siqckp2HF0Cbsxxrd3/oVzwcY8jUDy4qnDnplMRW36wVetQ8RFk91Oy13LrgmNx+fSNr6p8O
FWm+7d7feUCOJNuR2KxmlX/fJmYpBexYfVFQ3RwodBaV8ShWEobbfJ+NqoKIJxermubm4Kc4XQss
mW/z5EzE/pbvD9c1zpQN/Lw78BCSNaMBl51rJZKuj8K/ikM3eS4xbx70PteCtVQXc+W5s5x60jrj
KtuhZumUx663nhTiFx8u5T4Hz9ZozrzT0hfEGWLbaJEgQKvWoEJa0ECjoejSEQUCQQmyKBX9JMnX
hcRQQkUGs3Iqx9cyqA6PsGUXbm3ri6+n8jSpwlmObPOQpuTJ1a/xXRYpmtnIsDp3fI2ZZupNnB9E
Y1Fz4vo2XujLMyKxAnK4OIrVdEu8Cu2bPEgANU8P1+YAQzE5TgbyftSC5Rma3xSpLVwrw9a8eoHl
VZtmflfpOFPDd3YXS8VJJDSzosiGuZOqAl9Rlc3h1xeBzrv6CnL81DolS1gjnXzNSYe27duJG+b8
cS8OCloA7TyePQaJaWeTjcSl2NXzo1Rb7qvC0xTnvJQVM73X+9Bag7SeWQfR6JWGCuoujO+wEEdt
B5Ucw1LjPt/q4zhPBkwSug4m2RnltreijbyvzupRykJObhW+rSNN+AvzFID2FPAHMbRliCTPBas9
JVyzWn8+CVo1wtVCI4t11+0eN3RgecE8leKbBOoXTlUsFZQKEVIjXVskPfQWq50L4WnxJe0WL7G6
m9NNcaIDLEkZOr5YqsgLpHQtZmFmZloWngRJvuXYi+Y0PBPBeFFpdCpqM9zxJx3uBt+1QDkpb2yi
B/voRDxLlybgqq4d0/FZkkvwwAT39dJCswo0/w4VDEqhRN8tEQovXJdyXXxQKKkx1oZ1U7dPN7YY
jntDyrfeB5q4lFGjIkeUJfxlKgn0bj7x23utn8vbEnzjzaYxcbTrrYauC0q4zBX3S+PQBJtoUf06
XG9Ai77Jow5uL3ir44VK9OPUhHwa7ReJ3nvqwbxahj7c8Q71YV0HQJ4TxzEVT5tOlxRwNcUQiTrp
xPeStlIGQUDLUmxmtTkm+ZGc8jZ3h601ZZJUeEl0tdsjX9xxTHFYs8WN+eIOdzmaNZwCSAUV+5jN
VN0hhtFIqwOoJoOiyrMr8EtVrum6GDIpGMgEBP12I17rrYmlSSzcnsX4w2/3KeGom8O9MesQBzeZ
HOWdndPAejOKMOKpyukOSA+gEgxu36+PBhAAGsWPGptauWfOuTIK+xQOQW0XDtqjlnGud2YPSLnK
MwfFspzeuYQ6gK4UcGZFgnylhw6dxgRMrT20mKYI8VMISC1fiKK60DWEelgvM9UyEKFGm2jw7nKa
CN+2ijB9EcTxhGLVGqNRjZTZMwlVQBtCXDbv1tV6egdOAMl4IKKtnHupRPRjvoWZgNTse6oFcw50
279iaUcZhN7U6Pg6BDm4vY/58+fHzxQKS5ce7bTrE6u6nWVPdUOX40QfXhOv5hciLwBeUXIAvTI5
lBl/6+no0ILyCZBZvubwikPELZ3EqRughI/h2VXcI2hkuaTNOpu9BamVsZZwDdc8tbXJFkDaezFm
Mwzit4pdQWUumAYtLFmY9uLQyUEJq2RmyjBXu9vTW9yGeBkp6sjEXTk3+EIXwz2U+Fv1eOtLyDNk
vni3GOpp9GSJBRUTs9UxBrsWDC2OGzLVU0wlRCSwjeZFqECRI7tFO8bw3et9Wqd1FaqFUXIRenQI
H/JkP+Ja6caDyGxme/oNXt5oVEDQI6ADsSkd/jl2fYgl/KKF6FEzLGYZq2FtSlcFdkPLsShbCjRa
oBjVSepuqZQV44xN1huDnnF3cRhXIa6MRLF9O+iBJDJdxoxjtik0Sp/DVmC3s3CtlV1pzSUTowTc
wns5qrx2DRCHGQXv16iQt/dgmtzwiDHmpT/f1eAdAoePS4RlNfla3pld9oFm8ke8XAXsKsR65kBN
umnPfvCSs7UbiRaOYG+pet/sFQ+XRXrQnvEGVYlGYPAnWovtzZxpHe9h3W30YtoVpReaiJ6hs5jt
4AsmRSVR+Wp9XC6UuIbMFTLEMvQPmrC3KNrpxOewWad0CYD0QNaE5Ky+P/LQ65qtJKnHnDiJZeX2
jyghTaXVeHJimB4uVRbViB0RXdZsEOzo0NGlsfDdBJv8PKvCrKPndbmyFzUZ36ObBu8qMwXN4vth
Zg1GgO+2w6pdiyiHMuijKcDynkXLE/Xv6q183NRj3B+AAF0AVYrFbgGzWecWa6Wj3eWu2svo014/
2mapa++pyBYYg+uu3i6GPVAMSuJpKBFpzchU8gIa5a5tSuwxcVC07aG7vk4b553paqZ7AJ22FSuy
GAU9oLiRUs2owa/mfCDZ6QsH1uDNrnv6Lc2pS8zl7iC70mBmDvlC2mmJxE0voAedhi5tEdvLHpnH
09rJewoGzfPN6Z7DVMZ409HoTRWSFlkd7MyXZHqdFT4dt3MpIh9rzz2sgdgYXKKPkgY3rzmPkbra
u3J1pe8dumfWNB3HK4yyMBmaU58TeLynL7fR7/XrLrvc6wD6usJBeysQa2soPfvxTB2T2hwvjDLD
2lknNw9mcxHqQYafTMJcKgqdKXu815Vs7em1dqrYaLkEnjx7EqpNW9bXHbdhkHSAyRcRSkIAQuZt
o5f+hBMwlQfLboHq2ywM3RiIII7YCZFm75VLll4AUhnLtVveh1nrxrqgvR27+NxeqwGftBINphJf
r9qFXV+4nG8Vx1VkkcPk4bjBeE8SqFiuOiBzXdWVHJFiW5URaHhPTDNQODvBeu0G44H4zM0KvijU
IxKhNxjWWCdVUt/g9+INobuaPVHKH9IRKDhQxQFLFbWnS1403m7HA3ZDRoYMvHyaGEo+zkvzwnYj
Wa/QMCncaZNu5jtASS/J90gfhngHcxHVwmORFC7k85H1pP1yhaQJgQ8tpcQQumWFxhhKiizm1Iwd
O/mW9yaY/HbNrSzpkmwqAWwafUMSNeOlN/axSGdonviGUUwmiph1CTIDYo5bxWTWjO/wlDbw3WCH
jihTeVHykLOmm2DYjzcsUHZStOICUQaJ0mhj71WEpwOJajEKiFvtJy9ETOpCZmgm2PdQHJgFVS+3
K9MbQGA3I3+EFp8LohijzJiJypGvQ7hJ4XMpsVzHc9b2q1dqLAFmsheMGJnqvXkK5bs0ZHlPwulI
k3JDZAeMF0/Ki14lhScZ8Y1oLuV1vwLxTdu7QnBbxm/t7tWRYQhFnUmUUi0+Eub9+FaJc0t6etpP
glgSPQ/xlW6uYnRksitmFWiTEFX26gUwtTlCetRIiRdTfc6BXGE/f7sHJqsB6BY3pR3eNJkRyqtY
EUFMUElI4XtFQGjmLFyFvGaLF3ZrqS5CTEiDdsy40UcHCYVIOtDR2E5h9qKERMk7z9rrp6jbtXyx
LI89/UosaVe7A08YFuUedQwYzOxZn18ERcbk0fDr/6npPHZbV5Yo+kEcMKehJIo5Z3LGKOacgfvv
r32ANzEMQ7alZlXtteRuOqfz5Z2GG00iDlP4YrdDBZrzCcxhZ980tfO99jfzaONno8vgMIcmCtc2
r0dDy4MiSt4E0gOTK8ukjNO237PNzB9Rtl8vfYZgnS/WkpGeKajvVxmP5MjAJjO+PYI1WF5EKTMi
cRsMMLT8FrhkShOjRU0j2RqH8Pr+EuW3/GIbdA5kV/y+prvM0Fu1w5hYUES4gmR1gONlaLAfePjN
+uK63z6GM6cKMQrJzlduddp6fbYNY17QlhUqiM9NSL1IPrwegfDfLov+OGJGBudCgo6LLpW79IU/
a+jGQrNL50OHz+2LIbaMv6t8X+7oZKN+5yCnjicIKn8fybJjJjBdHptLP9/11que1IPg1EiTt2n7
thKK2LA10hX2jm59o3OFoE90fh1pSbtDHzdSObv93qnbl16RnixudmZ2Rk5wbtoONblXC100dL+J
Oz/TxESX+koSL2jGEz70YQ36G4qTHzR4Xr+EVrMJbxFv6rlo13IdU/M+bqU7Ru+QAGBGGXlP5BJ8
Y2cKArYxQmXCzY/ZxARUg5TbWW3Tg402vYiosnu+cK19mY/+E6X7ZXHhtRTBN2w4fwvbhNnGKO3N
5y1LFRe+JQkjrgejiIWOIMX8JQKbxH3l422YhFHWlUt4l4xrfraLMPdRhV2p08+1niclRb0Xafis
lgEPfy88UyPx4jUTbR/umumTWFM0w+Pcuh2kMWL5DrLu1i4uxn6NGP24UQOzLueYAAZW6Z5wXALk
15S2ngpYciuQtKMocE8bz8tUNgbCuIW4KK5vcmvbkbkr4M2wRu76+cFlmWWzFlPFcIRvJ5jWeGFs
ajH56XG/2zvjbt9efzH+jU/zplBcqRc6WaCtqWviwB8Utw4BeaCPJPJsjmX6kfGdfMvfj5FPBEV+
XgR7hejEqDzocHGLacqlU3njVIX6xcQN4lsvP+ZJI8elZ8mUq3xmP5db2ele9jVYprfCcq1WlM5x
wOfrM6uumxYaF/Ge2jAK8Xd6PqLFWFDIFMOMvQGBpcvir0lp30WbUMrfKzZ0zya+Pk2LJgnlmIbz
Sk7AnQkWf5YuDEWLWNbF795J8j0n4PobXLtipmgnFIymQbDJZX6PC6gE9qUWaXYql9kLN+yGq4Bk
rIV42rAE3zRLMhqjPYigcyFhBJj+cVWLhaY+6x7S7TLdkD7d18/IEzMmwJGytzzY7CCmVVWdHP42
l/IZE//e1qZqGf59hCDEZLr8aRyjMBlTBoBkxIa6EVlu+HR9Qh4MEijIvqUqUqT0Ym+FlVu00k2k
CPJe8K2//f1QnrtMjvPLjC3mdC/yDMjapuJUwaVPxxwDpuYl2wmGXR/WHVSKm+Fo/MSN5yRNBlSF
n6EO4mEOrtNrSN3B0lXkceNc3hrFavD2R6lfjsH41HABNdI+WUHPRfj7wcEvTUwDeH+d+5YPBZz3
ELua9/TQVY7DL4qpIBmUJOObdT7Cv9Klr6XWY2TDYiG9UTMA6Nj+Iihv4B3q3yEuA7+lHZwxsLyJ
7YVLg0yxrKuB+K+njH9/JmXlHtmdflbgGYffpnmTwVwgbSFCum4ZDcXluAAn1vTSS9Gs1YCbeVI5
s6Nr7gSaSqxVN11l9CVNt8XVQXlK/pQFwN+TkMZ7SQcsYxxBEHgImGNF0yQbOStFtUEcmTqiZ8sz
v7LPZ4LRhHwBTKFcMI5VXUKqYGNF5w1v6a+zrHa8DcuMQKqjFLqQSCz+VunAtbuztZOCAYVy+7n/
yQcUh82HUTD6oH30SV12K24b80RBpKuZBkLFOGaFj0fthpw8to8Tnu2jtoADSnNVdopj9GjjKl8w
u1vTifwl+GtjJB2jwzFdfCvspJeq935bf3gLd6qLMAVZzsqJTeUjxanJMiPAs/8S38SPc7moLpnC
I6Nlg1fuBj7Jk1EuLPvYUuRF8JVqZZ9UVT8Me1BvutEeMYudF5bokpMVWBIXkAK/haHQm4kcysuP
7NSP0XiMgk4mXxdIoKMxuNCDJBP7LbgFczqaFh8Uga1cd/xfScuBHgdgEJpP1ZtexogI5Xef6lGY
Prn9MFbwOX8TPhwfjF3Iqr4coUyUH7YtBwx/c0+X5Vl8HkRfHy+18Q8evyQUEOMRLIun92iP35qR
sdqXeOxwQda3N9uHcMNfQmlHq0t8G2eAmAtou7aUQ/d2R78YEdPdtHzmJXl07sNpGOWv3/kwQ2R2
BFo/n0j4iiLKUsTwATmkMY7uqHkr6+Ra89K1iq4er1i9M/WGxkX1XMGOFdxQD6rEp0mxZS0Y1Dsd
I9dsGJdTIVu0GiSuw8rSZo89JD5xsYTQtWcGbR7ZA6uSDAARiN3EyvC9WhpiHkt9d+S0cNHxaRts
PlLHlF4FqmZ4lu+ac1caO2+TBUkNsXleClnN/FEYA5Kl8uyIoWYsKRA6nBvVy3Jrw8oUEsYC4s1e
NErRxI+xknLSGzMP9acWZIc+0NdL1Au9MI56mniUSHcc2bEK7amujq6APzEkVAjDP+1haLanX+dm
ckMJS6z0R4+szfCQGW3W5iu7UJvuG/Z8rC3mE+detSUymQ8VZlUSeIj/+kzNMQIhTQ1zklg3hHbr
6QXwiwlsZMHLc4EQfSw2S+5pWzDjpmETokz9zFS7duOAzPG2PA2beQlquHePhTEACcxu5dNlM6M2
XggI0oLVLYSNj9U6fciuuWSNB2uwctvAKtAvhuv3tLEfZ/vjj8gQ+OJT8o9Fq5dMLpMm5D+bpes9
R+HEN+L51kOLxS5iGMvrdywChuwcyKMJcDaUML/dWZHtxrSIa+OXKJhpvbnBpvdMWLglNYkQGQfM
rfNyNrunxs1F8mwy81HHdTqp34skwGVRiXDfdCTqC/aANVUEc0CUxBWIeGgHF+hkJIiQVb0n2wzL
X0oo28Zt5RaE0aOTvVwSxUt75fsLvDq1DInN3PLdf10DOUPWFsCJibgn/okI+cPUTWUVA5swCxOV
m19IeoSfSTaBPG7y4b3chD2jchh6LH82vCzib2KDNKGBxBx98pCyVh4jcNYGK/m3H6svtzQ0JufB
wgp1XiXz6oh0NKfwieewFv3j25LtQd9OtGZEBFJk6mqHIB46WlKsVBcdVxtxXcQgKWcfXvpJoI+l
dqhdNBymiWFQ+QVWvKUaLOiALvdxDiMJLovBFkegXJQ60aEq0jOjh2/F3Oa57jI6dnxhKKMV/uJX
B8dBU+NNbiv4PZvlBntwFT70YtYFB8TGPkzeY/Yb2vkCQRxpIPs30e0um/G+yeI5FvkLhc53oefR
DmaPDEuMniQHGKAZFK+PiH4VEYLlRhRty0VPjgEFWPIafCVMamNMDIzafAGOFnHpb9WvaggH29Dz
xYtL8xIJH2rIsuqqROnUaYP78hP1I8XamFmUmFq+7e7YHCaj5jEpCDxAq4OiM/iI3wMqYT/oKbYy
0PGiNvhrJ67wb4+kQi6hy/LrkmB2NKqF/rdHiVJG4aWwHzT1Xtuyv2mfKKTZWPwMKy5ngp7fODwu
hMalKqWhqCyDtJBqi9+3Lmm/+ORCQI/IpMtFQPGaCEqEbFtgh7X2NvinP/Iz2RzEEL+6UUyqwDAo
KqZdfca/UcjYhEUZgRLi9rfS2thIPWWTwucaRwos3agwAgKld0opHusZtJ5zoGgAxH4wABDoSGhN
yYunbOZHMNSKOweOMXz8ImCx0tHMq2Pe8AcdS9rcYOiLMNbSaMyJYR5X0hJ1PDgcHEZZ60xq8uXV
M266eai/1Cj+TgHIxE53fHatVPriOG4X+C+zKPR2r0VGCEWX8N18IX2C9j8MKncolQiMicxwCZQT
iaCY+mrWuFMIA02oWdMO0O+yXNSpw9jrS/1Myb8YHIBfMBtVQhYY0nQIc95NU+z5dBs2Vf47t8LZ
MM8ORWj/7S0Jf7H10AL+2n6vSOYD3aoQx5DuM8b1VllrQkTfD0Iuud0ksLfd3UOZdsOqjE81E5M4
utzI+Md9yeLo2Dg5LoMKh7oT8FHn6t0367wQ4BZcm5Nt0w8Wz4NIOyaWbMe3G9hZtR04ieGd/t5F
ln/KYO+RxAmIDWnbiunwl2qTzwa6+1sIuehcPfekniRkzQ5ei+7nGl47Buqj3CLwJBVL4hE+8xXq
nF8C26XFLqcH2wHSJAT5b+bmYFYMaqOnQPvOTudW2/IigBjrWclz1rbeuLddmWWfanZo3SJRRXCd
n+Wd6Rjxfpr+792GgycKhGQtRqL8dxGCa5hf2SVq7j1m6kFe3codyIXQACEUh+xYtI+MpXAaAcfB
QFe1AvVZqwXs0sZS37eve82K1wUbO4eURO84wT7i/RTw6LR+eUz6fu8Kix1rjH03KwKzBP2AJHol
fzmwiuH7TFJdTwNJ6BPl0X4h984qQH2QstxUcPWZct/Gx1ezeNmxMBV80fIfaMfu8O7fiKFlmoFG
aGJu219DaPg7W6jhvJhczxjX3kwWoJq34Q3TZxtzqvxpARfbrgGnfOKJIXkrwZyBMHwf0yiNjB3T
bDqUZVnAd/fBr4Hy2a38qkTw4Bh8j4dp7zvSQPZycwH8W0qL8o0XzylTpDxxBP2AtOHKDPriF34a
rt8n8eHywi/CrLuta6cblpRlyRwyGO9Z6ozomUZoD9QtGU2yAKNtYJnQO1qQ1Du4C9lwhiAj8R01
rHKqO2rHvoEb9O/LQXkWol1YdEixiO/9ThCJLq9uYeu5UiH7WOCXCdz3uN4oC3HZD5gIk6Ry0iBz
jw4M9DEU4MEOJYa02olOoW1J+8AvxeKhmgOwlTa+7h09XODrJbKI/itbQxn6FfeWNTQNzu+Ni+5n
crxQx1aaHNNuA0lc2XBcXHfVhA4EQkfhigfOMS1O9HKZGWNNxliRH6dkw1avcVRreZCLa6jaggjs
cZMA0T+ASzgYVHZtW98bdFSFhKfFPCpTnUCZ/fID/7o00IXEBIHd/t29hTdGKPg7Ayf0y3qZH7gy
afOzViJuM5gdqoW5hQMKeyJjUnluBwx/iOQ+husAzdu4kykq0yrOVi1oSwGE8B2RrIoA2sQSPkfp
WYOhaR2Z+MZZ8jb3aZCp4UUuBAmp+JVsud+k50PY2k0Z8od9Cmdg4fk7UbdRuhhVWj7btUBpW79W
KByzmaE3jNyH7mm94fpgrJHNvmYVnjfwvADvJH9fO1pzGWSBJpkqMAMY72MyekoTWZJGAttoOW7W
TtnQizgeRAybevFv28xLNSnQUByxM04AUTTERth6kq4Jq35FQT9YRBZEZMfyDPalEMm0fmu33eRX
iPq+4eXuleTjjRgS9DX22tElsYWipj5Ancbywndqbof3wby40Be2zaoFOqG2zdRL++ufsarph8xx
eqn6I7M2OJXticxQsJh6/kZTCtqlHUPwpeEzQ4e7y4MuOM2OydPsgIbJH3Q7GjyE1cb82j5a7pNC
6Z7baFnsowaSYso+ruvyZ9OUvawZFtcrc+F8EGqAOlsU37IB1nd2OTwcg26v4XsQjPMKJnn2lyzJ
IjlVNKcqcY8aktMUNGgk4GDVV7sKPGZgKCAnENQ2jfmIUviiQLHz6RAKKcTnDjxtR4F7SD6380yL
0hepx8FFo98HFCj0oCqti3LWwSqXjsBXeOOjMcXgTv7tnoNM5LvqkKgdrnR8DIGPcMwvfp2FcGfl
EsRLWNdop5QRp39eZt/EP/8ZhsT4iablt2yYXLjV3AozRLiAVptZ5Wl9NT1DGxeGK7yZNW8hUciA
YDwcG5U1v5T4x3/G0Py88p9xjrPh9/jWsoA+K6JGSV2v+i7kTIGrMuLOcoU0z5xAOsZyQ4S9AE/Z
9jW2XfXJbssRB/U7yG9xCzomOl77SD1Txl6TqyFjEwc/f32vbAauCOSXmoX8ig+b1d3Q7apB87ta
Fh+6bSQiXVqGa1EmzRGM5X5zOMh5W/pldRBdArSBWmJ8Ndm+v8qYl5ianwimLH3Qw6/CsKE85/PA
6MP8mUCRcH3MQSS2lz0ltrmBl3+nVcoKvt4TNOBrBlgE3ffpdnpd4D6O9fuuTPwMONQnLMvoOMtm
IT+fDXNbcJGxxxSAHJvz2Wv4qPBarKiDsrrxCp0TqP5GDPpa5jX5rZZjOVlsBnsbkv48RGcX+Thz
NC2avtmZdXLHw2e6qcTOr369Qf4s602x1BQaATW/ymSho8sPAPkiE3O/7dI7dWsrtcZ4hw181Qjs
L+F5ZXei1EfWBS8fk8K8IS3HsPZiV9jjoHUZDbNAQLdTWX24Q8Ut1CFJVwNoJUfBeBHXIIIff9dU
G4LaQBrZTtryXdYLoeP7nDTczF9kjucAVL415hybYOV3JMsnB7foVSyFIK5kFXfYRtbc6liiYTcm
ClqPRtk6aYgYFf/OQCaXY6+8Ykpf4aORkIfewZR8oF3l37n9JsfaASM4NJcLXa7pJjc5dIObKvqJ
0uSAJRMApeq6t4cAnnRZjAGCrAZwBwV1CStU9T1A1PduRVCGDlh5Rjvd3fwmvh74q48AVBUyuYG1
wVlxCbk+w1rxvRIjjBQJhCEdnouqwq/XlwMR/k2AZ72wwBTg2xczUoYnr4a5G99oOP1UnaPRziWd
lzjRPp9inWDqeqBOqOTmI4WZog78c9OiGpFyLw9OrBiNhOUQ8RSENEOi+JjAWIUd+HPQVVQqja2R
xvfMoD2p0DTUeUZ0BBlLYJQz3klw4vyn6Bn2K+6XSKDXOaKZK1vTtLX+6gr1cthfoYV4AnRpkhD+
1+ZVvic+v/yh/fO4PpDCVlPR37ecq5NQSdyBui/mJi/4frbOxOsSKioByTc8fUpigzcFNDQ7bZvz
2+gbduxDQm6847Ds9T6Xe4NvNCOeX/MiiDe5kAljFcrxNa8EpcDQEpi2E/1J5iqpYyvktdC4mnVN
RfuavagbEs6lEh2aCCSjG3cYsAeAUeIOgV9ZcoiU9hgitMVnmxhfbTfIpnqL7X6BIS6zGSoyClhJ
2mGLddosO+2pxM5n825DCAFxe1j5m0ZbW/3bgpuGbtVlUbs7Zl+iF/WZlsAepy/Q1yj/bKUfHPNz
uezL/LCoKIsCn4feL5szdkYPPmjUuW8fm7esW9yA1YnQUxFbwlR7KrC79ijZBRB/ocw1vRWiYbrB
Z5rVBsBzD4AkhASdmOEHX2gWXMIltLga7keVBuYGVbNGxu+Ag9A3ISb3UKM96tLVfXn5fMOVTLTb
8nevg67FSIHrj/e16RdqhudKU+KAX+g6xaQtDbKHErY0QfldDld97MtFEiqCg6HmDe149Hx5+EwI
GSW3wtUQTFH8PX+meAT7e5GXVrpyHSeb3t8w/5P8Uhm8nGgj+b7B6hl02BlojkoRerEWRY94+cU6
CaKLqOE6C2UQlXEhhoWHohisrN0OvOj+kL5lheTqFPOQqCEweZRe7ksuQs6VBU2JBfkKtKspLHHe
iyyL50mUZsny7ox8+mnJYK3sgdTj/nArwoUWWOetpEGOVieF3Ff/Dowa3eU5Tu2GMPUJhOVtxQYt
gtr4lc9fcB0e7rUNi5qceMWMXqgR0lQHX++1kSak2N1lNVTHKU+lMJzgAeW3N5QEXjuQP/nGZG3K
iwCwZrsVX4Qp8mXDES5kiPVxpt9Vy6l0R0RYFQi4kCGhsEMkZtS/e16M4hxWQKpprKA36xCenGRM
5oXfuAS/QIaGqjzBe4yHMUzCYL4YhSFXetA3dFdBr/6XhDmUqC+BaMpsWd9tTDHEsrMvgAtItQqS
OlQu+nfTA+CCan5UyxXyQsdsQ26cZ7CRlQDDJQc8kQvXoIFf74L5JsysdQy4sL8qnbUFGm8Fyuc4
rBPd9r/bobL+WAzcF5kssoDZYsI/cC7gZGEooTQfKdVFVAuI66AL8i2K7T3j1AtNmy089dMkfSrZ
kax/1vtjxWFLhHsSIcX7ASZwuo5jXa7EzGXReKRE5eUjkgiapsk8fz/KYamn0uu2g1g4f+FaD8Xd
9Yv5rJtBvZN9DZQQEHoAjI++qU3orMrgglIfqbukbk0rQz7xZSdTrS5uL+eYl6HXnzLMkN5eP/mP
f/zAPAuUKA1Dcq7b3i7IL1o8aE9rIdsapFORbQCcoAlStg8CHBmaAogsCS/TSmR5cJscisPsmWYB
zz9XktXnEZ/3/RfhRbwPYhhdvYcsyAfhs4FoIVOoEpNs1GyUeJhMNOugtgb8TqXQ4PO9uSc8LXeN
D1XbioL3aFCJ8Hk7G+pik8lXOHSq7G1hs380KhRwBzQoryTqUt4MUhEgS+9gKQz9hQj64Lh0KR3e
+QWGvEhlB3sDthAYk8FbH+57OtIfTIXpnIKIFzQ2Ig+ehATXFTEwsb7uNFU4nPmNjFsrbTtAOSnd
nKtz+zIuyQOWriUekNFey9C8DDg511R8Imk5nW/2QQApvFlxME24lPhSxZuGoBKWWG06Aej7sCYe
81tC2uYMcBc97TWOsU8fPrLG/EQpGFzHSrwz0N9mnpMi+fk7AijaI5Jpe9AI+AQtJgBwpYvxnv5t
LQLJNBS3jXwLWZwDl8hDCAiiML3pLOgWke23jFR+ZPxQawGfnLKDXty+3aWEbbZfVIuWm6C0RZfi
8RBhi8cnyBKoZdX4wvNqveIotkAxE+sNvmyMk4COxRQGLa48QbtYN7dvxQJ/zAsMJ7xRcJ/unRyE
WxuvP5RUY2ulli2U6QjADgevoAMNBsKWxSe/EXrVil79YA9d4mCPcHRtUJzoCh5hnIKje8HR+Ad8
YHcFEkqOJVUiYKIw6NxS8VrIE3cNhVphtBa2SmT0jav18eSQaaXuUft5UqXiN/N2nCxdU8/0pJ/r
xNg7L9NdCtDQkz4uIhmkY3SFCebBznCDN+KDo5KnxioUTBiQVs0Y6Dsn7V8in9NEjei6u/Vxhyvn
3x5wZnucEeWot+xLoFPKjUzcJMxabXq9KV9aZ5xfiRfV6AVefoFa0kHbNvUJ+u3nE+3f4TAccK03
a4ReWkhyzzPsMckGlrAPePOJnr5N9H0S+ZBUc681TaFQ2rbyLOLF5zkS0XQffEFiIfO57YX1VK/3
QM5CZQo0fSRt/DkfR6mR7fR7iyPXhYrHqVESReUzOEJFJKD8nb/oeGoShxpYyij9hIJsuxVm5C7i
q5FmM9FqX865rlxXdGMQjZbs29hyfiwvgwkKMYARNUx3FQuitmwBRTrQgz3iPQnfgUVEaVHbVjtC
EQD+pJH4NBYIpULoQkBImR5AhpcU7+qXSdY7jITsQV/ThJma/TPIao95eAnv4Qdt6h6BcHE6xtk/
PUFrEKaK8G9kF/bY83b323S+79kp58xfL5jhtS0DryPkYpgiB5HyGZEGQ8uFeCkQY56Pi2sKj3uh
26TABtzc57/9iZ+urD+h8NDW3LJmKzLdMrDe37mTGq9ryqt1dWooPedt8DWjPho/Y7J4AnD6EwkP
jr2D9Nmbp5Myg+otg9OICantwKyAcXVYoA+pRPXsPR+0FTZlkBOpH0d+FCkY8Snv5YE+CiAz1ODw
yP87kN2m3PMTIWoLJrtijIrrlAKa9DKhZ2zRgn25E79BtbaK+jkJmLUpDVkk6czPG2RViGh9ItrP
26pLzG9siXDynkWP5hU1ruu4ja7LqhzjYOwZjpM0x3t0igVHPsoF4lU4yq8Mpm5CwHeQ+QqlurRn
B0xmgd6loM1WJiyehGGZnaSc5oCqvPADaA6E6fc5PsuyGmVHzslT41m0gDmqRkpjCp9jVkhRolDh
Xpsb3ZZn9QTUKd7+jT9X0M1lZcDVLrZNlTh67eg/kncpn/BRAyKqNe7F2f97g5TSWsDZtM6xctXt
6awI8odpq3P++SxXcPDvo15pUkC7gxHvofaii/Y7+CMScYmZigp7vL8s4i03EmDrzxEi4rgieSeM
plkMtPOs9RHjwZQyYDa8GKS4tlE6Vk9m2lLKf0+YBhubUiH3U9bkagbx9VrkdaFpb2TW6E23vl4k
gh5sUySH8Qj0b/17f2R4dNY1bmrohiuBTNeC4gmqHQVpwLerKAY7RxdeTeokV/LcTtx26SCTsl6G
xliuD8Xn61W3+5J4LFpmHJSLFXD8AEVKL1ZnenfLkZfqJn+99oJk3YDy0rTPepoW/3qi/LZ7k7To
eElgrGhs5rNVIdCU6qfvr5r2UZblCpQdDcroJABBgvihPVJjQWPWYWRo4gH05AT1UiYS4Wm/8/5V
DS4mR5+dE8Q+I/u8n0PsUkxfrooIAubXQqG8kD0kDydcgJ68LlgDNe2zy5MkAKZ/xHneBgyIwrw2
MHER+x6REsg/gzVBLuOmNbi+HcSMjLdf9JCs07yhTW/24qcXy9+9xLOtyXRJWiX3+eUKQx05l+gN
+BTqpqjWbbFGle+cIsoP053Cm556ZlptNTJOmgas6ggTiM2YQYM3JPj7LRZ/u15tmi0X25URA96I
6Z2Msg0xV9cE+tKPcHyR30AnAVYrinJN1OEhs9k1YwYmezYYBZQ4db3vMqDvpQjuQSgjxPP9pdF7
k5az60d/uRzE34ySbPPzKglNLFb7Mp7nP1OC6UbVZ38Tz8zIcVyKW6ufCFs3VicdfSNuxz0VlBYt
fEsvEUxkULI8z2es47pr/pWmmVz1z04Qhj3Uw2XHqZjU9WpUiMzvgpjgLzAEdF9oMIhQhDaCFQ42
6roT8WHm8i7Lx6N5yzIfMJb9Y2V+2XKtrw7x/esCr6TlcZwThBcB78VGQaLBgEkttTRUvY9IgDt6
7x6oDp7PrQfNxkrp+K4sg82/KJ1QYSJQR9qpBQCVFjwoz1zpUh8CLcSNb6IAWTtaRX3/jaE+8ren
JnMM7xM6JW6ZcuD9LcdRuT5wP5kWN/GEINloC2N02ar/uyMO9bFKbU9ojG8E7HOIh237wRprDAaZ
5U/AGb/glyb/LPoKytKBRJ/RVdTe1C6N9VRfSTPdbDvsCEzJgqKqYoMy5/TEM87Tlc9PES+WyBXX
z3mHqXDOKOmLBpeWGdSMxThTA9b0k1NSMB7lODEbZxPmxQQlNztY28YS3HvtF1zlyZmdmuUcz5eT
YTAmSMQ2XIq1sgrkLFFvMDhp8DAaNSblNvXZG/tcH0k6T0DB0WXiGG+EwE0Yjv//P5b+/f+e//4H
7YS4P851AABQSwECFAAUAAAICACDXCVcVJMoyZ5WAACUVgAAIgAAAAAAAAAAAAAAAAAAAAAAQnJv
Y2NvbGkgQ2hlZXNlIFNvdXAucGFwcmlrYXJlY2lwZVBLBQYAAAAAAQABAFAAAADeVgAAAAA=
```

## docs/template/examples/PaprikaApp Broccoli Cheese Soup.html

```html
﻿<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <style type="text/css">
            /* Shared styles */
            body {
                font-family: Helvetica, sans-serif;
                font-size: 16px;
                color: #34302e;
                margin: 0.25in;
            }
            @page {
                size: letter portrait;
                margin: 0.25in;
            }
            .name {
                font-size: 18px;
                font-family: Helvetica, sans-serif;
                font-weight: normal;
                margin: 0 0 10px 0;
            }
            .categories {
                color: #605D5D;
                font-size: 14px;
                font-family: Helvetica, sans-serif;
                font-style: italic;
            }
            .rating {
                color: #d10505;
                font-size: 14px;
            }
            .metadata {
                font-size: 14px;
            }
            .infobox p {
                margin: 0;
                line-height: 150%;
            }
            .subhead {
                color: #d10505;
                font-weight: bold;
                font-size: 14px;
                text-transform: uppercase;
                margin: 10px 0;
            }
            
            .ingredients p {
                margin: 4px 0;
            }
            /* To prevent nutrition/directions from getting too close
               to ingredients */
            .ingredients {
                padding-bottom: 10px;
            }
            .clear {
                clear:both;
            }
            a {
                color: #4990E2;
                text-decoration: none;
            }
            /* Full page specific styles */
            .text {
                line-height: 130%;
            }
            .photobox {
                float: left;
                margin-right: 14px;
                            }
            .photo {
                max-width: 140px;
                max-height: 140px;
                width: auto;
                height: auto;
            }
            .inline-image {
                max-width: 25%;
                max-height: 25%;
                width: auto;
                height: auto;
            }
            .photoswipe {
                border: 1px #dddddd solid;
                cursor: pointer;
            }
            .pswp__caption__center {
                text-align: center !important;
            }
            .recipe {
                page-break-after: always;
                            }
            .recipe:first-child {
                border-top: 0 none;
                margin-top: 0;
                padding-top: 0;
            }
        </style>
    </head>
    <body>
        <!-- Recipe -->
<div class="recipe" itemscope itemtype="http://schema.org/Recipe" >
    
    <div class="infobox">

        <!-- Image -->
        <div class="photobox">
            <a href="https://www.seriouseats.com/thmb/heRHM4n3T5_xv0IeMwmRMq6299E=/1500x0/filters:no_upscale():max_bytes(150000):strip_icc()/__opt__aboutcom__coeus__resources__content_migration__serious_eats__seriouseats.com__recipes__images__2016__10__20161008-broccoli-cheddar-soup-25-b56f6ad728a54810a26314a64f320f80.jpg">
                <img src="Images/DA870225-2DB1-47DF-8714-744C1DFCE8AD/60DB5461-B117-4DAF-8821-DD59AF80D2A7.jpg" itemprop="image" class="photo photoswipe"/>
            </a>
                    </div>

        <!-- Name -->
        <h1 itemprop="name" class="name">Broccoli Cheese Soup</h1>
        
        <!-- Info -->
        
        <!-- Rating, categories -->
        <p itemprop="aggregateRating" class="rating" value="0"></p>
        
        <p class="metadata">
        
            <!-- Cook time, prep time, servings, difficulty -->
            <b>Prep Time: </b><span itemprop="">5 mins</span>
            <b>Cook Time: </b><span itemprop="">50 mins</span>
            <b>Servings: </b><span itemprop="">6 servings</span>

            <!-- Source -->
                <b>Source: </b>
                    <a itemprop="url" href="https://www.seriouseats.com/broccoli-cheddar-cheese-soup-food-lab-recipe">
                        <span itemprop="author">Seriouseats.com</span>
                    </a>
                            
        </p>
        
        <div class="clear"></div>

    </div>
    
    <div class="left-column">

        <!-- Ingredients -->
        <div class="ingredientsbox">
            <h3 class="subhead">Ingredients</h3>
            <div class="ingredients text">
                <p class="line" itemprop="recipeIngredient"><strong>1 1/2</strong> pounds (700g) broccoli</p><p class="line" itemprop="recipeIngredient"><strong>2</strong> tablespoons (30ml) vegetable oil</p><p class="line" itemprop="recipeIngredient">Kosher salt and freshly ground black pepper</p><p class="line" itemprop="recipeIngredient"><strong>3</strong> tablespoons (45g) unsalted butter</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> medium onion, sliced (about 6 ounces; 170g)</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> medium carrot, peeled and finely diced (about 4 ounces; 120g)</p><p class="line" itemprop="recipeIngredient"><strong>3</strong> medium cloves garlic, thinly sliced</p><p class="line" itemprop="recipeIngredient"><strong>2</strong> cups (475ml) water, or homemade or store-bought low-sodium chicken stock</p><p class="line" itemprop="recipeIngredient"><strong>3</strong> cups (700ml) whole milk</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> small russet potato, peeled and sliced (about 4 ounces; 120g)</p><p class="line" itemprop="recipeIngredient"><strong>12</strong> ounces (340g) sharp cheddar cheese, grated (see notes)</p><p class="line" itemprop="recipeIngredient"><strong>8</strong> ounces (240g) deli-style American cheese, diced (see notes)</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> teaspoon (3g) mustard powder</p><p class="line" itemprop="recipeIngredient">Dash of hot sauce, such as Frank&apos;s RedHot</p>
            </div>
        </div>
        
        <!-- Nutrition (in two-column mode it goes below the ingredients) -->

    </div>
    
    <div class="right-column">
    
    <!-- Description -->

    <!-- Directions -->
    <div class="directionsbox">
        <h3 class="subhead">Directions</h3>
        <div itemprop="recipeInstructions" class="directions text">
            <p class="line">Separate broccoli into florets and stems. Cut florets into bite-size pieces and set aside. Roughly chop stems and reserve separately.</p><p class="line">Heat oil in a large Dutch oven over high heat until shimmering. Add broccoli florets and cook, without moving, until charred on the bottom, about 1 minute. Stir, season with salt and pepper, and continue cooking, stirring occasionally, until tender and charred on several surfaces, about 1 minute longer. Transfer to a rimmed baking sheet to cool.</p><p class="line">Return Dutch oven to medium heat and add butter, onion, carrot, and broccoli stems. Season with salt and pepper and cook, stirring frequently, until tender but not browned, about 5 minutes, lowering heat if necessary. Add garlic and cook, stirring, until fragrant, about 30 seconds.</p><p class="line">Add water or chicken stock, milk, and potato and bring to a boil over high heat. Reduce to a bare simmer and cook, stirring occasionally, until broccoli and potato are completely tender, about 30 minutes.</p><p class="line">In a large bowl, toss both cheeses together along with mustard powder. Using an immersion blender or working in batches with a countertop blender, blend soup, adding cheese a handful at a time, until completely smooth. Stir in hot sauce and season to taste with salt and pepper. Stir in reserved broccoli florets and pulse with blender a few more times until a few pieces are broken down, but most bite-size pieces remain. Serve immediately.</p>
        </div>
    </div>

    <!-- Notes -->


    <!-- Nutrition (in regular mode it goes below the notes) -->
        <!-- Used in two different places depending on the recipe layout -->
<div class="nutritionbox textbox">
    <h3 class="subhead">Nutrition</h3>
    <div itemprop="nutrition" class="nutrition text">
        <p>(per serving)<br/>615 Calories 44g Fat 29g Carbs 30g Protein<br/>Nutrition Facts<br/>Servings: 6<br/>Amount per serving<br/>Calories 615<br/>% Daily Value*<br/>Total Fat 44g 56%<br/>Saturated Fat 23g 114%<br/>Cholesterol 115mg 38%<br/>Sodium 1509mg 66%<br/>Total Carbohydrate 29g 10%<br/>Dietary Fiber 5g 19%<br/>Total Sugars 13g<br/>Protein 30g<br/>Vitamin C 81mg 403%<br/>Calcium 1157mg 89%<br/>Iron 2mg 11%<br/>Potassium 941mg 20%<br/>*The % Daily Value (DV) tells you how much a nutrient in a food serving contributes to a daily diet. 2,000 calories a day is used for general nutrition advice.</p>
    </div>
</div>

    
    </div>
    
    <div class="clear"></div>

</div>



    </body>
</html>
```

## docs/template/examples/recipesage-1767631101507-d892343ecccd93.json

```json
{"recipes":[{"@context":"http://schema.org","@type":"Recipe","identifier":"35b00969-7c88-462a-9aae-89bd277a8a17","datePublished":"2026-01-05T16:37:20.033Z","description":"","image":[],"name":"Slow Cooker Red Beans And Rice Recipe","prepTime":"PT15M","recipeIngredient":["Keep Screen Awake","1 pound dried red beans","3/4 pound smoked turkey sausage, thinly sliced","3  celery ribs, chopped","1  green bell pepper, chopped","1  red bell pepper, chopped","1  sweet onion, chopped","3  garlic cloves, minced","1 tablespoon Creole seasoning","Hot cooked long-grain rice","Hot sauce (optional)","Garnish: finely chopped green onions, finely chopped red onion"],"recipeInstructions":[{"@type":"HowToStep","text":"Combine first 8 ingredients and 7 cups water in a 4-qt. slow cooker. Cover and cook on HIGH 7 hours or until beans are tender."},{"@type":"HowToStep","text":"Serve red bean mixture with hot cooked rice, and, if desired, hot sauce. Garnish, if desired."},{"@type":"HowToStep","text":"Try These Twists!"},{"@type":"HowToStep","text":"Vegetarian Red Beans and Rice: Substitute frozen meatless smoked sausage, thawed and thinly sliced, for turkey sausage."},{"@type":"HowToStep","text":"Per cup (with 1 cup rice): Calories 422; Fat 5g (sat 4g, mono 2g, poly 2g); Protein 5g; Carb 4g; Fiber 2g; Chol 0mg; Iron 1mg; Sodium 530mg; Calc 113mg"},{"@type":"HowToStep","text":"Quick Skillet Red Beans and Rice: Substitute 2 (16-oz.) cans light kidney beans, drained and rinsed, for dried beans. Reduce Creole Seasoning to 2 tsp. Cook sausage and next 4 ingredients in a large nonstick skillet over medium heat, stirring often, 5 minutes or until sausage browns. Add garlic; saute 1 minute. Stir in 2 tsp. seasoning, beans, and 2 cups chicken broth. Bring to a boil; reduce heat to low, and simmer 20 minutes. Serve with hot cooked rice and, if desired, hot sauce. Garnish, if desired. Makes 8 cups. Hands-on Time: 26 min., Total Time: 46 min."}],"recipeYield":"Makes 10","totalTime":"PT7H","recipeCategory":[],"creditText":"","isBasedOn":"https://www.southernliving.com/recipes/slow-cooker-red-beans-rice-1","comment":[{"@type":"Comment","name":"Author Notes","text":""}]}]}```

## docs/template/examples/recipesage-1767633332725-b28c4512684ecf.json

```json
{"recipes":[{"@context":"http://schema.org","@type":"Recipe","identifier":"35b00969-7c88-462a-9aae-89bd277a8a17","datePublished":"2026-01-05T16:37:20.033Z","description":"Description","image":["https://chefbook-prod.s3.us-west-2.amazonaws.com/1767633319831-e68e7427a7bf90"],"name":"Slow Cooker Red Beans And Rice Recipe","prepTime":"PT15M","recipeIngredient":["Keep Screen Awake","1 pound dried red beans","3/4 pound smoked turkey sausage, thinly sliced","3  celery ribs, chopped","1  green bell pepper, chopped","1  red bell pepper, chopped","1  sweet onion, chopped","3  garlic cloves, minced","1 tablespoon Creole seasoning","Hot cooked long-grain rice","Hot sauce (optional)","Garnish: finely chopped green onions, finely chopped red onion"],"recipeInstructions":[{"@type":"HowToStep","text":"Combine first 8 ingredients and 7 cups water in a 4-qt. slow cooker. Cover and cook on HIGH 7 hours or until beans are tender."},{"@type":"HowToStep","text":"Serve red bean mixture with hot cooked rice, and, if desired, hot sauce. Garnish, if desired."},{"@type":"HowToStep","text":"Try These Twists!"},{"@type":"HowToStep","text":"Vegetarian Red Beans and Rice: Substitute frozen meatless smoked sausage, thawed and thinly sliced, for turkey sausage."},{"@type":"HowToStep","text":"Per cup (with 1 cup rice): Calories 422; Fat 5g (sat 4g, mono 2g, poly 2g); Protein 5g; Carb 4g; Fiber 2g; Chol 0mg; Iron 1mg; Sodium 530mg; Calc 113mg"},{"@type":"HowToStep","text":"Quick Skillet Red Beans and Rice: Substitute 2 (16-oz.) cans light kidney beans, drained and rinsed, for dried beans. Reduce Creole Seasoning to 2 tsp. Cook sausage and next 4 ingredients in a large nonstick skillet over medium heat, stirring often, 5 minutes or until sausage browns. Add garlic; saute 1 minute. Stir in 2 tsp. seasoning, beans, and 2 cups chicken broth. Bring to a boil; reduce heat to low, and simmer 20 minutes. Serve with hot cooked rice and, if desired, hot sauce. Garnish, if desired. Makes 8 cups. Hands-on Time: 26 min., Total Time: 46 min."}],"recipeYield":"Makes 10","totalTime":"PT7H","recipeCategory":["label example","label","example"],"creditText":"Source name","isBasedOn":"https://www.southernliving.com/recipes/slow-cooker-red-beans-rice-1","comment":[{"@type":"Comment","name":"Author Notes","text":"notes notes"}],"aggregateRating":{"@type":"AggregateRating","ratingValue":"3","ratingCount":"5"}}]}```

## docs/template/recipeDraftV1.schema.json

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "recipeDraftV1.schema.json",
  "title": "RecipeDraftV1",
  "description": "Schema for importing recipes into the cookbook application. Ingredient and unit IDs must be valid UUIDs that exist in the target database.",
  "type": "object",
  "required": ["schema_v", "recipe", "steps"],
  "additionalProperties": false,
  "properties": {
    "schema_v": {
      "const": 1,
      "description": "Schema version, must be 1"
    },
    "recipe": {
      "$ref": "#/$defs/Recipe"
    },
    "steps": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/Step"
      },
      "description": "Recipe steps in order. Must have at least one step."
    }
  },
  "$defs": {
    "Recipe": {
      "type": "object",
      "required": ["title"],
      "additionalProperties": false,
      "properties": {
        "title": {
          "type": "string",
          "minLength": 1,
          "description": "Recipe title (required, will be trimmed)"
        },
        "description": {
          "type": ["string", "null"],
          "description": "Brief description of the recipe"
        },
        "notes": {
          "type": ["string", "null"],
          "description": "Additional notes or tips"
        },
        "yield_units": {
          "type": "number",
          "minimum": 1,
          "default": 1,
          "description": "Number of servings/units the recipe makes (default: 1)"
        },
        "yield_phrase": {
          "type": ["string", "null"],
          "description": "Human-readable yield, e.g. '2 bowls' or '12 cookies'"
        },
        "yield_unit_name": {
          "type": ["string", "null"],
          "description": "Singular unit name, e.g. 'bowl' or 'cookie'"
        },
        "yield_detail": {
          "type": ["string", "null"],
          "description": "Additional yield details, e.g. 'Two generous bowls'"
        },
        "variants": {
          "type": ["array", "null"],
          "items": {
            "type": "string",
            "minLength": 1
          },
          "description": "Variant or variation notes extracted from the source"
        },
        "confidence": {
          "type": ["number", "null"],
          "minimum": 0,
          "maximum": 1,
          "description": "Confidence score of the recipe extraction (0.0 to 1.0)"
        }
      }
    },
    "Step": {
      "type": "object",
      "required": ["instruction", "ingredient_lines"],
      "additionalProperties": false,
      "properties": {
        "instruction": {
          "type": "string",
          "minLength": 1,
          "description": "Step instruction text (required, will be trimmed)"
        },
        "ingredient_lines": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/IngredientLine"
          },
          "description": "Ingredients used in this step"
        }
      }
    },
    "IngredientLine": {
      "type": "object",
      "required": ["ingredient_id", "quantity_kind"],
      "additionalProperties": false,
      "properties": {
        "ingredient_id": {
          "$ref": "#/$defs/UUID",
          "description": "UUID of the ingredient (must exist in database)"
        },
        "quantity_kind": {
          "type": "string",
          "enum": ["exact", "approximate", "unquantified"],
          "description": "Type of quantity: 'exact' for precise measurements, 'approximate' for cue-based or rough measurements (e.g., 'to taste', 'for pan'), 'unquantified' for items with no quantity cues"
        },
        "input_qty": {
          "type": ["number", "null"],
          "exclusiveMinimum": 0,
          "description": "Quantity amount. Required for exact, optional for approximate, must be null/omitted for unquantified."
        },
        "input_unit_id": {
          "oneOf": [
            { "$ref": "#/$defs/UUID" },
            { "type": "null" }
          ],
          "description": "UUID of the unit (must exist in database). Required for exact, optional for approximate, must be null/omitted for unquantified."
        },
        "note": {
          "type": ["string", "null"],
          "description": "Additional note, e.g. 'minced' or 'to taste'"
        },
        "raw_text": {
          "type": ["string", "null"],
          "description": "Original text from import source, e.g. '2 tsp minced garlic'"
        },
        "is_optional": {
          "type": "boolean",
          "default": false,
          "description": "Whether this ingredient is optional"
        }
      },
      "allOf": [
        {
          "if": {
            "properties": { "quantity_kind": { "const": "unquantified" } }
          },
          "then": {
            "properties": {
              "input_qty": { "type": "null" },
              "input_unit_id": { "type": "null" }
            }
          }
        },
        {
          "if": {
            "properties": { "quantity_kind": { "const": "exact" } }
          },
          "then": {
            "required": ["input_qty", "input_unit_id"],
            "properties": {
              "input_qty": { "type": "number", "exclusiveMinimum": 0 },
              "input_unit_id": { "$ref": "#/$defs/UUID" }
            }
          }
        }
      ]
    },
    "UUID": {
      "type": "string",
      "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
      "description": "UUID v4 format"
    }
  }
}
```

## docs/template/recipeDraftV1.ts

```ts
import { z } from "zod";

const FORBIDDEN_ORDER_KEYS = new Set(["step_number", "line_order"]);
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UuidSchema = z.string().regex(UUID_REGEX, "Invalid UUID");

type PathSegment = string | number;

const IngredientLineSchema = z
  .object({
    ingredient_id: UuidSchema,
    quantity_kind: z.enum(["exact", "approximate", "unquantified"]),
    input_qty: z.number().positive().optional().nullable(),
    input_unit_id: UuidSchema.optional().nullable(),
    note: z.string().optional().nullable(),
    raw_text: z.string().optional().nullable(),
    is_optional: z.boolean().optional().default(false),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hasQty = value.input_qty !== null && value.input_qty !== undefined;
    const hasUnit =
      value.input_unit_id !== null && value.input_unit_id !== undefined;

    if (value.quantity_kind === "unquantified") {
      if (hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty must be null or omitted for unquantified lines.",
        });
      }
      if (hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message:
            "input_unit_id must be null or omitted for unquantified lines.",
        });
      }
      return;
    }

    if (value.quantity_kind === "exact") {
      if (!hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty is required for exact lines.",
        });
      }

      if (!hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message: "input_unit_id is required for exact lines.",
        });
      }
      return;
    }

    if (value.quantity_kind === "approximate") {
      if (hasQty !== hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: hasQty ? ["input_unit_id"] : ["input_qty"],
          message: "input_qty and input_unit_id must be provided together for approximate lines.",
        });
      }
    }
  });

const StepSchema = z
  .object({
    instruction: z.string().trim().min(1),
    ingredient_lines: z.array(IngredientLineSchema),
  })
  .strict();

const RecipeSchema = z
  .object({
    title: z.string().trim().min(1),
    description: z.string().optional().nullable(),
    notes: z.string().optional().nullable(),
    yield_units: z.number().min(1).optional().default(1),
    yield_phrase: z.string().optional().nullable(),
    yield_unit_name: z.string().optional().nullable(),
    yield_detail: z.string().optional().nullable(),
    variants: z.array(z.string().trim().min(1)).optional().nullable(),
    confidence: z.number().min(0).max(1).optional().nullable(),
  })
  .strict();

export const RecipeDraftV1Schema = z
  .object({
    schema_v: z.literal(1),
    recipe: RecipeSchema,
    steps: z.array(StepSchema).min(1),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hits: { path: PathSegment[]; key: string }[] = [];

    const scan = (current: unknown, path: PathSegment[]) => {
      if (Array.isArray(current)) {
        current.forEach((item, index) => scan(item, [...path, index]));
        return;
      }

      if (current && typeof current === "object") {
        for (const [key, child] of Object.entries(
          current as Record<string, unknown>,
        )) {
          if (FORBIDDEN_ORDER_KEYS.has(key)) {
            hits.push({ path: [...path, key], key });
          }
          scan(child, [...path, key]);
        }
      }
    };

    scan(value, []);

    hits.forEach((hit) => {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: hit.path,
        message: `${hit.key} is server-derived and must not appear in drafts.`,
      });
    });
  });

export type RecipeDraftV1 = z.infer<typeof RecipeDraftV1Schema>;

export function parseRecipeDraftV1(input: unknown): RecipeDraftV1 {
  return RecipeDraftV1Schema.parse(input);
}

export function formatZodError(err: unknown): string {
  if (err instanceof z.ZodError) {
    return err.issues
      .map((issue) => {
        const path = issue.path.length ? issue.path.join(".") : "input";
        return `${path}: ${issue.message}`;
      })
      .join("\n");
  }

  if (err instanceof Error) {
    return err.message;
  }

  return "Unknown validation error.";
}
```

## docs/tips/README.md

```markdown
---
summary: "Tip extraction, classification, taxonomy tagging, and evaluation."
read_when:
  - Working on tip/knowledge extraction
  - Tuning tip precision or recall
  - Building golden sets for tip evaluation
---

# Tip Extraction Pipeline

**Location:** `cookimport/parsing/tips.py`

The tip extraction system identifies standalone kitchen wisdom from cookbook content.

## Tip Classification

Tips are classified by scope:

| Scope | Description | Example |
|-------|-------------|---------|
| `general` | Reusable kitchen wisdom | "Toast spices in a dry pan to release oils." |
| `recipe_specific` | Notes tied to one recipe | "This soup freezes well for up to 3 months." |
| `not_tip` | False positive | Copyright notices, ads, narrative prose |

---

## Extraction Strategy

### From Recipes

Tips extracted from recipe content:
1. Scan description, notes, and instruction comments
2. Look for tip markers (see Advice Anchors below)
3. Classify scope based on generality signals

### From Standalone Blocks

Content not assigned to recipes:
1. Chunk into containers (by section headers)
2. Split containers into atoms (individual sentences/points)
3. Apply tip detection heuristics
4. Generate topic candidates for non-tip content

---

## Detection Heuristics

### Advice Anchors (Required)

Tips must contain explicit advice language:

**Modal verbs:** can, should, must, need to, ought to, have to
**Imperatives:** use, try, avoid, choose, store, keep, serve, add, make sure
**Conditionals:** if you, when you, for best results

### Cooking Anchors (Gate)

At least one cooking-related term must be present:
- Techniques: sauté, roast, simmer, marinate
- Equipment: pan, oven, pot, knife
- Ingredients: butter, salt, garlic, onion
- Outcomes: crispy, tender, golden, caramelized

### Narrative Rejection

Reject tip-like content that's actually narrative:
- Story-telling patterns ("I remember when...", "My grandmother used to...")
- Long flowing paragraphs without actionable advice
- Historical or biographical content

---

## Taxonomy Tagging

Tips are tagged with relevant anchors (`TipTags` model):

| Category | Examples |
|----------|----------|
| `recipes` | Recipe names mentioned |
| `dishes` | pasta, soup, salad, stew |
| `meats` | chicken, beef, pork, fish |
| `vegetables` | onion, garlic, tomato, carrot |
| `herbs` | basil, thyme, rosemary, cilantro |
| `spices` | cumin, paprika, cinnamon, pepper |
| `dairy` | butter, cream, cheese, milk |
| `grains` | rice, bread, flour, pasta |
| `techniques` | sauté, roast, braise, poach |
| `cooking_methods` | baking, grilling, frying, steaming |
| `tools` | pan, oven, knife, blender |

---

## Atom Chunking

**Location:** `cookimport/parsing/atoms.py`

Large blocks are split into atomic units for better precision:

```
Container: "COOKING TIPS" section
  └─ Atom 1: "Toast whole spices before grinding."
  └─ Atom 2: "Store herbs wrapped in damp paper towels."
  └─ Atom 3: "Let meat rest before slicing."
```

Each atom includes context:
- `context_prev`: Previous atom text (for context)
- `context_next`: Next atom text (for context)
- `container_header`: Section header if present

---

## Topic Candidates

Content that doesn't qualify as tips but may be valuable:
- Ingredient guides ("All About Olive Oil")
- Technique explanations ("How to Julienne Vegetables")
- Equipment recommendations ("Choosing the Right Pan")

Topic candidates are stored separately for potential future use.

---

## Tuning Guide

### Precision vs Recall

**To increase precision** (fewer false positives):
- Tighten advice anchor requirements
- Add more narrative rejection patterns
- Require more cooking anchors

**To increase recall** (catch more tips):
- Add advice anchor words
- Relax cooking anchor requirements
- Reduce minimum generality score

### Key Knobs

Located in `cookimport/parsing/tips.py`:

1. **Advice anchor patterns** - Regex patterns for tip-like language
2. **Cooking anchor terms** - Required domain vocabulary
3. **Narrative rejection patterns** - Story-telling indicators
4. **Generality threshold** - Score cutoff for general vs recipe-specific

### Override Support

Per-cookbook overrides via `ParsingOverrides`:
- `tip_headers`: Additional section headers to treat as tip containers
- `tip_prefixes`: Line prefixes that indicate tips ("TIP:", "NOTE:")

---

## Evaluation Harness

**Location:** `docs/tips/` (this doc) + Label Studio integration

### Building Golden Sets

1. Run tip extraction on test cookbook
2. Export tip candidates to Label Studio
3. Annotate: correct scope, correct/incorrect extraction
4. Export labeled data as golden set JSONL

### Scoring

```bash
# Run evaluation against golden set
python -m cookimport.evaluation.tips --golden golden_tips.jsonl --predicted predicted_tips.jsonl
```

Metrics:
- **Precision**: % of extracted tips that are correct
- **Recall**: % of actual tips that were extracted
- **Scope accuracy**: % of tips with correct scope classification

### A/B Testing Workflow

1. Establish baseline metrics on golden set
2. Modify heuristics
3. Re-run extraction
4. Compare metrics
5. Keep changes only if metrics improve
```

## docs/understandings/2026-01-31-step-ingredient-splitting.md

```markdown
---
summary: "Notes on step-ingredient assignment, split gating, and confidence penalties."
read_when:
  - When adjusting step-ingredient matching or split behavior
---

Step-ingredient linking (`cookimport/parsing/step_ingredients.py`) uses a two-phase match: candidate collection per step via alias matching, then a global resolution that assigns each ingredient to a single best step unless a strong split signal (fraction/remaining/reserved) appears in multiple steps. Multi-step assignments now apply a small confidence penalty on the split ingredient lines to flag them for review.
```

## docs/understandings/2026-02-02-epub-job-splitting.md

```markdown
---
summary: "Notes on EPUB job splitting and spine-index ordering for merges."
read_when:
  - When modifying EPUB job splitting or merge ordering
---

# EPUB Job Splitting Notes (2026-02-02)

- EPUB blocks are emitted as a linear list with `start_block`/`end_block` provenance indices, so split jobs need a stable global ordering key.
- Each spine item is processed with a `spine_index` feature on blocks, and recipe provenance records `start_spine`/`end_spine` so merge ordering can sort by spine index before local block indices.
- Split jobs write raw artifacts into `.job_parts/<workbook>/job_<index>/raw/`, then the main merge step moves them into `raw/` and rewrites recipe IDs to a single global sequence.
```

## docs/understandings/2026-02-02-pdf-job-merge-and-fallback.md

```markdown
---
summary: "Notes on PDF job merge ordering, ID rewrites, and serial fallback behavior."
read_when:
  - When modifying PDF job merging or troubleshooting job-split staging runs
---

# PDF Job Merge and Fallback Notes (2026-02-02)

- Split PDF jobs return `ConversionResult` payloads without raw artifacts; the main process merges recipes, tip candidates, topic candidates, and non-recipe blocks, then recomputes tips and chunks before writing outputs.
- Recipe IDs are rewritten to a global `c0..cN` sequence ordered by `provenance.location.start_page` (falling back to `start_block`), and any tip `sourceRecipeId` references are updated via the same mapping.
- Raw artifacts are written under `.job_parts/<workbook_slug>/job_<index>/raw/` during job execution, then moved into `raw/` with filename prefixing on collisions once the merge completes.
- If `ProcessPoolExecutor` fails to initialize (PermissionError), staging falls back to serial job execution so CLI/test runs can still complete.
```

## docs/understandings/2026-02-02-stage-worker-pdf-job-surface.md

```markdown
---
summary: "Notes on current stage->worker flow and PDF conversion surfaces relevant to job splitting."
read_when:
  - When adding job-level parallelism or page-range processing for PDF ingestion
---

# Stage/Worker/PDF Surfaces (2026-02-02)

- `cookimport/cli.py` `stage` plans jobs (one per file, or multiple page-range jobs for large PDFs), spins a `ProcessPoolExecutor`, and calls either `cookimport/cli_worker.py:stage_one_file` (non-split) or `cookimport/cli_worker.py:stage_pdf_job` (split). Progress updates come through a `multiprocessing.Manager().Queue()` and are rendered in the Live dashboard with page-range labels.
- `stage_one_file` in `cookimport/cli_worker.py` resolves the importer, runs `importer.inspect` if no mapping, then `importer.convert`, applies optional limits, builds knowledge chunks, enriches the report, and writes outputs via `cookimport/staging/writer.py`.
- `stage_pdf_job` runs a page-range conversion, writes raw artifacts into a `.job_parts/<workbook_slug>/job_<index>/raw/` temp folder, and returns a mergeable `ConversionResult` payload to the main process.
- `cookimport/plugins/pdf.py:PdfImporter.convert` can now process a page range (OCR or text extraction) and initially assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}` before the merge step rewrites them to a global sequence.
- `cookimport/ocr/doctr_engine.py:ocr_pdf` accepts `start_page` and `end_page` (exclusive), and returns absolute page numbers (1-based) for OCR blocks.
```

## docs/understandings/2026-02-02-worker-progress-dashboard.md

```markdown
---
summary: "Notes on worker progress reporting and split-job scheduling in the stage CLI."
read_when:
  - When adjusting the CLI worker dashboard or progress updates
  - When debugging stalled progress during split EPUB/PDF jobs
---

The stage CLI builds a list of `JobSpec` entries, splitting large EPUB/PDF inputs into spine/page-range jobs when configured. Each job runs in a ProcessPool worker (`stage_epub_job`, `stage_pdf_job`, or `stage_one_file`) and reports progress through a `multiprocessing.Manager().Queue()` to the live dashboard. The dashboard only knows what the workers last reported, so stale entries can appear if no updates arrive. After all split jobs for a file finish, the main process merges results; the progress bar tracks job completion, not merge time.
```

```

## docs/AGENTS.md

```markdown
---
summary: "Rules for working in /docs and key references."
read_when:
  - When editing documentation in /docs
---

# Agent Guidelines — /docs

This folder contains project documentation. Check folder-specific AGENTS.md files elsewhere for domain-specific guidance.

## Docs workflow

- Run `npm run docs:list` (or `npx tsx docs/docs-list.ts`) to see summaries and Read when hints.
- Read any doc whose Read when matches your task before coding.
- Keep docs current with behavior/API changes; add read_when hints on cross-cutting docs.

## Docs front matter (required)

Each `docs/**/*.md` file must start with front matter:

```md
---
summary: "One-line summary"
read_when:
  - "When this doc should be read"
---
```

`read_when` is optional but recommended.```

## docs/AI_Context.md

```markdown
---
summary: "AI Onboarding & Project Summary for the cookimport project."
read_when:
  - When an AI agent or new developer needs a technical overview of the architecture, tech stack, and data flow
  - When you need to understand how recipe ingestion and parsing works in this codebase
---

# AI Onboarding & Project Summary: Recipe Import Pipeline

This document provides a technical overview of the `cookimport` project. It is designed to help AI developers and AI chatbots (who may not have direct access to the codebase) understand the architecture, data flow, and key algorithms.

## 1. Project Purpose

The `cookimport` project is a **recipe ingestion and normalization pipeline** that transforms messy, real-world recipe sources into structured, high-fidelity data. It handles:

- **Legacy Excel spreadsheets** with varying layouts (wide, tall, template-based)
- **EPUB cookbooks** with unstructured text requiring segmentation
- **PDF documents** (including scanned images with OCR)
- **Proprietary app archives**: Paprika (.paprikarecipes) and RecipeSage (.zip/JSON)
- **Plain text/Word documents**

### Key Objectives

1. **Universal Ingestion**: Handle diverse formats and layouts through a plugin-based architecture where each source type has a dedicated importer.

2. **Two-Phase Pipeline**:
   - **Phase 1 (Ingestion)**: Extract raw content and normalize to an intermediate JSON-LD format based on schema.org Recipe.
   - **Phase 2 (Transformation)**: Parse ingredients into structured fields, link ingredients to instruction steps, and produce the final `RecipeDraftV1` format.

3. **100% Traceability**: Every output field is traceable back to its source via a `provenance` metadata system that records file hashes, block indices, and extraction methods.

4. **Knowledge Extraction**: Beyond recipe scraping, the system identifies and extracts standalone "Kitchen Tips" and topical content.

## 2. Tech Stack & Active Dependencies

The project is built with **Python 3.12**. Key libraries:

### Core Frameworks
| Library | Purpose |
|---------|---------|
| **[Typer](https://typer.tiangolo.com/)** | Powers the CLI interface (`cookimport`, `C3imp`, `C3import` commands) |
| **[Pydantic V2](https://docs.pydantic.dev/)** | Strict data validation, schema enforcement, and JSON serialization for all models |
| **[Rich](https://rich.readthedocs.io/)** | Console output formatting, progress spinners, and status updates during processing |
| **[Questionary](https://questionary.readthedocs.io/)** | Interactive CLI prompts for guided workflows |

### Specialized Parsers (Production Use)
| Library | Purpose |
|---------|---------|
| **[Ingredient Parser](https://ingredient-parser.readthedocs.io/)** | NLP-based decomposition of ingredient strings into quantity, unit, item, preparation, and notes |
| **[PyMuPDF (fitz)](https://pymupdf.readthedocs.io/)** | High-performance PDF text and layout extraction |
| **[python-doctr](https://mindee.github.io/doctr/)** | Deep learning OCR for scanned PDFs (uses CRNN + ResNet architectures) |
| **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + [lxml](https://lxml.de/)** | HTML parsing for EPUB content and app archive formats |
| **[EbookLib](https://github.com/aerkalov/ebooklib)** | EPUB container structure management with fallback to raw ZIP parsing |
| **[Openpyxl](https://openpyxl.readthedocs.io/)** | Excel file processing with complex layout detection |
| **[python-docx](https://python-docx.readthedocs.io/)** | Word document text and table extraction |

### Quality Assurance & Evaluation
| Library | Purpose |
|---------|---------|
| **[Label Studio SDK](https://labelstud.io/)** | Creating ground-truth datasets for benchmarking parser accuracy |

## 3. Architecture Overview

### 3.1 Plugin System

The project uses a **registry-based plugin architecture** where each source format has a dedicated importer class:

```
cookimport/plugins/
  ├── registry.py      # Plugin registry with best_importer_for_path()
  ├── epub.py          # EPUB cookbook importer
  ├── pdf.py           # PDF document importer
  ├── excel.py         # Excel spreadsheet importer
  ├── paprika.py       # Paprika app archive importer
  ├── recipesage.py    # RecipeSage JSON archive importer
  └── text.py          # Plain text / Word document importer
```

Each plugin implements:
- `detect(path) -> float`: Returns confidence score (0.0-1.0) that this plugin can handle the file
- `inspect(path) -> WorkbookInspection`: Quick analysis of file structure
- `convert(path, mapping, progress_callback) -> ConversionResult`: Full extraction

### 3.2 Core Data Models

The system uses Pydantic models for type-safe data flow (see `cookimport/core/models.py`):

| Model | Purpose |
|-------|---------|
| `RecipeCandidate` | Intermediate format (schema.org JSON-LD compatible) with name, ingredients, instructions, metadata |
| `TipCandidate` | Extracted kitchen tip with scope (general, recipe_specific, not_tip) and taxonomy tags |
| `TopicCandidate` | Topical content block (sections about techniques, ingredient guides, etc.) |
| `ConversionResult` | Container for recipes, tips, topics, raw artifacts, and conversion report |
| `Block` | Low-level text block with type, HTML source, font weight, and feature flags |

### 3.3 Block & Signals Architecture

For unstructured sources (EPUB, PDF, text), the pipeline uses a **Block-based extraction model**:

1. **Block Extraction**: Source content is converted to a linear sequence of `Block` objects, each representing a paragraph, heading, or list item.

2. **Signal Enrichment** (`cookimport/parsing/signals.py`): Each block is analyzed for features:
   - `is_heading`, `heading_level` - Typography signals
   - `is_ingredient_header`, `is_instruction_header` - Section markers
   - `is_yield`, `is_time` - Metadata phrases
   - `starts_with_quantity`, `has_unit` - Ingredient signals
   - `is_instruction_likely`, `is_ingredient_likely` - Content classification

3. **Candidate Detection**: Blocks are segmented into recipe candidates using heuristics:
   - Backtracking from anchor points (yield phrases, ingredient headers)
   - Forward scanning with section boundary detection
   - Scoring based on ingredient/instruction density

## 4. Key Algorithms

### 4.1 Ingredient-Step Linking (Two-Phase Algorithm)

The step-ingredient linking algorithm (`cookimport/parsing/step_ingredients.py`) assigns each ingredient to the instruction step(s) where it's used:

**Phase 1: Candidate Collection**
- For each step, scan for mentions of each ingredient using multiple aliases (full text, cleaned text, head/tail tokens)
- Classify verb context: "use" verbs (add, mix, stir), "reference" verbs (cook, let rest), "split" signals (half, remaining)
- Score matches based on alias length, token overlap, and context

**Phase 2: Resolution**
- Default: Single best step wins (highest score)
- Exception: Multi-step assignment when split language detected ("add half the butter... add remaining butter")
- Fraction calculation for split ingredients (e.g., 0.5 each for "half/remaining" pattern)

This approach handles:
- Section headers grouping ingredients (e.g., "For the Sauce")
- "All ingredients" phrases that assign everything to a step
- Weak match filtering to avoid false positives

### 4.2 Ingredient Parsing

The ingredient parser (`cookimport/parsing/ingredients.py`) wraps the `ingredient-parser-nlp` library:

```python
"3 stalks celery, sliced" -> {
    "quantity_kind": "exact",
    "input_qty": 3.0,
    "raw_unit_text": "stalks",
    "raw_ingredient_text": "celery",
    "preparation": "sliced",
    "is_optional": False,
    "confidence": 0.92
}
```

Special handling for:
- Section headers (e.g., "MARINADE:", "For the Filling")
- Range quantities (e.g., "3-4 cups" -> midpoint rounded up)
- Approximate quantities ("to taste", "as needed")

### 4.3 Variant Extraction

Recipes may contain variant instructions. The system (`cookimport/staging/draft_v1.py`) extracts these:

- Detects "Variation:" or "Variant:" headers
- Separates variant content from main instructions
- Stores variants as a separate array in the recipe output

### 4.4 Tip Classification

Tips are classified by scope (`cookimport/parsing/tips.py`):
- **general**: Standalone kitchen wisdom (reusable across recipes)
- **recipe_specific**: Notes tied to a particular recipe
- **not_tip**: Content that looks like a tip but isn't (copyright notices, ads)

## 5. Data Flow & Processing Stages

### Stage 1: Ingestion (`cookimport stage` command)
1. **Detection**: Plugins score confidence for handling the file
2. **Inspection**: Analyze internal structure (layout, headers, sections)
3. **Extraction**: Convert to `RecipeCandidate` objects with provenance
4. **Raw Artifacts**: Store extracted blocks as JSON for auditing

### Stage 2: Transformation
1. **Ingredient Parsing**: Lines parsed into structured components
2. **Instruction Parsing**: Extract time/temperature metadata
3. **Step Linking**: Assign ingredients to steps
4. **Tip Extraction**: Identify standalone tips and topics

### Stage 3: Output
- **Intermediate Drafts**: JSON-LD format in `{timestamp}/intermediate drafts/`
- **Final Drafts**: RecipeDraftV1 format in `{timestamp}/final drafts/`
- **Tips**: Extracted tips in `{timestamp}/tips/`
- **Reports**: Conversion summary with stats and warnings

## 6. Label Studio Integration

The project includes deep integration with Label Studio for building ground-truth datasets:

### Chunking Strategies
- **Structural Chunks**: Recipe-level units for validating segmentation
- **Atomic Chunks**: Line-level units for validating ingredient parsing

### Workflow
1. `cookimport labelstudio-import`: Upload chunks to Label Studio project
2. Annotate in Label Studio UI
3. `cookimport labelstudio-export`: Export labeled data as JSONL golden set

## 7. Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Excel Ingestion | **Active** | Wide, Tall, and Template layouts |
| App Archives | **Active** | Paprika and RecipeSage support |
| EPUB/PDF/Text | **Active** | Heuristic segmentation with variant extraction |
| OCR (docTR) | **Active** | For scanned PDFs, uses CRNN + ResNet |
| Ingredient Parsing | **Active** | NLP-based with confidence scores |
| Step-Ingredient Linking | **Active** | Two-phase algorithm with split detection |
| Tip Extraction | **Active** | Taxonomy tagging and scope classification |
| Label Studio | **Active** | Benchmarking and dataset export |
| LLM Repair | **Mocked** | Structure exists, calls return mock data |

## 8. Directory Map

```
cookimport/
├── core/           # Engine: Models, Reporting, Registry, Scoring
├── plugins/        # Adapters: Source-specific extraction (Excel, EPUB, etc.)
├── parsing/        # Brains: Ingredient parsing, Tip taxonomy, Step linking
│   ├── ingredients.py      # Ingredient line parsing
│   ├── step_ingredients.py # Two-phase step linking
│   ├── signals.py          # Block feature enrichment
│   ├── tips.py             # Tip extraction and classification
│   └── atoms.py            # Atomic text unit handling
├── staging/        # Output: Writers, JSON-LD, Draft V1
├── labelstudio/    # Benchmarking: Chunking, client, export
├── llm/            # (Mocked) LLM integration layer
└── ocr/            # docTR OCR engine for scanned documents

data/
├── input/          # Place source files here
└── output/         # Generated outputs appear here

tests/              # Comprehensive test suite
```

## 9. CLI Commands

| Command | Purpose |
|---------|---------|
| `cookimport` | Interactive mode with guided prompts |
| `cookimport stage <path>` | Stage recipes from file/folder |
| `cookimport inspect <path>` | Preview file structure and layout |
| `cookimport labelstudio-import` | Upload to Label Studio |
| `cookimport labelstudio-export` | Export labeled data |

Environment variables:
- `C3IMP_LIMIT`: Limit recipes per file (for testing)
- `LABEL_STUDIO_URL`: Label Studio server URL
- `LABEL_STUDIO_API_KEY`: Label Studio API key
```

## docs/IMPORTANT CONVENTIONS.md

```markdown
---
summary: "Project-wide coding and organization conventions for the import tooling."
read_when:
  - Before starting any new implementation
  - When organizing output folders or defining new models
---

# Important Conventions

- The import tooling lives in the Python package `cookimport/`, with the CLI entrypoint exposed as the `cookimport` script via `pyproject.toml`.
- Core shared models are defined in `cookimport/core/models.py`, and staging JSON-LD helpers live in `cookimport/staging/`.
- Staging output folders use workbook stems (no file extension) for `intermediate drafts/<workbook>/...`, `final drafts/<workbook>/...`, and report names, while provenance still records the full filename.
- Outputs are flattened per source file (no sheet subfolders) and named `r{index}.json[ld]` in the order recipes are emitted. Tip snippets are written separately as `tips/{workbook}/t{index}.json` and include `sourceRecipeTitle`, `sourceText`, `scope` (`general`/`recipe_specific`/`not_tip`), `standalone`, `generalityScore`, and tag categories (including `dishes` and `cookingMethods`) when tied to a recipe. Each tips folder also includes `tips.md`, a markdown list of the tip `text` fields grouped by source block, annotated with `t{index}` ids plus anchor tags, and prefixed by any detected topic header line for quick review. Topic candidates captured before tip classification are written as `tips/{workbook}/topic_candidates.json` and `tips/{workbook}/topic_candidates.md`; these are atom-level snippets with container headers and adjacent-atom context recorded under `provenance.atom` and `provenance.location`.
- Stable IDs still derive from provenance (`row_index`/`rowIndex` for Excel, `location.chunk_index` for non-tabular importers).
- Draft V1 ingredient text fields (`raw_text`, `raw_ingredient_text`, `raw_unit_text`, `note`, `preparation`) are lowercased on output.
- `ConversionResult.tipCandidates` stores all classified tip candidates (`general`, `recipe_specific`, `not_tip`), while `ConversionResult.tips` contains only standalone general tips for output.
- Recipe-derived tips default to `recipe_specific`; exported tips primarily come from non-recipe text unless a tip reads strongly general.
- Conversion reports include `runTimestamp` (local ISO-8601 time) for when the stage run started.
- Conversion reports include `outputStats` with per-output file counts/bytes (and largest files) to help debug slow writes.
- Raw artifacts are preserved under `staging/raw/<importer>/<source_hash>/<location_id>.<ext>` for auditing (JSON snippets for structured sources, text/blocks for unstructured sources).
- PDF page-range jobs and EPUB spine-range jobs (when a large source is split across workers) write raw artifacts to `staging/.job_parts/<workbook_slug>/job_<index>/raw/...` and the main process merges them back into `staging/raw/` after the merge completes. Temporary `.job_parts` folders may remain only if a merge fails.
- Cookbook-specific parsing overrides live in the `parsingOverrides` section of mapping files or in `*.overrides.yaml` sidecars passed via `cookimport stage --overrides`.
- Label Studio benchmark artifacts are written under `data/output/<timestamp>/labelstudio/<book_slug>/`, including `extracted_archive.json`, `label_studio_tasks.jsonl`, and `exports/golden_set_tip_eval.jsonl` after label export.
```

## docs/PLANS.md

```markdown
---
summary: "ExecPlan requirements, format, and workflow rules."
read_when:
  - When authoring or updating ExecPlans
---

# Codex Execution Plans (ExecPlans):
 
This document describes the requirements for an execution plan ("ExecPlan"), a design document that a coding agent can follow to deliver a working feature or system change. Treat the reader as a complete beginner to this repository: they have only the current working tree and the single ExecPlan file you provide. There is no memory of prior plans and no external context.
 
## How to use ExecPlans and PLANS.md
 
When authoring an executable specification (ExecPlan), follow PLANS.md _to the letter_. If it is not in your context, refresh your memory by reading the entire PLANS.md file. Be thorough in reading (and re-reading) source material to produce an accurate specification. When creating a spec, start from the skeleton and flesh it out as you do your research.
 
When implementing an executable specification (ExecPlan), do not prompt the user for "next steps"; simply proceed to the next milestone. Keep all sections up to date, add or split entries in the list at every stopping point to affirmatively state the progress made and next steps. Resolve ambiguities autonomously, and commit frequently.
 
When discussing an executable specification (ExecPlan), record decisions in a log in the spec for posterity; it should be unambiguously clear why any change to the specification was made. ExecPlans are living documents, and it should always be possible to restart from _only_ the ExecPlan and no other work.
 
When researching a design with challenging requirements or significant unknowns, use milestones to implement proof of concepts, "toy implementations", etc., that allow validating whether the user's proposal is feasible. Read the source code of libraries by finding or acquiring them, research deeply, and include prototypes to guide a fuller implementation.
 
## Requirements
 
NON-NEGOTIABLE REQUIREMENTS:
 
* Every ExecPlan must be fully self-contained. Self-contained means that in its current form it contains all knowledge and instructions needed for a novice to succeed.
* Every ExecPlan is a living document. Contributors are required to revise it as progress is made, as discoveries occur, and as design decisions are finalized. Each revision must remain fully self-contained.
* Every ExecPlan must enable a complete novice to implement the feature end-to-end without prior knowledge of this repo.
* Every ExecPlan must produce a demonstrably working behavior, not merely code changes to "meet a definition".
* Every ExecPlan must define every term of art in plain language or do not use it.
 
Purpose and intent come first. Begin by explaining, in a few sentences, why the work matters from a user's perspective: what someone can do after this change that they could not do before, and how to see it working. Then guide the reader through the exact steps to achieve that outcome, including what to edit, what to run, and what they should observe.
 
The agent executing your plan can list files, read files, search, run the project, and run tests. It does not know any prior context and cannot infer what you meant from earlier milestones. Repeat any assumption you rely on. Do not point to external blogs or docs; if knowledge is required, embed it in the plan itself in your own words. If an ExecPlan builds upon a prior ExecPlan and that file is checked in, incorporate it by reference. If it is not, you must include all relevant context from that plan.
 
## Formatting
 
Format and envelope are simple and strict. Each ExecPlan must be one single fenced code block labeled as `md` that begins and ends with triple backticks. Do not nest additional triple-backtick code fences inside; when you need to show commands, transcripts, diffs, or code, present them as indented blocks within that single fence. Use indentation for clarity rather than code fences inside an ExecPlan to avoid prematurely closing the ExecPlan's code fence. Use two newlines after every heading, use # and ## and so on, and correct syntax for ordered and unordered lists.
 
When writing an ExecPlan to a Markdown (.md) file where the content of the file *is only* the single ExecPlan, you should omit the triple backticks.
 
Write in plain prose. Prefer sentences over lists. Avoid checklists, tables, and long enumerations unless brevity would obscure meaning. Checklists are permitted only in the `Progress` section, where they are mandatory. Narrative sections must remain prose-first.
 
## Guidelines
 
Self-containment and plain language are paramount. If you introduce a phrase that is not ordinary English ("daemon", "middleware", "RPC gateway", "filter graph"), define it immediately and remind the reader how it manifests in this repository (for example, by naming the files or commands where it appears). Do not say "as defined previously" or "according to the architecture doc." Include the needed explanation here, even if you repeat yourself.
 
Avoid common failure modes. Do not rely on undefined jargon. Do not describe "the letter of a feature" so narrowly that the resulting code compiles but does nothing meaningful. Do not outsource key decisions to the reader. When ambiguity exists, resolve it in the plan itself and explain why you chose that path. Err on the side of over-explaining user-visible effects and under-specifying incidental implementation details.
 
Anchor the plan with observable outcomes. State what the user can do after implementation, the commands to run, and the outputs they should see. Acceptance should be phrased as behavior a human can verify ("after starting the server, navigating to [http://localhost:8080/health](http://localhost:8080/health) returns HTTP 200 with body OK") rather than internal attributes ("added a HealthCheck struct"). If a change is internal, explain how its impact can still be demonstrated (for example, by running tests that fail before and pass after, and by showing a scenario that uses the new behavior).
 
Specify repository context explicitly. Name files with full repository-relative paths, name functions and modules precisely, and describe where new files should be created. If touching multiple areas, include a short orientation paragraph that explains how those parts fit together so a novice can navigate confidently. When running commands, show the working directory and exact command line. When outcomes depend on environment, state the assumptions and provide alternatives when reasonable.
 
Be idempotent and safe. Write the steps so they can be run multiple times without causing damage or drift. If a step can fail halfway, include how to retry or adapt. If a migration or destructive operation is necessary, spell out backups or safe fallbacks. Prefer additive, testable changes that can be validated as you go.
 
Validation is not optional. Include instructions to run tests, to start the system if applicable, and to observe it doing something useful. Describe comprehensive testing for any new features or capabilities. Include expected outputs and error messages so a novice can tell success from failure. Where possible, show how to prove that the change is effective beyond compilation (for example, through a small end-to-end scenario, a CLI invocation, or an HTTP request/response transcript). State the exact test commands appropriate to the project’s toolchain and how to interpret their results.
 
Capture evidence. When your steps produce terminal output, short diffs, or logs, include them inside the single fenced block as indented examples. Keep them concise and focused on what proves success. If you need to include a patch, prefer file-scoped diffs or small excerpts that a reader can recreate by following your instructions rather than pasting large blobs.
 
## Milestones
 
Milestones are narrative, not bureaucracy. If you break the work into milestones, introduce each with a brief paragraph that describes the scope, what will exist at the end of the milestone that did not exist before, the commands to run, and the acceptance you expect to observe. Keep it readable as a story: goal, work, result, proof. Progress and milestones are distinct: milestones tell the story, progress tracks granular work. Both must exist. Never abbreviate a milestone merely for the sake of brevity, do not leave out details that could be crucial to a future implementation.
 
Each milestone must be independently verifiable and incrementally implement the overall goal of the execution plan.
 
## Living plans and design decisions
 
* ExecPlans are living documents. As you make key design decisions, update the plan to record both the decision and the thinking behind it. Record all decisions in the `Decision Log` section.
* ExecPlans must contain and maintain a `Progress` section, a `Surprises & Discoveries` section, a `Decision Log`, and an `Outcomes & Retrospective` section. These are not optional.
* When you discover optimizer behavior, performance tradeoffs, unexpected bugs, or inverse/unapply semantics that shaped your approach, capture those observations in the `Surprises & Discoveries` section with short evidence snippets (test output is ideal).
* If you change course mid-implementation, document why in the `Decision Log` and reflect the implications in `Progress`. Plans are guides for the next contributor as much as checklists for you.
* At completion of a major task or the full plan, write an `Outcomes & Retrospective` entry summarizing what was achieved, what remains, and lessons learned.
 
# Prototyping milestones and parallel implementations
 
It is acceptable—-and often encouraged—-to include explicit prototyping milestones when they de-risk a larger change. Examples: adding a low-level operator to a dependency to validate feasibility, or exploring two composition orders while measuring optimizer effects. Keep prototypes additive and testable. Clearly label the scope as “prototyping”; describe how to run and observe results; and state the criteria for promoting or discarding the prototype.
 
Prefer additive code changes followed by subtractions that keep tests passing. Parallel implementations (e.g., keeping an adapter alongside an older path during migration) are fine when they reduce risk or enable tests to continue passing during a large migration. Describe how to validate both paths and how to retire one safely with tests. When working with multiple new libraries or feature areas, consider creating spikes that evaluate the feasibility of these features _independently_ of one another, proving that the external library performs as expected and implements the features we need in isolation.
 
## Skeleton of a Good ExecPlan
 
    # <Short, action-oriented description>
 
    This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
 
    If PLANS.md file is checked into the repo, reference the path to that file here from the repository root and note that this document must be maintained in accordance with PLANS.md.
 
    ## Purpose / Big Picture
 
    Explain in a few sentences what someone gains after this change and how they can see it working. State the user-visible behavior you will enable.
 
    ## Progress
 
    Use a list with checkboxes to summarize granular steps. Every stopping point must be documented here, even if it requires splitting a partially completed task into two (“done” vs. “remaining”). This section must always reflect the actual current state of the work.
 
    - [x] (2025-10-01 13:00Z) Example completed step.
    - [ ] Example incomplete step.
    - [ ] Example partially completed step (completed: X; remaining: Y).
 
    Use timestamps to measure rates of progress.
 
    ## Surprises & Discoveries
 
    Document unexpected behaviors, bugs, optimizations, or insights discovered during implementation. Provide concise evidence.
 
    - Observation: …
      Evidence: …
 
    ## Decision Log
 
    Record every decision made while working on the plan in the format:
 
    - Decision: …
      Rationale: …
      Date/Author: …
 
    ## Outcomes & Retrospective
 
    Summarize outcomes, gaps, and lessons learned at major milestones or at completion. Compare the result against the original purpose.
 
    ## Context and Orientation
 
    Describe the current state relevant to this task as if the reader knows nothing. Name the key files and modules by full path. Define any non-obvious term you will use. Do not refer to prior plans.
 
    ## Plan of Work
 
    Describe, in prose, the sequence of edits and additions. For each edit, name the file and location (function, module) and what to insert or change. Keep it concrete and minimal.
 
    ## Concrete Steps
 
    State the exact commands to run and where to run them (working directory). When a command generates output, show a short expected transcript so the reader can compare. This section must be updated as work proceeds.
 
    ## Validation and Acceptance
 
    Describe how to start or exercise the system and what to observe. Phrase acceptance as behavior, with specific inputs and outputs. If tests are involved, say "run <project’s test command> and expect <N> passed; the new test <name> fails before the change and passes after>".
 
    ## Idempotence and Recovery
 
    If steps can be repeated safely, say so. If a step is risky, provide a safe retry or rollback path. Keep the environment clean after completion.
 
    ## Artifacts and Notes
 
    Include the most important transcripts, diffs, or snippets as indented examples. Keep them concise and focused on what proves success.
 
    ## Interfaces and Dependencies
 
    Be prescriptive. Name the libraries, modules, and services to use and why. Specify the types, traits/interfaces, and function signatures that must exist at the end of the milestone. Prefer stable names and paths such as `crate::module::function` or `package.submodule.Interface`. E.g.:
 
    In crates/foo/planner.rs, define:
 
        pub trait Planner {
            fn plan(&self, observed: &Observed) -> Vec<Action>;
        }
 
If you follow the guidance above, a single, stateless agent -- or a human novice -- can read your ExecPlan from top to bottom and produce a working, observable result. That is the bar: SELF-CONTAINED, SELF-SUFFICIENT, NOVICE-GUIDING, OUTCOME-FOCUSED.
 
When you revise a plan, you must ensure your changes are comprehensively reflected across all sections, including the living document sections, and you must write a note at the bottom of the plan describing the change and the reason why. ExecPlans must describe not just the what but the why for almost everything.
```

## docs/SPEED_UP.md

```markdown
# Accelerate cookimport by scaling CPU concurrency and explicitly optimizing OCR compute

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root.

## Purpose / Big Picture

After this change, a user can run `cookimport stage` on a folder of many files and have `cookimport` automatically use more of the machine: multiple CPU cores will process multiple input files at once, and OCR will explicitly select and use the best available compute device (GPU when present, otherwise CPU). The observable result is that bulk imports complete significantly faster while producing the same staged outputs (intermediate drafts, final drafts, tips, and reports) as before.

A user should be able to verify it is working by running `cookimport stage <folder> --workers 4 --ocr-device auto --ocr-batch-size 8 --warm-models`, observing that multiple files advance concurrently, and seeing log output that states which OCR device is being used (e.g., `cuda`, `mps`, or `cpu`). They should also be able to rerun the same command with `--workers 1 --ocr-device cpu` and observe that the produced recipe drafts are equivalent, but runtime is slower.

## Progress

- [x] (2026-02-01 19:10Z) Establish a baseline: measure wall-clock time for staging a representative folder and capture current logs and outputs for later comparison.
- [x] (2026-02-01 19:15Z) Add a small, always-on timing scaffold to the staging pipeline that reports per-file and per-stage durations in the existing conversion report.
- [x] (2026-02-01 19:30Z) Implement explicit OCR device selection (`auto|cpu|cuda|mps`) and make the selection visible in logs and reports.
- [x] (2026-02-01 19:40Z) Implement OCR batching (process N pages per model call) behind a configurable `--ocr-batch-size` flag and prove outputs are stable.
- [x] (2026-02-01 19:50Z) Implement model warming and per-process caching for OCR and other heavy NLP models to avoid first-file cold start costs.
- [x] (2026-02-01 20:05Z) Implement parallel file processing in `cookimport stage` with a configurable worker count, with safe output writing and an aggregated end-of-run summary.
- [x] (2026-02-01 20:15Z) Add automated tests for device selection logic, batching boundaries, and parallel staging invariants.
- [x] (2026-02-01 20:30Z) Update user-facing docs/help text and add a “performance tuning” note that explains how to pick `--workers` based on RAM and OCR device availability.

## Surprises & Discoveries

- Observation: `multiprocessing` on Linux uses `fork` by default, which triggered `DeprecationWarning` from `torch` because the process was already multi-threaded. For a CLI, this is typically manageable, but `spawn` might be safer for complex environments.
- Observation: `MappingConfig` was being loaded and passed to workers. By adding `ocr_device` and `ocr_batch_size` to `MappingConfig`, we ensured that global CLI overrides are consistently available to all plugins without changing every signature.

## Decision Log

- Decision: Used a separate `cookimport/cli_worker.py` for the parallel worker function.
  Rationale: Avoids circular imports and ensures the function is top-level and picklable for `ProcessPoolExecutor`.
  Date/Author: 2026-02-01 / Gemini

## Outcomes & Retrospective

- (2026-02-01) Parallelism successfully implemented. Baseline tests show timing data is correctly captured in JSON reports.

## Artifacts and Notes

    Sequential (workers=1, ocr=cpu, batch=1): ~8.3s for 3 tests (including setup)
    Parallel (workers=2): Successfully interleaved file processing in tests.
    OCR device: auto-resolves to cpu/cuda/mps correctly.
    Timing data: Now included in every `.report.json` under the "timing" key.

## Context and Orientation

`cookimport` is a Python 3.12 recipe ingestion and normalization pipeline. It supports multiple source formats (Excel, EPUB, PDF, app archives, text/Word) via a registry-based plugin system under `cookimport/plugins/`, where each plugin detects whether it can handle a path and converts it into staged candidates. The primary “bulk import” workflow is `cookimport stage <path>`, which performs Phase 1 ingestion and then downstream transformations to produce intermediate JSON-LD drafts and final `RecipeDraftV1` outputs.

The performance report for this work states that CPU is underutilized because `cookimport` processes files sequentially in a single loop within `cookimport/cli.py`, and that GPU acceleration for OCR is “potentially utilized but unmanaged” because `docTR` relies on PyTorch but the code does not explicitly choose an OCR device. The report proposes four concrete strategies: parallel file processing via multiprocessing, explicit GPU acceleration, batch OCR processing, and model warming/caching. This ExecPlan turns those goals into concrete, testable code changes.

Key files and concepts you will need to locate and read in the repository:

- `cookimport/cli.py`: Defines the Typer CLI and the `stage` command. This is where the sequential loop will be replaced (or wrapped) with a parallel executor and new CLI flags.
- `cookimport/plugins/registry.py` and `cookimport/plugins/*.py`: The plugin registry and importers that stage recipes from different formats. Parallelism will occur at the granularity of “one input file per worker”.
- `cookimport/ocr/doctr_engine.py`: The OCR engine wrapper around `python-doctr` / PyTorch. Device selection, batching, and predictor caching will be implemented here.
- `cookimport/parsing/*`: Ingredient parsing and other NLP routines. Some of these load heavy models (for example spaCy pipelines) and may benefit from per-process caching and optional warming.
- `cookimport/staging/*`: Writers that emit intermediate and final drafts and conversion reports. Parallelism must not cause output collisions or partial writes that leave confusing state behind.

Definitions used in this plan:

- “Worker”: a separate operating-system process used to run Python code in parallel on multiple CPU cores. This is required because Python threads do not parallelize CPU-bound work well due to the Global Interpreter Lock (GIL).
- “ProcessPoolExecutor”: the standard library mechanism (`concurrent.futures.ProcessPoolExecutor`) used to run callables in multiple processes.
- “OCR device”: the PyTorch execution device used for OCR model inference. `cpu` uses the CPU, `cuda` uses an NVIDIA GPU, and `mps` uses Apple Silicon GPU acceleration.
- “Batching”: passing multiple pages (images) to the OCR model in a single call, instead of one page at a time, to reduce overhead and improve throughput.

## Plan of Work

This work is intentionally staged to reduce risk. The order is: first make performance measurable, then make OCR compute deterministic and configurable, then add batching and warming, and only then add parallel file processing. Parallelism multiplies resource use and can amplify existing “hidden” problems; we de-risk it by first stabilizing OCR behavior and reporting.

### Milestone 1: Baseline and observability without output changes

By the end of this milestone you will be able to point to a “before” measurement and a repeatable way to capture “after” measurements, and you will have per-file and per-stage timing information emitted in a structured way.

Work:

- Read `cookimport/cli.py` and identify the full staging flow for a single file and for a folder. Determine where to measure, and whether a “file” is a concrete input path or a discovered set of files from recursion.
- Add a lightweight timing utility (for example a context manager that records monotonic time deltas) in a new module such as `cookimport/core/timing.py` (or a nearby appropriate package).
- Integrate timing into the staging flow so each input file produces a small, structured record including: total time, OCR time (if applicable), parsing time, and output writing time. Prefer writing this into the existing report object if there is one; otherwise write a new JSON file adjacent to the existing conversion report.
- Ensure default behavior remains identical in outputs. This milestone should only add additional report fields or new report artifacts.

Proof:

- Run `cookimport stage` on a small folder and confirm you get the same drafts as before plus the new timing info.

### Milestone 2: Explicit OCR device selection and visibility

By the end of this milestone, OCR will explicitly run on the chosen device, and the chosen device will be visible in logs and in the report.

Work:

- Read `cookimport/ocr/doctr_engine.py` to find how `ocr_predictor` is created and called today.
- Implement a device selection function that supports:
  - `auto`: choose `cuda` if `torch.cuda.is_available()`; otherwise choose `mps` if `torch.backends.mps.is_available()`; otherwise `cpu`.
  - `cpu`, `cuda`, `mps`: explicit selection; if the requested device is not available, fail fast with a clear error message that also prints what is available.
- Add a CLI flag on `cookimport stage` such as `--ocr-device` with those choices, defaulting to `auto`.
- Ensure the OCR predictor is created with the selected device. If the version of `doctr` in this repo accepts a `device` argument, pass it directly. If it does not, move tensors/models appropriately within the engine wrapper and document exactly how you verified it (for example by inspecting the predictor signature in a Python REPL).
- Add logging that prints the chosen device once per run and once per worker (later, when parallelism exists).

Proof:

- Run `cookimport stage` on a scanned PDF input and confirm logs indicate `OCR device: <device>`. Run again with `--ocr-device cpu` and confirm it uses CPU.

### Milestone 3: Batch OCR processing with stable outputs

By the end of this milestone, OCR will process multiple pages per inference call, controlled by `--ocr-batch-size`, and outputs will remain stable.

Work:

- Identify where PDF pages are converted to images (PIL images or arrays) before passing to OCR.
- Modify `doctr_engine.py` so it can accept a list of page images and submit them to the OCR predictor in chunks of size N, where N is `--ocr-batch-size` (default 1 to preserve current behavior until proven).
- Ensure the “page order” is preserved and that downstream text extraction and block reconstruction still aligns with the original page numbers.
- Add guardrails for memory. If a PDF has many pages, do not load all pages into memory at once if current code streams; keep streaming behavior by batching at the point where images exist.

Proof:

- Run `cookimport stage` on a PDF with multiple pages and compare outputs for `--ocr-batch-size 1` vs `--ocr-batch-size 8`. Accept small differences only if they are explained and justified (for example if OCR produces slightly different whitespace); otherwise treat differences as regressions and fix.

### Milestone 4: Model warming and per-process caching

By the end of this milestone, “cold start” delays are reduced. OCR and other heavy models are cached per process and can be proactively warmed at startup with `--warm-models`.

Work:

- In `cookimport/ocr/doctr_engine.py`, implement predictor caching so the predictor is created once per process and reused for subsequent calls. In plain Python this can be done with a module-level singleton or an `functools.lru_cache` keyed by `(device, model_config)`.
- Find other heavy model loads in parsing modules (for example spaCy pipelines used by ingredient parsing). Wrap these loaders similarly so they are created once per process.
- Add a CLI flag `--warm-models` to `cookimport stage` that triggers loading those cached models early, before processing the first file. In a future parallel step, this warming will occur in each worker process at worker startup.
- Ensure warming is optional. Default should keep startup fast for small runs.

Proof:

- Run `cookimport stage` twice on a small sample. On the second run (in the same process), confirm the first-file delay is reduced. For a single run with `--warm-models`, confirm that the warm step happens before file processing and is reported.

### Milestone 5: Parallel file processing in `cookimport stage`

By the end of this milestone, staging a folder can use multiple CPU cores by processing multiple input files concurrently, with safe output semantics and an end-of-run summary.

Work:

- In `cookimport/cli.py`, identify the code path that iterates through multiple files. Replace the sequential loop with a `ProcessPoolExecutor` driven by a “one input file per task” function.
- Define a top-level worker function (must be importable and picklable) such as `cookimport.cli_worker.stage_one_path(path: str, config: StageConfig) -> StageSummary`. This function should:
  - Perform the same staging steps for a single file as the current sequential loop.
  - Write outputs for that file to disk.
  - Return only a small summary (counts, timings, any warnings, path to report), not the full staged objects, to avoid pickling large data.
- Introduce a `StageConfig` data structure that is serializable (simple fields only) and includes: output root directory, OCR device and batch size, warm_models, and any existing CLI options required to make staging deterministic.
- Add CLI flags:
  - `--workers <int|auto>` with default `1` (preserving current behavior).
  - Optionally `--workers auto` computes a safe default using a heuristic derived from the report’s guidance: `min(cpu_count, floor(total_ram_gb / 3))`, but never less than 1. If reliable total RAM cannot be computed without adding dependencies, treat `auto` as “cpu_count” with a prominent warning explaining that RAM may be the limiting factor.
- Ensure safe output writing:
  - If the current staging writes everything into a shared timestamped directory, keep a single run-level output directory, but ensure each input file writes into its own subdirectory (for example by a stable slug of the input filename plus a short hash).
  - Ensure that any shared “summary report” is written only by the parent process after collecting worker summaries, to avoid concurrent writes to the same file.
  - Ensure that partial worker failures do not corrupt other outputs. A failing file should produce a clear error record and the overall run should exit non-zero only if requested (decide and record this policy in the Decision Log).
- Worker initialization and warming:
  - If `ProcessPoolExecutor` supports an `initializer`, use it to call the warm routine when `--warm-models` is enabled. Otherwise, make the worker call a warm-on-first-use function at the start of `stage_one_path`.

Proof:

- Run `cookimport stage data/input --workers 4` and observe that multiple files are being processed concurrently (for example by interleaved per-file log lines, and by system CPU usage). At the end, print a summary like “processed N files, M succeeded, K failed, total time X; average per-file time Y; OCR device Z”.

### Milestone 6: Tests, validation harness, and documentation

By the end of this milestone, changes are protected by tests, and users have clear guidance for tuning.

Work:

- Add unit tests for device selection:
  - Monkeypatch torch availability to simulate CUDA present, MPS present, and neither present.
  - Validate `auto` selection and validate that requesting an unavailable device errors with a clear message.
- Add unit tests for batching behavior:
  - Use small synthetic “page images” or a tiny fixture PDF (if fixtures already exist) and assert that batching yields the same extracted text ordering.
- Add integration tests for parallel staging invariants:
  - Run a small staging set with `--workers 1` and `--workers 2` and confirm that produced outputs (or key report summaries) are equivalent and that no output collisions occur.
- Update CLI help strings and add a short doc file such as `docs/performance.md` (or update an existing docs location) that explains:
  - When to use multiple workers.
  - How to pick a worker count based on available RAM.
  - How OCR device selection works and what `auto` does.
  - How to tune batch size and why larger is not always better (memory tradeoff).

Proof:

- `pytest` passes. A small “benchmark” run demonstrates improvement on a representative dataset and documents the measured numbers in `Artifacts and Notes`.

## Concrete Steps

All commands below are run from the repository root.

1) Locate the current staging loop and OCR engine.

    - `rg -n "def stage\\b|@app\\.command\\(\\)\\s*\\n\\s*def stage" cookimport/cli.py`
    - `rg -n "ProcessPoolExecutor|concurrent\\.futures" -S cookimport`
    - `ls cookimport/ocr && rg -n "doctr|ocr_predictor|torch" cookimport/ocr/doctr_engine.py`

2) Establish a baseline measurement (choose a representative folder of mixed inputs).

    - `time python -m cookimport stage data/input/sample_bulk`

    Save:
    - The produced output directory path.
    - Any existing conversion report file(s).
    - Wall-clock time.

3) Implement Milestone 1 timing scaffold, then rerun baseline and confirm outputs are unchanged aside from the new timing fields/artifacts.

4) Implement Milestones 2–4 in order, rerunning a small scanned PDF case after each step.

5) Implement Milestone 5 parallelism, then test:

    - `time python -m cookimport stage data/input/sample_bulk --workers 1 --ocr-device cpu --ocr-batch-size 1`
    - `time python -m cookimport stage data/input/sample_bulk --workers 4 --ocr-device auto --ocr-batch-size 8 --warm-models`

    Expected observable log lines (exact wording can differ, but the content must exist):

      - “Using workers: 4”
      - “OCR device: cuda” (or `mps` / `cpu`)
      - Per-file start/finish lines including durations
      - End-of-run summary with success/failure counts

6) Add tests and run them.

    - `pytest -q`

## Validation and Acceptance

This work is accepted when all of the following are true:

- Running `cookimport stage <folder> --workers 1` produces the same staged artifacts as before this change (modulo additional timing metadata or new report files that do not change recipe content).
- Running `cookimport stage <folder> --workers 4` completes successfully and demonstrates parallel processing by observable behavior: multiple files progress concurrently and overall wall-clock time is materially reduced on a multi-core machine.
- OCR device selection is explicit and visible:
  - `--ocr-device auto` selects `cuda` when available, otherwise `mps` when available, otherwise `cpu`.
  - Requesting an unavailable device fails fast with a clear error.
- OCR batching is configurable and defaults to the previous behavior (`--ocr-batch-size 1`).
- Model warming is optional and, when enabled, reduces cold-start overhead in a measurable way.
- Automated tests cover device selection logic and protect against basic output collisions in parallel staging.
- The documentation/help text explains the new flags and provides safe tuning guidance, including the RAM tradeoff described in the performance report.

## Idempotence and Recovery

- The changes must be safe to run repeatedly. If output directories are timestamped, multiple runs should naturally not collide. If runs share an output root, each input file must still write to a unique per-file subdirectory to avoid overwrites.
- If a worker crashes or a file fails to parse, the failure must be recorded in a per-file error report and must not corrupt successful outputs from other files.
- If parallelism introduces instability, users must be able to recover by rerunning with `--workers 1`, `--ocr-device cpu`, and `--ocr-batch-size 1`, which should match the pre-change behavior as closely as possible.

## Artifacts and Notes

During implementation, capture the following evidence snippets here:

- Baseline vs improved timing runs (short `time ...` outputs).
- A sample of the end-of-run summary output.
- A short excerpt of the new timing report schema (a few fields only), showing per-file durations and the selected OCR device.

Example (replace with real numbers during implementation):

    Baseline (workers=1, ocr=cpu, batch=1): real 3m12s
    Improved (workers=4, ocr=auto, batch=8, warm): real 1m04s
    OCR device: cuda
    Files: 24 total; 24 succeeded; 0 failed

## Interfaces and Dependencies

New or modified interfaces must be explicit and stable:

- `cookimport/cli.py` (or a new `cookimport/cli_worker.py`) must expose a top-level worker entry point that can be submitted to a `ProcessPoolExecutor`. It must accept only picklable arguments.
- `cookimport/ocr/doctr_engine.py` must expose a clear API that accepts:
  - `device`: one of `cpu|cuda|mps`
  - `batch_size`: positive integer
  - and internally caches the predictor per process for reuse.
- The CLI for `cookimport stage` must add:
  - `--workers`
  - `--ocr-device`
  - `--ocr-batch-size`
  - `--warm-models`
  Each must have a help string that explains what it does and what the default means.
- Avoid adding new third-party dependencies unless absolutely necessary. If you choose to add one (for example for RAM detection), record the decision and rationale in the Decision Log and include exact installation/update steps and why standard library options were insufficient.

```

## docs/architecture/README.md

```markdown
---
summary: "System architecture, pipeline design, and project conventions."
read_when:
  - Starting work on the project
  - Making architectural decisions
  - Understanding output folder structure or naming conventions
---

# Architecture & Conventions

## Pipeline Overview

The cookimport system uses a **two-phase pipeline**:

```
Source Files → [Ingestion] → RecipeCandidate (JSON-LD) → [Transformation] → RecipeDraftV1
                    ↓                                           ↓
              Raw Artifacts                              Step-linked recipes
              Tip Candidates                             Parsed ingredients
              Topic Candidates                           Time/temp metadata
```

### Phase 1: Ingestion
Each source format has a dedicated plugin that:
1. Detects if it can handle the file (confidence score)
2. Inspects internal structure (layouts, headers, sections)
3. Extracts content to `RecipeCandidate` objects (schema.org JSON-LD compatible)
4. Preserves raw artifacts for auditing

### Phase 2: Transformation
Converts intermediate format to final output:
1. Parses ingredient strings into structured components
2. Extracts time/temperature from instruction text
3. Links ingredients to the steps where they're used
4. Classifies and extracts standalone tips

---

## Output Folder Structure

Each run creates a timestamped folder:

```
data/output/{YYYY-MM-DD-HH-MM-SS}/
├── intermediate drafts/{workbook_slug}/   # RecipeSage JSON-LD per recipe
├── final drafts/{workbook_slug}/          # RecipeDraftV1 per recipe
├── tips/{workbook_slug}/                  # Tips and topic candidates
├── chunks/{workbook_slug}/                # Knowledge chunks (optional)
├── raw/{importer}/{source_hash}/          # Raw extracted artifacts
└── {workbook_slug}.excel_import_report.json  # Conversion report
```

---

## Naming Conventions

### File Naming
- Workbook slug: lowercase, alphanumeric + underscores (from source filename)
- Recipe files: `r{index}.json` (0-indexed)
- Tip files: `t{index}.json` (0-indexed)
- Topic files: `topic_{index}.json`

### ID Generation
Stable IDs use URN format: `urn:cookimport:{importer}:{file_hash}:{location_id}`

Example: `urn:cookimport:epub:abc123:c5` (chunk 5 from EPUB with hash abc123)

---

## PDF & EPUB Job Splitting

When `cookimport stage` runs with `--workers > 1`, large PDFs can be split into
page-range jobs (`--pdf-pages-per-job` controls the target pages per job). Each
job parses a slice in parallel, then the main process merges results into a
single workbook output with sequential recipe IDs. During a split run, raw
artifacts are written to a temporary `.job_parts/` folder under the run output
and merged into `raw/` after the merge completes.

Large EPUBs can also be split into spine-range jobs with
`--epub-spine-items-per-job`. Each job parses a subset of spine items, and the
merge step rewrites recipe IDs to a single global sequence.

### Field Normalization
- `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note` → **lowercase**
- Whitespace: normalized (single spaces, max 2 newlines)
- Unicode: NFKC normalized, mojibake repaired

---

## Provenance System

Every output includes provenance for full traceability:

```json
{
  "provenance": {
    "source_file": "cookbook.epub",
    "source_hash": "sha256:abc123...",
    "extraction_method": "heuristic_epub",
    "confidence_score": 0.85,
    "location": {
      "start_block": 42,
      "end_block": 67,
      "chunk_index": 5
    },
    "extracted_at": "2026-01-31T10:30:00Z"
  }
}
```

---

## Plugin Architecture

Importers register with the plugin registry (`cookimport/plugins/registry.py`):

```python
class MyImporter:
    name = "my_format"

    def detect(self, path: Path) -> float:
        """Return confidence 0.0-1.0 that we can handle this file."""

    def inspect(self, path: Path) -> WorkbookInspection:
        """Quick structure analysis without full extraction."""

    def convert(self, path: Path, mapping: MappingConfig | None,
                progress_callback=None) -> ConversionResult:
        """Full extraction to RecipeCandidate objects."""

registry.register(MyImporter())
```

The registry's `best_importer_for_path()` selects the highest-confidence plugin.

---

## Future: LLM & ML Integration

The system follows a **deterministic-first** philosophy:
- Heuristics handle ~90%+ of cases
- LLM escalation only for low-confidence outputs
- ML classification reserved for cases where heuristics systematically fail

Infrastructure exists in `cookimport/llm/` (currently mocked):
- Schema-constrained output (Pydantic models)
- Caching by (model, prompt_version, input_hash)
- Token budget awareness (~30-40M tokens for 300 cookbooks)

ML options documented for future use:
- Zero-shot NLI (BART-large-mnli) for tip classification
- Weak supervision (Snorkel) for labeling function combination
- Supervised DistilBERT for ingredient/instruction segmentation
```

## docs/build-docs-summary.sh

```
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docs_dir="${repo_root}/docs"
timestamp="$(date +"%Y-%m-%d_%H%M%S")"
output="${docs_dir}/${timestamp}_importer-docs-summary.md"

if [[ ! -d "$docs_dir" ]]; then
  echo "Docs directory not found: $docs_dir" >&2
  exit 1
fi

mapfile -d '' files < <(find "$docs_dir" -type f -print0 | sort -z)

{
  cat <<EOF
---
summary: "Combined snapshot of docs/ as of ${timestamp}."
read_when:
  - When you need a single-file snapshot of the docs tree.
---
# Importer Docs Summary
Generated: ${timestamp}
Source root: docs/

EOF

  for file in "${files[@]}"; do
    if [[ "$file" == "$output" ]]; then
      continue
    fi

    rel="${file#$repo_root/}"
    echo "## ${rel}"
    echo ""

    mime_info="$(file --mime "$file" 2>/dev/null || true)"
    if [[ "$mime_info" == *"charset=binary"* ]]; then
      echo "_Binary file; base64-encoded below._"
      echo ""
      printf '```base64\n'
      base64 "$file"
      printf '```\n'
      echo ""
      continue
    fi

    ext="${file##*.}"
    ext_lower="$(printf "%s" "$ext" | tr '[:upper:]' '[:lower:]')"
    case "$ext_lower" in
      md) lang="markdown" ;;
      json) lang="json" ;;
      ts) lang="ts" ;;
      html|htm) lang="html" ;;
      txt) lang="text" ;;
      yml|yaml) lang="yaml" ;;
      *) lang="" ;;
    esac

    if [[ -n "$lang" ]]; then
      printf '```%s\n' "$lang"
    else
      printf '```\n'
    fi
    cat "$file"
    printf '```\n'
    echo ""
  done
} > "$output"

echo "Wrote $output"
```

## docs/docs-list.md

```markdown
---
summary: "Docs list script behavior and expected front matter."
read_when:
  - When updating docs list tooling or doc front matter
---

# Docs list script

The docs list script (`docs/docs-list.ts`) prints a summary of every markdown file under `docs/`, skipping hidden entries plus `archive/` and `research/`. Run it with `npm run docs:list` or `npx tsx docs/docs-list.ts`.

## Expected front matter

Each `docs/**/*.md` file must start with:

```md
---
summary: "One-line summary"
read_when:
  - When this doc should be read
---
```

`read_when` is optional and can be a bullet list or an inline array.

## What happens on missing metadata

If a file is missing front matter or a non-empty `summary`, the script still lists it but appends an error label:

- `missing front matter`
- `unterminated front matter`
- `summary key missing`
- `summary is empty`
```

## docs/docs-list.ts

```ts
#!/usr/bin/env tsx
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const docsListFile = fileURLToPath(import.meta.url);
const docsListDir = dirname(docsListFile);
const DOCS_DIR = join(docsListDir, '..', 'docs');

const EXCLUDED_DIRS = new Set(['archive', 'research']);

function compactStrings(values: unknown[]): string[] {
  const result: string[] = [];
  for (const value of values) {
    if (value === null || value === undefined) {
      continue;
    }
    const normalized = String(value).trim();
    if (normalized.length > 0) {
      result.push(normalized);
    }
  }
  return result;
}

function walkMarkdownFiles(dir: string, base: string = dir): string[] {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    if (entry.name.startsWith('.')) {
      continue;
    }
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_DIRS.has(entry.name)) {
        continue;
      }
      files.push(...walkMarkdownFiles(fullPath, base));
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      files.push(relative(base, fullPath));
    }
  }
  return files.sort((a, b) => a.localeCompare(b));
}

function extractMetadata(fullPath: string): {
  summary: string | null;
  readWhen: string[];
  error?: string;
} {
  const content = readFileSync(fullPath, 'utf8');
  if (!content.startsWith('---')) {
    return { summary: null, readWhen: [], error: 'missing front matter' };
  }
  const endIndex = content.indexOf('\n---', 3);
  if (endIndex === -1) {
    return { summary: null, readWhen: [], error: 'unterminated front matter' };
  }
  const frontMatter = content.slice(3, endIndex).trim();
  const lines = frontMatter.split('\n');
  let summaryLine: string | null = null;
  const readWhen: string[] = [];
  let collectingField: 'read_when' | null = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith('summary:')) {
      summaryLine = line;
      collectingField = null;
      continue;
    }
    if (line.startsWith('read_when:')) {
      collectingField = 'read_when';
      const inline = line.slice('read_when:'.length).trim();
      if (inline.startsWith('[') && inline.endsWith(']')) {
        try {
          const parsed = JSON.parse(inline.replace(/'/g, '"')) as unknown;
          if (Array.isArray(parsed)) {
            readWhen.push(...compactStrings(parsed));
          }
        } catch {
          // ignore malformed inline arrays
        }
      }
      continue;
    }
    if (collectingField === 'read_when') {
      if (line.startsWith('- ')) {
        const hint = line.slice(2).trim();
        if (hint) {
          readWhen.push(hint);
        }
      } else if (line === '') {
        continue;
      } else {
        collectingField = null;
      }
    }
  }

  if (!summaryLine) {
    return { summary: null, readWhen, error: 'summary key missing' };
  }
  const summaryValue = summaryLine.slice('summary:'.length).trim();
  const normalized = summaryValue
    .replace(/^['"]|['"]$/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!normalized) {
    return { summary: null, readWhen, error: 'summary is empty' };
  }

  return { summary: normalized, readWhen };
}

console.log('Listing all markdown files in docs folder:');
const markdownFiles = walkMarkdownFiles(DOCS_DIR);
for (const relativePath of markdownFiles) {
  if (relativePath.endsWith('AGENTS.md')) {
    console.log(`${relativePath} - reminder to always read this`);
    continue;
  }
  const fullPath = join(DOCS_DIR, relativePath);
  const { summary, readWhen, error } = extractMetadata(fullPath);
  if (summary) {
    console.log(`${relativePath} - ${summary}`);
    if (readWhen.length > 0) {
      console.log(`  Read when: ${readWhen.join('; ')}`);
    }
  } else {
    const reason = error ? ` - [${error}]` : '';
    console.log(`${relativePath}${reason}`);
  }
}

console.log(
  '\nReminder: keep docs up to date as behavior changes. IF ANY FILES THROW ERRORS, FIX THEM ' +
    'When your task matches any "Read when" hint above ' +
    '(React hooks, cache directives, database work, tests, etc.), ' +
    'read that doc before coding, and suggest new coverage when it is missing.'
);
```

## docs/docs-summary-script.md

```markdown
---
summary: "How to generate the combined docs snapshot."
read_when:
  - When you need a single-file snapshot of the docs tree.
---

# Docs Summary Script

Run `docs/build-docs-summary.sh` to generate `docs/<timestamp>_importer-docs-summary.md` with the contents of every file under `docs/`.
```

## docs/ingestion/README.md

```markdown
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

**Job splitting:**
- Large EPUBs can be split into spine-range jobs when `cookimport stage` runs
  with `--workers > 1`; tune with `--epub-spine-items-per-job`.

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

**Job splitting:**
- Large PDFs can be split into page-range jobs when `cookimport stage` runs with multiple workers.
- Use `--pdf-pages-per-job` to control the target number of pages per job; results are merged back into a single workbook output.
- OCR and text extraction both honor page ranges, so each job only processes its assigned slice.

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
```

## docs/label-studio/README.md

```markdown
---
summary: "Label Studio integration for benchmarking and golden set creation."
read_when:
  - Setting up Label Studio for evaluation
  - Creating or exporting golden sets
  - Understanding chunking strategies
---

# Label Studio Integration

**Location:** `cookimport/labelstudio/`

Label Studio is used to create ground-truth datasets for validating extraction accuracy.

## Quick Start

### Prerequisites

```bash
# Start Label Studio (Docker)
docker run -it -p 8080:8080 heartexlabs/label-studio:latest

# Set environment variables
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=your_api_key_here
```

### Import Workflow

```bash
# Import a cookbook for labeling
cookimport labelstudio-import path/to/cookbook.epub \
  --project-name "ATK Cookbook Benchmark" \
  --chunk-level both
```

### Export Workflow

```bash
# Export labeled data as golden set
cookimport labelstudio-export \
  --project-name "ATK Cookbook Benchmark" \
  --output-dir data/golden/
```

---

## Chunking Strategies

### Structural Chunks

Recipe-level units for validating segmentation accuracy.

**Use case:** "Did we correctly identify recipe boundaries?"

Each chunk contains:
- Full recipe text (ingredients + instructions)
- Extracted recipe title
- Source location (block indices)

**Labels:** Correct boundary, Over-segmented, Under-segmented, Not a recipe

### Atomic Chunks

Line-level units for validating parsing accuracy.

**Use case:** "Did we correctly parse this ingredient line?"

Each chunk contains:
- Single ingredient or instruction line
- Parsed fields (quantity, unit, item, etc.)
- Confidence score

**Labels:** Correct, Incorrect quantity, Incorrect unit, Incorrect item, etc.

### Chunk Levels

| Level | Description |
|-------|-------------|
| `structural` | Recipe-level chunks only |
| `atomic` | Line-level chunks only |
| `both` | Both structural and atomic chunks |

---

## Labeling Interface

The Label Studio project uses a custom labeling config (`label_config.py`):

### For Structural Chunks
- Boundary correctness (correct/over/under-segmented)
- Recipe vs non-recipe classification
- Title extraction accuracy

### For Atomic Chunks
- Field-by-field correctness
- Quantity kind accuracy
- Section header detection

---

## Golden Set Export

Exported data format (JSONL):

```json
{
  "chunk_id": "urn:cookimport:epub:abc123:c5",
  "chunk_type": "structural",
  "source_file": "cookbook.epub",
  "labels": {
    "boundary": "correct",
    "is_recipe": true,
    "title_correct": true
  },
  "annotator": "user@example.com",
  "annotated_at": "2026-01-31T10:30:00Z"
}
```

---

## Pipeline Routing

The chunking module (`cookimport/labelstudio/chunking.py`) handles:

### Extraction Archive

Raw extracted content stored for reference:
- Block text and indices
- Source location
- Extraction method

### Chunk Generation

```python
# Structural chunks
chunks = chunk_structural(result, archive, source_file, book_id, pipeline, file_hash)

# Atomic chunks
chunks = chunk_atomic(result, archive, source_file, book_id, pipeline, file_hash)
```

### Coverage Tracking

Monitors extraction completeness:
- `extracted_chars`: Total characters from source
- `chunked_chars`: Characters included in chunks
- `warnings`: Coverage gaps or issues

---

## Artifacts

Each import run creates:

```
data/output/{timestamp}/labelstudio/{book_slug}/
├── manifest.json           # Run metadata, chunk IDs, coverage
├── extracted_archive.json  # Raw extracted blocks
├── extracted_text.txt      # Plain text for reference
├── label_studio_tasks.jsonl # Tasks uploaded to Label Studio
├── project.json            # Label Studio project info
└── coverage.json           # Extraction coverage stats
```

---

## Resume Mode

Import supports resuming to add new chunks without duplicating:

```bash
# First import
cookimport labelstudio-import cookbook.epub --project-name "My Project"

# Later: resume with additional chunks
cookimport labelstudio-import cookbook.epub --project-name "My Project"
# Automatically detects existing chunks and only uploads new ones
```

Use `--overwrite` to start fresh (deletes existing project).

---

## Client API

Direct API access for advanced use:

```python
from cookimport.labelstudio.client import LabelStudioClient

client = LabelStudioClient(url, api_key)

# Find or create project
project = client.find_project_by_title("My Project")
if not project:
    project = client.create_project("My Project", label_config_xml)

# Import tasks
client.import_tasks(project["id"], tasks)

# Export annotations
annotations = client.export_annotations(project["id"])
```
```

## docs/parsing/receipe_parsing.md

```markdown
---
summary: "Ingredient parsing, instruction metadata extraction, and text normalization."
read_when:
  - Working on ingredient line parsing
  - Extracting time/temperature from instructions
  - Understanding text preprocessing pipeline
---

# Parsing Pipeline

The parsing phase transforms raw text into structured data.

## Ingredient Parsing

**Location:** `cookimport/parsing/ingredients.py`

**Library:** [ingredient-parser-nlp](https://ingredient-parser.readthedocs.io/) - NLP-based decomposition

### Input/Output Example

```python
parse_ingredient_line("3 stalks celery, sliced")
# Returns:
{
    "quantity_kind": "exact",      # exact | approximate | unquantified | section_header
    "input_qty": 3.0,              # Numeric quantity (float)
    "raw_unit_text": "stalks",     # Unit as written
    "raw_ingredient_text": "celery",  # Ingredient name
    "preparation": "sliced",       # Prep instructions
    "note": None,                  # Additional notes
    "is_optional": False,          # Detected from "(optional)"
    "confidence": 0.92,            # Parser confidence
    "raw_text": "3 stalks celery, sliced"  # Original input
}
```

### Quantity Kinds

| Kind | Description | Example |
|------|-------------|---------|
| `exact` | Numeric quantity present | "2 cups flour" |
| `approximate` | Vague quantity | "salt to taste", "oil for frying" |
| `unquantified` | No quantity detected | "fresh parsley" |
| `section_header` | Ingredient group label | "FOR THE SAUCE:", "Marinade" |

### Section Header Detection

Headers are identified by:
- ALL CAPS single words: "FILLING", "MARINADE"
- "For the X" pattern: "For the Filling"
- Known keywords: garnish, topping, sauce, dressing, crust, glaze, etc.
- No amounts parsed from text

### Range Handling

Ranges like "3-4 cups" → midpoint rounded up (4.0)

### Approximate Phrases

Detected patterns:
- "to taste", "as needed", "as desired"
- "for serving", "for garnish", "for frying"
- "for greasing", "for the pan"

---

## Instruction Metadata Extraction

**Location:** `cookimport/parsing/instruction_parser.py`

Extracts time and temperature from instruction text.

### Time Extraction

```python
parse_instruction("Bake for 25-30 minutes until golden.")
# Returns:
{
    "total_time_seconds": 1650,  # Midpoint of range (27.5 min)
    "temperature": None,
    "temperature_unit": None
}
```

Supported patterns:
- "X minutes", "X hours", "X-Y minutes"
- "1 hour 30 minutes", "1.5 hours"
- Accumulates multiple times in one step

### Temperature Extraction

```python
parse_instruction("Preheat oven to 375°F.")
# Returns:
{
    "total_time_seconds": None,
    "temperature": 375.0,
    "temperature_unit": "F"
}
```

Supported patterns:
- "350°F", "180°C", "350 degrees F"
- Unit conversion available (F↔C)

### Cook Time Aggregation

Total recipe cook time = sum of all step times (when not explicitly provided in source).

---

## Text Normalization

**Location:** `cookimport/parsing/cleaning.py`

### Unicode Normalization
- NFKC normalization (compatibility decomposition + canonical composition)
- Non-breaking spaces → regular spaces

### Mojibake Repair
Common encoding corruption fixes:
- `â€™` → `'` (smart quote)
- `â€"` → `—` (em dash)
- `Ã©` → `é` (accented characters)

### Whitespace Standardization
- Collapse multiple spaces to single space
- Collapse 3+ newlines to 2 newlines
- Strip leading/trailing whitespace

### Hyphenation Repair
Rejoins words split across lines:
- "ingre-\ndients" → "ingredients"
- Handles soft hyphens (U+00AD)

---

## Signal Detection

**Location:** `cookimport/parsing/signals.py`

Enriches `Block` objects with feature flags for downstream processing.

### Available Signals

| Signal | Description |
|--------|-------------|
| `is_heading` | Detected as heading element |
| `heading_level` | 1-6 for h1-h6 |
| `is_ingredient_header` | "Ingredients:", "For the Sauce:" |
| `is_instruction_header` | "Instructions:", "Method:", "Directions:" |
| `is_yield` | "Serves 4", "Makes 12 cookies" |
| `is_time` | "Prep: 15 min", "Cook: 30 min" |
| `starts_with_quantity` | Line starts with number/fraction |
| `has_unit` | Contains unit term (cup, tbsp, oz) |
| `is_ingredient_likely` | High probability ingredient line |
| `is_instruction_likely` | High probability instruction step |

### Override Support

Cookbook-specific overrides via `ParsingOverrides`:
- Custom ingredient headers
- Custom instruction headers
- Additional imperative verbs
- Custom unit terms
```

## docs/parsing/semantic-matching-for-ingredients.md

```markdown
---
summary: "Semantic fallback matching for ingredient-to-step assignment."
read_when:
  - When improving ingredient normalization or semantic matching in step linking
---

# Semantic Matching for Ingredient-to-Step Assignment

## Current behavior (implemented)

- Exact alias matching runs first (raw + cleaned aliases).
- If an ingredient has **no exact matches**, a lightweight **lemmatized** fallback runs.
- "Exact match" here includes head/tail single-token aliases, so semantic/fuzzy only run when **no alias tokens** hit a step.
- Lemmatization is **rule-based** (suffix stripping + a small override map) and adds **no external deps**.
- A **curated synonym map** expands semantic aliases (e.g., scallion ↔ green onion).
- If an ingredient is still unmatched, a **RapidFuzz** fallback runs for near-miss typos.
- Candidates are tagged as `match_kind="semantic"` or `match_kind="fuzzy"` and only considered when exact matches are absent for that ingredient.

## Why it helps

This rescues common morphology gaps without heavy models, e.g.:

- "floured" → "flour"
- "onions" → "onion"
- "chopped" → "chop"
- "scallions" → "green onion"
- "squah" (typo) → "squash" (via fuzzy rescue)

## Where it lives

- `cookimport/parsing/step_ingredients.py`
  - `_lemmatize_token` / `_lemmatize_tokens`
  - `_expand_synonym_variants` / `_add_alias_variants`
  - `_tokenize(..., lemmatize=True)`
  - semantic fallback in `assign_ingredient_lines_to_steps`
  - fuzzy fallback in `assign_ingredient_lines_to_steps`

## Guardrails and tuning knobs

- `_SYNONYM_GROUPS`: curated synonym phrase groups (lemmatized tokens).
- `_FUZZY_MIN_SCORE`: minimum RapidFuzz score for fuzzy candidates (default 85).
- `_GENERIC_FUZZY_TOKENS`: excludes very generic single-word ingredients from fuzzy rescue.

## Future options (not implemented)

- Real lemmatizers (spaCy, NLTK, LemmInflect)
- Embedding fallback for *unassigned* ingredients only, ideally on constrained spans
```

## docs/parsing/tip-knowledge-chunking.md

```markdown
# Implement knowledge chunking with highlight-based tip mining

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repo root; this plan must be maintained in accordance with it. &#x20;

## Purpose / Big Picture

Today, `cookimport` extracts “tips” as small spans, which has good precision on tip-shaped sentences but is recall-limited and frequently clips the surrounding explanation, emits orphan aphorisms, and leaks front-matter blurbs into the output.  &#x20;

After this change, `cookimport stage …` will additionally produce “knowledge chunks”: longer, coherent, cookbook-structure-respecting sections of non-recipe text. Each knowledge chunk will:

- be labeled as `knowledge`, `narrative`, or `noise` (so blurbs/jacket copy do not pollute knowledge extraction),
- include provenance back to the original block stream,
- include “highlights” (the existing tip miner output) and a “tip density” score, but the chunk boundary is not decided by punctuation or one-sentence “tips”.
  This implements the recommended strategy: chunk first, mine highlights inside chunks, and distill from the whole chunk (optionally via the existing mocked LLM layer).  &#x20;

You will know it is working by staging a cookbook and finding new output artifacts (e.g. `chunks.md` and `c{index}.json`) where:

- front-matter blurbs like “This beautiful, approachable book…” are classified as `narrative`/`noise`, not `knowledge`,&#x20;
- clipped “tips” are no longer emitted as the unit of output; instead, they appear as highlights inside a larger coherent chunk that contains the missing explanation,&#x20;
- headings like “USING SALT” group the following material into a single section chunk rather than many disconnected tips. &#x20;

## Progress

- [x] (2026-01-31) Baseline: run `cookimport stage` on a representative cookbook and save current `tips.md` + tip JSON outputs for comparison.

- [x] (2026-01-31) Add chunk data model(s) and writer output folder + human-readable `chunks.md`.
  - Added `ChunkLane`, `ChunkBoundaryReason`, `ChunkHighlight`, `KnowledgeChunk` models to `core/models.py`
  - Added `write_chunk_outputs()` to `staging/writer.py`
  - Output: `chunks/<workbook>/c{index}.json` and `chunks.md`

- [x] (2026-01-31) Implement deterministic heading-driven chunker (section chunks) that operates on the existing block stream.
  - Created `cookimport/parsing/chunks.py` with `chunk_non_recipe_blocks()` function
  - Uses ALL CAPS, colon-terminated, and title-case heading detection
  - Maintains section path stack for nested headings
  - Handles stop headings (INDEX, ACKNOWLEDGMENTS, etc.)

- [x] (2026-01-31) Implement lane assignment (`knowledge`/`narrative`/`noise`) including a front-matter/blurb filter.
  - `assign_lanes()` scores chunks based on knowledge/narrative/noise signals
  - Knowledge: imperatives, modals, mechanisms, diagnostics, temps/times
  - Narrative: first-person, anecdotes, opinions
  - Noise: praise adjectives, book/marketing language, quote-only content

- [x] (2026-01-31) Integrate existing tip miner as "highlights" inside each knowledge chunk; compute tip density and aggregate tags.
  - `extract_highlights()` runs tip miner on knowledge chunks
  - Computes `tip_density` (highlights per 1000 chars)
  - Aggregates tags from all highlights

- [x] (2026-01-31) Add boundary refinements (hard/medium/soft), callout chunking (TIP/NOTE/Variation boxes), and max/min chunk sizing.
  - `ChunkingProfile` configures min/max chars, heading levels, stop headings
  - Callout prefixes (TIP:, NOTE:, etc.) create boundaries
  - Format mode changes (prose ↔ bullets) trigger soft boundaries
  - `merge_small_chunks()` combines undersized chunks

- [x] (2026-01-31) Add tests (unit + small fixture) proving the three failure modes are mitigated; ensure legacy tip extraction still works.
  - Created `tests/test_chunks.py` with 18 tests covering:
    - Heading detection and section paths
    - Lane assignment for knowledge/narrative/noise
    - Highlight extraction and tag aggregation
    - Chunk merging and boundary reasons
  - All 172 tests pass (including existing tests)

- [ ] (2026-01-31) (Optional) Add "distill chunk" path using the existing mocked LLM layer, with caching and a CLI flag to enable.

## Surprises & Discoveries

* Observation: Topic candidates from conversion don't preserve original block structure, so we convert them to blocks for chunking.
  Evidence: Created `chunks_from_topic_candidates()` bridge function to convert TopicCandidate → Block → KnowledgeChunk.

* Observation: Stop sections (INDEX, ACKNOWLEDGMENTS) need to skip ALL following blocks until next major heading, not just the heading itself.
  Evidence: Added `in_stop_section` flag to track and skip content within stop sections.

* Observation: The chunking integrates cleanly with existing architecture by running after conversion and populating `result.chunks`.
  Evidence: Salt Fat Acid Heat EPUB: 466 chunks (424 knowledge, 37 narrative, 5 noise), 224 highlights extracted.

## Decision Log

- Decision: Keep the existing tip miner, but demote it to highlights inside chunk outputs; do not remove legacy `tips.md` initially.
  Rationale: This preserves current functionality while enabling the new “coherent chunk → distill” pipeline; it matches the recommended hybrid approach.&#x20;
  Date/Author: 2026-01-31 / assistant
- Decision: Boundaries are structure-first (headings/sections), not punctuation-first.
  Rationale: Prevents clipped spans and orphan aphorisms; cookbook structure is a stronger signal than sentence shape. &#x20;
- Decision: Add explicit `narrative` and `noise` lanes and route blurbs/front matter away from knowledge extraction.
  Rationale: The current output includes jacket-copy-like praise blurbs; they should be excluded from knowledge distillation. &#x20;
- Decision: Prefer deterministic chunking; only add LLM refinement behind a flag and with caching.
  Rationale: Stable, debuggable output is required for tuning and regression testing; LLM can improve quality but must not be required for baseline correctness.&#x20;

## Outcomes & Retrospective

### First End-to-End Success (2026-01-31)

Tested on `saltfatacidheat.epub`:
- **466 total chunks** generated with proper boundaries
- **Lane classification working**: 424 knowledge, 37 narrative, 5 noise
- **224 highlights** extracted from knowledge chunks

#### Failure Mode #1: Praise blurbs routed to noise ✓
```
### c0 🔇 NOISE
**(untitled)**
"This beautiful, approachable book not only teaches you how to cook..."
—Alice Waters
```

#### Failure Mode #2: Headings group content coherently ✓
```
### c3 📚 KNOWLEDGE
**SALT**
Section: SALT > Using Salt
Blocks: [24..35] (12 blocks)
```
The SALT section now groups 12 blocks together rather than emitting disconnected tips.

#### Failure Mode #3: Aphorisms become highlights, not standalone ✓
Short tip-like content appears inside larger knowledge chunks as highlights with `selfContained` flag, not as the primary unit of output.

### Files Added/Modified
- `cookimport/core/models.py`: Added ChunkLane, ChunkBoundaryReason, ChunkHighlight, KnowledgeChunk models
- `cookimport/parsing/chunks.py`: New module with chunking pipeline
- `cookimport/staging/writer.py`: Added write_chunk_outputs()
- `cookimport/cli.py`: Integrated chunk generation into stage command
- `tests/test_chunks.py`: 18 unit tests for chunking functionality

## Context and Orientation

`cookimport` is a multi-format ingestion engine (PDF/EPUB/Excel/Text/etc.) that stages recipes into structured outputs and also extracts standalone “Kitchen Tips” and topics. &#x20;

For unstructured sources, the system uses a linear stream of `Block` objects (paragraphs/headings/list items) enriched with “signals” like `is_heading`, `heading_level`, `is_instruction_likely`, and `is_ingredient_likely`.&#x20;
Tip extraction currently:

- atomizes text into “atoms” (paragraph/list/header) and preserves neighbor context for repair,&#x20;
- extracts candidate spans via prefixes/anchors (e.g. “TIP:”, “Make sure…”) and repairs incomplete spans by merging neighbors,&#x20;
- judges candidates with a tipness score (imperatives, modals, benefit cues vs narrative cues and recipe overlap) and a generality score,&#x20;
- tags tips via a taxonomy mapping (tools/techniques/ingredients),&#x20;
- writes results to `data/output/<timestamp>/tips/<workbook_stem>/` including `t{index}.json` and `tips.md`.&#x20;

The newest sample output shows the main issues this plan targets: front-matter blurbs extracted as tips, headings emitted as tips, and short aphorisms without payload. &#x20;

## Plan of Work

Implement a new “Knowledge Chunking” subsystem that runs on the same non-recipe block stream currently sent to tip extraction. The subsystem will produce coherent chunks and then run the existing tip miner inside each knowledge chunk to produce highlights and scoring, rather than treating mined spans as the final output unit.&#x20;

This should be done in small, verifiable milestones:

1. get a minimal chunk artifact written end-to-end,
2. make chunk boundaries respect cookbook structure (headings and callouts),
3. reliably separate knowledge vs narrative/noise,
4. attach highlights and scoring,
5. prove the failure modes are fixed with tests and fixture output diffs,
6. optionally enable LLM distillation over chunks using the existing mocked `cookimport/llm/` layer.

Throughout, preserve provenance and debuggability: every chunk should explain why it started/ended and which source blocks it contains.&#x20;

## Concrete Steps

All commands below are run from the repository root.

0. Optional dependency wiring (no behavior change).

   - Add optional dependencies (extras, or a separate requirements file) for:
     - `pysbd`
     - `spacy`
     - `sentence-transformers`
     - `scikit-learn`
     - `bertopic`
     - `umap-learn`
     - `hdbscan`
   - Ensure all imports are guarded and the default staging pipeline runs without these packages installed.
   - Add explicit CLI/profile flags for each optional feature so behavior is easy to reason about (e.g. `--sentence-splitter=pysbd`, `--topic-similarity=embedding`, `--lane-classifier=...`).

1. Establish baseline behavior and locate the current tip pipeline.

   - Run staging on a known cookbook input:
     python -m cookimport.cli stage data/input/\<your\_file>
     (This is the documented entrypoint; if the repo also exposes a `cookimport stage …` console script, that is acceptable too.) &#x20;
   - Find the most recent output folder in `data/output/…` and open:
     - `tips/<workbook_stem>/tips.md`
     - a handful of `tips/<workbook_stem>/t*.json`
   - Save a copy of the baseline `tips.md` snippet that includes:
     - the praise blurb tip(s),
     - “USING SALT” section,
     - the “pepper inverse” aphorism line,
       so you can compare after chunking. &#x20;

2. Add chunk artifacts (models + writer) without changing chunking logic yet.

   - In `cookimport/core/models.py`, add Pydantic models that are parallel to `TipCandidate`/`TopicCandidate`:
     - `ChunkLane`: enum with values `knowledge`, `narrative`, `noise`.
     - `ChunkBoundaryReason`: string enum; start with a small set: `heading`, `recipe_boundary`, `callout_seed`, `format_mode_change`, `max_chars`, `noise_break`, `end_of_input`.
     - `ChunkHighlight`: stores a reference to a mined tip/highlight and its location within the chunk (at minimum: `text` and `source_block_ids`; optionally offsets if easily available).
     - `ChunkCandidate` (or `KnowledgeChunk`): fields:
       - `id` (stable within output: `c{index}`),
       - `lane`,
       - `title` (derived from heading path),
       - `section_path` (list of headings),
       - `text` (the concatenated chunk text),
       - `block_ids` (source block indices or provenance ids),
       - `aside_block_ids` (optional; blocks inside the chunk classified as narrative-aside even if the overall chunk lane is `knowledge`),
       - `excluded_block_ids_for_distillation` (optional; blocks to omit when building `distill_text`),
       - `distill_text` (optional; the text actually sent to any distiller, derived from chunk blocks minus excluded/aside blocks),
       - `boundary_start_reason` / `boundary_end_reason`,
       - `tags` (aggregate, reuse the existing tag schema where possible),
       - `tip_density` (float or simple counts),
       - `highlights` (list of `ChunkHighlight`),
       - `provenance` (reuse the repo’s existing provenance conventions; do not invent an incompatible format).
         This mirrors how `TipCandidate` is used today.&#x20;
   - In `cookimport/staging/writer.py`, add a new output folder sibling to `tips/`, e.g.:
     - `data/output/<timestamp>/chunks/<workbook_stem>/`
     - `c{index}.json`
     - `chunks.md` (human-readable summary like `tips.md`)
       Preserve the existing `tips/` outputs unchanged in this milestone.&#x20;
   - The initial `chunks.md` format should be optimized for debugging:
     - chunk id, lane, title/section path
     - start/end boundary reasons
     - tip density (even if 0 for now)
     - first \~300–800 chars of chunk text
     - list of included block ids
       Keep it deterministic so diffs are stable.

3. Implement the minimal deterministic chunker (heading-driven “section chunks”).

   - Create a new module `cookimport/parsing/chunks.py` with a single entry function, for example:
     def chunk\_non\_recipe\_blocks(blocks: list[Block], \*, profile: ChunkingProfile) -> list[ChunkCandidate]
     Keep it pure (no IO); writer stays in `staging/writer.py`.

   - Implement “section chunk” as the default winner:

     - treat a heading block as a hard boundary and a chunk seed,
     - include “heading + everything until the next peer/parent heading” in the same chunk, not many small chunks,
     - do not let punctuation create boundaries.

   - Add an explicit fallback for weak structure / no headings:

     - detect “heading sparsity” (e.g. no headings for N blocks or >X chars),
     - switch to a micro-chunk mode that splits by medium boundaries + topic continuity heuristics rather than headings,
     - record `boundary_*_reason` as `topic_pivot` or `max_chars` (never “sentence end”).
       Suggested deterministic topic-pivot heuristic (good enough to start):
     - Provide two backends (configurable):
       - `lexical`: TF-IDF / bag-of-words overlap between a rolling window of the last K blocks and the next block.
       - `embedding` (if `sentence-transformers` is installed): SBERT embeddings per block and cosine similarity between adjacent blocks.
     - Split when similarity drops below a threshold **and** at least one medium boundary cue is present (blank line, list-mode change, callout seed, definition-like `:` pattern).
     - Merge when similarity stays high and no hard boundary is crossed.
     - Cache per-block features (TF-IDF vectors or embeddings) keyed by block text hash + model/version so re-runs are cheap and deterministic.



- Use the existing `Block & Signals` architecture:
  - determine heading blocks via existing `is_heading` / `heading_level` signals, and maintain a `section_path` stack as you iterate.&#x20;
- Define a `ChunkingProfile` (similar in spirit to `TipParsingProfile`) that contains:
  - `min_chars`, `max_chars` (start with something like 800 and 6000, but make it configurable),
  - heading levels considered “major” vs “minor” (use repo-specific heading levels; validate with a fixture),
  - a small list of “stop headings” for noise-heavy parts (e.g. INDEX, ACKNOWLEDGMENTS) but only as a default suggestion; keep it overrideable.
  - `sentence_splitter`: `none|pysbd|spacy` (default: `none`), for within-block sentence segmentation.
  - `topic_similarity_backend`: `none|lexical|embedding` (default: `lexical` in heading-sparse fallback; `none` otherwise).
  - `embedding_model_name` + `embedding_cache_dir` (only used when `topic_similarity_backend=embedding`).
  - `similarity_thresholds` (merge/split thresholds) and `window_k` for heading-sparse mode.
  - `lane_classifier_path` (optional; if present and enabled, use it to override/augment heuristic lane scoring).
- Ensure every chunk carries explicit boundary reasons (start and end).

4. Add lane assignment and a front-matter/blurb filter.
   - Add lane scoring functions in `cookimport/parsing/signals.py` or a new `cookimport/parsing/lane.py`:

     - `knowledge_score`: imperatives/modals/diagnostic cues/temps-times-quantities/mechanisms (“because/so that/therefore”) (some already exist in tip scoring logic).&#x20;
     - `narrative_score`: first-person voice markers and anecdote cues (some are already “negative signals” in tip judging).&#x20;
     - `noise_score` / `blurb_score`: praise adjectives + “book” + “teaches you” + quote-only patterns, matching the observed blurbs.

   - Optional (high leverage): supervised lane classifier (requires `scikit-learn` and a trained model artifact).

     - Train a lightweight classifier (logistic regression / linear SVM) from Label Studio exports.
     - Features: existing heuristic signals + TF-IDF bag-of-words + optional embedding features.
     - Inference policy: classifier can *override* heuristics only when confidence is high; otherwise fall back to heuristics.

   - Optional (feature enrichment): if `spacy` is installed, add POS/dependency-derived features to lane scoring and self-containedness checks (imperatives, modals, causal clauses).

   - Apply lane assignment at the section/chunk level (not per sentence), so one stray anecdote line does not flip an entire technique section.

   - Make an explicit, consistent choice for “knowledge → anecdote → knowledge” inside one section:

     - default behavior: keep a single `knowledge` chunk if knowledge dominates, but mark the anecdote blocks as `aside_block_ids` and add them to `excluded_block_ids_for_distillation`.
     - distillation (if enabled) must use `distill_text` and ignore aside blocks.
     - if an aside grows beyond a configurable size (e.g. `narrative_aside_split_chars`), optionally split it into a sibling `narrative` chunk that inherits the same `section_path`.

- Explicitly route the sample praise-blurb content to `noise` (or `narrative`, but consistently) and verify it no longer appears under `knowledge`.&#x20;
  - Add “quote gate” and “intro/foreword gating” as heuristics, but do not blanket-drop introductions; treat them as likely narrative and keep them available for inspection.&#x20;

5. Integrate the existing tip miner as highlights and compute tip density.
   - In `cookimport/parsing/tips.py`, add a mode that can accept a pre-bounded chunk of text/blocks and return:

     - highlight spans (existing `TipCandidate` outputs, but marked as highlights),
     - tags (taxonomy-derived),
     - a per-highlight “self-contained” flag if implemented.
       The goal is to reuse the existing miner without reusing its boundary choice.&#x20;

   - Implement a “standalone tip gate” but in the chunk pipeline, not as the main output:

     - if a mined span is single-sentence and lacks action/mechanism/example, do not promote it as a standalone tip; keep it only as a highlight.&#x20;
       This specifically addresses aphorisms like “the inverse isn’t necessarily so.”&#x20;

   - Add deterministic span expansion (within chunk context) for mined highlights that appear clipped:

     - expand forward (and optionally backward) while still inside the same section, until a hard boundary or `max_chars`.
     - stop on heading, recipe boundary, major formatting break, or topic jump heuristic.

   - Add two cheap sanity checks as explicit heuristics (optional but recommended):

     - Sentence splitting backend (enabler): use `pysbd` (preferred for messy OCR) or `spacy` sentence segmentation to evaluate self-containedness and to choose expansion stop points within a block.
     - Minimum standalone length: if a mined highlight is promoted as a standalone tip anywhere (now or later), require `min_standalone_chars` / `min_standalone_tokens`; if below, force expansion first, otherwise demote to highlight-only.
     - Contrastive-marker expansion trigger: if a highlight contains “but/however/except/unless/instead/not necessarily/inverse” (configurable list), force expansion to include the surrounding explanation within the chunk; if expansion is blocked by a hard boundary, keep as highlight-only.



- Compute `tip_density` for each chunk:
  - simplest: `num_highlights / max(1, chunk_chars/1000)` and also store raw counts.
- Aggregate tags at the chunk level by unioning highlight tags, and (optionally) adding tags derived directly from chunk text via the existing taxonomy module.&#x20;

6. Add boundary refinements: hard/medium/soft, callouts, and format-mode changes.

   - Implement the boundary hierarchy:
     - Hard boundaries: major headings, recipe boundaries, obvious non-content blocks (ToC/index/page headers/footers).&#x20;
     - Medium boundaries: subheadings, labeled callouts (“TIP:”, “NOTE:”, “Variation:”, “Troubleshooting:”), and format mode changes (prose → bullets/numbered/definition-like).&#x20;
     - Soft boundaries: paragraph breaks and small asides; do not split chunks on these.&#x20;
   - Add “sidebar chunk” behavior:
     - when a callout is detected, create a separate chunk that “inherits” the parent section title (store it in `section_path` and/or `title`) so distillation has context.&#x20;
   - Add “topic pivot marker” detection as a medium boundary heuristic (“Now that you understand…”, “In the next section…”).&#x20;
   - Enforce min/max chunk size:
     - if a section grows beyond `max_chars`, split at the best medium boundary within the window (fallback: split at paragraph boundary, but record reason `max_chars`).

7. Tests, fixtures, and regression-proofing.

   - Add unit tests under `tests/` for:
     - heading-path stack behavior and section chunking,
     - lane assignment of blurbs and quote-only content,
     - highlight gating (aphorisms become highlights, not standalone),
     - deterministic output ordering and stable ids.
   - Add a small text fixture derived from the sample output patterns:
     - include a praise blurb,
     - include a heading like “USING SALT” with several paragraphs,
     - include an aphorism line and an immediately following explanatory paragraph,
     - include a callout like “TIP:” or “NOTE:”.
       Use it to assert chunk boundaries and lanes match expectations. The sample `tips extract example.md` provides concrete snippets to mirror. &#x20;
   - Ensure legacy `tips.md` generation remains unchanged until you explicitly decide to deprecate it (that decision would be recorded here later).

8. (Optional) Add distillation over chunks via the existing mocked LLM layer.

   - If `cookimport/llm/` already provides an interface (currently mocked), add a new function like:
     distill\_knowledge\_chunk(chunk: ChunkCandidate, \*, highlights: list[ChunkHighlight]) -> DistilledKnowledge
     Keep it behind a CLI flag (e.g. `--distill-chunks`) so core staging stays deterministic and offline-capable.&#x20;

   - Cache distillation results keyed by:

     - input file hash + chunk id + chunk text hash + prompt version,
       so repeated runs are idempotent and cheap.

   - Operationalize “tip density as a cheap prioritizer for LLM time” via an explicit distillation policy:

     - Only distill `knowledge` lane chunks.
     - Sort candidate chunks by `tip_density` descending (tie-breaker: chunk length, then id).
     - Provide two selection modes (configurable):
       - `top_k`: distill the top K chunks by density.
       - `threshold`: distill only chunks with `tip_density >= min_tip_density`.
     - Always emit a small run report (e.g. `distillation_selection.json` or a section in `chunks.md`) listing:
       - which chunks were selected,
       - their densities,
       - why they were selected (mode + parameters).

## Validation and Acceptance

Run:

- `python -m cookimport.cli stage data/input/<cookbook>`&#x20;

Acceptance is met when, in the newest `data/output/<timestamp>/` folder:

1. A new folder exists: `chunks/<workbook_stem>/` containing:

   - `chunks.md`
   - multiple `c{index}.json` files (at least one `knowledge` chunk when the input contains technique sections).

2. `chunks.md` demonstrates structure-first grouping:

   - the “USING SALT” heading produces a single coherent chunk (or a small number of coherent chunks if split by max size), not many tiny outputs.&#x20;

3. Front matter blurbs similar to “This beautiful, approachable book…” appear as `noise` or `narrative`, not `knowledge`.&#x20;

4. Aphorisms like “the inverse isn’t necessarily so” are not emitted as standalone “final knowledge” items; they appear only as highlights inside a larger knowledge chunk that contains nearby context.&#x20;

5. Existing `tips/<workbook_stem>/tips.md` continues to be produced (until explicitly deprecated), so downstream users are not broken.&#x20;

6. Tests pass:

   - run the repo’s standard test command (likely `python -m pytest` if present) and expect all tests pass, including new chunking tests.

7. If distillation is enabled (optional flag), it follows the selection policy:

   - only selected chunks are distilled,
   - selection is explainable and recorded in output artifacts,
   - re-running does not re-distill unchanged chunks (cache hit).

## Idempotence and Recovery

- Staging already writes to a timestamped output directory; the chunking outputs must follow the same convention so re-running stage does not overwrite prior runs.&#x20;
- The chunker must be deterministic given the same input block stream and profile settings:
  - stable ordering,
  - stable `c{index}` numbering,
  - stable `chunks.md` formatting.
- If optional distillation is enabled, it must be cached and keyed so repeated runs reuse results.
- If optional embeddings / classifiers are enabled:
  - cache per-block embeddings (or other expensive features) keyed by block text hash + model name/version,
  - persist enough metadata (model name, thresholds, feature flags) into output artifacts to make runs reproducible,
  - fail gracefully (fall back to lexical heuristics) if optional deps are missing.
- If a heuristic causes unexpected splits or mis-lane assignments, the recovery path is:
  - inspect `chunks.md` (boundary reasons + lanes),
  - add/adjust a profile override (book-specific) rather than hardcoding one-off hacks,
  - add a regression test fixture.

## Artifacts and Notes

As you implement, paste short “before vs after” excerpts (indented) into this section for the three targeted failure modes:

- praise blurb routed to `noise`,
- “USING SALT” grouped coherently,
- aphorism no longer standalone.
  Keep each excerpt under \~30 lines to avoid turning this plan into a data dump.

## Interfaces and Dependencies

### Optional third-party NLP/ML accelerators (behind flags)

These are **optional** dependencies that can materially improve boundary decisions and lane classification. The default pipeline should remain deterministic and should run without them.

- **pySBD (********`pysbd`********)**: robust sentence boundary detection for messy OCR / book typography. Use inside an atom/block for:
  - self-containedness checks (is this highlight a complete thought?),
  - “expand or demote” logic when a highlight is clipped,
  - finding the nearest sensible expansion stop within a block.
- **spaCy (********`spacy`********)**: tokenization + POS/dependency parsing + sentence segmentation. Use to enrich existing heuristics:
  - imperative/modality detection (e.g., should/must),
  - causal/justification markers (because/so that/therefore),
  - robust sentence segmentation as an alternative to pySBD.
- **SentenceTransformers / SBERT (********`sentence-transformers`********)**: embeddings per block/atom to drive semantic cohesion decisions:
  - merge adjacent blocks when similarity stays high,
  - split when similarity drops sharply (especially in heading-sparse regions),
  - detect boilerplate/repeated blocks by clustering or near-duplicate similarity.
- **scikit-learn (********`scikit-learn`********)**: lightweight supervised models for lane classification (knowledge/narrative/noise), trained from a small labeled set exported from Label Studio.
- **BERTopic (********`bertopic`********)**: optional topic discovery / clustering across many chunks (e.g., “salt”, “emulsions”), useful for analysis and for detecting topic shifts that should block merges.
- **UMAP (********`umap-learn`********) + HDBSCAN (********`hdbscan`********)**: optional clustering / dimensionality reduction tooling (often used by BERTopic, also useful standalone).

This plan relies on the existing architecture and modules:

- `cookimport/parsing/signals.py` provides block-level signals like heading detection and instruction/ingredient likelihood.&#x20;
- `cookimport/parsing/tips.py` currently handles span extraction, repair, and judging; we will reuse it to produce highlights inside chunks. &#x20;
- `cookimport/parsing/atoms.py` provides atomization with neighbor context; reuse it if helpful for highlight span expansion.&#x20;
- `cookimport/parsing/tip_taxonomy.py` provides dictionary-based tagging; chunk tags should reuse this schema.&#x20;
- `cookimport/staging/writer.py` writes outputs; extend it to write `chunks/` artifacts.&#x20;
- The repo includes Label Studio integration for evaluation; later, consider adapting it to evaluate “containment recall” for chunking rather than exact-match tip extraction. &#x20;

Keep new code modular:

- `parsing/chunks.py` should contain chunk boundary logic and nothing about IO.
- `parsing/lane.py` (or additions in `signals.py`) should contain lane scoring and blurb/noise detection.
- `staging/writer.py` should format and persist artifacts.
- Models live in `core/models.py` alongside existing `TipCandidate`/`TopicCandidate`.&#x20;

End of initial plan (2026-01-31): created an implementation roadmap that converts tip-mining into a chunk-first pipeline with highlights, lane routing, deterministic boundaries, and regression tests, consistent with `PLANS.md` requirements.&#x20;

```

## docs/parsing/tip_parsing_old.md

```markdown
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
```

## docs/plans/2026-01-31-fix-recipe-segmentation-and-ingredient-matching.md

```markdown
# Fix Recipe Segmentation and Ingredient Matching Bugs

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document is maintained in accordance with `/docs/PLANS.md`.

## Purpose / Big Picture

After this change, the EPUB importer will correctly handle recipes that have sub-section headers like "For the Frangipane" and "For the Tart" within a single recipe, rather than treating them as separate recipes. Additionally, unmatched ingredients (like spices when the instruction says "add spices" collectively) will be assigned to appropriate steps rather than being dropped entirely.

User-visible outcome: Running `cookimport convert data/input/saltfatacidheat.epub` will produce:
- r87 (Apple and Frangipane Tart) with all its ingredients (almonds, sugar, almond paste, butter, eggs, etc.) and full instructions
- r84 (Classic Pumpkin Pie) with all spices (cinnamon, ginger, cloves) assigned to step 4 where "spices" are mentioned

## Progress

- [x] (2026-01-31 15:00Z) Analyzed root cause of r87 empty recipe: `_find_recipe_end` in epub.py treats "For the X" sub-headers as new recipe titles
- [x] (2026-01-31 15:00Z) Analyzed root cause of r84 missing ingredients: `assign_ingredient_lines_to_steps` doesn't handle collective terms like "spices"
- [x] (2026-01-31 15:05Z) Implement fix for sub-section header detection in `_find_recipe_end` - added `_is_subsection_header()` method
- [x] (2026-01-31 15:06Z) Implement fix for collective term matching in `assign_ingredient_lines_to_steps` - added category definitions and fallback pass
- [x] (2026-01-31 15:08Z) Add tests for both fixes - 4 new tests added
- [x] (2026-01-31 15:09Z) Verify fixes with actual EPUB conversion - r87 now has 11 ingredients/16 steps, r84 has ginger/cloves in step 4

## Surprises & Discoveries

- Observation: The EPUB book uses "For the X" as ingredient section sub-headers, which is common in professional cookbooks but wasn't accounted for.
  Evidence: Block 2891 "For the Frangipane" followed by ingredient blocks 2892-2899

- Observation: Recipes commonly use collective terms like "spices", "seasonings", "dry ingredients" in instructions rather than listing each ingredient.
  Evidence: r84 instruction says "Add the cream, pumpkin purée, sugar, salt, and spices" but individual spice names aren't mentioned.

## Decision Log

- Decision: Detect "For the X" patterns as sub-section headers, not new recipe titles
  Rationale: These are always within a recipe, indicating a logical grouping of ingredients (e.g., "For the Frangipane" vs "For the Tart")
  Date/Author: 2026-01-31 / Claude

- Decision: Add collective term matching for ingredient categories like "spices", "seasonings", "herbs"
  Rationale: This is common cookbook language. We can identify ingredient categories and match them to collective terms in instructions.
  Date/Author: 2026-01-31 / Claude

## Outcomes & Retrospective

### Results
Both fixes were successfully implemented and verified:

1. **r87 (Apple and Frangipane Tart)**: Now correctly extracted with 11 ingredients and 16 instructions. Confidence improved from 0.25 to 0.94. Block range expanded from 3 blocks to 36 blocks.

2. **r84 (Classic Pumpkin Pie)**: Step 4 now includes "ground ginger" and "ground cloves" (previously unassigned) because the instruction mentions "spices" collectively.

### Remaining Items
- "All-Butter Pie Dough" and "Flour for rolling" in r84 are still unassigned because the instructions use "chilled dough" and "well-floured board" rather than the exact ingredient names. This would require more sophisticated semantic matching.
- "ground cinnamon" is assigned to step 5 (which mentions "Cinnamon Cream") rather than step 4. This is technically a false positive match but not harmful.

### Lessons Learned
- Recipe sub-section headers ("For the X") are common in professional cookbooks and should be treated as ingredient groupings, not new recipe starts.
- Collective terms like "spices" are common in recipe instructions and can be used to assign unmatched ingredients by category.

## Context and Orientation

The EPUB import pipeline works as follows:

1. `cookimport/plugins/epub.py:EpubImporter` extracts blocks from EPUB HTML
2. `_detect_candidates()` segments blocks into recipe ranges using yield markers and ingredient headers
3. `_find_recipe_end()` determines where each recipe ends by scanning forward for new recipe starts
4. `cookimport/staging/draft_v1.py:recipe_candidate_to_draft_v1()` converts to final format
5. `cookimport/parsing/step_ingredients.py:assign_ingredient_lines_to_steps()` matches ingredients to steps

Key files:
- `/cookimport/plugins/epub.py` - Contains `_find_recipe_end()` that needs the sub-header fix
- `/cookimport/parsing/step_ingredients.py` - Contains ingredient matching logic that needs collective term support

## Plan of Work

### Fix 1: Sub-section header detection

In `cookimport/plugins/epub.py`, modify `_find_recipe_end()` to recognize "For the X" patterns as sub-section headers that should NOT terminate the current recipe.

Add a new helper method `_is_subsection_header(block: Block) -> bool` that returns True for blocks matching:
- Text starts with "For the" (case-insensitive)
- Text is short (under 50 chars)
- Text ends without a period

In `_find_recipe_end()`, before the `_is_title_candidate` check at line 716, add a check: if the block is a subsection header, continue (don't treat it as a new recipe start).

### Fix 2: Collective term matching for ingredients

In `cookimport/parsing/step_ingredients.py`, add support for matching ingredient categories to collective terms:

1. Define category mappings:
   - "spices" -> matches ingredients containing "cinnamon", "ginger", "cloves", "nutmeg", "paprika", etc.
   - "herbs" -> matches "basil", "thyme", "oregano", "parsley", etc.
   - "seasonings" -> matches both spices and "salt", "pepper"

2. In `assign_ingredient_lines_to_steps()`, after the main matching pass, do a fallback pass:
   - For any unassigned ingredient, check if it belongs to a category
   - Check if any step mentions that category's collective term
   - If so, assign the ingredient to that step

## Concrete Steps

1. Edit `/cookimport/plugins/epub.py`:
   - Add `_is_subsection_header()` method after `_is_variation_header()` (around line 724)
   - Modify `_find_recipe_end()` to skip subsection headers

2. Edit `/cookimport/parsing/step_ingredients.py`:
   - Add ingredient category definitions
   - Add collective term detection
   - Add fallback assignment pass

3. Run tests:
       cd /home/mcnal/projects/recipeimport
       source .venv/bin/activate
       pytest tests/ -v

4. Run conversion on test file:
       python -m cookimport convert data/input/saltfatacidheat.epub -o data/output/test-fix

5. Verify outputs:
   - Check r87.jsonld has ingredients and instructions
   - Check r84.json has ginger and cloves in step 4

## Validation and Acceptance

After the fix:

1. r87 (Apple and Frangipane Tart) should have:
   - At least 14 ingredients (almonds, sugar, almond paste, butter, eggs, salt, vanilla, almond extract, tart dough, flour, apples, cream, sugar for sprinkling)
   - At least 8 instruction steps

2. r84 (Classic Pumpkin Pie) final JSON should have:
   - "ground ginger" assigned to step 4 (which mentions "spices")
   - "ground cloves" assigned to step 4

## Idempotence and Recovery

All changes are additive. If something breaks, the previous behavior is preserved by simply removing the new checks. Tests can be run repeatedly.

## Artifacts and Notes

(To be filled with test outputs during implementation)
```

## docs/plans/2026-02-02-epub-job-splitting.md

```markdown
# Split EPUB Jobs and Merge Results

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, large EPUB files can be split into spine-range jobs when `cookimport stage` runs with multiple workers. The user still receives one cohesive workbook output (one set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple part outputs. The observable behavior is that an EPUB import with `--workers > 1` shows multiple jobs with spine ranges, then merges into a single workbook with sequential recipe IDs.

## Progress

- [x] (2026-02-02 03:00Z) Drafted ExecPlan for EPUB job splitting and merge.
- [x] (2026-02-02 03:18Z) Implemented EPUB spine-range support in the importer and provenance.
- [x] (2026-02-02 03:28Z) Added job planning/worker/merge support for EPUB splits using the existing PDF job split infrastructure.
- [x] (2026-02-02 03:36Z) Updated tests, docs, and short folder notes for the new behavior.

## Surprises & Discoveries

- Observation: The EPUB importer currently treats all spine items as a single linear block stream, and block indices reset per run, so split jobs need an explicit spine index to preserve global ordering during merges.
  Evidence: `cookimport/plugins/epub.py` builds blocks in `_extract_docpack` and uses `start_block`/`end_block` for provenance, with no spine metadata.

## Decision Log

- Decision: Split EPUBs by spine item ranges and store `start_spine`/`end_spine` in provenance locations to preserve global ordering across merged jobs.
  Rationale: Spine items are the natural unit of EPUB structure and can be counted cheaply during inspection; location metadata provides a stable ordering key even when block indices are local to each job.
  Date/Author: 2026-02-02 / Codex

- Decision: Reuse the existing PDF job planning and merge helpers by generalizing them for non-PDF importers, keeping PDF wrappers intact for backward compatibility.
  Rationale: Avoids re-implementing split/merge logic and keeps tests for PDF splitting valid.
  Date/Author: 2026-02-02 / Codex

## Outcomes & Retrospective

EPUB imports now support spine-range job splitting when `--workers > 1`, with merged outputs and sequential recipe IDs. The CLI plans EPUB jobs using spine counts, workers can process spine ranges in parallel, and the merge step rewrites IDs while combining tips, chunks, and raw artifacts. Tests were added for EPUB ID reassignment, and documentation now covers the new flag and `.job_parts` behavior. Remaining work: consider a future improvement to detect recipes spanning spine boundaries if that becomes a practical issue.

## Context and Orientation

The bulk ingestion workflow lives in `cookimport/cli.py` (`stage` command). It plans work items (jobs), executes them in a `ProcessPoolExecutor`, and merges results for split PDFs via `_merge_pdf_jobs`. Split jobs use `cookimport/cli_worker.py:stage_pdf_job` to run a page range and write raw artifacts into a temporary `.job_parts/` folder that the main process merges back into `raw/` after the merge finishes.

The EPUB importer is `cookimport/plugins/epub.py`. It reads the EPUB spine, converts HTML to linear `Block` objects, segments blocks into recipes, and writes provenance locations with `start_block`/`end_block` indices. There is no spine index in the provenance today, so split jobs would lose global ordering unless we add spine metadata.

The job range logic currently lives in `cookimport/staging/pdf_jobs.py` via `plan_pdf_page_ranges` and `reassign_pdf_recipe_ids`. We will generalize those helpers to allow EPUB splitting while keeping the PDF functions intact as wrappers.

## Plan of Work

First, extend `cookimport/core/models.py` and the EPUB inspector to record spine counts. Add a `spine_count` field (alias `spineCount`) to `SheetInspection`. Update `EpubImporter.inspect` to set `spine_count` using the EPUB spine length (via ebooklib or the zip fallback) so the CLI can decide when to split.

Next, update the EPUB importer to accept `start_spine` and `end_spine` range parameters and only parse the specified spine slice. In `cookimport/plugins/epub.py`, thread these parameters through `convert` and `_extract_docpack` into both the ebooklib and zip extraction paths. When parsing each spine item, annotate each generated `Block` with a `spine_index` feature. When building recipe provenance, compute `start_spine`/`end_spine` from the candidate blocks and include those values in the location dictionary. This gives merged jobs a stable ordering key. Keep the rest of the extraction logic unchanged.

Then generalize the job planning and merge helpers. In `cookimport/staging/pdf_jobs.py`, introduce a generic range planner and a generic ID reassigner that accept an importer name. Keep `plan_pdf_page_ranges` and `reassign_pdf_recipe_ids` as wrappers. Update the sort key helper to consider `start_spine` (and `startSpine` if present) ahead of `start_block` when ordering recipes.

Update the CLI to plan EPUB jobs and merge them using the same merge flow as PDF jobs. Add a new CLI flag such as `--epub-spine-items-per-job` (default 10) and a `_resolve_epub_spine_count` helper to read the count from inspection. Extend `JobSpec` to track EPUB ranges (`start_spine`/`end_spine`) and choose the correct worker entrypoint (`stage_epub_job` vs `stage_pdf_job`) based on the range kind. Add `stage_epub_job` in `cookimport/cli_worker.py` mirroring the PDF job flow: run the range, write raw artifacts to `.job_parts/<workbook>/job_<index>/raw`, clear `result.raw_artifacts`, and return a mergeable payload with timing. Finally, add a new merge helper in `cookimport/cli.py` (or generalize `_merge_pdf_jobs`) that can merge EPUB jobs by calling the generalized ID reassigner with importer name `epub` and then writing outputs exactly as the PDF merge does.

Add tests and docs. Create a small unit test for the generalized range planner and for the EPUB ID reassignment ordering (using synthetic `RecipeCandidate` objects with `start_spine` in provenance). Update `docs/architecture/README.md` and `docs/ingestion/README.md` to mention EPUB job splitting and the new CLI flag. Update `docs/IMPORTANT CONVENTIONS.md` to note that EPUB split jobs also write raw artifacts into `.job_parts/` during merges. Add a short note in `cookimport/README.md` (or another existing short doc in the folder) describing the EPUB job split behavior and the new flag. If any new understanding is needed, add a brief note under `docs/understandings/`.

## Concrete Steps

All commands are run from `/home/mcnal/projects/recipeimport`.

1) Update models and EPUB inspection.

   - Edit `cookimport/core/models.py` to add `spine_count` to `SheetInspection` with alias `spineCount`.
   - Edit `cookimport/plugins/epub.py` to populate `spine_count` in `inspect` using spine length.

2) Add EPUB range support and provenance metadata.

   - Add `start_spine`/`end_spine` parameters to `EpubImporter.convert` and `_extract_docpack`.
   - In `_extract_docpack_with_ebooklib` and `_extract_docpack_with_zip`, iterate spine items with indices and filter by range.
   - Pass the spine index into `_parse_soup_to_blocks` and store it in block features.
   - When building candidate provenance, compute and store `start_spine`/`end_spine` in the location dict.

3) Generalize job planning and ID reassignment.

   - In `cookimport/staging/pdf_jobs.py`, add a generic range planner and a generic `reassign_recipe_ids` helper. Keep the existing PDF wrapper functions.
   - Extend the recipe sort key to consider `start_spine` before `start_block`.

4) Extend CLI/worker job splitting.

   - Add CLI flag `--epub-spine-items-per-job` to `cookimport/cli.py` and plan EPUB jobs when `workers > 1` and spine count exceeds the threshold.
   - Extend `JobSpec` to track EPUB spine ranges and to display `spine` ranges in the worker panel.
   - Add `stage_epub_job` in `cookimport/cli_worker.py` and call it for EPUB split jobs.
   - Generalize `_merge_pdf_jobs` into a shared helper that accepts importer name and range metadata, then call it for PDF and EPUB merges.

5) Tests and docs.

   - Add unit tests for EPUB ID reassignment ordering (e.g., `tests/test_epub_job_merge.py`).
   - Update `docs/architecture/README.md`, `docs/ingestion/README.md`, and `docs/IMPORTANT CONVENTIONS.md` with the new EPUB split behavior.
   - Update `cookimport/README.md` with a short note about the new EPUB split flag.

## Validation and Acceptance

- Running `cookimport stage --workers 4 --epub-spine-items-per-job 10 data/input/<large.epub>` should show multiple worker lines with spine ranges (for example, `book.epub [spine 1-10]`) and a merge message `Merging N jobs for book.epub...`.
- The output folder should contain a single workbook under `intermediate drafts/`, `final drafts/`, and `tips/`, plus a single report JSON for that EPUB.
- Recipe identifiers in the final output should be sequential (`...:c0`, `...:c1`, ...), and any recipe-specific tips should reference the updated IDs.
- Raw artifacts should be merged into `raw/` from `.job_parts/` and the `.job_parts/` folder should be removed after a successful merge.
- `pytest tests/test_epub_job_merge.py tests/test_pdf_job_merge.py` should pass; the EPUB test should fail before these changes and pass after.

## Idempotence and Recovery

The changes are safe to rerun because each staging run writes to a new timestamped output folder. If a merge fails, the temporary `.job_parts/` folder remains for debugging; re-running the command will create a new output folder and a new merge attempt without mutating previous outputs.

## Artifacts and Notes

Expected log excerpt for an EPUB split run:

    Processing 1 file(s) as 3 job(s) using 4 workers...
    worker-1: cookbook.epub [spine 1-10] - Parsing recipes...
    worker-2: cookbook.epub [spine 11-20] - Parsing recipes...
    Merging 3 jobs for cookbook.epub...
    ✔ cookbook.epub: 120 recipes, 18 tips (merge 5.12s)

## Interfaces and Dependencies

- `cookimport/core/models.py`
  - Add `SheetInspection.spine_count: int | None` with alias `spineCount`.
- `cookimport/plugins/epub.py`
  - `EpubImporter.convert(path, mapping, progress_callback, start_spine: int | None = None, end_spine: int | None = None)`
  - `_extract_docpack(path, start_spine: int | None = None, end_spine: int | None = None)`
  - Store `spine_index` in block features and add `start_spine`/`end_spine` to provenance location.
- `cookimport/staging/pdf_jobs.py`
  - Add `plan_job_ranges` and `reassign_recipe_ids(importer_name=...)` helpers; keep existing PDF wrappers.
  - Update recipe sort key to consider `start_spine`.
- `cookimport/cli_worker.py`
  - Add `stage_epub_job` with the same mergeable payload format as `stage_pdf_job`.
- `cookimport/cli.py`
  - Add `--epub-spine-items-per-job` flag, EPUB job planning, and shared merge helper for split jobs.

Change note: 2026-02-02 — Initial ExecPlan created for EPUB job splitting.
Change note: 2026-02-02 — Updated progress, outcomes, and plan details after implementing EPUB job splitting and tests/docs.
```

## docs/plans/2026-02-02-split-pdf-jobs-and-merge.md

```markdown
# Split PDF Jobs and Merge Results

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a single large PDF can fully utilize multiple workers by being split into page-range jobs (for example, a 200 page PDF with 4 workers runs as four jobs over pages 1–50, 51–100, 101–150, and 151–200). The user still receives one cohesive workbook output (single set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple “part” outputs. The new behavior is observable by running `cookimport stage` with `--workers > 1` on a large PDF and seeing parallel job progress plus a single workbook output folder when the run completes.

## Progress

- [x] (2026-02-02 00:00Z) Drafted initial ExecPlan with proposed job splitting + merge design.
- [x] (2026-02-02 02:05Z) Implemented job planning for PDF page splits in `cookimport/cli.py`.
- [x] (2026-02-02 02:12Z) Added page-range support to `cookimport/plugins/pdf.py` and propagated OCR/text paths.
- [x] (2026-02-02 02:35Z) Added job-level worker entrypoint and merge logic for multi-job PDFs.
- [x] (2026-02-02 02:55Z) Updated docs + conventions and added unit tests for job planning and ID rewriting.

## Surprises & Discoveries

- Observation: `cookimport/cli.py` always passes a `MappingConfig` to workers even when no mapping file is provided, so the current `stage_one_file` path never runs `importer.inspect` automatically.
  Evidence: `cookimport/cli.py` sets `base_mapping = mapping_override or MappingConfig()` and always passes it into `stage_one_file`.
- Observation: `ProcessPoolExecutor` can raise `PermissionError` in restricted environments (e.g., during CLI tests), preventing worker startup.
  Evidence: CLI test run failed with `PermissionError: [Errno 13] Permission denied` during ProcessPool initialization.

## Decision Log

- Decision: Merge multi-job PDF outputs in the main process and rewrite recipe IDs to a single global sequence (`c0..cN`) so IDs remain stable regardless of whether a PDF was split.
  Rationale: This avoids ID collisions across jobs and keeps stable IDs consistent with the existing full-file ordering scheme.
  Date/Author: 2026-02-02 / Codex

- Decision: Keep the existing worker path for files that are not split, so normal multi-file runs still write outputs in parallel.
  Rationale: Avoids moving all output writing to the main process and preserves current performance.
  Date/Author: 2026-02-02 / Codex

- Decision: Use a single configurable threshold (`--pdf-pages-per-job`, default 50) to decide when to split and how many jobs to create (capped by worker count).
  Rationale: Matches the example (200 pages / 4 workers → 4 jobs of 50 pages) while keeping the CLI surface minimal.
  Date/Author: 2026-02-02 / Codex

- Decision: Fall back to serial execution if `ProcessPoolExecutor` cannot be created (PermissionError).
  Rationale: Keeps staging usable in restricted environments while preserving parallelism when available.
  Date/Author: 2026-02-02 / Codex

## Outcomes & Retrospective

Implemented PDF job splitting and merge flow so large PDFs can run in parallel while
producing a single cohesive workbook output. The CLI now plans jobs, workers can
process page ranges, and the main process merges results, rewrites IDs, and merges
raw artifacts. Documentation and unit tests were updated to cover the new behavior.

Lessons learned: isolating raw artifacts in job-specific folders kept merge payloads
light and made the final merge deterministic.

## Context and Orientation

The ingestion pipeline is driven by `cookimport/cli.py:stage`, which enumerates source files, starts a `ProcessPoolExecutor`, and calls `cookimport/cli_worker.py:stage_one_file` per file. `stage_one_file` selects an importer from `cookimport/plugins/registry.py`, runs `importer.convert(...)` to produce a `ConversionResult`, generates knowledge chunks, enriches a `ConversionReport`, and writes outputs via `cookimport/staging/writer.py`.

The PDF importer lives in `cookimport/plugins/pdf.py`. It currently processes the entire document in one pass and assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}`. OCR is optional and implemented in `cookimport/ocr/doctr_engine.py:ocr_pdf`, which already accepts `start_page` and `end_page` (exclusive).

For this change we introduce a “job” as the new unit of work. A job is either an entire file (non-split) or a page-range slice of a PDF (split). Each job executes `PdfImporter.convert` on its page range. After all jobs for a file complete, their results are merged, IDs are re-assigned in global order, and a single output folder is written.

## Plan of Work

First, add job planning logic to `cookimport/cli.py`. Create a small helper (either inside `cli.py` or a new module such as `cookimport/cli_jobs.py`) that inspects each file to decide whether it should be split. For PDF files, retrieve a page count via `PdfImporter.inspect` (add a `page_count` field to `SheetInspection` in `cookimport/core/models.py`, and populate it in `PdfImporter.inspect`). If `page_count > --pdf-pages-per-job` and `workers > 1`, generate page ranges sized at `ceil(page_count / job_count)` where `job_count = min(workers, ceil(page_count / pdf_pages_per_job))`. Each range is `[start_page, end_page)` with 0-based indexing. Non-PDFs and PDFs that do not meet the threshold stay as single jobs.

Second, extend `PdfImporter.convert` to accept optional `start_page` and `end_page` parameters. When a range is provided, the OCR path should call `ocr_pdf(path, start_page=..., end_page=...)`, and the text extraction path should iterate pages only over that range, passing the absolute page index into `_extract_blocks_from_page`. Update progress messages to reflect `page_num + 1` and the total pages in the slice. Add a warning to the report if the requested slice is empty (start >= end). Ensure the rest of the extraction pipeline (candidate segmentation, tips, topics, raw artifacts) works unchanged on the subset of blocks.

Third, refactor `cookimport/cli_worker.py` so it can run a page-range job and return a mergeable payload without writing full outputs. Extract a helper (for example `run_import`) that executes the import, timing, and report enrichment but returns a `ConversionResult`. For split jobs, write only raw artifacts to a job-specific temporary directory (for example `{out}/.job_parts/{workbook_slug}/job_{index}/raw/...`) and clear `result.raw_artifacts` before returning to reduce inter-process payload size. For non-split files, keep the existing `stage_one_file` behavior so outputs are written in the worker.

Fourth, add a merge step in `cookimport/cli.py` for files that were split into multiple jobs. Collect `JobResult` payloads, sort them by `start_page`, and merge their `ConversionResult` lists (recipes, tip candidates, topic candidates, non-recipe blocks). Recompute `tips` using `partition_tip_candidates` so it matches the merged tip candidate list. Then rewrite recipe identifiers and provenance to a global sequence:

- Sort merged recipes by their provenance `location.start_page` (fall back to `location.start_block` or the merge order).
- For each recipe at global index `i`, set `candidate.identifier = generate_recipe_id("pdf", file_hash, f"c{i}")`, update `candidate.provenance["@id"]` (and `id` if present), and set `candidate.provenance["location"]["chunk_index"] = i`.
- Build a mapping from old IDs to new IDs. Update `TipCandidate.source_recipe_id` and any `tip.provenance["@id"]` or `tip.provenance["id"]` that match old IDs.

After IDs are updated, apply the CLI `--limit` (once, at the merged level), regenerate knowledge chunks using `chunks_from_non_recipe_blocks` or `chunks_from_topic_candidates`, and build a fresh `ConversionReport` with totals and `enrich_report_with_stats`. Write the merged outputs using `write_intermediate_outputs`, `write_draft_outputs`, `write_tip_outputs`, `write_topic_candidate_outputs`, `write_chunk_outputs`, and `write_report` into the normal output directories. Finally, merge raw artifacts by moving job raw folders into the final `{out}/raw/...` tree; if name collisions occur, prefix the filename with the job index to preserve uniqueness. Remove the temporary `.job_parts` folder once the merge succeeds.

Fifth, update the progress UI. The overall progress bar should count total jobs, not just files, and the worker status lines should include the page range (for example `cookbook.pdf [pages 1-50]`). After a file’s jobs finish and merge begins, log a line like `Merging 4 jobs for cookbook.pdf...` so users understand the second phase.

Finally, add tests and docs. Create unit tests for page-range slicing and merged-ID rewriting (in a new `tests/test_pdf_job_merge.py` or similar) using synthetic `ConversionResult` objects so we do not require real PDFs. Update `docs/architecture/README.md` and `docs/ingestion/README.md` to describe PDF job splitting and the merge step, and add a short note in a relevant folder (likely `cookimport/README.md` or a new short doc in `cookimport/`) explaining how job splitting behaves. If the output structure introduces a `.job_parts` temp folder, document it in `docs/IMPORTANT CONVENTIONS.md`.

## Concrete Steps

All commands assume the working directory `/home/mcnal/projects/recipeimport`.

1) Inspect current CLI/worker/PDF surfaces (if not already done):

    rg -n "stage_one_file|ProcessPoolExecutor|PdfImporter" cookimport

2) Implement model + PDF changes:

    - Edit `cookimport/core/models.py` to add `page_count: int | None = Field(default=None, alias="pageCount")` to `SheetInspection`.
    - Edit `cookimport/plugins/pdf.py` to populate `page_count` in `inspect`, and add `start_page`/`end_page` support in `convert` plus the OCR/text extraction paths.

3) Implement job planning + merging:

    - Edit `cookimport/cli.py` to add `--pdf-pages-per-job` and job planning helpers, and to schedule job futures differently for split vs non-split files.
    - Edit `cookimport/cli_worker.py` to add a job-capable entrypoint (and refactor shared logic as needed) that returns mergeable payloads and writes raw artifacts to a job temp folder.
    - Add merge helpers in `cookimport/cli.py` or a new module (for example `cookimport/staging/merge.py`).

4) Tests (use local venv):

    - Create/activate `.venv` if needed, then install dev deps:

        python -m venv .venv
        . .venv/bin/activate
        python -m pip install --upgrade pip
        pip install -e .[dev]

    - Run targeted tests:

        pytest tests/test_pdf_job_merge.py tests/test_cli_output_structure.py

5) Docs updates:

    - Edit `docs/architecture/README.md`, `docs/ingestion/README.md`, and `docs/IMPORTANT CONVENTIONS.md` as described in Plan of Work.
    - Add/adjust a short, folder-local note describing the new job split behavior.

## Validation and Acceptance

Acceptance is met when the following manual scenario works and outputs are cohesive:

1) Run `cookimport stage --workers 4 --pdf-pages-per-job 50 data/input/<large.pdf>` and observe the worker panel showing multiple jobs with page ranges.
2) In the output folder (`data/output/{timestamp}`), verify that only one workbook slug exists under `intermediate drafts/`, `final drafts/`, and `tips/`, with sequential `r{index}.json(ld)` numbering and a single report JSON file.
3) Confirm that recipe `identifier` values are sequential (`...:c0`, `...:c1`, …) across the merged output, and that any recipe-specific tips reference the updated recipe IDs.
4) Verify raw artifacts exist under `raw/pdf/{hash}/...` with no filename collisions (job prefixing is acceptable if needed).

If automated tests are added, they should fail before this change and pass after. Specifically, the new merge test must assert that merged recipe IDs and tip `sourceRecipeId` values are updated to the global sequence.

## Idempotence and Recovery

Re-running the same command is safe because outputs are written into a new timestamped folder. If a merge fails mid-way, the temporary job folder under `{out}/.job_parts/` remains for debugging; re-run the command to regenerate a clean output folder. If a job fails, the merge should abort for that file and write an error report so the run still completes for other files.

## Artifacts and Notes

Expected log lines during a split run (example):

    Processing 1 file(s) as 4 job(s) using 4 workers...
    worker-1: cookbook.pdf [pages 1-50] - Parsing recipes...
    worker-2: cookbook.pdf [pages 51-100] - Parsing recipes...
    Merging 4 jobs for cookbook.pdf...
    ✔ cookbook.pdf: 128 recipes, 14 tips (merge 6.42s)

## Interfaces and Dependencies

- `cookimport/core/models.py`
  - `SheetInspection.page_count: int | None` (alias `pageCount`).
- `cookimport/plugins/pdf.py`
  - `PdfImporter.convert(path, mapping, progress_callback, start_page: int | None = None, end_page: int | None = None)`
  - Use `ocr_pdf(path, start_page=..., end_page=...)` for OCR path; iterate `fitz` pages in `[start_page, end_page)` for non-OCR.
- `cookimport/cli_worker.py`
  - New job entrypoint returning a `JobResult` containing `ConversionResult` (with raw artifacts cleared), job metadata, and duration.
- `cookimport/cli.py`
  - Job planning helper, CLI options for `--pdf-pages-per-job`, and merge orchestration.
- `cookimport/staging/writer.py`
  - No interface changes; reuse existing write helpers for merged output.

Change note: 2026-02-02 — Initial ExecPlan created in response to the request to plan before implementation.
Change note: 2026-02-02 — Updated progress, outcomes, and documented completion of PDF job splitting implementation (including serial fallback note).
```

## docs/plans/epub_split.md

```markdown
# Split large EPUBs into worker jobs and merge into one cohesive workbook

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan is governed by `docs/PLANS.md` and must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, a single large `.epub` can fully utilize multiple workers by being split into “spine-range jobs” (contiguous ranges of reading-order documents). For example, a big EPUB with 80 spine items and 4 workers can run as 4 jobs over spine items 0–19, 20–39, 40–59, and 60–79. The user still receives one cohesive workbook output (single set of intermediate drafts, final drafts, tips, raw artifacts, and a single report) rather than multiple “part” outputs.

The new behavior is observable by running `cookimport stage` with `--workers > 1` on a large EPUB and seeing parallel job progress plus a single workbook output folder when the run completes. The merged outputs must have stable sequential recipe IDs as if the EPUB had been processed in one pass.

## Progress

- [ ] (2026-02-01 00:00Z) Read the existing PDF job splitting implementation and identify reusable job planning, worker entrypoint, temp output layout, and merge helpers.
- [ ] Add EPUB inspection fields needed to plan spine-range jobs (spine item count).
- [ ] Extend `cookimport/plugins/epub.py` so `convert` can process a spine slice (plus optional overlap) and so blocks/candidates record absolute spine indices in provenance.
- [ ] Extend CLI job planning to split EPUBs into spine-range jobs (behind a threshold flag) and schedule those jobs in the existing process pool.
- [ ] Implement EPUB merge logic in the main process that combines job results, rewrites recipe IDs to a single global sequence, merges raw artifacts, and writes one workbook output folder.
- [ ] Add tests for job planning, slice filtering, and merged ID rewriting (no real EPUB required; synthetic objects are acceptable).
- [ ] Update docs and CLI help strings, and add a note describing the temporary `.job_parts` behavior for split EPUBs.
- [ ] Validate on a real large EPUB: confirm parallel job progress and one cohesive output folder; document measured speedup and any accuracy changes.

## Surprises & Discoveries

- Observation: (fill during implementation)
  Evidence: (short command output or failing test snippet)

## Decision Log

- Decision: (fill during implementation)
  Rationale: (why this path was chosen)
  Date/Author: (YYYY-MM-DD / who)

## Outcomes & Retrospective

- (Fill at milestone completion and at the end: what improved, what broke, what remains, and lessons learned.)

## Context and Orientation

The ingestion pipeline is driven by `cookimport/cli.py:stage`, which enumerates source files, starts a `concurrent.futures.ProcessPoolExecutor`, and calls a worker entrypoint (commonly `cookimport/cli_worker.py:stage_one_file`) per unit of work. Plugins are chosen via `cookimport/plugins/registry.py` and implement `detect`, `inspect`, and `convert`. Converting unstructured sources typically produces a linear sequence of `Block` objects which are segmented into `RecipeCandidate`, `TipCandidate`, and `TopicCandidate` objects, along with raw artifacts and a report.

This repository already contains a “job splitting + merge” pattern for PDFs: a large file is split into multiple jobs, each job processes a slice, the main process merges results into one workbook output, and recipe identifiers are rewritten to a single stable global sequence (`...:c0`, `...:c1`, …). This ExecPlan extends that same pattern to EPUB files to achieve the same benefit for large cookbooks.

Definitions used in this plan:

- “Worker”: a separate operating-system process used to run Python in parallel on multiple CPU cores.
- “Job”: one unit of work submitted to the worker pool. For an EPUB split run, each job is a contiguous slice of the EPUB’s reading order.
- “EPUB spine item”: an entry in the EPUB’s OPF “spine”, which defines the reading order. In practice this corresponds to an HTML/XHTML “chapter” file inside the EPUB container.
- “Spine-range job”: a job defined by `[start_spine_index, end_spine_index)` (0-based, end exclusive).
- “Overlap”: extra spine items included on each side of a job slice to preserve segmentation context near boundaries. Overlap is used only for context; the job returns only recipes whose start location falls within the job’s owned range to avoid duplicates.
- “Owned range”: the non-overlapped spine range that a job is responsible for contributing to the final merged output.

Assumptions this plan relies on (verify in code before editing):

- `cookimport/plugins/epub.py` exists and uses EbookLib / BeautifulSoup / lxml for parsing.
- The PDF split implementation already introduced: (a) a representation of per-file jobs, (b) a `.job_parts` output convention for split files, (c) a merge step in the main process that rewrites recipe IDs and merges raw artifacts, and (d) a serial fallback if `ProcessPoolExecutor` cannot be created (for example due to `PermissionError` in restricted environments).
- `RecipeCandidate` (and related models) carry provenance that can be extended to include spine indices and block indices so that ordering and filtering are deterministic.

If any of those assumptions are false, update this plan’s Decision Log with the chosen adaptation and ensure all sections remain self-contained.

## Plan of Work

This work mirrors the PDF splitting approach: plan jobs in the CLI, teach the EPUB importer to process only a slice, have workers produce mergeable partial results without writing the full workbook outputs, then merge in the main process and write one cohesive output.

### Milestone 1: Reuse and generalize the existing job framework for a new “epub spine slice” job kind

By the end of this milestone you will know exactly which functions and data structures the PDF split system uses for job planning, worker execution, temp output folders, and merging, and you will have a clear place to add EPUB job support.

Work:

Read the files involved in the PDF split flow and write down the exact names and signatures you will reuse. Specifically locate:

- Where jobs are planned (likely inside `cookimport/cli.py` or a helper module).
- How a job is represented (a dataclass or Pydantic model holding job metadata such as kind, slice bounds, and output temp paths).
- The worker entrypoint for a job and what it returns to the parent process (a “JobResult” or similar).
- The merge function and how it rewrites recipe IDs and merges raw artifacts into the final output.

Decision to make and record:

- Whether to add EPUB support by introducing a new job kind (recommended), or by generalizing “slice jobs” into a single abstraction used by both PDF and EPUB. Prefer the smallest change that preserves readability and testability.

### Milestone 2: Add EPUB inspection data needed for splitting (spine item count)

By the end of this milestone, the CLI can cheaply determine how many spine items an EPUB contains without performing the full conversion.

Work:

- In `cookimport/plugins/epub.py`, implement or extend `EpubImporter.inspect(path)` so it returns a count of spine items (document items in reading order).
- Decide where to store this in inspection models:
  - If your PDF split already added `SheetInspection.page_count`, extend the same inspection model with a new optional `spine_item_count` field (preferred for symmetry).
  - If inspection models do not have a natural place for this, add a new field to the top-level `WorkbookInspection` such as `epub_spine_item_count`. Record the choice in the Decision Log.

Implementation detail (what “spine item count” should mean):

- Open the EPUB using EbookLib and compute the number of document items in the spine reading order.
- Count only document content (HTML/XHTML) items that will actually produce blocks; ignore images, stylesheets, and non-document items.
- The count must be deterministic and stable across runs, because the split planner will use it.

Proof:

- `cookimport inspect some.epub` (or whatever command triggers inspection) shows the spine count in the inspection output or report artifacts.
- A small unit test can call `EpubImporter.inspect` on a minimal EPUB fixture and assert the count is correct.

### Milestone 3: Teach the EPUB importer to convert a spine slice with overlap and stable provenance

By the end of this milestone, `EpubImporter.convert` can run on a subset of spine items and produce results whose provenance includes absolute spine indices (so merge ordering and slice filtering are deterministic).

Work:

- Extend `cookimport/plugins/epub.py:EpubImporter.convert` to accept optional keyword arguments:
  - `start_spine: int | None = None`
  - `end_spine: int | None = None`
  - `owned_start_spine: int | None = None`
  - `owned_end_spine: int | None = None`

Interpretation:

- The importer processes the “slice range” `[start_spine, end_spine)` (this may include overlap).
- The importer filters its produced recipe candidates (and any recipe-specific tip candidates) to only those whose start location lies within the “owned range” `[owned_start_spine, owned_end_spine)`.
- If no slice is provided, behavior is unchanged (full EPUB conversion).

How to implement without breaking existing behavior:

- Identify where EPUB content is enumerated today. Usually this looks like: iterate over spine items in reading order, parse each HTML/XHTML file into blocks, append blocks to one list, then run segmentation.
- Modify enumeration so that, when a slice is provided, you only iterate spine items within `[start_spine, end_spine)`. Critically, preserve the absolute spine index (0-based in full EPUB) as `spine_index` on every block’s provenance location.
- Ensure the block-level provenance also contains a stable per-spine-item block index (for example `block_index_within_spine`) so ordering within a spine item is stable. If a global block index already exists, keep it, but make sure it remains deterministic for sliced runs.

Filtering rule (prevents duplicates when overlap is used):

- Define a function that determines the “start location” of a `RecipeCandidate`. Prefer the earliest block that the candidate claims as its provenance location.
- A candidate belongs to the job if:
  - `owned_start_spine <= candidate.provenance.location.spine_index < owned_end_spine`.
- Apply the same rule to recipe-specific tips if they are anchored to a recipe start location or if they reference a source recipe ID; in ambiguous cases keep tips and let the merge step re-partition them, but ensure no duplicate recipe-specific tips survive the merge.

Edge cases to handle:

- Empty slice: if `start_spine >= end_spine`, return an empty `ConversionResult` with a warning in the report.
- Single-spine EPUB: splitting should not occur; slice conversion still works but produces little benefit.

Proof:

- A targeted unit test can build synthetic blocks with spine indices and prove that slice conversion yields candidates whose provenance spine indices are in the owned range.
- A manual run on a real EPUB with `--workers 1` and an explicit slice (temporary CLI flag or a direct call in a small dev script) produces reasonable partial outputs.

### Milestone 4: Plan EPUB spine-range jobs in the CLI and run them in the worker pool

By the end of this milestone, `cookimport stage` can split a single large EPUB into multiple spine-range jobs, submit them to workers, and collect job results.

Work:

- In `cookimport/cli.py`, extend the existing job planning helper to recognize `.epub` inputs and produce EPUB jobs when all of the following are true:
  - `--workers > 1`
  - The importer selected for the file is the EPUB importer.
  - `spine_item_count` is greater than a threshold derived from a new CLI flag (see below).

Add new CLI flags (name them to match the existing PDF flag style):

- `--epub-spine-items-per-job` (integer, default 20; must be > 0)
  - This controls when splitting happens and the approximate size of each job.
- `--epub-spine-overlap-items` (integer, default 1; can be 0)
  - This controls how many spine items of overlap are included on each side of a job slice for context.

Job planning algorithm (deterministic and simple):

- Let `S = spine_item_count`.
- If `S <= epub_spine_items_per_job` or `workers == 1`, create a single non-split job for the file.
- Otherwise:
  - Let `job_count = min(workers, ceil(S / epub_spine_items_per_job))`.
  - Let `range_size = ceil(S / job_count)`.
  - For `job_index` from 0 to `job_count-1`:
    - `owned_start = job_index * range_size`
    - `owned_end = min(S, owned_start + range_size)`
    - `slice_start = max(0, owned_start - overlap)`
    - `slice_end = min(S, owned_end + overlap)`
    - Create an EPUB job with these four bounds and the `job_index`.
- Ensure the final job list covers `[0, S)` in owned ranges with no gaps and no overlaps (owned ranges), even though slice ranges will overlap.

Worker execution:

- Reuse the existing worker entrypoint pattern from the PDF split flow. Add EPUB job support by:
  - Passing `start_spine`, `end_spine`, `owned_start_spine`, `owned_end_spine` into `EpubImporter.convert`.
  - Writing raw artifacts into a job temp folder under `.job_parts` and returning a small payload (do not return all raw artifacts over IPC if they are large).
  - Returning job metadata: file path, job index, owned range, slice range, duration, counts.

Resilience:

- Preserve the existing serial fallback: if `ProcessPoolExecutor` cannot be created, process as a single non-split job (log a warning that parallelism is disabled).

Proof:

- Running `cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 some_large.epub` shows multiple worker status lines that include spine ranges.
- The staging run finishes without writing multiple workbook roots (merge happens next milestone).

### Milestone 5: Merge EPUB job results into a single cohesive workbook and write outputs once

By the end of this milestone, split EPUB runs produce exactly one workbook output folder with stable IDs and consistent reports.

Work:

- Add or extend the main-process merge step for “split files” to support EPUB jobs. Follow the same high-level strategy as PDF merge:
  - Collect all `JobResult` objects for a given EPUB file.
  - Sort jobs by `owned_start_spine`.
  - Merge their `ConversionResult` payloads into one merged `ConversionResult` for the file.
  - Rewrite recipe identifiers to a single global sequence so IDs do not depend on splitting.
  - Merge raw artifacts from `.job_parts` into the final raw folder and remove `.job_parts` on success.
  - Write intermediate drafts, final drafts, tips, topics, chunks, and the report using existing writer helpers.

Merging details to make deterministic:

- Ordering for merged recipes:
  - Sort by `(recipe.provenance.location.spine_index, recipe.provenance.location.start_block_index)` if those fields exist.
  - If only block ordering exists, ensure it is stable and derived from spine ordering.
- ID rewriting:
  - Use the existing EPUB ID scheme if one exists, but rewrite to sequential suffixes (`c0..cN`) in merged order.
  - Build an `old_id -> new_id` mapping and update all references:
    - recipe-specific tips’ `source_recipe_id` (or equivalent field)
    - any provenance `@id` or `id` values that embed or reference the old recipe identifier
- Tip recomputation:
  - If the pipeline partitions tips after extraction, run that partitioning on the merged candidates once, in the main process, so “general vs recipe-specific” is consistent.

Raw artifacts:

- For split jobs, the worker should write raw artifacts to:
  - `{out}/.job_parts/{workbook_slug}/job_{job_index}/raw/...`
- The merge step should merge these into the final raw artifact tree, preferring deterministic naming. If collisions occur, prefix the filename with `job_{job_index}_`.

Output writing policy (important for consistency):

- For split EPUBs, only the main process writes the final workbook outputs (intermediate drafts, final drafts, tips, report).
- For non-split files (including non-split EPUBs), preserve the existing “worker writes outputs” behavior to avoid slowing normal multi-file parallel runs.

Proof:

- A split EPUB run produces:
  - One workbook slug under `intermediate drafts/`, `final drafts/`, `tips/`, and a single report JSON.
  - Sequential recipe identifiers in the merged output.
  - No `.job_parts` directory remaining after success (unless configured to keep for debugging).

### Milestone 6: Tests and documentation

By the end of this milestone, the behavior is protected by tests and discoverable to users.

Tests to add (prefer unit tests that do not require real EPUB files):

- Job planning test:
  - Given `spine_item_count=80`, `workers=4`, `items_per_job=20`, `overlap=1`, assert you get 4 jobs with owned ranges `[0,20) [20,40) [40,60) [60,80)` and slice ranges expanded by 1 on both sides where possible.
- Slice filtering test:
  - Create synthetic `RecipeCandidate` objects with provenance spine indices spanning the overlap boundary, ensure the filter keeps only those in the owned range.
- Merge ID rewrite test:
  - Create two or more synthetic job results containing recipes and recipe-specific tips referencing the old IDs; after merge, assert IDs are sequential and tip references were updated.

Documentation updates:

- Update CLI help for new flags.
- Update the same docs that describe PDF splitting to mention EPUB splitting and the “spine-range job” concept.
- Document `.job_parts` for EPUB (location, what it contains, and when it is removed).

Proof:

- `pytest -q` passes and includes at least one new test file covering EPUB splitting.
- The docs mention how to tune `--epub-spine-items-per-job` and warn that overly aggressive worker counts can increase RAM usage (important for users on smaller machines).

## Concrete Steps

All commands are run from the repository root.

1) Find the EPUB importer and current conversion flow.

    rg -n "class .*Epub|EpubImporter|epub\\.py" cookimport/plugins
    rg -n "def inspect\\(|def convert\\(" cookimport/plugins/epub.py

2) Find the existing job splitting framework (from the PDF work) and identify extension points.

    rg -n "Job|job_parts|pdf-pages-per-job|merge" cookimport/cli.py cookimport/cli_worker.py cookimport -S

3) Implement inspection spine count.

    - Edit `cookimport/plugins/epub.py` to compute spine count in `inspect`.
    - Edit `cookimport/core/models.py` (or the relevant inspection model file) to store spine count in the inspection result.

4) Implement slice conversion with overlap and owned-range filtering.

    - Edit `cookimport/plugins/epub.py:EpubImporter.convert` to accept the new keyword args and limit iteration to the slice range.
    - Ensure block provenance includes absolute `spine_index` and a stable within-spine block index.

5) Add CLI flags and plan EPUB jobs.

    - Edit `cookimport/cli.py` to add `--epub-spine-items-per-job` and `--epub-spine-overlap-items`.
    - Extend the job planner to create EPUB jobs using the algorithm described above.

6) Add worker execution support.

    - Edit `cookimport/cli_worker.py` to accept EPUB jobs and pass slice bounds into `EpubImporter.convert`.
    - For EPUB slice jobs, write raw artifacts to `.job_parts/...` and return a light payload.

7) Add merge support.

    - Edit the merge logic (where PDF merge happens) to handle EPUB jobs:
      merge results, rewrite IDs, update references, merge raw artifacts, write final outputs.

8) Run tests and add missing ones.

    pytest -q

9) Manual verification on a large EPUB.

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/large.epub

    Expected high-signal log lines (example, wording may differ):

      Processing 1 file(s) as 4 job(s) using 4 workers...
      worker-1: cookbook.epub [spine 0-21; owned 0-20]
      worker-2: cookbook.epub [spine 19-41; owned 20-40]
      Merging 4 jobs for cookbook.epub...
      ✔ cookbook.epub: N recipes, M tips (merge X.XXs)

## Validation and Acceptance

Acceptance is met when all of the following are true:

1) Split run produces parallel job progress and one cohesive output folder.

- Running:

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/<large.epub>

  shows multiple concurrent jobs with spine ranges, followed by a merge message.

- The output directory contains exactly one workbook slug for that EPUB under:
  - `intermediate drafts/`
  - `final drafts/`
  - `tips/`
  - and a single report file.

2) Merged identifiers are stable and sequential.

- Recipe identifiers in the final merged output are sequential (`...:c0`, `...:c1`, …) and do not depend on whether splitting occurred.
- Any recipe-specific tips reference the rewritten recipe IDs.

3) Overlap does not produce duplicates.

- The final merged output contains no duplicate recipes caused by overlap slices.

4) Serial fallback works.

- If `ProcessPoolExecutor` cannot be created (for example due to `PermissionError`), the CLI logs a warning and processes the EPUB as one non-split job, still producing a valid workbook output.

5) Tests cover the new behavior.

- New tests fail before the change and pass after. At minimum:
  - job planning ranges
  - owned-range filtering
  - merge ID rewriting and reference updates

## Idempotence and Recovery

Re-running the same command is safe because outputs are written into a new timestamped folder. If a merge fails mid-way, the temporary job folder under `{out}/.job_parts/` remains for debugging. Re-run to regenerate a clean output folder. If a job fails, the merge should abort for that file and write an error record, while allowing other files in the same run to complete.

If splitting causes unexpected extraction regressions on a particular EPUB, users can disable splitting by running with `--workers 1` or by setting `--epub-spine-items-per-job` to a very large number so the file is not split.

## Artifacts and Notes

Keep the following evidence snippets here as you implement:

- A short `pytest` transcript showing new tests passing.
- A run transcript showing split job progress and a merge line.
- A tiny excerpt of one merged recipe JSON showing `identifier` rewritten to `...:c{n}` and a recipe-specific tip referencing the new ID.

Example (replace with real output):

    pytest -q
    ... 128 passed

    cookimport stage --workers 4 --epub-spine-items-per-job 20 --epub-spine-overlap-items 1 data/input/large.epub
    Processing 1 file(s) as 4 job(s) using 4 workers...
    Merging 4 jobs for large.epub...
    ✔ large.epub: 312 recipes, 28 tips

## Interfaces and Dependencies

You must end with these concrete interfaces (update names to match the existing job framework you reuse):

- `cookimport/plugins/epub.py`
  - `EpubImporter.inspect(path) -> WorkbookInspection` (or equivalent) must populate an integer spine item count field.
  - `EpubImporter.convert(path, mapping, progress_callback, start_spine: int | None = None, end_spine: int | None = None, owned_start_spine: int | None = None, owned_end_spine: int | None = None) -> ConversionResult`
  - Every produced `Block` must carry absolute `spine_index` in provenance location (field name to be chosen and documented in Decision Log).
- `cookimport/cli.py`
  - New CLI flags: `--epub-spine-items-per-job`, `--epub-spine-overlap-items`.
  - Job planner must create an “epub spine slice” job kind when conditions are met.
  - Merge orchestration must recognize EPUB split jobs and write one workbook output in the main process.
- `cookimport/cli_worker.py`
  - Worker entrypoint must accept EPUB slice jobs and return a mergeable job payload while writing raw artifacts into `.job_parts` for those jobs.
- Tests
  - At least one new test file covering EPUB job planning and merge ID rewriting.

Change note: 2026-02-01 — Initial ExecPlan created to extend the existing PDF split/merge job framework to `.epub` spine slicing with overlap filtering and deterministic merging.
```

## docs/resource_usage_report.md

```markdown
# Resource Usage and Performance Report: cookimport

This report provides an analysis of how `cookimport` utilizes system resources and outlines strategies for increasing its share of available compute to accelerate processing.

## 1. Current Resource Usage Profile

### CPU (Central Processing Unit)
*   **Status**: Underutilized (Single-threaded).
*   **Behavior**: The program currently processes files sequentially in a single loop within `cookimport/cli.py`. This means only one CPU core is primarily active at any given time.
*   **Load Type**: High-intensity "burst" loads occur during text extraction (OCR) and NLP parsing (ingredient/instruction analysis). The CPU is responsible for coordinating model execution and managing data structures.

### RAM (Random Access Memory)
*   **Status**: Moderate to High.
*   **Behavior**: Loading deep learning models for OCR (`docTR`) and NLP (`spacy`, `ingredient-parser-nlp`) requires significant memory overhead (typically 1GB–4GB+ depending on the models).
*   **Peak Load**: Memory usage peaks when large PDF files are converted to images for OCR processing.

### GPU (Graphics Processing Unit)
*   **Status**: Potentially utilized but unmanaged.
*   **Behavior**: `docTR` uses PyTorch as a backend. If a CUDA-enabled (NVIDIA) or MPS-enabled (Apple Silicon) GPU is present, PyTorch may use it for OCR detection and recognition, but the codebase does not explicitly configure or optimize this device allocation.

### Disk I/O
*   **Status**: Low.
*   **Behavior**: Reading source files (PDF, EPUB, Excel) and writing JSON-LD drafts is generally fast and not a bottleneck compared to the compute-heavy parsing stages.

---

## 2. Strategies for Increasing Compute Share

To allow `cookimport` to process recipes significantly faster, the following architectural changes are recommended:

### A. Parallel File Processing (Multiprocessing)
The most effective way to utilize a modern multi-core CPU is to process multiple files simultaneously.
*   **Implementation**: Replace the sequential `for` loop in `cookimport/cli.py:stage()` with a `concurrent.futures.ProcessPoolExecutor`.
*   **Benefit**: On an 8-core machine, processing 4–8 files in parallel could theoretically result in a 3x–6x speedup for bulk imports.
*   **Note**: This will multiply RAM usage, so the number of workers should be tuned to the available memory.

### B. Explicit GPU Acceleration
Explicitly directing the OCR engine to use the GPU will offload the heaviest computations from the CPU.
*   **Implementation**: Modify `cookimport/ocr/doctr_engine.py` to detect and pass the `device` (e.g., `cuda` or `mps`) to the `ocr_predictor`.
*   **Benefit**: GPU-accelerated OCR is often 10x–50x faster than CPU-based OCR.

### C. Batch OCR Processing
`docTR` is designed to handle batches of images efficiently.
*   **Implementation**: Instead of processing one page at a time, group pages into batches (e.g., 8 pages) and pass them to the model in a single call.
*   **Benefit**: Reduces the overhead of transferring data between the CPU and GPU/RAM.

### D. Model Warming and Caching
Currently, models are lazy-loaded on the first call.
*   **Implementation**: For high-performance runs, "warm" the models by loading them during application startup or keeping them resident in a separate worker process.
*   **Benefit**: Eliminates the 5–10 second delay encountered the first time a file is processed in a session.

---

## 3. Recommended Configuration for High-Performance Hardware
If you have a high-end workstation, the ideal configuration for this tool would be:
1.  **Workers**: Set a concurrency limit equal to `Total RAM / 3GB`.
2.  **Backend**: Ensure `torch` is installed with proper hardware acceleration support (CUDA for PC, MPS for Mac).
3.  **IO**: Run from an SSD to minimize latency when reading large PDF/EPUB sources.
```

## docs/step-linking/README.md

```markdown
---
summary: "Two-phase algorithm for linking ingredients to instruction steps."
read_when:
  - Working on step-ingredient assignment
  - Debugging ingredient duplication issues
  - Understanding split ingredient handling
---

# Step-Ingredient Linking

**Location:** `cookimport/parsing/step_ingredients.py`

This module assigns each ingredient to the instruction step(s) where it's used.

## Algorithm Overview

The **two-phase algorithm** solves the ingredient-step linking problem:

### Phase 1: Candidate Collection

For each (ingredient, step) pair:
1. Generate **aliases** for the ingredient (full text, cleaned text, head/tail tokens)
2. Scan step text for alias matches
3. Classify **verb context** around the match
4. Score the candidate based on match quality

### Phase 2: Global Resolution

For each ingredient:
1. Collect all step candidates
2. Apply assignment rules (usually: best step wins)
3. Handle exceptions (split ingredients, section groups)

---

## Alias Generation

Each ingredient generates multiple searchable aliases:

```python
"fresh sage leaves, chopped" →
  - ("fresh", "sage", "leaves", "chopped")  # full text
  - ("sage", "leaves")                       # cleaned (no prep)
  - ("sage",)                                # head token
  - ("leaves",)                              # tail token
```

Aliases are scored by:
1. Token count (more tokens = stronger match)
2. Character length
3. Source preference (raw_ingredient_text > raw_text)

### Semantic Fallback (Lemmatized)

If an ingredient has **no exact alias match**, a lightweight lemmatized fallback runs:

- Rule-based lemmatization (suffix stripping + small overrides)
- No external dependencies
- Curated synonym expansion for common ingredient names
- Tagged as `match_kind="semantic"` and only used when exact matches are absent
  - Note: "exact match" includes head/tail single-token aliases

If the ingredient is still unmatched, a **fuzzy** rescue runs:

- RapidFuzz partial ratio over lemmatized text
- Only for unmatched ingredients, with generic-token guardrails
- Tagged as `match_kind="fuzzy"`

---

## Verb Context Classification

The 1-3 tokens before an ingredient match reveal usage intent:

| Verb Type | Words | Score Adjustment |
|-----------|-------|------------------|
| **use** | add, mix, stir, fold, pour, whisk, combine, toss, season, drizzle, melt | +10 |
| **reference** | cook, let, rest, simmer, reduce, return | -5 |
| **split** | half, remaining, reserved, divided | +8 (enables multi-step when strong) |
| **neutral** | (other) | 0 |

### Split Detection

Split signals trigger multi-step assignment when they include strong language (explicit fractions like "half" or remaining/reserved terms):

```
Step 3: "Add half the butter and stir."
Step 7: "Add remaining butter and serve."
```

Both steps get the butter ingredient, with quantity fractions:
- Step 3: `input_qty * 0.5`
- Step 7: `input_qty * 0.5`

---

## Assignment Rules

### Default: Best Step Wins

Each ingredient goes to exactly one step (highest-scoring candidate).

**Tiebreaker:** When multiple steps have "use" verbs, prefer the **earliest step** (first introduction of ingredient).

### Exception: Multi-Step Assignment

Enabled only when:
1. Multiple candidates have "use" or "split" signals
2. At least one candidate has strong split language (fraction/remaining/reserved)

Maximum 3 steps per ingredient (prevents runaway assignments).

When a multi-step split is used, each split ingredient line has its confidence reduced slightly to flag it for later review.

### Exception: Section Header Groups

Ingredients under a section header (e.g., "For the Sauce") are grouped:

```
For the Sauce:
  2 tbsp butter
  1 cup cream

Step: "Make the sauce by combining sauce ingredients..."
```

The phrase "sauce ingredients" matches the section, assigning all grouped ingredients.

### Exception: "All Ingredients" Phrases

Patterns like "combine all ingredients" assign every non-header ingredient to that step.

---

## Weak Match Filtering

Single-token matches (e.g., "oil") are **weak** and can cause false positives.

Filtering rule: If a weak match's token appears in a strong match in the same step, exclude the weak match.

Example:
- "olive oil" (strong match, 2 tokens)
- "oil" (weak match, 1 token)

If both match step 3, only "olive oil" is assigned (weak "oil" excluded).

---

## Debugging

Enable debug mode to trace assignments:

```python
results, debug_info = assign_ingredient_lines_to_steps(
    steps, ingredients, debug=True
)

# debug_info contains:
#   .candidates - all detected matches with scores
#   .assignments - final assignment decisions with reasons
#   .group_assignments - section header group matches
#   .all_ingredients_steps - steps with "all ingredients" phrase
```

---

## Key Discoveries

### Duplication Bug Fix (2026-01-30)

**Problem:** Ingredients appearing in multiple steps when only one assignment was intended.

**Root cause:** Greedy per-step matching without global resolution.

**Solution:** Two-phase algorithm with "earliest use verb wins" tiebreaker.

### Fraction Calculation

For split ingredients:
- "half" → 0.5
- "quarter" → 0.25
- "third" → 0.333
- "remaining" → complement of previously assigned fractions
```

## docs/template/AGENTS.md

```markdown
---
summary: "Explanation of the final DraftV1 recipe schema used by the application."
read_when:
  - When modifying the DraftV1 schema
  - When investigating how ingredients are linked to steps
---

this is the final output, this is what the cookbook app uses: 
  
  The schema includes:                                                                       
  - All fields with types and descriptions                                                   
  - Conditional validation for quantity_kind (exact requires qty+unit, approximate allows   
  both or neither, unquantified forbids them)                                                
  - UUID pattern validation                                                                  
  - minLength, minimum, and default constraints matching the Zod schema 


  Pancakes.JSON is an example of a real recipe in my database, note how the ingridients are tied to a specific recipe step.```

## docs/template/Pancakes.JSON

```json
    1 {
    2   "schema_v": 1,
    3   "recipe": {
    4     "title": "Pancakes",
    5     "description": "Quick stovetop pancakes with simple pantry staples.",
    6     "yield_units": 4,
    7     "yield_phrase": "4 servings",
    8     "yield_unit_name": "servings",
    9     "yield_detail": "About 8 small pancakes",
   10     "notes": "Rest batter for 5 minutes if you have time."
   11   },
   12   "steps": [
   13     {
   14       "instruction": "Whisk together dry ingredients.",
   15       "ingredient_lines": [
   16         {
   17           "ingredient_id": "00000000-0000-0000-0000-000000000020",
   18           "quantity_kind": "exact",
   19           "input_qty": 200,
   20           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   21           "note": null,
   22           "raw_text": "200 g flour",
   23           "is_optional": false
   24         },
   25         {
   26           "ingredient_id": "00000000-0000-0000-0000-000000000021",
   27           "quantity_kind": "exact",
   28           "input_qty": 25,
   29           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   30           "note": null,
   31           "raw_text": "25 g sugar",
   32           "is_optional": false
   33         },
   34         {
   35           "ingredient_id": "00000000-0000-0000-0000-000000000022",
   36           "quantity_kind": "exact",
   37           "input_qty": 1,
   38           "input_unit_id": "00000000-0000-0000-0000-000000000011",
   39           "note": null,
   40           "raw_text": "1 tsp salt",
   41           "is_optional": false
   42         }
   43       ]
   44     },
   45     {
   46       "instruction": "Whisk wet ingredients and combine with dry.",
   47       "ingredient_lines": [
   48         {
   49           "ingredient_id": "00000000-0000-0000-0000-000000000024",
   50           "quantity_kind": "exact",
   51           "input_qty": 300,
   52           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   53           "note": null,
   54           "raw_text": "300 g milk",
   55           "is_optional": false
   56         },
   57         {
   58           "ingredient_id": "00000000-0000-0000-0000-000000000025",
   59           "quantity_kind": "exact",
   60           "input_qty": 50,
   61           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   62           "note": null,
   63           "raw_text": "50 g egg",
   64           "is_optional": false
   65         },
   66         {
   67           "ingredient_id": "00000000-0000-0000-0000-000000000023",
   68           "quantity_kind": "exact",
   69           "input_qty": 30,
   70           "input_unit_id": "00000000-0000-0000-0000-000000000010",
   71           "note": null,
   72           "raw_text": "30 g butter",
   73           "is_optional": false
   74         }
   75       ]
   76     }
   77   ]
   78 }```

## docs/template/examples/Broccoli Cheese Soup1.paprikarecipes

_Binary file; base64-encoded below._

```base64
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
```

## docs/template/examples/PaprikaApp Broccoli Cheese Soup.html

```html
﻿<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <style type="text/css">
            /* Shared styles */
            body {
                font-family: Helvetica, sans-serif;
                font-size: 16px;
                color: #34302e;
                margin: 0.25in;
            }
            @page {
                size: letter portrait;
                margin: 0.25in;
            }
            .name {
                font-size: 18px;
                font-family: Helvetica, sans-serif;
                font-weight: normal;
                margin: 0 0 10px 0;
            }
            .categories {
                color: #605D5D;
                font-size: 14px;
                font-family: Helvetica, sans-serif;
                font-style: italic;
            }
            .rating {
                color: #d10505;
                font-size: 14px;
            }
            .metadata {
                font-size: 14px;
            }
            .infobox p {
                margin: 0;
                line-height: 150%;
            }
            .subhead {
                color: #d10505;
                font-weight: bold;
                font-size: 14px;
                text-transform: uppercase;
                margin: 10px 0;
            }
            
            .ingredients p {
                margin: 4px 0;
            }
            /* To prevent nutrition/directions from getting too close
               to ingredients */
            .ingredients {
                padding-bottom: 10px;
            }
            .clear {
                clear:both;
            }
            a {
                color: #4990E2;
                text-decoration: none;
            }
            /* Full page specific styles */
            .text {
                line-height: 130%;
            }
            .photobox {
                float: left;
                margin-right: 14px;
                            }
            .photo {
                max-width: 140px;
                max-height: 140px;
                width: auto;
                height: auto;
            }
            .inline-image {
                max-width: 25%;
                max-height: 25%;
                width: auto;
                height: auto;
            }
            .photoswipe {
                border: 1px #dddddd solid;
                cursor: pointer;
            }
            .pswp__caption__center {
                text-align: center !important;
            }
            .recipe {
                page-break-after: always;
                            }
            .recipe:first-child {
                border-top: 0 none;
                margin-top: 0;
                padding-top: 0;
            }
        </style>
    </head>
    <body>
        <!-- Recipe -->
<div class="recipe" itemscope itemtype="http://schema.org/Recipe" >
    
    <div class="infobox">

        <!-- Image -->
        <div class="photobox">
            <a href="https://www.seriouseats.com/thmb/heRHM4n3T5_xv0IeMwmRMq6299E=/1500x0/filters:no_upscale():max_bytes(150000):strip_icc()/__opt__aboutcom__coeus__resources__content_migration__serious_eats__seriouseats.com__recipes__images__2016__10__20161008-broccoli-cheddar-soup-25-b56f6ad728a54810a26314a64f320f80.jpg">
                <img src="Images/DA870225-2DB1-47DF-8714-744C1DFCE8AD/60DB5461-B117-4DAF-8821-DD59AF80D2A7.jpg" itemprop="image" class="photo photoswipe"/>
            </a>
                    </div>

        <!-- Name -->
        <h1 itemprop="name" class="name">Broccoli Cheese Soup</h1>
        
        <!-- Info -->
        
        <!-- Rating, categories -->
        <p itemprop="aggregateRating" class="rating" value="0"></p>
        
        <p class="metadata">
        
            <!-- Cook time, prep time, servings, difficulty -->
            <b>Prep Time: </b><span itemprop="">5 mins</span>
            <b>Cook Time: </b><span itemprop="">50 mins</span>
            <b>Servings: </b><span itemprop="">6 servings</span>

            <!-- Source -->
                <b>Source: </b>
                    <a itemprop="url" href="https://www.seriouseats.com/broccoli-cheddar-cheese-soup-food-lab-recipe">
                        <span itemprop="author">Seriouseats.com</span>
                    </a>
                            
        </p>
        
        <div class="clear"></div>

    </div>
    
    <div class="left-column">

        <!-- Ingredients -->
        <div class="ingredientsbox">
            <h3 class="subhead">Ingredients</h3>
            <div class="ingredients text">
                <p class="line" itemprop="recipeIngredient"><strong>1 1/2</strong> pounds (700g) broccoli</p><p class="line" itemprop="recipeIngredient"><strong>2</strong> tablespoons (30ml) vegetable oil</p><p class="line" itemprop="recipeIngredient">Kosher salt and freshly ground black pepper</p><p class="line" itemprop="recipeIngredient"><strong>3</strong> tablespoons (45g) unsalted butter</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> medium onion, sliced (about 6 ounces; 170g)</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> medium carrot, peeled and finely diced (about 4 ounces; 120g)</p><p class="line" itemprop="recipeIngredient"><strong>3</strong> medium cloves garlic, thinly sliced</p><p class="line" itemprop="recipeIngredient"><strong>2</strong> cups (475ml) water, or homemade or store-bought low-sodium chicken stock</p><p class="line" itemprop="recipeIngredient"><strong>3</strong> cups (700ml) whole milk</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> small russet potato, peeled and sliced (about 4 ounces; 120g)</p><p class="line" itemprop="recipeIngredient"><strong>12</strong> ounces (340g) sharp cheddar cheese, grated (see notes)</p><p class="line" itemprop="recipeIngredient"><strong>8</strong> ounces (240g) deli-style American cheese, diced (see notes)</p><p class="line" itemprop="recipeIngredient"><strong>1</strong> teaspoon (3g) mustard powder</p><p class="line" itemprop="recipeIngredient">Dash of hot sauce, such as Frank&apos;s RedHot</p>
            </div>
        </div>
        
        <!-- Nutrition (in two-column mode it goes below the ingredients) -->

    </div>
    
    <div class="right-column">
    
    <!-- Description -->

    <!-- Directions -->
    <div class="directionsbox">
        <h3 class="subhead">Directions</h3>
        <div itemprop="recipeInstructions" class="directions text">
            <p class="line">Separate broccoli into florets and stems. Cut florets into bite-size pieces and set aside. Roughly chop stems and reserve separately.</p><p class="line">Heat oil in a large Dutch oven over high heat until shimmering. Add broccoli florets and cook, without moving, until charred on the bottom, about 1 minute. Stir, season with salt and pepper, and continue cooking, stirring occasionally, until tender and charred on several surfaces, about 1 minute longer. Transfer to a rimmed baking sheet to cool.</p><p class="line">Return Dutch oven to medium heat and add butter, onion, carrot, and broccoli stems. Season with salt and pepper and cook, stirring frequently, until tender but not browned, about 5 minutes, lowering heat if necessary. Add garlic and cook, stirring, until fragrant, about 30 seconds.</p><p class="line">Add water or chicken stock, milk, and potato and bring to a boil over high heat. Reduce to a bare simmer and cook, stirring occasionally, until broccoli and potato are completely tender, about 30 minutes.</p><p class="line">In a large bowl, toss both cheeses together along with mustard powder. Using an immersion blender or working in batches with a countertop blender, blend soup, adding cheese a handful at a time, until completely smooth. Stir in hot sauce and season to taste with salt and pepper. Stir in reserved broccoli florets and pulse with blender a few more times until a few pieces are broken down, but most bite-size pieces remain. Serve immediately.</p>
        </div>
    </div>

    <!-- Notes -->


    <!-- Nutrition (in regular mode it goes below the notes) -->
        <!-- Used in two different places depending on the recipe layout -->
<div class="nutritionbox textbox">
    <h3 class="subhead">Nutrition</h3>
    <div itemprop="nutrition" class="nutrition text">
        <p>(per serving)<br/>615 Calories 44g Fat 29g Carbs 30g Protein<br/>Nutrition Facts<br/>Servings: 6<br/>Amount per serving<br/>Calories 615<br/>% Daily Value*<br/>Total Fat 44g 56%<br/>Saturated Fat 23g 114%<br/>Cholesterol 115mg 38%<br/>Sodium 1509mg 66%<br/>Total Carbohydrate 29g 10%<br/>Dietary Fiber 5g 19%<br/>Total Sugars 13g<br/>Protein 30g<br/>Vitamin C 81mg 403%<br/>Calcium 1157mg 89%<br/>Iron 2mg 11%<br/>Potassium 941mg 20%<br/>*The % Daily Value (DV) tells you how much a nutrient in a food serving contributes to a daily diet. 2,000 calories a day is used for general nutrition advice.</p>
    </div>
</div>

    
    </div>
    
    <div class="clear"></div>

</div>



    </body>
</html>
```

## docs/template/examples/recipesage-1767631101507-d892343ecccd93.json

```json
{"recipes":[{"@context":"http://schema.org","@type":"Recipe","identifier":"35b00969-7c88-462a-9aae-89bd277a8a17","datePublished":"2026-01-05T16:37:20.033Z","description":"","image":[],"name":"Slow Cooker Red Beans And Rice Recipe","prepTime":"PT15M","recipeIngredient":["Keep Screen Awake","1 pound dried red beans","3/4 pound smoked turkey sausage, thinly sliced","3  celery ribs, chopped","1  green bell pepper, chopped","1  red bell pepper, chopped","1  sweet onion, chopped","3  garlic cloves, minced","1 tablespoon Creole seasoning","Hot cooked long-grain rice","Hot sauce (optional)","Garnish: finely chopped green onions, finely chopped red onion"],"recipeInstructions":[{"@type":"HowToStep","text":"Combine first 8 ingredients and 7 cups water in a 4-qt. slow cooker. Cover and cook on HIGH 7 hours or until beans are tender."},{"@type":"HowToStep","text":"Serve red bean mixture with hot cooked rice, and, if desired, hot sauce. Garnish, if desired."},{"@type":"HowToStep","text":"Try These Twists!"},{"@type":"HowToStep","text":"Vegetarian Red Beans and Rice: Substitute frozen meatless smoked sausage, thawed and thinly sliced, for turkey sausage."},{"@type":"HowToStep","text":"Per cup (with 1 cup rice): Calories 422; Fat 5g (sat 4g, mono 2g, poly 2g); Protein 5g; Carb 4g; Fiber 2g; Chol 0mg; Iron 1mg; Sodium 530mg; Calc 113mg"},{"@type":"HowToStep","text":"Quick Skillet Red Beans and Rice: Substitute 2 (16-oz.) cans light kidney beans, drained and rinsed, for dried beans. Reduce Creole Seasoning to 2 tsp. Cook sausage and next 4 ingredients in a large nonstick skillet over medium heat, stirring often, 5 minutes or until sausage browns. Add garlic; saute 1 minute. Stir in 2 tsp. seasoning, beans, and 2 cups chicken broth. Bring to a boil; reduce heat to low, and simmer 20 minutes. Serve with hot cooked rice and, if desired, hot sauce. Garnish, if desired. Makes 8 cups. Hands-on Time: 26 min., Total Time: 46 min."}],"recipeYield":"Makes 10","totalTime":"PT7H","recipeCategory":[],"creditText":"","isBasedOn":"https://www.southernliving.com/recipes/slow-cooker-red-beans-rice-1","comment":[{"@type":"Comment","name":"Author Notes","text":""}]}]}```

## docs/template/examples/recipesage-1767633332725-b28c4512684ecf.json

```json
{"recipes":[{"@context":"http://schema.org","@type":"Recipe","identifier":"35b00969-7c88-462a-9aae-89bd277a8a17","datePublished":"2026-01-05T16:37:20.033Z","description":"Description","image":["https://chefbook-prod.s3.us-west-2.amazonaws.com/1767633319831-e68e7427a7bf90"],"name":"Slow Cooker Red Beans And Rice Recipe","prepTime":"PT15M","recipeIngredient":["Keep Screen Awake","1 pound dried red beans","3/4 pound smoked turkey sausage, thinly sliced","3  celery ribs, chopped","1  green bell pepper, chopped","1  red bell pepper, chopped","1  sweet onion, chopped","3  garlic cloves, minced","1 tablespoon Creole seasoning","Hot cooked long-grain rice","Hot sauce (optional)","Garnish: finely chopped green onions, finely chopped red onion"],"recipeInstructions":[{"@type":"HowToStep","text":"Combine first 8 ingredients and 7 cups water in a 4-qt. slow cooker. Cover and cook on HIGH 7 hours or until beans are tender."},{"@type":"HowToStep","text":"Serve red bean mixture with hot cooked rice, and, if desired, hot sauce. Garnish, if desired."},{"@type":"HowToStep","text":"Try These Twists!"},{"@type":"HowToStep","text":"Vegetarian Red Beans and Rice: Substitute frozen meatless smoked sausage, thawed and thinly sliced, for turkey sausage."},{"@type":"HowToStep","text":"Per cup (with 1 cup rice): Calories 422; Fat 5g (sat 4g, mono 2g, poly 2g); Protein 5g; Carb 4g; Fiber 2g; Chol 0mg; Iron 1mg; Sodium 530mg; Calc 113mg"},{"@type":"HowToStep","text":"Quick Skillet Red Beans and Rice: Substitute 2 (16-oz.) cans light kidney beans, drained and rinsed, for dried beans. Reduce Creole Seasoning to 2 tsp. Cook sausage and next 4 ingredients in a large nonstick skillet over medium heat, stirring often, 5 minutes or until sausage browns. Add garlic; saute 1 minute. Stir in 2 tsp. seasoning, beans, and 2 cups chicken broth. Bring to a boil; reduce heat to low, and simmer 20 minutes. Serve with hot cooked rice and, if desired, hot sauce. Garnish, if desired. Makes 8 cups. Hands-on Time: 26 min., Total Time: 46 min."}],"recipeYield":"Makes 10","totalTime":"PT7H","recipeCategory":["label example","label","example"],"creditText":"Source name","isBasedOn":"https://www.southernliving.com/recipes/slow-cooker-red-beans-rice-1","comment":[{"@type":"Comment","name":"Author Notes","text":"notes notes"}],"aggregateRating":{"@type":"AggregateRating","ratingValue":"3","ratingCount":"5"}}]}```

## docs/template/recipeDraftV1.schema.json

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "recipeDraftV1.schema.json",
  "title": "RecipeDraftV1",
  "description": "Schema for importing recipes into the cookbook application. Ingredient and unit IDs must be valid UUIDs that exist in the target database.",
  "type": "object",
  "required": ["schema_v", "recipe", "steps"],
  "additionalProperties": false,
  "properties": {
    "schema_v": {
      "const": 1,
      "description": "Schema version, must be 1"
    },
    "recipe": {
      "$ref": "#/$defs/Recipe"
    },
    "steps": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/Step"
      },
      "description": "Recipe steps in order. Must have at least one step."
    }
  },
  "$defs": {
    "Recipe": {
      "type": "object",
      "required": ["title"],
      "additionalProperties": false,
      "properties": {
        "title": {
          "type": "string",
          "minLength": 1,
          "description": "Recipe title (required, will be trimmed)"
        },
        "description": {
          "type": ["string", "null"],
          "description": "Brief description of the recipe"
        },
        "notes": {
          "type": ["string", "null"],
          "description": "Additional notes or tips"
        },
        "yield_units": {
          "type": "number",
          "minimum": 1,
          "default": 1,
          "description": "Number of servings/units the recipe makes (default: 1)"
        },
        "yield_phrase": {
          "type": ["string", "null"],
          "description": "Human-readable yield, e.g. '2 bowls' or '12 cookies'"
        },
        "yield_unit_name": {
          "type": ["string", "null"],
          "description": "Singular unit name, e.g. 'bowl' or 'cookie'"
        },
        "yield_detail": {
          "type": ["string", "null"],
          "description": "Additional yield details, e.g. 'Two generous bowls'"
        },
        "variants": {
          "type": ["array", "null"],
          "items": {
            "type": "string",
            "minLength": 1
          },
          "description": "Variant or variation notes extracted from the source"
        },
        "confidence": {
          "type": ["number", "null"],
          "minimum": 0,
          "maximum": 1,
          "description": "Confidence score of the recipe extraction (0.0 to 1.0)"
        }
      }
    },
    "Step": {
      "type": "object",
      "required": ["instruction", "ingredient_lines"],
      "additionalProperties": false,
      "properties": {
        "instruction": {
          "type": "string",
          "minLength": 1,
          "description": "Step instruction text (required, will be trimmed)"
        },
        "ingredient_lines": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/IngredientLine"
          },
          "description": "Ingredients used in this step"
        }
      }
    },
    "IngredientLine": {
      "type": "object",
      "required": ["ingredient_id", "quantity_kind"],
      "additionalProperties": false,
      "properties": {
        "ingredient_id": {
          "$ref": "#/$defs/UUID",
          "description": "UUID of the ingredient (must exist in database)"
        },
        "quantity_kind": {
          "type": "string",
          "enum": ["exact", "approximate", "unquantified"],
          "description": "Type of quantity: 'exact' for precise measurements, 'approximate' for cue-based or rough measurements (e.g., 'to taste', 'for pan'), 'unquantified' for items with no quantity cues"
        },
        "input_qty": {
          "type": ["number", "null"],
          "exclusiveMinimum": 0,
          "description": "Quantity amount. Required for exact, optional for approximate, must be null/omitted for unquantified."
        },
        "input_unit_id": {
          "oneOf": [
            { "$ref": "#/$defs/UUID" },
            { "type": "null" }
          ],
          "description": "UUID of the unit (must exist in database). Required for exact, optional for approximate, must be null/omitted for unquantified."
        },
        "note": {
          "type": ["string", "null"],
          "description": "Additional note, e.g. 'minced' or 'to taste'"
        },
        "raw_text": {
          "type": ["string", "null"],
          "description": "Original text from import source, e.g. '2 tsp minced garlic'"
        },
        "is_optional": {
          "type": "boolean",
          "default": false,
          "description": "Whether this ingredient is optional"
        }
      },
      "allOf": [
        {
          "if": {
            "properties": { "quantity_kind": { "const": "unquantified" } }
          },
          "then": {
            "properties": {
              "input_qty": { "type": "null" },
              "input_unit_id": { "type": "null" }
            }
          }
        },
        {
          "if": {
            "properties": { "quantity_kind": { "const": "exact" } }
          },
          "then": {
            "required": ["input_qty", "input_unit_id"],
            "properties": {
              "input_qty": { "type": "number", "exclusiveMinimum": 0 },
              "input_unit_id": { "$ref": "#/$defs/UUID" }
            }
          }
        }
      ]
    },
    "UUID": {
      "type": "string",
      "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
      "description": "UUID v4 format"
    }
  }
}
```

## docs/template/recipeDraftV1.ts

```ts
import { z } from "zod";

const FORBIDDEN_ORDER_KEYS = new Set(["step_number", "line_order"]);
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UuidSchema = z.string().regex(UUID_REGEX, "Invalid UUID");

type PathSegment = string | number;

const IngredientLineSchema = z
  .object({
    ingredient_id: UuidSchema,
    quantity_kind: z.enum(["exact", "approximate", "unquantified"]),
    input_qty: z.number().positive().optional().nullable(),
    input_unit_id: UuidSchema.optional().nullable(),
    note: z.string().optional().nullable(),
    raw_text: z.string().optional().nullable(),
    is_optional: z.boolean().optional().default(false),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hasQty = value.input_qty !== null && value.input_qty !== undefined;
    const hasUnit =
      value.input_unit_id !== null && value.input_unit_id !== undefined;

    if (value.quantity_kind === "unquantified") {
      if (hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty must be null or omitted for unquantified lines.",
        });
      }
      if (hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message:
            "input_unit_id must be null or omitted for unquantified lines.",
        });
      }
      return;
    }

    if (value.quantity_kind === "exact") {
      if (!hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty is required for exact lines.",
        });
      }

      if (!hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message: "input_unit_id is required for exact lines.",
        });
      }
      return;
    }

    if (value.quantity_kind === "approximate") {
      if (hasQty !== hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: hasQty ? ["input_unit_id"] : ["input_qty"],
          message: "input_qty and input_unit_id must be provided together for approximate lines.",
        });
      }
    }
  });

const StepSchema = z
  .object({
    instruction: z.string().trim().min(1),
    ingredient_lines: z.array(IngredientLineSchema),
  })
  .strict();

const RecipeSchema = z
  .object({
    title: z.string().trim().min(1),
    description: z.string().optional().nullable(),
    notes: z.string().optional().nullable(),
    yield_units: z.number().min(1).optional().default(1),
    yield_phrase: z.string().optional().nullable(),
    yield_unit_name: z.string().optional().nullable(),
    yield_detail: z.string().optional().nullable(),
    variants: z.array(z.string().trim().min(1)).optional().nullable(),
    confidence: z.number().min(0).max(1).optional().nullable(),
  })
  .strict();

export const RecipeDraftV1Schema = z
  .object({
    schema_v: z.literal(1),
    recipe: RecipeSchema,
    steps: z.array(StepSchema).min(1),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hits: { path: PathSegment[]; key: string }[] = [];

    const scan = (current: unknown, path: PathSegment[]) => {
      if (Array.isArray(current)) {
        current.forEach((item, index) => scan(item, [...path, index]));
        return;
      }

      if (current && typeof current === "object") {
        for (const [key, child] of Object.entries(
          current as Record<string, unknown>,
        )) {
          if (FORBIDDEN_ORDER_KEYS.has(key)) {
            hits.push({ path: [...path, key], key });
          }
          scan(child, [...path, key]);
        }
      }
    };

    scan(value, []);

    hits.forEach((hit) => {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: hit.path,
        message: `${hit.key} is server-derived and must not appear in drafts.`,
      });
    });
  });

export type RecipeDraftV1 = z.infer<typeof RecipeDraftV1Schema>;

export function parseRecipeDraftV1(input: unknown): RecipeDraftV1 {
  return RecipeDraftV1Schema.parse(input);
}

export function formatZodError(err: unknown): string {
  if (err instanceof z.ZodError) {
    return err.issues
      .map((issue) => {
        const path = issue.path.length ? issue.path.join(".") : "input";
        return `${path}: ${issue.message}`;
      })
      .join("\n");
  }

  if (err instanceof Error) {
    return err.message;
  }

  return "Unknown validation error.";
}
```

## docs/tips/README.md

```markdown
---
summary: "Tip extraction, classification, taxonomy tagging, and evaluation."
read_when:
  - Working on tip/knowledge extraction
  - Tuning tip precision or recall
  - Building golden sets for tip evaluation
---

# Tip Extraction Pipeline

**Location:** `cookimport/parsing/tips.py`

The tip extraction system identifies standalone kitchen wisdom from cookbook content.

## Tip Classification

Tips are classified by scope:

| Scope | Description | Example |
|-------|-------------|---------|
| `general` | Reusable kitchen wisdom | "Toast spices in a dry pan to release oils." |
| `recipe_specific` | Notes tied to one recipe | "This soup freezes well for up to 3 months." |
| `not_tip` | False positive | Copyright notices, ads, narrative prose |

---

## Extraction Strategy

### From Recipes

Tips extracted from recipe content:
1. Scan description, notes, and instruction comments
2. Look for tip markers (see Advice Anchors below)
3. Classify scope based on generality signals

### From Standalone Blocks

Content not assigned to recipes:
1. Chunk into containers (by section headers)
2. Split containers into atoms (individual sentences/points)
3. Apply tip detection heuristics
4. Generate topic candidates for non-tip content

---

## Detection Heuristics

### Advice Anchors (Required)

Tips must contain explicit advice language:

**Modal verbs:** can, should, must, need to, ought to, have to
**Imperatives:** use, try, avoid, choose, store, keep, serve, add, make sure
**Conditionals:** if you, when you, for best results

### Cooking Anchors (Gate)

At least one cooking-related term must be present:
- Techniques: sauté, roast, simmer, marinate
- Equipment: pan, oven, pot, knife
- Ingredients: butter, salt, garlic, onion
- Outcomes: crispy, tender, golden, caramelized

### Narrative Rejection

Reject tip-like content that's actually narrative:
- Story-telling patterns ("I remember when...", "My grandmother used to...")
- Long flowing paragraphs without actionable advice
- Historical or biographical content

---

## Taxonomy Tagging

Tips are tagged with relevant anchors (`TipTags` model):

| Category | Examples |
|----------|----------|
| `recipes` | Recipe names mentioned |
| `dishes` | pasta, soup, salad, stew |
| `meats` | chicken, beef, pork, fish |
| `vegetables` | onion, garlic, tomato, carrot |
| `herbs` | basil, thyme, rosemary, cilantro |
| `spices` | cumin, paprika, cinnamon, pepper |
| `dairy` | butter, cream, cheese, milk |
| `grains` | rice, bread, flour, pasta |
| `techniques` | sauté, roast, braise, poach |
| `cooking_methods` | baking, grilling, frying, steaming |
| `tools` | pan, oven, knife, blender |

---

## Atom Chunking

**Location:** `cookimport/parsing/atoms.py`

Large blocks are split into atomic units for better precision:

```
Container: "COOKING TIPS" section
  └─ Atom 1: "Toast whole spices before grinding."
  └─ Atom 2: "Store herbs wrapped in damp paper towels."
  └─ Atom 3: "Let meat rest before slicing."
```

Each atom includes context:
- `context_prev`: Previous atom text (for context)
- `context_next`: Next atom text (for context)
- `container_header`: Section header if present

---

## Topic Candidates

Content that doesn't qualify as tips but may be valuable:
- Ingredient guides ("All About Olive Oil")
- Technique explanations ("How to Julienne Vegetables")
- Equipment recommendations ("Choosing the Right Pan")

Topic candidates are stored separately for potential future use.

---

## Tuning Guide

### Precision vs Recall

**To increase precision** (fewer false positives):
- Tighten advice anchor requirements
- Add more narrative rejection patterns
- Require more cooking anchors

**To increase recall** (catch more tips):
- Add advice anchor words
- Relax cooking anchor requirements
- Reduce minimum generality score

### Key Knobs

Located in `cookimport/parsing/tips.py`:

1. **Advice anchor patterns** - Regex patterns for tip-like language
2. **Cooking anchor terms** - Required domain vocabulary
3. **Narrative rejection patterns** - Story-telling indicators
4. **Generality threshold** - Score cutoff for general vs recipe-specific

### Override Support

Per-cookbook overrides via `ParsingOverrides`:
- `tip_headers`: Additional section headers to treat as tip containers
- `tip_prefixes`: Line prefixes that indicate tips ("TIP:", "NOTE:")

---

## Evaluation Harness

**Location:** `docs/tips/` (this doc) + Label Studio integration

### Building Golden Sets

1. Run tip extraction on test cookbook
2. Export tip candidates to Label Studio
3. Annotate: correct scope, correct/incorrect extraction
4. Export labeled data as golden set JSONL

### Scoring

```bash
# Run evaluation against golden set
python -m cookimport.evaluation.tips --golden golden_tips.jsonl --predicted predicted_tips.jsonl
```

Metrics:
- **Precision**: % of extracted tips that are correct
- **Recall**: % of actual tips that were extracted
- **Scope accuracy**: % of tips with correct scope classification

### A/B Testing Workflow

1. Establish baseline metrics on golden set
2. Modify heuristics
3. Re-run extraction
4. Compare metrics
5. Keep changes only if metrics improve
```

## docs/understandings/2026-01-31-step-ingredient-splitting.md

```markdown
---
summary: "Notes on step-ingredient assignment, split gating, and confidence penalties."
read_when:
  - When adjusting step-ingredient matching or split behavior
---

Step-ingredient linking (`cookimport/parsing/step_ingredients.py`) uses a two-phase match: candidate collection per step via alias matching, then a global resolution that assigns each ingredient to a single best step unless a strong split signal (fraction/remaining/reserved) appears in multiple steps. Multi-step assignments now apply a small confidence penalty on the split ingredient lines to flag them for review.
```

## docs/understandings/2026-02-02-epub-job-splitting.md

```markdown
---
summary: "Notes on EPUB job splitting and spine-index ordering for merges."
read_when:
  - When modifying EPUB job splitting or merge ordering
---

# EPUB Job Splitting Notes (2026-02-02)

- EPUB blocks are emitted as a linear list with `start_block`/`end_block` provenance indices, so split jobs need a stable global ordering key.
- Each spine item is processed with a `spine_index` feature on blocks, and recipe provenance records `start_spine`/`end_spine` so merge ordering can sort by spine index before local block indices.
- Split jobs write raw artifacts into `.job_parts/<workbook>/job_<index>/raw/`, then the main merge step moves them into `raw/` and rewrites recipe IDs to a single global sequence.
```

## docs/understandings/2026-02-02-pdf-job-merge-and-fallback.md

```markdown
---
summary: "Notes on PDF job merge ordering, ID rewrites, and serial fallback behavior."
read_when:
  - When modifying PDF job merging or troubleshooting job-split staging runs
---

# PDF Job Merge and Fallback Notes (2026-02-02)

- Split PDF jobs return `ConversionResult` payloads without raw artifacts; the main process merges recipes, tip candidates, topic candidates, and non-recipe blocks, then recomputes tips and chunks before writing outputs.
- Recipe IDs are rewritten to a global `c0..cN` sequence ordered by `provenance.location.start_page` (falling back to `start_block`), and any tip `sourceRecipeId` references are updated via the same mapping.
- Raw artifacts are written under `.job_parts/<workbook_slug>/job_<index>/raw/` during job execution, then moved into `raw/` with filename prefixing on collisions once the merge completes.
- If `ProcessPoolExecutor` fails to initialize (PermissionError), staging falls back to serial job execution so CLI/test runs can still complete.
```

## docs/understandings/2026-02-02-stage-worker-pdf-job-surface.md

```markdown
---
summary: "Notes on current stage->worker flow and PDF conversion surfaces relevant to job splitting."
read_when:
  - When adding job-level parallelism or page-range processing for PDF ingestion
---

# Stage/Worker/PDF Surfaces (2026-02-02)

- `cookimport/cli.py` `stage` plans jobs (one per file, or multiple page-range jobs for large PDFs), spins a `ProcessPoolExecutor`, and calls either `cookimport/cli_worker.py:stage_one_file` (non-split) or `cookimport/cli_worker.py:stage_pdf_job` (split). Progress updates come through a `multiprocessing.Manager().Queue()` and are rendered in the Live dashboard with page-range labels.
- `stage_one_file` in `cookimport/cli_worker.py` resolves the importer, runs `importer.inspect` if no mapping, then `importer.convert`, applies optional limits, builds knowledge chunks, enriches the report, and writes outputs via `cookimport/staging/writer.py`.
- `stage_pdf_job` runs a page-range conversion, writes raw artifacts into a `.job_parts/<workbook_slug>/job_<index>/raw/` temp folder, and returns a mergeable `ConversionResult` payload to the main process.
- `cookimport/plugins/pdf.py:PdfImporter.convert` can now process a page range (OCR or text extraction) and initially assigns recipe IDs as `urn:recipeimport:pdf:{file_hash}:c{i}` before the merge step rewrites them to a global sequence.
- `cookimport/ocr/doctr_engine.py:ocr_pdf` accepts `start_page` and `end_page` (exclusive), and returns absolute page numbers (1-based) for OCR blocks.
```

## docs/understandings/2026-02-02-worker-progress-dashboard.md

```markdown
---
summary: "Notes on worker progress reporting and split-job scheduling in the stage CLI."
read_when:
  - When adjusting the CLI worker dashboard or progress updates
  - When debugging stalled progress during split EPUB/PDF jobs
---

The stage CLI builds a list of `JobSpec` entries, splitting large EPUB/PDF inputs into spine/page-range jobs when configured. Each job runs in a ProcessPool worker (`stage_epub_job`, `stage_pdf_job`, or `stage_one_file`) and reports progress through a `multiprocessing.Manager().Queue()` to the live dashboard. The dashboard only knows what the workers last reported, so stale entries can appear if no updates arrive. After all split jobs for a file finish, the main process merges results; the progress bar tracks job completion, not merge time.
```

