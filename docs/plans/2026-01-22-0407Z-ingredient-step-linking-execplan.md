---
summary: "ExecPlan for attaching ingredients to steps in Draft V1."
read_when:
  - When implementing step-level ingredient linking
---

# Attach Ingredients to Steps in Draft V1

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` from the repository root.

## Purpose / Big Picture

After this change, each step in the Draft V1 output will list only the ingredient lines used by that step instead of putting every ingredient on the first step. A user can run `cookimport stage` and see that steps in `data/output/.../drafts/.../*.json` have `ingredient_lines` that align with the instruction text, matching the pattern shown in `docs/template/Pancakes.JSON`. This enables downstream apps to highlight ingredients per step and avoids manual reassignment.

## Progress

- [x] (2026-01-22 04:07Z) Draft ExecPlan for step-level ingredient linking.
- [x] (2026-01-22 04:30Z) Add step ingredient linking utilities with deterministic matching heuristics and unit tests.
- [x] (2026-01-22 04:30Z) Integrate step mapping into `cookimport/staging/draft_v1.py` and document the heuristic.
- [ ] Validate output against sample data and confirm acceptance criteria (completed: pytest coverage; remaining: run `cookimport stage` and inspect sample output).

## Surprises & Discoveries

No surprises yet. Update this section if matching heuristics behave unexpectedly on real recipes.

## Decision Log

- Decision: Use deterministic text matching with a two-stage alias+scoring approach and section-header grouping, without LLM calls.
  Rationale: The repository has no active LLM pipeline and deterministic matching is repeatable, inexpensive, and easier to debug.
  Date/Author: 2026-01-22 / Agent

- Decision: Use section-header lines as group labels only and exclude them from `steps[].ingredient_lines`.
  Rationale: Section headers are not ingredients and the Draft V1 schema expects ingredient lines only.
  Date/Author: 2026-01-22 / Agent

- Decision: Allow a single ingredient line to appear in multiple steps when the instruction text explicitly mentions it.
  Rationale: Ingredients are often reused across steps, and duplicating the line preserves that usage.
  Date/Author: 2026-01-22 / Agent

- Decision: Treat any section header (for example, "Sauce", "Filling", "For the topping") as a grouping label and allow steps that mention that label to map to that group, with dry/wet as a narrow special-case.
  Rationale: Real recipes refer to sauces, fillings, and toppings far more than "dry/wet" language, so general section grouping yields better coverage with fewer false positives.
  Date/Author: 2026-01-22 / Agent

- Decision: Use word-boundary matching and prefer longer phrases to avoid substring false-positives and generic word matches.
  Rationale: Avoids common bugs like "oil" matching "boil" and "pepper" matching "peppercorns" when "red pepper flakes" is intended.
  Date/Author: 2026-01-22 / Agent

- Decision: Apply a cap on weak matches per step and allow "all ingredients" phrases to override the cap.
  Rationale: Prevents ingredient spam on steps that mention generic words while still allowing intentional "combine all" steps.
  Date/Author: 2026-01-22 / Agent

- Decision: Add a single-token tail alias for multi-word ingredients and drop weak matches that overlap strong multi-word matches.
  Rationale: Keeps longer phrases like "chili powder" dominant while still offering a fallback token when only the short form appears.
  Date/Author: 2026-01-22 / Agent

- Decision: Clean raw-text aliases by stripping parentheticals, commas, and measurement/unit tokens.
  Rationale: Prevents tokens like "cup" or "optional" from matching instruction text.
  Date/Author: 2026-01-22 / Agent

## Outcomes & Retrospective

Implemented token-based ingredient matching with section grouping, added unit tests, and integrated step assignment into Draft V1 output. Staging output inspection is still pending.

## Context and Orientation

The import pipeline builds `RecipeCandidate` objects from sources like Excel, then writes Draft V1 JSON through `cookimport/staging/writer.py`. The Draft V1 schema lives in `docs/template/recipeDraftV1.schema.json` and expects each step to contain an `ingredient_lines` array. The current implementation in `cookimport/staging/draft_v1.py` converts all ingredients with `_convert_ingredient()` and attaches the entire list to the first step, leaving subsequent steps empty. Ingredients are parsed by `cookimport/parsing/ingredients.py`, which provides `input_item`, `preparation`, and `raw_text` fields that can be used to match instruction text. Instruction steps are strings or `HowToStep` models in `cookimport/core/models.py`.

In this plan, an "ingredient line" is the dict returned by `_convert_ingredient()` and includes `ingredient_id`, `quantity_kind`, `input_item`, and `raw_text`. A "section header" is an ingredient line whose `quantity_kind` is `"section_header"`. A "step" is one entry in the Draft V1 `steps` array with `instruction` and `ingredient_lines`.

## Plan of Work

Milestone 1 introduces a deterministic step-ingredient linker in a new module and verifies it with focused unit tests. The linker will normalize ingredient names and instruction text, build alias candidates for each ingredient line (from `input_item` and cleaned `raw_text`), and match against steps using word-boundary regexes with a scoring model that prefers longer phrases over single tokens. It will also group ingredients by section headers and allow steps that mention a section name ("make the sauce", "prepare the filling") to map to that group. Dry/wet matching is treated as a special-case of section grouping rather than the core fallback. The goal of this milestone is a pure function that accepts steps as strings or `HowToStep`, returns per-step ingredient lists in original order, and internally preserves match reasons for debugging.

Milestone 2 integrates the linker into `cookimport/staging/draft_v1.py` so Draft V1 output uses the new mapping. This includes filtering out section headers from step output, cloning ingredient dicts when an ingredient is used in multiple steps, and ensuring steps without matches remain valid with empty `ingredient_lines`. Add a short note in `cookimport/staging/README.md` describing the heuristic, the alias/scoring rules, and the lists that can be tuned (section keywords, "all ingredients" phrases, weak-match caps). Update the ExecPlan sections as work progresses.

Milestone 3 validates the behavior by running the unit tests and re-running staging on sample input. Compare a representative output to the pattern in `docs/template/Pancakes.JSON` and confirm that step ingredient assignments align with the instructions, including section references such as "sauce" or "topping".

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`. Use the project-local virtual environment:

    python -m venv .venv
    source .venv/bin/activate

If pip is missing in the venv, bootstrap it with get-pip.py and avoid using system pip.

Create `cookimport/parsing/step_ingredients.py` with the linker implementation and update `cookimport/parsing/__init__.py` to export the new helper if needed. Add a new test file `tests/test_step_ingredient_linking.py` with focused unit tests that cover:

    - Negative matches: "oil" does not match "boil", "salt" does not match "unsalted".
    - Multi-word preference: "chili powder" beats "powder" when both appear.
    - Section header mapping: "Make the sauce" maps to the "Sauce" section ingredients.
    - Duplication rules: ingredients only repeat across steps when explicitly mentioned or when an "all ingredients" phrase is used.
    - HowToStep inputs: mixed string and `HowToStep` steps are handled safely.

Update `cookimport/staging/draft_v1.py` to replace the "attach all ingredients to the first step" logic with the linker output.

Add a brief note in `cookimport/staging/README.md` explaining the matching heuristic and the keyword lists it uses.

Run tests and staging:

    pytest tests/test_step_ingredient_linking.py -v
    pytest tests/test_ingredient_parser.py -v
    cookimport stage data/input --out data/output

Inspect a sample output JSON and confirm that steps contain the expected ingredient lines.

Completed:

    source .venv/bin/activate
    pytest tests/test_step_ingredient_linking.py -v
    pytest tests/test_ingredient_parser.py -v

## Validation and Acceptance

The change is accepted when the following are true:

1. Unit tests in `tests/test_step_ingredient_linking.py` pass and demonstrate correct mapping for explicit mentions, section headers, and dry/wet fallback.
2. Running `cookimport stage data/input --out data/output` completes without errors.
3. At least one output file shows per-step ingredient lines that align with the instruction text, similar in structure to `docs/template/Pancakes.JSON`.
4. No step outputs include `quantity_kind` of `"section_header"`.
5. Steps without explicit matches do not receive more than a small capped number of weak matches (for example, no more than 3), unless the step contains an "all ingredients" phrase.

## Idempotence and Recovery

The linker is deterministic and pure, so re-running staging produces the same output. If a match looks wrong, adjust the keyword lists or normalization rules in the linker module and re-run `cookimport stage`. No destructive operations are required.

## Artifacts and Notes

Example of expected step mapping for a pancakes-style recipe:

    Step 1 instruction: "Whisk together dry ingredients."
    Step 1 ingredient_lines includes: flour, sugar, salt
    Step 2 instruction: "Whisk wet ingredients and combine with dry."
    Step 2 ingredient_lines includes: milk, egg, butter

Include a short excerpt from a generated Draft V1 JSON in this section once implementation is complete.

Test evidence:

    tests/test_step_ingredient_linking.py::test_negative_matches_no_substrings PASSED
    tests/test_step_ingredient_linking.py::test_multiword_preference PASSED
    tests/test_step_ingredient_linking.py::test_section_header_grouping PASSED
    tests/test_step_ingredient_linking.py::test_duplication_and_all_ingredients PASSED
    tests/test_step_ingredient_linking.py::test_howtostep_inputs PASSED

    tests/test_ingredient_parser.py::TestBasicParsing::test_simple_ingredient_with_unit PASSED
    tests/test_ingredient_parser.py::TestConfidence::test_section_header_zero_confidence PASSED

## Interfaces and Dependencies

No new external dependencies are required. Implement the step-ingredient linker using standard library modules (re, string, dataclasses) and existing parsed ingredient data.

Define the following interface in `cookimport/parsing/step_ingredients.py`:

    def assign_ingredient_lines_to_steps(
        steps: list[str | HowToStep],
        ingredient_lines: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """Return a per-step list of ingredient lines in original order."""

The function should treat `quantity_kind == "section_header"` as a group label rather than an ingredient, it should return deep-copied ingredient dicts when a line is used in multiple steps, and it should use word-boundary matching with a scoring threshold so that longer phrase matches win over single-token matches.

Plan revision note: Updated the plan to use a two-stage alias+scoring matcher, expand section grouping beyond dry/wet, add caps for weak matches, and align the interface with `HowToStep` inputs based on the documented risk spots. (2026-01-22 04:07Z)
Plan revision note: Recorded implementation details, decisions, and test evidence; updated progress to reflect completed work and remaining staging validation. (2026-01-22 04:30Z)
