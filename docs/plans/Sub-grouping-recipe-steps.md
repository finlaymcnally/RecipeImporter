# Add component sections for multi-part recipes

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repo includes ExecPlan requirements at `docs/PLANS.md`. This document must be maintained in accordance with that file.


## Purpose / Big Picture

Many real recipes are multi-component: they present “For the meat”, “For the gravy”, “For the topping”, etc., each with its own ingredient subset and its own instruction subset. Today, our pipeline can detect some ingredient section headers, but (a) instruction section headers are often treated as literal steps, and (b) the final cookbook3 output drops ingredient section headers, which makes it harder to keep the “component” structure for review/debugging and can hurt step↔ingredient linking in ambiguous cases.

After this change, the staging pipeline will:

1) Detect section headers in both ingredients and instructions, producing a structured “sections” view of the recipe (components).

2) Use section context to improve step-ingredient linking in multi-component recipes (especially when ingredient names repeat across components).

3) Preserve section structure in artifacts that humans and downstream tooling can inspect:
   - Intermediate schema.org JSON-LD: represent instruction sections using HowToSection/HowToStep when multiple sections exist.
   - A new `sections/` output artifact per recipe that records the grouped ingredients/steps (without changing cookbook3’s contract shape).

You can see it working by running `cookimport stage` on a fixture recipe that has “For the meat / For the gravy” headings, then confirming:
- The new `sections/<workbook>/...` files exist and show the right grouping.
- The intermediate JSON-LD’s `recipeInstructions` becomes a list of HowToSection objects.
- A new/updated unit test proves section-aware linking picks the correct step for repeated ingredients.


## Progress

- [x] (2026-02-25T16:25Z) Read current code paths for ingredient parsing, instruction parsing, step-ingredient linking, and staging writers; captured active entry points (`instruction_parser.py`, `draft_v1.py`, `jsonld.py`, `writer.py`, CLI merge/single-file writers).
- [x] (2026-02-25T16:31Z) Added deterministic section extraction module `cookimport/parsing/sections.py` and focused unit tests in `tests/parsing/test_recipe_sections.py`.
- [x] (2026-02-25T16:37Z) Integrated section context into `cookimport/parsing/step_ingredients.py` (tie-break + scoped special passes), plus duplicate-safe index tracking and regression coverage in `tests/parsing/test_step_ingredient_linking.py`.
- [x] (2026-02-25T16:40Z) Added staging section artifacts (`write_section_outputs` -> `sections/<workbook_slug>/...`) and updated intermediate JSON-LD section emission (`HowToSection` + `recipeimport:ingredientSections`).
- [x] (2026-02-25T16:41Z) Updated parsing/staging/docs conventions references for the new behavior and artifact contract.
- [x] (2026-02-25T16:42Z) Ran end-to-end `cookimport stage` on `tests/fixtures/sectioned_components_recipe.txt` and captured concrete output snippets below.


## Surprises & Discoveries

- Observation: Ingredient “section_header” lines are currently detected, but dropped during cookbook3 draft shaping.
  Evidence: `docs/05-staging/05-staging_readme.md` notes “section_header lines are dropped from output lines” (reader should confirm in `cookimport/staging/draft_v1.py`).

- Observation: EPUB segmentation explicitly keeps “For the X” inside a recipe to avoid false splits, meaning these headers are common and should be treated as intra-recipe structure rather than recipe boundaries.
  Evidence: `docs/04-parsing/04-parsing_readme.md` describes “Explicitly keeps subsection headers inside recipe, including: For the X …”.

- Observation: Existing step-linking special passes still keyed ingredient identity by `raw_ingredient_text`, which can collapse duplicate ingredient lines.
  Evidence: New regression `test_section_context_disambiguates_repeated_ingredient_names` initially failed with both salts assigned to the first step until index-based identity tracking was added.

- Observation: Section tie-break needed to override step-index bias for duplicated aliases.
  Evidence: Linker scoring includes an earlier-step bias; section-aware disambiguation required a wider near-tie epsilon and same-section use-verb preference path.


## Decision Log

