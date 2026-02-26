# Priority 4: Harden ingredient parsing (normalization + post-parse repair) and remove the “medium” default

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

PLANS.md is checked into the repo root as `PLANS.md`; this document must be maintained in accordance with it.:contentReference[oaicite:0]{index=0}

## Purpose / Big Picture

After this change, ingredient lines that commonly break parsers will be normalized and repaired deterministically, so that:

1) “Packaging” lines like `1 (14-ounce) can tomatoes` keep `can` as the unit while preserving `14-ounce` in `note`.

2) Lines with a count but no explicit unit (e.g., `2 onions`) no longer default to unit `"medium"`. Instead, they keep the quantity and use a “missing-unit policy” (default: unit null; optional: unit `"each"`; optional legacy: `"medium"` for benchmarking).

3) If parsing produces obviously-bad outputs (non-numeric quantities, empty ingredient names, “unit” that is clearly an ingredient word), we repair or fall back to a simpler parse while preserving `raw_text` so nothing is lost.

You can see it working by running the focused ingredient parser tests and by calling `parse_ingredient_line()` on the examples above; the returned dict/model should show correct `input_qty`, `raw_unit_text` (or equivalent), and `note`, with no `"medium"` default leaking into units unless the legacy option is explicitly enabled.:contentReference[oaicite:1]{index=1}

## Progress

- [x] (2026-02-25 00:00Z) ExecPlan authored.
- [ ] Add dependencies: `ftfy`, `quantulum3`, `pint` to `pyproject.toml` and lockfile; confirm import works.
- [ ] Prototype the three libraries in small one-off scripts to confirm APIs and edge cases.
- [ ] Add new RunSettings knobs for ingredient parsing options and ensure they persist into run-config metadata (stage + prediction-generation lane).
- [ ] Implement pre-normalization pipeline, including packaging pattern hoisting into `note`.
- [ ] Implement post-parse validation + deterministic repair rules, including fallback parsing.
- [ ] Implement “missing unit policy” (default: null) and keep `legacy_medium` as an explicit benchmark option.
- [ ] Implement `quantulum3` as an alternate parser backend (and/or fallback backend) without removing the existing `ingredient-parser-nlp` backend.
- [ ] Implement `pint` as an optional unit canonicalization backend without removing existing upstream normalization.
- [ ] Update docs to match new semantics and new knobs.
- [ ] Add/adjust tests in `tests/test_ingredient_parser.py` to cover the new behavior and options.
- [ ] Run focused tests and a small end-to-end stage/prediction run to ensure run-config metadata includes the new knobs.

## Surprises & Discoveries

- Observation: The current ingredient parser already uses `ingredient-parser-nlp` and has a deliberate but semantically-debty behavior: when an amount has no unit, the unit defaults to `"medium"`. This is called out in the repo docs summary and in Priority 4’s requirements.:contentReference[oaicite:2]{index=2}:contentReference[oaicite:3]{index=3}
- Observation: The staging contract already supports unresolved units by setting `input_unit_id` to null while preserving `raw_unit_text`, and requires unquantified lines to have `input_qty=null` and `input_unit_id=null`. This makes “quantity present, unit missing” safe as long as we keep the quantity and leave unit unresolved (or set a safe placeholder like `"each"`).
- Observation: The project has a durable “pipeline-option wiring checklist” for introducing new processing knobs; if we add RunSettings options for ingredient parsing, we must wire them through both stage and prediction-generation/benchmark paths so they appear in run-config metadata and dashboards.:contentReference[oaicite:5]{index=5}

## Decision Log

- Decision: Treat `ingredient-parser-nlp` as the baseline parser backend and add `quantulum3` as an additional selectable backend (plus a hybrid fallback mode), rather than replacing the existing parser.
  Rationale: The user benchmarks permutations and explicitly wants new tools to be new options when they overlap existing capabilities.
  Date/Author: 2026-02-25 / ChatGPT

