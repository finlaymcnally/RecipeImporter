# ExecPlan: Priority 7 — Structured-first lane (Schema.org Recipe) for HTML/JSON inputs

This ExecPlan implements **Priority 7** from BIG PICTURE UPGRADES: add a **structured-first “schema lane”** (Schema.org Recipe) for **HTML files saved from the web** and **JSON files containing schema-like Recipe objects**, with a **heuristic fallback** when schema is absent/weak. This is explicitly described as the “inverse mapping” of your existing `RecipeCandidate -> schema.org Recipe JSON-LD` staging converter (`cookimport/staging/jsonld.py`).

It must also incorporate **all tools/libraries mentioned in BIG PICTURE UPGRADES.md that relate to Priority 7**, and each such tool must be implemented as a **new selectable option** (not a replacement), since you benchmark permutations:
- Schema extraction / structured ingestion options: **extruct**, **scrape-schema-recipe**, **pyld**, **recipe-scrapers**
- HTML boilerplate removal / text extraction options (fallback lane): **trafilatura**, **readability-lxml**, optionally **jusText**, **BoilerPy3**
- ISO-8601 Schema.org duration parsing: **isodate**

---

## Purpose / Big Picture

### Why this exists
Your current architecture already supports “two-lane” ingestion in spirit (structured vs heuristic), and has a convergence point (`ConversionResult` + staging writer) that makes adding a new importer lane low-risk.

However, you are explicitly missing a **structured-first lane for web-ish Schema.org Recipe**; your docs state **web scraping isn’t implemented** and HTML recipe support is missing.

Priority 7’s intended logic is:
1) detect Schema.org Recipe objects in HTML/JSON
2) if high confidence, create `RecipeCandidate` directly from schema fields
3) validate via recipe-likeness gates
4) otherwise fallback to heuristic segmentation

This ExecPlan implements exactly that (and keeps every new extraction tool as an option for benchmarking).

### What “done” looks like
- A new importer pipeline (recommended name: `WEBSCHEMA`) is available and/or auto-selected for `.html/.htm/.jsonld` and schema-like `.json`.
- Stage runs produce standard outputs under `data/output/<timestamp>/...`, including `intermediate drafts/...`, `final drafts/...`, and `raw/<importer>/<source_hash>/...` for debugging.
- For HTML with embedded schema recipe(s), the importer creates one or more `RecipeCandidate`s from schema with minimal/no heuristic guessing.
- For HTML without schema, the importer falls back to a deterministic HTML-to-text extraction method (selectable: trafilatura/readability/jusText/BoilerPy3/bs4 baseline) and then deterministic section heuristics (ingredients/instructions) to build `RecipeCandidate`.
- All new third-party tools are implemented behind **configurable strategy enums**, enabling benchmarking permutations.

---

## Progress

- [x] (2026-02-25 America/Toronto) Wrote initial ExecPlan for Priority 7 structured-first lane.
- [ ] Add optional dependency extras for schema/html extraction tools.
- [ ] Add RunSettings + CLI + env-var plumbing for WEBSCHEMA knobs.
- [ ] Implement schema recipe detection + normalization + confidence scoring.
- [ ] Implement schema→RecipeCandidate mapping (inverse of staging/jsonld).
- [ ] Implement HTML schema extraction strategies (builtin JSON-LD, extruct, scrape-schema-recipe, recipe-scrapers; optional pyld normalize).
- [ ] Implement HTML boilerplate removal/text extraction strategies (trafilatura, readability-lxml, jusText, BoilerPy3; baseline bs4).
- [ ] Implement `WEBSCHEMA` importer: detect/inspect/convert, raw artifacts, report fields, fallback lane.
- [ ] Tests + fixtures for schema lane and fallback lane.
- [ ] Update support matrix/docs and (optional) benchmark permutation wiring.

---

## Surprises & Discoveries

- None yet. (Update this section while implementing.)

---

## Decision Log

- (2026-02-25) Implement Priority 7 as a **new importer plugin** (`WEBSCHEMA`) instead of branching Text importer. Rationale: keeps benchmarking clean (distinct pipeline id), avoids regression risk in existing Text importer, and matches existing “Importer families” model (Structured-import-first lane).
- (2026-02-25) Expose every new third-party capability as a **strategy option**, never replacing existing behavior. Rationale: user benchmarks permutations; priority 7 requires multiple tools to coexist.
- (2026-02-25) Provide a `web_schema_policy` knob: `prefer_schema` (default), `schema_only`, `heuristic_only`. Rationale: makes benchmarking and debugging schema-vs-fallback deterministic and reproducible.
- (2026-02-25) Use `isodate` as the default ISO-8601 duration parser when installed; keep a tiny built-in fallback parser (limited) for testability/minimal install. Rationale: BIG PICTURE UPGRADES explicitly recommends isodate for schema durations.

