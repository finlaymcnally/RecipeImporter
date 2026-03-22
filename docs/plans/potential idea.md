---
summary: "Use the existing line-role pass to exclude only obviously non-knowledge outside-recipe material from knowledge review, while leaving semantic knowledge-vs-other authority to the optional knowledge stage."
read_when:
  - When reducing knowledge-stage token spend on obvious front matter, navigation, testimonials, or publishing matter
  - When changing outside-recipe line-role responsibilities without restoring line-role as final `KNOWLEDGE` authority
  - When changing Stage 7 review-eligibility routing, knowledge-job inputs, or `08_nonrecipe_spans.json`
---

# Use line-role as a fail-open coarse junk veto for outside-recipe text

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

The line-role stage in `cookimport/parsing/canonical_line_roles.py` already has to read the whole book in order to separate recipe structure from non-recipe material. The knowledge stage in `cookimport/llm/codex_farm_knowledge_orchestrator.py` is the expensive semantic pass that decides whether outside-recipe text is actually reusable cooking knowledge. The goal of this plan is to use the already-paid-for line-role pass to do one narrow extra job: mark obviously useless outside-recipe material so the knowledge stage does not waste prompts on it.

The key limit is intentional. The line-role stage must not become the final judge of whether subtle prose is useful cooking knowledge. It should only recognize overwhelming low-risk cases such as table-of-contents rows, isolated page numbers, running headers, copyright/legal boilerplate, cataloging metadata, testimonials, and similar publishing/navigation surfaces. Ambiguous outside-recipe prose must fail open and continue to knowledge review.

After this change, running the normal stage path with optional knowledge review enabled should still produce `08_nonrecipe_spans.json` and `09_knowledge_outputs.json`. The knowledge worker should see fewer obviously useless blocks in `knowledge/in/*.json`, while a new or extended artifact surface should make the excluded rows and blocks inspectable by a human. No new LLM pass is added. The existing line-role pass adds only one extra coarse routing bit, and the existing knowledge pass remains the only semantic `knowledge` versus `other` authority for the unsuppressed remainder.

## Progress

- [x] (2026-03-22 13:39 EDT) Re-read `docs/PLANS.md`, `docs/04-parsing/04-parsing_readme.md`, and `docs/10-llm/nonrecipe_knowledge_review.md` to anchor this plan in the current line-role-first and optional-knowledge-review contracts.
- [x] (2026-03-22 13:39 EDT) Re-inspected `cookimport/parsing/canonical_line_roles.py`, `cookimport/parsing/label_source_of_truth.py`, `cookimport/staging/nonrecipe_stage.py`, `cookimport/staging/writer.py`, `cookimport/llm/codex_farm_knowledge_jobs.py`, and `cookimport/llm/codex_farm_knowledge_orchestrator.py` to confirm the current seams.
- [x] (2026-03-22 13:39 EDT) Replaced the earlier over-broad plan with this narrower version: line-role performs only a fail-open obvious-junk veto, while semantic knowledge judgment stays in the optional knowledge stage.
- [x] (2026-03-22 13:55 EDT) Re-read `docs/10-llm/10-llm_README.md`, `docs/05-staging/05-staging_readme.md`, `docs/07-bench/07-bench_README.md`, and the current touched tests to align this plan with the current packetized knowledge runtime, stage-summary artifacts, and benchmark projection rules.
- [x] (2026-03-22 15:46 EDT) Extended the line-role contract with optional `review_exclusion_reason`, taught prompt/worker validation about the allowed reason codes, and normalized outside-recipe `KNOWLEDGE` back to review-eligible `OTHER`.
- [x] (2026-03-22 15:46 EDT) Propagated review-exclusion metadata through authoritative lines/blocks, added Stage 7 review-eligibility routing plus preview text, and wrote `08_nonrecipe_review_exclusions.jsonl`.
- [x] (2026-03-22 15:46 EDT) Switched knowledge-job planning/manifests to the Stage 7 review-eligible span set, added excluded/review-eligible counts to summaries, and updated the current parsing/LLM docs.
- [x] (2026-03-22 15:46 EDT) Validation run complete: focused parsing/staging/knowledge tests passed; `./scripts/test-suite.sh domain parsing` passed; `./scripts/test-suite.sh domain staging` passed after updating the fresh-directory-walk expectation for the new exclusion ledger.
- [ ] `./scripts/test-suite.sh domain llm` still stops on `tests/llm/test_recipe_phase_workers.py::test_recipe_phase_runtime_writes_worker_prompt_and_manifest_contract`, which appears unrelated to this change and was not pursued under this plan.

