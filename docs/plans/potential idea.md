---
summary: "Route obviously non-knowledge outside-recipe text off the knowledge path without adding any new LLM passes."
read_when:
  - When changing line-role labels, line-role worker output contracts, or outside-recipe suppression policy
  - When changing Stage 7 non-recipe ownership, knowledge-stage input eligibility, or `08_nonrecipe_spans.json`
  - When debugging why table-of-contents, copyright, navigation, or boilerplate text still reaches knowledge review
---

# Route obviously non-knowledge outside-recipe text off the knowledge path without adding any new LLM passes

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

Right now the first LLM stage in `cookimport/parsing/canonical_line_roles.py` spends a lot of effort on a hard outside-recipe question: whether each non-recipe line is `KNOWLEDGE` or `OTHER`. That is the noisiest part of the benchmark, and it forces the same model pass to solve recipe structure, outside-recipe semantics, and obvious junk filtering all at once. After this change, the line-role LLM will still do all recipe-local labeling, but it will stop being responsible for deciding broad outside-recipe `KNOWLEDGE` versus `OTHER`. Instead, it will do two simpler things outside recipes: leave normal outside-recipe text as provisional `OTHER`, and explicitly mark absurdly obvious non-knowledge material as “suppressed from knowledge review.”

The user-visible behavior after implementation is concrete. Running the normal stage path with the existing optional knowledge stage enabled should still produce `08_nonrecipe_spans.json` and `09_knowledge_outputs.json`, but obvious junk such as table-of-contents rows, running headers, copyright boilerplate, bare page numbers, and similar material should no longer reach the knowledge worker inputs. Those suppressed rows must remain visible in repo artifacts through a dedicated suppression ledger and summary counts, so a human can see exactly what was routed off, why it was routed off, and whether the rules or the LLM are being too aggressive. No new LLM pass is added. The existing line-role pass does the marking, and the existing optional knowledge pass only sees the unsuppressed remainder.

## Progress

- [x] (2026-03-22 02:22 EDT) Re-read `docs/PLANS.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/10-llm/10-llm_README.md`, and `docs/10-llm/nonrecipe_knowledge_review.md` to anchor this plan in the current label-first parsing and optional knowledge-review contracts.
- [x] (2026-03-22 02:27 EDT) Inspected the current line-role, label-source-of-truth, nonrecipe-stage, writer, and knowledge-orchestrator seams to confirm where suppression metadata and knowledge eligibility can be introduced without adding another LLM phase.
- [x] (2026-03-22 02:33 EDT) Authored this ExecPlan with the explicit constraint that no additional LLM passes may be added; the existing line-role pass is the only new decision point.
- [ ] Implementation has not started yet.
- [ ] Deterministic tests, stage-path validation, and benchmark validation remain to be added and recorded here during implementation.

## Surprises & Discoveries

- Observation: the current Stage 7 non-recipe authority already has a natural place to store “final other but not knowledge-review eligible.”
  Evidence: `cookimport/staging/nonrecipe_stage.py` already separates deterministic seed block categories from final refined categories, and `cookimport/staging/writer.py` already writes both seed and final views into `08_nonrecipe_spans.json`.

- Observation: the current line-role runtime has no field for “mark this OTHER line as suppressible.”
  Evidence: worker outputs are still effectively `{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}` and validators key primarily on `atomic_index` plus `label`. There is no explicit suppression channel today.

- Observation: recipe-span grouping does not require `KNOWLEDGE` specifically; it only needs non-recipe gap labels distinct from recipe-local labels.
  Evidence: `cookimport/parsing/recipe_span_grouping.py` bridges gaps using `_NONRECIPE_GAP_LABELS = {"KNOWLEDGE", "OTHER"}`. A conservative “outside recipe defaults to `OTHER`” approach can preserve grouping behavior.

- Observation: the current knowledge stage already operates on Stage 7 seed non-recipe spans rather than on raw line-role packets.
  Evidence: `docs/10-llm/nonrecipe_knowledge_review.md` and `cookimport/llm/codex_farm_knowledge_orchestrator.py` both describe knowledge input as “seed Stage 7 non-recipe spans.”

- Observation: a line-role-only benchmark will stop being the right quality gate if line-role no longer emits final `KNOWLEDGE`.
  Evidence: the current benchmark and several recent plans interpret line-role `KNOWLEDGE` versus `OTHER` errors directly. If line-role intentionally collapses unsuppressed outside-recipe text to provisional `OTHER`, a standalone line-role score will understate the final pipeline quality.