---

## Outcomes & Retrospective

(Leave blank until implementation completes.)

- Intended measurable outcome: +1 supported “web-ish” source class (HTML/JSON-LD), with high precision when schema exists, and deterministic fallback when it doesn’t.
- Intended operational outcome: more raw artifacts for debugging schema extraction and fallback extraction.

---

## Context and Orientation

### Current architecture constraints we must respect
- Importers are selected via **score-based registry** (`best_importer_for_path`) and implement:
  - `detect(path) -> float`
  - `inspect(path) -> WorkbookInspection`
  - `convert(path, mapping, progress_callback) -> ConversionResult`
- All importers converge through `ConversionResult`, and final recipe shaping happens in staging (`cookimport/staging/draft_v1.py`), then writing via `cookimport/staging/writer.py`.
- Existing importer families:
  - Block-first: EPUB/PDF
  - Recipe-record-first: Text/Excel
  - Structured-import-first: Paprika/RecipeSage
- Web scraping is not currently supported; we are not adding network fetching. We ingest **local HTML/JSON files** only.

### Priority 7’s required behavior (source of truth)
BIG PICTURE UPGRADES defines Priority 7 as:
- ingest HTML saved from the web or JSON files with schema-like Recipe objects
- detect schema Recipe objects (JSON-LD/microdata extracted into dicts)
- if confidence high, map schema fields directly (ingredients/instructions/yield/time)
- validate with recipe-likeness gates
- fallback to heuristic segmentation if schema absent/weak

### Tooling we must incorporate as options (source of truth)
If we ingest HTML-ish sources, BIG PICTURE UPGRADES recommends:
- `extruct`, `scrape-schema-recipe`, `pyld`, `recipe-scrapers`
- `trafilatura`, `readability-lxml`, optionally `jusText`, `BoilerPy3`
and recommends `isodate` for Schema.org ISO-8601 durations.

---

## Plan of Work

### Milestone 0 — Wire dependencies + run settings (benchmarkable knobs)

Goal: make every new library available as an *optional dependency* and every new feature as a *selectable run setting*.

Deliverables:
- New extra dependency group(s) in `pyproject.toml` (recommended: `webschema`)
- `RunSettings` updated with WEBSCHEMA knobs
- CLI flags (stage + benchmark flows) updated
- Env-var propagation consistent with existing patterns (EPUB uses `C3IMP_*`)

Proposed new RunSettings fields (names chosen to be stable + explicit):
- `web_schema_extractor: Literal["builtin_jsonld", "extruct", "scrape_schema_recipe", "recipe_scrapers", "ensemble_v1"]`
- `web_jsonld_normalizer: Literal["simple", "pyld"]`
- `web_html_text_extractor: Literal["bs4", "trafilatura", "readability_lxml", "justext", "boilerpy3", "ensemble_v1"]`
- `web_schema_policy: Literal["prefer_schema", "schema_only", "heuristic_only"]`
- `web_schema_min_confidence: float` (default: 0.75)
- (optional) `web_schema_min_ingredients: int` (default: 2)
- (optional) `web_schema_min_instruction_steps: int` (default: 1)

Proposed env vars (mirroring EPUB patterns):
- `C3IMP_WEB_SCHEMA_EXTRACTOR`
- `C3IMP_WEB_JSONLD_NORMALIZER`
- `C3IMP_WEB_HTML_TEXT_EXTRACTOR`
- `C3IMP_WEB_SCHEMA_POLICY`
- `C3IMP_WEB_SCHEMA_MIN_CONFIDENCE`
- `C3IMP_WEB_SCHEMA_MIN_INGREDIENTS`
- `C3IMP_WEB_SCHEMA_MIN_INSTRUCTION_STEPS`

### Milestone 1 — Implement schema recipe model + confidence gates + mapping

Goal: implement the core of Priority 7 independent of HTML extraction:
- detect Recipe objects in parsed JSON (JSON-LD-ish)
- normalize shapes (handle `@graph`, lists, nested dicts)
- compute confidence score
- map schema Recipe to `RecipeCandidate` (inverse of staging/jsonld)

