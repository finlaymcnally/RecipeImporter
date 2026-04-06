---
summary: "ExecPlan for structure-aware EPUB hints that preserve the current block-first pipeline."
read_when:
  - When implementing EPUB structure-aware candidate hints or diagnostics
  - When deciding how EPUB can use internal XHTML structure without becoming structured-export-first
---

# EPUB Structure-Aware Hints While Staying Block-First

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Operator Intent (Verbatim) - DO NOT DELETE

The following is the operator's exact stated intent for this change.

> im not saying "change epub to structured-export-first" im asking if giving epubs an option to leverage existing structure IF it exists could be useful? we'd obviously still need to do a ton of parsing, but it might be a good shortcut to figuring out what is/ins't a recipe. or worst case, we still only do block-first but can check against the structure? idk

> okay nice. first things first, write an execplan in docs/plans to implement this based on your initial reaction here, and then we'll refine it

## Operator Intent (Structured) - DO NOT DELETE

The operator wants EPUB importing to remain block-first, but to become more structure-aware when the source contains useful XHTML or HTML structure. Existing structure should help the importer package better evidence about what looks recipe-like and what looks clearly non-recipe, especially before recipe-boundary runs. This must not create an EPUB-only final-authority path. The shared stage pipeline must still decide what is a recipe and what is not. Deterministic code may package evidence and emit better hints, but it must not replace later semantic ownership with importer guesses.

## Purpose / Big Picture

After this change, an EPUB with strong internal structure such as heading tags, ingredient lists, ordered instruction lists, or explicit navigation sections will produce richer importer evidence than it does today. The importer will still hand off canonical source blocks plus `sourceSupport` proposals, but those proposals will carry structure-backed evidence instead of only text-flow heuristics. EPUB runs will also package explicit non-recipe structural evidence for things like navigation and table-of-contents clusters when the source exposes them.

This matters because EPUBs sit between plain flowing documents and true structured exports. Many cookbook EPUBs are not as authoritative as Paprika or RecipeSage exports, but they still often encode useful layout truth that can help the pipeline start from a better place. The proof for this plan is not "the importer now decides recipes correctly on its own." The proof is that structured EPUB fixtures produce richer, inspectable candidate evidence and fewer obviously bad candidate inputs, while recipe-boundary and later stages remain the authority.

## Progress

- [x] (2026-04-02 10:56 America/Toronto) Read `docs/PLANS.md`, `docs/03-ingestion/03-ingestion_readme.md`, `docs/04-parsing/04-parsing_readme.md`, and the relevant `cookimport/plugins/epub.py`, `cookimport/plugins/text.py`, `cookimport/plugins/excel.py`, and `cookimport/parsing/section_detector.py` seams.
- [x] (2026-04-02 10:56 America/Toronto) Confirmed that the current EPUB importer already preserves block HTML, structured table-row metadata, deterministic pattern diagnostics, and `candidate_recipe_region` support proposals, but it does not yet have a first-class structure-hints layer.
- [x] (2026-04-02 10:56 America/Toronto) Wrote the first-pass ExecPlan for structure-aware EPUB hints. Implementation has not started yet.
- [x] (2026-04-04 11:56 America/Toronto) Refined the plan so phase 1 stays additive: EPUB structure hints enrich candidate evidence, block annotations, and diagnostics without adding a second negative-suppression path on top of existing nav/TOC guardrails.
- [x] (2026-04-04 12:14 America/Toronto) Reviewed the sample EPUBs under `data/input/full book` and updated the plan to prioritize semantic class/id token evidence, mixed TOC-vs-recipe edge cases, and graceful no-op behavior for weakly structured narrative books.
- [ ] Add a dedicated EPUB structure-hints module that converts preserved structural clues into explicit positive and negative evidence.
- [ ] Thread structure hints into `cookimport/plugins/epub.py` so they can enrich proposals, annotate blocks, and emit a dedicated raw diagnostics artifact.
- [ ] Add focused ingestion/parsing tests that prove the helper is conservative, additive, and does not change importer authority.
- [ ] Update ingestion, parsing, and plain-English docs to explain that EPUB remains block-first but can emit structure-aware hints when the source provides them.

