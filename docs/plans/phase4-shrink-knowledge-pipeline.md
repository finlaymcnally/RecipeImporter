---
summary: "ExecPlan for Phase 4 of the Refactor migration: make non-recipe ownership label-driven, persist deterministic non-recipe classification, and narrow optional knowledge extraction to labeled knowledge spans only."
read_when:
  - "When implementing Phase 4 from docs/reports/Refactor.md"
  - "When shrinking pass4 into optional extraction over already-labeled knowledge spans"
---

# Shrink the Knowledge Pipeline to a Label-Driven Stage 7

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

This plan assumes the earlier migration work is already present in the working tree. In concrete terms, the runtime already has one authoritative segmented block stream, one normalized Stage 2 block-label view for every source block, one deterministic Stage 3 recipe-span artifact built from those labels, the recipe path from Stage 4 through Stage 6 no longer depends on legacy pre-label recipe-candidate residue, and `stage_observability.json` is already the canonical place where stage names and owned artifacts are recorded. If the concrete Phase 2 handoff type is named `LabelFirstCompatibilityResult`, this phase may read that type at the boundary, but the work in this plan should delete compatibility-only carryovers rather than preserve them. Once Stage 7 exists, the repo should stop speaking in residue-first and pass4-first terms.

## Purpose / Big Picture

After this change, the non-recipe lane will stop using broad residue mining as its main architecture. Stage 7 will deterministically classify every block outside recipe spans as either `knowledge` or `other` from the already-corrected Stage 2 labels, persist that result as a first-class artifact, and only then optionally run a lightweight LLM extraction step on the `knowledge` spans. The user-visible effect is simple: a staged run with `--llm-knowledge-pipeline off` still writes stable non-recipe classification artifacts and still produces correct `KNOWLEDGE` labels in benchmark evidence, while a run with `--llm-knowledge-pipeline codex-farm-knowledge-v1` produces snippets only from blocks already labeled `knowledge`. In the shared observability layer, the semantic stage keys should match the Refactor naming scheme: `classify_nonrecipe` for deterministic Stage 7 and `extract_knowledge_optional` for the optional extraction stage.

This plan is a hard cut to the new model, not a soft migration. Delete `ConversionResult.non_recipe_blocks` as an authority boundary, delete pass4-driven relabeling, and delete compatibility-only readers or files when their replacements land. Do not keep old knowledge outputs alive as parallel product truth “just in case.”

The proof points are equally concrete. In a new run, `08_nonrecipe_spans.json` should show contiguous `knowledge` and `other` spans derived from Stage 2 labels. `09_knowledge_outputs.json` should exist even when the LLM is off, because Stage 7 classification is now a first-class artifact rather than a compatibility side export. When the LLM is on, `pass4_knowledge_manifest.json.counts.jobs_written` should reflect only `knowledge` spans or subspans, never every non-recipe residue sequence.

## Progress

- [x] (2026-03-15_22.21.16) Re-read `docs/PLANS.md` before drafting this ExecPlan.
- [x] (2026-03-15_22.21.16) Re-read `docs/reports/Refactor.md` and captured the exact Phase 4 target: stronger early labels and optional downstream extraction only on labeled knowledge spans.
- [x] (2026-03-15_22.21.16) Inspected the live knowledge lane in `cookimport/staging/import_session.py`, `cookimport/llm/codex_farm_knowledge_orchestrator.py`, `cookimport/llm/codex_farm_knowledge_jobs.py`, `cookimport/staging/stage_block_predictions.py`, and `cookimport/labelstudio/canonical_line_projection.py`.
- [x] (2026-03-15_22.21.16) Wrote the discovery summary to `docs/understandings/2026-03-15_22.21.16-phase4-knowledge-pipeline-current-seams.md`.
- [x] (2026-03-15_22.21.16) Drafted this ExecPlan.
- [x] (2026-03-15_23.02.26) Revised the ExecPlan to reflect the destructive-migration philosophy: Phase 4 now deletes residue-first and pass4-compatibility seams instead of preserving them.
- [ ] Add one deterministic Stage 7 in-memory contract for non-recipe spans and canonical Stage 7 outputs.
- [ ] Rewire stage execution so Stage 7 is built from final labels plus recipe spans and remove `ConversionResult.non_recipe_blocks` from the authoritative path.
- [ ] Narrow pass4 so it only consumes Stage 7 `knowledge` spans and never acts as the primary classifier for `knowledge` versus `other`.
- [ ] Update benchmark and Label Studio readers so they consume Stage 7 ownership directly and delete pass4 relabeling/reporting seams.
- [ ] Add focused tests plus domain regression runs, then update docs.

