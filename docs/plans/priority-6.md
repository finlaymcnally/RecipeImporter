# ExecPlan: Priority 6 — Time/Temperature/Yield Upgrades (multi-backend, benchmarkable)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This plan must be maintained in accordance with `PLANS.md` at the repository root. :contentReference[oaicite:0]{index=0}

## Context

Priority 6 in `BIG PICTURE UPGRADES.md` calls for deterministic upgrades that better match downstream database fields: (a) capture all temperatures per step and compute `max_oven_temp_f` from “oven-like” temps, (b) compute step `total_time_seconds` more robustly than summing all durations, and (c) make yield extraction consistent by selecting among multiple candidates via scoring, populating `yield_units`, `yield_phrase`, `yield_unit_name`, and `yield_detail` while avoiding nutrition-number false positives. :contentReference[oaicite:1]{index=1}

The current instruction parser extracts per-step time and temperature metadata, but its documented limitations match the Priority 6 motivations: it sums all duration spans into `total_time_seconds` and only captures the first temperature mention. :contentReference[oaicite:2]{index=2}

Staging converts `RecipeCandidate -> RecipeDraftV1` in `cookimport/staging/draft_v1.py`, and step time metadata is already used as a fallback rollup for recipe cook time when recipe-level cook time is missing. That makes a “smarter `total_time_seconds`” directly impact downstream `cook_time_seconds` quality. :contentReference[oaicite:3]{index=3}

The reference DB field inventory includes `max_oven_temp_f` plus yield-related columns (`yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail`), which Priority 6 explicitly targets. :contentReference[oaicite:4]{index=4}:contentReference[oaicite:5]{index=5}

To support these improvements with benchmarkable permutations, `BIG PICTURE UPGRADES.md` recommends specific libraries for Priority 6 and Priority 6-secondary usage:
- `isodate` for parsing schema.org ISO-8601 durations,
- `quantulum3` for numeric+unit span extraction (times/temps),
- `pint` for unit canonicalization/conversion,
- and (for HTML-ish schema sources that can improve time/yield) `extruct`, `scrape-schema-recipe`, `pyld`, and `recipe-scrapers`. :contentReference[oaicite:6]{index=6}:contentReference[oaicite:7]{index=7}

Run settings are defined in `cookimport/config/run_settings.py` and are designed to be expanded via `ui_*` metadata so the interactive editor picks them up; `stage(...)` is called from both Typer CLI and direct callers, so new settings must be consistently plumbed through and persisted. :contentReference[oaicite:8]{index=8}

## Goal

Implement Priority 6 as a set of deterministic, configurable extraction upgrades that:
- Populate DB-aligned recipe fields for yield (`yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail`) and temperature (`max_oven_temp_f`) in the produced `RecipeDraftV1` (and any schema.org JSON-LD artifacts if applicable).
- Improve step-level time aggregation to support safer `cook_time_seconds` rollups, without losing the legacy “sum all durations” baseline.
- Introduce new, selectable backends for overlapping functionality so you can benchmark permutations:
  - Time extraction: existing regex baseline and new `quantulum3` (plus a hybrid option).
  - Temperature extraction: existing regex baseline and new `quantulum3` (plus a hybrid option), plus `pint` for unit handling as an additional option.
  - ISO-8601 duration parsing: `isodate` as an option for schema durations.
  - HTML/schema extraction (Priority 6-secondary): `extruct`, `scrape-schema-recipe`, `pyld`, `recipe-scrapers` as options when HTML-ish inputs or embedded schema are present.
- Keep defaults conservative (legacy behavior) to avoid surprise regressions; make the improved paths opt-in via run settings and CLI flags, with clear install guidance for optional dependencies.

## Non-Goals

This plan does not implement Priority 7’s full “structured-first lane” (no new end-to-end web scraping workflow, no network fetching, and no guarantee that HTML ingestion is a first-class importer). The HTML/schema tooling will be integrated only as optional, local-only helpers to improve time/yield when schema is already present in an input or importer-provided HTML payload. :contentReference[oaicite:9]{index=9}

This plan does not:
- Change the stage block-role classifier or benchmark scoring surface (which scores stage evidence `stage_block_predictions.json`, not final draft fields). :contentReference[oaicite:10]{index=10}
- Introduce new database migrations or alter DB constraints (it only targets producing better values for existing fields).
- Rework the LLM pipelines; any interactions with LLM outputs are additive and must remain grounded in extracted evidence.