- Decision: The default “missing unit policy” becomes `null` (no unit) when a numeric quantity exists but no unit is present; additionally provide `each` and `legacy_medium` as explicit options.
  Rationale: Priority 4 explicitly recommends unit null and notes this is safe with the current staging schema; `each` may help downstream “countable item” logic; `legacy_medium` is needed for benchmarking and backwards-compat comparisons.:contentReference[oaicite:6]{index=6}
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Use `ftfy` as an optional ingredient-line text “fixer” step in pre-normalization (toggleable), even though the broader cleaning pipeline already does some normalization.
  Rationale: Priority 4 recommends `ftfy` for this area, and the user wants overlapping tools to exist as options for benchmarking, not as replacements.:contentReference[oaicite:8]{index=8}:contentReference[oaicite:9]{index=9}
  Date/Author: 2026-02-25 / ChatGPT

- Decision: Preserve package size details by hoisting them into `note` on ingredient lines (as a deterministic string) without requiring schema changes.
  Rationale: Priority 4 explicitly calls this out, and the output model already has `note` for ingredient lines.:contentReference[oaicite:10]{index=10}
  Date/Author: 2026-02-25 / ChatGPT

## Outcomes & Retrospective

Plan authored; implementation has not started yet. When complete, ingredient parsing should be more robust to common real-world formatting, and benchmarking should be able to compare parser/normalizer permutations without removing any existing capability.

## Context and Orientation

This repository is a recipe ingestion pipeline. A “RecipeCandidate” is extracted from a source (EPUB/PDF/Text/etc). Staging converts candidates into “Draft v1” outputs, including ingredient line objects.

Ingredient parsing happens in `cookimport/parsing/ingredients.py`. The current implementation uses the external library `ingredient-parser-nlp` (`parse_ingredient(..., string_units=True)`) and returns a normalized dict/model with `quantity_kind` values such as `exact`, `approximate`, `unquantified`, and `section_header`. The docs summary notes a key semantic debt: when a parsed amount has no unit, the parser defaults the unit to `"medium"`. Tests live in `tests/test_ingredient_parser.py`.:contentReference[oaicite:12]{index=12}

Staging conversion calls `parse_ingredient_line` when building draft outputs (`cookimport/staging/draft_v1.py`), and the output `StepIngredientLineOut` includes fields such as `raw_text`, `note`, and `preparation` (so we can store package size and repaired tokens).:contentReference[oaicite:14]{index=14}

The staging contract allows unresolved unit IDs to be null, preserving raw unit text separately, and enforces that unquantified lines have `input_qty=null` and `input_unit_id=null`. This supports a safe fix for “missing unit” without inventing `"medium"` as a unit.

Priority 4 requires three main improvements: (1) more aggressive pre-normalization before parsing (including “packaging patterns”); (2) deterministic post-parse validation and repair rules; and (3) removing the “missing unit defaults to medium” behavior, with better deterministic alternatives (unit null by default; optional `"each"` placeholder).:contentReference[oaicite:16]{index=16}

This plan also must incorporate the libraries/tools called out for this priority: `ftfy` (Priority 4), plus `quantulum3` and `pint` (secondary for Priority 4, primary for a later time/yield/unit effort). They must be integrated as selectable options, not replacements.:contentReference[oaicite:17]{index=17}

Finally, because the project treats new “processing options” as first-class RunSettings that appear in run-config reports and dashboards, any new ingredient parsing knobs must be wired through all required surfaces (definition/selection, runtime propagation, analytics persistence, and both execution lanes).:contentReference[oaicite:18]{index=18}

## Plan of Work

We will implement Priority 4 in five milestones, each independently verifiable.

Milestone 1 (“Dependencies + prototyping”) adds the new libraries and proves we can parse representative strings using their public APIs. We will not change production behavior yet; this reduces risk.

Milestone 2 (“Knobs + plumbing”) adds RunSettings knobs so the new libraries and behaviors can be enabled/disabled per run. We will confirm these knobs appear in run-config summaries/hashes in stage and prediction-generation (benchmark) flows.

Milestone 3 (“Pre-normalization + packaging hoist”) implements aggressive pre-normalization before the existing parser runs, including packaging pattern rewriting and storing package size in `note`.

Milestone 4 (“Post-parse validation/repair + missing-unit policy”) adds deterministic repair rules and removes the default `"medium"` unit, replacing it with the selected missing-unit policy. We keep legacy medium behavior as an explicit benchmark option.

