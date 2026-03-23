---
summary: "ExecPlan for shrinking cookimport/labelstudio/ingest.py and the shared stage-session coordinator into owned subflows while preserving the public Label Studio import and benchmark artifact-generation surface."
read_when:
  - "When reducing cookimport/labelstudio/ingest.py coordination breadth without changing labelstudio-import or benchmark artifact generation behavior."
  - "When extracting Label Studio ingest normalization, artifact generation, split merge, cache, or upload responsibilities into dedicated modules."
  - "When decomposing cookimport/staging/import_session.py so stage and Label Studio share a smaller stage-session boundary instead of one broad coordinator."
---

# Shrink `cookimport/labelstudio/ingest.py` and the shared stage session into owned subflows

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

Label Studio import and benchmark artifact generation are important operator-facing flows, but their implementation currently bottlenecks through one broad file: [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py). That file mixes option normalization, split-cache logic, split planning and merge helpers, run-artifact writing, prelabel adaptation, benchmark prediction generation, and online upload behavior. A contributor trying to change one narrow seam such as prelabel upload fallback or split-cache locking often has to read thousands of lines of unrelated logic.

There is a second coordinator problem sitting directly underneath that file: [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py). Label Studio and stage already share it as the central stage-session seam, but it still concentrates label-first authority building, optional recipe Codex, Stage 7 non-recipe routing, optional knowledge review, chunk/table regeneration, report normalization, and most output writing in one function. If `ingest.py` is decomposed without also shrinking `import_session.py`, a large fraction of the cognitive load simply moves one layer down into the shared runtime seam.

After this change, `run_labelstudio_import(...)` and `generate_pred_run_artifacts(...)` should still behave the same for operators and tests, but the implementation should be organized into smaller owned subflows under a dedicated package. The shared stage-session seam should also stay public and stable while becoming internally decomposed into owned subflows under `cookimport/staging/`. The visible proof is that Label Studio tests still pass while a contributor can change normalization, cache behavior, split merge, artifact writing, stage authority building, non-recipe review wiring, or upload logic from one focused module instead of one giant coordinator.

This plan is self-contained. It does not require a parent ExecPlan, and it now assumes the shared planner dependency has already landed in [cookimport/staging/job_planning.py](/home/mcnal/projects/recipeimport/cookimport/staging/job_planning.py). It also assumes the stable public stage-session entrypoint remains `execute_stage_import_session_from_result(...)` even while the implementation beneath it is split into smaller internal modules.

## Progress

- [x] (2026-03-22 18:00 EDT) Re-ran `bin/docs-list` and read `docs/PLANS.md`, `docs/reports/AI-codebase.md`, `docs/reports/ai-readiness-improvement-report.md`, `docs/06-label-studio/06-label-studio_README.md`, `docs/01-architecture/01-architecture_README.md`, and `docs/12-testing/12-testing_README.md`.
- [x] (2026-03-22 18:06 EDT) Audited [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py), including normalization helpers, split-cache helpers, split planning and merge logic, prediction-artifact generation, and Label Studio upload behavior.
- [x] (2026-03-22 18:06 EDT) Re-audited [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py) as the shared runtime coordinator that both stage and Label Studio ultimately depend on.
- [x] (2026-03-22 18:08 EDT) Authored this standalone Label Studio ingest decomposition ExecPlan in `docs/plans/`.
- [x] (2026-03-22 19:05 EDT) Reworked the plan into a burn-the-boats split: the final state deletes moved helper implementations from `ingest.py` and updates imports instead of preserving a broad facade.
- [x] (2026-03-23 17:16 EDT) Re-audited the live tree and confirmed the shared source-job planning dependency has already landed: [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py) now imports `JobSpec` and `plan_source_job(...)` from [cookimport/staging/job_planning.py](/home/mcnal/projects/recipeimport/cookimport/staging/job_planning.py) instead of owning duplicate planner bodies.
- [ ] Create a `cookimport/labelstudio/ingest_flows/` package with one module per major responsibility cluster.
- [ ] Move normalization and split-cache logic out of `ingest.py`.
- [ ] Move split merge and artifact-writing helpers out of `ingest.py`.
- [ ] Create a `cookimport/staging/import_session_flows/` package with one module per major stage-session responsibility cluster.
- [ ] Move label-first authority building, Stage 7 non-recipe session wiring, and output-writing coordination out of `import_session.py`.
- [ ] Keep `execute_stage_import_session_from_result(...)` as the stable public seam while deleting the moved implementation blocks from `import_session.py`.
- [ ] Move offline prediction-artifact generation into an owned module.
- [ ] Move online upload/project-resolution behavior into an owned module.
- [ ] Cut `ingest.py` down to the smallest product-facing entrypoint surface and delete old helper exports and compatibility names.
- [ ] Add or update Label Studio and staging docs and tests for the new ownership map.