## Assumptions

- `cookimport/parsing/instruction_parser.py` is the single point of truth for per-step time and temperature metadata extraction, and callers can be updated to pass an options object (or run settings derived options) without breaking unrelated pipelines. :contentReference[oaicite:11]{index=11}
- `cookimport/staging/draft_v1.py` (or a nearby staging module) is where recipe-level fields like cook time fallbacks are derived, and it can also safely compute `max_oven_temp_f` and yield fields at recipe build time. :contentReference[oaicite:12]{index=12}
- The block taxonomy already includes `YIELD_LINE` and `TIME_LINE`, and there are existing signal heuristics for yield/time detection that can be reused for candidate generation and scoring. :contentReference[oaicite:13]{index=13}:contentReference[oaicite:14]{index=14}
- Adding optional dependencies via extras (and guarding imports) is acceptable. Optional backends should fail fast with actionable error messages when selected but not installed.
- Some importers already preserve HTML-ish payloads (e.g., Paprika merges zip/HTML and RecipeSage has structured JSON), making optional schema extraction practical without adding a new importer. :contentReference[oaicite:15]{index=15}:contentReference[oaicite:16]{index=16}

## Milestones

### Milestone 1 — Parsing primitives + multi-backend instruction parsing (time + temperature)
Scope: Extend instruction parsing to support multiple extraction backends while keeping the current behavior as a selectable baseline. Introduce richer internal representations for time spans and temperature spans, including “oven-like” classification for temperatures.

What will exist at the end:
- `parse_instruction(...)` (or a sibling function) can return all temperature mentions and detailed time items.
- `total_time_seconds` can be computed by strategy (`sum_all`, `max`, `selective_sum_v1`) without removing the legacy strategy described in current docs. :contentReference[oaicite:17]{index=17}:contentReference[oaicite:18]{index=18}
- New extraction backends exist as options: `regex_v1` (current), `quantulum3_v1`, and `hybrid_v1` for both time and temperature. `pint` becomes an optional conversion/canonicalization backend, and `isodate` becomes an optional parser for ISO-8601 duration strings. :contentReference[oaicite:19]{index=19}:contentReference[oaicite:20]{index=20}

Commands to run:
    python -m pip install -e '.[dev]'
    python -m pip install -e '.[priority6]'  # new extra added in this milestone
    pytest -q tests/test_instruction_parser.py

Acceptance:
- Baseline tests for instruction parsing still pass, and new tests demonstrate:
  - Multiple temperatures are captured in metadata.
  - “Oven-like” classification works for “preheat oven to 350°F” vs “chill to 40°F”.
  - `total_time_seconds` differs by strategy in a deterministic, explainable way.

### Milestone 2 — Yield extraction engine (candidate generation + scoring + parsing)
Scope: Build a single yield extraction path that can pull yield candidates from multiple sources (block labels, heuristics, importer-provided fields, and optional schema), score them, select the best, and parse into DB-aligned fields.

What will exist at the end:
- A new module (or modules) dedicated to yield extraction that:
  - Generates yield candidates using existing `YIELD_LINE` blocks and yield/time signals. :contentReference[oaicite:21]{index=21}:contentReference[oaicite:22]{index=22}
  - Scores candidates (near title/top, near ingredients heading) and rejects nutrition-like false positives via keyword context. :contentReference[oaicite:23]{index=23}
  - Produces `yield_phrase` even when numeric parsing fails, and fills `yield_detail` for qualifiers (ranges, “about”, etc.). :contentReference[oaicite:24]{index=24}
- Yield parsing backends exist as options: `regex_v1` (baseline) and `quantulum3_v1` (plus `hybrid_v1`), and `pint` is optionally used for unit canonicalization when relevant. :contentReference[oaicite:25]{index=25}:contentReference[oaicite:26]{index=26}

Commands to run:
    python -m pip install -e '.[priority6]'
    pytest -q tests/test_yield_extraction.py

