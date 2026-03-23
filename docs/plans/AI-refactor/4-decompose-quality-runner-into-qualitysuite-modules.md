---
summary: "ExecPlan for splitting cookimport/bench/quality_runner.py into deep QualitySuite modules while preserving the public bench quality surface."
read_when:
  - "When reducing cookimport/bench/quality_runner.py coordination breadth without changing the public QualitySuite CLI."
  - "When extracting QualitySuite planning, execution, resume, and summary seams into owned modules."
---

# Decompose `cookimport/bench/quality_runner.py` into deep QualitySuite modules

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

QualitySuite is one of the repo’s most important AI-facing benchmark surfaces, but its main implementation file is currently a giant mixed-responsibility coordinator. Today [cookimport/bench/quality_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/quality_runner.py) owns experiment models, environment guardrails, resume/checkpoint files, experiment expansion, executor selection, per-experiment runtime orchestration, reporting, summary formatting, and a worker CLI entrypoint. That means a contributor trying to change one narrow concern such as resume validation or summary rendering often has to open more than three thousand lines of unrelated logic.

After this change, QualitySuite should still behave the same for operators using `cookimport bench quality-run` and related read-side tools, but the code should be organized into a `qualitysuite` package with explicit ownership boundaries for planning, runtime execution, persistence, and summaries. The visible proof is that benchmark commands and existing quality-domain tests still pass while a newcomer can inspect one smaller module to change one concern safely.

This plan is self-contained. It does not require a parent ExecPlan, but it is intentionally sequenced after the already-authored CLI, shared-planning, and run-settings plans because those shrink broader coordination surfaces first.

## Progress

- [x] (2026-03-22 18:00 EDT) Re-ran `bin/docs-list` and re-read `docs/PLANS.md`, `docs/reports/AI-codebase.md`, `docs/reports/ai-readiness-improvement-report.md`, `docs/07-bench/07-bench_README.md`, and `docs/12-testing/12-testing_README.md`.
- [x] (2026-03-22 18:03 EDT) Audited the current QualitySuite file shape in [cookimport/bench/quality_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/quality_runner.py), including experiment models, resume/checkpoint logic, executor/environment logic, experiment planning, per-experiment runtime execution, summary/report formatting, and worker CLI support.
- [x] (2026-03-22 18:08 EDT) Authored this standalone QualitySuite decomposition ExecPlan in `docs/plans/`.
- [x] (2026-03-22 19:05 EDT) Reworked the plan into a burn-the-boats split: the final state deletes old helper imports and internal compatibility re-exports instead of keeping `quality_runner.py` as a broad facade.
- [ ] Create a `cookimport/bench/qualitysuite/` package with one module per major responsibility cluster.
- [ ] Move experiment schema and resolution logic out of `quality_runner.py`.
- [ ] Move environment/executor decision logic and subprocess worker plumbing out of `quality_runner.py`.
- [ ] Move checkpoint/resume persistence and summary/report rendering out of `quality_runner.py`.
- [ ] Cut `quality_runner.py` down to the smallest product-facing entrypoint surface and delete old helper exports and internal compatibility names.
- [ ] Add or update bench-domain tests and docs so the new QualitySuite ownership map is explicit.

## Surprises & Discoveries

- Observation: `quality_runner.py` is not merely large; it is a full subsystem flattened into one file.
  Evidence: the file currently contains Pydantic experiment models, environment guardrails, subprocess worker execution, resume compatibility checks, experiment planning, summary aggregation, report formatting, and a worker CLI parser.

- Observation: the file already contains natural deep-module seams.
  Evidence: function clusters separate cleanly into environment/executor helpers, experiment expansion and resolution, checkpoint persistence, per-experiment runtime execution, and summary/report loading.

- Observation: QualitySuite already has meaningful boundary tests that can lock down a refactor.
  Evidence: the bench and CLI docs name active test anchors, and the repo already contains focused adapter and benchmark tests that can verify the public surface while the implementation moves underneath.

- Observation: this refactor is valuable for AI-readiness even if the public API stays the same.
  Evidence: [docs/reports/AI-codebase.md](/home/mcnal/projects/recipeimport/docs/reports/AI-codebase.md) emphasizes deep modules with small explicit interfaces, and `quality_runner.py` is currently the opposite: a wide surface that forces broad reading.

## Decision Log

- Decision: keep only the truly public QualitySuite entrypoints in `quality_runner.py` and move everything else to the new package with updated imports.
  Rationale: the burn-the-boats end state should not preserve the old file as a compatibility museum. Only real product-facing entrypoints should remain there.
  Date/Author: 2026-03-22 / Codex

