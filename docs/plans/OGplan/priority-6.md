---
summary: "ExecPlan for Priority 6: deterministic time/temperature/yield upgrades aligned to current parser and staging behavior."
read_when:
  - "When implementing docs/plans/priority-6.md"
  - "When changing instruction time/temperature parsing behavior"
  - "When changing yield fields in draft-v1 outputs or run-setting/CLI surfaces"
---

# Build Priority 6: Deterministic Time, Temperature, and Yield Upgrades


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


After this change, staged recipe outputs will keep legacy-safe behavior by default while exposing deterministic upgrades for three areas that currently underperform:

1. richer instruction time extraction (strategy-based totals, not always sum-all),
2. richer temperature extraction (multiple temperatures per step, recipe-level `max_oven_temp_f`),
3. centralized yield extraction/parsing into `yield_units`, `yield_phrase`, `yield_unit_name`, and `yield_detail`.

User-visible outcomes:

1. Recipe drafts can include `max_oven_temp_f` and better structured yield fields instead of only `yield_phrase` passthrough plus hardcoded defaults.
2. Step time rollups into `cook_time_seconds` become configurable and benchmarkable.
3. Backend/strategy selection is explicit in run settings and CLI so legacy-vs-upgrade comparisons are reproducible.

This priority remains deterministic and keeps recipe codex-farm parsing off.


## Progress


- [x] (2026-02-27_22.24.37) Ran docs bootstrap check (`bin/docs-list`/`docs:list` unavailable here) and loaded required docs: `docs/AGENTS.md`, `docs/PLANS.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/05-staging/05-staging_readme.md`.
- [x] (2026-02-27_22.24.37) Audited current Priority 6 surfaces in code: `cookimport/parsing/instruction_parser.py`, `cookimport/staging/draft_v1.py`, importer yield extraction (`plugins/text.py`, `plugins/excel.py`, `plugins/epub.py`, `plugins/pdf.py`), `cookimport/config/run_settings.py`, and current tests.
- [x] (2026-02-27_22.24.37) Replaced stale `docs/plans/priority-6.md` with this code-audited, current-state ExecPlan.
- [ ] Milestone 0: capture baseline outputs/tests for current parser + staging contracts.
- [ ] Milestone 1: implement parser contract upgrade (multi-temperature extraction + strategy-based time totals) with full backward compatibility.
- [ ] Milestone 2: implement centralized yield candidate/scoring/parsing module (legacy + scored modes).
- [ ] Milestone 3: integrate Priority 6 outputs into `draft_v1` (`max_oven_temp_f`, yield fields, strategy-aware cook-time rollup).
- [ ] Milestone 4: wire run settings + CLI + prediction-generation surfaces for Priority 6 knobs.
- [ ] Milestone 5: add optional dependency backends/extras (`quantulum3`, `pint`, `isodate`, plus schema helpers) with fail-fast guards.
- [ ] Milestone 6: add tests, stage evidence, and docs updates; record final acceptance artifacts.


## Surprises & Discoveries


- Observation: Active and archived Priority 6 plans were identical and stale.
  Evidence: `docs/plans/priority-6.md` and `docs/plans/OGplan/priority-6.md` matched and both contained old citation placeholders.

- Observation: The old plan referenced `BIG PICTURE UPGRADES.md`, but that file is not present in this repo.
  Evidence: repository root listing contains no such file.

- Observation: Current instruction parsing is single-backend regex with fixed behavior.
  Evidence: `cookimport/parsing/instruction_parser.py` currently has no options surface; `total_time_seconds` is always sum of extracted durations and only the first temperature match is returned.

- Observation: Current `draft_v1` sets yield defaults but does not compute recipe-level max oven temp.
  Evidence: `cookimport/staging/draft_v1.py` sets `yield_units=1`, `yield_phrase=candidate.recipe_yield`, `yield_unit_name=None`, `yield_detail=None`, and does not emit `max_oven_temp_f`.

- Observation: Yield detection/parsing is importer-local and inconsistent.
  Evidence: separate yield handlers exist in `plugins/text.py` (`_extract_yield_phrase`), `plugins/epub.py` (`_yield_phrase`), and PDF block-feature paths, with no shared yield parsing/scoring module.

- Observation: There are no Priority 6 run settings or optional dependency extras yet.
  Evidence: `RunSettings` in `cookimport/config/run_settings.py` has no `p6_*` fields; `pyproject.toml` has no `priority6`/`htmlschema` extras.