## Decision Log

- Decision: do not add any new LLM pass.
  Rationale: this plan must work within the existing LLM budget. The only semantic responsibilities changing are moved off the line-role pass and onto the already-existing optional knowledge review stage.
  Date/Author: 2026-03-22 / Codex

- Decision: keep the public final label taxonomy unchanged.
  Rationale: changing the user-facing labels would ripple through benchmarks, Label Studio exports, writer contracts, and downstream consumers. “Suppressed from knowledge review” is metadata, not a new final label.
  Date/Author: 2026-03-22 / Codex

- Decision: line-role will no longer be responsible for broad outside-recipe `KNOWLEDGE` promotion.
  Rationale: the current weak point is forcing one pass to solve recipe structure, prose semantics, and junk filtering simultaneously. Line-role should focus on recipe-local structure plus obvious suppression only.
  Date/Author: 2026-03-22 / Codex

- Decision: suppression must fail open.
  Rationale: the only safe hard-suppression targets are rows or blocks that are overwhelmingly obvious non-knowledge. Anything arguable must remain eligible for later knowledge review.
  Date/Author: 2026-03-22 / Codex

- Decision: suppression must be visible in first-class artifacts.
  Rationale: the user explicitly wants to inspect what got “removed.” The correct implementation is not silent filtering; it is explicit routing with counts, reasons, and line/block provenance.
  Date/Author: 2026-03-22 / Codex

- Decision: knowledge eligibility will be promoted from line-level annotations to block-level routing conservatively.
  Rationale: knowledge input operates on Stage 7 block/span ownership, not atomic lines. A block should be excluded from knowledge review only when its owned outside-recipe lines are all suppressed or when a block-level suppression pattern is explicitly proven.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

This plan has only been authored so far. No code or docs outside this plan have been changed yet.

The design target is clear: line-role becomes a recipe-structure-and-suppression pass, while the existing optional knowledge stage becomes the only place that still decides `knowledge` versus `other` for unsuppressed outside-recipe text. The main risks to watch during implementation are silent over-suppression, breaking line-role worker output compatibility, and continuing to read line-role-only benchmark scores as if they still measure final outside-recipe quality.

## Context and Orientation

The current label-first parsing path starts in `cookimport/parsing/label_source_of_truth.py`. That module atomizes archive blocks into labelable lines, calls `cookimport/parsing/canonical_line_roles.py` to assign one final line-role label per atomic line, then projects those labeled lines up to block labels and recipe spans. Recipe-span grouping happens in `cookimport/parsing/recipe_span_grouping.py`. The key fact for this plan is that the line-role stage currently tries to output one final global label for every line, including outside-recipe `KNOWLEDGE` and `OTHER`.

Stage 7 non-recipe ownership lives in `cookimport/staging/nonrecipe_stage.py`. That module looks at final block labels after recipe spans are accepted, keeps all non-recipe blocks, and assigns each non-recipe block a Stage 7 category of either `knowledge` or `other`. `cookimport/staging/writer.py` then writes that authoritative machine-readable state to `08_nonrecipe_spans.json`. If the optional knowledge stage is enabled, `cookimport/llm/codex_farm_knowledge_orchestrator.py` and `cookimport/llm/codex_farm_knowledge_jobs.py` take those seed non-recipe spans and ask the existing knowledge worker to refine `knowledge` versus `other`.

In this plan, “suppression” does not mean deleting a line or block from final artifacts. It means: “this outside-recipe text is so obviously not reusable cooking knowledge that it should be final `other` immediately and should not be sent into knowledge review.” Examples include table of contents rows with page-number leaders, isolated page numbers, running headers and footers, copyright boilerplate, ISBN / Library of Congress metadata, and similarly obvious navigation or publishing matter. Suppression must remain explicit metadata with a reason code such as `toc_leader_row` or `copyright_boilerplate`.

The line-role worker runtime lives in `cookimport/parsing/canonical_line_roles.py` plus `cookimport/llm/canonical_line_role_prompt.py`. The workers currently emit one row result with `atomic_index` and `label`. This plan requires extending that worker output contract to allow an optional suppression annotation for `OTHER` rows. The validator, recovery logic, prompt examples, and worker hints must all agree on that new field.