- Decision: Do not change cookbook3 output schema to add first-class section objects in this iteration; instead, add section-aware linking plus a new `sections/` artifact and richer intermediate JSON-LD.
  Rationale: cookbook3 staging contract is regression-sensitive; DB schema does not currently encode section headers; adding a parallel artifact keeps compatibility while still making structure visible and useful for debugging and future schema work.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Represent instruction sections in intermediate schema.org JSON-LD using HowToSection/HowToStep only when multiple sections are detected; otherwise continue emitting a flat HowToStep list (or current behavior, if already structured).
  Rationale: Keeps output more compatible with consumers that expect a simple instruction list, while still preserving sections when needed.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Keep final cookbook3 drafts schema-stable; section structure is exposed via additive `sections/` artifacts and intermediate JSON-LD only.
  Rationale: Avoids staging contract drift while still making section grouping inspectable and testable.
  Date/Author: 2026-02-25 / Codex

- Decision: Track ingredient identity by index inside linker passes, then strip internal indices before returning staged lines.
  Rationale: Duplicate ingredient names across sections cannot be safely disambiguated by text equality.
  Date/Author: 2026-02-25 / Codex


## Outcomes & Retrospective

- Shipped:
  - `cookimport/parsing/sections.py` with deterministic ingredient/instruction section extraction.
  - section-aware linker behavior in `cookimport/parsing/step_ingredients.py`.
  - instruction section handling in `cookimport/staging/jsonld.py` (`HowToSection` when multi-section).
  - additive section artifacts in `cookimport/staging/writer.py` and wired stage/merge/ingest call sites.
  - regression and unit coverage (`tests/parsing/test_recipe_sections.py`, `tests/parsing/test_step_ingredient_linking.py`, `tests/staging/test_section_outputs.py`, plus CLI structure assertion update).
- Remaining:
  - None for this ExecPlan scope.
- Learned:
  - Section-aware matching is most reliable when paired with index-based ingredient identity, because many recipes repeat identical ingredient names across components.


## Context and Orientation

This repository is a recipe ingestion + normalization pipeline (“cookimport”). Its stage command produces:

- Intermediate outputs: `schema.org Recipe JSON` written to:
  `data/output/<timestamp>/intermediate drafts/<workbook_slug>/r{index}.jsonld`

- Final outputs: `cookbook3` written to:
  `data/output/<timestamp>/final drafts/<workbook_slug>/r{index}.json`

The relevant code areas (paths are repo-relative):

- `cookimport/parsing/ingredients.py`
  Parses individual ingredient lines via an NLP ingredient parser. It contains heuristics to classify some lines as “section headers” (e.g., “For the gravy:”).

- `cookimport/parsing/instruction_parser.py`
  Splits and normalizes instructions into step strings and extracts times/temps as applicable.

- `cookimport/parsing/sections.py`
  Detects ingredient/instruction section headers, removes header lines from content lists, and emits normalized section keys for alignment.

- `cookimport/parsing/step_ingredients.py`
  Assigns each ingredient line to one or more steps using alias matching + heuristics, with some existing special passes (including a pass that uses ingredient section-header groups).

- `cookimport/staging/draft_v1.py`
  Converts a `RecipeCandidate` into the cookbook3 output shape. This is where staging “contract shaping” happens, including dropping ingredient section headers.

- `cookimport/staging/jsonld.py`
  Converts a `RecipeCandidate` into schema.org Recipe JSON-LD for intermediate outputs.

- `cookimport/staging/writer.py`
  Writes intermediate/final artifacts and run reports.

Terminology used in this plan:

- “Section header line”: A line that is not itself an ingredient/step, but labels a component group, e.g. “For the gravy”, “Gravy:”, “Assembly”, “To serve”.

- “Component section” (or just “section”): The logical grouping created by a section header, containing a subset of ingredients and a subset of instruction steps.

- “Section context”: The section key/name assigned to a given ingredient line and/or instruction step, used to bias matching and for output grouping.

- “Schema.org HowToSection”: A schema.org type meant to group a sequence of HowToStep instructions inside a single how-to/recipe, used here only for `recipeInstructions` grouping in intermediate JSON-LD.

Non-goals for this iteration (explicitly out of scope to keep the change shippable):