## Surprises & Discoveries

- Observation: The current EPUB importer already preserves enough raw material to support this idea without inventing a second pipeline.
  Evidence: `cookimport/plugins/epub.py` writes per-block `html` into block features when available, preserves `spine_index`, emits `candidate_recipe_region` `SourceSupport`, and records `pattern_diagnostics.json`.

- Observation: EPUB already has importer-specific deterministic structure preservation for tables.
  Evidence: `docs/04-parsing/04-parsing_readme.md` documents `cookimport/parsing/epub_table_rows.py`, which preserves EPUB `<tr>` rows as structured cell arrays instead of flattening them away.

- Observation: The shared section detector already knows how to reason over block sequences and block features.
  Evidence: `cookimport/parsing/section_detector.py::detect_sections_from_blocks(...)` accepts normalized `Block` objects and can be reused instead of creating a parallel section parser.

- Observation: The repo already has a good authority boundary for this work.
  Evidence: importer output still converges on canonical `sourceBlocks`, optional `sourceSupport`, raw artifacts, and a report. That makes it safe to add evidence packaging without changing later stage ownership.

- Observation: The strongest explicit negative EPUB cases already have deterministic guardrails before any new structure-hints layer exists.
  Evidence: `cookimport/plugins/epub.py` skips nav/TOC spine documents up front, and `docs/04-parsing/04-parsing_readme.md` documents `pattern_flags.py` as already detecting TOC-like clusters before candidate extraction.

- Observation: In the sampled EPUBs, the strongest recipe structure is usually carried by semantic `class` names rather than by rich HTML5 layout tags.
  Evidence: `DinnerFor2.epub` uses classes like `yield`, `headnote`, `ingredients`, and `method`; `RoastChickenAndOtherStories.epub` uses `recipe-title`, `ingredient`, and `ingredients-title`; `SweetEnoughADessertCookbook.epub` uses `ingredients_list` and `recipe_notes`; `TheFoodLab.epub` uses `recipe_i`, `recipe_rsteps1`, and `recipe_y`; `WhatGoodCooksKnow.epub` uses `recipe_title`, `ingredients`, `yield`, and `step`.

- Observation: Tag shape alone is not a reliable positive signal across these books.
  Evidence: Several sampled recipe-heavy EPUBs express recipe content mainly through `<p>` and `<div>` blocks with semantic classes, while list and table markup is sparse, absent, or used primarily for reference/chart content.

- Observation: Some books mix chapter-local TOC or index furniture with nearby recipe content instead of isolating all navigation into a single dedicated nav document.
  Evidence: `WhatGoodCooksKnow.epub` contains `chapter_toc`, `ch_toc_head`, and `ch_toc_text` classes inside chapter documents, and `SeaAndSmoke.epub` / `TheFoodLab.epub` also include `Contents`-like or TOC-like local documents beyond a single canonical nav surface.

- Observation: Some cookbook EPUBs are only weakly structured from a recipe perspective and should not be forced through an over-eager structure layer.
  Evidence: `SaltFatAcidHeat.epub` and `SeaAndSmoke.epub` are dominated by prose-oriented classes and chapter narrative markup, with little reusable recipe-specific structural markup.

## Decision Log

- Decision: EPUB remains a block-first importer after this work.
  Rationale: EPUB sources are still documents, not trustworthy exported recipe-object graphs. Promoting them to structured-export-first would blur the authority boundary and create an EPUB-only semantic path that the repo does not want.
  Date/Author: 2026-04-02 / Codex

- Decision: Structure will be used only as additive evidence, not as final recipe authority.
  Rationale: This matches the project's stated boundary that deterministic code packages evidence and LLM or later semantic stages make fuzzy semantic calls. Importer output may suggest, but not decide.
  Date/Author: 2026-04-02 / Codex

