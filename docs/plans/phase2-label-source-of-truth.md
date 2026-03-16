---
summary: "ExecPlan for Phase 2 of the Refactor migration: make Stage 2 labeling authoritative so recipe grouping and non-recipe ownership flow from labels instead of importer candidate heuristics."
read_when:
  - "When implementing Phase 2 from docs/reports/Refactor.md"
  - "When moving stage/import and Label Studio prediction generation from candidate-first ownership to label-first ownership"
---

# Make Labeling the Source of Truth

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

Assumption for this plan: Phase 1 from `docs/reports/Refactor.md` has already been implemented to spec. In practical terms, that means the repo already has clear stage names, one shared `stage_observability.json` contract, and reporting that matches the pre-Phase-2 runtime. This plan does not spend time renaming stages or inventing observability from scratch. It uses that groundwork to change runtime ownership and to register the new label-first stages through the shared observability seam.

This plan is intentionally not conservative. It is a one-way migration to the new architecture. The repo should not keep a long-lived candidate-first backbone, a user-facing fallback toggle, or compatibility behavior whose only job is to preserve the old mental model. If a temporary internal shim is required to keep one downstream module working while the cutover is in flight, that shim must stay narrow, private, and explicitly temporary. The finished Phase 2 state is label-first only.

## Purpose / Big Picture

After this change, Stage 2 labels become the authoritative answer to the question “what is this line of cookbook text?” Recipe grouping, non-recipe residue, and later recipe parsing all flow from those labels instead of from importer-local candidate heuristics. A user running `cookimport stage` or `cookimport labelstudio-benchmark --no-upload` should be able to inspect the run folder and see that recipe spans, non-recipe spans, and stage block predictions were derived from the same authoritative label artifact.

The user-visible proof is a small cookbook import where the stage run writes Stage 2 and Stage 3 artifacts before recipe drafting, and the resulting recipes and non-recipe spans match those artifacts. The Label Studio prediction flow should no longer need to run a second post-stage “diagnostic” line-role pass, because the stage run itself already produced the authoritative labels. The user should not have to choose between “legacy” and “new” behavior. After this phase lands, the new paradigm is simply the runtime.

## Progress

- [x] (2026-03-15_22.20.45) Re-read `docs/PLANS.md` before drafting this ExecPlan.
- [x] (2026-03-15_22.20.45) Re-read `docs/reports/Refactor.md`, especially `# Recommended Migration Strategy` and `## Phase 2 — Make labeling the source of truth`.
- [x] (2026-03-15_22.20.45) Re-read `docs/01-architecture/01-architecture_README.md` and `docs/06-label-studio/06-label-studio_README.md` to ground the plan in the current runtime and Label Studio prediction flow.
- [x] (2026-03-15_22.20.45) Inspected the current candidate-first seams in `cookimport/core/models.py`, `cookimport/plugins/epub.py`, `cookimport/plugins/text.py`, `cookimport/staging/import_session.py`, `cookimport/parsing/canonical_line_roles.py`, `cookimport/parsing/recipe_block_atomizer.py`, and `cookimport/labelstudio/ingest.py`.
- [x] (2026-03-15_22.20.45) Recorded the implementation seam in `docs/understandings/2026-03-15_22.20.45-phase2-label-first-runtime-seam.md`.
- [x] (2026-03-15_22.20.45) Wrote this ExecPlan.
- [ ] Introduce the authoritative Stage 2/3 contracts and delete user-facing candidate-first ownership switches.
- [ ] Switch stage/import and prediction generation to produce recipe ownership from authoritative labels.
- [ ] Remove the extra post-stage diagnostic line-role pass and delete the duplicate candidate-first ownership path from entrypoints.
- [ ] Validate the new runtime on a real cutdown book and update docs touched by the new runtime.

## Surprises & Discoveries

- Observation: the repo already has most of the Stage 2 classifier behavior, but it lives in the wrong place in the pipeline.
  Evidence: `cookimport/parsing/canonical_line_roles.py` already returns `CanonicalLineRolePrediction` rows with `block_id`, `block_index`, `atomic_index`, `label`, `confidence`, `decided_by`, and `reason_tags`, but `cookimport/labelstudio/ingest.py` currently runs it after authoritative stage outputs exist and marks the projection as `mode: "diagnostics_only"`.