Acceptance:
- Unit tests cover at least:
  - “Serves 4” -> `yield_units=4`, `yield_unit_name` resolves to “servings” (or project’s canonical equivalent), `yield_phrase` preserved.
  - “Makes 24 cookies” -> `yield_units=24`, `yield_unit_name=cookies`.
  - A nutrition line like “Calories: 240” is not selected as yield when a real yield candidate exists nearby.
  - When parsing fails, `yield_phrase` is still populated and `yield_units` remains a safe default (respecting DB constraints).

### Milestone 3 — Staging integration: recipe-level `max_oven_temp_f`, yield fields, and time rollup strategy
Scope: Wire the new parsing engines into staging so outputs actually improve DB-aligned fields, while keeping old behavior selectable. This includes computing recipe-level `max_oven_temp_f` from step temperature metadata and ensuring cook-time rollups respect the selected `total_time_seconds` strategy.

What will exist at the end:
- `cookimport/staging/draft_v1.py` populates:
  - Yield fields (`yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail`) using the new scored selector (or legacy mode, selectable). :contentReference[oaicite:27]{index=27}
  - `max_oven_temp_f` as the max of “oven-like” temperatures across steps. :contentReference[oaicite:28]{index=28}
- Step time metadata rollup to recipe cook time uses the chosen `total_time_seconds` strategy (without removing the legacy sum behavior). :contentReference[oaicite:29]{index=29}

Commands to run:
    python -m pip install -e '.[priority6]'
    cookimport stage data/input/<small_fixture> --output-dir data/output/_p6_smoke
    pytest -q tests/test_staging_draft_v1.py -q

Acceptance:
- A staged output contains the expected fields populated (or intentionally empty when not derivable) and remains schema-valid for `RecipeDraftV1`.
- The legacy behavior can be reproduced by selecting legacy run settings, enabling head-to-head benchmarking.

### Milestone 4 — Optional HTML/schema helpers (Priority 6-secondary): extruct / scrape-schema-recipe / pyld / recipe-scrapers
Scope: Add optional schema extraction helpers that can improve yield/time when schema is present in HTML-ish inputs, without implementing full Priority 7 ingestion. Provide multiple library choices as benchmarkable options.

What will exist at the end:
- A new “schema recipe extraction” interface with selectable backends:
  - `extruct_v1` (extract JSON-LD/microdata),
  - `scrape_schema_recipe_v1` (convenience adapter),
  - `pyld_v1` (optional normalization for `@graph`/multi-entity JSON-LD),
  - `recipe_scrapers_v1` (schema-aware extractor, local HTML mode when possible). :contentReference[oaicite:30]{index=30}
- `isodate` is used (as an option) to parse schema ISO-8601 duration fields into seconds/minutes when schema fields like `prepTime`, `cookTime`, `totalTime` exist. :contentReference[oaicite:31]{index=31}
- Integration is strictly optional and gated behind run settings; when disabled, behavior is unchanged.

Commands to run:
    python -m pip install -e '.[priority6,htmlschema]'
    pytest -q tests/test_schema_recipe_extraction.py

Acceptance:
- With a small local HTML fixture containing schema.org Recipe JSON-LD, the extractor can produce a normalized “schema recipe” object and yield/time values that feed the same yield/time pipelines as text-derived candidates.
- Each backend can be selected independently; missing dependencies produce a clear error telling the user which extra to install.

### Milestone 5 — Run settings + CLI wiring + benchmarking artifacts
Scope: Make every new backend/strategy selectable from the existing run-settings surface and provide artifacts that support benchmarking permutations without changing the existing stage/benchmark scoring surfaces.

What will exist at the end:
- New run settings fields in `cookimport/config/run_settings.py` with `ui_*` metadata, wired through `stage(...)` callers so they persist and appear in interactive run-settings editor. :contentReference[oaicite:32]{index=32}
- CLI flags (or equivalent configuration paths) to select:
  - time backend + time aggregation strategy,
  - temperature backend + conversion backend,
  - yield selection mode + yield parse backend,
  - optional schema-extraction backend and duration parsing backend.
- A new optional debug/coverage artifact family (written under the run folder) that records:
  - selected yield + top N candidates with scores and parse outcomes,
  - per-step temperatures found and which were “oven-like”,
  - computed `max_oven_temp_f`,
  - time items per step and resulting `total_time_seconds` under the selected strategy.
  This artifact is specifically to support permutation benchmarking without altering the benchmark’s stage-block prediction surface. :contentReference[oaicite:33]{index=33}

