---
summary: "ExecPlan for Priority 7: deterministic schema-first ingestion for local HTML/JSON recipe files with heuristic fallback."
read_when:
  - "When adding a dedicated HTML/JSON schema-first importer"
  - "When wiring web-schema run settings through stage and benchmark paths"
  - "When validating importer selection and fallback behavior for .html/.htm/.jsonld/.json"
---

# Build Priority 7: Deterministic Schema-First Local HTML/JSON Ingestion


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


After this change, `cookimport stage` can ingest local web-origin recipe files (`.html`, `.htm`, `.jsonld`, and schema-like `.json`) through a dedicated schema-first importer.

User-visible behavior:

1. Schema-rich inputs produce `RecipeCandidate` records from structured data first.
2. Schema-poor HTML inputs still attempt deterministic fallback extraction from visible text.
3. Reports clearly state when schema was used versus fallback and which extraction backend ran.
4. No AI/LLM parsing is introduced. Recipe codex-farm parsing remains policy-locked off.

You can verify the feature by staging local fixture files and confirming `importerName` is `webschema` in the report JSON, then checking raw artifacts under `raw/webschema/<source_hash>/...`.


## Progress


- [x] (2026-02-27_22.26.32) Ran docs discovery (`npm run docs:list`) and reviewed required docs (`docs/AGENTS.md`, `docs/PLANS.md`, `docs/03-ingestion/03-ingestion_readme.md`, `docs/02-cli/02-cli_README.md`).
- [x] (2026-02-27_22.26.32) Audited current code surfaces for importer registration, detection, run settings, CLI wiring, and benchmark variant dimensions.
- [x] (2026-02-27_22.26.32) Rebuilt `docs/plans/priority-7.md` so it matches current code contracts (no stale `--pipeline WEBSCHEMA` flow, no missing-source citations, and explicit current gaps).
- [x] (2026-02-27_22.52.17) Milestones 0-2: added deterministic fixtures/tests and implemented `schemaorg_ingest`, `html_schema_extract`, `html_text_extract`, and shared `text_section_extract` module.
- [x] (2026-02-27_22.52.17) Milestones 3-4: implemented `webschema` importer, wired registry imports (`cli` + `cli_worker`), added webschema run settings, stage/benchmark CLI flags, adapters, and bounded all-method variant expansion.
- [x] (2026-02-27_22.54.14) Milestone 5: added importer/parsing/run-settings/all-method tests, updated ingestion/CLI/bench docs, staged fixture smoke runs, and wrote understanding note `docs/understandings/2026-02-27_22.52.17-priority7-webschema-detection-and-variant-guardrails.md`.


## Surprises & Discoveries


- Observation: Active and archived Priority 7 plans were effectively the same stale draft.
  Evidence: `docs/plans/priority-7.md` and `docs/plans/OGplan/priority-7.md` carried identical old structure and placeholder citation markers.

- Observation: The old plan referenced `BIG PICTURE UPGRADES.md`, which is not present in this repository.
  Evidence: repository search does not contain that file.

- Observation: Stage/import runtime does not support selecting an importer via `--pipeline`.
  Evidence: `cookimport/cli.py:stage(...)` has no importer-selection flag; importer selection is score-based via `registry.best_importer_for_path(...)` in `cookimport/cli_worker.py`.

- Observation: There is currently no dedicated web/html importer and no webschema run-setting fields.
  Evidence: registered importers are `text`, `excel`, `epub`, `pdf`, `paprika`, and `recipesage`; `RunSettings` only contains EPUB/scoring/LLM/table knobs.

- Observation: A narrow schema-like path already exists inside Paprika HTML handling.
  Evidence: `cookimport/plugins/paprika.py` reads embedded JSON-LD from Paprika export HTML and falls back to deterministic DOM extraction.

- Observation: all-method webschema expansion needed `.json` content inspection guardrails, not extension-only logic.
  Evidence: RecipeSage exports are also `.json`; extension-only branching would incorrectly expand webschema policy variants for RecipeSage inputs.