## Surprises & Discoveries

- Observation: current outside-recipe `KNOWLEDGE` authority still lives in line-role today, even after recent tightening.
  Evidence: `cookimport/parsing/canonical_line_roles.py` still promotes outside-recipe rows to `KNOWLEDGE` in `_deterministic_label(...)`, and `_sanitize_prediction(...)` still treats outside-recipe `KNOWLEDGE` as a line-role-owned final label.

- Observation: the repo already has a separate concept of “obvious junk” in parser-owned chunking, but that seam is not the current final routing authority for knowledge review.
  Evidence: `cookimport/parsing/chunks.py` scores navigation, attribution, dedication, and similar material as `noise`, but `cookimport/llm/codex_farm_knowledge_orchestrator.py` currently calls `build_knowledge_jobs(...)` without using the existing `skip_suggested_lanes` seam.

- Observation: there is currently no field in the line-role output contract for “this row stays `OTHER`, but do not send it to knowledge review.”
  Evidence: `CanonicalLineRolePrediction` in `cookimport/parsing/canonical_line_roles.py` still carries only `label`, `decided_by`, `reason_tags`, and `escalation_reasons`.

- Observation: Stage 7 already has the right shape to preserve both seed and final authority, so review-exclusion visibility can be added without changing the public `knowledge` / `other` taxonomy.
  Evidence: `NonRecipeStageResult` already keeps both seed and final non-recipe spans plus a `refinement_report`, and `cookimport/staging/writer.py` already writes both pre-review and post-review views.

- Observation: the current knowledge runtime is more packetized and artifact-heavy than the original draft assumed.
  Evidence: current docs and tests describe `knowledge/in/*.json` immutable shard payloads, packet-level `task_status.jsonl`, stage-level `stage_status.json`, and the compact operator summary `knowledge_stage_summary.json` as first-class runtime seams.

- Observation: benchmark scoring already projects final outside-recipe authority rather than blindly trusting pre-knowledge line-role labels.
  Evidence: current staging and benchmark docs say canonical scoring must use the final non-recipe authority recorded in `08_nonrecipe_spans.json`, not just the deterministic seed.

- Observation: several test fixtures construct `NonRecipeStageResult` directly rather than always going through `build_nonrecipe_stage_result(...)`.
  Evidence: knowledge-orchestrator tests no-oped until `NonRecipeStageResult.__post_init__` backfilled review-eligible spans/indices for legacy fixture payloads.

- Observation: adding the exclusion ledger changes run-output accounting even though it does not change the public `knowledge` / `other` taxonomy.
  Evidence: `tests/staging/test_split_merge_status.py::test_merge_split_jobs_output_stats_match_fresh_directory_walk` needed the new `08_nonrecipe_review_exclusions.jsonl` path mapped into the `nonRecipe` output-stats category.

## Decision Log

- Decision: line-role will not own semantic outside-recipe `knowledge` versus `other` decisions after this change.
  Rationale: the line-role pass is already busy separating recipe structure from everything else. Asking it to also be the final judge of subtle memoir-versus-teaching prose is exactly the overload this plan is meant to reduce.
  Date/Author: 2026-03-22 / Codex

- Decision: line-role may still own a fail-open coarse veto for obviously useless outside-recipe material.
  Rationale: that pass is already paid for because it must inspect the whole book. Extracting one extra high-confidence routing bit from that pass is cheaper than adding another LLM stage.
  Date/Author: 2026-03-22 / Codex

- Decision: the public final taxonomy remains `knowledge` and `other`; exclusion from review is metadata, not a new user-facing category.
  Rationale: a new public label would ripple through benchmarks, writer contracts, Label Studio, and downstream consumers for little user benefit.
  Date/Author: 2026-03-22 / Codex