Deliverables:
- New module: `cookimport/parsing/schemaorg_ingest.py`
- Unit tests for normalization + instruction flattening + mapping
- A small, deterministic schema confidence score function usable by all extractors

### Milestone 2 — Implement HTML schema extraction strategies and HTML→text fallback strategies

Goal: add multiple schema extractors (each as a selectable option) and multiple text extractors (each as a selectable option).

Deliverables:
- New module: `cookimport/parsing/html_schema_extract.py`
- New module: `cookimport/parsing/html_text_extract.py`
- Optional `ensemble_v1` mode(s) that runs multiple installed extractors and selects the best output by the same confidence scoring (explicitly chosen; not “auto” hidden).

### Milestone 3 — Implement the `WEBSCHEMA` importer plugin + registry integration

Goal: implement a new importer plugin that plugs into the existing conversion/staging/writer flow.

Deliverables:
- New plugin: `cookimport/plugins/webschema.py` (or similarly named)
- Registry update so `.html/.htm/.jsonld` auto-select WEBSCHEMA
- Safe `.json` detection (avoid clobbering RecipeSage importer)
- Raw artifacts + report fields for debugging and benchmarking
- Tests that do not require optional deps (use builtin_jsonld + bs4 baseline in default CI)

### Milestone 4 — Optional: benchmark/dash dimension wiring

Goal: make it easy to compare runs by extractor choices.

Deliverables (optional, but recommended given benchmarking intent):
- Add requested/effective WEBSCHEMA knobs into run report summary fields used by performance history and dashboard.
- If there is an “all-method permutation set” for offline benchmarking, add WEBSCHEMA dimensions similarly to EPUB extractor dimensions (explicit columns). (Docs mention interactive all-method permutations exist.):contentReference[oaicite:23]{index=23}

---

## Concrete Steps

### 0) Create a working branch and run baseline tests
1. Create branch:
   - `git checkout -b feat/webschema-priority7`
2. Run baseline tests (or at least `pytest -q`) to ensure clean start.

### 1) Add optional dependencies as a new extra group
1. Edit `pyproject.toml`:
   - Add an extra group, recommended name: `webschema`
   - Add packages:
     - `extruct`
     - `scrape-schema-recipe`
     - `pyld`
     - `recipe-scrapers`
     - `trafilatura`
     - `readability-lxml`
     - `justext`
     - `boilerpy3`
     - `isodate`
   - Keep them *optional* so base installs remain lean.
2. Validate install:
   - `pip install -e ".[dev,webschema]"` (or the repo’s standard dev install command):contentReference[oaicite:24]{index=24}
3. Add a minimal “missing optional dependency” error helper (if one does not exist):
   - e.g., `cookimport/util/optional_deps.py` with:
     - `require_optional(dep_name: str, extra_name: str) -> None` that raises a friendly exception:
       “Install with `pip install -e '.[webschema]'` or choose a different extractor”.

### 2) Add RunSettings knobs + CLI flags + env-var propagation
1. Edit `cookimport/config/run_settings.py`:
   - Add the WEBSCHEMA fields under `RunSettings`.
   - Add UI metadata if your interactive UI relies on `ui_*` / enumerations.
2. Edit config defaults file(s):
   - Update `cookimport.json` defaults (or equivalent) so new fields exist with explicit defaults.
3. Edit CLI:
   - In `cookimport/cli.py` (stage and benchmark commands):
     - Add flags:
       - `--web-schema-extractor`
       - `--web-jsonld-normalizer`
       - `--web-html-text-extractor`
       - `--web-schema-policy`
       - `--web-schema-min-confidence`
       - optional thresholds flags
4. Propagate settings to env vars before worker pools spawn (same pattern as EPUB):
   - Set the `C3IMP_WEB_*` env vars from run settings inside the stage orchestration layer.
   - Ensure values are persisted into run reports (runConfig snapshot) for benchmarking.

Validation:
- Running `cookimport stage --help` shows new flags.
- A dry run with no WEBSCHEMA input still works (new knobs are inert unless importer is used).

### 3) Implement schema normalization + confidence scoring + mapping
Create `cookimport/parsing/schemaorg_ingest.py` with the following stable interfaces.

#### 3.1 Data types / interfaces
- `SchemaRecipeCandidate` (dataclass or pydantic model) representing:
  - `raw: dict` (original schema object)
  - `confidence: float`
  - `reasons: list[str]` (for report/debug)