- Decision: Phase 1 should not add a new user-facing run setting.
  Rationale: The likely implementation is opportunistic and low-risk: if the extractor preserved useful structure, use it; if not, do nothing. Adding a new knob would increase run-settings surface area before there is evidence that tuning is needed.
  Date/Author: 2026-04-02 / Codex

- Decision: The safest implementation shape is a dedicated EPUB structure-hints helper that runs after block extraction and before final proposal assembly.
  Rationale: This keeps structure reasoning in one deterministic module, avoids scattering HTML heuristics through `cookimport/plugins/epub.py`, and makes the feature testable with synthetic fixtures.
  Date/Author: 2026-04-02 / Codex

- Decision: Negative structural evidence should be preserved as explicit document-structure evidence, not promoted into a new suppression path in phase 1.
  Rationale: Positive hints can be safely additive, but negative hints are riskier. The strongest explicit negative cases are already covered by existing nav/TOC skip logic and pattern diagnostics, so a new suppression path should not be added in phase 1.
  Date/Author: 2026-04-02 / Codex

- Decision: Phase 1 will record negative structure evidence in diagnostics, but it will not introduce new structure-based candidate suppression.
  Rationale: This keeps the first implementation useful without stacking another exclusion system on top of guardrails that already exist. It also makes false-negative regressions much less likely while still packaging the evidence needed to evaluate whether a later suppression pass is justified.
  Date/Author: 2026-04-04 / Codex

- Decision: The helper must treat normalized semantic `class` and `id` tokens as first-class EPUB structure evidence.
  Rationale: Real sampled EPUBs often encode recipe roles through CSS-oriented semantic tokens such as `recipe-title`, `ingredients_list`, `method`, `recipe_i`, `recipe_y`, and `step`, even when the surrounding HTML tag structure is shallow.
  Date/Author: 2026-04-04 / Codex

- Decision: Positive structure evidence must not depend on `<ul>`, `<ol>`, or `<table>` tags being present.
  Rationale: Those tags are useful when available, but the sample shows that many recipe EPUBs express ingredient and instruction structure as paragraphs or divs with semantic class names. A tag-first design would miss too many good cases.
  Date/Author: 2026-04-04 / Codex

- Decision: Negative structure evidence should be emitted as local ranges with concrete signals, not as broad document-level verdicts.
  Rationale: Some EPUBs contain chapter-local TOC or index-like furniture near real recipe content. Localized evidence is safer and more inspectable than declaring an entire spine document "non-recipe" based on one structural motif.
  Date/Author: 2026-04-04 / Codex

- Decision: Validation must cover four EPUB archetypes: class-semantic recipe books, list/table-assisted recipe books, mixed TOC-plus-recipe books, and weak-structure narrative books.
  Rationale: The sampled EPUBs span all four shapes, and the helper will only be trustworthy if tests prove it helps on the first two without hurting the latter two.
  Date/Author: 2026-04-04 / Codex

## Outcomes & Retrospective

The plan is drafted and the current seams are understood. No implementation has landed yet, so there is no runtime outcome to report. The key design outcome so far is that the feature should be framed as "structure-aware block-first EPUB importing," not as a fourth importer mode and not as an EPUB-specific structured-export path. The plan now also makes phase 1 narrower and more concrete: additive structure evidence, block annotations, and diagnostics first; semantic `class`/`id` tokens are first-class evidence; any new structure-driven candidate suppression only if later evidence shows the existing guardrails are insufficient.

## Context and Orientation

The current EPUB importer lives in [cookimport/plugins/epub.py](/home/mcnal/projects/recipeimport/cookimport/plugins/epub.py). It reads EPUB spine content, extracts a linear list of `Block` objects, runs deterministic pattern filtering, segments candidate recipe ranges, and finally returns a `ConversionResult` that contains canonical `sourceBlocks`, optional `sourceSupport`, raw artifacts, and a conversion report. In this repository, a `Block` is the normalized document unit used across later stages. A `SourceSupport` entry is a truthful importer-supplied hint, not final authority. The importer already emits `candidate_recipe_region` proposals, but those proposals are mostly derived from document flow and existing splitter logic rather than a first-class structure-evidence pass.