- Observation: the main obstacle is ownership, not label vocabulary.
  Evidence: importer code such as `cookimport/plugins/epub.py::_detect_candidates(...)` and `cookimport/plugins/text.py::_split_recipes(...)` still decides recipe boundaries before Stage 2 labels exist, while `ConversionResult` in `cookimport/core/models.py` is still built around `recipes` plus `non_recipe_blocks`.

- Observation: `ConversionResult` is still a real implementation seam even though candidate-first ownership should be removed.
  Evidence: `cookimport/staging/import_session.py` still expects a `ConversionResult`, and Phase 3 already owns the heavier rewrite of deterministic intermediate recipe building plus the LLM recipe correction contract. If Phase 2 needs an adapter, it should exist only as a narrow internal seam while the repo ships one label-first runtime.

## Decision Log

- Decision: treat Phase 2 as a one-way cutover, not a dual-backbone rollout.
  Rationale: the refactor goal is to replace candidate-first ownership, not preserve it behind a switch. Keeping both backbones alive would prolong stale code, duplicate debugging surfaces, and weaken the new architecture’s authority boundary.
  Date/Author: 2026-03-15 / Codex

- Decision: keep segmented lines as the detailed labeling input, but normalize Phase 2 outputs into one final block-label view and block-range recipe-span view before downstream handoff.
  Rationale: the atomizer is still the right place to run fine-grained labeling and diff inspection, but Phases 3 and 4 consume recipe ownership and non-recipe ownership in block terms. Phase 2 therefore needs both line-level detail and block-level normalized truth instead of forcing later phases to reinterpret atomic rows independently.
  Date/Author: 2026-03-15 / Codex

- Decision: if Phase 2 uses a `ConversionResult` adapter, keep it private and temporary rather than presenting it as a supported compatibility mode.
  Rationale: the refactor document assigns the larger “labeled span -> intermediate recipe object -> one LLM correction stage” rewrite to the next migration phase, so a narrow internal seam may still be practical. But the repo should not expose or defend the old candidate-first runtime as a first-class path.
  Date/Author: 2026-03-15 / Codex

- Decision: Label Studio and benchmark flows must consume the stage-produced authoritative labels rather than re-running a second line-role pass after stage output generation.
  Rationale: keeping both paths alive in the same run would reintroduce the exact ambiguity Phase 2 is supposed to remove.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

This plan is not implemented yet. The intended outcome is a runtime where the answer to “is this recipe text, knowledge text, or other text?” is settled once in Stage 2 and reused everywhere else. The main residual risk is migration pressure around the current `ConversionResult` shape. If an adapter is required, it is a narrow implementation seam, not a product compatibility promise or a reason to keep the old candidate-first path alive.

## Context and Orientation

Today the repo has two different views of line labeling.

The first view is authoritative runtime ownership. Importers under `cookimport/plugins/` still decide recipe candidates directly. `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py` call `_detect_candidates(...)`; `cookimport/plugins/text.py` calls `_split_recipes(...)`; those importer decisions populate `ConversionResult.recipes` and `ConversionResult.non_recipe_blocks` in `cookimport/core/models.py`. `cookimport/staging/import_session.py` then performs LLM recipe correction, knowledge harvesting, and output writing from that candidate-first result.

The second view is canonical labeling. `cookimport/parsing/recipe_block_atomizer.py` turns blocks into stable, labelable line rows. `cookimport/parsing/canonical_line_roles.py` applies deterministic rules first and optional Codex correction second. `cookimport/labelstudio/canonical_line_projection.py` can project those labels into freeform span artifacts and benchmark block predictions. But this path is launched from `cookimport/labelstudio/ingest.py` after the main stage outputs already exist, and the resulting projections are explicitly non-authoritative diagnostics.