- Core functions:
  - `def collect_schemaorg_recipe_objects(data: object) -> list[dict]:`
    - Traverses nested dict/list structures (including `@graph`) and returns dicts that “look like” schema recipe.
  - `def schema_recipe_confidence(recipe_obj: dict, *, min_ingredients: int, min_steps: int) -> tuple[float, list[str]]:`
    - Score in [0,1] using deterministic signals:
      - has `recipeIngredient` list length >= min_ingredients
      - has non-empty instructions after flatten
      - has `name` (title)
      - (optional) has times/yield
    - Return both score and reasons.
  - `def flatten_schema_recipe_instructions(recipe_obj: dict) -> list[str]:`
    - Handle:
      - string instructions
      - list of strings
      - `HowToStep` objects (`{"@type":"HowToStep","text":...}`)
      - `HowToSection` objects with nested steps
    - Output should be a list of step strings (no empty strings).
  - `def schema_recipe_to_recipe_candidate(recipe_obj: dict, *, source_path: str, source_hash: str, recipe_index: int) -> RecipeCandidate:`
    - Map:
      - title: `name`
      - ingredients: `recipeIngredient`
      - instructions: flattened instructions
      - yield/time: `recipeYield`, `prepTime`, `cookTime`, `totalTime` (store as candidate metadata if RecipeCandidate lacks explicit fields)
    - Preserve provenance:
      - stable candidate id includes source_hash + recipe_index
      - store original schema object in raw artifacts (and optionally candidate metadata)

#### 3.2 Duration parsing (isodate)
- Implement `parse_schema_duration_to_seconds(duration_value) -> Optional[int]`
  - If `isodate` is installed, use it.
  - If not installed, implement a small fallback that supports only common `PT#H#M#S` and `P#DT#H#M#S` patterns.
- Rationale: BIG PICTURE UPGRADES recommends `isodate` specifically for Schema.org durations (prepTime/cookTime/totalTime).

#### 3.3 JSON-LD normalization (pyld option)
- Implement `normalize_jsonld(data: object, mode: Literal["simple","pyld"]) -> object`
  - `simple`:
    - if dict has `@graph`, return `@graph` list (and keep top-level keys if needed)
    - if list, return list
  - `pyld`:
    - optional path: expand/flatten using pyld and a strict, offline document loader:
      - allow only `http(s)://schema.org` contexts without network
      - if unknown contexts, skip or fallback to simple normalization (but record in report)
- This keeps `pyld` as a benchmarkable option and improves robustness for `@graph`/context variants.

Tests:
- Add tests for:
  - `flatten_schema_recipe_instructions` for HowToStep/HowToSection
  - `collect_schemaorg_recipe_objects` finds recipe in `@graph`
  - `schema_recipe_confidence` thresholds work
  - `parse_schema_duration_to_seconds("PT20M") == 1200` (if isodate present; fallback acceptable with same result)

### 4) Implement HTML schema extraction strategies
Create `cookimport/parsing/html_schema_extract.py`.

Stable interface:
- `def extract_schema_recipes_from_html(html: str, *, base_url: Optional[str], extractor: WebSchemaExtractor, normalizer: JsonLdNormalizer, thresholds: Thresholds) -> list[SchemaRecipeCandidate]:`

Implementation requirements:
- `builtin_jsonld` strategy:
  - Parse `<script type="application/ld+json">...</script>` blocks
  - JSON parse each, normalize, collect recipe objects, score confidence
- `extruct` strategy (option):
  - Use extruct to extract JSON-LD/microdata/RDFa into dicts, then normalize+collect recipe objects, score confidence
- `scrape_schema_recipe` strategy (option):
  - Use scrape-schema-recipe to extract schema recipe objects; then normalize+collect recipe objects, score confidence
- `recipe_scrapers` strategy (option):
  - Use recipe-scrapers as an alternate structured extraction (site-specific or schema-assisted).
  - Map its extracted fields into a schema-like dict (or directly into RecipeCandidate mapping layer).
  - Treat as a separate extractor option for benchmarking
- `ensemble_v1` strategy (option):
  - Run all installed schema extractors in a deterministic order:
    1) scrape-schema-recipe
    2) extruct
    3) builtin_jsonld
    4) recipe-scrapers
  - Choose the set of recipe candidates with:
    - max count of “accepted” candidates above min confidence
    - tie-breaker: highest average confidence
  - Record “effective extractor” in report (requested vs used).