- Decision: exclusion must fail open.
  Rationale: only overwhelmingly obvious cases should bypass the knowledge stage. Ambiguous instructional, memoir, essay, or reference prose must remain review-eligible.
  Date/Author: 2026-03-22 / Codex

- Decision: excluded material must remain visible in first-class artifacts.
  Rationale: the operator needs to audit what was skipped and why. Silent filtering would make prompt savings impossible to debug or trust.
  Date/Author: 2026-03-22 / Codex

- Decision: current chunk-lane `noise` heuristics are useful contrast and validation signals, but they must not become the new final semantic authority for keep/cut.
  Rationale: the operator requirement is explicit: deterministic logic cannot own useful-versus-useless semantic judgment. This plan uses line-role LLM output for the coarse veto and keeps deterministic logic as supporting evidence or diagnostics only.
  Date/Author: 2026-03-22 / Codex

- Decision: the shipped line-role contract uses one optional string field `review_exclusion_reason` instead of a separate boolean plus reason pair.
  Rationale: `label == "OTHER"` already means “not recipe structure / not final knowledge yet.” A single optional reason code is enough to distinguish review-eligible `OTHER` from obviously excluded `OTHER` without widening the payload shape further.
  Date/Author: 2026-03-22 / Codex

- Decision: outside-recipe lesson detection remains as a supporting heuristic seam, but final line-role output still demotes outside-recipe `KNOWLEDGE` back to review-eligible `OTHER`.
  Rationale: the existing heuristics are still useful for prompt guidance, sanitization, and artifact interpretation, but this plan requires the optional knowledge stage to remain the only semantic outside-recipe `knowledge` authority.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

The code now matches the narrower design target. Line-role still owns recipe structure, but outside-recipe semantic `knowledge` authority has moved out of line-role output and into the optional knowledge stage. The only new upstream routing bit is optional `review_exclusion_reason` on outside-recipe `OTHER` rows, plus the Stage 7 review-eligible/excluded span split and the human-auditable `08_nonrecipe_review_exclusions.jsonl` ledger.

The highest-value proof points were: parsing-domain green after updating outside-recipe expectations to review-eligible `OTHER`, staging-domain green with the new ledger counted in output stats, and focused knowledge-runtime tests proving the orchestrator now reads `review_eligible_nonrecipe_spans` and reports excluded-block counts in manifests/summaries. The remaining open item is one unrelated `domain llm` failure in the recipe worker contract surface, not in the knowledge/Stage 7 path changed here.

## Context and Orientation

The current label-first path starts in `cookimport/parsing/label_source_of_truth.py`. That module atomizes full blocks into atomic lines, calls `cookimport/parsing/canonical_line_roles.py` to assign one final line-role label per atomic line, projects those labels back up to block labels, and then groups recipe spans. Outside-recipe semantic `knowledge` is no longer finalized there; line-role can now only mark obvious outside-recipe `OTHER` rows with `review_exclusion_reason`.

Stage 7 non-recipe ownership lives in `cookimport/staging/nonrecipe_stage.py`. It consumes final block labels after recipe spans are accepted, keeps the blocks that are not owned by recipes, and assigns each non-recipe block a Stage 7 category of `knowledge` or `other`. `cookimport/staging/writer.py` writes that state to `08_nonrecipe_spans.json`, and `09_knowledge_outputs.json` later records the final post-review authority when the optional knowledge stage runs.

The optional non-recipe knowledge review stage lives in `cookimport/llm/codex_farm_knowledge_orchestrator.py` and `cookimport/llm/codex_farm_knowledge_jobs.py`. It currently builds immutable `knowledge/in/*.json` shard payloads from Stage 7 seed non-recipe spans, then executes packetized chunk-review tasks inside worker-local workspaces. Packet-level status lands in `task_status.jsonl`, stage-level state lands in `stage_status.json`, and the compact operator summary lands in `knowledge_stage_summary.json`. Any implementation of this plan must update that fuller runtime surface, not just the input bundle text.