Phase 2 resolves that split. In this plan, “authoritative” means the artifact that later stages are required to consume as the single source of truth. A “segmented line” means one ordered Stage 1 unit that still points back to a stable source `block_id` and `block_index`; in practice this will be the existing atomizer output unless the Phase 1 implementation already provides an equivalent contract. A “final block label” means the one normalized Stage 2 label that Phase 2 exposes for one source block after line-level labeling is complete. A “recipe span” means a half-open block range plus optional atomic evidence fields that explain how the grouped range was formed. A “temporary adapter” means private code that converts label-first spans into the current `ConversionResult` shape only where unavoidable while the surrounding runtime is being cut over. It is not a rollback mechanism and must not keep candidate-first ownership alive as a parallel architecture.

The plan assumes Phase 1 already gave the repo stage-aware reporting and artifact registration, not that it already implemented the full label-first evidence model. If the repo still lacks one inspectable segmented-line artifact when this phase begins, Phase 2 must introduce or formalize that artifact as part of the label-first backbone work. Keep the behavior concrete and repeatable by providing the interfaces named below even if the underlying file names differ.

## Milestones

### Milestone 1: Introduce explicit label-first contracts and remove user-facing legacy switches

At the end of this milestone, the repo should have explicit data models for line-level labels, normalized block-level labels, grouped recipe spans, and the one handoff bundle later phases must consume. It should not have a user-facing runtime switch that preserves candidate-first ownership as a supported alternative.

Delete any user-facing backbone toggle if one exists, or avoid introducing one if it does not. If run metadata needs to record architecture for clarity, write a descriptive immutable value such as `pipeline_architecture=label-first-v1` in manifests and reports, but do not let operators choose a candidate-first runtime after this phase lands.

This milestone must also reserve the semantic stage keys that this phase introduces. Follow the naming guidance in `docs/reports/Refactor.md`: the deterministic Stage 2 pass should surface as `label_det`, the optional LLM correction pass as `label_llm_correct`, and deterministic span grouping as `group_recipe_spans`. Human-facing labels may be friendlier, but `stage_observability.json` should carry these semantic keys so later phases inherit one naming scheme.

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

    class AuthoritativeBlockLabel(BaseModel):
        source_block_id: str
        source_block_index: int
        supporting_atomic_indices: list[int]
        deterministic_label: str
        final_label: str
        confidence: float
        decided_by: Literal["rule", "codex", "fallback"]
        reason_tags: list[str] = Field(default_factory=list)

    class RecipeSpan(BaseModel):
        span_id: str
        start_block_index: int
        end_block_index: int
        block_indices: list[int]
        source_block_ids: list[str]
        start_atomic_index: int | None = None
        end_atomic_index: int | None = None
        atomic_indices: list[int] = Field(default_factory=list)
        title_block_index: int | None = None
        title_atomic_index: int | None = None
        warnings: list[str] = Field(default_factory=list)

    class LabelStageResult(BaseModel):
        labeled_lines: list[AuthoritativeLabeledLine]
        block_labels: list[AuthoritativeBlockLabel]

    class LabelFirstCompatibilityResult(BaseModel):
        labeled_lines: list[AuthoritativeLabeledLine]
        block_labels: list[AuthoritativeBlockLabel]
        recipe_spans: list[RecipeSpan]
        non_recipe_lines: list[AuthoritativeLabeledLine]
        conversion_result: ConversionResult

This `LabelFirstCompatibilityResult` shape, or one thin adapter that is equivalent in meaning, is the only Phase 2 handoff later phases should consume. Phase 3 should read `block_labels` plus `recipe_spans` from it when preparing recipe correction, and Phase 4 should read the same normalized `block_labels` plus `recipe_spans` when deriving non-recipe ownership. Neither later phase should have to reinterpret raw atomic labels or importer-owned candidates to rediscover that authority boundary.

If `CanonicalLineRolePrediction` is already deeply embedded in code, it is acceptable to extend that model instead of creating a sibling type, but the final contract must expose both the deterministic label and the final authoritative label so diffs are inspectable. Do not leave “baseline label” implicit.

