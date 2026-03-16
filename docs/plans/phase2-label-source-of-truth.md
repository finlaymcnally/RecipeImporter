---
summary: "ExecPlan for Phase 2 of the Refactor migration: make Stage 2 labeling authoritative so recipe grouping and non-recipe ownership flow from labels instead of importer candidate heuristics."
read_when:
  - "When implementing Phase 2 from docs/plans/Refactor.md"
  - "When moving stage/import and Label Studio prediction generation from candidate-first ownership to label-first ownership"
---

# Make Labeling the Source of Truth

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

Assumption for this plan: Phase 1 from `docs/plans/Refactor.md` has already been implemented to spec. In practical terms, that means the repo already has clear stage names, persisted per-stage artifacts, and reporting that matches the pre-Phase-2 runtime. This plan does not spend time renaming stages or inventing observability from scratch. It uses that groundwork to change runtime ownership.

## Purpose / Big Picture

After this change, Stage 2 labels become the authoritative answer to the question “what is this line of cookbook text?” Recipe grouping, non-recipe residue, and later recipe parsing all flow from those labels instead of from importer-local candidate heuristics. A user running `cookimport stage` or `cookimport labelstudio-benchmark --no-upload` should be able to inspect the run folder and see that recipe spans, non-recipe spans, and stage block predictions were derived from the same authoritative label artifact.

The user-visible proof is a small cookbook import where the stage run writes Stage 2 and Stage 3 artifacts before recipe drafting, and the resulting recipes and non-recipe spans match those artifacts. The Label Studio prediction flow should no longer need to run a second post-stage “diagnostic” line-role pass when the label-first backbone is enabled, because the stage run itself already produced the authoritative labels.

## Progress

- [x] (2026-03-15_22.20.45) Re-read `docs/PLANS.md` before drafting this ExecPlan.
- [x] (2026-03-15_22.20.45) Re-read `docs/plans/Refactor.md`, especially `# Recommended Migration Strategy` and `## Phase 2 — Make labeling the source of truth`.
- [x] (2026-03-15_22.20.45) Re-read `docs/01-architecture/01-architecture_README.md` and `docs/06-label-studio/06-label-studio_README.md` to ground the plan in the current runtime and Label Studio prediction flow.
- [x] (2026-03-15_22.20.45) Inspected the current candidate-first seams in `cookimport/core/models.py`, `cookimport/plugins/epub.py`, `cookimport/plugins/text.py`, `cookimport/staging/import_session.py`, `cookimport/parsing/canonical_line_roles.py`, `cookimport/parsing/recipe_block_atomizer.py`, and `cookimport/labelstudio/ingest.py`.
- [x] (2026-03-15_22.20.45) Recorded the implementation seam in `docs/understandings/2026-03-15_22.20.45-phase2-label-first-runtime-seam.md`.
- [x] (2026-03-15_22.20.45) Wrote this ExecPlan.
- [ ] Introduce the Phase 2 backbone setting and authoritative Stage 2/3 contracts.
- [ ] Switch stage/import and prediction generation to produce recipe ownership from authoritative labels.
- [ ] Remove the extra post-stage diagnostic line-role pass from the label-first path while preserving the legacy path behind a compatibility toggle.
- [ ] Validate the new backbone on a real cutdown book and update docs touched by the new runtime.

## Surprises & Discoveries

- Observation: the repo already has most of the Stage 2 classifier behavior, but it lives in the wrong place in the pipeline.
  Evidence: `cookimport/parsing/canonical_line_roles.py` already returns `CanonicalLineRolePrediction` rows with `block_id`, `block_index`, `atomic_index`, `label`, `confidence`, `decided_by`, and `reason_tags`, but `cookimport/labelstudio/ingest.py` currently runs it after authoritative stage outputs exist and marks the projection as `mode: "diagnostics_only"`.

- Observation: the main obstacle is ownership, not label vocabulary.
  Evidence: importer code such as `cookimport/plugins/epub.py::_detect_candidates(...)` and `cookimport/plugins/text.py::_split_recipes(...)` still decides recipe boundaries before Stage 2 labels exist, while `ConversionResult` in `cookimport/core/models.py` is still built around `recipes` plus `non_recipe_blocks`.