## Surprises & Discoveries

- Observation: `ingest.py` is really two major public flows plus several support subsystems flattened into one file.
  Evidence: the file owns both `generate_pred_run_artifacts(...)` and `run_labelstudio_import(...)`, along with their supporting normalization, split-cache, merge, manifest, artifact, and upload helpers.

- Observation: the file already contains clean support seams that do not need a redesign to become modules.
  Evidence: normalization helpers cluster together, split-cache helpers cluster together, offset/merge helpers cluster together, and online upload logic is mostly concentrated under `run_labelstudio_import(...)`.

- Observation: the shared source-job planning seam is already an external dependency of this plan in the live tree.
  Evidence: [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py) now imports `JobSpec` and `plan_source_job(...)` from [cookimport/staging/job_planning.py](/home/mcnal/projects/recipeimport/cookimport/staging/job_planning.py), so this decomposition no longer needs to move or rewrite planner logic.

- Observation: decomposing `ingest.py` alone would leave too much of the actual runtime story concentrated in `import_session.py`.
  Evidence: [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py) currently owns label-first authority building, optional recipe Codex application, Stage 7 non-recipe routing, optional knowledge review, chunk and table regeneration, report rebuilding, and most staged output writing in one coordinator.

- Observation: `import_session.py` is already the shared seam between stage and Label Studio, so it is the right place to preserve one stable public interface while shrinking implementation breadth behind it.
  Evidence: the architecture docs already describe [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py) as the main shared runtime seam used by multiple top-level flows.

- Observation: this refactor is highly aligned with the AI-friendly-codebase goal because Label Studio behavior spans many visible capabilities.
  Evidence: [docs/reports/AI-codebase.md](/home/mcnal/projects/recipeimport/docs/reports/AI-codebase.md) recommends deep modules with simple explicit interfaces, while the current file forces a newcomer to read cache, merge, artifact, and upload code together.

## Decision Log

- Decision: keep `cookimport.labelstudio.ingest.generate_pred_run_artifacts` and `cookimport.labelstudio.ingest.run_labelstudio_import` as stable public import paths during migration.
  Rationale: tests and CLI call sites already use these names; implementation ownership should change without forcing broad import churn.
  Date/Author: 2026-03-22 / Codex

- Decision: create a dedicated internal package `cookimport/labelstudio/ingest_flows/`.
  Rationale: Label Studio ingest has enough internal structure to deserve a visible subsystem boundary rather than a few extra sibling files.
  Date/Author: 2026-03-22 / Codex

- Decision: treat shared source-job planning as an external dependency of this plan once that dedicated planner seam exists.
  Rationale: the AI-friendly goal is single authority, so this decomposition should consume the shared planner plan rather than re-own it.
  Date/Author: 2026-03-22 / Codex

- Decision: preserve the current `job_planning.py` dependency and remove any wording in this plan that implies `ingest.py` still owns planner duplication.
  Rationale: the shared planner refactor has already landed, so this plan should focus only on the still-broad normalization/cache/merge/upload/session responsibilities.
  Date/Author: 2026-03-23 / Codex