Acceptance for this milestone is that a contributor can point to one set of Phase 2 models and one authoritative runtime path and explain exactly how the label-first system is wired without reading the rest of the repo.

### Milestone 2: Run authoritative Stage 2 labeling before recipe ownership is decided

At the end of this milestone, the runtime should consume Phase 1 segmented lines, run deterministic labeling plus optional Codex correction, normalize those results into one final block-label view, and persist authoritative Stage 2 artifacts before any recipe grouping occurs.

Implement a single orchestration function such as `label_segmented_lines(...)` in `cookimport/parsing/label_source_of_truth.py`. It should accept the Phase 1 segmented-line artifact, the current `RunSettings`, and the same Codex execution controls the repo already uses for canonical line-role. Reuse `cookimport/parsing/recipe_block_atomizer.py` and `cookimport/parsing/canonical_line_roles.py` rather than cloning their heuristics. The new function’s job is to normalize those existing outputs into the authoritative Stage 2 contract and write both artifact views:

- deterministic labels, one row per labeled line;
- corrected final labels, one row per labeled line;
- one normalized final label per source block for downstream ownership and benchmark/staging readers;
- an explicit diff indicator when the final label differs from the deterministic label.

Add writer helpers in `cookimport/staging/writer.py` for the authoritative Stage 2 files if Phase 1 did not already create them. Use the artifact names from `docs/reports/Refactor.md` unless Phase 1 already checked in equivalent names. The important rule is that stage runs, benchmark prediction runs, and Label Studio prediction runs all read the same Stage 2 outputs from the same run root.

When these artifacts are written, register them through the Phase 1 observability contract so `stage_observability.json` records `label_det` and `label_llm_correct` with truthful status and artifact ownership. If the LLM correction step is disabled, record `label_llm_correct` as skipped or absent through that shared stage layer rather than inferring it later from ad hoc summary logic.

Acceptance for this milestone is that a normal stage run writes Stage 2 artifacts before any recipe drafts are written, and a reviewer can inspect label changes without consulting benchmark-only diagnostics.

### Milestone 3: Group recipe spans deterministically from labels and bridge only where unavoidable

At the end of this milestone, Stage 3 recipe ownership should come entirely from normalized block labels, and any downstream session seam should receive data derived from those labels instead of from importer candidate heuristics.

Create `cookimport/parsing/recipe_span_grouping.py` and define one public entrypoint:

    def group_recipe_spans_from_labels(
        block_labels: Sequence[AuthoritativeBlockLabel],
        labeled_lines: Sequence[AuthoritativeLabeledLine],
    ) -> tuple[list[RecipeSpan], list[AuthoritativeBlockLabel]]:

This function should be pure and deterministic. It should start a span at a title-like recipe label, continue through recipe-local labels, stop at the next strong recipe title or a strong non-recipe boundary, and preserve warnings when the label sequence is inconsistent. Its owned output must be block-range spans, with atomic indices retained only as supporting evidence. It must not call an LLM. It must not look at importer-specific candidate spans.

If the existing stage session still requires `ConversionResult`, create a temporary adapter, preferably in `cookimport/parsing/label_first_conversion.py`. Define one public function:

    def build_conversion_result_from_label_spans(
        *,
        source_file: Path,
        importer_name: str,
        labeled_lines: Sequence[AuthoritativeLabeledLine],
        block_labels: Sequence[AuthoritativeBlockLabel],
        recipe_spans: Sequence[RecipeSpan],
        phase1_artifacts: Any,
    ) -> LabelFirstCompatibilityResult

The adapter should produce three things from the authoritative labels:

1. a `ConversionResult.recipes` list that keeps later stages working;
2. a `ConversionResult.non_recipe_blocks` list built from the non-recipe lines left after recipe grouping;
3. a Phase 2 bundle containing labeled lines and recipe spans for artifact writing and downstream reuse.

Do not let importer candidate detection participate in the authoritative path. Delete or disconnect importer-owned recipe grouping once the label-first grouping path is wired. If any candidate-first helper is temporarily retained during the edit sequence, it may exist only long enough to support an in-flight patch series and must not remain as a supported runtime path.