Commands to run:
    cookimport stage data/input/<fixture> --output-dir data/output/_p6_bench --p6-time-backend regex_v1 --p6-time-strategy sum_all
    cookimport stage data/input/<fixture> --output-dir data/output/_p6_bench --p6-time-backend quantulum3_v1 --p6-time-strategy selective_sum_v1
    cookimport stage data/input/<fixture> --output-dir data/output/_p6_bench --p6-yield-mode scored_v1 --p6-yield-backend hybrid_v1 --p6-emit-metadata-debug
    pytest -q

Acceptance:
- All new knobs are visible and persist correctly in interactive and non-interactive flows.
- Debug artifacts are produced only when enabled, and are stable enough to diff/aggregate across runs.

## Work Plan

### 1) Add optional dependencies and extras

Update `pyproject.toml` (or the project’s dependency manifest) to add new extras:

- Extra `priority6` (core Priority 6 tools):
  - `isodate`
  - `quantulum3`
  - `pint`

- Extra `htmlschema` (Priority 6-secondary HTML/schema helpers):
  - `extruct`
  - `scrape-schema-recipe`
  - `pyld`
  - `recipe-scrapers`

The goal is to keep the base install unchanged and allow explicit installation for benchmarking permutations. If the repo already uses extras (e.g., `.[epubdebug]`), follow the same convention for naming and documentation.

Implementation detail: Add a small helper module for optional imports, so backends fail fast with messages like: “Backend quantulum3_v1 selected but quantulum3 not installed. Install with `pip install -e '.[priority6]'`”.

### 2) Introduce a Priority-6 options surface derived from run settings

Add new fields to `cookimport/config/run_settings.py` (with `ui_title`, `ui_help`, allowed values, and safe defaults). Run settings are the canonical surface for “benchmark permutations”, so every overlapping capability must be selectable here. :contentReference[oaicite:34]{index=34}

Suggested fields (names may be adjusted to match existing style, but keep them grouped/prefixed so they’re easy to sweep):
- `p6_time_backend`: `regex_v1` | `quantulum3_v1` | `hybrid_v1` (default `regex_v1`)
- `p6_time_total_strategy`: `sum_all_v1` | `max_v1` | `selective_sum_v1` (default `sum_all_v1`) :contentReference[oaicite:35]{index=35}
- `p6_temperature_backend`: `regex_v1` | `quantulum3_v1` | `hybrid_v1` (default `regex_v1`)
- `p6_temperature_unit_backend`: `builtin_v1` | `pint_v1` (default `builtin_v1`)
- `p6_temperature_ovenlike_mode`: `keywords_v1` (default) plus a `none_v1` fallback if you want a baseline that treats all temps equally.
- `p6_yield_mode`: `legacy_v1` | `scored_v1` (default `legacy_v1`) :contentReference[oaicite:36]{index=36}
- `p6_yield_parse_backend`: `regex_v1` | `quantulum3_v1` | `hybrid_v1` (default `regex_v1`)
- `p6_schema_html_backend`: `off` | `extruct_v1` | `scrape_schema_recipe_v1` | `recipe_scrapers_v1` (default `off`) :contentReference[oaicite:37]{index=37}
- `p6_schema_duration_backend`: `off` | `isodate_v1` (default `off` unless schema backend is enabled) :contentReference[oaicite:38]{index=38}
- `p6_emit_metadata_debug`: bool (default false)

Each run setting’s `ui_help` must explain what changes, and which extra is required.

Plumbing: Identify the single place where `RunSettings` is normalized and passed into staging workers (`stage(...)` callsites) and ensure these new fields are included end-to-end (Typer CLI, interactive menu, and direct Python entrypoints). This is explicitly called out as a correctness requirement for run settings. :contentReference[oaicite:39]{index=39}

### 3) Refactor instruction parsing to support multiple backends and strategies

In `cookimport/parsing/instruction_parser.py`, introduce:
- A stable `InstructionParseOptions` (or similar) object derived from run settings.
- A pair of backend interfaces (or simple strategy functions):
  - `extract_time_items(text, backend=...) -> list[TimeItem]`
  - `extract_temperature_items(text, backend=...) -> list[TemperatureItem]`

