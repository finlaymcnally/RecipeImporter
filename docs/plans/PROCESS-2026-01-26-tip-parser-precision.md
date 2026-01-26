---
summary: "ExecPlan to improve tip/knowledge precision by filtering narrative text and tightening general-tip rules."
read_when:
  - When improving tip/knowledge extraction accuracy or reducing narrative tip output
---

# Improve tip/knowledge precision (heuristic pass)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

The file `docs/PLANS.md` in the repository root defines the required ExecPlan format and workflow. This plan must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

The current tip output is polluted with narrative sentences from cookbook prose, especially in EPUB standalone blocks. After this change, running `cookimport stage` should emit a smaller set of higher-signal tips that read like general advice (“rest meat before slicing because…”), while story-like sentences (“in my mind…”, “I once…”) are dropped or kept only as recipe-specific notes. The user will observe the difference by staging an EPUB (e.g., The Food Lab) and seeing the tips folder contain more actionable advice and fewer narrative snippets.

## Progress

- [x] (2026-01-26 02:40Z) Review current tip extraction heuristics and identify why narrative sentences are passing the tip filter.
- [x] (2026-01-26 02:55Z) Implement stronger advice gating + narrative rejection in `cookimport/parsing/tips.py` (including header/prefix strength).
- [x] (2026-01-26 03:05Z) Update tests to cover narrative rejection and new advice-positive extraction cases.
- [x] (2026-01-26 03:10Z) Update parsing documentation and add a short understanding note about tip extraction pitfalls.
- [x] (2026-01-26 03:15Z) Run tests in a local venv and record results.
- [x] (2026-01-26 04:05Z) Add cooking-anchor gating for standalone tips and expand taxonomy anchors (salt/seasoning).
- [x] (2026-01-26 04:10Z) Add tips summary markdown output and update staging/docs/tests.
- [x] (2026-01-26 04:45Z) Add dish taxonomy and cooking-method tag category; update anchors/tests/docs.
- [x] (2026-01-26 05:05Z) Extend standalone tip acceptance with explanation cues and enrich tips.md with ids/anchors and grouping.
- [x] (2026-01-26 05:35Z) Add topic chunking for standalone blocks and refine tool/ingredient anchors.
- [x] (2026-01-26 06:05Z) Add topic candidate outputs and evaluation harness scaffolding.
- [x] (2026-01-26 07:20Z) Include detected topic headers in `tips.md` summaries for grouped tips.

## Surprises & Discoveries

- Observation: EPUB standalone blocks are scanned for tips without any header filtering, so weak advice cues (“aim to”, “better”) can cause story-like prose to pass the tip threshold.
  Evidence: `cookimport/plugins/epub.py::_extract_standalone_tips` passes every non-recipe block to `extract_tip_candidates`.
- Observation: The “short tip” guardrail (`_MIN_GENERAL_WORDS`) demoted explicit advice like “Salt food regularly…” unless benefit/advice cues were allowed to override it.
  Evidence: `tests/test_tip_extraction.py::test_extract_standalone_tip_with_advice_cue` failed until benefit/advice overrides were added.

## Decision Log

- Decision: Require an explicit advice anchor (strong tip header/prefix, imperative start, diagnostic cue, benefit cue, or strong advice modal) before accepting standalone tips.
  Rationale: Narrative prose often contains weak advice words but lacks clear directive structure.
  Date/Author: 2026-01-26 / Codex
- Decision: Treat “note”/“hint” headers and prefixes as weaker signals that must be paired with advice cues.
  Rationale: Many cookbooks use “note” for narrative or background that is not actionable guidance.
  Date/Author: 2026-01-26 / Codex
- Decision: Boost generality scoring for strong imperatives/benefit cues and allow short tips to survive when they include explicit benefit/advice language.
  Rationale: Keeps concise, actionable tips while still rejecting terse narrative fragments.
  Date/Author: 2026-01-26 / Codex
- Decision: Require cooking anchors (ingredient/technique/tool keywords) for standalone tips, and avoid counting bare “never/always” as strong advice.
  Rationale: Filters science/narrative statements that lack actionable cooking context while preserving imperative tips.
  Date/Author: 2026-01-26 / Codex
- Decision: Write `tips.md` alongside `t*.json` outputs for quick review.
  Rationale: Reviewer-friendly scan of all tip text without opening each JSON file.
  Date/Author: 2026-01-26 / Codex
- Decision: Introduce `dishes` and `cookingMethods` tag categories and split cooking methods from general techniques.
  Rationale: Supports dynamic surfacing of tips by dish and by heat application method, per user feedback.
  Date/Author: 2026-01-26 / Codex
- Decision: Allow anchored explanatory tips without explicit advice cues when they are long and non-narrative.
  Rationale: Increases recall for scientific explanations tied to cooking concepts without admitting pure narrative.
  Date/Author: 2026-01-26 / Codex
- Decision: Include `t{index}` ids and anchor tags in tips.md and group tips by source block.
  Rationale: Improves review workflow and merges short related tips into longer summaries.
  Date/Author: 2026-01-26 / Codex
