---
summary: "ExecPlan for Priority 4: harden ingredient parsing and remove default 'medium' unit policy safely."
read_when:
  - "When implementing Priority 4 ingredient parsing improvements."
  - "When changing cookimport/parsing/ingredients.py, staging ingredient conversion, or ingredient parser run settings."
---

# Priority 4: Harden ingredient parsing and remove the default `medium` unit

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

After this work, ingredient parsing will be more reliable on real cookbook text and will stop inventing `"medium"` as a default unit for count-based lines like `2 onions`.

User-visible outcomes:

- Packaging lines such as `1 (14-ounce) can tomatoes` keep container unit semantics and preserve package-size detail in `note`.
- Missing-unit lines keep quantity but follow an explicit policy (`null`, `each`, or `legacy_medium`) instead of hidden behavior.
- Clearly bad parse outputs are repaired deterministically without dropping `raw_text`.
- New parsing options are selectable via run settings so benchmark permutations stay possible.

## Progress

- [x] (2026-02-25) Initial Priority-4 ExecPlan drafted.
- [x] (2026-02-28 21:20Z) Current-state audit completed against live code/docs/tests.
- [x] (2026-02-28 21:22Z) Baseline check run: `pytest -q tests/parsing/test_ingredient_parser.py` exits 0 in `.venv`.
- [x] (2026-02-28 03:12Z) Added optional dependency extra `ingredientparse` (`ftfy`, `quantulum3`, `pint`) in `pyproject.toml`.
- [x] (2026-02-28 03:18Z) Added Priority-4 run settings (`ingredient_*`) in `RunSettings`, adapter mappings, and stage/benchmark/ingest CLI wiring.
- [x] (2026-02-28 03:25Z) Implemented pre-normalization modes, packaging extraction hoist, backend selection, and unit canonicalization/missing-unit policies in `cookimport/parsing/ingredients.py`.
- [x] (2026-02-28 03:31Z) Threaded ingredient parser run-config options through draft conversion (`draft_v1.py` + `writer.py` + stage/merge/labelstudio callsites).
- [x] (2026-02-28 03:38Z) Updated parser/staging/run-settings tests for new behavior and option propagation.
- [x] (2026-02-28 03:41Z) Updated parsing/staging/CLI/config docs to match Priority-4 runtime behavior.

## Surprises & Discoveries

- Observation: `ingredient-parser-nlp` already preserves container-unit semantics for common package lines (`1 (14-ounce) can tomatoes`) by returning multiple amounts; explicit regex hoist is still useful to make package-size detail deterministic in `note`.
  Evidence: manual parse probes in `.venv` showed primary unit `can` plus secondary amount `14 ounces`; regex mode now emits `note='pkg: 14-ounce'`.

- Observation: Section-header regression surfaced when parser returned no `name` for one-word headers like `Garnish`.
  Evidence: `tests/parsing/test_ingredient_parser.py::TestSectionHeaders` failed until heuristic keyword fallback was added in `_is_section_header_heuristic(...)`.

- Observation: Run-config threading for ingredient parser knobs required wiring at draft-write boundaries, not importer boundaries.
  Evidence: parser options are consumed during `recipe_candidate_to_draft_v1(...)`, so stage/merge/labelstudio writer callsites needed explicit `ingredient_parser_options=run_config` plumbing.

## Decision Log

- Decision: Keep `ingredient-parser-nlp` as the baseline backend and add any new parser logic as selectable options.
  Rationale: preserves deterministic baseline and supports benchmark permutations.
  Date/Author: 2026-02-25 / ExecPlan author

- Decision: Missing-unit handling will be explicit policy, with default target behavior `null` and optional `each` + `legacy_medium`.
  Rationale: removes hidden semantic drift while preserving backwards-compat comparison mode.
  Date/Author: 2026-02-25 / ExecPlan author

- Decision: Priority-4 rollout should be staged behind settings first, then defaults flipped only after tests/docs are aligned.
  Rationale: minimizes regressions in stage and benchmark runs.
  Date/Author: 2026-02-28 / Plan refresh