Milestone 5 (“Alternative backends”) implements `quantulum3` as an optional parsing backend/fallback and `pint` as an optional unit canonicalization backend. These are selectable, so the baseline remains available.

At the end, we update docs and tests, and we validate via `pytest` plus at least one small “parse ingredient lines” script run.

## Concrete Steps

All commands below are written as if run from the repository root.

### Milestone 1: Dependencies + prototyping (safe, no production behavior changes)

1) Create a new git branch.

    git checkout -b feat/priority4-ingredient-parsing

2) Add dependencies to `pyproject.toml` and lockfile.

   This repo uses `pyproject.toml` for dependencies (the docs summary references it as the source of truth).:contentReference[oaicite:19]{index=19}

   Use the repo’s existing dependency workflow:

   - If the repo uses Poetry:

       poetry add ftfy quantulum3 pint

   - If the repo uses pip/uv with `pyproject.toml`:

       uv add ftfy quantulum3 pint

   - If neither applies, edit `pyproject.toml` manually and then run the repo’s lock/update command (check README or `make` targets).

3) Verify imports quickly.

    python -c "import ftfy; import quantulum3; import pint; print('ok')"

4) Prototype `ftfy` on a couple likely failure strings.

    python - <<'PY'
    from ftfy import fix_text
    samples = [
        "2\u20133 onions",          # en dash
        "1 (14\u2011ounce) can",    # non-breaking hyphen
        "1\u20444 cup sugar",       # fraction slash 1/4
    ]
    for s in samples:
        print("IN: ", s)
        print("OUT:", fix_text(s))
        print()
    PY

   Acceptance: output prints without exceptions, and “weird” characters are normalized into reasonable Unicode.

5) Prototype `quantulum3` parsing on the packaging-size substrings and simple units.

    python - <<'PY'
    from quantulum3 import parser
    samples = [
        "14-ounce",
        "14 oz",
        "400g",
        "1 1/2 cups",
        "2 tbsp",
        "3 x 400g tins tomatoes",
    ]
    for s in samples:
        qs = parser.parse(s)
        print("IN:", s)
        for q in qs[:3]:
            # Print a conservative subset of fields; exact object shape can vary by version.
            print("  ", q)
        print()
    PY

   Acceptance: for at least “14 oz”, “400g”, and “2 tbsp”, `quantulum3` returns a parsed quantity with a unit.

6) Prototype `pint` parsing/canonicalization.

    python - <<'PY'
    import pint
    ureg = pint.UnitRegistry()
    # Define common cooking aliases if pint doesn't recognize them.
    # Only define if missing, so reruns are safe.
    for definition in [
        "tbsp = tablespoon",
        "tsp = teaspoon",
        "oz = ounce",
        "fl_oz = fluid_ounce",
    ]:
        try:
            ureg.define(definition)
        except Exception:
            pass
    samples = ["1 tbsp", "2 tsp", "14 oz", "400 g", "1 cup"]
    for s in samples:
        try:
            q = ureg.parse_expression(s)
            print("IN:", s, "->", q)
        except Exception as e:
            print("IN:", s, "-> ERROR:", e)
    PY

   Acceptance: at least “14 oz” and “400 g” parse successfully. If “tbsp/tsp” fail without aliases, confirm that the alias definitions fix them.

Record anything surprising in `Surprises & Discoveries` (for example, if quantulum3’s API differs from assumptions, or pint needs more alias definitions).

### Milestone 2: Add RunSettings knobs and wire them through stage + prediction-generation

We are adding new processing options, so we must follow the repo’s pipeline-option wiring checklist: define in `RunSettings`, ensure interactive surfaces show it, wire through stage and benchmark paths, and ensure run-config metadata shows it in reports/dashboards.:contentReference[oaicite:20]{index=20}