Keep the existing output fields for backward compatibility, but extend the result with:
- `temperature_items`: list of all extracted temps (with original span text, converted Fahrenheit, and an `is_oven_like` flag).
- `time_items`: keep as-is but enrich items with flags that help selective-sum logic (alternative/frequency/total-override).
- `total_time_seconds`: computed according to selected strategy; keep legacy sum strategy available and default. :contentReference[oaicite:40]{index=40}:contentReference[oaicite:41]{index=41}

Backend specifics:
- `regex_v1`: preserve current regex extraction logic, but return all matches instead of only the first temperature. Maintain an explicit compatibility field like `temperature_f` set to “first match” to avoid downstream breakage.
- `quantulum3_v1`: use quantulum3 to extract quantities with time and temperature units. Cache any expensive model initialization (quantulum3 may transitively rely on NLP components; do not reinitialize per step). If quantulum3 requires a spaCy model, document and/or provide a minimal fallback configuration so that enabling the backend is deterministic.
- `hybrid_v1`: run both regex and quantulum3, deduplicate overlaps (by span indices or normalized value/unit), and keep a deterministic ordering (e.g., by start position then by backend priority).

Time aggregation strategies:
- `sum_all_v1`: sum the max duration for each time item (legacy behavior).
- `max_v1`: take the maximum duration in the step.
- `selective_sum_v1`: sum only durations that are not obviously alternatives or non-total “frequency” instructions (e.g., “every 2 minutes”), and treat “or” alternatives as a max-group rather than additive. The intent is deterministic but less error-prone than blind summing. :contentReference[oaicite:42]{index=42}

Temperature “oven-like” classification:
- Implement `is_oven_like(text, span_start, span_end)` using keyword proximity rules (“preheat”, “oven”, “bake at”) as suggested, plus a small explicit negative keyword list (e.g., “fridge”, “refrigerate”, “freezer”) to reduce false positives. The recipe-level `max_oven_temp_f` must only consider temps marked oven-like by this heuristic. :contentReference[oaicite:43]{index=43}

### 4) Implement yield candidate generation, scoring, and parsing

Create a new yield module (recommended structure):
- `cookimport/parsing/yield_candidates.py`: gathers candidates from:
  - blocks labeled `YIELD_LINE`,
  - any existing yield/time signal heuristics,
  - importer-provided structured yield/servings fields when present,
  - optional schema recipe fields when available (Milestone 4).
- `cookimport/parsing/yield_scoring.py`: scores candidates based on:
  - position near the top/title,
  - position near ingredients heading,
  - presence of yield keywords (“serves”, “makes”, “yield”),
  - explicit rejection penalties when nutrition keywords are present (calories/macros). :contentReference[oaicite:44]{index=44}
- `cookimport/parsing/yield_parsing.py`: parses the selected candidate into:
  - `yield_phrase` always,
  - `yield_units` when possible,
  - `yield_unit_name` when possible,
  - `yield_detail` for ranges/qualifiers.

Backend support:
- `regex_v1`: deterministic regex rules for common yield phrasing.
- `quantulum3_v1`: quantity+unit parsing where it helps; for “count” yields with arbitrary units (cookies, muffins), allow a fallback that treats the noun following the number as `yield_unit_name` if quantulum3 returns unitless output.
- `hybrid_v1`: prefer regex for “serves/makes/yield” patterns and use quantulum3 for physical-unit yields or messy numeric spans.

DB alignment caveat:
- If the DB enforces `yield_units >= 1`, ensure yield parsing never emits a value < 1. If the parsed yield is < 1 and the unit is a physical unit, optionally use `pint_v1` to convert to a smaller unit that yields a magnitude >= 1 (e.g., 0.5 cup -> 8 tbsp). If conversion is unavailable, clamp to 1 and keep the true quantity in `yield_detail` while preserving `yield_phrase`. This is a pragmatic “match DB fields” policy and should be explicitly tested. :contentReference[oaicite:45]{index=45}:contentReference[oaicite:46]{index=46}

### 5) Wire staging outputs (draft + schema) to use the new engines