## Surprises & Discoveries

- Observation: the current pass4 lane is larger than “optional extraction”; it still owns the first preferred `KNOWLEDGE` signal in stage evidence.
  Evidence: `cookimport/staging/stage_block_predictions.py` loads `knowledge/block_classifications.jsonl` before falling back to snippets or deterministic chunk lanes.

- Observation: Label Studio benchmark helpers still allow pass4 to mutate outside-recipe `KNOWLEDGE` versus `OTHER` after the main stage session is complete.
  Evidence: `cookimport/labelstudio/canonical_line_projection.py` upgrades and downgrades span labels from pass4 block classifications and writes `pass4_merge_report.json`.

- Observation: the job-builder boundary is still residue-first.
  Evidence: `cookimport/llm/codex_farm_knowledge_jobs.py::build_pass4_knowledge_jobs(...)` takes `non_recipe_blocks`, splits them into contiguous sequences, and re-runs chunking on that residue instead of consuming a label-driven span selection.

## Decision Log

- Decision: remove compatibility-only knowledge classification files and make Stage 7 artifacts the only authoritative non-recipe surface for new runs.
  Rationale: preserving old file contracts would keep the codebase split across two paradigms. Readers should be updated to consume Stage 7 outputs directly instead of teaching the repo to publish both old and new truths.
  Date/Author: 2026-03-15 / Codex

- Decision: delete `ConversionResult.non_recipe_blocks` from the authoritative path as part of this phase.
  Rationale: as long as residue-first ownership stays in a live runtime object, later code will keep drifting back to it. The refactor only becomes real when Stage 7 is the only ownership boundary for non-recipe text.
  Date/Author: 2026-03-15 / Codex

- Decision: Stage 7 should be allowed to write empty deterministic artifacts and skip pass4 cleanly when no `knowledge` spans exist.
  Rationale: “no knowledge spans” is a normal book outcome, not an error. The current orchestrator raises on missing `non_recipe_blocks`; Phase 4 must become no-op friendly.
  Date/Author: 2026-03-15 / Codex

- Decision: delete pass4-era relabeling reports and legacy knowledge-path fallbacks instead of preserving them as passive compatibility artifacts.
  Rationale: if files such as `pass4_merge_report.json` survive in the new pipeline, they will continue to mislead readers about where authoritative knowledge labels come from. The new stage boundary should be explicit and singular.
  Date/Author: 2026-03-15 / Codex

- Decision: Phase 4 stage naming must extend the shared `stage_observability.json` contract instead of teaching `classify_nonrecipe` and `extract_knowledge_optional` directly in each reporting surface.
  Rationale: Phase 1 exists specifically to centralize stage semantics. Phase 4 should add its new stage keys and artifact references there once, then let summaries, benchmark evidence, and Label Studio readers inherit that truth.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

Initial planning outcome only: the live repo already has the extraction and rendering pieces needed for a smaller knowledge lane, but two old seams must be deleted to make the new topology real. First, pass4 job construction is still based on `non_recipe_blocks`. Second, stage and benchmark evidence still treat pass4 block classifications as authoritative. This plan is intentionally centered on deleting those seams, not wrapping them.

## Context and Orientation

This repository stages cookbook imports into persisted outputs under `data/output/<timestamp>/`. The recipe path already writes recipe artifacts and benchmark evidence. Phase 4 is about the text outside recipe spans.