In this plan, “excluded from knowledge review” means: “the line-role pass has judged this outside-recipe material to be so obviously not reusable cooking knowledge that it should remain final `other` immediately and should not consume knowledge-review tokens.” It does not mean “the LLM has fully judged all outside-recipe semantics.” Examples include dotted table-of-contents rows, isolated page numbers, running headers and footers, copyright/legal boilerplate, ISBN or Library of Congress cataloging blocks, testimonial blurbs, and other publishing/navigation surfaces. Ambiguous essays, memoir fragments, explanatory headings, and prose with even a plausible chance of carrying reusable cooking advice must remain review-eligible.

The important architectural choice is now implemented: recipe-local structure remains line-role-owned, while outside-recipe text becomes either `OTHER` plus “review eligible” or `OTHER` plus `review_exclusion_reason`. The optional knowledge stage is now the only place that can still promote the review-eligible remainder to final `knowledge`.

## Plan of Work

Start in `cookimport/parsing/canonical_line_roles.py` and `cookimport/llm/canonical_line_role_prompt.py`. Extend the line-role worker contract so a row may still return the ordinary label, but an outside-recipe `OTHER` row may also carry an optional review-exclusion annotation. The minimum contract should be a boolean plus a small reason code. A concrete shape is:

    {"atomic_index": 123, "label": "OTHER", "review_exclusion_reason": "navigation"}

The prompt must tell the worker exactly what this new bit means. The worker still does recipe-local labeling as before. It must not try to decide subtle outside-recipe usefulness. For outside-recipe text it should:

1. keep obvious recipe structure labels when they are truly recipe-local,
2. otherwise default non-recipe text to `OTHER`,
3. set the exclusion bit only for overwhelming obvious-junk cases,
4. leave ambiguous prose as plain `OTHER` with no exclusion bit.

At the same time, update line-role sanitization so outside-recipe `KNOWLEDGE` is no longer a required or preferred output of this stage. The safe end state is that outside-recipe non-recipe prose comes out of line-role as `OTHER` plus optional exclusion metadata, not as final `KNOWLEDGE`. During migration, old worker outputs that omit the new fields must still validate and normalize safely.

Define a deliberately tiny exclusion vocabulary owned by the repo. Good initial reason codes are `toc_navigation`, `page_number_only`, `running_header_footer`, `copyright_legal`, `isbn_cataloging`, `publisher_metadata`, `testimonial_blurb`, and `index_navigation`. Do not add fuzzy reasons such as `probably_not_knowledge`. The reason codes must describe only surfaces that are obvious to a human reviewer.

Then propagate that metadata through `cookimport/parsing/label_source_of_truth.py`. The shipped field is `review_exclusion_reason: str | None = None` on both `AuthoritativeLabeledLine` and `AuthoritativeBlockLabel`. Block-level promotion must be conservative. A block should become excluded only when all of its relevant outside-recipe lines are excluded for compatible reasons or when a specific block-level normalization rule proves the entire block is the same obvious junk surface. If any line in the block remains plausibly reviewable, the block must remain review-eligible.

Next, update `cookimport/staging/nonrecipe_stage.py`. Keep the public block categories `knowledge` and `other`, but split “other” into two internal routing views: review-eligible `other` blocks and review-excluded `other` blocks. The stage result should gain fields for exact excluded block indices, exact review-eligible block indices, exclusion reasons by block, and a second set of contiguous spans that represent only the review-eligible subset used to build knowledge jobs. This extra span list is necessary because a single broad Stage 7 `other` span may contain both excluded and reviewable blocks after the new routing logic is introduced.

Update `cookimport/staging/writer.py` so this routing stays inspectable. `08_nonrecipe_spans.json` should continue to report `knowledge` and `other`, but it must also report how many `other` blocks were excluded from review and how many remained review-eligible. In addition, write a dedicated sibling ledger such as `08_nonrecipe_review_exclusions.jsonl` with one row per excluded line or block. Each ledger row should include stable ids, a short preview, the final category `other`, the exclusion reason code, and whether the exclusion came directly from line-role or from conservative block-level promotion of excluded lines.