- Observation: Stage smoke runs surface existing worker warning noise for non-RunSettings keys in run config.
  Evidence: `stage` logs “Ignoring unknown stage run config keys: epub_extractor_effective, epub_extractor_requested, write_markdown” from `RunSettings.from_dict(...)` in worker path.


## Decision Log


- Decision: Keep Priority 7 deterministic and local-file-only.
  Rationale: aligns with project policy (no AI parsing for import) and current ingestion model.
  Date/Author: 2026-02-27_22.26.32 / Codex GPT-5

- Decision: Implement Priority 7 as a new importer plugin (`webschema`) instead of extending existing importers.
  Rationale: keeps detection/reporting/benchmark comparisons explicit and lowers regression risk for existing importer families.
  Date/Author: 2026-02-27_22.26.32 / Codex GPT-5

- Decision: Use `RunSettings` as the canonical knob surface for webschema behavior; do not add new env-var-only controls.
  Rationale: current architecture already passes `run_settings` into every importer convert call, and run-config hash/reporting depend on that path.
  Date/Author: 2026-02-27_22.26.32 / Codex GPT-5

- Decision: Keep `.json` detection conservative to avoid stealing RecipeSage exports.
  Rationale: RecipeSage already claims `.json` when export structure is present; Priority 7 should only claim schema-like JSON that does not match RecipeSage shape.
  Date/Author: 2026-02-27_22.26.32 / Codex GPT-5

- Decision: Treat all-method matrix expansion for webschema as additive and guarded.
  Rationale: current all-method matrix is EPUB-centric; unbounded cross-product growth would inflate runtime and hide signal.
  Date/Author: 2026-02-27_22.26.32 / Codex GPT-5

- Decision: Expand all-method webschema permutations only across `web_schema_policy` for webschema-capable sources.
  Rationale: this gives schema-vs-fallback behavioral comparison without requiring optional extractor dependencies or creating large cross-product runs.
  Date/Author: 2026-02-27_22.52.17 / Codex GPT-5


## Outcomes & Retrospective


Implemented.

Delivered outcome:

- Stage imports local HTML/JSON schema recipes through dedicated `webschema` importer with deterministic schema-first + fallback behavior.
- Reports/raw artifacts now expose webschema knobs and lane evidence (`schema_extracted`, optional `schema_accepted`, optional `fallback_text`).
- RecipeSage `.json` routing remains intact via guarded webschema JSON detection.
- All-method variants stay stable for non-web sources; webschema-capable sources expand only across `web_schema_policy`.
- Targeted tests and two stage smoke runs validated schema lane and fallback lane behavior.


## Context and Orientation


### Current importer runtime

Importer selection is score-based (`cookimport/plugins/registry.py`, `cookimport/cli_worker.py:_run_import`).

Currently registered importers (import side-effect imports in `cookimport/cli.py` and `cookimport/cli_worker.py`):

- `text`: `.txt`, `.md`, `.markdown`, `.docx`
- `excel`: `.xlsx`, `.xlsm`
- `epub`: `.epub`
- `pdf`: `.pdf`
- `paprika`: `.paprikarecipes` and Paprika export directories
- `recipesage`: `.json` with RecipeSage-specific export shape
- `webschema`: `.html`, `.htm`, `.jsonld`, and schema-like `.json` (guarded so RecipeSage exports stay on `recipesage`)

### Current run-settings and CLI surfaces

Canonical run settings are in `cookimport/config/run_settings.py`, propagated via:

- `cookimport/config/run_settings_adapters.py`
- `cookimport/cli.py:stage(...)`
- `cookimport/cli.py:labelstudio_benchmark(...)`
- `cookimport/cli_worker.py` and `cookimport/labelstudio/ingest.py`

Webschema run settings are now present in `RunSettings` and CLI surfaces:

- `web_schema_extractor`
- `web_schema_normalizer`
- `web_html_text_extractor`
- `web_schema_policy`
- `web_schema_min_confidence`
- `web_schema_min_ingredients`
- `web_schema_min_instruction_steps`