- Decision: introduce a new internal package `cookimport/bench/qualitysuite/` rather than creating more sibling giant files under `cookimport/bench/`.
  Rationale: this creates a visible subsystem boundary with progressive disclosure instead of redistributing a giant module into another shallow module web.
  Date/Author: 2026-03-22 / Codex

- Decision: group modules by responsibility cluster, not by tiny helper category.
  Rationale: the point is to create deep modules with simple entrypoints, not to maximize file count.
  Date/Author: 2026-03-22 / Codex

- Decision: move the worker CLI parser and `_main(...)` path into the new package and update any invoking paths rather than preserving broad helper exports from `quality_runner.py`.
  Rationale: subprocess worker behavior is runtime implementation, not a reason to keep the old giant file as a general-purpose import surface.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

No code has changed yet. The current outcome is a concrete decomposition plan for one of the repo’s largest active benchmark coordinators.

The main planning lesson is that `quality_runner.py` already contains strong seams; the work is less about inventing abstractions than about making the existing responsibility clusters visible and separately owned.

## Context and Orientation

QualitySuite is the deterministic quality benchmark surface described in [docs/07-bench/07-bench_README.md](/home/mcnal/projects/recipeimport/docs/07-bench/07-bench_README.md). In this repo, “QualitySuite” means the logic behind `cookimport bench quality-run`, related experiment definitions, resume/checkpoint files, and the summary artifacts that later readers such as the leaderboard consume. The active public runtime entrypoint today is [cookimport/bench/quality_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/quality_runner.py).

The current file mixes several concerns:

- experiment schema models such as `QualityExperiment`, `QualityLever`, and `QualityExperimentResult`
- environment and executor guardrails such as WSL safety checks and process-vs-thread executor choice
- experiment expansion and resolution from experiment files plus base run settings
- per-experiment runtime execution including subprocess worker fallback
- checkpoint, resume, and partial-summary persistence
- run-summary aggregation and markdown/text report formatting
- a worker CLI parser and `_main(...)` entrypoint

For AI-readiness, that is too much breadth in one file. A fresh agent trying to change summary formatting should not need to scan subprocess worker plumbing. A contributor trying to change resume compatibility should not need to read all-method runtime target selection. The goal is progressive disclosure: first open the small product-facing entrypoint surface, then one owning module, then its internals only if needed.

The target package layout for this plan is:

- `cookimport/bench/qualitysuite/__init__.py`
- `cookimport/bench/qualitysuite/models.py`
- `cookimport/bench/qualitysuite/environment.py`
- `cookimport/bench/qualitysuite/planning.py`
- `cookimport/bench/qualitysuite/runtime.py`
- `cookimport/bench/qualitysuite/persistence.py`
- `cookimport/bench/qualitysuite/summary.py`
- `cookimport/bench/qualitysuite/worker_cli.py`

The final product-facing surface may remain in [cookimport/bench/quality_runner.py](/home/mcnal/projects/recipeimport/cookimport/bench/quality_runner.py) only for the genuinely public entrypoints such as `run_quality_suite(...)` and `load_quality_run_summary(...)`. Moved helper names, model names, and runtime internals should not be re-exported from that file in the completed end state.

The intended ownership boundaries are:

- `models.py`: experiment/result models and resolved experiment dataclasses
- `environment.py`: platform guards, load-based caps, executor-mode decisions, live ETA poll defaults
- `planning.py`: experiment-file loading, base-run-settings resolution, patch validation, experiment expansion and target selection
- `runtime.py`: `run_quality_suite(...)`, per-experiment execution, subprocess worker request handling, runtime target loop orchestration
- `persistence.py`: checkpoint files, result snapshots, resume compatibility, JSON helper reads/writes
- `summary.py`: summary payload construction, report formatting, source-group aggregation, line-role artifact summaries, read-side helpers
- `worker_cli.py`: parser construction and `_main(...)`

That layout is intentionally not tiny-granular. Each new module should be deep enough that a contributor can learn one responsibility cluster without bouncing through a web of one-function files.

## Milestones

### Milestone 1: Create the `qualitysuite` package and move the stable models

At the end of this milestone, the repo will contain the new `cookimport/bench/qualitysuite/` package and the experiment/result models will live in `models.py`. `quality_runner.py` may still define runtime logic, but the subsystem will have a visible ownership map and the lowest-risk shared types will no longer be buried in the giant coordinator file.

Acceptance is that imports and tests still pass, and the repo has updated any imports that used old helper/model names from `quality_runner.py` rather than preserving those names indefinitely.