1) Add new knobs to `cookimport/config/run_settings.py`.

   Add fields (names are prescriptive; do not bikeshed so configs remain stable):

   - `ingredient_text_fix_backend`: `"none"` or `"ftfy"` (default `"none"`).
   - `ingredient_pre_normalize_mode`: `"legacy"` or `"aggressive_v1"` (default `"legacy"` initially; we’ll flip default after tests are in place).
   - `ingredient_packaging_mode`: `"off"` or `"regex_v1"` (default `"off"` initially).
   - `ingredient_parser_backend`: `"ingredient_parser_nlp"` or `"quantulum3_regex"` or `"hybrid_nlp_then_quantulum3"` (default `"ingredient_parser_nlp"`).
   - `ingredient_unit_canonicalizer`: `"legacy"` or `"pint"` (default `"legacy"`).
   - `ingredient_missing_unit_policy`: `"legacy_medium"` or `"null"` or `"each"` (default `"legacy_medium"` initially; we’ll flip default later).

   Add UI metadata (`ui_label`, `ui_help`, and choices) so the interactive editor can present them. The docs summary notes that new per-run toggles live in `cookimport/config/run_settings.py` and the interactive editor reads metadata from there.:contentReference[oaicite:21]{index=21}

   Ensure the canonical serialization/hashing and summary ordering includes these fields, so they appear in `run_config_hash` and `run_config_summary` (these are key for benchmarking and dashboards).:contentReference[oaicite:22]{index=22}

2) Ensure interactive editor surfaces show the new knobs.

   Verify in:
   - `cookimport/cli_ui/run_settings_flow.py`
   - `cookimport/cli_ui/toggle_editor.py`

   If the editor cannot represent enumerated choices, fall back to a “string choice prompt” (Questionary select) for those fields. Keep booleans only if forced by UI constraints; the user explicitly wants multiple options for benchmarking.

3) Runtime propagation.

   Identify where `RunSettings` is passed into staging conversion. The staging conversion path calls `parse_ingredient_line` from `cookimport/staging/draft_v1.py` when building draft outputs.:contentReference[oaicite:23]{index=23}

   Plumb the effective RunSettings (or a small “ingredient parsing options” struct derived from it) into ingredient parsing code. Concretely:

   - Update `cookimport/parsing/ingredients.py:parse_ingredient_line(...)` to accept an optional `settings: RunSettings | None` (or `options: IngredientParsingOptions | None`).
   - In `cookimport/staging/draft_v1.py`, pass the RunSettings/options when calling `parse_ingredient_line`.

   Use `rg "parse_ingredient_line\\(" -n cookimport` to find all call sites and update them consistently.

4) Prediction-generation / benchmark lane parity.

   Ensure the same RunSettings options are available when generating prediction artifacts for benchmarks, via `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)` and related planners. The checklist explicitly calls out parity between `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` planning/execution paths.:contentReference[oaicite:24]{index=24}

5) Analytics persistence verification.

   Run one small stage run (or any run that produces a report) and verify the report contains:

   - `runConfig` JSON with the new keys
   - `runConfigHash`
   - `runConfigSummary` that includes the new fields

   If the report is produced under `data/output/<timestamp>/...`, open the generated `*.excel_import_report.json` and confirm.

Acceptance: After this milestone, you can toggle the new ingredient parsing knobs in RunSettings and see them appear in run-config metadata, even though the parsing behavior is still “legacy”.

### Milestone 3: Implement pre-normalization and packaging hoist (aggressive_v1)

Priority 4 requires pre-normalizing ingredient lines more aggressively before the parser, including dash folding, parenthesis whitespace normalization, fraction/range spacing normalization, and packaging patterns, with package size hoisted into `note` while leaving container unit as the unit.:contentReference[oaicite:25]{index=25}

1) In `cookimport/parsing/ingredients.py`, implement:

   - `dash_fold(text: str) -> str` to map `–` and `—` (and any other dash-like chars you find in your corpus) to `-`.
   - `normalize_parentheses_space(text: str) -> str` to enforce `"( ... )"` spacing deterministically.
   - `normalize_fraction_and_range_spacing(text: str) -> str` to normalize:
     - `1  /  2` → `1/2`
     - `2 - 3` and `2–3` → `2-3`
     - `1 1/2` stays `1 1/2` (do not collapse into `1.5` at this stage; let parser handle).
   - `extract_packaging_note(text: str) -> tuple[str, str | None]` that recognizes high-value packaging patterns like:
     - `1 (14-ounce) can tomatoes`
     - `2 (14 oz) cans tomatoes`
     - `3 x 400g tins tomatoes`
     and returns:
       - a rewritten string suitable for the downstream parser (parenthetical removed / “x 400g” removed),
       - and a package-size note string (e.g., `pkg: 14-ounce`, `pkg: 400g`).

   Keep this conservative: if a match is ambiguous (for example, no actual ingredient text remains after removing packaging info), do not rewrite; just return the original string and no packaging note.