Acceptance for this milestone is that `cookimport/staging/import_session.py` can consume the new label-driven handoff, whether directly or through a narrow private adapter, while Stage 2 and Stage 3 artifacts clearly show that recipe ownership came from labels first and candidate-first ownership code is no longer part of the runtime path.

### Milestone 4: Switch stage, benchmark, and Label Studio prediction flows to the label-first runtime and remove the old path

At the end of this milestone, the label-first runtime should be exercised by the real entrypoints that currently produce stage-backed outputs and Label Studio prediction runs, and the old candidate-first ownership path should be gone from those entrypoints.

Update `cookimport/cli.py` so the main `stage` path always uses the new label-first orchestration. It should call the Phase 1 segmented-line producer, run Stage 2 labeling, run Stage 3 grouping, build the temporary adapter result only if still required, then hand off to `cookimport/staging/import_session.py`.

Update `cookimport/labelstudio/ingest.py` in the same way. It must not run a second post-stage `label_atomic_lines(...)` pass after `execute_stage_import_session_from_result(...)` finishes. Instead, it should read the authoritative Stage 2 artifacts produced by the stage session or carry the in-memory Phase 2 bundle through to the freeform-span projection helpers. If a benchmark or prediction run needs `stage_block_predictions.json`, generate it from the authoritative block-label view inside the stage session, not from a later diagnostic rerun.

The run should expose `label_det`, `label_llm_correct`, and `group_recipe_spans` as first-class observed stages in `stage_observability.json` before any recipe-drafting stage begins. Do not teach these stage names separately in `run_summary`, Label Studio helpers, or benchmark renderers; those surfaces should inherit them through the Phase 1 shared contract.

Delete the legacy benchmark and import behavior from the real entrypoints as part of this milestone. The important invariant is simple: one runtime, one authoritative label artifact per run.

Acceptance for this milestone is that stage runs and Label Studio prediction runs both operate on the new runtime without any duplicate line-role pass appearing later in the pipeline and without any user-facing escape hatch back to candidate-first ownership.

### Milestone 5: Lock in tests, real-run validation, and docs

At the end of this milestone, the new runtime should be protected by targeted tests and one real cookbook run.

Add focused tests:

- `tests/parsing/test_recipe_span_grouping.py` for deterministic grouping from label sequences, including mixed recipe/non-recipe transitions, section headings, note attachment, and ambiguous boundaries.
- `tests/parsing/test_label_first_conversion.py` for the temporary adapter, especially the contract that non-recipe residue comes from authoritative labels rather than importer candidate leftovers.
- Extend `tests/parsing/test_canonical_line_roles.py` to assert deterministic-vs-final label diffs are persisted in the authoritative model and that Phase 2 normalizes one final label per source block.
- Extend `tests/labelstudio/test_labelstudio_ingest_parallel.py` so the runtime proves that Label Studio prediction generation consumes authoritative Stage 2 artifacts and does not rerun line-role as a separate diagnostics-only stage.
- Extend the relevant CLI or staging tests so there is one label-first path and no surviving candidate-first branch in the entrypoint logic.

Then run one real end-to-end cutdown book, preferably `data/input/saltfatacidheatCUTDOWN.epub`. Confirm that the run root contains authoritative Stage 2 and Stage 3 artifacts, that recipe drafts and stage block predictions align with those artifacts, and that Label Studio prediction generation can consume the same run without adding a duplicate line-role pass.

Update the short docs that future contributors will actually open first: `docs/01-architecture/01-architecture_README.md`, `docs/06-label-studio/06-label-studio_README.md`, and a short note in the nearest code folder such as `cookimport/parsing/README.md` or `cookimport/staging/README.md`, depending on where the authoritative orchestration lands. Keep that note short and explain only the new backbone boundary.

Acceptance for this milestone is a passing targeted test slice plus a real stage run where a human can trace a recipe span back to authoritative Stage 2 labels without consulting legacy candidate heuristics, and where the deleted candidate-first route cannot be selected because it no longer exists.

## Plan of Work