The important architectural choice is that this plan does not introduce a new label such as `SUPPRESSED_OTHER` or `NON_RECIPE_TEXT` into the public schema. Final labels remain the existing public labels. Suppression is a side-channel that influences later routing and artifacts, not a replacement taxonomy.

## Plan of Work

Start in `cookimport/parsing/canonical_line_roles.py` and `cookimport/llm/canonical_line_role_prompt.py`. Define a stage-local line-role output contract that still allows all recipe-local labels, still allows `OTHER`, but stops instructing the line-role worker to perform open-ended `KNOWLEDGE` promotion for outside-recipe text. The worker prompt should say plainly: identify recipe structure as before; for obviously non-knowledge outside-recipe junk, keep the line as `OTHER` and optionally mark it `suppressed_from_knowledge` with one allowed reason code; otherwise leave outside-recipe text as unsuppressed `OTHER`. The worker should not try to decide final `KNOWLEDGE` anymore.

Add a small, explicit suppression vocabulary owned by the repo. Keep it short and conservative. Good initial reason codes are: `toc_navigation`, `page_number_only`, `running_header_footer`, `copyright_legal`, `isbn_cataloging`, `publisher_metadata`, `index_navigation`, and `decorative_front_matter`. Every code must describe something a human can understand quickly in a ledger. Do not include fuzzy semantic categories such as `probably_not_knowledge` or `editorial_vibes`.

Extend `CanonicalLineRolePrediction` and the line-role worker output validator so each row may optionally carry suppression metadata. The minimum viable shape is one boolean plus one reason code. A good concrete output shape is `{"atomic_index":123,"label":"OTHER","suppressed_from_knowledge":true,"suppression_reason_code":"toc_navigation"}`. Validation must reject suppression on non-`OTHER` labels, reject unknown reason codes, and strip suppression automatically when the line is inside a recipe span or when the line is later rescued into a recipe-local label. Keep fallback behavior safe: if a malformed worker row tries to suppress with a bad reason, the row should still fall back to ordinary unsuppressed `OTHER` rather than silently preserving invalid metadata.

Then update the deterministic line-role baseline and sanitizer logic in `cookimport/parsing/canonical_line_roles.py`. The deterministic code should no longer promote outside-recipe `KNOWLEDGE` as a normal line-role end state. Instead it should produce either a recipe-local label or `OTHER`, with optional deterministic suppression tags only for truly obvious patterns. The line-role LLM can then preserve, clear, or add suppression tags within the allowed vocabulary. This keeps the line-role LLM useful for hard table-of-contents and boilerplate recognition without asking it to solve the full `KNOWLEDGE` problem. The existing `_outside_recipe_knowledge_label_allowed(...)` seam should not be deleted immediately; it should be retired deliberately after all callers are updated, because the optional knowledge stage and current benchmarks may still depend on it during migration.

Next, propagate suppression into authoritative line and block state in `cookimport/parsing/label_source_of_truth.py`. Add fields such as `suppressed_from_knowledge: bool = False` and `suppression_reason_code: str | None = None` to `AuthoritativeLabeledLine` and `AuthoritativeBlockLabel`. Block-level suppression must be conservative. If a block contains any unsuppressed outside-recipe line or any recipe-local label, the block remains knowledge-eligible. A block becomes suppressed only if all surviving relevant lines are `OTHER` with compatible suppression reasons or if a deterministic block-level rule proves that the whole block is the same obvious junk surface. Record both the promoted block-level suppression flag and the set of source atomic indices that caused it.

After that, update `cookimport/staging/nonrecipe_stage.py`. The Stage 7 category should remain `knowledge` or `other`, but the stage result must now carry suppression visibility and knowledge eligibility separately. Add fields to `NonRecipeSpan` and `NonRecipeStageResult` for suppression counts and for the exact block indices that are `other` and suppressed versus `other` and still knowledge-review-eligible. Do not redefine “other” itself. The final Stage 7 result should still say that suppressed blocks are `other`; it should additionally say that they were excluded from knowledge review and why.