2) Integrate into `parse_ingredient_line`:

   - If `ingredient_text_fix_backend == "ftfy"`, run `ftfy.fix_text` first.
   - If `ingredient_pre_normalize_mode == "aggressive_v1"`, apply dash/parenthesis/fraction/range normalization.
   - If `ingredient_packaging_mode == "regex_v1"`, run packaging extraction and carry the extracted note forward.

3) Merge the packaging note into the parsed output’s `note` field.

   The output model already includes `note` for ingredient lines.

   Use a deterministic join rule such as:
   - if existing note empty: note = packaging_note
   - else: note = existing_note + "; " + packaging_note

Acceptance: With knobs enabled, calling `parse_ingredient_line("1 (14-ounce) can tomatoes")` yields a result whose note includes `14-ounce` and whose unit reflects `can` (not `14-ounce`). Also add unit tests proving it.

### Milestone 4: Post-parse validation + repair rules and missing-unit policy

Priority 4 requires deterministic “self-correcting” repair rules after parsing, plus removal of the default `"medium"` unit when unit is missing.:contentReference[oaicite:27]{index=27}

1) Add a post-parse repair stage inside `parse_ingredient_line` (or a helper like `repair_parsed_ingredient(parsed: ParsedIngredient, raw_text: str, ...) -> ParsedIngredient`).

   Implement the repair rules exactly:

   a) Quantity sanity.

   If the parser’s “quantity” is non-numeric and not in the allowed “approximate token set” (at least: `pinch`, `to taste`, `as needed`), then:
   - set `input_qty` to null,
   - move that token/phrase into `note` (append, do not overwrite).:contentReference[oaicite:28]{index=28}

   If the non-numeric quantity *is* in the approximate token set, still set `input_qty` to null and store the token in `note`. Keep `quantity_kind` as `unquantified` (to satisfy staging constraints).

   b) Unit sanity.

   If quantity is missing (null) and the parsed unit looks like an ingredient word (example: `salt`), treat it as the ingredient name and set unit to null. A robust deterministic heuristic is:

   - If `input_qty is None` AND `name is empty/too short` AND `raw_unit_text is not None`,
     then set `name = raw_unit_text` and `raw_unit_text = None`.:contentReference[oaicite:30]{index=30}

   c) Abbreviation normalization.

   Normalize common abbreviations upstream and/or in repair:
   - tsp, tbsp, oz (and other obvious ones you already support)

   Do not remove existing behavior; this is additional normalization. (This can also feed into the optional `pint` canonicalizer later.):contentReference[oaicite:31]{index=31}

   d) Name fallback.

   If the parsed name is empty or too short after repairs, fall back deterministically:
   - Option 1: a simpler regex parser (extract leading quantity and unit, remainder is name).
   - Option 2: mark as “unparsed” but preserve `raw_text` and put the whole text into name so the ingredient line is still visible downstream.:contentReference[oaicite:32]{index=32}

   Keep it simple and deterministic: the fallback must never drop the original line.

2) Implement missing-unit policy (removing “medium” default).

   The current docs note the behavior: “if parsed amount has no unit, unit defaults to 'medium'”. Priority 4 says this is wrong and poisons unit resolution, and recommends better deterministic options: unit null by default; treat size adjectives as note; optional `"each"` placeholder for countables.:contentReference[oaicite:33]{index=33}

   Implement this as a policy switch:

   - `ingredient_missing_unit_policy == "null"`:
     If `input_qty` exists and there is no unit, set unit to null and keep quantity.
   - `ingredient_missing_unit_policy == "each"`:
     If `input_qty` exists and there is no unit, set unit to `"each"` (store as `raw_unit_text="each"` or whatever the code uses) and keep quantity.
   - `ingredient_missing_unit_policy == "legacy_medium"`:
     Preserve the prior behavior for benchmarking/back-compat.

   Also implement the size-adjective handling independent of policy:
   - If unit is one of `small`, `medium`, `large`, move it to `note` (or `preparation` if that field is the conventional place in this code) and set unit to null, keeping quantity and name.