- Creating separate “sub-recipes” as new Recipe records and linking them via `linked_recipe_id`.
- Database schema migrations to store section headers as first-class objects.
- Solving every ambiguous heading; this is best-effort heuristic extraction with strong tests for known patterns.


## Plan of Work

### Milestone 1: Section extraction module + tests (structure only, no linking changes yet)

Goal: Build a deterministic, well-tested way to extract sections from raw ingredient lines and raw instruction lines.

Work:

1) Add a new module: `cookimport/parsing/sections.py`.

2) Implement two passes:

   - Ingredient section extraction:
     - Input: `list[str]` of raw ingredient lines (exactly what is currently stored in candidates).
     - Output:
       - `ingredient_lines_no_headers`: list of ingredient lines with section headers removed.
       - `ingredient_section_key_by_line`: list mapping each non-header ingredient line to a section key.
       - `ingredient_section_display_by_key`: dict mapping keys to display names (e.g., key `gravy`, display “For the gravy”).
       - `ingredient_header_hits`: debug list of where headers were found (original index + raw header line).

     - Detection rule: start by reusing (or factoring out) the existing ingredient “section header” heuristic in `cookimport/parsing/ingredients.py` so behavior stays consistent. If the heuristic is currently private/inline, refactor it into a shared helper in `sections.py` and call it from both modules.

   - Instruction section extraction:
     - Input: `list[str]` of instruction lines/steps (the pre-final-splitting representation used in draft conversion; if instructions are currently a single blob, split into lines first using the existing logic).
     - Output:
       - `steps_no_headers`: list of step strings with section header lines removed.
       - `step_section_key_by_step`: list mapping each step to a section key.
       - `instruction_header_hits`: debug list of where headers were found.

     - Detection rule (must be conservative to avoid deleting real steps):
       - Treat as a section header if ALL are true:
         - The line is “header-like”: short (e.g., <= 60 chars), contains no digits, and either ends with a colon OR is title-cased/uppercase-ish (implement a simple heuristic).
         - The line matches known component patterns like:
           - “For the X”, “For X” (with optional trailing colon)
           - “X:” where X is 1–5 words
           - “To serve”, “Assembly”, “Optional” (allow these as sections; they’re useful in practice)
         - The line does NOT contain a clear instruction verb phrase (use a small denylist heuristic: if it contains commas plus a verb-like word such as “cook”, “mix”, “stir”, “add”, “bake”, treat it as a step, not a header).
       - Always strip trailing colon from the canonical display name.

3) Normalize section keys so ingredient + instruction sections can align:
   - `normalize_section_key(display_name: str) -> str` should:
     - lowercase
     - remove leading “for” / “for the”
     - strip punctuation and trailing colon
     - collapse whitespace
     - remove common stop words like “the”, “a”, “an”
     - Example: “For the Gravy:” -> key “gravy”

4) Add unit tests in a new file `tests/test_recipe_sections.py`:
   - A minimal multi-component recipe example with:
     - ingredient headers: “For the meat”, “For the gravy”
     - instruction headers: “For the meat”, “For the gravy”
   - Assert:
     - header lines are removed from the “no_headers” arrays
     - section mapping arrays assign the right keys
     - keys align between ingredient and instruction sections

Acceptance / Proof:

- Running:
    pytest -q tests/test_recipe_sections.py
  should pass, and the test should clearly demonstrate that header lines are not treated as ingredients/steps.


### Milestone 2: Section-aware step-ingredient linking (behavior change with regression tests)

Goal: Use section context to improve linking in multi-component recipes without breaking non-section recipes.

Work:

1) Update `cookimport/parsing/step_ingredients.py` to accept optional section context.

   In the main linking entry point (whatever function the draft conversion calls; likely something like `assign_ingredient_lines_to_steps(...)`), add optional parameters:

     - `ingredient_section_key_by_line: list[str] | None`
     - `step_section_key_by_step: list[str] | None`

   These lists must be the same lengths as the ingredient/step arrays passed into linking (excluding section headers).

2) Integrate section context as a tie-breaker, not a hard filter:

   The safe default rule:

   - If an ingredient has multiple plausible candidate steps with similar scores (within an epsilon like 0.05), prefer a candidate step that shares the same section key.
   - If no same-section candidate exists, keep the existing best candidate.

   This avoids preventing legitimate cross-section usage while still improving ambiguous cases.