The structure already preserved today matters. [cookimport/plugins/epub.py](/home/mcnal/projects/recipeimport/cookimport/plugins/epub.py) writes `html` into block features when available, preserves `spine_index`, and keeps structured EPUB table rows through [cookimport/parsing/epub_table_rows.py](/home/mcnal/projects/recipeimport/cookimport/parsing/epub_table_rows.py). The shared section detector in [cookimport/parsing/section_detector.py](/home/mcnal/projects/recipeimport/cookimport/parsing/section_detector.py) can detect ingredient, instruction, note, and other spans from a block sequence. This is the right seam for a structure-aware helper because it already operates on normalized blocks rather than raw source-specific objects.

The current negative guardrails also matter. [cookimport/plugins/epub.py](/home/mcnal/projects/recipeimport/cookimport/plugins/epub.py) already skips explicit navigation and table-of-contents spine documents before block extraction, and deterministic pattern flags already mark TOC-like clusters before candidate extraction. That means this plan does not need to invent another exclusion layer just to be useful. The first implementation can focus on richer positive evidence and clearer diagnostics.

The sampled EPUBs also show what "structure" really means in practice. Sometimes it is true document structure such as headings, lists, or tables. Very often it is CSS-style semantic markup carried in `class` or `id` attributes on otherwise plain `<p>` or `<div>` blocks. Examples from the sample set include `recipe-title`, `ingredient`, `ingredients-title`, `yield`, `method`, `ingredients_list`, `recipe_notes`, `recipe_i`, `recipe_rsteps1`, `recipe_y`, `recipe_title`, and `step`. The helper must treat those normalized semantic tokens as evidence. It must also tolerate books where these signals barely exist at all, such as narrative-heavy cookbooks whose EPUBs are mostly prose chapters with styling classes rather than explicit recipe markup.

For this plan, "structure-aware block-first" means the importer continues to produce one ordered block stream as the truthful source model, but it also packages evidence derived from headings, lists, tables, explicit navigation markup, and similar document structure when that structure survives extraction. It does not synthesize final recipe objects. It does not bypass recipe-boundary. It does not claim that every EPUB with nice HTML is a structured export.

The most relevant files for implementation are:

`cookimport/plugins/epub.py` is the EPUB conversion orchestrator. It currently extracts blocks, runs `detect_deterministic_patterns(...)`, calls `_detect_candidates(...)`, applies the multi-recipe splitter, and emits `candidate_recipe_region` support payloads.

`cookimport/parsing/section_detector.py` is the shared deterministic section detector that can turn a sequence of lines or blocks into ingredients, instructions, notes, and other spans.

`cookimport/parsing/epub_table_rows.py` is the existing structured-table preservation seam for EPUB rows.

`tests/ingestion/test_epub_importer.py` and `tests/ingestion/test_epub_extraction_quickwins.py` are the primary importer-level test seams.

`tests/parsing/test_section_detector.py` is the shared section-detection test seam.

`docs/03-ingestion/03-ingestion_readme.md`, `docs/04-parsing/04-parsing_readme.md`, and `docs/plain-english-explanation.md` will need updates once behavior changes.

## Milestone 1: Add A Dedicated EPUB Structure-Hints Layer

This milestone creates one deterministic helper that inspects normalized EPUB blocks and preserved structural metadata, then returns explicit structure evidence. At the end of this milestone, the repo will have a single place where EPUB-only structure logic lives, with tests proving that it can recognize strong positive recipe evidence and explicit negative document-structure evidence without changing later authority. The proof for this milestone is a focused test suite over synthetic block sequences and preserved HTML/table metadata.