- Observation: a compatibility adapter is the safest Phase 2 shape.
  Evidence: `cookimport/staging/import_session.py` still expects a `ConversionResult`, and Phase 3 already owns the heavier rewrite of deterministic intermediate recipe building plus the LLM recipe correction contract. Phase 2 should therefore change ownership first, then adapt back into the existing session boundary until Phase 3 lands.

## Decision Log

- Decision: treat Phase 2 as a backbone rewrite with a rollout toggle instead of a one-shot hard cutover.
  Rationale: `cookimport` has multiple entrypoints that currently depend on candidate-first `ConversionResult` semantics. A toggle makes it possible to prove behavior in stage runs, benchmark prediction runs, and Label Studio flows without breaking the legacy path on day one.
  Date/Author: 2026-03-15 / Codex

- Decision: make the authoritative Stage 2 unit the segmented line, not the legacy recipe candidate.
  Rationale: the existing atomizer already preserves `block_id` and `block_index` while producing a stable ordered `atomic_index`. That gives the pipeline a labelable unit that remains traceable to Phase 1 block evidence.
  Date/Author: 2026-03-15 / Codex

- Decision: keep `cookimport/staging/import_session.py` as the downstream session boundary during Phase 2, and feed it through a compatibility adapter.
  Rationale: the refactor document assigns the larger “labeled span -> intermediate recipe object -> one LLM correction stage” rewrite to the next migration phase. Phase 2 should not take on that additional scope.
  Date/Author: 2026-03-15 / Codex

- Decision: on the label-first backbone, Label Studio and benchmark flows must consume the stage-produced authoritative labels rather than re-running a second line-role pass after stage output generation.
  Rationale: keeping both paths alive in the same run would reintroduce the exact ambiguity Phase 2 is supposed to remove.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

This plan is not implemented yet. The intended outcome is a runtime where the answer to “is this recipe text, knowledge text, or other text?” is settled once in Stage 2 and reused everywhere else. The main residual risk is migration pressure around the current `ConversionResult` shape. The compatibility adapter described below is the chosen containment boundary for that risk.

## Context and Orientation

Today the repo has two different views of line labeling.

The first view is authoritative runtime ownership. Importers under `cookimport/plugins/` still decide recipe candidates directly. `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py` call `_detect_candidates(...)`; `cookimport/plugins/text.py` calls `_split_recipes(...)`; those importer decisions populate `ConversionResult.recipes` and `ConversionResult.non_recipe_blocks` in `cookimport/core/models.py`. `cookimport/staging/import_session.py` then performs LLM recipe correction, knowledge harvesting, and output writing from that candidate-first result.

The second view is canonical labeling. `cookimport/parsing/recipe_block_atomizer.py` turns blocks into stable, labelable line rows. `cookimport/parsing/canonical_line_roles.py` applies deterministic rules first and optional Codex correction second. `cookimport/labelstudio/canonical_line_projection.py` can project those labels into freeform span artifacts and benchmark block predictions. But this path is launched from `cookimport/labelstudio/ingest.py` after the main stage outputs already exist, and the resulting projections are explicitly non-authoritative diagnostics.

Phase 2 resolves that split. In this plan, “authoritative” means the artifact that later stages are required to consume as the single source of truth. “Segmented line” means one ordered Stage 1 unit that still points back to a stable source `block_id` and `block_index`; in practice this will be the existing atomizer output unless the Phase 1 implementation already provides an equivalent contract. “Compatibility adapter” means temporary code that converts label-first spans back into the existing `ConversionResult` shape so the later recipe-writing session can remain intact until Phase 3 replaces it.

The plan assumes Phase 1 already gave the repo an inspectable Stage 1 artifact and stage-aware writers. If Phase 1 landed those pieces under slightly different file names, keep the behavior but provide the interfaces named below before proceeding, so the rest of this plan remains concrete and repeatable.

## Milestones

### Milestone 1: Introduce explicit label-first contracts and a safe rollout toggle

At the end of this milestone, the repo should have one named runtime switch that selects between the legacy candidate-first backbone and the new label-first backbone, plus explicit data models for authoritative labeled lines and grouped recipe spans.