In `cookimport/staging/draft_v1.py`:
- Identify where step metadata is computed (it already parses steps with `parse_instruction`). Update the call to pass `InstructionParseOptions` derived from `RunSettings`. :contentReference[oaicite:47]{index=47}
- Compute recipe-level `max_oven_temp_f` by taking the max of oven-like temps across all steps. Store it into the draft field that maps to the DB column `max_oven_temp_f`. :contentReference[oaicite:48]{index=48}:contentReference[oaicite:49]{index=49}
- Apply the yield extraction engine to populate `yield_units`, `yield_phrase`, `yield_unit_name`, `yield_detail` in the draft. The `legacy_v1` yield mode must preserve current behavior (whatever it is today), and `scored_v1` must be available as an alternative option for benchmarking. :contentReference[oaicite:50]{index=50}
- Ensure the existing cook-time fallback rollup uses the step-level `total_time_seconds` as computed under the selected strategy, while preserving legacy `sum_all_v1` as an option. :contentReference[oaicite:51]{index=51}

If `cookimport/staging/jsonld.py` emits schema.org Recipe JSON-LD already, consider also including:
- `recipeYield` from the selected yield phrase,
- `prepTime/cookTime/totalTime` if derived from schema or structured sources,
- and/or a `recipeimport:` namespaced metadata field for `max_oven_temp_f` if the schema supports custom extension fields in your pipeline.
This is optional, but helps downstream consumers that read schema JSON-LD as an intermediate artifact. :contentReference[oaicite:52]{index=52}

### 6) Optional schema extraction backends (local HTML mode only)

Add a module like `cookimport/parsing/schema_recipe_extract.py` that:
- Accepts an HTML string plus optional URL/base URL.
- Runs one selected backend:
  - `extruct_v1` to extract JSON-LD/microdata into raw dicts,
  - `scrape_schema_recipe_v1` as a convenience adapter,
  - `pyld_v1` (optional) to normalize `@graph` to a single Recipe object,
  - `recipe_scrapers_v1` to extract recipe fields when supported, using local HTML rather than fetching. :contentReference[oaicite:53]{index=53}
- Produces a normalized “schema recipe” dict (or None) that is passed into the same yield/time pipelines as an additional high-confidence candidate source.
- Uses `isodate_v1` (when enabled) to parse ISO durations to seconds. :contentReference[oaicite:54]{index=54}

Integration point:
- If an importer already preserves an HTML payload (e.g., Paprika), thread that HTML string into the candidate metadata so staging can use it when `p6_schema_html_backend != off`. This is intentionally “secondary” integration, not a new importer. :contentReference[oaicite:55]{index=55}

### 7) Benchmarking artifacts (debug + coverage) without changing benchmark scoring

Add an optional artifact writer (likely in `cookimport/staging/writer.py`, alongside other stage output families) that emits a machine-readable per-recipe/per-run debug record when `p6_emit_metadata_debug` is true. The artifact should live under the run folder and be deterministic, stable for diffs, and safe to ignore.

Proposed shape (one JSON object per recipe, JSONL):
    {
      "recipe_id": "...",
      "title": "...",
      "p6": {
        "time_backend": "quantulum3_v1",
        "time_strategy": "selective_sum_v1",
        "temp_backend": "hybrid_v1",
        "temp_ovenlike_mode": "keywords_v1",
        "yield_mode": "scored_v1",
        "yield_backend": "hybrid_v1",
        "schema_backend": "off"
      },
      "yield": {
        "selected": { "yield_units": 4, "yield_unit_name": "servings", "yield_phrase": "Serves 4", "yield_detail": null },
        "candidates": [ { "text": "...", "score": 0.93, "parsed": {...}, "rejected_reason": null }, ... ]
      },
      "temperature": {
        "max_oven_temp_f": 350,
        "steps": [ { "step_index": 0, "temps": [ ... ] }, ... ]
      },
      "time": {
        "steps": [ { "step_index": 0, "time_items": [ ... ], "total_time_seconds": 1800 }, ... ]
      }
    }

This artifact is for permutation benchmarking and does not affect the stage evidence surface used by `cookimport bench` or Label Studio benchmark flows. :contentReference[oaicite:56]{index=56}

### 8) CLI + interactive wiring

Add CLI flags that map 1:1 to new run settings fields. Use existing patterns in `cookimport/cli.py` and ensure that:
- Non-interactive `cookimport stage` accepts these flags.
- Interactive run-settings editor shows these fields (because they’re defined in `run_settings.py` with `ui_*` metadata). :contentReference[oaicite:57]{index=57}
- `stage(...)` normalization coerces Typer defaults correctly and persists settings so reruns and sweeps capture the full permutation surface. :contentReference[oaicite:58]{index=58}