### Milestone 2: Extract planning and environment guardrails

At the end of this milestone, experiment expansion, target selection, base payload resolution, and executor/environment decisions will live in `planning.py` and `environment.py`. `quality_runner.py` should stop being the first place to open for these concerns.

Acceptance is that experiment-resolution behavior, parallelism caps, and executor selection stay unchanged and the relevant bench tests still pass.

### Milestone 3: Extract persistence and summary/report logic

At the end of this milestone, checkpoint files, result snapshots, resume compatibility checks, summary payload builders, and report formatting will live in `persistence.py` and `summary.py`.

Acceptance is that resumed runs, partial-summary writes, and summary/report consumers still behave the same while the ownership of read/write artifact logic becomes obvious.

### Milestone 4: Isolate runtime execution and worker CLI plumbing

At the end of this milestone, runtime orchestration will live in `runtime.py` and worker parser / `_main(...)` logic will live in `worker_cli.py`. `quality_runner.py` will no longer be the implementation home and should expose only the smallest product-facing entrypoints still required by callers.

Acceptance is that `run_quality_suite(...)` still works, subprocess worker execution still works, and the worker CLI path still accepts the same arguments and exits with the same success/failure behavior.

### Milestone 5: Tighten tests and docs around the new boundaries

At the end of this milestone, benchmark docs and tests will teach and protect the new ownership map. Add or update tests that fail narrowly when public QualitySuite imports drift or when the resume/summary/runtime contract changes accidentally.

Acceptance is passing bench-domain validation, passing CLI paths that touch QualitySuite, and docs that point contributors at `cookimport/bench/qualitysuite/` rather than treating `quality_runner.py` as the only mental model.

## Plan of Work

Start by creating `cookimport/bench/qualitysuite/` and moving the least-coupled pieces first. The safest opening move is models plus pure planning helpers, because that creates the subsystem shape without destabilizing runtime orchestration. Update imports as the new modules land; do not preserve broad helper re-exports from `quality_runner.py` in the final state.

Next, extract environment and executor guardrails. Those helpers are an especially good deep-module seam because they are conceptually one policy cluster: how QualitySuite decides whether to use process workers, thread workers, or safety-reduced parallelism on the current host. They should be readable without scanning summary formatting or experiment expansion.

Then extract checkpoint/resume and summary/report logic. Those are already artifact-focused concerns and should become their own modules because they define the persistence contract for QualitySuite runs. A contributor debugging resume compatibility should be able to stay inside `persistence.py` plus a small number of tests.

Finally, move runtime execution and worker CLI logic. This is left until late because it likely has the widest coupling to the existing file and the most moving parts. Finish by deleting the moved helper implementations from `quality_runner.py` and leaving only the product-facing entrypoints that still deserve that import path.

Throughout the migration, prefer decisive cutovers over lingering compatibility layers. The AI-friendly goal is not just “split the file.” It is to create discoverable responsibility boundaries with narrow public entrypoints and strong regression feedback, with the old wide import surface removed.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Inspect the current QualitySuite seam map:

    rg -n "^class |^def " cookimport/bench/quality_runner.py

    sed -n '900,1180p' cookimport/bench/quality_runner.py

Create the new package with `apply_patch`:

    cookimport/bench/qualitysuite/__init__.py
    cookimport/bench/qualitysuite/models.py
    cookimport/bench/qualitysuite/environment.py
    cookimport/bench/qualitysuite/planning.py
    cookimport/bench/qualitysuite/runtime.py
    cookimport/bench/qualitysuite/persistence.py
    cookimport/bench/qualitysuite/summary.py
    cookimport/bench/qualitysuite/worker_cli.py

Migration order:

1. Move models and resolved-experiment types.
2. Move planning helpers and environment/executor helpers.
3. Move persistence and summary/report helpers.
4. Move runtime and worker CLI plumbing.
5. Delete moved helper exports from `quality_runner.py` and leave only the product-facing entrypoints that still matter.
6. Update docs and tests.

Prepare the environment if needed:

    . .venv/bin/activate
    pip install -e .[dev]

Use narrow diagnostic loops first:

    . .venv/bin/activate
    pytest tests/bench -k "quality"

    . .venv/bin/activate
    pytest tests/cli -k "bench or quality"

Then run broader wrappers:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain bench

    . .venv/bin/activate
    ./scripts/test-suite.sh domain cli

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

Check import discoverability after major moves:

    rg -n "from cookimport\\.bench\\.quality_runner import|import cookimport\\.bench\\.quality_runner" cookimport tests

## Validation and Acceptance