Also add:
- `def extract_canonical_url(html: str) -> Optional[str]`:
  - parse `<link rel="canonical">` and/or `<meta property="og:url">`
  - used as `base_url` and to help recipe-scrapers choose the right scraper

### 5) Implement HTML→text extraction strategies for fallback
Create `cookimport/parsing/html_text_extract.py`.

Stable interface:
- `def extract_main_text_from_html(html: str, *, extractor: WebHtmlTextExtractor) -> tuple[str, dict]:`
  - returns (text, metadata)
  - metadata includes which extractor ran, word/line counts, etc.

Implement these options as separate strategies (all benchmarkable):
- `bs4` (baseline, minimal dependencies):
  - BeautifulSoup get_text with newline separators; strip/normalize whitespace
- `trafilatura` (option)
- `readability_lxml` (option)
- `justext` (option)
- `boilerpy3` (option)
- `ensemble_v1` (option):
  - run all installed extractors, choose best by heuristic “recipe-likeness proxy” score:
    - contains “Ingredients” and “Instructions/Directions/Method”
    - number of non-empty lines
    - penalize extremely short results
  - record requested vs effective in report

Note: This is the fallback lane. Priority 7 explicitly requires fallback when schema absent/weak.

### 6) Implement heuristic section extraction (fallback lane)
Because staging expects importers to provide `RecipeCandidate` objects with explicit ingredient/instruction lines (staging focuses on parsing/linking, not section discovery), implement a minimal section extractor inside the WEBSCHEMA importer module or in a helper module.

Preferred approach (reuse existing shared heuristics, minimal duplication):
- Find the section detection logic already used by `cookimport/plugins/text.py` and factor it into a shared helper:
  - new helper module suggestion: `cookimport/parsing/text_section_extract.py`
  - or add a new function in `cookimport/parsing/sections.py` that is line-oriented.
- Requirements:
  - Input: list[str] lines
  - Output: `(title: Optional[str], ingredients: list[str], instructions: list[str], notes: list[str])`
- Keep it deterministic and conservative:
  - Only accept candidate as “valid recipe” if both ingredients and instructions meet minimum line counts.
  - If one section present and the other absent, return a “partial” candidate (with a low confidence score stored in metadata) rather than inventing data.

This keeps faith with Priority 7’s “validate with recipe-likeness gates” requirement, even before Priority 1’s global scoring system is implemented.

### 7) Implement the WEBSCHEMA importer plugin
Create `cookimport/plugins/webschema.py`.

#### 7.1 Pipeline id + detection
- Pipeline id string: `WEBSCHEMA`
- `detect(path) -> float`:
  - `.html/.htm` => 0.95
  - `.jsonld` => 0.95
  - `.json` => sniff file:
    - parse json, return 0.80 only if it contains `@context` referencing schema.org (or a schema-like Recipe object)
    - otherwise 0.0 (so RecipeSage importer still wins for its `.json` exports)
  - else 0.0

#### 7.2 inspect(path)
- Return a minimal `WorkbookInspection` that:
  - declares a single “sheet”/unit-like entry representing the file
  - includes file size, guessed type (html/json), and any fast-detected metadata
- IMPORTANT: do not add unsupported top-level fields (there is a known sharp edge: `WorkbookInspection` doesn’t accept a `warnings` field).

#### 7.3 convert(path, mapping, progress_callback) -> ConversionResult
High-level algorithm (matches Priority 7):
1) Read file contents.
2) If HTML:
   - determine base_url via canonical url helper
   - run schema extraction using configured `web_schema_extractor` + configured normalizer
3) If JSON:
   - parse JSON, normalize, collect schema recipe objects
4) Score candidates, filter by `web_schema_min_confidence` (and min line thresholds).
5) Apply `web_schema_policy`:
   - `heuristic_only`: ignore schema results, go directly to fallback
   - `schema_only`: if no accepted schema recipes, return ConversionResult with zero recipes + error in report (or raise a controlled exception handled by stage)
   - `prefer_schema`: if accepted schema recipes exist, produce them; else fallback