### Current benchmark permutations

`cookimport/cli.py:_build_all_method_variants(...)` now expands:

- EPUB extractor dimensions for `.epub` sources (existing behavior),
- webschema policy dimensions for webschema-capable sources (`.html`, `.htm`, `.jsonld`, and schema-like `.json`),
- single variant for other non-EPUB source types.

### Existing relevant building blocks

- `RecipeCandidate` already matches schema.org-like fields (`recipeIngredient`, `recipeInstructions`, `recipeYield`, `prepTime`, `cookTime`, `totalTime`) in `cookimport/core/models.py`.
- Recipe-likeness scoring/gating is already integrated in all importer families via `score_recipe_likeness(...)` and `recipe_gate_action(...)`.
- Text/Excel include deterministic section-header fallback extraction (`_extract_sections_from_blob`) that can be shared or factored.
- Paprika importer already demonstrates local HTML + embedded JSON-LD handling patterns.


## Plan of Work


### Milestone 0: Baseline and guardrails

Capture current behavior before new importer wiring.

Work:

1. Add baseline tests asserting no importer currently claims `.html`/`.jsonld`.
2. Add fixture files for target formats under `tests/fixtures/webschema/`.
3. Record a baseline stage run on an HTML fixture to prove current failure/no-importer behavior.

Acceptance:

- Baseline test evidence is recorded in `Progress`.
- Fixture set exists and is deterministic.

### Milestone 1: Schema ingestion primitives

Implement schema-only parsing/mapping independent of HTML extractor choices.

Work:

1. Add `cookimport/parsing/schemaorg_ingest.py` with deterministic helpers:
   - collect schema recipe objects from nested dict/list/`@graph` payloads,
   - flatten instruction forms (`string`, `HowToStep`, `HowToSection`),
   - compute schema confidence/reasons,
   - map schema recipe object to `RecipeCandidate`.
2. Add duration parser helper with optional `isodate` backend and deterministic fallback.
3. Add unit tests for object collection, instruction flattening, and mapping.

Acceptance:

- Unit tests pass for representative JSON-LD graph and list shapes.
- Mapping outputs valid `RecipeCandidate` objects without importer context.

### Milestone 2: HTML extraction + fallback modules

Implement selectable schema extractors and text extraction fallback.

Work:

1. Add `cookimport/parsing/html_schema_extract.py`:
   - baseline embedded JSON-LD script extraction,
   - optional backends (`extruct`, `scrape-schema-recipe`, `recipe-scrapers`),
   - optional JSON-LD normalization mode (`simple` vs `pyld`),
   - deterministic extractor selection and confidence ranking.
2. Add `cookimport/parsing/html_text_extract.py`:
   - baseline BeautifulSoup text extraction,
   - optional extractor backends (`trafilatura`, `readability-lxml`, `justext`, `boilerpy3`),
   - deterministic text quality scoring for fallback selection.
3. Factor shared section fallback helper from existing text/excel implementation into a reusable parsing helper.

Acceptance:

- Schema extraction and fallback extraction can be exercised directly via unit tests.
- Missing optional dependencies fail with clear install guidance.

### Milestone 3: New importer plugin (`webschema`)

Add the importer and integrate with registry selection.

Work:

1. Add `cookimport/plugins/webschema.py` with:
   - `detect(...)` scoring for `.html/.htm/.jsonld` and guarded `.json`.
   - `inspect(...)` contract-compliant `WorkbookInspection` response.
   - `convert(...)` schema-first flow plus fallback lane and raw artifacts.
2. Register importer in runtime import side-effect paths:
   - `cookimport/cli.py`
   - `cookimport/cli_worker.py`
3. Ensure report fields include extractor policy/counters and recipe-likeness summary integration remains intact.

Acceptance:

- `.html` and `.jsonld` choose `webschema` via `registry.best_importer_for_path(...)`.
- `.json` RecipeSage exports still choose `recipesage`.

### Milestone 4: Run-settings, CLI, adapters, and benchmark wiring