After that, update `cookimport/llm/codex_farm_knowledge_jobs.py` and `cookimport/llm/codex_farm_knowledge_orchestrator.py`. Knowledge-job planning must read the new review-eligible Stage 7 span list rather than the old full seed-nonrecipe span list. Excluded blocks must remain visible in `08_nonrecipe_spans.json` and the exclusion ledger, but they must not appear in `knowledge/in/*.json`. The manifest, `stage_status.json`, and `knowledge_stage_summary.json` should report excluded-block counts so missing blocks are explainable rather than surprising.

Finally, update benchmark interpretation and current-state docs. Current canonical scoring already projects final non-recipe authority, so this refactor should preserve that contract rather than inventing a new benchmark interpretation surface. The promotion metric for this feature is still the end-to-end staged output with optional knowledge review enabled: fewer obvious-junk blocks in `knowledge/in/*.json`, no regression in recipe structure labeling, and correct final `knowledge` / `other` output after the knowledge stage finishes.

## Concrete Steps

All commands below run from the repository root:

    cd /home/mcnal/projects/recipeimport

Before implementation, reopen the exact seams this plan touches:

    sed -n '360,430p' cookimport/parsing/canonical_line_roles.py
    sed -n '6250,6495p' cookimport/parsing/canonical_line_roles.py
    sed -n '8170,8210p' cookimport/parsing/canonical_line_roles.py
    sed -n '1,220p' cookimport/llm/canonical_line_role_prompt.py
    sed -n '100,160p' cookimport/parsing/label_source_of_truth.py
    sed -n '1,220p' cookimport/staging/nonrecipe_stage.py
    sed -n '1176,1360p' cookimport/staging/writer.py
    sed -n '68,170p' cookimport/llm/codex_farm_knowledge_jobs.py
    sed -n '964,1085p' cookimport/llm/codex_farm_knowledge_orchestrator.py
    sed -n '1,120p' docs/10-llm/10-llm_README.md
    sed -n '140,170p' docs/05-staging/05-staging_readme.md
    sed -n '240,260p' docs/07-bench/07-bench_README.md

Implement in this order:

1. In `cookimport/parsing/canonical_line_roles.py`, define the exclusion reason-code vocabulary, extend `CanonicalLineRolePrediction`, update response parsing and validation, and add sanitization rules so exclusion metadata is accepted only on outside-recipe `OTHER` rows.

2. In `cookimport/llm/canonical_line_role_prompt.py` and the live worker prompt text in `cookimport/parsing/canonical_line_roles.py`, rewrite the outside-recipe instructions so line-role defaults ambiguous non-recipe prose to `OTHER` and uses the exclusion bit only for overwhelming obvious-junk cases.

3. In `cookimport/parsing/label_source_of_truth.py`, carry exclusion metadata into authoritative lines and block labels, then conservatively promote line-level exclusions to block-level review exclusion.

4. In `cookimport/staging/nonrecipe_stage.py`, preserve the public `knowledge` / `other` categories while adding explicit review-eligibility routing and a second span set for the knowledge-job builder.

5. In `cookimport/staging/writer.py`, extend `08_nonrecipe_spans.json` and add `08_nonrecipe_review_exclusions.jsonl`.

6. In `cookimport/llm/codex_farm_knowledge_jobs.py` and `cookimport/llm/codex_farm_knowledge_orchestrator.py`, build knowledge inputs only from review-eligible Stage 7 spans and record exclusion counts in manifests and summaries.

7. Update `docs/04-parsing/04-parsing_readme.md` and `docs/10-llm/nonrecipe_knowledge_review.md` so the current docs describe line-role as a coarse outside-recipe review-exclusion seam rather than as the final owner of outside-recipe `KNOWLEDGE`.

8. Add tests before running broader validation.

Prepare the Python environment if needed:

    source .venv/bin/activate
    pip install -e .[dev]

During implementation, prefer these focused tests first:

    source .venv/bin/activate
    pytest -q tests/parsing/test_canonical_line_roles.py -k "knowledge_review or exclusion or nonrecipe"