Create a new helper module at [cookimport/parsing/epub_structure_hints.py](/home/mcnal/projects/recipeimport/cookimport/parsing/epub_structure_hints.py). Define a small result model in plain deterministic terms. The exact class names may vary, but the module must expose one stable public function that looks like:

    collect_epub_structure_hints(blocks: list[Block]) -> EpubStructureHintsResult

The result object must contain four categories of output.

First, per-block annotations that can be safely attached back onto block features. These are facts such as "this block came from a heading-like HTML element," "this block came from a list item," "this block came from a table row," "this block carries semantic class tokens that look ingredient-like or instruction-like," or "this block appears inside navigation-like structure." These are not recipe claims. They are source-shape facts.

Second, positive structure spans that suggest a recipe-like region. A span should be created only when the helper can point to specific evidence such as a title-like heading followed nearby by ingredient and instruction sections, a semantic recipe-title token followed by ingredient-like and instruction-like block runs, or a heading followed by structured table/list content that looks like recipe body proof. The helper must not create a positive span from a heading alone, and it must not require list or table tags when semantic class evidence already provides body proof.

Third, negative structure spans that identify obviously document-like regions such as navigation clusters, table-of-contents sections, index runs, chapter-local recipe-preview lists, or other explicit non-recipe structure. In phase 1 these spans exist to package evidence and diagnostics, not to create a new exclusion path. Only explicit document-structure signals should produce a negative span in phase 1. Weak semantic guesses such as "this feels like an essay" are out of scope.

Fourth, a compact diagnostics payload that can be written as a raw artifact. This payload should summarize which signals were found, on which block ranges, and which spans were classified as positive or negative.

Keep the helper deterministic and source-first. It may use block text, block features, preserved `html`, normalized `class` and `id` tokens extracted from that HTML, and the existing section detector, but it must not try to infer cookbook meaning from broad semantic heuristics. Use the shared section detector to identify ingredient and instruction runs over the block sequence rather than cloning section logic into a new EPUB-only parser.

In this milestone, do not change `cookimport/plugins/epub.py` behavior yet beyond wiring the helper into isolated tests if needed. The goal is to create a testable evidence layer first.

## Milestone 2: Enrich EPUB Candidate Proposals And Diagnostics

This milestone wires the structure-hints helper into the live EPUB importer. At the end of this milestone, EPUB conversion will still produce one block stream, but candidate proposals and debug artifacts will be able to cite structure-backed evidence. The proof for this milestone is that structured EPUB fixtures yield richer `sourceSupport` payloads and a new structure-hints raw artifact, while messy or structure-poor fixtures still behave like normal block-first EPUB imports.

Update [cookimport/plugins/epub.py](/home/mcnal/projects/recipeimport/cookimport/plugins/epub.py) after block extraction and deterministic pattern detection. The new order should be:

1. extract EPUB blocks
2. run existing pattern diagnostics
3. run `collect_epub_structure_hints(blocks)`
4. attach safe source-shape annotations back onto blocks
5. run the existing `_detect_candidates(...)`
6. merge the base candidate ranges with positive structure spans
7. emit final `candidate_recipe_region` `SourceSupport` entries with both old and new evidence attached, plus a dedicated structure-hints artifact

The merge rules must stay conservative. The existing text-flow candidate detector remains primary. Positive structure spans should enrich an overlapping candidate whenever one already exists. A new candidate span may be added only when the structure evidence includes both a title anchor and body proof. In practical terms, a heading plus a nearby ingredient run and instruction run is strong enough, and a semantic recipe-title token plus nearby ingredient-like and instruction-like class-backed runs is also strong enough. List markup or table markup can help, but they are optional supporting evidence rather than required proof.

For negative structure evidence, phase 1 records it but does not use it to suppress candidates. Examples include navigation landmarks, table-of-contents clusters, or equivalent extracted structure that already says "this is navigation-like source furniture." The helper should package that evidence in a stable way so runs can be inspected later, but candidate suppression continues to come only from the existing importer skip logic and pattern diagnostics already in the pipeline.

