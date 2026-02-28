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
- [ ] Add optional dependencies for Priority-4 backends (`ftfy`, `quantulum3`, `pint`) and wire extras.
- [ ] Introduce ingredient parsing run settings and CLI/interactive wiring.
- [ ] Implement pre-normalization + packaging extraction/hoist.
- [ ] Implement post-parse repair rules.
- [ ] Implement missing-unit policy and remove implicit default-to-medium behavior from default path.
- [ ] Add/adjust tests for new behavior and option permutations.
- [ ] Update parsing/staging docs after behavior changes land.

## Surprises & Discoveries

- Observation: Priority 4 implementation has not started in runtime code yet; behavior is still legacy.
  Evidence: `cookimport/parsing/ingredients.py` still uses `_extract_unit(...)` fallback to `"medium"`; `tests/parsing/test_ingredient_parser.py` still asserts `"medium"` for `"2 chicken breasts, cubed"`.

- Observation: No Priority-4 run settings knobs are present yet.
  Evidence: no matches for `ingredient_missing_unit_policy`, `ingredient_parser_backend`, `ingredient_pre_normalize_mode`, `ftfy`, or `quantulum3` in `cookimport/config/run_settings.py`, CLI, or interactive run-settings files.

- Observation: The parser module currently has duplicate `parse_ingredient_line` function definitions (a stub followed by the real implementation).
  Evidence: `cookimport/parsing/ingredients.py` defines `parse_ingredient_line` near top and again as the active implementation.

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

## Outcomes & Retrospective

As of 2026-02-28, this plan is refreshed to current code reality. Runtime behavior still matches legacy ingredient parsing; Priority-4 feature work remains pending.

## Context and Orientation

Current relevant modules:

- [ingredients.py](/home/mcnal/projects/recipeimport/cookimport/parsing/ingredients.py): parser entrypoint and normalization logic.
- [draft_v1.py](/home/mcnal/projects/recipeimport/cookimport/staging/draft_v1.py): calls `parse_ingredient_line` while building staged output.
- [run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py): canonical settings model for pipeline options.
- [test_ingredient_parser.py](/home/mcnal/projects/recipeimport/tests/parsing/test_ingredient_parser.py): parser behavior tests, currently legacy-aligned.
- [04-parsing_readme.md](/home/mcnal/projects/recipeimport/docs/04-parsing/04-parsing_readme.md): docs still describe default unit fallback to `medium`.

Current baseline behavior to preserve until switched by explicit options:

- Parser uses `ingredient-parser-nlp` output normalization.
- Missing unit defaults to `medium` in current implementation.
- Staging lowercases ingredient text fields and applies safety normalization, but does not expose Priority-4 parser knobs.

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
    pytest -q tests/parsing/test_ingredient_parser.py tests/staging/test_draft_v1_staging_alignment.py

3. After parser behavior changes, run broader parsing/staging checks:

    source .venv/bin/activate
    pytest -q tests/parsing tests/staging

4. Validate end-to-end staging output on a small input and inspect emitted ingredient lines.

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