- Decision: Set default `ingredient_missing_unit_policy` to `null` in `RunSettings`.
  Rationale: Priority-4 acceptance requires removing implicit `medium` from default behavior while retaining `legacy_medium` for back-compat benchmarking.
  Date/Author: 2026-02-28 / implementation

- Decision: Keep optional backends/normalizers soft-failable (graceful fallback) when optional deps are not installed.
  Rationale: preserves deterministic baseline behavior in environments that do not install `ingredientparse` extras.
  Date/Author: 2026-02-28 / implementation

## Outcomes & Retrospective

Priority-4 implementation is complete as of 2026-02-28:

- Default missing-unit behavior is now explicit (`ingredient_missing_unit_policy=null`) and no longer invents `medium`.
- Legacy behavior remains reproducible via `ingredient_missing_unit_policy=legacy_medium`.
- Packaging hoist (`regex_v1`) preserves container units and records package detail in `note`.
- Parser repair and backend selection options are run-config selectable and threaded through stage + benchmark prediction generation imports.
- Focused verification passed in `.venv`:
  - `pytest -q tests/parsing/test_ingredient_parser.py tests/staging/test_draft_v1_variants.py tests/llm/test_run_settings.py`
  - `pytest -q tests/staging/test_run_manifest_parity.py`
  - `pytest -q tests/parsing tests/staging`

## Context and Orientation

Current relevant modules:

- [ingredients.py](/home/mcnal/projects/recipeimport/cookimport/parsing/ingredients.py): parser entrypoint and normalization logic.
- [draft_v1.py](/home/mcnal/projects/recipeimport/cookimport/staging/draft_v1.py): calls `parse_ingredient_line` while building staged output.
- [run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py): canonical settings model for pipeline options.
- [test_ingredient_parser.py](/home/mcnal/projects/recipeimport/tests/parsing/test_ingredient_parser.py): parser behavior tests updated for explicit missing-unit policy modes.
- [04-parsing_readme.md](/home/mcnal/projects/recipeimport/docs/04-parsing/04-parsing_readme.md): parsing docs updated for Priority-4 defaults/options.

Current baseline behavior after Priority-4 implementation:

- Parser default backend remains `ingredient_parser_nlp`, with optional `quantulum3_regex` and `hybrid_nlp_then_quantulum3`.
- Missing-unit default policy is `null`; `legacy_medium` and `each` remain explicit selectable options.
- Staging lowercases ingredient text fields and now applies run-config-aware parser behavior through `ingredient_*` options.

## Plan of Work

### Milestone 1: Add settings and dependency scaffolding (no behavior change)

Add new run settings and wiring without changing default outputs. This gives benchmarkable option surface first.

Scope:

- Add optional dependency extras for `ftfy`, `quantulum3`, `pint`.
- Add settings fields in `RunSettings` with UI metadata and summary/hash inclusion.
- Thread settings through stage and prediction-generation code paths without enabling new behavior yet.

### Milestone 2: Implement pre-normalization and packaging handling

Introduce deterministic normalization pipeline steps before parse:

- punctuation/dash/fraction cleanup,
- optional text-fix backend (`ftfy`),
- packaging extraction/hoist (`1 (14-ounce) can ...` keeps `can` as unit and preserves package detail in `note`).

### Milestone 3: Post-parse repairs and missing-unit policy

Implement repair pass and policy-driven missing-unit semantics:

- detect/repair invalid quantity/unit/name combinations,
- preserve `raw_text` and avoid dropping lines,
- replace implicit `medium` default with policy switch:
  - `null` (target default),
  - `each`,
  - `legacy_medium`.

### Milestone 4: Optional alternate backends

Add optional backend choices (not replacements):

- parse assistance via `quantulum3`,
- unit canonicalization via `pint`,
- hybrid fallback mode.

### Milestone 5: Test/docs/default flip

Update tests and docs, then flip default missing-unit policy from legacy mode to target mode once validations are green.

## Concrete Steps

From repo root (`/home/mcnal/projects/recipeimport`):