- Decision: separate offline artifact generation from online Label Studio upload behavior.
  Rationale: these are distinct product concerns with different dependencies and validation loops, and they should not require joint understanding for routine changes.
  Date/Author: 2026-03-22 / Codex

- Decision: keep `cookimport.staging.import_session.execute_stage_import_session_from_result(...)` as the stable shared entrypoint while decomposing its internals into owned subflows.
  Rationale: stage and Label Studio already share this seam, so the goal is to preserve a narrow public interface and move the current internal coordination breadth behind smaller modules rather than to invent a second parallel session API.
  Date/Author: 2026-03-22 / Codex

- Decision: treat `ingest.py` and `import_session.py` as one architectural decomposition problem for this refactor.
  Rationale: they sit on the same call path. Shrinking only the top-level Label Studio coordinator would still leave the shared runtime coordinator too broad for AI-friendly local change.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

This plan is still largely outstanding, but one important dependency is now complete: shared source-job planning has already moved out into [cookimport/staging/job_planning.py](/home/mcnal/projects/recipeimport/cookimport/staging/job_planning.py). The remaining work is the decomposition of the still-broad Label Studio ingest and shared stage-session coordinators.

The main planning lesson is that both files already contain coherent support clusters. The work is to make those clusters first-class owners, not to invent a new runtime model.

## Context and Orientation

The Label Studio ingest/eval/import surface is documented in [docs/06-label-studio/06-label-studio_README.md](/home/mcnal/projects/recipeimport/docs/06-label-studio/06-label-studio_README.md). In this repo, “ingest” means the runtime path that can generate prediction-run artifacts offline and, when explicitly allowed, upload tasks to Label Studio online. The public implementation home today is [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py).

The current file mixes these concerns:

- normalization and validation helpers for EPUB, parser, Codex, and prelabel options
- single-book split-cache helpers and file locking
- shared-planner calls, per-job conversion, offset rebasing, and result merging
- manifest and processed-artifact writing
- authoritative line-role and non-recipe projection helpers
- offline prediction-artifact generation in `generate_pred_run_artifacts(...)`
- online project lookup, resume semantics, and task upload behavior in `run_labelstudio_import(...)`

For AI-friendly change, that is too much breadth. A contributor trying to change split-cache locking should not need to scan Label Studio project-creation logic. Someone changing prelabel upload fallback should not need to read all merge-offset code first.

The shared stage-session surface is documented in [docs/01-architecture/01-architecture_README.md](/home/mcnal/projects/recipeimport/docs/01-architecture/01-architecture_README.md) and currently lives in [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py). In this repo, “stage session” means the shared runtime pass that takes a `ConversionResult`, builds label-first authority, optionally runs recipe and knowledge Codex stages, rebuilds non-recipe authority, regenerates chunks and tables, normalizes the final report, and writes the staged artifacts. It is already the right public seam, but it is too broad internally.

The current stage-session file mixes these concerns:

- label-first archive reconstruction and authoritative label artifacts
- recipe-span regrouping and conversion-result rebuilding
- optional recipe Codex application and override handoff
- Stage 7 non-recipe routing and optional knowledge refinement
- chunk and table regeneration
- report normalization and final `llm_report` assembly
- output-writing progress accounting and orchestration across many writer functions

For AI-friendly change, that is too much hidden pipeline truth in one place. A contributor trying to change non-recipe authority should not have to scan recipe override plumbing. Someone changing output-writing order should not need to reason through the full label-first and knowledge-review stack.

The target package layout for this plan is:

- `cookimport/labelstudio/ingest_flows/__init__.py`
- `cookimport/labelstudio/ingest_flows/normalize.py`
- `cookimport/labelstudio/ingest_flows/split_cache.py`
- `cookimport/labelstudio/ingest_flows/split_merge.py`
- `cookimport/labelstudio/ingest_flows/artifacts.py`
- `cookimport/labelstudio/ingest_flows/prediction_run.py`
- `cookimport/labelstudio/ingest_flows/upload.py`
- `cookimport/staging/import_session_flows/__init__.py`
- `cookimport/staging/import_session_flows/authority.py`
- `cookimport/staging/import_session_flows/recipe_stage.py`
- `cookimport/staging/import_session_flows/nonrecipe_stage.py`
- `cookimport/staging/import_session_flows/output_stage.py`
- `cookimport/staging/import_session_flows/reporting.py`

The intended ownership boundaries are:

- `normalize.py`: option normalization and small validation helpers
- `split_cache.py`: single-book split-cache entry files, lock files, wait/retry logic
- `split_merge.py`: split worker job adaptation, offset rebasing, result merge logic, and the existing shared planner dependency
- `artifacts.py`: manifest/report/artifact write helpers and authority-projection helpers
- `prediction_run.py`: the owned implementation of `generate_pred_run_artifacts(...)`
- `upload.py`: the owned implementation of `run_labelstudio_import(...)`, project resolution, resume behavior, and upload fallback logic
- `authority.py`: label-first archive handling, authoritative label artifacts, recipe-span regrouping, and authority-mismatch diagnostics
- `recipe_stage.py`: optional recipe Codex application plus recipe override handoff back into the stage session
- `nonrecipe_stage.py`: Stage 7 seed routing, optional knowledge review application, and final non-recipe authority projection back into the session state
- `output_stage.py`: chunk/table regeneration plus ordered staged-output writing and progress accounting
- `reporting.py`: final report normalization, `llm_report` assembly, and stable session-result construction

The final product-facing surface may remain in [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py) only for the genuinely public entrypoints `generate_pred_run_artifacts(...)` and `run_labelstudio_import(...)`. Moved helper names and internal support logic should not be re-exported from that file in the completed end state.

The final shared runtime surface should remain in [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py) only for the genuinely public entrypoint `execute_stage_import_session_from_result(...)` plus its small result dataclass and the narrow helper glue required to preserve imports. Moved implementation blocks should not remain there as broad private compatibility helpers in the completed end state.

## Milestones

### Milestone 1: Create the `ingest_flows` package and move normalization/cache helpers

At the end of this milestone, the new package will exist and the least-coupled helpers such as normalization and split-cache logic will live there. The completed milestone state should already remove those helpers from `ingest.py`.

Acceptance is that imports and Label Studio tests still pass and the moved helpers are no longer buried in the giant coordinator file.

### Milestone 2: Extract split merge and artifact-writing helpers

At the end of this milestone, offset rebasing, merge logic, manifest/report writing, and authoritative artifact projection helpers will live in dedicated modules. The split-merge module should consume the existing shared planner in [cookimport/staging/job_planning.py](/home/mcnal/projects/recipeimport/cookimport/staging/job_planning.py) rather than recreating planning logic locally.

Acceptance is that split-run merge behavior, processed artifacts, and manifest/report writes remain stable.

### Milestone 3: Decompose the shared stage-session coordinator behind a stable entrypoint

At the end of this milestone, [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py) will still expose `execute_stage_import_session_from_result(...)`, but the implementation under that function will delegate to owned subflow modules for label-first authority building, optional recipe-stage application, non-recipe authority refinement, output orchestration, and reporting. The old implementation blocks should be deleted from `import_session.py` once the new modules are wired in.

Acceptance is that stage and Label Studio still share the same public session seam while a contributor can now change authority building, knowledge refinement wiring, or output coordination from one smaller owner module.

### Milestone 4: Move offline prediction-artifact generation into `prediction_run.py`

At the end of this milestone, the full implementation of `generate_pred_run_artifacts(...)` will live in `prediction_run.py`, and the old helper bodies supporting it should be deleted from `ingest.py`.