6) If schema accepted:
   - produce one RecipeCandidate per schema recipe object via mapping function
   - generate tip_candidates from each recipe (use existing `extract_tip_candidates_from_candidate` helper if that’s the standard)
   - raw artifacts:
     - `raw/webschema/<source_hash>/schema_extracted.json` (all candidates + confidences)
     - optionally `raw/.../schema_accepted.json` (accepted only)
     - optionally `raw/.../source.html` (copy of input html, if input was html)
   - report:
     - requested/effective extractor
     - number of schema recipes found / accepted
     - confidence distribution summary

7) If fallback:
   - HTML: run configured html-text extractor; store raw artifact `text_extracted.txt` (or `.md`)
   - run heuristic section extraction to get ingredients/instructions
   - create a single RecipeCandidate (or multiple, if your heuristic sectioning already supports multi-recipe)
   - if still cannot extract a plausible recipe, return 0 recipes but keep extracted text as raw artifact and report “no recipe found”; (do not hallucinate)
   - tip/topic candidates:
     - from candidate if any
     - if no candidate, leave empty

Return a fully populated ConversionResult consistent with other importers:
- `recipes`
- `tip_candidates`, `topic_candidates` as appropriate
- `non_recipe_blocks` likely empty for this importer
- `raw_artifacts` for debugging
- `report` with run config + extractor info

This aligns with the “structured-import-first” family model and the shared writer/staging pipeline.

### 8) Register importer in the registry
- Edit `cookimport/plugins/registry.py`:
  - add `WebSchemaImporter` to the importer list
  - ensure ordering doesn’t matter (score-based selection should pick it)
- Add a small regression test:
  - `.html` path selects WEBSCHEMA
  - `.json` RecipeSage export still selects RecipeSage importer

### 9) Add fixtures + unit tests
Add fixture files under test fixtures directory (follow existing test conventions):
- `fixtures/webschema/html_with_jsonld.html`
  - Minimal HTML with `<script type="application/ld+json">` containing a Recipe
- `fixtures/webschema/html_without_schema_but_clear_sections.html`
  - Ingredients and Instructions headings in body text
- `fixtures/webschema/recipe_jsonld_graph.json`
  - JSON-LD with `@graph` and a Recipe node

Tests to add:
- `test_schemaorg_ingest_flatten_instructions`
- `test_schemaorg_ingest_collects_recipe_from_graph`
- `test_webschema_importer_schema_lane_builtin_jsonld`
  - run with env vars set to builtin_jsonld + simple normalizer
- `test_webschema_importer_fallback_lane_bs4`
  - run with `web_schema_policy=schema_only` should fail when schema absent
  - run with `prefer_schema` should fallback and produce candidate if sections exist
- Optional tests gated by `pytest.importorskip`:
  - extruct strategy
  - scrape-schema-recipe strategy
  - trafilatura/readability/jusText/BoilerPy3 extractors
  - pyld normalizer

### 10) Update docs/support matrix (small but important)
- Update ingestion docs (where format support matrix is listed) to include:
  - HTML (`.html/.htm`) via `cookimport/plugins/webschema.py`
  - JSON-LD (`.jsonld`) and schema-like JSON via the same importer
- Ensure docs clearly state:
  - This is local file ingestion only (no network)
  - Schema-first is preferred and higher precision

### 11) Optional: benchmark permutation wiring
If you have a fixed “all-method” permutation runner:
- Add WEBSCHEMA strategy dimensions for:
  - schema extractor
  - html text extractor
  - jsonld normalizer
  - schema policy
- Ensure those appear as explicit dimension columns in summary tables (like EPUB extractor columns). (Docs mention “fixed extractor/tuning permutation set” exists.):contentReference[oaicite:40]{index=40}

---

## Validation and Acceptance

### Functional acceptance tests (manual)
1) Schema lane (HTML):
   - `cookimport stage path/to/recipe.html --pipeline WEBSCHEMA --web-schema-extractor builtin_jsonld`
   - Expect:
     - `data/output/<ts>/intermediate drafts/<workbook>/r0.jsonld` exists
     - `r0.jsonld` has title/ingredients/instructions that match schema content
     - `raw/webschema/<source_hash>/schema_extracted.json` exists

2) Schema lane (JSON-LD file):
   - `cookimport stage path/to/recipe.jsonld --pipeline WEBSCHEMA`
   - Same expectations.

3) Fallback lane:
   - Use HTML fixture without schema:
     - `cookimport stage path/to/no_schema.html --pipeline WEBSCHEMA --web-html-text-extractor bs4 --web-schema-policy prefer_schema`
   - Expect:
     - at least one recipe if headings exist
     - `raw/webschema/<source_hash>/text_extracted.txt` exists

