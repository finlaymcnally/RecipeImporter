---
summary: "ExecPlan for extracting one shared source-job planning seam used by stage and Label Studio flows."
read_when:
  - "When removing duplicated split-job planning from cookimport/cli.py and cookimport/labelstudio/ingest.py."
  - "When making PDF and EPUB split planning a single authoritative module."
---

# Extract a shared source-job planning seam for stage and Label Studio

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

RecipeImport currently plans split jobs in two different places. Stage planning lives in [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py) through `JobSpec` and `_plan_jobs(...)`. Label Studio planning lives in [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py) through `_plan_parallel_convert_jobs(...)`. Both make nearly the same decisions about PDF page splits, EPUB spine splits, markitdown exceptions, and worker-count behavior, but they expose different shapes and therefore can drift silently.

After this change, both stage and Label Studio flows should consume one shared planning module under `cookimport/staging/`. The visible proof is that the same input files and split settings produce the same split decisions regardless of which top-level flow calls the planner, and narrow planner tests plus CLI/Label Studio domain tests still pass.

This plan is standalone. It does not require a parent ExecPlan. It replaces the planning portion of the earlier umbrella refactor with one self-contained implementation document.

## Progress

- [x] (2026-03-22 16:57 EDT) Re-ran `bin/docs-list` and read `docs/PLANS.md`, `docs/01-architecture/01-architecture_README.md`, `docs/02-cli/02-cli_README.md`, `docs/12-testing/12-testing_README.md`, and `docs/reports/ai-readiness-improvement-report.md`.
- [x] (2026-03-22 16:58 EDT) Inspected the current duplicated planning seams in [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py), [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py), and [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py).
- [x] (2026-03-22 17:00 EDT) Authored this standalone planning-seam ExecPlan in `docs/plans/`.
- [x] (2026-03-22 17:30 EDT) Tightened the module contract after re-checking live callers and conventions, including the stale dual-planner guidance in `cookimport/config/CONVENTIONS.md`.
- [ ] Create `cookimport/staging/job_planning.py` with the authoritative `JobSpec` and shared planner helpers.
- [ ] Migrate stage planning to the shared module.
- [ ] Migrate Label Studio import and benchmark planning to the shared module.
- [ ] Re-home or re-export the effective-worker helper so it no longer behaves like CLI-specific logic.
- [ ] Add shared planner tests and update architecture docs.

## Surprises & Discoveries

- Observation: the duplicated logic is close enough that a shared module is clearly justified.
  Evidence: both `_plan_jobs(...)` in [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py) and `_plan_parallel_convert_jobs(...)` in [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py) inspect PDF page counts and EPUB spine counts, apply split-worker thresholds, respect the markitdown EPUB exception, and create one-or-many job records from that logic.

- Observation: the strongest natural home is under `cookimport/staging/`, not under the CLI or Label Studio packages.
  Evidence: shared stage execution already lives in [cookimport/staging/import_session.py](/home/mcnal/projects/recipeimport/cookimport/staging/import_session.py), and the architecture docs already describe stage session code as the strongest runtime seam shared by multiple top-level flows.

- Observation: `compute_effective_workers(...)` is already conceptually part of planning, even though it currently lives in the config module.
  Evidence: [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) computes effective workers from `workers`, `epub_split_workers`, source file types, and EPUB extractor choice, which is a planning concern rather than a persistence concern.

- Observation: the repo’s written conventions currently encode the duplication this plan is supposed to remove.
  Evidence: [cookimport/config/CONVENTIONS.md](/home/mcnal/projects/recipeimport/cookimport/config/CONVENTIONS.md) still tells contributors to update both planners and `compute_effective_workers(...)` together, so the migration is not complete until that guidance is replaced.

## Decision Log

- Decision: make `cookimport/staging/job_planning.py` the authoritative home of split-job planning.
  Rationale: both stage and Label Studio flows need the same semantics, and `staging` already owns the strongest shared runtime seams for these flows.
  Date/Author: 2026-03-22 / Codex