3) Improve existing “special passes” with section scoping (when section info is present):

   - “all ingredients” phrases:
     - If a step says “mix all ingredients” and the step belongs to section `S`, assign only ingredients in section `S` (instead of the entire recipe).
     - If the recipe has only one section, keep current behavior.

   - Collective-term fallback (“spices”, “herbs”, “seasonings”):
     - If an unmatched ingredient is in section `S`, and there is a step mentioning the collective term in section `S`, prefer that; otherwise fall back to existing global behavior.

   - Existing “section-header groups can add grouped ingredients to steps mentioning group aliases”:
     - Keep this behavior, but ensure it plays well with instruction section headings by allowing the heading context to count as a “mention” for the first step of the section (only if that’s how the current code models it). If this is too risky, skip this sub-change and rely on the tie-breaker improvements above.

4) Add a regression test to `tests/test_step_ingredient_linking.py`:

   Use a recipe where the same ingredient name appears in multiple sections but is used in different steps:

   - Ingredients:
     - For the meat:
       - “1 tsp salt”
     - For the gravy:
       - “1 tsp salt”
   - Instructions:
     - For the meat:
       - “Season the meat with salt.”
     - For the gravy:
       - “Season the gravy with salt.”

   The test should construct the ingredient/step inputs in the same shape the linker expects (use existing test helpers), pass section arrays, and assert that:
   - the “meat salt” line maps to the meat step
   - the “gravy salt” line maps to the gravy step

   If duplicate raw text lines are currently deduplicated by text somewhere, adjust the fixture slightly (e.g., “salt (for meat)” vs “salt (for gravy)”) and add a note in the test explaining why. If you discover text-based deduplication is the blocker, fix it as part of this milestone by ensuring ingredient identity is tracked by position/index rather than raw string.

Acceptance / Proof:

- Running:
    pytest -q tests/test_step_ingredient_linking.py
  should pass.

- The new test must fail on main (before the change) and pass after, demonstrating the section-aware improvement.


### Milestone 3: Persist section structure in outputs (new artifacts + richer intermediate JSON-LD)

Goal: Make sections visible to humans and downstream tools without breaking cookbook3.

Work:

1) Add new section artifacts under the run output folder.

   In `cookimport/staging/writer.py`, add a new function:

     - `write_section_outputs(out_dir: Path, workbook_slug: str, candidates: list[RecipeCandidate]) -> None`

   For each candidate recipe:
   - Extract raw ingredient lines and instruction lines (whatever fields are used for draft conversion).
   - Run the section extraction logic from `cookimport/parsing/sections.py`.
   - Write `sections/<workbook_slug>/r{index}.sections.json` with:
     - recipe id
     - recipe title
     - a list of sections in order, each containing:
       - section display name
       - ingredient lines (non-header) in that section
       - step texts (non-header) in that section
   - Write/update `sections/<workbook_slug>/sections.md` as a human-readable summary.

   Keep this artifact strictly additive: do not change existing intermediate/final file paths.

2) Update intermediate schema.org JSON-LD instruction representation.

   In `cookimport/staging/jsonld.py`, when producing the schema.org Recipe object:
   - If multiple instruction sections are detected, output `recipeInstructions` as a list of HowToSection objects:

       [
         { "@type": "HowToSection", "name": "<section name>", "itemListElement": [
             { "@type": "HowToStep", "text": "<step 1>" },
             ...
         ]},
         ...
       ]

   - If no (or only one) section is detected, output the current shape, but prefer a flat list of HowToStep objects if it is already supported by the code.

   This is intermediate-only; cookbook3 outputs must remain unchanged.

3) (Optional, but recommended) Add `recipeimport:` metadata for ingredient sections in JSON-LD.

   Because schema.org doesn’t have a standard ingredient-section structure that we rely on, add a custom field inside the JSON-LD output, using the existing “recipeimport:* metadata” approach the repo already uses, e.g.:

     - `recipeimport:ingredientSections`: list of sections, each with `name` and `recipeIngredient` (the ingredient strings)

   The exact property name should match existing conventions in `jsonld.py` (inspect what prefixing/context is already used there).