Acceptance is that benchmark/import offline artifact generation still works and relevant Label Studio tests still pass.

### Milestone 5: Move online upload/project behavior into `upload.py`

At the end of this milestone, project-title resolution, resume semantics, upload batching, inline-annotation fallback, and post-import annotation repair behavior will live in `upload.py`.

Acceptance is that `run_labelstudio_import(...)` still behaves the same for overwrite, resume, project-scope mismatch, and upload fallback scenarios.

### Milestone 6: Tighten docs and tests around the new boundaries

At the end of this milestone, Label Studio and staging docs and tests will teach and protect the new ownership map. Contributors should know where offline artifact generation, upload behavior, cache logic, split merge, shared authority building, non-recipe review wiring, and staged-output coordination each live.

Acceptance is passing Label Studio, staging, and CLI validation plus docs that point readers to `ingest_flows/` and `import_session_flows/` rather than only the old giant coordinator files.

## Plan of Work

Start with the lowest-coupled helpers: normalization and split-cache. These create the package structure and reduce noise in the public file without changing the main orchestration path much. Delete each moved helper cluster from `ingest.py` as soon as its new owning module is wired in.

Next, move split merge and artifact writing. Those helpers already form clear support layers and should not stay interwoven with online upload behavior. The shared planner dependency is already satisfied, so this step should preserve `job_planning.py` as the planner owner and only move the Label Studio-specific job execution, rebasing, and merge code.

Then split the shared stage session. Start by creating `cookimport/staging/import_session_flows/` and move the lowest-ambiguity seams first: label-first authority building and artifact writing, then optional recipe-stage application, then Stage 7 plus optional knowledge-review coordination, then output-writing orchestration and report assembly. Keep `execute_stage_import_session_from_result(...)` as the single public seam while deleting the moved implementation blocks from `import_session.py` once the new modules are wired in. The goal is not to create a second public session API. The goal is to preserve one small shared session entrypoint and make the internal pipeline stages progressive and inspectable.

After that, move the full implementation of `generate_pred_run_artifacts(...)` into `prediction_run.py`. This is the main offline artifact-generation path and should become its own deep module because it is a full workflow in its own right.

Finally, move `run_labelstudio_import(...)` implementation into `upload.py`. That module should own project creation, overwrite/resume semantics, task upload, prelabel upload-as behavior, and repair fallbacks. Keeping this separate from offline artifact generation is one of the biggest AI-readiness wins in the file.

Throughout the migration, preserve only the stable product-facing and shared-runtime entrypoints and avoid creating a shallow helper web. Each new module should correspond to a coherent user-visible or operator-visible concern, and the old helper bodies in `ingest.py` and `import_session.py` should be removed rather than left behind.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Inspect the current seam map:

    rg -n "^def |^class " cookimport/labelstudio/ingest.py

    sed -n '1620,1765p' cookimport/labelstudio/ingest.py
    sed -n '3505,3820p' cookimport/labelstudio/ingest.py

Create the new package with `apply_patch`:

    cookimport/labelstudio/ingest_flows/__init__.py
    cookimport/labelstudio/ingest_flows/normalize.py
    cookimport/labelstudio/ingest_flows/split_cache.py
    cookimport/labelstudio/ingest_flows/split_merge.py
    cookimport/labelstudio/ingest_flows/artifacts.py
    cookimport/labelstudio/ingest_flows/prediction_run.py
    cookimport/labelstudio/ingest_flows/upload.py
    cookimport/staging/import_session_flows/__init__.py
    cookimport/staging/import_session_flows/authority.py
    cookimport/staging/import_session_flows/recipe_stage.py
    cookimport/staging/import_session_flows/nonrecipe_stage.py
    cookimport/staging/import_session_flows/output_stage.py
    cookimport/staging/import_session_flows/reporting.py

Migration order:

1. Move normalization and cache helpers.
2. Move split-merge and artifact helpers.
3. Move `import_session.py` internals into `import_session_flows/` while keeping `execute_stage_import_session_from_result(...)` stable.
4. Move offline prediction-run implementation.
5. Move online upload implementation.
6. Delete moved helper exports from `ingest.py` and moved implementation blocks from `import_session.py`, leaving only the stable entrypoints that still matter.
7. Update docs and tests.

Prepare the environment if needed:

    . .venv/bin/activate
    pip install -e .[dev]

Use narrow diagnostic loops first:

    . .venv/bin/activate
    pytest tests/labelstudio -k "import or ingest_parallel or benchmark"

    . .venv/bin/activate
    pytest tests/cli -k "labelstudio"

    . .venv/bin/activate
    pytest tests/staging -k "nonrecipe or section_outputs or stage_observability or run_manifest"

Then run broader wrappers:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain labelstudio

    . .venv/bin/activate
    ./scripts/test-suite.sh domain staging

    . .venv/bin/activate
    ./scripts/test-suite.sh domain cli

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

Check public import stability:

    python - <<'PY'
    from cookimport.labelstudio.ingest import generate_pred_run_artifacts, run_labelstudio_import
    print(callable(generate_pred_run_artifacts), callable(run_labelstudio_import))
    PY

## Validation and Acceptance

Acceptance is behavioral first. `generate_pred_run_artifacts(...)` and `run_labelstudio_import(...)` must continue to support the same operator-facing behavior and artifact set.

The shared stage-session contract must also remain stable. `execute_stage_import_session_from_result(...)` must still support the same stage and Label Studio call paths and produce the same staged authority and output artifacts.

The second acceptance criterion is discoverability. A contributor should be able to open one owning module for normalization, cache logic, split merge, artifact writing, offline prediction generation, online upload behavior, label-first authority building, non-recipe refinement, or output coordination without reading the whole giant file.

The third acceptance criterion is regression safety. Label Studio tests, staging tests, and CLI paths that touch import/benchmark flows must still pass, including overwrite/resume behavior, split-run merge behavior, prelabel upload fallback behavior, and the current staged output contracts.

The fourth acceptance criterion is single authority. Once the shared source-job planning plan lands, `ingest_flows/split_merge.py` should consume that shared planner seam rather than preserving duplicate planning logic locally.

The fifth acceptance criterion is documentation. Label Studio and staging docs should explain the new ownership maps so future contributors no longer treat `ingest.py` and `import_session.py` as the only places to start.

The sixth acceptance criterion is deletion. Moved helper implementations and helper exports should be gone from `ingest.py`, and moved implementation blocks should be gone from `import_session.py`; those files should no longer function as broad compatibility layers.

## Idempotence and Recovery

This refactor is safe to do incrementally, but the completed end state must not keep broad helper delegates in `ingest.py` or broad stage-subflow implementations in `import_session.py`. If one workflow extraction becomes awkward, finish that migration or postpone the cutover rather than preserving a dual-home implementation.

If the shared source-job planning plan has not landed yet, do not block the whole decomposition. Move other seams first and leave a clearly marked temporary local planner delegate that can be replaced later.

If upload behavior or resume semantics drift unexpectedly, preserve the old online contract first and only then revisit module ownership. This is a user-facing flow, so behavior stability matters more than achieving a perfectly clean split in one pass.

If stage-output or authority behavior drifts during the `import_session.py` split, preserve the existing public session contract first and only then revisit the subflow boundary. This is a shared runtime seam, so correctness and artifact stability matter more than achieving a perfectly clean split in one pass.

## Artifacts and Notes