- Decision: keep `JobSpec` as the primary low-level planning model unless implementation proves it materially confusing.
  Rationale: the existing name is already in use and conveys the right level of abstraction for split job records.
  Date/Author: 2026-03-22 / Codex

- Decision: allow temporary adapters in legacy callers during migration.
  Rationale: the current stage and Label Studio code expect slightly different shapes, so a short adapter period is safer than combining semantic unification with broad caller rewrites in one step.
  Date/Author: 2026-03-22 / Codex

- Decision: move or re-export effective-worker computation alongside the shared planner.
  Rationale: worker-count resolution is part of how the planner interprets source sets and split settings, not just a property of stored config.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

No code has changed yet. The current result is a self-contained execution plan for one concrete architecture goal: one planning truth for stage and Label Studio split jobs.

The important lesson from planning is that this seam is a high-value, low-drama extraction. It gives a real AI-readiness win because it turns “remember to update both planners” into “there is only one planner.”

## Context and Orientation

This repository supports split processing for large PDFs and EPUBs. A “split job” means one bounded unit of source conversion work, such as a PDF page range or an EPUB spine-item range. Stage runs use split jobs for processed output generation. Label Studio import and benchmark flows use similar split logic to keep their processed predictions and global block coordinates aligned. In both cases the split plan determines how much work runs in parallel and how part results are merged later.

The current stage planning code lives in [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py). It defines `JobSpec`, `_resolve_pdf_page_count(...)`, `_resolve_epub_spine_count(...)`, and `_plan_jobs(...)`. That code uses `plan_pdf_page_ranges(...)` and `plan_job_ranges(...)` to build page-range or spine-range jobs when worker settings justify splitting. If splitting is not warranted, it emits a single unsplit `JobSpec`.

The current Label Studio planning code lives in [cookimport/labelstudio/ingest.py](/home/mcnal/projects/recipeimport/cookimport/labelstudio/ingest.py). It defines `_plan_parallel_convert_jobs(...)` and emits a list of dictionaries shaped like `{"job_index": ..., "start_page": ..., "end_page": ..., "start_spine": ..., "end_spine": ...}`. The logic is semantically parallel to the stage planner, but because it is a separate function it can drift.

The current worker-resolution helper lives in [cookimport/config/run_settings.py](/home/mcnal/projects/recipeimport/cookimport/config/run_settings.py) as `compute_effective_workers(...)`. It decides whether all-EPUB inputs with non-markitdown extractors should honor `epub_split_workers` over the base `workers` count. Although that function sits in the config module now, it is effectively planning logic because it interprets the planned source set.

The new target module is:

- `cookimport/staging/job_planning.py`

The target interface is:

    @dataclass(frozen=True)
    class JobSpec:
        file_path: Path
        job_index: int
        job_count: int
        start_page: int | None = None
        end_page: int | None = None
        start_spine: int | None = None
        end_spine: int | None = None

        @property
        def is_split(self) -> bool: ...

        @property
        def split_kind(self) -> str | None: ...

        @property
        def display_name(self) -> str: ...

    def resolve_pdf_page_count(path: Path) -> int | None: ...
    def resolve_epub_spine_count(path: Path) -> int | None: ...
    def plan_source_jobs(...) -> list[JobSpec]: ...
    def plan_source_job(...) -> list[JobSpec]: ...
    def compute_effective_workers_for_sources(...) -> int: ...

Callers may temporarily adapt `JobSpec` into legacy dictionaries, but the branching logic must live only here.

`plan_source_job(...)` is the single-file convenience wrapper for the current Label Studio calling pattern. It should delegate to `plan_source_jobs(...)` rather than recreate any branching logic.

## Milestones

### Milestone 1: Create the shared planning module and move the core planning model

At the end of this milestone, `cookimport/staging/job_planning.py` will exist and own `JobSpec`, page/spine-count helpers, and the authoritative shared planning function. Legacy helpers may still exist as wrappers, but they should delegate to the new module.

Acceptance is that the shared module exists and can plan split and unsplit jobs for PDFs and EPUBs without changing behavior.