Add a run-setting such as `pipeline_backbone` with allowed values `legacy-candidate-v1` and `label-first-v1`. Default it to `legacy-candidate-v1` until the new path is proven. Document the setting in the CLI and run-manifest metadata so benchmark and Label Studio artifacts can report which backbone generated them.

Define the Phase 2 contracts in a stable module, preferably `cookimport/parsing/label_source_of_truth.py` if Phase 1 did not already create one. The file should define at least three public models and keep them Pydantic-based like the rest of the repo:

    class AuthoritativeLabeledLine(BaseModel):
        source_block_id: str
        source_block_index: int
        atomic_index: int
        text: str
        within_recipe_span_hint: bool
        deterministic_label: str
        final_label: str
        confidence: float
        decided_by: Literal["rule", "codex", "fallback"]
        reason_tags: list[str] = Field(default_factory=list)

    class RecipeSpan(BaseModel):
        span_id: str
        start_atomic_index: int
        end_atomic_index: int
        atomic_indices: list[int]
        source_block_ids: list[str]
        title_atomic_index: int | None = None
        warnings: list[str] = Field(default_factory=list)

    class LabelFirstCompatibilityResult(BaseModel):
        labeled_lines: list[AuthoritativeLabeledLine]
        recipe_spans: list[RecipeSpan]
        non_recipe_lines: list[AuthoritativeLabeledLine]
        conversion_result: ConversionResult

If `CanonicalLineRolePrediction` is already deeply embedded in code, it is acceptable to extend that model instead of creating a sibling type, but the final contract must expose both the deterministic label and the final authoritative label so diffs are inspectable. Do not leave “baseline label” implicit.

Acceptance for this milestone is that a contributor can point to one runtime flag and one set of Phase 2 models and explain exactly how the label-first path will be wired without reading the rest of the repo.

### Milestone 2: Run authoritative Stage 2 labeling before recipe ownership is decided

At the end of this milestone, the label-first backbone should consume Phase 1 segmented lines, run deterministic labeling plus optional Codex correction, and persist authoritative Stage 2 artifacts before any recipe grouping occurs.

Implement a single orchestration function such as `label_segmented_lines(...)` in `cookimport/parsing/label_source_of_truth.py`. It should accept the Phase 1 segmented-line artifact, the current `RunSettings`, and the same Codex execution controls the repo already uses for canonical line-role. Reuse `cookimport/parsing/recipe_block_atomizer.py` and `cookimport/parsing/canonical_line_roles.py` rather than cloning their heuristics. The new function’s job is to normalize those existing outputs into the authoritative Stage 2 contract and write both artifact views:

- deterministic labels, one row per labeled line;
- corrected final labels, one row per labeled line;
- an explicit diff indicator when the final label differs from the deterministic label.

Add writer helpers in `cookimport/staging/writer.py` for the authoritative Stage 2 files if Phase 1 did not already create them. Use the artifact names from `docs/plans/Refactor.md` unless Phase 1 already checked in equivalent names. The important rule is that stage runs, benchmark prediction runs, and Label Studio prediction runs all read the same Stage 2 outputs from the same run root.

Acceptance for this milestone is that a stage run with `pipeline_backbone=label-first-v1` writes Stage 2 artifacts before any recipe drafts are written, and a reviewer can inspect label changes without consulting benchmark-only diagnostics.

### Milestone 3: Group recipe spans deterministically from labels and adapt back into the legacy session boundary

At the end of this milestone, Stage 3 recipe ownership should come entirely from authoritative labels, and the downstream stage session should receive a compatibility `ConversionResult` derived from those labels instead of from importer candidate heuristics.

Create `cookimport/parsing/recipe_span_grouping.py` and define one public entrypoint:

    def group_recipe_spans_from_labels(
        labeled_lines: Sequence[AuthoritativeLabeledLine],
    ) -> tuple[list[RecipeSpan], list[AuthoritativeLabeledLine]]:

This function should be pure and deterministic. It should start a span at a title-like recipe label, continue through recipe-local labels, stop at the next strong recipe title or a strong non-recipe boundary, and preserve warnings when the label sequence is inconsistent. It must not call an LLM. It must not look at importer-specific candidate spans.