Acceptance is behavioral first. `cookimport bench quality-run` and any read-side QualitySuite consumers must continue to work without operator-facing contract changes.

The second acceptance criterion is discoverability. A contributor looking for QualitySuite planning, runtime, persistence, or summary logic should be able to open one owning module inside `cookimport/bench/qualitysuite/` instead of scanning the whole giant file.

The third acceptance criterion is regression safety. Bench-domain and CLI paths that touch QualitySuite must still pass, including resume/checkpoint behavior, summary/report generation, and any worker CLI tests that already exist or are added during the migration.

The fourth acceptance criterion is public-import stability for the true product-facing entrypoints only. `run_quality_suite` and `load_quality_run_summary` may remain stable, but old helper/model import paths from `quality_runner.py` should be removed and callers updated.

The fifth acceptance criterion is documentation. Bench docs should teach the new ownership map so future contributors do not start from the giant old file by default.

The sixth acceptance criterion is deletion. The completed refactor must remove moved helper implementations and helper exports from `quality_runner.py`; the file should no longer function as a broad compatibility surface.

## Idempotence and Recovery

This refactor is safe to do incrementally, but the completed end state must not keep bridging code in `quality_runner.py` beyond the truly public entrypoints. If one runtime path is awkward, finish that migration or postpone the cutover rather than preserving a broad dual-home surface.

If public imports begin to drift, distinguish real public entrypoints from old convenience imports. Preserve the former with tests; update the latter and delete them.

If resume or summary behavior changes unexpectedly, preserve the old artifact shape first and only then refactor the writer/reader ownership. Artifact compatibility matters more than achieving a perfectly “clean” module graph in one pass.

## Artifacts and Notes

Keep short evidence snippets here as work proceeds. Examples:

    rg -n "cookimport\\.bench\\.qualitysuite" cookimport tests
    # expected: QualitySuite ownership now lives in the package rather than only the old giant file

    ./scripts/test-suite.sh domain bench
    # expected: QualitySuite commands and read-side consumers still pass

    python - <<'PY'
    from cookimport.bench.quality_runner import run_quality_suite
    print(callable(run_quality_suite))
    PY
    # expected: stable public import path still works

## Interfaces and Dependencies

The stable public interface should remain:

    def run_quality_suite(...) -> Path: ...
    def load_quality_run_summary(run_dir: Path) -> dict[str, Any]: ...

Internal package interfaces should become:

In `cookimport/bench/qualitysuite/models.py`:

    class QualityExperiment(BaseModel): ...
    class QualityExperimentResult(BaseModel): ...
    @dataclass
    class ResolvedExperiment: ...

In `cookimport/bench/qualitysuite/planning.py`:

    def load_experiment_file(...) -> ...: ...
    def resolve_base_run_settings_payload(...) -> dict[str, Any]: ...
    def expand_experiments(...) -> list[...]: ...
    def resolve_experiments(...) -> list[ResolvedExperiment]: ...

In `cookimport/bench/qualitysuite/environment.py`:

    def resolve_experiment_parallelism_cap(...) -> tuple[..., ...]: ...
    def resolve_quality_experiment_executor_mode(...) -> tuple[str, str]: ...
    def apply_wsl_quality_safety_guard(...) -> tuple[list[ResolvedExperiment], dict[str, Any]]: ...

In `cookimport/bench/qualitysuite/persistence.py`:

    def write_quality_run_checkpoint(...) -> None: ...
    def validate_resume_run_compatibility(...) -> None: ...
    def write_quality_experiment_result_snapshot(...) -> None: ...
    def load_quality_experiment_result_snapshot(...) -> dict[str, Any] | None: ...

In `cookimport/bench/qualitysuite/summary.py`:

    def summarize_experiment_report(...) -> dict[str, Any]: ...
    def build_summary_payload(...) -> dict[str, Any]: ...
    def format_quality_run_report(summary_payload: dict[str, Any]) -> str: ...

In `cookimport/bench/qualitysuite/worker_cli.py`:

    def build_worker_cli_parser() -> argparse.ArgumentParser: ...
    def main(argv: list[str] | None = None) -> int: ...

Use these as ownership targets, not rigid exact names if implementation reveals a clearer naming improvement. What matters is one obvious owner per responsibility cluster and a final state where the old giant file is no longer a broad import surface.

## Revision note

Created on 2026-03-22 as a follow-on AI-readiness plan after the initial CLI, shared planner, and run-settings plans. Updated later the same day to a burn-the-boats posture. This file owns only QualitySuite decomposition and now requires deletion of old helper exports from `quality_runner.py` rather than a long-lived compatibility facade.