When emitting final `candidate_recipe_region` proposals, extend the payload to include structure evidence in a stable, inspectable way. A payload should continue to record `candidate_index`, block ranges, segmentation score, pattern actions, and multi-recipe metadata. Add a new field such as `structure_hints` that contains concise evidence records. Each evidence record should name the signal family, the concrete normalized signal tokens or tag facts that fired, the relevant local block range, and whether it supported or opposed the candidate. Keep the payload small enough to remain readable in artifacts.

Also write a new raw artifact such as `structure_hints.json` under the normal EPUB raw-artifact tree. This artifact should summarize the positive spans, negative spans, signal counts, and any block-level annotations that were strong enough to matter. It becomes the debugging surface for this feature.

Finally, annotate canonical source blocks with only source-shape facts that are safe to preserve downstream. Examples include `structure_role`, `html_tag` when known, `html_classes` or normalized semantic tokens when known, `is_navigation_like`, `is_heading_like`, `is_list_like`, and `is_table_row_like`. Avoid adding features that claim recipe truth such as `is_recipe_title`. The importer packages evidence; later stages decide authority.

## Milestone 3: Prove The Layer Stays Additive And Useful

This milestone verifies that the importer became more informative without silently becoming authoritative. At the end of this milestone, focused tests will show that structure-aware hints change evidence and candidate quality, not ownership rules. The proof is behavioral: the importer still emits canonical blocks plus proposals, not final EPUB recipes, and the new helper stays conservative around ambiguous structure.

Extend or add importer tests under [tests/ingestion/test_epub_importer.py](/home/mcnal/projects/recipeimport/tests/ingestion/test_epub_importer.py) and a new focused file such as [tests/ingestion/test_epub_structure_hints.py](/home/mcnal/projects/recipeimport/tests/ingestion/test_epub_structure_hints.py). These tests should cover:

one structured positive case where a heading plus ingredient and instruction sections produces a proposal payload with structure-backed evidence

one explicit navigation or table-of-contents case where negative structure evidence is recorded in diagnostics without adding a second suppression path beyond the importer logic that already skips explicit nav documents

one mixed TOC-plus-recipe case where chapter-local preview or TOC furniture produces negative diagnostic ranges while nearby real recipe structure still remains eligible for normal candidate detection

one class-semantic case where recipe evidence comes primarily from semantic `class` tokens on `<p>` or `<div>` blocks rather than from list tags

one ambiguous or weak-structure narrative case where structure is present but not strong enough to create a new candidate or materially rewrite the base candidate evidence, proving the helper stays conservative

one case that preserves EPUB table rows and uses them only as evidence, not as automatic recipe acceptance

Add a small shared parsing test, likely in [tests/parsing/test_section_detector.py](/home/mcnal/projects/recipeimport/tests/parsing/test_section_detector.py) or a new EPUB-specific parsing test, that proves the structure helper uses the shared section detector consistently over block sequences.

Add an importer-level assertion that the final `ConversionResult` still uses `recipes=[]` and exposes structure hints only through `sourceBlocks`, `sourceSupport`, and raw artifacts. That is the authority-boundary proof needed for this phase.

## Plan of Work

Start by creating the dedicated helper module [cookimport/parsing/epub_structure_hints.py](/home/mcnal/projects/recipeimport/cookimport/parsing/epub_structure_hints.py). Keep the public API small and deterministic. The helper should accept normalized EPUB blocks and return a result object that contains block annotations, positive spans, negative spans, and a diagnostics payload. Reuse [cookimport/parsing/section_detector.py](/home/mcnal/projects/recipeimport/cookimport/parsing/section_detector.py) for ingredient and instruction span detection. Reuse preserved block `html` and existing feature dictionaries rather than parsing the original EPUB container again. Normalize semantic `class` and `id` tokens from preserved block HTML into a small deterministic vocabulary that the helper can score without depending on publisher-specific exact strings.