3) Update `tests/test_ingredient_parser.py` to cover:

   - “2 onions” no longer yields unit `"medium"` when policy is `"null"` or `"each"`.
   - “2 medium onions” yields note containing “medium” and unit is null (or each if you choose to apply each to all missing units).
   - “1 (14-ounce) can tomatoes” yields unit can, note includes `14-ounce`.
   - “salt” yields name salt, qty null, unit null (not unit=salt).
   - At least one “non-numeric quantity token” example gets moved into note and qty becomes null.

Acceptance: All new/updated tests pass. A quick manual call to `parse_ingredient_line` on the above examples produces outputs consistent with the acceptance descriptions.

### Milestone 5: Alternative backends and unit canonicalization options (quantulum3 + pint)

This milestone satisfies the “new tools as options” requirement for overlapping capabilities: `quantulum3` and `pint` are integrated as selectable backends, not replacements.:contentReference[oaicite:34]{index=34}

1) Add a `quantulum3` parsing backend.

   In `cookimport/parsing/ingredients.py`, implement:

   - `parse_with_quantulum3(line: str) -> ParsedIngredientLike`

   The deterministic approach:

   - Use `quantulum3.parser.parse(line)` to find the first quantity+unit occurrence.
   - If found, treat that as `input_qty` and `raw_unit_text`.
   - Remove that substring from the line (using the quantity’s span if available, otherwise string replace on the matched surface) and treat the remaining text as the ingredient name.
   - Preserve parentheses content and packaging notes by relying on the pre-normalization stage (Milestone 3) and then repairing notes (Milestone 4).

   Integrate behind `ingredient_parser_backend`:

   - `"quantulum3_regex"` uses quantulum3 backend only.
   - `"hybrid_nlp_then_quantulum3"` calls the existing `ingredient-parser-nlp` path first, runs post-parse repairs, and if the result is still “bad” (empty/too-short name, non-numeric quantity, or other repair failure), falls back to quantulum3 backend.

   This ensures the existing backend remains available and default, but quantulum3 can be benchmarked.

2) Add a `pint` unit canonicalizer option.

   Implement a helper:

   - `canonicalize_unit_with_pint(raw_unit_text: str) -> str`

   Keep it conservative:

   - If pint cannot parse the unit, return the original string.
   - Maintain a small list of alias definitions for cooking abbreviations (tsp/tbsp/oz/fl oz) as shown in prototyping.
   - Only canonicalize units that are clearly measurement units (mass/volume/length) and leave container units (“can”, “tin”, “clove”) untouched.

   Integrate behind `ingredient_unit_canonicalizer`:
   - `"legacy"` preserves existing behavior.
   - `"pint"` runs pint canonicalization after abbreviation normalization and before unit resolution.

3) Add tests that prove the options are selectable.

   Add at least one parametrized test that runs the same input line through:
   - baseline backend,
   - quantulum3 backend,
   - hybrid backend,
   and asserts that all return a non-empty ingredient name and preserve `raw_text`.

Acceptance: Tests confirm both new options run without error and are selectable via RunSettings.

## Validation and Acceptance

Run these validations from the repo root:

1) Focused ingredient parser tests.

    pytest -q tests/test_ingredient_parser.py

   Expectation: all tests in this file pass (update the expected values where “medium” used to appear).

2) A small manual smoke check via Python.

    python - <<'PY'
    from cookimport.parsing.ingredients import parse_ingredient_line
    # If parse_ingredient_line now takes settings/options, build a default settings object
    # and pass it in as appropriate. The goal is to exercise the new behavior.
    samples = [
        "2 onions",
        "2 medium onions",
        "1 (14-ounce) can tomatoes",
        "3 x 400g tins tomatoes",
        "salt",
    ]
    for s in samples:
        print(s, "->", parse_ingredient_line(s))
    PY

   Expectation: No `"medium"` default appears for “2 onions” when missing-unit policy is set to `null` or `each`. Packaging size appears in `note`. “salt” is treated as name.