- Observation: `max_oven_temp_f` currently appears only in tagging signals, derived ad hoc from step temps.
  Evidence: `cookimport/tagging/signals.py` computes `max_oven_temp_f` from step `temperature`/`temperature_unit`, but this is not persisted in draft recipe output.


## Decision Log


- Decision: Rewrite Priority 6 plan from current repository behavior instead of carrying forward stale assumptions.
  Rationale: The previous draft was not trustworthy as an implementation guide because it referenced missing sources and outdated contracts.
  Date/Author: 2026-02-27_22.24.37 / Codex GPT-5

- Decision: Keep legacy behavior selectable and default-safe during rollout.
  Rationale: Current parser/staging outputs are depended on by existing tests and downstream tooling; upgrades should be benchmarkable without forced regressions.
  Date/Author: 2026-02-27_22.24.37 / Codex GPT-5

- Decision: Land deterministic regex-based contract upgrades before optional library backends.
  Rationale: This de-risks integration and gives a clean baseline before adding dependency-conditioned permutations.
  Date/Author: 2026-02-27_22.24.37 / Codex GPT-5

- Decision: Centralize yield extraction in parsing/staging instead of leaving importer-local phrase extraction as the primary source.
  Rationale: Priority 6 needs consistent DB-aligned yield outputs across importer families.
  Date/Author: 2026-02-27_22.24.37 / Codex GPT-5


## Outcomes & Retrospective


Pending implementation.

Target completion state:

- Parser can expose richer time/temperature metadata while preserving old fields.
- Staged draft outputs include deterministic `max_oven_temp_f` and better yield field population.
- Run settings + CLI expose the full permutation surface for benchmarking.
- Legacy behavior remains reproducible through explicit settings.


## Context and Orientation


### Current instruction parser contract

`cookimport/parsing/instruction_parser.py` currently provides:

- `parse_instruction(text) -> InstructionMetadata`
- `parse_instructions(steps)` batch helper
- regex-based duration extraction (`seconds/minutes/hours/days`, ranges as midpoint)
- regex-based temperature extraction (first match only)

Current `InstructionMetadata` fields:

- `total_time_seconds`
- `time_items` (`seconds`, `original_text`)
- `temperature`
- `temperature_unit`
- `temperature_text`

No parser options/backends/strategies are currently exposed.

### Current staging behavior

`cookimport/staging/draft_v1.py:recipe_candidate_to_draft_v1(...)` currently:

- uses `parse_instruction` per step,
- emits per-step `time_seconds`, `temperature`, `temperature_unit` when present,
- sums step `total_time_seconds` into `recipe.cook_time_seconds` when `candidate.cook_time` is missing,
- sets recipe yield fields as:
  - `yield_units = 1`
  - `yield_phrase = candidate.recipe_yield`
  - `yield_unit_name = None`
  - `yield_detail = None`

There is no recipe-level `max_oven_temp_f` emitted by staging.

### Current yield extraction sources

Yield phrase extraction is currently fragmented by importer:

- text importer line regex extraction (`plugins/text.py`),
- EPUB helper (`plugins/epub.py`),
- PDF block signal path (`plugins/pdf.py`),
- plus any structured source fields already mapped into `RecipeCandidate.recipe_yield`.

There is no centralized scored candidate selector or standardized parsing to numeric/unit/detail fields.

### Current run settings/dependency surfaces

`cookimport/config/run_settings.py` has no Priority 6-specific settings. Stage and prediction-generation pipelines cannot currently select time/yield/temperature backends for this priority.

`pyproject.toml` currently has no `priority6`/`htmlschema` extras.

### Current test coverage

Existing focused coverage:

- `tests/parsing/test_instruction_parser.py` validates current sum-all and first-temperature behavior.
- `tests/ingestion/test_text_importer.py` validates basic yield phrase extraction for split text fixture.
- staging tests (`tests/staging/test_draft_v1_*`) focus on ingredient/staging contract normalization, not Priority 6 output fields.

Priority 6 lacks dedicated tests for:

- multi-temperature capture,
- strategy-based time totals,
- centralized yield scoring/parsing,
- staged `max_oven_temp_f` behavior.


## Plan of Work


### Milestone 0: Baseline contracts and evidence

Capture baseline behavior before Priority 6 edits.

Work:

1. Run focused parser/importer/staging tests that represent current contracts.
2. Stage a small fixture with clear yield/time text and keep output snapshots.
3. Record baseline draft fields and parser outputs in `Progress` for before/after comparison.