### Milestone 2: Migrate stage callers to the shared module

At the end of this milestone, the stage path in `cookimport/cli.py` will no longer own the real planning logic. It may still import `JobSpec` or wrapper helpers, but the logic itself must come from `cookimport/staging/job_planning.py`.

Acceptance is that stage behavior is unchanged and stage tests still pass.

### Milestone 3: Migrate Label Studio callers to the shared module

At the end of this milestone, Label Studio import and benchmark paths will call the shared planner and only adapt its result shape if necessary. `_plan_parallel_convert_jobs(...)` should be deleted or reduced to a trivial compatibility wrapper.

Acceptance is that Label Studio tests still pass and planner behavior matches stage behavior for the same inputs.

### Milestone 4: Unify effective-worker resolution with planning

At the end of this milestone, the effective-worker helper will either live in the shared planning module or be clearly re-exported from there as the authoritative owner. Callers should no longer have to infer that a planning rule is hidden in the config file.

Acceptance is that worker-resolution behavior remains unchanged but is easier to find and test.

### Milestone 5: Add tests and docs for the boundary

At the end of this milestone, there will be narrow tests proving that stage and Label Studio flows share planning truth, and docs will describe `cookimport/staging/job_planning.py` as the owner of split-job planning. The stale conventions note that mentions “update both planners together” must be removed or rewritten as part of this milestone.

Acceptance is passing tests plus updated architecture docs.

## Plan of Work

Start by creating `cookimport/staging/job_planning.py` and moving the low-level shared model there. Bring over `JobSpec`, `display_name` logic, page-count helpers, spine-count helpers, and the split planning logic. Keep the planner focused on deciding jobs, not on executing them or merging their results.

Once the module exists, change the stage path first. Replace direct use of `_plan_jobs(...)` with the new `plan_source_jobs(...)` function. Keep a small compatibility wrapper in `cookimport/cli.py` only if that helps stage migration happen without touching too much call-site code in one change.

Then change the Label Studio path. The easiest safe first step is to call `plan_source_job(...)` or `plan_source_jobs(...)` and convert each `JobSpec` into the current dictionary shape the caller expects. That preserves behavior while still deleting duplicate branching logic. Once tests pass, decide whether the caller should continue adapting to dictionaries or migrate further toward `JobSpec`.

Finally, address `compute_effective_workers(...)`. Either move it outright into `job_planning.py` or keep a re-export shim in `run_settings.py` while callers migrate. The important rule is discoverability: the planning contract should be readable in one place.

Add tests as soon as the new module exists. The best pattern is to add shared planner tests that exercise PDFs, EPUBs, markitdown EPUBs, unsplit single-job cases, and all-EPUB worker-resolution cases. Then add or update stage and Label Studio tests that prove both use the shared planner. Finish by updating both architecture docs and [cookimport/config/CONVENTIONS.md](/home/mcnal/projects/recipeimport/cookimport/config/CONVENTIONS.md) so contributors are no longer told to maintain duplicated planners.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Inspect the current planner seams:

    rg -n "class JobSpec|def _plan_jobs|def _resolve_pdf_page_count|def _resolve_epub_spine_count" cookimport/cli.py

    rg -n "def _plan_parallel_convert_jobs|def _job_sort_key|compute_effective_workers" \
      cookimport/labelstudio/ingest.py cookimport/config/run_settings.py

    sed -n '22640,22820p' cookimport/cli.py
    sed -n '1291,1388p' cookimport/labelstudio/ingest.py
    sed -n '1776,1810p' cookimport/config/run_settings.py

Create the new module with `apply_patch`:

    cookimport/staging/job_planning.py

Migration order:

1. Move `JobSpec` and shared helpers into the new module.
2. Update stage code to import and use them.
3. Update Label Studio code to import and use them.
4. Add planner tests.
5. Update docs and conventions.

Prepare the environment if needed:

    . .venv/bin/activate
    pip install -e .[dev]