Start by making the migration explicit. Remove any user-facing choice that preserves candidate-first ownership, and make manifests/reports record only the new architecture identity if that metadata is still useful.

Next, normalize the Stage 2 contract around the existing line-role machinery instead of creating a second classifier. The authoritative model must carry both the deterministic label and the final label. If the existing `CanonicalLineRolePrediction` model can be extended safely, do that; if it cannot, wrap it in a new model rather than leaving the “before” label implicit. Wire the writer so Stage 2 outputs are persisted as normal run artifacts, not only benchmark helpers.

After Stage 2 exists as a real runtime artifact, write the deterministic span grouper and keep it pure. This is the moment where recipe ownership changes. Do not let importer-local `_detect_candidates(...)` or `_split_recipes(...)` remain in the authoritative path once the label-first runtime is selected.

Then add the temporary adapter that turns label-first spans into the current `ConversionResult` only if the downstream session still requires it. Be disciplined about this boundary. Phase 2 is successful if the repo changes who owns recipe grouping, not if it simultaneously rewrites Stage 4, Stage 5, and Stage 6. The adapter may be temporarily redundant, but it must not become a public compatibility story or justify keeping candidate-first code alive.

Finally, switch the main entrypoints. `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` should each use the new runtime unconditionally, reuse the stage-produced label artifacts, and register their new stages through the Phase 1 observability seam. Delete the old candidate-first entrypoint branches as part of the same cutover.

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

After wiring the new runtime through the real entrypoints, rerun the targeted integration coverage:

    source .venv/bin/activate
    pytest tests/parsing/test_canonical_line_roles.py -q
    pytest tests/labelstudio/test_labelstudio_ingest_parallel.py -q

Then run a real stage import in label-first mode against a small existing sample:

    source .venv/bin/activate
    cookimport stage data/input/saltfatacidheatCUTDOWN.epub \
      --out /tmp/recipeimport-phase2-check \
      --line-role-pipeline codex-line-role-v1

Expected outcome after Phase 2:

    the run root under /tmp/recipeimport-phase2-check/<timestamp>/ contains Stage 2 label artifacts,
    Stage 3 recipe span artifacts, final drafts, intermediate drafts, and .bench stage predictions

If the repo also exposes an offline Label Studio prediction command against the same runtime, run one narrow follow-up:

    source .venv/bin/activate
    cookimport labelstudio-benchmark data/input/saltfatacidheatCUTDOWN.epub \
      --no-upload \
      --output-dir /tmp/recipeimport-phase2-benchmark \
      --processed-output-dir /tmp/recipeimport-phase2-processed \
      --line-role-pipeline codex-line-role-v1

Expected outcome after Phase 2:

    the prediction run reuses authoritative Stage 2 labels and does not write a second diagnostics-only line-role pass after stage output generation

## Validation and Acceptance

Validation is behavioral, not structural.

For a stage run, acceptance means:

- Stage 2 writes inspectable deterministic and final label artifacts before recipe drafts are written.
- Stage 3 writes recipe spans whose boundaries can be explained directly from Stage 2 labels.
- The resulting `ConversionResult`-backed recipe drafts and non-recipe outputs agree with those spans.
- `.bench/<workbook_slug>/stage_block_predictions.json` is derived from the authoritative block-label artifact, not from a second post-stage line-role pass.

For a Label Studio prediction run, acceptance means:

- the run metadata, if it records architecture at all, records only the new label-first architecture;
- freeform-span prediction artifacts come from the stage-produced authoritative labels;
- no later diagnostics-only line-role execution mutates or redefines recipe ownership.

## Idempotence and Recovery

The migration is intentionally one-way at the architecture level. Re-running a test or a stage command should either overwrite the same timestamped scratch root or create a new timestamped run root without damaging prior outputs.

If the new runtime fails mid-run, recovery is to fix the failing Phase 2 seam and rerun. Do not restore candidate-first ownership as a fallback path. Keep failure artifacts, patch the label-first path, and continue forward.

If the temporary adapter proves too lossy for a specific downstream stage, capture that gap in this plan and patch only the adapter boundary. Do not bypass authoritative Stage 2 labels by reintroducing importer-owned grouping logic into the runtime.