Update `cookimport/staging/writer.py` so the routing is inspectable. `08_nonrecipe_spans.json` should gain summary counts such as `suppressed_other_blocks`, `knowledge_review_eligible_other_blocks`, and a block-index map or summary section showing which blocks were suppressed. In addition, write a new sibling artifact such as `08_nonrecipe_suppression.jsonl` that contains one row per suppressed line or block. Each row should include the stable line or block id, the text preview, the final category (`other`), the suppression reason code, and whether the suppression came from a deterministic baseline or a Codex-reviewed line-role correction. This file is the primary debugging surface for “what got removed.”

Then update the existing knowledge stage input builders in `cookimport/llm/codex_farm_knowledge_orchestrator.py` and `cookimport/llm/codex_farm_knowledge_jobs.py`. When the optional knowledge stage is enabled, its seed input should be the unsuppressed subset of Stage 7 `other` blocks plus any existing seed `knowledge` blocks if that path still exists during migration. Suppressed `other` blocks must remain present in `08_nonrecipe_spans.json`, but they must not contribute chunk text to `knowledge/in/*.json`. The knowledge manifest and task metadata should record how many blocks were suppressed upstream so the absence of those blocks from knowledge jobs is explainable.

Finally, update benchmark and validation expectations. A line-role-only benchmark should no longer be interpreted as the final authority on outside-recipe quality, because line-role is intentionally no longer producing final `KNOWLEDGE`. Add a collapsed reporting view for the line-role stage that treats outside-recipe `KNOWLEDGE` and unsuppressed `OTHER` as one provisional non-recipe bucket, or at minimum document that the promotion metric for this feature is the end-to-end staged output with the optional knowledge stage enabled. This is necessary to avoid reading the expected line-role collapse as a regression.

## Concrete Steps

All commands below run from the repository root:

    cd /home/mcnal/projects/recipeimport

Before implementation, re-open the exact seams this plan touches:

    sed -n '6200,6425p' cookimport/parsing/canonical_line_roles.py
    sed -n '4010,4175p' cookimport/parsing/canonical_line_roles.py
    sed -n '1,220p' cookimport/llm/canonical_line_role_prompt.py
    sed -n '1,220p' cookimport/parsing/label_source_of_truth.py
    sed -n '1,240p' cookimport/staging/nonrecipe_stage.py
    sed -n '1180,1315p' cookimport/staging/writer.py
    sed -n '900,1150p' cookimport/llm/codex_farm_knowledge_orchestrator.py
    sed -n '1,240p' cookimport/llm/codex_farm_knowledge_jobs.py

Implement in this order:

1. In `cookimport/parsing/canonical_line_roles.py`, define the suppression reason-code vocabulary, extend the prediction model, and update sanitization and fallback rules so suppression is optional metadata on `OTHER` rows only.

2. In `cookimport/llm/canonical_line_role_prompt.py` and the live worker prompt text in `cookimport/parsing/canonical_line_roles.py`, change the line-role worker instructions so they emphasize recipe structure and obvious suppression, not open-ended outside-recipe `KNOWLEDGE`.

3. In `cookimport/parsing/label_source_of_truth.py`, carry suppression metadata into authoritative lines and block labels, and conservatively promote line-level suppression to block-level knowledge ineligibility.

4. In `cookimport/staging/nonrecipe_stage.py`, keep Stage 7 categories unchanged while adding suppression visibility and “knowledge review eligible” tracking.

5. In `cookimport/staging/writer.py`, extend `08_nonrecipe_spans.json` and add `08_nonrecipe_suppression.jsonl`.

6. In `cookimport/llm/codex_farm_knowledge_orchestrator.py` and `cookimport/llm/codex_farm_knowledge_jobs.py`, exclude suppressed blocks from knowledge input payloads and record suppression counts in manifests and summaries.

7. Update the short current-state docs in `docs/04-parsing/04-parsing_readme.md` and `docs/10-llm/nonrecipe_knowledge_review.md` so they explain that line-role suppression is now the hard junk-routing seam and that the optional knowledge stage only sees unsuppressed non-recipe text.

8. Add or update tests before running broader validation.

Prepare the Python environment if needed:

    source .venv/bin/activate
    pip install -e .[dev]

During implementation, prefer these targeted tests first:

    source .venv/bin/activate
    pytest -q tests/parsing/test_canonical_line_roles.py -k "suppression or nonrecipe or file_prompt"

Then validate the stage-ownership seam:

    source .venv/bin/activate
    pytest -q tests/parsing/test_label_source_of_truth.py -k "nonrecipe or suppression"
    source .venv/bin/activate
    pytest -q tests/staging/test_nonrecipe_stage.py -k "suppression or knowledge"