### 9) Documentation updates

Add a short doc entry describing:
- What Priority 6 adds (multi-temp, smarter time totals, scored yield).
- How to install extras (`.[priority6]`, `.[htmlschema]`).
- How to enable each backend via run settings and CLI.
- How to read the new metadata debug artifact.

Keep it minimal and colocated with existing staging/run settings docs.

## Validation Plan

Baseline first:
- On the current main branch (before changes), run `pytest -q` and record the baseline pass/fail counts in `Progress`. If there are known fixture-related failures, record them as baseline so you can assert “no new failures introduced”.

Unit tests:
- Extend `tests/test_instruction_parser.py` to cover:
  - multiple temps,
  - oven-like classification,
  - `sum_all_v1` vs `max_v1` vs `selective_sum_v1` differences.
- Add `tests/test_yield_extraction.py` to cover:
  - candidate scoring selection behavior (top vs near ingredients),
  - nutrition false positive rejection,
  - parsing of “serves”, “makes”, ranges, and “yield” phrasing.
- Add `tests/test_schema_recipe_extraction.py` (optional-deps) with a tiny HTML fixture that includes schema.org Recipe JSON-LD and ISO-8601 durations; validate `isodate_v1` parsing.

Integration/smoke tests:
- Run `cookimport stage` on one small fixture input with:
  - legacy settings (should match baseline),
  - each new backend enabled individually,
  - hybrid backends,
  - schema backend enabled (if fixture contains schema).
- Use `jq` (or a small Python snippet) to assert fields exist in output draft(s):
    jq '.draft_v1.max_oven_temp_f, .draft_v1.yield_phrase, .draft_v1.yield_units, .draft_v1.yield_unit_name, .draft_v1.yield_detail' <output_draft.json

Debug artifact validation:
- Enable `p6_emit_metadata_debug` and confirm:
  - file is written,
  - contains one record per recipe,
  - includes selected backend identifiers and selected outputs.

## Rollout Plan

Phase 1 (safe landing):
- Ship all new features behind run settings with legacy defaults:
  - time strategy default remains `sum_all_v1`,
  - time/temp backends default remain `regex_v1`,
  - yield mode default remains `legacy_v1`,
  - schema backend remains `off`.
This ensures existing production-like runs do not change unless explicitly opted in, while enabling permutation benchmarking.

Phase 2 (benchmark + decide defaults):
- Use the new debug artifact to compare:
  - coverage: % recipes with yield selected + parsed,
  - false positives: nutrition lines selected,
  - `max_oven_temp_f` plausibility distribution,
  - cook time rollup stability.
- After you have data, consider flipping defaults (e.g., time strategy to `selective_sum_v1` and yield mode to `scored_v1`) in a separate, explicitly labeled change, with a documented Decision Log entry and before/after summary.

Phase 3 (optional HTML/schema):
- Keep schema backend off by default until you have real HTML sources; when enabled, treat schema-derived time/yield as a high-confidence candidate source but still run the scoring/selection logic so it competes with text-derived candidates (this makes it benchmarkable across different importers).

## Progress

- [x] (2026-02-25 18:44-05:00) Drafted ExecPlan for Priority 6 (time/temp/yield) with multi-backend options and dependency mapping.

- [ ] Record baseline `pytest -q` results from main (pass/fail counts + known failures).
- [ ] Add `priority6` and `htmlschema` extras in dependency manifest; add optional-import helpers and clear error messages.
- [ ] Implement multi-temp extraction + oven-like classification in instruction parsing (`regex_v1` baseline preserved).
- [ ] Implement time strategies (`sum_all_v1`, `max_v1`, `selective_sum_v1`) and ensure deterministic behavior with tests.
- [ ] Add `quantulum3_v1` and `hybrid_v1` backends for time/temp extraction; cache initialization and document any required models.
- [ ] Add yield candidate generation + scoring + parsing with `legacy_v1` and `scored_v1` modes; add tests.
- [ ] Integrate yield + `max_oven_temp_f` + time rollup strategy into `draft_v1` staging output.
- [ ] Implement optional schema extraction module with `extruct_v1`, `scrape_schema_recipe_v1`, `pyld_v1`, `recipe_scrapers_v1`; add HTML fixture tests.
- [ ] Add run settings + CLI flags + interactive wiring for all new knobs; verify persistence through `stage(...)`.
- [ ] Add optional metadata debug artifact; validate stability and usefulness for benchmarking.
- [ ] Update docs for new run settings and extras; record final validation outputs here.