4) Update docs:

   - `docs/04-parsing/04-parsing_readme.md`:
     - Add a subsection describing section extraction and how it influences step-ingredient linking.
     - Document the conservative header detection rules and known edge cases.

   - `docs/05-staging/05-staging_readme.md`:
     - Add `sections/<workbook_slug>/...` to the output layout.
     - Mention intermediate JSON-LD may now emit HowToSection for `recipeInstructions` when sections exist.

Acceptance / Proof:

- End-to-end run on a fixture text file:

    mkdir -p /tmp/cookimport_sections_demo
    cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/cookimport_sections_demo

  Then confirm:

  - A new folder exists:
      /tmp/cookimport_sections_demo/<timestamp>/sections/<workbook_slug>/

  - Files exist:
      r0.sections.json
      sections.md

  - The intermediate JSON-LD for the same recipe includes HowToSection objects in `recipeInstructions` when the fixture has multiple sections:
      /tmp/cookimport_sections_demo/<timestamp>/intermediate drafts/<workbook_slug>/r0.jsonld

  - Existing staging outputs still exist and are unchanged in path and basic structure:
      .../final drafts/<workbook_slug>/r0.json

- Run the full test suite or at minimum the affected tests:

    pytest -q


## Concrete Steps

All commands assume you are at the repository root.

1) Create a small fixture recipe text file at `tests/fixtures/sectioned_components_recipe.txt`:

    Title: Meat and Gravy
    Ingredients:
    For the meat:
    1 lb beef
    1 tsp salt
    For the gravy:
    2 tbsp flour
    1 tsp salt
    Instructions:
    For the meat:
    Season the meat with salt.
    Brown the beef.
    For the gravy:
    Whisk flour into drippings.
    Season the gravy with salt.

2) Implement Milestone 1 and run:

    pytest -q tests/parsing/test_recipe_sections.py

3) Implement Milestone 2 and run:

    pytest -q tests/parsing/test_step_ingredient_linking.py

4) Implement Milestone 3 and run an end-to-end stage:

    cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/cookimport_sections_demo

5) Inspect artifacts (paths will include a timestamp folder):

    ls -R /tmp/cookimport_sections_demo/<timestamp>/sections/
    cat /tmp/cookimport_sections_demo/<timestamp>/sections/<workbook_slug>/r0.sections.json
    sed -n '1,120p' /tmp/cookimport_sections_demo/<timestamp>/sections/<workbook_slug>/sections.md
    cat "/tmp/cookimport_sections_demo/<timestamp>/intermediate drafts/<workbook_slug>/r0.jsonld" | head


## Validation and Acceptance

Acceptance is met when all are true:

1) Unit tests:
   - `pytest -q tests/parsing/test_recipe_sections.py` passes.
   - `pytest -q tests/parsing/test_step_ingredient_linking.py` passes with a new regression test demonstrating section-aware linking.

2) End-to-end artifacts:
   - `cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/cookimport_sections_demo` succeeds.
   - The run output contains:
     - `sections/<workbook_slug>/r0.sections.json` with two sections (“meat”, “gravy”) and correct grouped lines.
     - `sections/<workbook_slug>/sections.md` showing the same grouping.
   - The intermediate JSON-LD has sectioned `recipeInstructions` (HowToSection) when multiple sections exist.
   - The final cookbook3 draft output remains valid and continues to drop ingredient section headers (contract unchanged).

3) Non-section recipes are not degraded:
   - Existing tests for ingredient parsing and instruction parsing remain green.
   - A spot-check on a simple one-section recipe yields no HowToSection output and no unexpected step deletions.


## Idempotence and Recovery

- All changes are additive or conservative refactors. Re-running `pytest` and `cookimport stage` is safe.

- If the new instruction-header detector accidentally removes real steps, recovery should be:
  1) Add the problematic line as a unit test case in `tests/parsing/test_recipe_sections.py`.
  2) Tighten the header detection rules (e.g., require trailing colon, or expand the “instruction verb” denylist).
  3) Re-run the full parsing/linking test suite.

- If intermediate JSON-LD consumers rely on the old `recipeInstructions` shape, keep the previous shape behind a small feature flag inside `jsonld.py` (defaulting to current behavior) and document it in `Decision Log`. Only do this if a concrete compatibility break is observed.