After the helper exists, update [cookimport/plugins/epub.py](/home/mcnal/projects/recipeimport/cookimport/plugins/epub.py) to call it immediately after `detect_deterministic_patterns(blocks)` and before final `SourceSupport` assembly. The importer should attach safe block annotations, preserve negative structure evidence in diagnostics, and merge positive structure spans into the candidate proposal list conservatively. Keep `_detect_candidates(...)` in place. Do not replace it. This feature is an enrichment layer over the current importer, not a rewrite of the importer around HTML semantics.

Once structure spans and diagnostics are flowing, add a raw artifact writer for `structure_hints.json` and extend `candidate_recipe_region` payloads with concise `structure_hints` entries. The payload should remain understandable to a human debugging a run. Do not bury the meaning inside opaque score fields alone.

Then write tests in the ingestion and parsing suites. Use small synthetic block fixtures or XHTML snippets wherever possible so failures are easy to diagnose. Prefer a new dedicated EPUB structure-hints test file over growing existing importer tests into unreadable long fixtures. Make sure the fixtures represent the four sampled archetypes: class-semantic recipe books, list/table-assisted recipe books, mixed TOC-plus-recipe books, and weak-structure narrative books.

Finally, update the docs. [docs/03-ingestion/03-ingestion_readme.md](/home/mcnal/projects/recipeimport/docs/03-ingestion/03-ingestion_readme.md) should explain that EPUB remains block-first but may package structure-aware evidence when extractors preserve enough structure. [docs/04-parsing/04-parsing_readme.md](/home/mcnal/projects/recipeimport/docs/04-parsing/04-parsing_readme.md) should describe the new helper and the rule that it uses shared section detection plus preserved HTML/table metadata. [docs/plain-english-explanation.md](/home/mcnal/projects/recipeimport/docs/plain-english-explanation.md) should be updated in plain language so the record-first versus block-first distinction is still accurate while acknowledging that block-first EPUB import can still leverage source structure as hints.

## Concrete Steps

All commands below are run from `/home/mcnal/projects/recipeimport`.

Prepare the project-local virtual environment before testing:

    test -x .venv/bin/python || python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .[dev]

Use narrow diagnostic loops while building the helper and importer wiring:

    . .venv/bin/activate
    .venv/bin/pytest tests/ingestion/test_epub_importer.py
    .venv/bin/pytest tests/ingestion/test_epub_extraction_quickwins.py
    .venv/bin/pytest tests/parsing/test_section_detector.py

After the new focused EPUB structure-hints tests exist, run them directly during iteration:

    . .venv/bin/activate
    .venv/bin/pytest tests/ingestion/test_epub_structure_hints.py

Once focused tests pass, run the repo-preferred domain suites that cover the importer and downstream contract:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain ingestion

Do not run Codex-backed benchmark or book-processing jobs for this work without explicit user approval. The intended validation path is deterministic and fixture-driven.

## Validation and Acceptance

Acceptance is behavioral.

For positive structure-aware evidence:

1. An EPUB fixture with a title heading, nearby ingredient structure, and nearby instruction structure produces one or more `candidate_recipe_region` proposals whose payloads include explicit `structure_hints`.
2. The corresponding raw artifact tree contains a readable `structure_hints.json` artifact that explains why the importer considered that region recipe-like.
3. The canonical block stream remains a normal ordered EPUB block archive. No final recipe objects are emitted directly by the importer.
4. At least one acceptance fixture proves that class-based semantic structure without list markup can still produce useful positive evidence.

For negative structure-aware evidence:

1. An EPUB fixture that is explicitly navigation-like or table-of-contents-like records negative structure evidence.
2. Phase 1 does not introduce any new structure-based candidate suppression behavior.
3. Ambiguous structural noise is recorded in diagnostics but does not create or delete candidates by itself.
4. A mixed TOC-plus-recipe fixture proves the helper can localize negative evidence without poisoning a whole spine document.