A “block” is one stable text unit from the shared Stage 1 segmented source. A “final corrected label” is the single Stage 2 semantic label assigned to one block after Phase 2 reconciles any finer-grained line-level labeling into one normalized block-label view. In this plan, Stage 2 already emits at least two non-recipe labels: `knowledge` and `other`, and may emit finer-grained noise labels such as `boilerplate` or `front_matter`. A “recipe span” is a contiguous half-open block range `[start, end)` from Stage 3 that marks which blocks belong to one recipe, with any atomic indices retained only as supporting evidence. A “non-recipe span” is the contiguous complement outside recipe spans, split by final Stage 2 non-recipe label family. A “knowledge span” is a non-recipe span whose Stage 2 family is `knowledge`. An “other span” is every other non-recipe span, including explicit noise categories.

The current knowledge pipeline is spread across a few modules:

- `cookimport/staging/import_session.py` runs the post-conversion stage session. Today it still builds chunks from `result.non_recipe_blocks`, then optionally runs pass4 knowledge harvest, then passes pass4 file paths into stage-block predictions.
- `cookimport/llm/codex_farm_knowledge_jobs.py` builds pass4 job files. Today it accepts `non_recipe_blocks`, re-chunks them, and derives recipe spans by subtracting non-recipe indices from the full block stream.
- `cookimport/llm/codex_farm_knowledge_orchestrator.py` shells out to codex-farm, writes the pass4 manifest, and currently raises if there are no `non_recipe_blocks`.
- `cookimport/llm/codex_farm_knowledge_writer.py` writes `knowledge/<workbook_slug>/snippets.jsonl`, `block_classifications.jsonl`, and `knowledge.md`.
- `cookimport/staging/stage_block_predictions.py` builds the deterministic benchmark evidence file `.bench/<workbook_slug>/stage_block_predictions.json`. It currently prefers pass4 block classifications when deciding which blocks are `KNOWLEDGE`.
- `cookimport/labelstudio/canonical_line_projection.py` builds freeform benchmark line-label artifacts and currently allows pass4 to upgrade or downgrade outside-recipe labels after the main stage session.

Phase 4 needs one new center of gravity: a deterministic Stage 7 artifact builder that consumes the authoritative block stream, the normalized Phase 2 block-label view, and the Phase 2/3 recipe-span view, then produces one stable classification result for every non-recipe block before any LLM extraction begins.

## Plan of Work

### Milestone 1: Introduce a deterministic Stage 7 contract

Create a new module `cookimport/staging/nonrecipe_stage.py`. This module should become the one place that understands how to derive non-recipe ownership from the already-authoritative recipe and label artifacts. Define two small dataclasses here:

    @dataclass(frozen=True, slots=True)
    class NonRecipeSpan:
        span_id: str
        category: str
        block_start_index: int
        block_end_index: int
        block_indices: list[int]
        block_ids: list[str]

    @dataclass(frozen=True, slots=True)
    class NonRecipeStageResult:
        nonrecipe_spans: list[NonRecipeSpan]
        knowledge_spans: list[NonRecipeSpan]
        other_spans: list[NonRecipeSpan]
        block_category_by_index: dict[int, str]

Also define one public constructor:

    def build_nonrecipe_stage_result(
        *,
        full_blocks: Sequence[Mapping[str, Any]],
        final_block_labels: Sequence[AuthoritativeBlockLabel],
        recipe_spans: Sequence[RecipeSpan],
        overrides: ParsingOverrides | None = None,
    ) -> NonRecipeStageResult:

The function must treat recipe spans as authoritative exclusion zones. A block inside a recipe span never appears in `nonrecipe_spans`, even if a stale or contradictory non-recipe label exists. For blocks outside recipe spans, normalize label families as follows:

- Stage 2 `knowledge` stays `knowledge`.
- Stage 2 `other`, `boilerplate`, `toc`, `front_matter`, `endorsement`, `navigation`, `marketing`, and any future non-knowledge noise subtype all map to Stage 7 `other`.
- Unknown or missing non-recipe labels must be recorded as `other` plus a warning note in the Stage 7 artifact, never silently dropped.

Group contiguous outside-recipe blocks with the same Stage 7 category into one `NonRecipeSpan`. The span convention must stay half-open on indices so it matches `cookimport/llm/non_recipe_spans.py`.

If some downstream code still expects chunk-shaped knowledge inputs, rewrite that code in this phase rather than keeping a `compatibility_chunks` field alive. Reuse `chunks_from_non_recipe_blocks(...)` only as an internal helper within one `knowledge` span at a time if it remains the fastest implementation path, and rename that helper later if needed so it stops teaching residue-first architecture.

At the end of this milestone, the repo has one deterministic Stage 7 object in memory that says, in one place, which outside-recipe blocks are knowledge and which are not.

### Milestone 2: Persist Stage 7 as the primary non-recipe artifact

Extend `cookimport/staging/writer.py` with a new helper:

    def write_nonrecipe_stage_outputs(
        stage_result: NonRecipeStageResult,
        output_dir: Path,
    ) -> Path:

Write `08_nonrecipe_spans.json` under the run root. The file must contain one schema version, one summary count section, and the complete span list with stable `span_id` values. The stable ID format should be:

    nr.<category>.<start>.<end>

For example, `nr.knowledge.120.136` means blocks `[120, 136)` are one Stage 7 knowledge span.

Also write `09_knowledge_outputs.json` under the run root as the canonical Stage 7 companion artifact. When the LLM is off, the file should still exist and should record zero extraction outputs plus the deterministic fact that Stage 7 classification completed. When the LLM is on, the file should record the knowledge extraction inputs and outputs derived only from `knowledge` spans. New readers should consume this file and `08_nonrecipe_spans.json` directly rather than looking for `knowledge/<workbook_slug>/block_classifications.jsonl`.

Keep `knowledge/<workbook_slug>/snippets.jsonl` and `knowledge.md` only if they remain useful as stage-local extraction artifacts under the new stage taxonomy. They are not compatibility requirements.

At the end of this milestone, a stage run has the two canonical non-recipe artifacts named in the refactor contract: `08_nonrecipe_spans.json` and `09_knowledge_outputs.json`.

When these artifacts are written, register them through the Phase 1 observability contract so `stage_observability.json` can show `classify_nonrecipe` as the owner of `08_nonrecipe_spans.json` and `extract_knowledge_optional` as the owner of `09_knowledge_outputs.json` when that optional stage runs.

### Milestone 3: Narrow pass4 to `knowledge` spans only

Refactor `cookimport/llm/codex_farm_knowledge_jobs.py` so `build_pass4_knowledge_jobs(...)` accepts `knowledge_spans` from `NonRecipeStageResult` instead of `non_recipe_blocks`. Preserve the current context-window logic against the full block stream, but change the selection logic:

- Only `knowledge_spans` produce pass4 jobs.
- `other_spans` never produce jobs.
- Recipe spans remain exclusion context only.
- Table-aware chunking rules may still split or preserve boundaries inside a `knowledge` span, but those refinements must not cause neighboring `other` spans to leak into pass4.

The easiest safe implementation is:

1. Slice one `knowledge` span out of `full_blocks`.
2. Convert only those blocks into the input shape expected by `chunks_from_non_recipe_blocks(...)`.
3. Chunk inside that one span if needed.
4. Build pass4 jobs from those chunklets.

Do not subtract recipe indices from `full_blocks` anymore inside the job builder. That math belongs to Stage 7 now.

Then refactor `cookimport/llm/codex_farm_knowledge_orchestrator.py`:

- Replace the requirement for `conversion_result.non_recipe_blocks` with a requirement for `NonRecipeStageResult`.
- If `knowledge_spans` is empty, return a successful report with `jobs_written = 0`, `outputs_parsed = 0`, and empty `missing_chunk_ids`.
- The pass4 manifest must state clearly that jobs were built from Stage 7 `knowledge` spans. Add a short manifest field such as:

    "input_mode": "stage7_knowledge_spans"

At the end of this milestone, pass4 is no longer a whole-residue mining pass. It is a scoped extractor over blocks already labeled `knowledge`.

Register this optional extraction stage through the shared observability layer under the semantic key `extract_knowledge_optional`. If no knowledge spans exist, the stage should still be representable as a successful no-op or skipped stage there instead of disappearing into local pass4 manifest semantics.

### Milestone 4: Rewire stage execution and delete pass4-era reader seams

Update `cookimport/staging/import_session.py` so the order is:

1. obtain final labels and recipe spans from the already-refactored earlier phases,
2. build `NonRecipeStageResult`,
3. write `08_nonrecipe_spans.json`,
4. write `09_knowledge_outputs.json` for the deterministic-or-optional extraction stage,
5. optionally run pass4 on `knowledge_spans`,
6. write any stage-local extraction artifacts under semantic Stage 7 ownership only,
7. write stage-block predictions.

Delete `result.non_recipe_blocks` from the authoritative execution path. If some downstream code still depends on it, rewrite that code now rather than threading the field through another phase.

Then update the evidence readers:

- In `cookimport/staging/stage_block_predictions.py`, resolve `KNOWLEDGE` from Stage 7 deterministic categories first. Snippet provenance can still enrich notes, but it must never be the first classifier.
- In `cookimport/labelstudio/canonical_line_projection.py`, stop using pass4 block classifications to upgrade or downgrade authoritative freeform labels and delete `pass4_merge_report.json` from the new path.
- In `cookimport/labelstudio/ingest.py`, resolve non-recipe knowledge evidence from Stage 7 paths only. Do not keep fallback logic for legacy llm-report paths in the new implementation.

At the end of this milestone, pass4 can still provide extraction output, but it no longer edits the canonical outside-recipe label story and no pass4-era reader seams remain in the main path.

### Milestone 5: Tests, docs, and removal checks

Add a focused test file `tests/staging/test_nonrecipe_stage.py`. Cover at least these cases:

- a block labeled `knowledge` inside a recipe span is excluded from Stage 7 output;
- outside-recipe contiguous `knowledge` blocks form one `knowledge` span;
- explicit noise labels normalize to Stage 7 `other`;
- `08_nonrecipe_spans.json` and `09_knowledge_outputs.json` are written even when the LLM is off;
- zero `knowledge` spans produces a successful pass4 no-op report instead of an exception.

Update existing tests:

- `tests/llm/test_codex_farm_knowledge_orchestrator.py` should assert `input_mode == "stage7_knowledge_spans"` and successful zero-job behavior.
- `tests/staging/test_stage_block_predictions.py` should assert `KNOWLEDGE` comes from deterministic Stage 7 categories even when no snippets exist.
- `tests/labelstudio/test_canonical_line_projection.py` should stop expecting pass4-driven label changes for new-format runs and should assert that no pass4 merge report is written.

After tests pass, update the short docs that define current behavior:

- `docs/10-llm/knowledge_harvest.md`
- `docs/10-llm/10-llm_README.md`
- `docs/05-staging/05-staging_readme.md`
- `docs/06-label-studio/06-label-studio_README.md`