## Decision Log

- Decision: Keep legacy behavior as the default for all Priority 6 settings; ship improvements as opt-in run settings first.
  Rationale: Enables safe landing and side-by-side benchmarking without silently changing outputs.
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Treat `quantulum3`, `pint`, and `isodate` as optional dependencies under a `priority6` extra, and HTML/schema helpers under a separate `htmlschema` extra.
  Rationale: Keeps base install lightweight and makes backends explicitly selectable and benchmarkable.
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Compute `max_oven_temp_f` from “oven-like” temperatures only, using keyword proximity rules (“preheat”, “oven”, “bake at”).
  Rationale: Matches Priority 6 guidance and avoids fridge/candy-thermometer noise.
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Yield selection uses scored candidate picking (top/title proximity and ingredients proximity) with nutrition-keyword rejection; always preserve `yield_phrase` even when parsing fails.
  Rationale: Matches Priority 6 guidance and aligns with DB fields.
  Date/Author: 2026-02-25 / ChatGPT

## Surprises & Discoveries

No discoveries yet. As implementation proceeds, record any unexpected behavior here with short evidence snippets (test output or minimal repros).

## Outcomes & Retrospective

Not started. At completion, summarize what shipped, what remains, and what you would do differently.

## Idempotence and Recovery

All work should remain idempotent and safe to rerun:
- Running `cookimport stage` with new settings must write to a new output directory or an explicitly chosen one; it should not mutate inputs.
- Optional backends must either run deterministically or fail early with clear guidance to install the correct extras.
- If a new backend produces undesirable outputs, recovery is selecting legacy run settings (baseline backends and strategies) and rerunning stage.

For partial failures:
- If staging fails mid-run, rerun with the same input and output dir policy you already use (if overwrite prompts exist, follow them). Ensure debug artifacts are written atomically (write temp then rename) so partially written JSONL does not masquerade as complete.

## Artifacts and Notes

Existing artifacts to keep stable:
- Stage evidence `.bench/<workbook_slug>/stage_block_predictions.json` is the benchmark prediction surface and should not be impacted by Priority 6 field changes. :contentReference[oaicite:59]{index=59}

New artifacts introduced by this plan (opt-in):
- A metadata debug artifact (JSONL) under the run folder that captures yield candidates/scores, per-step temps, and time items/totals for benchmarking permutations.

Notes:
- Prefer writing debug artifacts in a way that is stable for diffing (sorted keys, deterministic ordering of candidate lists, fixed rounding rules).

## Interfaces and Dependencies

New/updated internal interfaces:
- `InstructionParseOptions` derived from `RunSettings`, passed through wherever `parse_instruction` is called.
- `TimeExtractorBackend` and `TemperatureExtractorBackend` strategy layer (even if implemented as functions) that supports `regex_v1`, `quantulum3_v1`, and `hybrid_v1`.
- `YieldExtractor` that takes a recipe candidate + block context and returns DB-aligned yield fields plus debug details.

Run settings / user-facing dependencies:
- `cookimport/config/run_settings.py` must expose new Priority 6 configuration knobs via `ui_*` metadata and must be fully plumbed through `stage(...)` for both CLI and interactive flows. :contentReference[oaicite:60]{index=60}

External libraries that must be incorporated as selectable options (not replacements):
- `isodate` for ISO-8601 schema duration parsing (optionally enabled).
- `quantulum3` for quantity/unit span extraction (time/temp and yield parsing helper).
- `pint` for unit canonicalization/conversion (time/temp/yield when applicable).
- `extruct`, `scrape-schema-recipe`, `pyld`, `recipe-scrapers` for optional HTML/schema extraction pathways (Priority 6-secondary). :contentReference[oaicite:61]{index=61}:contentReference[oaicite:62]{index=62}

Change note (this plan revision)
- 2026-02-25 18:44-05:00: Initial ExecPlan created to implement Priority 6 from `BIG PICTURE UPGRADES.md`, explicitly incorporating all Priority 6 (and Priority 6-secondary) library/tool recommendations as benchmarkable options.