Then create a compatibility adapter, preferably in `cookimport/parsing/label_first_conversion.py`. Define one public function:

    def build_conversion_result_from_label_spans(
        *,
        source_file: Path,
        importer_name: str,
        labeled_lines: Sequence[AuthoritativeLabeledLine],
        recipe_spans: Sequence[RecipeSpan],
        phase1_artifacts: Any,
    ) -> LabelFirstCompatibilityResult

The adapter should produce three things from the authoritative labels:

1. a `ConversionResult.recipes` list that keeps later stages working;
2. a `ConversionResult.non_recipe_blocks` list built from the non-recipe lines left after recipe grouping;
3. a Phase 2 bundle containing labeled lines and recipe spans for artifact writing and downstream reuse.

Do not let importer candidate detection participate in the authoritative path. On `legacy-candidate-v1`, importer heuristics still own recipe grouping. On `label-first-v1`, importer heuristics may be retained only for diagnostics or regression comparison reports.

Acceptance for this milestone is that `cookimport/staging/import_session.py` can run unchanged on the compatibility `ConversionResult`, while Stage 2 and Stage 3 artifacts clearly show that recipe ownership came from labels first.

### Milestone 4: Switch stage, benchmark, and Label Studio prediction flows to the label-first backbone

At the end of this milestone, the label-first backbone should be exercised by the real entrypoints that currently produce stage-backed outputs and Label Studio prediction runs.

Update `cookimport/cli.py` so the main `stage` path chooses between the legacy importer-owned conversion and the new label-first orchestration based on `pipeline_backbone`. The label-first path should call the Phase 1 segmented-line producer, run Stage 2 labeling, run Stage 3 grouping, build the compatibility `ConversionResult`, then hand off to `cookimport/staging/import_session.py`.

Update `cookimport/labelstudio/ingest.py` in the same way. On `label-first-v1`, it must not run a second post-stage `label_atomic_lines(...)` pass after `execute_stage_import_session_from_result(...)` finishes. Instead, it should read the authoritative Stage 2 artifacts produced by the stage session or carry the in-memory Phase 2 bundle through to the freeform-span projection helpers. If a benchmark or prediction run needs `stage_block_predictions.json`, generate it from the authoritative labels inside the stage session, not from a later diagnostic rerun.

Keep the legacy benchmark and import behavior intact behind `legacy-candidate-v1` until Phase 2 validation is complete. The important invariant is simple: one backbone per run, one authoritative label artifact per run.

Acceptance for this milestone is that stage runs and Label Studio prediction runs can both operate in label-first mode without any duplicate line-role pass appearing later in the pipeline.

### Milestone 5: Lock in tests, real-run validation, and docs

At the end of this milestone, the new backbone should be protected by targeted tests and one real cookbook run.

Add focused tests:

- `tests/parsing/test_recipe_span_grouping.py` for deterministic grouping from label sequences, including mixed recipe/non-recipe transitions, section headings, note attachment, and ambiguous boundaries.
- `tests/parsing/test_label_first_conversion.py` for the compatibility adapter, especially the contract that non-recipe residue comes from authoritative labels rather than importer candidate leftovers.
- Extend `tests/parsing/test_canonical_line_roles.py` to assert deterministic-vs-final label diffs are persisted in the authoritative model.
- Extend `tests/labelstudio/test_labelstudio_ingest_parallel.py` so label-first mode proves that Label Studio prediction generation consumes authoritative Stage 2 artifacts and does not rerun line-role as a separate diagnostics-only stage.
- Extend the relevant CLI or staging tests so `pipeline_backbone` is recorded in run metadata and switches the correct path.

Then run one real end-to-end cutdown book, preferably `data/input/saltfatacidheatCUTDOWN.epub`, in label-first mode. Confirm that the run root contains authoritative Stage 2 and Stage 3 artifacts, that recipe drafts and stage block predictions align with those artifacts, and that Label Studio prediction generation can consume the same run without adding a duplicate line-role pass.

Update the short docs that future contributors will actually open first: `docs/01-architecture/01-architecture_README.md`, `docs/06-label-studio/06-label-studio_README.md`, and a short note in the nearest code folder such as `cookimport/parsing/README.md` or `cookimport/staging/README.md`, depending on where the authoritative orchestration lands. Keep that note short and explain only the new backbone boundary.