Then run the broader parsing and staging suites:

    source .venv/bin/activate
    ./scripts/test-suite.sh domain parsing
    source .venv/bin/activate
    ./scripts/test-suite.sh domain staging

If live quality validation is explicitly approved later, use the existing benchmark path and compare both the end-to-end workbook outputs and the new suppression artifact, not just the line-role-only strict accuracy:

    source .venv/bin/activate
    cookimport labelstudio-benchmark ...

The exact benchmark command should be filled in during implementation after confirming the intended benchmark entrypoint.

## Validation and Acceptance

This work is acceptable only if all of the following are true.

The line-role worker can still label recipe structure exactly as before, but its output contract now optionally includes suppression metadata on `OTHER` rows, and repo validation rejects malformed suppression metadata safely.

The final Stage 7 artifacts remain understandable to a human. `08_nonrecipe_spans.json` must still report `knowledge` and `other` counts, and it must now also report how many `other` blocks were suppressed away from knowledge review versus how many remained eligible.

A new ledger artifact must show exactly what was routed off. Opening `08_nonrecipe_suppression.jsonl` after a stage run should show stable ids, previews, and suppression reason codes for each suppressed line or block.

Suppressed blocks must not reach knowledge review. When the optional knowledge stage is enabled, `knowledge/in/*.json` payloads must omit suppressed blocks, and the knowledge manifest or stage summary must report how many blocks were excluded upstream.

The system must fail open. If a row or block is not clearly suppressible, it must remain unsuppressed and eligible for knowledge review.

Recipe-span grouping must not regress. Collapsing broad outside-recipe semantics to provisional `OTHER` must still preserve recipe span acceptance and the current block-gap bridging behavior.

Tests must prove both the positive and negative paths. Add deterministic cases for table-of-contents rows, page-number-only rows, copyright/legal boilerplate, and at least one false-positive guard such as a real explanatory heading that must remain eligible for knowledge review.

Acceptance should be demonstrated with both deterministic tests and one stage-path artifact inspection. A human should be able to run the stage pipeline, open `08_nonrecipe_suppression.jsonl`, and verify that obvious junk is present there while absent from `knowledge/in/*.json`.

## Idempotence and Recovery

This plan is designed to be implemented additively and safely. Suppression metadata should default to “off” everywhere until a specific row or block is explicitly marked. That means partial implementation can safely land behind empty metadata fields without silently deleting any text from the knowledge path.

If suppression becomes too aggressive during implementation, the safe rollback is to stop excluding suppressed blocks from the knowledge-job builder while keeping the suppression ledger artifacts intact. That preserves observability while removing the routing effect. Do not delete the ledger first; it is the debugging surface that will show why the rules were too aggressive.

If worker output compatibility breaks, recover by making suppression fields optional in validators and prompts before reintroducing hard validation of reason codes. A valid old-style worker row with only `atomic_index` and `label` should still normalize cleanly during the migration window.

## Artifacts and Notes

The most important artifacts after implementation should be:

    data/output/<ts>/08_nonrecipe_spans.json
    data/output/<ts>/08_nonrecipe_suppression.jsonl
    data/output/<ts>/raw/llm/<workbook_slug>/line-role-pipeline/runtime/line_role/workers/*/out/*.json
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json

The intended routing contract is:

    recipe-local lines -> line-role final recipe labels
    obvious outside-recipe junk -> final OTHER + suppressed_from_knowledge=true
    remaining outside-recipe text -> provisional OTHER + knowledge-review eligible
    optional knowledge stage -> refines only the unsuppressed remainder to knowledge or other

One expected suppression-ledger row should look conceptually like this:

    {"atomic_index": 44, "source_block_index": 12, "final_label": "OTHER", "suppressed_from_knowledge": true, "suppression_reason_code": "toc_navigation", "text_preview": "CHAPTER 3 ........ 87"}

One expected acceptance check for knowledge input should be:

    open 08_nonrecipe_suppression.jsonl and observe the TOC row above
    open knowledge/in/<shard>.json and verify that block 12 is absent from the chunk payload

Revision note: Initial draft created on 2026-03-22 to implement explicit hard suppression of obvious non-knowledge text before the existing optional knowledge review stage, with no new LLM passes and no new public label taxonomy.