Acceptance:

- Baseline test status is recorded.
- Baseline run artifact paths are recorded.


### Milestone 1: Parser contract upgrade (deterministic baseline)

Add richer parser output and time strategies while preserving current default behavior.

Work:

1. Extend parser data structures to include all temperature mentions and compatibility fields.
2. Add deterministic time aggregation strategies:
   - `sum_all_v1` (current behavior, default),
   - `max_v1`,
   - `selective_sum_v1` (rule-based exclusion for obvious alternatives/frequency spans).
3. Add oven-like temperature classification helper for recipe-level max calculations.
4. Preserve existing public API behavior when options are omitted.

Acceptance:

- Existing parser tests remain green.
- New parser tests prove multi-temp extraction and strategy differences.


### Milestone 2: Centralized yield extraction/parsing

Create a shared yield pipeline that is deterministic and importer-agnostic.

Work:

1. Add parsing modules for yield candidate collection, scoring, and parsing.
2. Support at least:
   - `legacy_v1` passthrough mode (current behavior parity),
   - `scored_v1` mode (candidate scoring + parsed fields).
3. Apply nutrition false-positive suppression and preserve `yield_phrase` even when numeric parsing fails.
4. Keep handling aligned with DB constraints (`yield_units >= 1`).

Acceptance:

- Unit tests cover common yield forms, range/qualifier handling, and nutrition rejection.


### Milestone 3: Staging integration

Wire parser/yield upgrades into draft output.

Work:

1. In `recipe_candidate_to_draft_v1`, switch from hardcoded yield placeholders to selected yield mode output.
2. Compute and emit recipe-level `max_oven_temp_f` using oven-like temperatures across steps.
3. Keep `cook_time_seconds` fallback based on selected time strategy, with legacy parity via `sum_all_v1`.
4. Preserve existing staging contract constraints for ingredient lines and fallback steps.

Acceptance:

- Staged drafts include expected Priority 6 fields when derivable.
- Legacy mode reproduces baseline behavior.


### Milestone 4: Run settings and pipeline wiring

Expose Priority 6 permutations end-to-end.

Work:

1. Add `p6_*` fields to `RunSettings` with UI metadata.
2. Wire settings through:
   - stage CLI paths,
   - interactive run-settings editor,
   - worker and prediction-generation adapters.
3. Ensure report `runConfig`/hash/summary include new fields.

Acceptance:

- Settings are visible, serializable, and reproducibly applied across stage and prediction-generation flows.


### Milestone 5: Optional backends and extras

Add benchmarkable optional backends with fail-fast dependency checks.

Work:

1. Add extras in `pyproject.toml`:
   - core (`priority6`): `quantulum3`, `pint`, `isodate`
   - schema helper (`htmlschema`): `extruct`, `scrape-schema-recipe`, `pyld`, `recipe-scrapers`
2. Add guarded backend selectors (`regex_v1`, optional backend variants, hybrids where appropriate).
3. Emit actionable errors when a selected backend dependency is missing.

Acceptance:

- Optional backends can be selected only when dependencies are installed, or fail with clear install guidance.


### Milestone 6: Validation, artifacts, and docs

Finish with evidence and docs updates.

Work:

1. Add parser/yield/staging tests for Priority 6 behavior.
2. Add optional metadata debug artifact for benchmark diffs (only when enabled).
3. Update docs for new settings/backends and artifact interpretation.

Acceptance:

- Tests and stage artifacts demonstrate behavior changes.
- Documentation matches implemented contracts.


## Concrete Steps


Run commands from repository root (`/home/mcnal/projects/recipeimport`).

1. Prepare environment.

    source .venv/bin/activate
    python -m pip install -e ".[dev]"

2. Capture focused baseline tests.

    pytest -q tests/parsing/test_instruction_parser.py tests/ingestion/test_text_importer.py tests/staging/test_draft_v1_staging_alignment.py tests/staging/test_draft_v1_lowercase.py tests/staging/test_draft_v1_variants.py

3. Capture baseline stage artifact with current behavior.

    cookimport stage tests/fixtures/serves_multi.txt --out /tmp/priority6-baseline --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown

4. Implement Milestones 1-4 (deterministic core), then run focused verification.

    pytest -q tests/parsing/test_instruction_parser.py tests/parsing/test_yield_extraction.py tests/staging/test_draft_v1_priority6.py tests/llm/test_run_settings.py tests/cli/test_toggle_editor.py