Acceptance for this milestone is a passing targeted test slice plus a real stage run where a human can trace a recipe span back to authoritative Stage 2 labels without consulting legacy candidate heuristics.

## Plan of Work

Start by making the migration explicit. Add the backbone setting and record it everywhere run configuration is serialized, because later debugging becomes much harder if benchmark or Label Studio artifacts cannot say whether they were produced by the legacy path or the label-first path.

Next, normalize the Stage 2 contract around the existing line-role machinery instead of creating a second classifier. The authoritative model must carry both the deterministic label and the final label. If the existing `CanonicalLineRolePrediction` model can be extended safely, do that; if it cannot, wrap it in a new model rather than leaving the “before” label implicit. Wire the writer so Stage 2 outputs are persisted as normal run artifacts, not only benchmark helpers.

After Stage 2 exists as a real runtime artifact, write the deterministic span grouper and keep it pure. This is the moment where recipe ownership changes. Do not let importer-local `_detect_candidates(...)` or `_split_recipes(...)` remain in the authoritative path once the label-first backbone is selected.

Then add the compatibility adapter that turns label-first spans into the current `ConversionResult`. Be disciplined about this boundary. Phase 2 is successful if the repo changes who owns recipe grouping, not if it simultaneously rewrites Stage 4, Stage 5, and Stage 6. The adapter can be temporary and even slightly redundant so long as it makes the ownership transition explicit and testable.