Expose webschema knobs through existing configuration surfaces.

Work:

1. Extend `RunSettings` and `build_run_settings(...)` with additive webschema fields (extractor policy, normalizer choice, fallback extractor choice, thresholds).
2. Add stage and benchmark CLI options that map to the same `RunSettings` fields.
3. Extend `build_stage_call_kwargs_from_run_settings(...)` and `build_benchmark_call_kwargs_from_run_settings(...)`.
4. Add webschema dimensions to all-method variant generation only for applicable source extensions (`.html`, `.htm`, `.jsonld`, schema-like `.json`).

Acceptance:

- New settings appear in run-config hash/summary and report payloads.
- Defaults preserve current behavior for non-webschema inputs.

### Milestone 5: Tests, docs, and acceptance evidence

Finalize with deterministic coverage and documentation updates.

Work:

1. Add ingestion tests for schema lane, fallback lane, and detection conflicts.
2. Add run-settings tests for defaults, UI exposure, hash/summary stability, and adapter propagation.
3. Update docs:
   - `docs/03-ingestion/03-ingestion_readme.md` support matrix and importer details.
   - `docs/02-cli/02-cli_README.md` stage/benchmark option docs.
4. Capture one stage run evidence folder and record paths in this plan.

Acceptance:

- Focused pytest slice passes.
- Docs and plan reflect final behavior.


## Concrete Steps


Run from repository root (`/home/mcnal/projects/recipeimport`) with project virtual environment active.

Executed verification commands:

    source .venv/bin/activate
    pip install -e '.[dev]'

    source .venv/bin/activate
    pytest -q tests/parsing/test_schemaorg_ingest.py tests/ingestion/test_webschema_importer.py tests/llm/test_run_settings.py tests/cli/test_run_settings_adapters.py

    source .venv/bin/activate
    pytest -q tests/labelstudio/test_labelstudio_benchmark_helpers.py -k "build_all_method_variants_epub_expected_count or build_all_method_variants_epub_includes_markdown_when_enabled or build_all_method_variants_non_epub_single_variant or build_all_method_variants_html_webschema_policy_matrix or build_all_method_variants_non_schema_json_single_variant or build_all_method_variants_schema_json_webschema_policy_matrix" tests/ingestion/test_text_importer.py::test_text_blob_section_extraction_keeps_for_component_headers tests/ingestion/test_excel_importer.py::test_excel_blob_section_extraction_keeps_for_component_headers

Smoke stage runs:

    source .venv/bin/activate
    cookimport stage tests/fixtures/webschema/html_with_jsonld.html --out /tmp/p7-smoke-a --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown
    cookimport stage tests/fixtures/webschema/html_without_schema.html --out /tmp/p7-smoke-b --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown

Evidence checks:

    rg -n '"importerName"|"totalRecipes"|"web_schema_policy"|"web_schema_extractor"' /tmp/p7-smoke-a/2026-02-27_22.53.26/html_with_jsonld.excel_import_report.json
    rg -n '"importerName"|"totalRecipes"|"web_schema_policy"|"web_schema_extractor"' /tmp/p7-smoke-b/2026-02-27_22.53.39/html_without_schema.excel_import_report.json
    find /tmp/p7-smoke-a/2026-02-27_22.53.26/raw/webschema -maxdepth 3 -type f | sort
    find /tmp/p7-smoke-b/2026-02-27_22.53.39/raw/webschema -maxdepth 3 -type f | sort


## Validation and Acceptance


Functional acceptance:

1. Schema lane:
   - Input: HTML fixture with valid schema.org Recipe JSON-LD.
   - Expect: report `importerName == "webschema"`, `totalRecipes >= 1`, and schema extraction raw artifact exists.

2. Fallback lane:
   - Input: HTML fixture with no schema but clear ingredient/instruction headers.
   - Expect: report still `importerName == "webschema"`; recipes generated via fallback.

3. Policy behavior:
   - `schema_only` and no schema -> zero recipes with explicit warning/error.
   - `heuristic_only` and schema present -> fallback path used and reported.