- Decision: Merge standalone blocks into topic chunks based on header cues + anchor overlap before extraction.
  Rationale: Increases tip length and reduces “too short” fragments while keeping topic boundaries.
  Date/Author: 2026-01-26 / Codex
- Decision: Emit topic candidates + add a small evaluation harness to label and score tip extraction.
  Rationale: Provides measurable feedback loop and LLM-ready prefiltering inputs.
  Date/Author: 2026-01-26 / Codex
- Decision: Surface topic headers in `tips.md` when available.
  Rationale: Keeps question/section titles (e.g., “Which salt should I use?”) visible in grouped tip summaries.
  Date/Author: 2026-01-26 / Codex

## Outcomes & Retrospective

Tip parsing now requires explicit advice anchors and filters narrative first-person prose unless paired with advice language. Header/prefix strength is tracked so “note” is treated as a weaker signal than “tip”. Generality scoring now favors strong imperatives and benefit cues, and short tips with explicit benefit/advice remain eligible. Standalone tips also require cooking anchors (dish/ingredient/technique/tool/cooking-method keywords) but can pass via explanatory cues when long and non-narrative. Standalone blocks are merged into topic chunks (header + anchor overlap) before extraction, improving tip length. `tips.md` summaries are written alongside tip JSON files with `t{index}` ids, anchor tags, grouping by source block, and any detected topic headers. Tips now include `dishes` and `cookingMethods` tags. Topic candidates are emitted to `topic_candidates.json`/`topic_candidates.md`, and `tools/tip_eval.py` provides a labeling/scoring harness. Tests were updated and `pytest` passes.

## Context and Orientation

Tip extraction lives in `cookimport/parsing/tips.py`. The extraction flow splits text into blocks/sentences, assigns a tipness score, repairs dependent fragments, and classifies each span as `general`, `recipe_specific`, or `not_tip`. For EPUB, `cookimport/plugins/epub.py` calls `extract_tip_candidates` on every block outside recipe ranges; these standalone blocks are a major source of narrative false positives. The output writer (`cookimport/staging/writer.py`) exports only `general` + `standalone` tips to `tips/{workbook}/t*.json`.

## Plan of Work

First, extend the tip parser to recognize strong advice anchors and to reject narrative-first-person prose unless a clear advice cue is present. This will require adjusting tip-prefix/header strength detection, expanding narrative detection, and refining tipness scoring to down-weight weak cues like “better” without an advice structure. Apply stricter gating for `standalone_block` sources so that only text with an explicit advice anchor can be classified as a general tip.

Next, update or add tests in `tests/test_tip_extraction.py` to cover: a general advice sentence without a header now being accepted, a first-person narrative sentence being rejected, and weak “note” headers requiring explicit advice. Ensure existing recipe-specific behavior remains intact.

Finally, update `cookimport/parsing/README.md` with a short note describing the new advice-anchor requirement and narrative filtering. Add a short understanding note in `docs/understandings/` summarizing the discovered failure mode and the new guardrails.

## Concrete Steps

From `/home/mcnal/projects/recipeimport`:

1) Edit `cookimport/parsing/tips.py` to add advice-anchor detection, header/prefix strength, and narrative rejection logic.
2) Update `tests/test_tip_extraction.py` with new expectations and cases.
3) Update `cookimport/parsing/README.md` with a short note about the new gating behavior.
4) Add a short understanding note in `docs/understandings/`.
5) Run tests in a local venv:

   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -e .[dev]
   pytest

## Validation and Acceptance

- Running `cookimport stage` on an EPUB with narrative prose yields tips that are predominantly actionable advice and no longer include obvious story-like sentences.
- `pytest` passes; new/updated tests fail before the change and pass after.

## Idempotence and Recovery

All changes are additive and safe to re-run. If stricter gating removes too many tips, thresholds and advice anchors can be tuned without changing data models or output schemas.

## Artifacts and Notes

Test run: `pytest` (69 passed, 2 warnings about Pydantic deprecation and BeautifulSoup XML parsing).

## Interfaces and Dependencies

No new dependencies. Changes are limited to `cookimport/parsing/tips.py` and existing tests. Existing interfaces (`extract_tips`, `extract_tip_candidates`) remain stable.

Change note: Initial plan authored to improve tip parsing precision and reduce narrative tips. Reason: user request for higher-quality general tips and pre-LLM filtering.
Change note: Marked progress complete, recorded decisions/outcomes, and captured test results. Reason: implementation and validation finished.
Change note: Added cooking-anchor gating and tips summary output updates. Reason: user feedback on narrative tips and need for review-friendly output.
Change note: Added dish taxonomy + cooking method tags and updated anchors/tests/docs. Reason: user requested five anchor categories for tips.
Change note: Added explanatory cue allowance and enriched tips.md formatting with ids/anchors/grouping. Reason: user feedback on short tips and summary usefulness.
Change note: Added topic chunking for standalone blocks and refined anchor lists (tools/seasoning). Reason: user feedback on short tips and topic borders.
Change note: Added topic candidate outputs and evaluation harness docs/script. Reason: user asked for golden set scaffolding.