Keep short evidence snippets here as work proceeds. Examples:

    rg -n "ingest_flows" cookimport tests
    # expected: Label Studio ingest ownership now lives in the package rather than only the old giant file

    rg -n "import_session_flows" cookimport tests
    # expected: stage-session ownership now lives in the package rather than only the old giant coordinator

    ./scripts/test-suite.sh domain labelstudio
    ./scripts/test-suite.sh domain staging
    # expected: import and benchmark artifact-generation flows still pass

    python - <<'PY'
    from cookimport.labelstudio.ingest import generate_pred_run_artifacts, run_labelstudio_import
    print(callable(generate_pred_run_artifacts), callable(run_labelstudio_import))
    PY
    # expected: stable public import paths still work

## Interfaces and Dependencies

The stable public interface should remain:

    def generate_pred_run_artifacts(...) -> dict[str, Any]: ...
    def run_labelstudio_import(...) -> dict[str, Any]: ...
    def execute_stage_import_session_from_result(...) -> StageImportSessionResult: ...

Internal package interfaces should become:

In `cookimport/labelstudio/ingest_flows/normalize.py`:

    def normalize_epub_extractor(...) -> str: ...
    def normalize_llm_recipe_pipeline(...) -> str: ...
    def normalize_codex_farm_failure_mode(...) -> str: ...

In `cookimport/labelstudio/ingest_flows/split_cache.py`:

    def load_single_book_split_cache_entry(...) -> dict[str, Any] | None: ...
    def write_single_book_split_cache_entry(...) -> None: ...
    def acquire_single_book_split_cache_lock(...) -> bool: ...

In `cookimport/labelstudio/ingest_flows/split_merge.py`:

    def plan_parallel_convert_jobs(...) -> list[dict[str, int | None]]: ...
    def merge_parallel_results(...) -> ConversionResult: ...

In `cookimport/labelstudio/ingest_flows/artifacts.py`:

    def write_manifest_best_effort(...) -> None: ...
    def write_processed_outputs(...) -> None: ...
    def write_authoritative_line_role_artifacts(...) -> None: ...

In `cookimport/labelstudio/ingest_flows/prediction_run.py`:

    def generate_pred_run_artifacts(...) -> dict[str, Any]: ...

In `cookimport/labelstudio/ingest_flows/upload.py`:

    def run_labelstudio_import(...) -> dict[str, Any]: ...

In `cookimport/staging/import_session_flows/authority.py`:

    def build_label_first_session_state(...) -> LabelFirstStageResult: ...
    def write_label_first_artifacts(...) -> dict[str, Path]: ...

In `cookimport/staging/import_session_flows/recipe_stage.py`:

    def apply_recipe_stage(...) -> tuple[ConversionResult, dict[str, Any], dict[str, dict[str, Any]] | None, dict[str, dict[str, Any]] | None]: ...

In `cookimport/staging/import_session_flows/nonrecipe_stage.py`:

    def build_nonrecipe_session_state(...) -> NonRecipeStageResult: ...
    def apply_knowledge_stage(...) -> tuple[NonRecipeStageResult, dict[str, Any] | None, Any | None]: ...

In `cookimport/staging/import_session_flows/output_stage.py`:

    def regenerate_nonrecipe_derivatives(...) -> tuple[list[Any], list[Any]]: ...
    def write_stage_outputs(...) -> Path: ...

In `cookimport/staging/import_session_flows/reporting.py`:

    def finalize_stage_report(...) -> tuple[ConversionReport, dict[str, Any]]: ...
    def build_stage_session_result(...) -> StageImportSessionResult: ...

These names are ownership targets, not rigid mandatory final names. What matters is a deep-module split where offline generation, online upload, cache logic, split merge, shared authority building, non-recipe refinement, output coordination, and report/session assembly each have one obvious implementation home.

## Revision note

Created on 2026-03-22 as a follow-on AI-readiness plan after the initial coordinator-splitting plans. Updated later the same day to a burn-the-boats posture. Updated on 2026-03-23 after re-auditing the live tree so the plan now reflects that shared source-job planning has already moved to `cookimport/staging/job_planning.py` and only the remaining ingest/session decomposition work is still pending.