## Artifacts and Notes

Example expected `sections/<workbook>/r0.sections.json` excerpt (illustrative, exact keys may differ):

    {
      "recipe_id": "urn:recipeimport:text:...",
      "title": "Meat and Gravy",
      "sections": [
        {
          "name": "For the meat",
          "key": "meat",
          "ingredients": ["1 lb beef", "1 tsp salt"],
          "steps": ["Season the meat with salt.", "Brown the beef."]
        },
        {
          "name": "For the gravy",
          "key": "gravy",
          "ingredients": ["2 tbsp flour", "1 tsp salt"],
          "steps": ["Whisk flour into drippings.", "Season the gravy with salt."]
        }
      ]
    }

Example expected intermediate JSON-LD `recipeInstructions` excerpt:

    "recipeInstructions": [
      {
        "@type": "HowToSection",
        "name": "For the meat",
        "itemListElement": [
          { "@type": "HowToStep", "text": "Season the meat with salt." },
          { "@type": "HowToStep", "text": "Brown the beef." }
        ]
      },
      {
        "@type": "HowToSection",
        "name": "For the gravy",
        "itemListElement": [
          { "@type": "HowToStep", "text": "Whisk flour into drippings." },
          { "@type": "HowToStep", "text": "Season the gravy with salt." }
        ]
      }
    ]

Observed run (2026-02-25):

    cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/cookimport_sections_demo

Produced:

    /tmp/cookimport_sections_demo/2026-02-25_16.42.25/sections/sectioned_components_recipe/r0.sections.json
    /tmp/cookimport_sections_demo/2026-02-25_16.42.25/sections/sectioned_components_recipe/sections.md
    /tmp/cookimport_sections_demo/2026-02-25_16.42.25/intermediate drafts/sectioned_components_recipe/r0.jsonld

Observed `r0.sections.json` keys:

    sections[0].key = "meat"
    sections[1].key = "gravy"


## Interfaces and Dependencies

No new external dependencies are required; reuse existing utilities (e.g., RapidFuzz if already present) only if needed for section-name alignment.

Define in `cookimport/parsing/sections.py`:

    from dataclasses import dataclass
    from typing import Optional

    @dataclass(frozen=True)
    class SectionHeaderHit:
        source: str              # "ingredients" or "instructions"
        original_index: int      # index in the original input list
        raw_line: str            # the header line as seen
        display_name: str        # canonical display, e.g. "For the gravy"
        key: str                 # normalized key, e.g. "gravy"

    @dataclass(frozen=True)
    class SectionedLines:
        lines_no_headers: list[str]
        section_key_by_line: list[str]
        section_display_by_key: dict[str, str]
        header_hits: list[SectionHeaderHit]

    def normalize_section_key(display_name: str) -> str:
        ...

    def extract_ingredient_sections(raw_ingredient_lines: list[str]) -> SectionedLines:
        ...

    def extract_instruction_sections(raw_instruction_lines: list[str]) -> SectionedLines:
        ...

Update `cookimport/parsing/step_ingredients.py` (exact function name may differ; confirm in code) so the main entry point accepts:

    def assign_ingredient_lines_to_steps(
        steps: list[...],
        ingredient_lines: list[...],
        *,
        ingredient_section_key_by_line: Optional[list[str]] = None,
        step_section_key_by_step: Optional[list[str]] = None,
        ...
    ) -> ...

Update `cookimport/staging/writer.py` to add:

    def write_section_outputs(out_dir: Path, workbook_slug: str, candidates: list[RecipeCandidate]) -> None:
        ...

Update `cookimport/staging/jsonld.py` so intermediate JSON-LD writing can emit HowToSection/HowToStep structures for `recipeInstructions` when sections exist.


---

Plan change notes:
- Initial version authored 2026-02-25. Rationale: introduce a safe, additive section model that improves linking and preserves structure without breaking cookbook3 staging contracts.
- 2026-02-25 implementation update. Rationale: mark completed milestones, record section-aware linker/index decisions, align test/documentation paths to current `tests/{parsing,staging,cli}` layout, and document actual stage artifact behavior.