4. Conflict behavior:
   - RecipeSage `.json` fixture remains routed to `recipesage` importer.

Automated acceptance:

- `pytest -q` on targeted new tests and touched existing tests.
- Existing ingestion importer tests continue passing.


## Idempotence and Recovery


- All extraction logic must be deterministic and local-only (no HTTP fetches).
- Re-running stage creates a new timestamped output folder; prior runs remain intact.
- Optional backend selection without installed dependency must fail fast with actionable message (extra name and install command).
- Raw artifacts must stay namespaced under `raw/webschema/<source_hash>/...` with stable file names.


## Artifacts and Notes


Planned new/changed files:

- `cookimport/parsing/schemaorg_ingest.py` (new)
- `cookimport/parsing/html_schema_extract.py` (new)
- `cookimport/parsing/html_text_extract.py` (new)
- `cookimport/parsing/text_section_extract.py` (new shared fallback helper)
- `cookimport/plugins/webschema.py` (new)
- `cookimport/cli.py` (stage/benchmark flags and all-method variant wiring)
- `cookimport/cli_worker.py` (import side-effect registration)
- `cookimport/config/run_settings.py` (new webschema fields and summary order)
- `cookimport/config/run_settings_adapters.py` (new kwargs propagation)
- `pyproject.toml` (new `webschema` optional extra)
- `tests/ingestion/test_webschema_importer.py` (new)
- `tests/parsing/test_schemaorg_ingest.py` (new)
- `tests/fixtures/webschema/*` (new)
- `docs/03-ingestion/03-ingestion_readme.md` (update support matrix)
- `docs/02-cli/02-cli_README.md` (update stage/benchmark options)

Expected raw artifacts at runtime:

- `raw/webschema/<source_hash>/schema_extracted.json`
- `raw/webschema/<source_hash>/schema_accepted.json` (optional)
- `raw/webschema/<source_hash>/fallback_text.txt` (when fallback used)
- `raw/webschema/<source_hash>/source.html` (optional debug copy)


## Interfaces and Dependencies


Importer contract (existing):

- `detect(path: Path) -> float`
- `inspect(path: Path) -> WorkbookInspection`
- `convert(path: Path, mapping: MappingConfig | None, progress_callback: Callable[[str], None] | None, run_settings: RunSettings | None) -> ConversionResult`

Planned parsing interfaces:

- `cookimport/parsing/schemaorg_ingest.py`
  - `collect_schemaorg_recipe_objects(data: object) -> list[dict[str, Any]]`
  - `flatten_schema_recipe_instructions(recipe_obj: dict[str, Any]) -> list[str]`
  - `schema_recipe_confidence(...) -> tuple[float, list[str]]`
  - `schema_recipe_to_candidate(...) -> RecipeCandidate`

- `cookimport/parsing/html_schema_extract.py`
  - `extract_schema_recipes_from_html(...) -> list[dict[str, Any]]`

- `cookimport/parsing/html_text_extract.py`
  - `extract_main_text_from_html(...) -> tuple[str, dict[str, Any]]`

Optional dependencies (all selectable, none mandatory for baseline):

- `extruct`
- `scrape-schema-recipe`
- `pyld`
- `recipe-scrapers`
- `trafilatura`
- `readability-lxml`
- `justext`
- `boilerpy3`
- `isodate`


Change note (2026-02-27_22.26.32): Rewrote this plan to reflect actual current runtime contracts and gaps. Removed stale assumptions (missing source file references, nonexistent `--pipeline WEBSCHEMA` flow), added front matter, and aligned milestones with current importer/run-settings architecture.
Change note (2026-02-27_22.54.14): Updated plan sections to completed state after implementation, added concrete evidence commands/paths from executed tests and smoke runs, and documented the final webschema design guardrails.
Change note (2026-02-27_22.56.49): Removed stale context sentence claiming webschema settings were absent so the “Current run-settings and CLI surfaces” section matches the implemented state.