Then validate label propagation and Stage 7 routing:

    source .venv/bin/activate
    pytest -q tests/parsing/test_label_source_of_truth.py -k "knowledge_review or exclusion or nonrecipe"
    source .venv/bin/activate
    pytest -q tests/staging/test_nonrecipe_stage.py -k "knowledge_review or exclusion"

Then validate knowledge-job input pruning and knowledge runtime reporting:

    source .venv/bin/activate
    pytest -q tests/llm/test_codex_farm_knowledge_orchestrator.py -k "exclusion or review_eligible"
    source .venv/bin/activate
    pytest -q tests/llm/test_codex_farm_knowledge_orchestrator_runtime.py -k "knowledge or stage_summary or status"
    source .venv/bin/activate
    pytest -q tests/llm/test_prompt_preview.py -k "knowledge or line_role"
    source .venv/bin/activate
    pytest -q tests/staging/test_stage_observability.py -k "knowledge_stage_summary or nonrecipe"

Then run the broader suites:

    source .venv/bin/activate
    ./scripts/test-suite.sh domain parsing
    source .venv/bin/activate
    ./scripts/test-suite.sh domain staging
    source .venv/bin/activate
    ./scripts/test-suite.sh domain llm

If a live benchmark or staged run is explicitly approved later, verify artifact behavior rather than relying on line-role-only label accuracy:

    source .venv/bin/activate
    cookimport stage <path> --llm-knowledge-pipeline codex-knowledge-shard-v1

After a live run, inspect:

    data/output/<ts>/08_nonrecipe_spans.json
    data/output/<ts>/08_nonrecipe_review_exclusions.jsonl
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json
    data/output/<ts>/09_knowledge_outputs.json

## Validation and Acceptance

This work is acceptable only if all of the following are true.

The line-role stage can still label recipe structure correctly, but it now also accepts an optional review-exclusion annotation on outside-recipe `OTHER` rows. Validation must reject that annotation on recipe-local labels, on outside-recipe rows labeled something other than `OTHER`, and on unknown exclusion reason codes.

Line-role must no longer be the final semantic authority for outside-recipe `knowledge`. Ambiguous non-recipe prose should remain `OTHER` and review-eligible rather than forcing line-role to decide subtle usefulness.

`08_nonrecipe_spans.json` must remain understandable to a human. It should still report `knowledge` and `other` counts, and it must now also report excluded-versus-reviewable `other` counts plus the exact review-eligible span list used by the knowledge job builder.

A dedicated exclusion ledger must show exactly what was routed off. Opening `08_nonrecipe_review_exclusions.jsonl` after a stage run should show stable ids, preview text, and exclusion reason codes for each excluded row or block.

Excluded blocks must not reach the knowledge stage. When optional knowledge review is enabled, `knowledge/in/*.json` payloads must omit excluded blocks, and the manifest or stage summary must report how many blocks were filtered upstream.

The packetized knowledge runtime must stay coherent. `task_status.jsonl`, `stage_status.json`, and `knowledge_stage_summary.json` should remain internally consistent with the filtered input set and should expose excluded-block counts in a way that explains why some Stage 7 `other` blocks never appeared in `knowledge/in/*.json`.

The system must fail open. If the line-role pass is not highly confident that material is obviously useless, that material must remain review-eligible.

Recipe-span grouping must not regress. Removing outside-recipe semantic `KNOWLEDGE` ownership from line-role must not break recipe structure labels or current recipe-span acceptance behavior.

Tests must cover both positive and negative paths. Add deterministic and LLM-shape tests for table-of-contents rows, isolated page numbers, cataloging/copyright blocks, and testimonial blurbs as positive exclusions, plus at least one explanatory heading or essay fragment that must remain review-eligible even if it is later judged `other` by the knowledge stage.

Acceptance should be demonstrated with both targeted tests and one artifact inspection. A human should be able to run the stage pipeline, open `08_nonrecipe_review_exclusions.jsonl`, and verify that obviously useless material appears there while remaining absent from `knowledge/in/*.json`.

## Idempotence and Recovery