## Artifacts and Notes

The most important artifacts created by this plan are the authoritative label and grouping outputs. Keep them stable and easy to inspect. A successful run should make it easy to answer three questions from files alone:

1. What label did each segmented line receive before and after Codex correction?
2. What final normalized label did each source block receive after those line-level decisions were reconciled?
3. Which contiguous blocks were grouped into each recipe span, and why did each span start and stop where it did?
4. Which downstream recipe and non-recipe outputs came from those spans?

An example expected artifact set for a successful run is:

    01_blocks.jsonl
    02_labels_deterministic.jsonl
    03_labels_corrected.jsonl
    03b_block_labels.jsonl
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
    ) -> LabelStageResult:

This function must wrap the existing deterministic-plus-Codex line-role machinery, expose both deterministic and final line labels, and normalize one final label per source block for downstream consumers.

In `cookimport/parsing/recipe_span_grouping.py`, define:

    def group_recipe_spans_from_labels(
        block_labels: Sequence[AuthoritativeBlockLabel],
        labeled_lines: Sequence[AuthoritativeLabeledLine],
    ) -> tuple[list[RecipeSpan], list[AuthoritativeBlockLabel]]:

This function must be pure, deterministic, and LLM-free. Its owned output must be block-range recipe spans plus any normalized block-label adjustments needed for downstream ownership.

In `cookimport/parsing/label_first_conversion.py`, define if still needed:

    def build_conversion_result_from_label_spans(
        *,
        source_file: Path,
        importer_name: str,
        labeled_lines: Sequence[AuthoritativeLabeledLine],
        block_labels: Sequence[AuthoritativeBlockLabel],
        recipe_spans: Sequence[RecipeSpan],
        phase1_artifacts: Any,
    ) -> LabelFirstCompatibilityResult:

This function is the only place in Phase 2 allowed to translate label-first ownership back into the legacy `ConversionResult` shape, and it exists only as a temporary internal seam.

In `cookimport/cli.py` and `cookimport/labelstudio/ingest.py`, route one runtime per run: the new label-first runtime. Do not preserve a parallel candidate-first branch in those entrypoints. If a metadata field describing pipeline architecture is useful, make it descriptive only, not a switch.

Plan update note: 2026-03-15_22.20.45 / Codex. Initial draft created from `docs/reports/Refactor.md` Phase 2, with the explicit assumption that Phase 1 observability has already been implemented to spec. The note exists so future revisions can explain how and why this plan changes over time.

Plan update note: 2026-03-15_22.30.53 / Codex. Revised to narrow the Phase 1 dependency to shared observability/reporting, not a fully built Stage 1 evidence model. The plan now makes Phase 2 explicitly responsible for introducing any missing segmented-line artifact and for registering `label_det`, `label_llm_correct`, and `group_recipe_spans` through the shared stage-observability contract.

Plan update note: 2026-03-15_22.42.10 / Codex. Revised to align Phase 2's data contract with the surrounding phase plans. The plan now treats segmented lines as Stage 2 detail, but requires Phase 2 to normalize one authoritative block-label view and block-range `RecipeSpan` view before handing off to Phases 3 and 4.

Plan update note: 2026-03-15_22.52.33 / Codex. Revised to make the Phase 2 handoff bundle explicit as the shared dependency for later phases. Reason: Phase 3 and Phase 4 now both depend on normalized `block_labels` plus `recipe_spans`, and this plan should say plainly that they consume that bundle rather than rediscover authority from atomic rows or legacy candidates.

Plan update note: 2026-03-15_23.00.00 / Codex. Revised stale cross-doc references from `docs/plans/Refactor.md` to `docs/reports/Refactor.md`. Reason: the phase-plan series should point at the real source document consistently.

Plan update note: 2026-03-15_23.00.00 / Codex. Revised the plan to make the migration philosophy explicit: this phase is a one-way cutover, not a conservative dual-backbone rollout. Reason: the desired refactor strategy is to burn down candidate-first ownership rather than preserve it behind toggles or long-lived compatibility paths.