5. Install optional deps and validate optional backends.

    python -m pip install -e ".[priority6,htmlschema]"
    pytest -q tests/parsing/test_instruction_parser.py tests/parsing/test_yield_extraction.py tests/parsing/test_schema_recipe_extract.py

6. Capture side-by-side stage outputs after Priority 6 wiring.

    cookimport stage tests/fixtures/serves_multi.txt --out /tmp/priority6-legacy --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown --p6-yield-mode legacy_v1 --p6-time-total-strategy sum_all_v1
    cookimport stage tests/fixtures/serves_multi.txt --out /tmp/priority6-scored --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown --p6-yield-mode scored_v1 --p6-time-total-strategy selective_sum_v1 --p6-emit-metadata-debug


## Validation and Acceptance


Acceptance is behavior-based.

1. Parser behavior:
   - Legacy path (`sum_all_v1`, regex baseline) matches old outputs.
   - Upgraded path can capture multiple temperatures and strategy-based time totals deterministically.

2. Staging behavior:
   - `recipe.max_oven_temp_f` is emitted when oven-like temperatures exist.
   - Yield fields populate from centralized selection/parsing (`yield_phrase`, `yield_units`, `yield_unit_name`, `yield_detail`).
   - `recipe.cook_time_seconds` remains present and strategy-controlled when recipe-level cook time is missing.

3. Run-settings behavior:
   - New Priority 6 fields appear in run settings UI, CLI, and report `runConfig`.

4. Dependency behavior:
   - Optional backend selection without install fails clearly and points to correct extra.

5. Regression guard:
   - Existing staging/parsing tests unrelated to Priority 6 remain green.


## Idempotence and Recovery


This rollout is additive and reversible.

- Safe rerun: commands can be repeated; stage outputs should target new `--out` roots for comparisons.
- Recovery switch: force legacy behavior via Priority 6 settings (`legacy_v1`, `sum_all_v1`, regex backends).
- Optional backend rollback: switch backend settings back to deterministic built-ins if optional libs regress.
- Keep recipe codex-farm parsing policy unchanged (`llm_recipe_pipeline=off`).


## Artifacts and Notes


Expected new/updated artifacts after Priority 6 implementation:

- draft outputs include richer yield and temperature-derived recipe fields,
- optional metadata debug artifact captures selected candidates, parser strategy/backends, and per-step extraction evidence,
- benchmark evidence surface (`.bench/<workbook>/stage_block_predictions.json`) remains unchanged.

Sample debug record shape (illustrative):

    {
      "recipe_id": "...",
      "p6": {
        "time_total_strategy": "selective_sum_v1",
        "yield_mode": "scored_v1"
      },
      "yield": {
        "selected": {"yield_phrase": "Serves 4", "yield_units": 4}
      },
      "temperature": {
        "max_oven_temp_f": 375
      }
    }


## Interfaces and Dependencies


Expected interfaces after Milestones 1-5.

In `cookimport/parsing/instruction_parser.py`:

    @dataclass
    class InstructionParseOptions:
        time_backend: str = "regex_v1"
        time_total_strategy: str = "sum_all_v1"
        temperature_backend: str = "regex_v1"
        temperature_unit_backend: str = "builtin_v1"
        ovenlike_mode: str = "keywords_v1"

    @dataclass
    class TemperatureItem:
        value: float
        unit: str
        value_f: int
        original_text: str
        is_oven_like: bool

    @dataclass
    class InstructionMetadata:
        total_time_seconds: int | None
        time_items: list[TimeItem]
        temperature: float | None  # compatibility
        temperature_unit: str | None  # compatibility
        temperature_text: str | None  # compatibility
        temperature_items: list[TemperatureItem]

In `cookimport/config/run_settings.py`:

- Add Priority 6 enum/string fields (exact names can follow local style), all with `ui_*` metadata and conservative defaults.

In `cookimport/staging/draft_v1.py`:

- Integrate selected parser/yield options and emit `recipe.max_oven_temp_f`.

Dependencies:

- No mandatory dependency additions for deterministic baseline rollout.
- Optional extras added for advanced backends in Milestone 5.


## Revision Notes


- 2026-02-27_22.24.37 (Codex GPT-5): Replaced stale Priority 6 copy with a code-audited ExecPlan aligned to current parser/staging/run-settings reality, removed invalid citation placeholders, and updated milestones/progress to reflect actual repository state.