Finally, switch the main entrypoints. `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` should each pick one backbone per run. On the label-first path they should reuse the stage-produced label artifacts; on the legacy path they should preserve today’s behavior until confidence is high enough to flip the default in a later follow-up.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`.

Prepare the environment:

    source .venv/bin/activate
    pip install -e .[dev]

Before coding, capture the current narrow baseline around line-role and Label Studio prediction plumbing:

    source .venv/bin/activate
    pytest tests/parsing/test_canonical_line_roles.py -q
    pytest tests/labelstudio/test_labelstudio_ingest_parallel.py -q -k line_role

During implementation, add and run the new focused grouping and adapter slices:

    source .venv/bin/activate
    pytest tests/parsing/test_recipe_span_grouping.py -q
    pytest tests/parsing/test_label_first_conversion.py -q

After wiring the backbone toggle through the real entrypoints, rerun the targeted integration coverage:

    source .venv/bin/activate
    pytest tests/parsing/test_canonical_line_roles.py -q
    pytest tests/labelstudio/test_labelstudio_ingest_parallel.py -q

Then run a real stage import in label-first mode against a small existing sample:

    source .venv/bin/activate
    cookimport stage data/input/saltfatacidheatCUTDOWN.epub \
      --out /tmp/recipeimport-phase2-check \
      --line-role-pipeline codex-line-role-v1 \
      --pipeline-backbone label-first-v1

Expected outcome after Phase 2:

    the run root under /tmp/recipeimport-phase2-check/<timestamp>/ contains Stage 2 label artifacts,
    Stage 3 recipe span artifacts, final drafts, intermediate drafts, and .bench stage predictions

If the repo also exposes an offline Label Studio prediction command against the same backbone, run one narrow follow-up:

    source .venv/bin/activate
    cookimport labelstudio-benchmark data/input/saltfatacidheatCUTDOWN.epub \
      --no-upload \
      --output-dir /tmp/recipeimport-phase2-benchmark \
      --processed-output-dir /tmp/recipeimport-phase2-processed \
      --line-role-pipeline codex-line-role-v1 \
      --pipeline-backbone label-first-v1

Expected outcome after Phase 2:

    the prediction run reuses authoritative Stage 2 labels and does not write a second diagnostics-only line-role pass after stage output generation

## Validation and Acceptance

Validation is behavioral, not structural.

For a stage run in label-first mode, acceptance means:

- Stage 2 writes inspectable deterministic and final label artifacts before recipe drafts are written.
- Stage 3 writes recipe spans whose boundaries can be explained directly from Stage 2 labels.
- The resulting `ConversionResult`-backed recipe drafts and non-recipe outputs agree with those spans.
- `.bench/<workbook_slug>/stage_block_predictions.json` is derived from the authoritative label artifact, not from a second post-stage line-role pass.

For a Label Studio prediction run in label-first mode, acceptance means:

- the run metadata records `pipeline_backbone=label-first-v1`;
- freeform-span prediction artifacts come from the stage-produced authoritative labels;
- no later diagnostics-only line-role execution mutates or redefines recipe ownership.

For the legacy path, acceptance means:

- `pipeline_backbone=legacy-candidate-v1` preserves current behavior;
- the new tests do not require label-first mode unless they are specifically testing the new backbone.

## Idempotence and Recovery

The migration is intentionally additive. Re-running a test or a stage command should either overwrite the same timestamped scratch root or create a new timestamped run root without damaging prior outputs.

If the label-first path fails mid-run, recovery is to switch back to `legacy-candidate-v1`, fix the failing Phase 2 seam, and rerun. Do not delete or rewrite the legacy importer candidate code until the label-first path has equivalent targeted coverage and a real cutdown-book validation run.

If the compatibility adapter proves too lossy for a specific downstream stage, capture that gap in this plan and patch only the adapter boundary. Do not bypass authoritative Stage 2 labels by reintroducing importer-owned grouping logic into the label-first path.

## Artifacts and Notes

The most important artifacts created by this plan are the authoritative label and grouping outputs. Keep them stable and easy to inspect. A successful run should make it easy to answer three questions from files alone:

1. What label did each segmented line receive before and after Codex correction?
2. Which contiguous lines were grouped into each recipe span, and why did each span start and stop where it did?
3. Which downstream recipe and non-recipe outputs came from those spans?

An example expected artifact set for a successful label-first run is:

    01_blocks.jsonl
    02_labels_deterministic.jsonl
    03_labels_corrected.jsonl
    04_recipe_spans.json
    08_nonrecipe_spans.json
    intermediate drafts/<workbook_slug>/...
    final drafts/<workbook_slug>/...
    .bench/<workbook_slug>/stage_block_predictions.json

If Phase 1 already named equivalent files differently, keep the current names but preserve the same observable meaning.

## Interfaces and Dependencies

Use the existing repo surfaces whenever possible. The important end-state interfaces are:

In `cookimport/parsing/label_source_of_truth.py`, define:

    def label_segmented_lines(
        *,
        segmented_lines: Sequence[Any],
        run_settings: RunSettings,
        artifact_root: Path | None,
        source_hash: str | None,
        live_llm_allowed: bool,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[AuthoritativeLabeledLine]:

This function must wrap the existing deterministic-plus-Codex line-role machinery and expose both deterministic and final labels.

In `cookimport/parsing/recipe_span_grouping.py`, define:

    def group_recipe_spans_from_labels(
        labeled_lines: Sequence[AuthoritativeLabeledLine],
    ) -> tuple[list[RecipeSpan], list[AuthoritativeLabeledLine]]:

This function must be pure, deterministic, and LLM-free.

In `cookimport/parsing/label_first_conversion.py`, define:

    def build_conversion_result_from_label_spans(
        *,
        source_file: Path,
        importer_name: str,
        labeled_lines: Sequence[AuthoritativeLabeledLine],
        recipe_spans: Sequence[RecipeSpan],
        phase1_artifacts: Any,
    ) -> LabelFirstCompatibilityResult:

This function is the only place in Phase 2 allowed to translate label-first ownership back into the legacy `ConversionResult` shape.

In `cookimport/config/run_settings.py`, add:

    pipeline_backbone: PipelineBackbone = PipelineBackbone.legacy_candidate_v1

and propagate it through CLI parsing, run-config serialization, and manifest/report metadata.

In `cookimport/cli.py` and `cookimport/labelstudio/ingest.py`, route one backbone per run. Do not mix the authoritative label-first path with the legacy candidate-first path inside one execution.

Plan update note: 2026-03-15_22.20.45 / Codex. Initial draft created from `docs/plans/Refactor.md` Phase 2, with the explicit assumption that Phase 1 observability has already been implemented to spec. The note exists so future revisions can explain how and why this plan changes over time.