This plan should be implemented additively and fail open. The new exclusion metadata must default to “off” everywhere until a row or block is explicitly marked.

If the exclusion logic becomes too aggressive, the safe rollback is to keep writing the exclusion metadata and ledger but stop pruning excluded blocks from the knowledge-job builder. That preserves observability while removing the token-saving side effect until the exclusion prompt/rules are corrected.

If worker-output compatibility breaks during migration, make the new fields fully optional first. Old worker rows shaped like `{"atomic_index": 123, "label": "OTHER"}` must continue to normalize cleanly until all prompt examples, validators, and cached outputs are updated.

If mixed excluded and reviewable blocks inside one Stage 7 span make knowledge-job planning awkward, recover by deriving a second contiguous review-eligible span list rather than weakening the fail-open rule or silently dropping mixed spans.

## Artifacts and Notes

The most important artifacts after implementation should be:

    data/output/<ts>/08_nonrecipe_spans.json
    data/output/<ts>/08_nonrecipe_review_exclusions.jsonl
    data/output/<ts>/raw/llm/<workbook_slug>/line-role-pipeline/runtime/line_role/workers/*/out/*.json
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge/in/*.json
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge/task_status.jsonl
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge/stage_status.json
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge/knowledge_stage_summary.json
    data/output/<ts>/raw/llm/<workbook_slug>/knowledge_manifest.json
    data/output/<ts>/09_knowledge_outputs.json

The intended routing contract is:

    recipe-local rows -> ordinary line-role final recipe labels
    obvious outside-recipe junk -> final OTHER + review_exclusion_reason set
    ambiguous outside-recipe prose -> provisional OTHER + review-eligible
    optional knowledge stage -> only this stage can promote review-eligible outside-recipe text to final knowledge

One expected exclusion-ledger row should look conceptually like this:

    {"atomic_index": 44, "source_block_index": 12, "final_label": "OTHER", "review_exclusion_reason": "navigation", "text_preview": "CHAPTER 3 ........ 87"}

One expected acceptance check for knowledge input should be:

    open 08_nonrecipe_review_exclusions.jsonl and observe the TOC row above
    open knowledge/in/<shard>.json and verify that block 12 is absent from the job payload

## Interfaces and Dependencies

In `cookimport/parsing/canonical_line_roles.py`, extend:

    class CanonicalLineRolePrediction(BaseModel):
        ...
        review_exclusion_reason: str | None = None

The parser and sanitizer must enforce:

    - `review_exclusion_reason` is only valid when `label == "OTHER"`
    - the candidate must be outside any accepted recipe span
    - `review_exclusion_reason` must be one of the repo-owned allowed codes
    - invalid exclusion metadata falls back safely to plain `OTHER`

In `cookimport/parsing/label_source_of_truth.py`, extend:

    class AuthoritativeLabeledLine(BaseModel):
        ...
        review_exclusion_reason: str | None = None

    class AuthoritativeBlockLabel(BaseModel):
        ...
        review_exclusion_reason: str | None = None

In `cookimport/staging/nonrecipe_stage.py`, extend `NonRecipeStageResult` with exact routing state needed by the knowledge-job builder, for example:

    review_eligible_block_indices: list[int]
    review_excluded_block_indices: list[int]
    review_exclusion_reason_by_block: dict[int, str]
    review_eligible_nonrecipe_spans: list[NonRecipeSpan]

`cookimport/llm/codex_farm_knowledge_jobs.py` must then accept and use `review_eligible_nonrecipe_spans` as the sole source for `knowledge/in/*.json` bundle planning, while `cookimport/llm/codex_farm_knowledge_orchestrator.py` and the stage-observability helpers must surface the resulting filtered counts in `knowledge_manifest.json`, `stage_status.json`, and `knowledge_stage_summary.json`.

Revision note: Updated again on 2026-03-22 after implementation. The plan now records the shipped `review_exclusion_reason` contract, the Stage 7 review-eligible/excluded routing split, the new `08_nonrecipe_review_exclusions.jsonl` artifact, the knowledge-manifest/input-mode change, and the validation status including the unrelated remaining `domain llm` failure outside this feature path.