For authority boundaries:

1. Recipe-boundary and later stages still make the authoritative recipe decision.
2. The importer still returns `recipes=[]` and exposes hints only through canonical blocks, proposal support, and raw artifacts.
3. No new code path allows EPUB importing to skip canonical blocks and hand later stages a final recipe object graph.

For docs:

1. The ingestion and parsing docs say clearly that EPUB is still block-first.
2. The plain-English explanation says clearly that block-first EPUB importing may still leverage internal structure as hints without becoming structured-export-first.

## Idempotence and Recovery

This change should be implemented additively and in the same order as the milestones. The safest recovery path is to land the helper and its tests before using it to affect candidate assembly. If the helper proves too noisy at first, keep its diagnostics artifact and block annotations while tightening or removing the positive merge rules that caused noise. Do not leave the repo in a mixed state where the helper exists but its payload format or annotations are unstable across tests and docs.

No destructive migration is required. If a particular structural signal turns out to be unreliable, remove that signal from the helper and keep the surrounding result format stable. Favor deleting a noisy hint over widening the importer's authority boundary or adding new suppression behavior too early.

## Artifacts and Notes

The key runtime artifacts after implementation should be:

`candidate_recipe_region` support entries whose payloads include concise `structure_hints`

`raw/epub/.../structure_hints.json` summarizing positive spans, negative spans, and signal counts

canonical source blocks with source-shape annotations such as heading/list/navigation facts when those facts are known

Keep the artifact payloads concise. They should help a human understand "what structural evidence did the importer see?" without reading source code.

## Interfaces and Dependencies

In [cookimport/parsing/epub_structure_hints.py](/home/mcnal/projects/recipeimport/cookimport/parsing/epub_structure_hints.py), define one public deterministic entry point and a small result model. The result model must include:

    block_annotations: dict[int, dict[str, Any]]
    positive_spans: list[...]
    negative_spans: list[...]
    diagnostics: dict[str, Any]

The exact dataclass names are up to the implementer, but the semantics are not optional. The result must distinguish positive and negative evidence explicitly, and block annotations must remain source-shape facts rather than recipe-truth claims.

The helper must expose or internally use a deterministic normalization pass for semantic HTML tokens. The normalization should:

- read `class` and `id` tokens from preserved block HTML when available
- lowercase and split those tokens into stable comparable units
- map obviously recipe-like publisher tokens such as `recipe-title`, `recipe_title`, `recipe_rt`, `ingredients_list`, `ingredient`, `ingredients`, `method`, `step`, `recipe_i`, `recipe_rsteps`, `recipe_y`, `yield`, and `headnote` into a small normalized vocabulary
- map obviously navigation-like publisher tokens such as `toc`, `chapter_toc`, `index`, `indexoffset`, `ch_toc_head`, and `ch_toc_text` into a small normalized vocabulary
- preserve the original tokens in diagnostics so a human can see exactly what fired

The normalization layer should be narrow and evidence-oriented. It should not attempt to infer arbitrary cookbook semantics from every CSS class in the wild.

In [cookimport/plugins/epub.py](/home/mcnal/projects/recipeimport/cookimport/plugins/epub.py), the final importer contract after this work must still end with:

    return ConversionResult(
        recipes=[],
        sourceBlocks=...,
        sourceSupport=...,
        rawArtifacts=...,
        report=...,
        ...
    )

That `recipes=[]` line is important to the design. It proves the importer remains source-first and block-first.

This plan now scopes phase 1 to additive structure evidence, safe block annotations, and diagnostics, leaving any new structure-based suppression for a later follow-up only if the existing skip and pattern guardrails prove insufficient. The strongest implementation direction from the sampled EPUBs is class-aware and conservative: trust normalized semantic markup when it exists, treat list/table tags as supporting evidence rather than the main event, and degrade gracefully when a book is mostly prose or styling noise.