4) Policy correctness:
   - `--web-schema-policy schema_only` + no schema:
     - run should produce zero recipes and clearly report why (or fail with friendly error)
   - `--web-schema-policy heuristic_only` + schema present:
     - run should ignore schema and use fallback (for benchmarking)

### Automated acceptance tests
- `pytest -q` passes.
- Optional dependency tests pass when running with `.[webschema]`.

---

## Idempotence and Recovery

- All new extractors must be deterministic over file contents (no network, no time-based behavior).
- All raw artifacts written should be namespaced under:
  - `raw/webschema/<source_hash>/...`
  - and use stable filenames (`schema_extracted.json`, `text_extracted.txt`, etc.)
- If a run fails mid-way:
  - rerunning `cookimport stage` should produce a new timestamped run root; no prior output dirs are mutated by default (existing stage behavior).
- Optional deps:
  - If a configured extractor’s dependency is missing, fail fast with a clear message and do not silently fall back unless the extractor is `ensemble_v1` (explicitly chosen).

---

## Artifacts and Notes

### New/changed files (expected)
- `cookimport/plugins/webschema.py` (new)
- `cookimport/parsing/schemaorg_ingest.py` (new)
- `cookimport/parsing/html_schema_extract.py` (new)
- `cookimport/parsing/html_text_extract.py` (new)
- `cookimport/config/run_settings.py` (modified)
- `cookimport/cli.py` (modified: flags + env propagation)
- `cookimport/plugins/registry.py` (modified: add importer)
- `tests/test_webschema_importer.py` (new)
- `tests/test_schemaorg_ingest.py` (new)
- `tests/fixtures/webschema/*` (new)
- `pyproject.toml` (modified: add `webschema` extra)

### Raw artifacts
At minimum, when WEBSCHEMA runs:
- `raw/webschema/<source_hash>/schema_extracted.json`
- `raw/webschema/<source_hash>/schema_accepted.json` (optional but recommended)
- `raw/webschema/<source_hash>/text_extracted.txt` (fallback lane)
- `raw/webschema/<source_hash>/source.html` (optional copy for debugging)

---

## Interfaces and Dependencies

### Importer interface (must match existing contract)
- `detect(path: str) -> float`
- `inspect(path: str) -> WorkbookInspection`
- `convert(path: str, mapping: MappingSpec, progress_callback: Callable[..., None]) -> ConversionResult`

### Proposed stable internal interfaces
In `cookimport/parsing/schemaorg_ingest.py`:
- `collect_schemaorg_recipe_objects(data: object) -> list[dict]`
- `flatten_schema_recipe_instructions(recipe_obj: dict) -> list[str]`
- `schema_recipe_confidence(recipe_obj: dict, *, min_ingredients: int, min_steps: int) -> tuple[float, list[str]]`
- `schema_recipe_to_recipe_candidate(recipe_obj: dict, *, source_path: str, source_hash: str, recipe_index: int) -> RecipeCandidate`
- `parse_schema_duration_to_seconds(value: object) -> Optional[int]` (isodate-backed)

In `cookimport/parsing/html_schema_extract.py`:
- `extract_canonical_url(html: str) -> Optional[str]`
- `extract_schema_recipes_from_html(html: str, *, base_url: Optional[str], extractor: str, normalizer: str, thresholds: Thresholds) -> list[SchemaRecipeCandidate]`

In `cookimport/parsing/html_text_extract.py`:
- `extract_main_text_from_html(html: str, *, extractor: str) -> tuple[str, dict]`

### Third-party libs and how they’re used (as options)
- `extruct`: schema metadata extraction (JSON-LD/microdata/RDFa)
- `scrape-schema-recipe`: schema.org Recipe extraction helper
- `pyld`: optional JSON-LD normalization for robust `@graph`/context handling
- `recipe-scrapers`: alternate structured extraction (site-specific)
- `isodate`: parse Schema.org ISO-8601 durations for prep/cook/total times
- `trafilatura`: boilerplate removal text extractor (fallback lane)
- `readability-lxml`: boilerplate removal via readability algorithm (fallback lane)
- `jusText`: optional boilerplate removal (fallback lane)
- `BoilerPy3`: optional boilerplate removal (fallback lane)

---

Change note (2026-02-25): Initial ExecPlan created for Priority 7 implementation, focusing on adding a WEBSCHEMA structured-first importer lane with schema extraction options + deterministic fallback.