3) Run-config metadata contains new knobs (stage and/or prediction-generation).

   Run a minimal stage conversion (use whatever small input file you have) and confirm the produced report JSON includes the new run-config fields. This is critical for benchmarking permutations.

   If you have no handy source file, use the smallest “text importer” fixture in the repo, or create a minimal text file with one recipe.

   Evidence to capture in `Artifacts and Notes`:
   - the `runConfigSummary` string showing the new knobs and their values,
   - one parsed ingredient line in the output that demonstrates packaging-note + missing-unit policy.

## Idempotence and Recovery

- Dependency additions are safe to rerun; they should be no-ops once the lockfile is updated.
- The new parsing behaviors are guarded by explicit RunSettings knobs. If a regression appears in downstream stages, you can recover quickly by switching to:
  - `ingredient_pre_normalize_mode="legacy"`
  - `ingredient_packaging_mode="off"`
  - `ingredient_parser_backend="ingredient_parser_nlp"`
  - `ingredient_unit_canonicalizer="legacy"`
  - `ingredient_missing_unit_policy="legacy_medium"`
  and rerunning the same import to reproduce baseline behavior for comparison.

- If the new parser changes cause test churn, land changes as a small sequence of “perfect commits”:
  1) dependencies + prototypes,
  2) RunSettings + plumbing (no behavior change),
  3) new behavior gated behind knobs with updated tests,
  4) flip defaults (with tests updated).

## Artifacts and Notes

As you implement, paste short evidence snippets here (indented, no nested code fences). Examples to capture:

- The updated `pytest -q tests/test_ingredient_parser.py` output showing all passing.
- The `parse_ingredient_line` smoke-check output for the five sample lines.
- One excerpt from a stage report JSON showing `runConfigSummary` includes the new ingredient knobs.

## Interfaces and Dependencies

### New external dependencies (must be added)

- `ftfy` (ingredient-line text fixing / mojibake repair option).:contentReference[oaicite:35]{index=35}
- `quantulum3` (alternate quantity/unit extraction backend; optional fallback).:contentReference[oaicite:36]{index=36}
- `pint` (optional unit canonicalization backend).:contentReference[oaicite:37]{index=37}
- Existing dependency to keep: `ingredient-parser-nlp` remains the baseline backend (do not remove).:contentReference[oaicite:38]{index=38}

### New RunSettings fields (must exist after Milestone 2)

In `cookimport/config/run_settings.py`, define the following fields, with validation and UI metadata:

- `ingredient_text_fix_backend: Literal["none", "ftfy"]`
- `ingredient_pre_normalize_mode: Literal["legacy", "aggressive_v1"]`
- `ingredient_packaging_mode: Literal["off", "regex_v1"]`
- `ingredient_parser_backend: Literal["ingredient_parser_nlp", "quantulum3_regex", "hybrid_nlp_then_quantulum3"]`
- `ingredient_unit_canonicalizer: Literal["legacy", "pint"]`
- `ingredient_missing_unit_policy: Literal["legacy_medium", "null", "each"]`

They must appear in `run_config_summary` and `run_config_hash` and therefore be visible in stage/benchmark reporting surfaces.:contentReference[oaicite:39]{index=39}

### Parsing function interface expectations

In `cookimport/parsing/ingredients.py`:

- `parse_ingredient_line` must accept a way to pass the settings (either the whole `RunSettings` or a dedicated `IngredientParsingOptions` derived from it). It must be possible to select:
  - the baseline `ingredient-parser-nlp` path,
  - the new `quantulum3` path,
  - a hybrid fallback path.

- The parsed ingredient line output must continue to preserve `raw_text` and support `note` so packaging size and repaired tokens are not lost.

### Docs that must be updated

Search and update the parsing documentation that currently mentions the `"medium"` default and ingredient parsing behavior. The docs summary explicitly describes this behavior, so the underlying docs should be brought into alignment once defaults are flipped.:contentReference[oaicite:41]{index=41}

At minimum, update:
- `docs/04-parsing/04-parsing_readme.md` (or wherever the “Ingredient Parsing (`cookimport/parsing/ingredients.py`)” section lives)
to describe:
- packaging note hoisting,
- post-parse repair rules,
- missing-unit policy default (null) and the available options (each, legacy_medium).

## Plan change log

(When you revise this plan during implementation, append a dated note here describing what changed and why.)