1. Baseline confirmation:

    source .venv/bin/activate
    pytest -q tests/parsing/test_ingredient_parser.py

2. Add settings/dependency scaffolding first, then run focused test subsets:

    source .venv/bin/activate
    pip install -e .[dev]
    pytest -q tests/parsing/test_ingredient_parser.py tests/staging/test_draft_v1_variants.py tests/llm/test_run_settings.py

3. After parser behavior changes, run broader parsing/staging checks:

    source .venv/bin/activate
    pytest -q tests/parsing tests/staging

4. Run manifest parity check for stage vs prediction-run config propagation:

    source .venv/bin/activate
    pytest -q tests/staging/test_run_manifest_parity.py

5. Validate parse examples manually:

    source .venv/bin/activate
    python - <<'PY'
    from cookimport.parsing.ingredients import parse_ingredient_line
    print(parse_ingredient_line("2 onions"))
    print(parse_ingredient_line("2 onions", ingredient_missing_unit_policy="legacy_medium"))
    print(parse_ingredient_line("1 (14-ounce) can tomatoes", ingredient_pre_normalize_mode="aggressive_v1", ingredient_packaging_mode="regex_v1"))
    PY

## Validation and Acceptance

Acceptance criteria for Priority 4 completion:

- `2 onions` no longer defaults to `raw_unit_text="medium"` under default policy.
- `2 onions` behavior can still be reproduced under `legacy_medium` policy.
- `1 (14-ounce) can tomatoes` preserves package detail in `note` and keeps container-like unit semantics.
- Existing staging invariants remain valid.
- Docs describe the new default and options accurately.
- Targeted parser/staging tests pass in `.venv`.

## Idempotence and Recovery

- All new behavior must be switchable via run settings.
- Safe rollback path is to select baseline settings (`ingredient-parser-nlp` + `legacy_medium`) while debugging.
- Keep changes additive per milestone so test failures can be isolated quickly.

## Artifacts and Notes

Evidence to capture while implementing:

- Test output snippets showing parser/staging suites passing.
- One before/after parse sample for `2 onions` and `1 (14-ounce) can tomatoes`.
- One run-config summary showing new ingredient options are persisted.

Captured sample outputs (2026-02-28, `.venv`):

- Default `parse_ingredient_line("2 onions")` -> `input_qty=2.0`, `raw_unit_text=None`, `raw_ingredient_text="onions"`.
- Legacy `parse_ingredient_line("2 onions", ingredient_missing_unit_policy="legacy_medium")` -> `raw_unit_text="medium"`.
- Packaging mode `parse_ingredient_line("1 (14-ounce) can tomatoes", ingredient_pre_normalize_mode="aggressive_v1", ingredient_packaging_mode="regex_v1")` -> `raw_unit_text="can"`, `note="pkg: 14-ounce"`.

## Interfaces and Dependencies

Planned settings (names fixed for stable benchmarking):

- `ingredient_text_fix_backend`: `none | ftfy`
- `ingredient_pre_normalize_mode`: `legacy | aggressive_v1`
- `ingredient_packaging_mode`: `off | regex_v1`
- `ingredient_parser_backend`: `ingredient_parser_nlp | quantulum3_regex | hybrid_nlp_then_quantulum3`
- `ingredient_unit_canonicalizer`: `legacy | pint`
- `ingredient_missing_unit_policy`: `legacy_medium | null | each`

Dependency intent:

- Keep `ingredient-parser-nlp` baseline path.
- Add `ftfy`, `quantulum3`, and `pint` as optional/additive capabilities.

## Plan change log

- 2026-02-28: Rewrote this ExecPlan to match current code reality (legacy behavior still active, Priority-4 options not yet implemented), removed stale reference-noise, corrected file/test paths, added required front matter, and reset progress to executable next steps.
- 2026-02-28: Updated plan to implemented state: checked completed milestones, replaced stale legacy observations with implementation discoveries, recorded final design choices (default missing-unit policy `null`, soft-failable optional backends), and added concrete validation evidence/commands so the document now describes shipped behavior.