Use narrow diagnostic loops first:

    . .venv/bin/activate
    pytest tests/cli -k "stage and split"

    . .venv/bin/activate
    pytest tests/labelstudio -k "planner or split or benchmark or ingest_parallel"

Then run broader wrappers:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain cli

    . .venv/bin/activate
    ./scripts/test-suite.sh domain labelstudio

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

## Validation and Acceptance

Acceptance is that split planning becomes single-sourced without changing behavior.

The first acceptance criterion is semantic equivalence. For the same inputs, stage and Label Studio must produce the same split versus unsplit decisions, the same page or spine ranges, and the same treatment of markitdown EPUBs.

The second acceptance criterion is discoverability. A contributor looking for split planning should be able to open `cookimport/staging/job_planning.py` and find the authoritative logic there instead of tracing parallel branches across CLI and Label Studio code.

The third acceptance criterion is local proof. Narrow planner-related test slices must pass, followed by `./scripts/test-suite.sh domain cli`, `./scripts/test-suite.sh domain labelstudio`, and then `./scripts/test-suite.sh fast`.

The fourth acceptance criterion is documentation. The architecture docs and [cookimport/config/CONVENTIONS.md](/home/mcnal/projects/recipeimport/cookimport/config/CONVENTIONS.md) must describe the new shared planning seam clearly enough that future work no longer relies on a conventions note saying “update both planners together.”

## Idempotence and Recovery

This refactor is safe to perform incrementally. The easiest rollback path is to keep wrappers in the old modules that delegate to the new shared planner while caller migrations settle. Do not restore a second real planner just because one caller is temporarily awkward to migrate.

If stage and Label Studio behavior diverge during migration, write a test that captures the divergence before deciding which behavior is correct. The point of this refactor is to make such disagreements explicit and fixable.

## Artifacts and Notes

Keep short evidence snippets here as work proceeds. Examples:

    rg -n "plan_source_jobs|compute_effective_workers_for_sources" cookimport
    # expected: both stage and Label Studio callers now use the shared planner

    ./scripts/test-suite.sh domain cli
    ./scripts/test-suite.sh domain labelstudio
    # expected: both domains still pass after planner extraction

    rg -n "update both planners together" cookimport/config/CONVENTIONS.md
    # expected: no stale dual-planner rule remains

## Interfaces and Dependencies

The authoritative interface is:

    @dataclass(frozen=True)
    class JobSpec:
        file_path: Path
        job_index: int
        job_count: int
        start_page: int | None = None
        end_page: int | None = None
        start_spine: int | None = None
        end_spine: int | None = None

    def plan_source_jobs(
        files: Sequence[Path],
        *,
        pdf_pages_per_job: int,
        epub_spine_items_per_job: int,
        pdf_split_workers: int,
        epub_split_workers: int,
        epub_extractor: str = "unstructured",
        epub_extractor_by_file: Mapping[Path, str] | None = None,
    ) -> list[JobSpec]: ...

    def plan_source_job(
        file_path: Path,
        *,
        pdf_pages_per_job: int,
        epub_spine_items_per_job: int,
        pdf_split_workers: int,
        epub_split_workers: int,
        epub_extractor: str = "unstructured",
    ) -> list[JobSpec]: ...

    def compute_effective_workers_for_sources(...) -> int: ...

`plan_source_jobs(...)` should not accept unused arguments merely to mirror old call sites. If a caller needs worker-resolution logic, it should call `compute_effective_workers_for_sources(...)` first and then pass the resolved split inputs to the planner.

## Revision note

Created on 2026-03-22 as one of three standalone child ExecPlans replacing the earlier umbrella AI-readiness refactor plan. Updated later the same day after re-checking the live duplicated planner seams. The revision adds the missing conventions-doc cleanup, introduces an explicit single-file convenience wrapper for Label Studio callers, and removes the misleading suggestion that `plan_source_jobs(...)` should keep an unused `workers` parameter. Legacy helpers in `cookimport/cli.py`, `cookimport/labelstudio/ingest.py`, and `cookimport/config/run_settings.py` may remain as temporary re-export wrappers only while migration is in progress.