The docs update must explicitly say that pass4 is now optional snippet extraction over Stage 7 `knowledge` spans, is no longer the primary classifier for outside-recipe labels, and no longer owns any compatibility-only reader contract.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`.

Prepare the environment:

    source .venv/bin/activate
    pip install -e .[dev]

Before changing code, run the narrow domains that already cover the current pass4 surfaces:

    source .venv/bin/activate
    ./scripts/test-suite.sh domain llm
    ./scripts/test-suite.sh domain staging
    ./scripts/test-suite.sh domain labelstudio

Implement the new Stage 7 builder and its focused tests first:

    source .venv/bin/activate
    pytest tests/staging/test_nonrecipe_stage.py -q

Then run the regression slices that must stay green:

    source .venv/bin/activate
    pytest tests/llm/test_codex_farm_knowledge_orchestrator.py -q
    pytest tests/staging/test_stage_block_predictions.py -q
    pytest tests/labelstudio/test_canonical_line_projection.py -q

After the focused slices pass, run the broader domain suites again:

    source .venv/bin/activate
    ./scripts/test-suite.sh domain llm
    ./scripts/test-suite.sh domain staging
    ./scripts/test-suite.sh domain labelstudio

Finally, run one manual stage check on any block-first source already present under `data/input/`:

    source .venv/bin/activate
    cookimport stage data/input/<book>.epub --llm-knowledge-pipeline off
    cookimport stage data/input/<book>.epub --llm-knowledge-pipeline codex-farm-knowledge-v1

Expected observations:

- both runs write `08_nonrecipe_spans.json`;
- both runs write `09_knowledge_outputs.json`;
- only the second run writes pass4 raw IO plus `snippets.jsonl` and `knowledge.md`;
- the second run writes fewer jobs than “all non-recipe residue blocks” because it only targets Stage 7 `knowledge` spans.

## Validation and Acceptance

The implementation is accepted when all of the following are true.

First, deterministic behavior is observable. A stage run with `--llm-knowledge-pipeline off` still writes one stable Stage 7 classification artifact plus `09_knowledge_outputs.json` with zero extraction outputs. `.bench/<workbook_slug>/stage_block_predictions.json` marks outside-recipe `KNOWLEDGE` blocks correctly without any pass4 output being present.

Second, pass4 is visibly smaller. A stage run with `--llm-knowledge-pipeline codex-farm-knowledge-v1` writes `pass4_knowledge_manifest.json` whose `input_mode` is `stage7_knowledge_spans`, and every written job corresponds to a Stage 7 `knowledge` span or chunklet inside one. No `other` span generates a job.

Third, benchmark and Label Studio readers no longer depend on pass4 relabeling. `cookimport/labelstudio/canonical_line_projection.py` does not write `pass4_merge_report.json`, and new-format runs do not change authoritative labels from pass4 classifications.

Fourth, the old path contract is gone. New-format runs do not publish `knowledge/<workbook_slug>/block_classifications.jsonl` as a compatibility crutch, do not keep `ConversionResult.non_recipe_blocks` alive as an ownership source, and do not expose legacy llm-report fallbacks.

Fifth, the new topology is visible through the shared observability contract. `stage_observability.json` must show `classify_nonrecipe` for the deterministic Stage 7 artifact write, and when the LLM lane runs it must show `extract_knowledge_optional` as a separate optional stage rather than hiding that meaning only inside pass4-era manifests.

## Idempotence and Recovery

The new Stage 7 builder is deterministic over the same block, label, and recipe-span inputs. Re-running tests is safe. Re-running `cookimport stage` is also safe because each run writes to a fresh timestamped output directory.

This plan is intentionally destructive. If a reader breaks because it depended on a deleted compatibility path, rewrite the reader to the Stage 7 artifacts rather than reintroducing the old file. If a run hits zero `knowledge` spans, `09_knowledge_outputs.json` should record a successful no-op extraction state instead of recreating old compatibility files.

## Artifacts and Notes

The key new artifact should look like this:

    {
      "schema_version": "nonrecipe_spans.v1",
      "counts": {
        "nonrecipe_spans": 14,
        "knowledge_spans": 5,
        "other_spans": 9
      },
      "spans": [
        {
          "span_id": "nr.knowledge.120.136",
          "category": "knowledge",
          "block_start_index": 120,
          "block_end_index": 136
        }
      ]
    }

The canonical knowledge-output artifact should look roughly like this when the LLM is off:

    {
      "schema_version": "knowledge_outputs.v1",
      "classification_source": "stage7",
      "extraction_mode": "off",
      "knowledge_span_count": 5,
      "snippets": []
    }

The pass4 manifest should clearly advertise the new input boundary:

    {
      "input_mode": "stage7_knowledge_spans",
      "counts": {
        "jobs_written": 5,
        "outputs_parsed": 5
      }
    }

## Interfaces and Dependencies

Define the new Stage 7 builder in `cookimport/staging/nonrecipe_stage.py`:

    @dataclass(frozen=True, slots=True)
    class NonRecipeSpan:
        span_id: str
        category: str
        block_start_index: int
        block_end_index: int
        block_indices: list[int]
        block_ids: list[str]

    @dataclass(frozen=True, slots=True)
    class NonRecipeStageResult:
        nonrecipe_spans: list[NonRecipeSpan]
        knowledge_spans: list[NonRecipeSpan]
        other_spans: list[NonRecipeSpan]
        block_category_by_index: dict[int, str]

    def build_nonrecipe_stage_result(
        *,
        full_blocks: Sequence[Mapping[str, Any]],
        final_block_labels: Sequence[AuthoritativeBlockLabel],
        recipe_spans: Sequence[RecipeSpan],
        overrides: ParsingOverrides | None = None,
    ) -> NonRecipeStageResult:
        ...

Update `cookimport/llm/codex_farm_knowledge_jobs.py` so its public builder takes `knowledge_spans` instead of `non_recipe_blocks`, and update `cookimport/llm/codex_farm_knowledge_orchestrator.py` so its public entrypoint receives `NonRecipeStageResult` and writes `input_mode = "stage7_knowledge_spans"` in the manifest. Keep existing codex-farm runner dependencies and schema resolution intact; this phase changes selection boundaries, not subprocess execution contracts.

Change `cookimport/staging/stage_block_predictions.py` and `cookimport/labelstudio/canonical_line_projection.py` to treat Stage 7 deterministic categories as authoritative for outside-recipe `KNOWLEDGE` ownership. Snippets remain evidence, not classifiers. Delete pass4-era relabeling reports and legacy path fallbacks from those modules instead of leaving them dormant.

Change note (2026-03-15_22.21.16): Initial ExecPlan created from the Phase 4 section in `docs/reports/Refactor.md` plus a code/doc survey of the current pass4, staging, and Label Studio seams. Reason: provide a self-contained implementation spec for the label-driven knowledge-pipeline shrink assuming earlier migration phases already landed.

Change note (2026-03-15_22.30.53): Revised to add front matter and to align the plan with the shared Phase 1 observability contract and the Refactor naming scheme. The plan now explicitly treats `classify_nonrecipe` and `extract_knowledge_optional` as semantic stage keys owned by `stage_observability.json`, with pass4-era paths retained only as compatibility artifacts.

Change note (2026-03-15_22.42.10): Revised to align the Stage 7 inputs with the tightened Phase 2 contract. Reason: the surrounding plans now make Phase 2 responsible for handing off normalized block labels and block-range `RecipeSpan` objects, so Phase 4 should name those types directly instead of falling back to generic mappings.

Change note (2026-03-15_22.52.33): Revised to make the upstream handoff and acceptance boundary more explicit. Reason: the surrounding plans now agree that Phase 4 should consume the Phase 2 bundle's normalized `block_labels` plus `recipe_spans` directly and should prove the resulting topology through `stage_observability.json`, not only through pass4 compatibility artifacts.

Change note (2026-03-15_23.00.00): Revised stale cross-doc references from `docs/plans/Refactor.md` to `docs/reports/Refactor.md`. Reason: the phase-plan series should point at the real source document consistently.

Change note (2026-03-15_23.02.26): Revised the plan around a destructive migration philosophy after user clarification. Reason: the earlier draft preserved compatibility exports, `ConversionResult.non_recipe_blocks`, and pass4-era reader seams, which contradicted the intended major-refactor posture of deleting old knowledge-pipeline contracts and shipping only the Stage 7 model.
